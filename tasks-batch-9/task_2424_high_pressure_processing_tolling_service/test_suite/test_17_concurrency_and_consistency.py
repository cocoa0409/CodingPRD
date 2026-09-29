"""Breadth over the concurrency guards and the consistency model.

The three optimistic-concurrency writes of §2.5 all share a shape: the transition
they guard is legitimate product behaviour, so no state check can catch a caller
working from an outdated read, and the expected-version field is the only guard.
Each is replayed from a stale view and then re-sent from a fresh one.  The last
test walks the other half of the model — every cascade of §2.9 is already visible
to the very next read, with no sweep and no retry.
"""

from test_helpers import (
    QM_CAROL,
    ApiErrorId,
    add_stored_pallet,
    api_client,
    create_cycle_load_payload,
    define_family,
    list_qualifications,
    make_customer_headers,
    qualify_recipe,
    read_cold_room,
    read_contract,
    read_cycle,
    read_lot,
    read_qualification,
    read_vessel,
    record_release_decision,
    register_customer,
    release_decision_payload,
    set_clock,
    setup_dispositioned_clean_cycle,
    setup_loaded_cycle,
    setup_scheduled_cycle,
    supersede_qualification,
    supersede_qualification_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    CLOCK_AUG03,
    OPERATOR,
    QUALITY,
    QUALITY_SECOND,
    SCHEDULER,
)


def test_a_second_load_written_against_the_pre_load_view_of_the_chamber_is_refused():
    """The first booking moved the cycle to version 2, so replaying version 1 is a 412 —
    and the very same payload succeeds once the scheduler re-reads the chamber.

    PRD 2.5: "Booking a load onto a vessel cycle requires `expected_cycle_version`,
    matching the target `VesselCycle`'s current `version`. Adding a second or third load
    to a cycle that is still `SCHEDULED` or `LOADED` is entirely legitimate product
    behaviour, so no state check can catch a scheduler who is working from an outdated
    picture of the chamber's basket occupancy and estimated fee; the version check is
    the guard. If `expected_cycle_version` does not equal the cycle's current `version`,
    the request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) and no load is
    created."
    PRD 3.5: "Chamber utilisation, `utilization_pct`, is 100 multiplied by the cycle's
    `baskets_used_total` and divided by the vessel's `basket_count`, rounded half up to
    two decimal places."
    PRD 3.5: "On the contract side, `reserved_slots` rises by one, which drops
    `available_slots` by one, and when the recomputed `available_slots` reaches zero the
    contract advances `ACTIVE → EXHAUSTED`."

    Design: Corner/cross-cutting complexity layers/corner_occc_stale_cycle_version_blocks_a_second_load
    """
    world = setup_loaded_cycle()
    second_pallet = add_stored_pallet(world, "PAL-002", 500)
    stale_payload = create_cycle_load_payload(
        second_pallet["id"], world["contract"]["id"], 1, 500, 1
    )

    refused = api_client.create_cycle_load(
        world["cycle"]["id"], stale_payload, SCHEDULER
    )

    validate_error(refused, ApiErrorId.ERR_STALE_CYCLE_VERSION.value, 412)
    assert read_cycle(world["cycle"]["id"])["baskets_used_total"] == 2
    assert read_contract(world["contract"]["id"])["reserved_slots"] == 1

    fresh = read_cycle(world["cycle"]["id"])
    assert fresh["version"] == 2

    validate_success(
        api_client.create_cycle_load(
            world["cycle"]["id"],
            create_cycle_load_payload(
                second_pallet["id"], world["contract"]["id"], 1, 500, fresh["version"]
            ),
            SCHEDULER,
        ),
        201,
    )

    loaded = read_cycle(world["cycle"]["id"])
    contract = read_contract(world["contract"]["id"])
    assert loaded["baskets_used_total"] == 3
    assert loaded["utilization_pct"] == 75.00
    assert loaded["version"] == 3
    assert contract["reserved_slots"] == 2
    assert contract["available_slots"] == 3


