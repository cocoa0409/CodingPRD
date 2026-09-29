"""Sometimes nothing is wrong with the row you named.

A pallet's release is blocked by a deviation reached only through its load and its
chamber run, and the identical request succeeds unchanged once that sibling row is
adjudicated.  A chamber start is blocked by the machine's own status, set by an
unrelated administrator, and succeeds once the machine comes back into service.
"""

from test_helpers import (
    QM_CAROL,
    ApiErrorId,
    adjudicate_deviation,
    api_client,
    assert_instant_equals,
    first_deviation_on_load,
    patch_vessel_status,
    read_cycle,
    read_deviation,
    read_lot,
    read_vessel,
    record_release_decision,
    release_decision_payload,
    setup_inspected_load,
    setup_loaded_cycle,
    start_cycle,
    validate_error,
)
from test_helpers.fixtures import OPERATOR, QUALITY_SECOND, QUALITY_THIRD


# --------------------------------------------------------------------------- #
# Lot release gated by a Deviation two aggregates away
# --------------------------------------------------------------------------- #
def test_the_open_package_deviation_blocks_a_release_the_pallet_itself_permits():
    """The pallet is TREATED and NOT_RELEASED, which the release rules allow; the
    refusal comes from a deviation reached through its load and its chamber run.

    PRD 3.9: "Two further gates protect a release, and their order is fixed. First,
    no deviation on the pallet's cycle may still be `OPEN`, or the decision is
    refused with `ERR_DEVIATION_UNRESOLVED`."
    PRD 3.8: "Because that deviation is open, it blocks the release of **every**
    pallet on that cycle until it has been adjudicated — and because its
    `cycle_load_id` is not null, the only disposition available to the adjudicating
    manager is `ACCEPT`."

    Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_open_deviation_on_its_cycle
    """
    world = setup_inspected_load()
    assert world["lot"]["custody_state"] == "TREATED"
    assert world["lot"]["release_state"] == "NOT_RELEASED"

    response = api_client.record_release_decision(
        world["lot"]["id"],
        release_decision_payload("RELEASE", world["lot"]["version"]),
        QUALITY_SECOND,
    )

    validate_error(response, ApiErrorId.ERR_DEVIATION_UNRESOLVED.value, 409)
    after = read_lot(world["lot"]["id"])
    assert after["release_state"] == "NOT_RELEASED"
    assert after["version"] == world["lot"]["version"]


def test_accepting_the_package_deviation_unblocks_the_identical_request():
    """Adjudicating the sibling row changes nothing on the pallet, yet the same
    release call now succeeds and stamps the acting manager.

    PRD 3.7: "An `ACCEPT` advances the deviation `OPEN → ADJUDICATED_ACCEPT` and does
    nothing else. No pallet moves, no fee is computed, no chargeback line is minted;
    the cycle still has to be dispositioned separately by a `QualityManager` as
    described in §3.8."
    PRD 3.9: "A `RELEASE` advances the pallet `NOT_RELEASED → RELEASED`, or
    `ON_HOLD_FOR_TEST → RELEASED` when it was on hold, in which case `hold_reason` is
    cleared to null. Either way `released_by_user_id` is stamped with the acting
    `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_open_deviation_on_its_cycle
    """
    world = setup_inspected_load()
    deviation = first_deviation_on_load(world["load"]["id"])

    adjudicate_deviation(
        deviation["id"],
        "ACCEPT",
        root_cause_code="PKG_SEAL_SUPPLIER",
        headers=QUALITY_THIRD,
    )
    record_release_decision(world["lot"]["id"], "RELEASE", headers=QUALITY_SECOND)

    assert read_deviation(deviation["id"])["status"] == "ADJUDICATED_ACCEPT"
    lot = read_lot(world["lot"]["id"])
    assert lot["release_state"] == "RELEASED"
    assert lot["released_by_user_id"] == QM_CAROL


