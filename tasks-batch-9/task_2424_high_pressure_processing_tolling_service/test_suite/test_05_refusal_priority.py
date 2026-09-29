"""When one request breaks two rules, which error comes back is a contract.

Both cases below book a pallet onto a chamber run that is doubly bad.  The first
pits a state precondition against a food-safety rule; the second pits a physical
quantity constraint against a commercial one.  In each case the lower-priority
violation is verified to be genuinely present, so the winner cannot be an accident.
"""

from test_helpers import (
    ApiErrorId,
    add_stored_pallet,
    api_client,
    create_cycle_load_payload,
    cycle_version,
    list_loads,
    read_contract,
    read_cycle,
    read_lot,
    read_qualification,
    run_day_close,
    set_clock,
    setup_exhausted_spot_contract_world,
    setup_running_cycle,
    validate_error,
)
from test_helpers.fixtures import SCHEDULER


# --------------------------------------------------------------------------- #
# tier 8 state beats tier 9 food safety
# --------------------------------------------------------------------------- #
def _running_cycle_with_expired_qualification() -> dict:
    """A RUNNING cycle, a second stored pallet, and a qualification aged out."""
    world = setup_running_cycle()
    world["lot2"] = add_stored_pallet(world, "PAL-002", 800)
    world["cycle_version_when_running"] = cycle_version(world["cycle"]["id"])
    set_clock("2027-08-04T08:00:00Z")
    run_day_close()
    return world


def test_the_running_cycle_reports_its_state_and_not_the_expired_qualification():
    """The chamber is already pressurised and the recipe has aged out; the 409 state
    refusal wins because state preconditions are checked one tier earlier.

    PRD 2.6: "Checks are grouped into fourteen ordered tiers, and the first tier
    that produces a violation determines the response."
    PRD 2.6: "**State preconditions.** The target row's lifecycle state permits the
    requested transition, and single-occurrence records have not already been
    written. These yield HTTP 409."
    PRD 3.5: "A booking against a cycle in any other state is refused with
    `ERR_INVALID_CYCLE_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_expired_qualification_on_load
    """
    world = _running_cycle_with_expired_qualification()

    response = api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot2"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=800,
            expected_cycle_version=world["cycle_version_when_running"],
        ),
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_QUALIFICATION_EXPIRED.value
    )


def test_the_expired_qualification_really_is_the_lower_priority_violation_present():
    """The day-close sweep did age the recipe out, so the food-safety rule the
    client was not told about is genuinely broken.

    PRD 2.6: "**Food-safety and compliance rules.** Qualification gates, cold-chain
    limits, segregation rules, chamber-target rules and the separation-of-duties
    rules. These outrank every capacity, uniqueness, scheduling and fiscal
    constraint below them."
    PRD 3.2: "The end-of-day sweep described in §3.9 moves any `QUALIFIED`
    qualification whose `expires_at` is at or before the logical clock to `EXPIRED`,
    incrementing its `version`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_expired_qualification_on_load
    """
    world = _running_cycle_with_expired_qualification()

    api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot2"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=800,
            expected_cycle_version=world["cycle_version_when_running"],
        ),
        SCHEDULER,
    )

    assert read_qualification(world["qualification"]["id"])["status"] == "EXPIRED"


def test_the_refused_booking_leaves_the_running_cycle_exactly_as_it_was():
    """A refusal writes nothing: the cycle keeps its state and its version, and no
    load row was created for the second pallet.

    PRD 2.4: "Most resources additionally carry an `updated_at` timestamp in the
    same format, refreshed on every mutation of that row, and a `version`, an
    integer that starts at 1 when the row is created and increments by exactly one
    on every mutation of that row — including mutations the client did not request
    directly but that a cascade produced."
    PRD 3.5: "Loads can be listed and filtered by `cycle_id`, `lot_id`,
    `contract_id`, `inspection_state` and `disposition_state`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_expired_qualification_on_load
    """
    world = _running_cycle_with_expired_qualification()

    api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot2"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=800,
            expected_cycle_version=world["cycle_version_when_running"],
        ),
        SCHEDULER,
    )
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["state"] == "RUNNING"
    assert cycle["version"] == world["cycle_version_when_running"]
    assert list_loads(lot_id=world["lot2"]["id"]) == []