def test_a_release_written_before_the_hold_cannot_sign_the_pallet_out_afterwards():
    """Hold then release is a legal path, so only the version stops a `RELEASE` authored
    against the pre-hold pallet; re-reading it makes the identical decision stick.

    PRD 2.5: "Recording a quality release decision on a pallet requires
    `expected_lot_version`, matching that `Lot`'s current `version`. Because moving a
    pallet from `NOT_RELEASED` to `ON_HOLD_FOR_TEST` and then to `RELEASED` is a
    legitimate sequence, a second decision is not blocked by any release-state
    precondition — so the version check is what stops a `RELEASE` authored against a
    view of the pallet taken before another `QualityManager` placed it on
    microbiological hold. A mismatch is rejected with `ERR_STALE_LOT_VERSION`
    (HTTP 412)."
    PRD 3.9: "A `RELEASE` advances the pallet `NOT_RELEASED → RELEASED`, or
    `ON_HOLD_FOR_TEST → RELEASED` when it was on hold, in which case `hold_reason` is
    cleared to null. Either way `released_by_user_id` is stamped with the acting
    `X-User-ID`. A `HOLD_FOR_TEST` advances the pallet `NOT_RELEASED →
    ON_HOLD_FOR_TEST` and records the supplied `hold_reason`; this is the
    operator-driven counterpart of the automatic hold that a deviated chamber run
    applies."

    Design: Corner/cross-cutting complexity layers/corner_occ_stale_lot_version_blocks_a_release_authored_before_a_hold
    """
    world = setup_dispositioned_clean_cycle()
    pre_hold_version = read_lot(world["lot"]["id"])["version"]

    held = record_release_decision(
        world["lot"]["id"],
        "HOLD_FOR_TEST",
        QUALITY,
        expected_lot_version=pre_hold_version,
        hold_reason="micro plate pending",
    )
    assert held["release_state"] == "ON_HOLD_FOR_TEST"
    assert held["hold_reason"] == "micro plate pending"
    assert held["version"] == pre_hold_version + 1

    refused = api_client.record_release_decision(
        world["lot"]["id"],
        release_decision_payload("RELEASE", pre_hold_version),
        QUALITY_SECOND,
    )

    validate_error(refused, ApiErrorId.ERR_STALE_LOT_VERSION.value, 412)
    assert read_lot(world["lot"]["id"])["release_state"] == "ON_HOLD_FOR_TEST"
    assert read_lot(world["lot"]["id"])["version"] == pre_hold_version + 1

    released = validate_success(
        api_client.record_release_decision(
            world["lot"]["id"],
            release_decision_payload("RELEASE", pre_hold_version + 1),
            QUALITY_SECOND,
        ),
        200,
    )

    assert released["release_state"] == "RELEASED"
    assert released["hold_reason"] is None
    assert released["released_by_user_id"] == QM_CAROL
    assert released["version"] == pre_hold_version + 2


