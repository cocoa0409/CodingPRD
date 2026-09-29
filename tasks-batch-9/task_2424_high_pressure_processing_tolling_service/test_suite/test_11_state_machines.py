"""Breadth over the lifecycles: edges that do not exist, edges that do, and their fallout.

A qualification cannot be re-submitted once it is qualified and a dispositioned run
cannot be cancelled after the fact; activation is not idempotent.  The edges that do
exist carry their whole cascade with them — the deviated branch parks pallets behind
a new deviation, a reprocess adjudication unwinds and re-bills in one call, and a
door refusal writes the pallet off without ever charging the cold room.
"""

from test_helpers import (
    QM_ALICE,
    ApiErrorId,
    adjudicate_deviation,
    api_client,
    assert_instant_equals,
    assert_unit_ledger_conserved,
    commission_vessel,
    define_family,
    inspect_at_dock,
    list_chargeback_lines,
    list_deviations,
    list_qualifications,
    open_active_contract,
    read_cold_room,
    read_contract,
    read_customer,
    read_cycle,
    read_deviation,
    read_load,
    read_lot,
    read_qualification,
    read_vessel,
    register_customer,
    setup_completed_deviated_cycle,
    setup_dispositioned_clean_cycle,
    setup_qualified_facility,
    setup_running_cycle,
    set_clock,
    supersede_qualification,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLOCK_AUG03, OPERATOR, QUALITY, SCHEDULER


def test_submitting_an_already_qualified_recipe_is_refused():
    """`QUALIFIED` has no submit edge at all, so the record does not move and no
    revision round is opened.

    PRD 3.2: "Submitting a qualification is the customer's act of handing it to the
    quality organisation. From `DRAFT` the qualification advances `DRAFT →
    SUBMITTED`, and the acting `X-User-ID` must be the qualification's own customer."
    PRD 3.2: "A qualification in any other status is refused with
    `ERR_INVALID_QUALIFICATION_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_submit_a_qualified_qualification_is_refused
    """
    world = setup_qualified_facility()
    assert world["qualification"]["status"] == "QUALIFIED"

    response = api_client.submit_qualification(
        world["qualification"]["id"], world["customer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_QUALIFICATION_STATE.value, 409)
    after = read_qualification(world["qualification"]["id"])
    assert after["status"] == "QUALIFIED"
    assert after["revision_round"] == 0


def test_a_freshly_scheduled_cycle_is_empty_yet_already_has_its_window():
    """No baskets are occupied and utilisation is 0.00, but the come-up derived from
    the pump's ramp rate has already fixed the 472-second occupancy window.

    PRD 3.5: "A new cycle opens at `SCHEDULED` with `baskets_used_total` at 0,
    `utilization_pct` at 0.0, both `started_at` and `dispositioned_at` null, and both
    `actual_cycle_seconds` and `actual_tolling_fee_cents` null."
    PRD 3.5: "Under the **ESTIMATED** variant used at scheduling time, come-up is the
    cycle's `target_pressure_mpa` divided by the vessel's
    `pump_ramp_rate_mpa_per_sec`, rounded up to a whole second, and hold is the
    cycle's `target_hold_seconds`; the result is stored as `estimated_cycle_seconds`."

    Design: Corner/state_machines/corner_new_cycle_starts_in_scheduled_with_zero_baskets
    """
    set_clock(CLOCK_AUG03)
    family = define_family()
    vessel = commission_vessel()

    cycle = validate_success(
        api_client.create_vessel_cycle(
            {
                "vessel_id": vessel["id"],
                "product_family_id": family["id"],
                "scheduled_start": "2026-08-05T09:00:00Z",
                "target_pressure_mpa": 600.0,
                "target_hold_seconds": 180,
            },
            SCHEDULER,
        ),
        201,
    )

    assert cycle["state"] == "SCHEDULED"
    assert cycle["baskets_used_total"] == 0
    assert cycle["utilization_pct"] == 0.00
    assert cycle["estimated_cycle_seconds"] == 472
    assert_instant_equals(cycle["scheduled_end"], "2026-08-05T09:07:52Z")
    assert cycle["actual_cycle_seconds"] is None
    assert cycle["actual_tolling_fee_cents"] is None
    assert cycle["started_at"] is None
    assert cycle["dispositioned_at"] is None
    assert cycle["version"] == 1


def test_terminating_a_dispositioned_cycle_is_refused_and_the_money_stands():
    """`DISPOSITIONED` is terminal, so a late cancellation cannot unwind the frozen
    fee or the load's allocation.

    PRD 3.6: "A termination attempted on a cycle that is not `SCHEDULED`, `LOADED` or
    `RUNNING` is refused with `ERR_INVALID_CYCLE_STATE`. `DISPOSITIONED`, `ABORTED`
    and `CANCELLED` are the cycle's three terminal states."
    PRD 3.8: "Alongside the fee, disposition advances the cycle to `DISPOSITIONED`,
    stamps `dispositioned_at` with the logical clock, and moves each participating
    load's `disposition_state` from `PENDING` to `ALLOCATED` — which, in slot-ledger
    terms, moves exactly one slot per load out of the contract's `reserved_slots` and
    into its `consumed_slots`, leaving `available_slots` unchanged."

    Design: Corner/state_machines/corner_terminate_a_dispositioned_cycle_is_refused
    """
    world = setup_dispositioned_clean_cycle()

    response = api_client.terminate_cycle(
        world["cycle"]["id"], {"reason": "late cancellation attempt"}, SCHEDULER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409)
    cycle = read_cycle(world["cycle"]["id"])
    load = read_load(world["load"]["id"])
    assert cycle["state"] == "DISPOSITIONED"
    assert cycle["actual_tolling_fee_cents"] == 12825
    assert load["disposition_state"] == "ALLOCATED"
    assert load["allocated_fee_cents"] == 12825


def test_activating_an_already_active_contract_is_refused_and_not_idempotent():
    """The second activation is a 409 rather than a silent no-op, and the ledger the
    first activation established is left exactly as it stands.

    PRD 3.3: "Activating a contract that is not `DRAFT` is refused with
    `ERR_INVALID_CONTRACT_STATE` (HTTP 409)."
    PRD 3.3: "Activation advances it `DRAFT → ACTIVE` and re-establishes that same
    opening ledger — `reserved_slots` and `consumed_slots` at zero and
    `available_slots` equal to `committed_slots` — making the slots bookable."

    Design: Corner/state_machines/corner_second_activate_on_an_active_contract_is_refused
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    contract = open_active_contract(customer["id"])
    assert contract["status"] == "ACTIVE"
    assert contract["version"] == 2

    response = api_client.activate_contract(contract["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_CONTRACT_STATE.value, 409)
    after = read_contract(contract["id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == 2
    assert after["available_slots"] == 5


def test_the_deviated_branch_fires_every_side_effect_in_one_request():
    """One CCP capture appends the record, closes the run as deviated, frees and
    counts the machine, moves the units to treated, and parks the pallet on hold
    behind a new open deviation.

    PRD 3.6: "Both branches share a common set of consequences: the immutable record
    is appended, the cycle's `actual_cycle_seconds` is taken from it, the vessel
    returns `IN_USE → AVAILABLE` and its `cycles_run_count` rises by one, and every
    loaded pallet advances `IN_VESSEL → TREATED`, moving its `units_in_vessel` into
    `units_treated`."
    PRD 3.6: "Second, every loaded pallet advances `NOT_RELEASED →
    ON_HOLD_FOR_TEST` with `hold_reason` recorded as `CCP deviation`."

    Design: Corner/state_machines/corner_deviation_branch_puts_every_loaded_lot_on_hold
    """
    world = setup_running_cycle()

    record = validate_success(
        api_client.create_cycle_log(
            world["cycle"]["id"],
            {
                "actual_pressure_mpa": 600.0,
                "actual_hold_seconds": 179,
                "come_up_seconds": 104,
                "water_temp_c": 7.5,
            },
            OPERATOR,
        ),
        201,
    )
    cycle = read_cycle(world["cycle"]["id"])
    lot = read_lot(world["lot"]["id"])
    deviations = list_deviations(cycle_id=world["cycle"]["id"])

    assert record["ccp_verdict"] == "DEVIATION"
    assert record["deviation_flags"] == ["SHORT_HOLD"]
    assert cycle["state"] == "COMPLETED_DEVIATED"
    assert cycle["actual_cycle_seconds"] == 475
    assert read_vessel(world["vessel"]["id"])["status"] == "AVAILABLE"
    assert read_vessel(world["vessel"]["id"])["cycles_run_count"] == 1
    assert lot["custody_state"] == "TREATED"
    assert lot["units_treated"] == 1000
    assert lot["units_in_vessel"] == 0
    assert lot["release_state"] == "ON_HOLD_FOR_TEST"
    assert lot["hold_reason"] == "CCP deviation"
    assert len(deviations) == 1
    assert deviations[0]["deviation_type"] == "SHORT_HOLD"
    assert deviations[0]["severity"] == "MAJOR"
    assert deviations[0]["worst_shortfall_pct"] == 0.56
    assert deviations[0]["status"] == "OPEN"
    assert deviations[0]["cycle_load_id"] is None


def test_reprocessing_a_deviation_bills_half_the_fee_and_returns_the_units():
    """A package root cause makes the customer liable: the run is priced and
    allocated, the load is marked reprocessed, half the fee is billed, and the pallet
    goes back to being bookable.

    PRD 3.7: "Where the deviation's `chargeback_party` is `CUSTOMER`, one chargeback
    line is minted per reprocessed load, with `basis` of `REPROCESS`, `deviation_id`
    pointing at this deviation, `customer_id` naming the charged customer, `status`
    of `PENDING`, and `amount_cents` equal to half the load's `allocated_fee_cents` —
    that is, the allocated fee multiplied by 0.50 and rounded half up to a whole
    cent."
    PRD 3.7: "And every referenced pallet is returned to the untreated pool: its
    `units_treated` moves back into `units_untreated`, its custody retreats `TREATED
    → IN_COLD_STORAGE`, and its release dimension retreats `ON_HOLD_FOR_TEST →
    NOT_RELEASED` with `hold_reason` cleared to null, so the pallet is eligible to be
    booked onto a fresh chamber run."

    Design: Corner/state_machines/corner_reprocess_adjudication_returns_units_and_bills_the_customer
    """
    world = setup_completed_deviated_cycle(actual_hold_seconds=179)

    adjudicate_deviation(
        world["deviation"]["id"], "REPROCESS", root_cause_code="PKG_FILM_SPEC"
    )
    deviation = read_deviation(world["deviation"]["id"])
    cycle = read_cycle(world["cycle"]["id"])
    load = read_load(world["load"]["id"])
    lines = list_chargeback_lines(customer_id=world["customer"]["id"])
    lot = read_lot(world["lot"]["id"])

    assert deviation["status"] == "ADJUDICATED_REPROCESS"
    assert deviation["chargeback_party"] == "CUSTOMER"
    assert deviation["adjudicated_by_user_id"] == QM_ALICE
    assert cycle["state"] == "DISPOSITIONED"
    assert cycle["actual_tolling_fee_cents"] == 11400
    assert load["disposition_state"] == "REPROCESSED"
    assert load["allocated_fee_cents"] == 11400
    assert len(lines) == 1
    assert lines[0]["basis"] == "REPROCESS"
    assert lines[0]["amount_cents"] == 5700
    assert lines[0]["status"] == "PENDING"
    assert lines[0]["deviation_id"] == world["deviation"]["id"]
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 5700
    assert lot["units_untreated"] == 1000
    assert lot["units_treated"] == 0
    assert lot["custody_state"] == "IN_COLD_STORAGE"
    assert lot["release_state"] == "NOT_RELEASED"
    assert lot["hold_reason"] is None
    assert_unit_ledger_conserved(lot)
    contract = read_contract(world["contract"]["id"])
    assert contract["consumed_slots"] == 1
    assert contract["reserved_slots"] == 0
    assert contract["available_slots"] == 4


def test_refusing_a_pallet_at_the_door_disposes_it_without_charging_the_room():
    """Every unit goes straight from untreated to disposed, and because the pallet
    never took a position the room's occupancy never moves.

    PRD 3.4: "A `REJECT` outcome refuses the pallet at the door: it advances `AT_DOCK
    → REJECTED_AT_DOCK`, moves every unit from `units_untreated` into
    `units_disposed`, and makes **no** change to cold-room occupancy, because a
    refused pallet never took a position."
    PRD 3.1: "`occupied_pallets` is not a free-running counter: it is the number of
    pallets assigned to this room whose `custody_state` is `IN_COLD_STORAGE`,
    `IN_VESSEL` or `TREATED`."

    Design: Corner/state_machines/corner_inspect_reject_at_the_dock_disposes_the_whole_pallet
    """
    world = setup_qualified_facility()
    lot = validate_success(
        api_client.create_lot(
            {
                "customer_id": world["customer"]["id"],
                "qualification_id": world["qualification"]["id"],
                "cold_room_id": world["room"]["id"],
                "pallet_ref": "PAL-001",
                "unit_count": 1000,
                "gross_weight_kg": 640.0,
                "carrier_temp_c": 2.5,
                "ship_by": "2026-08-20T00:00:00Z",
            },
            OPERATOR,
        ),
        201,
    )

    inspect_at_dock(lot["id"], "REJECT", pulp_temp_c=3.9)
    after = read_lot(lot["id"])
    room = read_cold_room(world["room"]["id"])

    assert after["custody_state"] == "REJECTED_AT_DOCK"
    assert after["units_disposed"] == 1000
    assert after["units_untreated"] == 0
    assert_unit_ledger_conserved(after)
    assert room["occupied_pallets"] == 0
    assert room["capacity_state"] == "NORMAL"


def test_superseding_a_qualified_recipe_mints_a_draft_and_retires_the_source():
    """One call walks the self-referential edge: the new DRAFT points back at the
    source, inherits the customer and the family it was never sent, and the source
    retires.

    PRD 3.2: "The result is a brand-new `DRAFT` qualification whose
    `supersedes_qualification_id` points at the source record, inheriting the
    source's `customer_id` and `product_family_id`, with its own suitability score
    computed at creation; that new row is what the response returns, with a 201."
    PRD 3.2: "Meanwhile the source record advances `QUALIFIED → SUPERSEDED` and its
    own `version` increments by one."

    Design: Corner/state_machines/corner_supersede_mints_a_draft_and_retires_the_source
    """
    world = setup_qualified_facility()
    source = world["qualification"]

    revision = supersede_qualification(
        source["id"],
        world["customer"]["id"],
        source["version"],
        version_label="REV-B",
    )

    assert revision["status"] == "DRAFT"
    assert revision["revision_round"] == 0
    assert revision["supersedes_qualification_id"] == source["id"]
    assert revision["customer_id"] == world["customer"]["id"]
    assert revision["product_family_id"] == world["family"]["id"]
    assert revision["package_suitability_score"] == 100.00
    assert read_qualification(source["id"])["status"] == "SUPERSEDED"
    assert len(list_qualifications(supersedes_qualification_id=source["id"])) == 1


def test_accepting_a_critical_deviation_is_never_permitted():
    """A 170-second hold against a required 180 is 5.56 percent short, over the
    critical line, and a critical process failure may not be waved through.

    PRD 3.7: "Next, an `ACCEPT` is refused outright when the deviation's `severity`
    is `CRITICAL` — a critical process failure may never be waved through — with
    `ERR_DEVIATION_ACCEPT_NOT_PERMITTED` (HTTP 422)."
    PRD 3.6: "The largest of those three percentages becomes the deviation's
    `worst_shortfall_pct`, and its `severity` is `CRITICAL` when that figure is at
    least 5.00 percent and `MAJOR` otherwise."

    Design: Corner/state_machines/corner_accept_on_a_critical_deviation_is_refused
    """
    world = setup_completed_deviated_cycle(actual_hold_seconds=170)

    response = api_client.adjudicate_deviation(
        world["deviation"]["id"],
        {"disposition": "ACCEPT", "root_cause_code": "EQUIP_PUMP_FAULT"},
        QUALITY,
    )

    validate_error(
        response, ApiErrorId.ERR_DEVIATION_ACCEPT_NOT_PERMITTED.value, 422
    )
    deviation = read_deviation(world["deviation"]["id"])
    assert deviation["severity"] == "CRITICAL"
    assert deviation["worst_shortfall_pct"] == 5.56
    assert deviation["status"] == "OPEN"
    assert read_cycle(world["cycle"]["id"])["state"] == "COMPLETED_DEVIATED"