# --------------------------------------------------------------------------- #
# tier 11 quantity beats tier 14 fiscal capacity
# --------------------------------------------------------------------------- #
def _exhausted_contract_and_a_second_pallet() -> dict:
    """The single-slot contract already EXHAUSTED, plus an 800-unit pallet stored."""
    world = setup_exhausted_spot_contract_world()
    world["lot2"] = add_stored_pallet(world, "PAL-002", 800)
    return world


def test_the_physical_shortage_is_reported_before_the_commercial_one():
    """Booking 5000 units out of an 800-unit pallet against a contract with no slots
    left reports the quantity constraint, three tiers above fiscal capacity.

    PRD 2.6: "**Instantaneous capacity and quantity constraints.** Basket capacity,
    untreated-unit availability, empty-chamber refusal, inspection arithmetic and the
    cold room's derived posture."
    PRD 3.5: "The pallet must have the units on hand: `units_loaded` must not exceed
    the pallet's `units_untreated`, or the refusal is
    `ERR_INSUFFICIENT_UNTREATED_UNITS` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/unit_shortage_beats_contract_exhaustion_on_load
    """
    world = _exhausted_contract_and_a_second_pallet()

    response = api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot2"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=5000,
            expected_cycle_version=cycle_version(world["cycle"]["id"]),
        ),
        SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_UNTREATED_UNITS.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_CONTRACT_CAPACITY_EXHAUSTED.value
    )


def test_the_fiscal_violation_really_is_present_underneath_the_quantity_one():
    """The spot contract has no slot to give, which is the refusal the client would
    have seen had the ladder run in the other order.

    PRD 2.6: "**Fiscal capacity.** Contract slot availability — always evaluated
    last, so a request that is both unsafe and unfunded reports the safety defect."
    PRD 3.3: "A live contract with no `available_slots` left is refused separately,
    and always last of all checks, with `ERR_CONTRACT_CAPACITY_EXHAUSTED` (HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/unit_shortage_beats_contract_exhaustion_on_load
    """
    world = _exhausted_contract_and_a_second_pallet()

    api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot2"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=5000,
            expected_cycle_version=cycle_version(world["cycle"]["id"]),
        ),
        SCHEDULER,
    )
    contract = read_contract(world["contract"]["id"])

    assert contract["status"] == "EXHAUSTED"
    assert contract["available_slots"] == 0


def test_the_refused_booking_leaves_the_pallet_and_the_chamber_untouched():
    """Neither the second pallet's untreated pool nor the chamber's basket count
    moved, so no partial effect of the refused booking survived.

    PRD 2.9: "The **unit ledger** on a pallet holds that `unit_count` always equals
    `units_untreated` plus `units_in_vessel` plus `units_treated` plus
    `units_disposed`, after every single request that touches the pallet."
    PRD 3.5: "`baskets_used_total` is the sum of `baskets_used` across the cycle's
    loads whose `disposition_state` is anything other than `VOIDED`, which is why a
    voided load lowers utilisation on the next recompute."

    Design: Difficulty/priority_pair_validation_conflict/unit_shortage_beats_contract_exhaustion_on_load
    """
    world = _exhausted_contract_and_a_second_pallet()

    api_client.create_cycle_load(
        world["cycle"]["id"],
        create_cycle_load_payload(
            world["lot2"]["id"],
            world["contract"]["id"],
            baskets_used=2,
            units_loaded=5000,
            expected_cycle_version=cycle_version(world["cycle"]["id"]),
        ),
        SCHEDULER,
    )
    lot2 = read_lot(world["lot2"]["id"])
    cycle = read_cycle(world["cycle"]["id"])

    assert lot2["units_untreated"] == 800
    assert lot2["custody_state"] == "IN_COLD_STORAGE"
    assert cycle["baskets_used_total"] == 2
    assert cycle["state"] == "LOADED"