def test_a_second_revision_from_the_same_read_reports_the_version_not_the_state():
    """Replaying one read supersedes an already-superseded record, breaking both the
    version guard and the QUALIFIED-only gate — and the 412 of tier 7 is what answers.

    PRD 2.5: "Opening a revision of a qualified process recipe requires
    `expected_qualification_version`, matching the source `ProductQualification`'s
    current `version`. A revision legitimately supersedes the record it points at, so
    again no state precondition covers the write; the version check is what stops a
    customer from building a revision on top of a record that has since changed
    underneath it. A mismatch is rejected with `ERR_STALE_QUALIFICATION_VERSION`
    (HTTP 412)."
    PRD 2.6: "7. **Optimistic concurrency.** The expected-version field matches the
    parent's current `version`, as described in §2.5."
    PRD 2.6: "8. **State preconditions.** The target row's lifecycle state permits the
    requested transition, and single-occurrence records have not already been written.
    These yield HTTP 409."
    PRD 3.2: "Meanwhile the source record advances `QUALIFIED → SUPERSEDED` and its own
    `version` increments by one. The uniqueness rule on the customer, SKU and
    version-label triple applies to the new row exactly as it does to a fresh
    qualification. A revision attempted against a record that is not `QUALIFIED` is
    refused with `ERR_INVALID_QUALIFICATION_STATE`."
    PRD 3.2: "Qualifications can be listed and filtered by `customer_id`, by
    `product_family_id`, by `supersedes_qualification_id` — which is how a customer
    finds the revision chain behind a record — and by `status`."

    Design: Corner/cross-cutting complexity layers/corner_occ_stale_qualification_version_outranks_the_state_check
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    source = qualify_recipe(customer["id"], family["id"])
    source_version = source["version"]
    revision_b = supersede_qualification(
        source["id"], customer["id"], source_version, version_label="REV-B"
    )

    owner = make_customer_headers(customer["id"])
    refused = api_client.supersede_qualification(
        source["id"],
        supersede_qualification_payload(source_version, version_label="REV-C"),
        owner,
    )

    validate_error(refused, ApiErrorId.ERR_STALE_QUALIFICATION_VERSION.value, 412)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_QUALIFICATION_STATE.value
    )
    reread = read_qualification(source["id"], owner)
    assert reread["version"] == source_version + 1
    assert reread["status"] == "SUPERSEDED"

    chain = list_qualifications(supersedes_qualification_id=source["id"])
    assert len(chain) == 1
    assert chain[0]["id"] == revision_b["id"]
    assert chain[0]["version_label"] == "REV-B"


def test_every_parent_touched_by_a_write_is_already_correct_in_the_next_read():
    """Occupancy, the slot ledger, the machine's status and the pallet's unit ledger are
    all recomputed inside the writes that touch them, with nothing left for a sweep.

    PRD 2.9: "Cascades in this service are immediate and multi-level. A single request
    routinely mutates a chain of rows — a pallet's custody state moves, which changes a
    cold room's `occupied_pallets`, which flips that room's derived `capacity_state`; a
    load is created, which changes a contract's `reserved_slots`, which drops
    `available_slots`, which flips the contract's `status`. Each row touched in such a
    chain has its own `updated_at` refreshed and its own `version` incremented by one,
    including rows the caller never named."
    PRD 3.1: "The room's `capacity_state` is a derived posture with exactly two values —
    it is `AT_CAPACITY` whenever `occupied_pallets` is greater than or equal to
    `capacity_pallets`, and `NORMAL` otherwise — and it is recomputed after every
    request that changes the room's occupancy."
    PRD 3.5: "On the contract side, `reserved_slots` rises by one, which drops
    `available_slots` by one, and when the recomputed `available_slots` reaches zero the
    contract advances `ACTIVE → EXHAUSTED`."
    PRD 3.6: "A successful start stamps `started_at` with the logical clock, moves the
    vessel `AVAILABLE → IN_USE`, and for each loaded pallet advances `IN_COLD_STORAGE →
    IN_VESSEL` while moving that load's `units_loaded` out of `units_untreated` and into
    `units_in_vessel`."

    Design: Corner/consistency model/corner_every_cascade_is_visible_in_the_same_request
    """
    world = setup_scheduled_cycle()
    add_stored_pallet(world, "PAL-002", 500)

    room = read_cold_room(world["room"]["id"])
    assert room["occupied_pallets"] == 2
    assert room["capacity_state"] == "AT_CAPACITY"

    booked = validate_success(
        api_client.create_cycle_load(
            world["cycle"]["id"],
            create_cycle_load_payload(
                world["lot"]["id"],
                world["contract"]["id"],
                2,
                1000,
                world["cycle"]["version"],
            ),
            SCHEDULER,
        ),
        201,
    )
    contract = read_contract(world["contract"]["id"])
    assert booked["baskets_used"] == 2
    assert contract["reserved_slots"] == 1
    assert contract["available_slots"] == 4

    started = validate_success(api_client.start_cycle(world["cycle"]["id"], OPERATOR), 200)
    vessel = read_vessel(world["vessel"]["id"])
    lot = read_lot(world["lot"]["id"], QUALITY)

    assert started["state"] == "RUNNING"
    assert vessel["status"] == "IN_USE"
    assert lot["custody_state"] == "IN_VESSEL"
    assert lot["units_in_vessel"] == 1000
    assert lot["units_untreated"] == 0
