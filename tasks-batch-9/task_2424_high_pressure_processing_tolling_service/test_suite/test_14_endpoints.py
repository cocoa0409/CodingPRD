"""Breadth over the endpoint surface: CRUD, action endpoints, bulk sweeps, reads.

Reference data is create-read-update only; the interesting endpoints are the action
ones, which take an empty body and earn their keep entirely through side effects —
opening a slot ledger, linking three parents in one write, sweeping every stale
recipe at once, or freezing a settlement.  The read endpoints are checked for the
derived figures they are supposed to expose.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    commission_vessel,
    create_qualification_payload,
    define_family,
    inspect_load,
    list_chargeback_lines,
    make_customer_headers,
    qualify_recipe,
    read_contract,
    read_customer,
    read_cycle,
    read_load,
    read_qualification,
    register_customer,
    run_day_close,
    setup_dispositioned_clean_cycle,
    setup_scheduled_cycle,
    set_clock,
    validate_success,
    validate_error,
    write_contract,
    assert_instant_equals,
    append_acceptable_runs,
    decide_qualification,
    submit_qualification,
)
from test_helpers.fixtures import ADMIN, CLOCK_AUG03, OPERATOR, SCHEDULER


def test_a_vessel_round_trips_through_create_read_and_a_status_patch():
    """The machine reads back exactly as commissioned with an untouched run counter,
    and the maintenance patch moves nothing but the status and the version.

    PRD 3.1: "A new vessel is `AVAILABLE` with `cycles_run_count` at 0."
    PRD 3.1: "A `FacilityAdmin` may take a machine out of service or return it to
    service by supplying a new `status`, but only `AVAILABLE`, `MAINTENANCE` or `DOWN`
    may be supplied that way — `IN_USE` is reserved for the system, which sets it when
    a chamber run begins and clears it when the run ends."

    Design: Corner/endpoints/corner_vessel_create_read_and_status_patch_round_trip
    """
    set_clock(CLOCK_AUG03)
    vessel = commission_vessel()

    fresh = validate_success(api_client.get_vessel(vessel["id"], ADMIN), 200)
    patched = validate_success(
        api_client.patch_vessel(vessel["id"], {"status": "MAINTENANCE"}, ADMIN), 200
    )
    reread = validate_success(api_client.get_vessel(vessel["id"], OPERATOR), 200)

    assert fresh["vessel_code"] == "HPP-1"
    assert fresh["basket_count"] == 4
    assert fresh["max_pressure_mpa"] == 600.0
    assert fresh["pump_ramp_rate_mpa_per_sec"] == 6.0
    assert fresh["decompression_seconds"] == 12
    assert fresh["hourly_operating_cost_cents"] == 90000
    assert fresh["status"] == "AVAILABLE"
    assert fresh["cycles_run_count"] == 0
    assert fresh["version"] == 1
    assert patched["status"] == "MAINTENANCE"
    assert reread["version"] == 2
    assert reread["basket_count"] == 4
    assert reread["cycles_run_count"] == 0
    assert reread["vessel_code"] == "HPP-1"


def test_the_activate_action_endpoint_opens_the_slot_ledger_and_nothing_else():
    """An empty body turns a draft into bookable capacity: five committed slots become
    five available ones, with the settlement figures still at zero.

    PRD 3.3: "Activation advances it `DRAFT → ACTIVE` and re-establishes that same
    opening ledger — `reserved_slots` and `consumed_slots` at zero and
    `available_slots` equal to `committed_slots` — making the slots bookable."
    PRD 3.3: "A contract is written as a `DRAFT` with `reserved_slots` at 0,
    `consumed_slots` at 0, `available_slots` equal to `committed_slots`, and both
    `shortfall_slots` and `take_or_pay_cents` at 0."

    Design: Corner/endpoints/corner_activate_action_endpoint_initialises_the_slot_ledger
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    contract = write_contract(customer["id"])
    assert contract["status"] == "DRAFT"

    activated = validate_success(
        api_client.activate_contract(contract["id"], ADMIN), 200
    )

    assert activated["status"] == "ACTIVE"
    assert activated["reserved_slots"] == 0
    assert activated["consumed_slots"] == 0
    assert activated["available_slots"] == 5
    assert activated["shortfall_slots"] == 0
    assert activated["take_or_pay_cents"] == 0
    assert activated["version"] == 2