def test_the_deviation_only_ever_gated_the_release_dimension():
    """Neither the block nor its lifting touched custody: the pallet stayed TREATED
    throughout, and the accepted deviation is the package-failure one.

    PRD 3.8: "A load at or above 3,000 ppm additionally raises a fresh `Deviation` at
    `OPEN`, with `deviation_type` of `PACKAGE_FAILURE_RATE`, `severity` of `MAJOR`,
    `worst_shortfall_pct` of 0.00, `cycle_load_id` pointing at this load and
    `cycle_log_id` null."
    PRD 3.4: "Pallets are read back with both state dimensions and the full unit
    ledger visible, and can be listed and filtered by `customer_id`,
    `qualification_id`, `cold_room_id`, `custody_state` and `release_state` — the two
    state dimensions being independently filterable precisely because they evolve
    independently."

    Design: Difficulty/cross_entity_state_dependency/lot_release_blocked_by_open_deviation_on_its_cycle
    """
    world = setup_inspected_load()
    deviation = first_deviation_on_load(world["load"]["id"])
    assert deviation["deviation_type"] == "PACKAGE_FAILURE_RATE"

    adjudicate_deviation(
        deviation["id"],
        "ACCEPT",
        root_cause_code="PKG_SEAL_SUPPLIER",
        headers=QUALITY_THIRD,
    )
    record_release_decision(world["lot"]["id"], "RELEASE", headers=QUALITY_SECOND)

    assert read_lot(world["lot"]["id"])["custody_state"] == "TREATED"


# --------------------------------------------------------------------------- #
# VesselCycle start gated by the Vessel's own status
# --------------------------------------------------------------------------- #
def test_a_machine_taken_out_of_service_refuses_a_perfectly_good_start():
    """The cycle is LOADED with a compliant recipe, but the administrator's
    maintenance patch is what the operator hears about.

    PRD 3.6: "The vessel's `status` must be `AVAILABLE`; a machine that is `IN_USE`,
    in `MAINTENANCE` or `DOWN` refuses the start with `ERR_VESSEL_NOT_AVAILABLE`
    (HTTP 422)."
    PRD 3.1: "A `FacilityAdmin` may take a machine out of service or return it to
    service by supplying a new `status`, but only `AVAILABLE`, `MAINTENANCE` or `DOWN`
    may be supplied that way — `IN_USE` is reserved for the system, which sets it when
    a chamber run begins and clears it when the run ends."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_blocked_by_vessel_maintenance_status
    """
    world = setup_loaded_cycle()
    patch_vessel_status(world["vessel"]["id"], "MAINTENANCE")

    response = api_client.start_cycle(world["cycle"]["id"], OPERATOR)

    validate_error(response, ApiErrorId.ERR_VESSEL_NOT_AVAILABLE.value, 422)
    assert read_cycle(world["cycle"]["id"])["state"] == "LOADED"
    assert read_lot(world["lot"]["id"])["custody_state"] == "IN_COLD_STORAGE"


def test_returning_the_machine_to_service_lets_the_same_start_through():
    """Patching the vessel back to `AVAILABLE` is the only change, and the start now
    stamps the logical clock and takes the machine back out of the pool.

    PRD 3.6: "A successful start stamps `started_at` with the logical clock, moves the
    vessel `AVAILABLE → IN_USE`, and for each loaded pallet advances
    `IN_COLD_STORAGE → IN_VESSEL` while moving that load's `units_loaded` out of
    `units_untreated` and into `units_in_vessel`."
    PRD 3.6: "Pressurising the chamber is a `PlantOperator` act and takes no request
    body at all. It advances the cycle `LOADED → RUNNING`."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_blocked_by_vessel_maintenance_status
    """
    world = setup_loaded_cycle()
    patch_vessel_status(world["vessel"]["id"], "MAINTENANCE")
    api_client.start_cycle(world["cycle"]["id"], OPERATOR)

    patch_vessel_status(world["vessel"]["id"], "AVAILABLE")
    start_cycle(world["cycle"]["id"])
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["state"] == "RUNNING"
    assert_instant_equals(cycle["started_at"], "2026-08-03T08:00:00Z")
    assert read_vessel(world["vessel"]["id"])["status"] == "IN_USE"


def test_the_successful_start_moves_the_pallets_units_into_the_chamber():
    """The dependency runs the other way once satisfied: starting the run empties the
    pallet's untreated pool into the in-vessel bucket.

    PRD 2.9: "Every later movement is a transfer between two of the four buckets and
    never a creation or destruction of units."
    PRD 3.6: "Finally every loaded pallet must still be sitting in cold storage with
    `custody_state` of `IN_COLD_STORAGE`."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_blocked_by_vessel_maintenance_status
    """
    world = setup_loaded_cycle()
    patch_vessel_status(world["vessel"]["id"], "MAINTENANCE")
    api_client.start_cycle(world["cycle"]["id"], OPERATOR)
    patch_vessel_status(world["vessel"]["id"], "AVAILABLE")

    start_cycle(world["cycle"]["id"])
    lot = read_lot(world["lot"]["id"])

    assert lot["custody_state"] == "IN_VESSEL"
    assert lot["units_in_vessel"] == 1000
    assert lot["units_untreated"] == 0