def test_one_day_close_call_expires_every_stale_recipe_and_reports_the_counts():
    """Both recipes were qualified on the same instant, so both age out together, and
    the sweep answers with its counts rather than one row at a time.

    PRD 3.2: "A qualification that clears all four gates advances `UNDER_VALIDATION →
    QUALIFIED`, stamps `qualified_at` with the logical clock instant of the decision,
    and sets `expires_at` to exactly 365 days after `qualified_at`."
    PRD 3.9: "It expires stale process recipes, advancing every `QUALIFIED`
    qualification whose `expires_at` is at or before the logical clock to `EXPIRED` and
    incrementing each one's `version`."
    PRD 3.9: "The sweep reports `expired_qualification_count`, the number of
    qualifications it moved to `EXPIRED`; `customers_rescored`, the number of customers
    whose trailing rate it recomputed; and `closed_at`, the logical clock instant at
    which the sweep ran."

    Design: Corner/endpoints/corner_day_close_sweep_expires_every_stale_qualification_at_once
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    first = qualify_recipe(customer["id"], family["id"])
    second = validate_success(
        api_client.create_qualification(
            create_qualification_payload(
                customer["id"], family["id"], sku_code="SOUP-300"
            ),
            make_customer_headers(customer["id"]),
        ),
        201,
    )
    submit_qualification(second["id"], customer["id"])
    append_acceptable_runs(second["id"], how_many=2)
    decide_qualification(second["id"], "QUALIFY")
    assert_instant_equals(first["expires_at"], "2027-08-03T08:00:00Z")
    assert_instant_equals(
        read_qualification(second["id"])["expires_at"], "2027-08-03T08:00:00Z"
    )

    set_clock("2027-08-04T08:00:00Z")
    report = run_day_close()

    assert report["expired_qualification_count"] == 2
    assert report["customers_rescored"] == 1
    assert_instant_equals(report["closed_at"], "2027-08-04T08:00:00Z")
    assert read_qualification(first["id"])["status"] == "EXPIRED"
    assert read_qualification(second["id"])["status"] == "EXPIRED"
    assert read_customer(customer["id"])["trailing_leaker_ppm"] == 0


def test_the_load_endpoint_links_three_parents_and_moves_two_of_them():
    """One write mints the junction, turns the chamber run LOADED with a tightened
    estimate, and reserves a slot on the contract behind it.

    PRD 3.5: "A successful booking creates the load with `disposition_state` of
    `PENDING`, `inspection_state` of `PENDING_INSPECTION`, `allocated_fee_cents` null,
    `units_inspected`, `leaker_units`, `leaker_ppm` and `chargeback_party` all null,
    and `chargeback_cents` at 0."
    PRD 3.5: "The cycle's `baskets_used_total`, `utilization_pct`,
    `estimated_cycle_seconds`, `estimated_tolling_fee_cents` and `scheduled_end` are
    all recomputed under the ESTIMATED variant, so each booking tightens the estimate
    as the chamber fills."
    PRD 3.5: "On the contract side, `reserved_slots` rises by one, which drops
    `available_slots` by one, and when the recomputed `available_slots` reaches zero
    the contract advances `ACTIVE → EXHAUSTED`."

    Design: Corner/endpoints/corner_load_endpoint_links_lot_cycle_and_contract_in_one_write
    """
    world = setup_scheduled_cycle()

    load = validate_success(
        api_client.create_cycle_load(
            world["cycle"]["id"],
            {
                "lot_id": world["lot"]["id"],
                "contract_id": world["contract"]["id"],
                "baskets_used": 2,
                "units_loaded": 1000,
                "expected_cycle_version": world["cycle"]["version"],
            },
            SCHEDULER,
        ),
        201,
    )
    cycle = read_cycle(world["cycle"]["id"])
    contract = read_contract(world["contract"]["id"])

    assert load["cycle_id"] == world["cycle"]["id"]
    assert load["lot_id"] == world["lot"]["id"]
    assert load["contract_id"] == world["contract"]["id"]
    assert load["disposition_state"] == "PENDING"
    assert load["inspection_state"] == "PENDING_INSPECTION"
    assert load["allocated_fee_cents"] is None
    assert cycle["state"] == "LOADED"
    assert cycle["baskets_used_total"] == 2
    assert cycle["utilization_pct"] == 50.00
    assert cycle["estimated_tolling_fee_cents"] == 11400
    assert contract["reserved_slots"] == 1
    assert contract["consumed_slots"] == 0
    assert contract["available_slots"] == 4
    assert contract["status"] == "ACTIVE"


def test_the_customer_read_shows_a_swept_risk_rate_with_an_untouched_balance():
    """Two leakers in a thousand is 2000 ppm — above the watch line, below the
    chargeback line — so the facility absorbs it and only the risk rate moves.

    PRD 3.8: "When the party is `FACILITY`, the load's `chargeback_cents` is 0, no
    chargeback line is created, and the customer's `chargeback_balance_cents` is
    unchanged."
    PRD 3.9: "When that population is empty the customer's `trailing_leaker_ppm` is 0;
    otherwise it is one million multiplied by the sum of `leaker_units` across the
    population, divided by the sum of `units_inspected` across the same population,
    rounded half up to a whole part per million."

    Design: Corner/endpoints/corner_customer_read_exposes_the_derived_risk_and_balance
    """
    world = setup_dispositioned_clean_cycle()
    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=2)
    inspected = read_load(world["load"]["id"])
    assert inspected["leaker_ppm"] == 2000
    assert inspected["inspection_state"] == "INSPECTED"
    assert inspected["chargeback_party"] == "FACILITY"
    assert list_chargeback_lines(customer_id=world["customer"]["id"]) == []

    set_clock("2026-08-03T20:00:00Z")
    report = run_day_close()
    customer = validate_success(
        api_client.get_customer(world["customer"]["id"], ADMIN), 200
    )

    assert report["customers_rescored"] == 1
    assert customer["trailing_leaker_ppm"] == 2000
    assert customer["chargeback_balance_cents"] == 0


def test_closing_a_contract_is_only_possible_once_it_has_been_activated():
    """A draft cannot be settled; the same call on the activated contract freezes a
    four-slot shortfall worth 240000 cents.

    PRD 3.3: "Settlement happens once, when a `FacilityAdmin` closes the contract from
    either `ACTIVE` or `EXHAUSTED`; closing from `DRAFT` or `CLOSED` is refused with
    `ERR_INVALID_CONTRACT_STATE`."
    PRD 3.3: "`take_or_pay_cents` is `shortfall_slots` multiplied by
    `slot_take_or_pay_cents`."

    Design: Corner/endpoints/corner_close_is_only_available_from_an_open_contract
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    contract = write_contract(customer["id"])

    refused = api_client.close_contract(contract["id"], ADMIN)
    validate_error(refused, ApiErrorId.ERR_INVALID_CONTRACT_STATE.value, 409)
    assert read_contract(contract["id"])["status"] == "DRAFT"

    api_client.activate_contract(contract["id"], ADMIN)
    settled = validate_success(api_client.close_contract(contract["id"], ADMIN), 200)
    lines = list_chargeback_lines(customer_id=customer["id"])

    assert settled["status"] == "CLOSED"
    assert settled["shortfall_slots"] == 4
    assert settled["take_or_pay_cents"] == 240000
    assert len(lines) == 1
    assert lines[0]["basis"] == "TAKE_OR_PAY_SHORTFALL"
    assert lines[0]["amount_cents"] == 240000
    assert read_customer(customer["id"])["chargeback_balance_cents"] == 240000
