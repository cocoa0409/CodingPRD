"""What a freshly opened row reads, what the first real transition writes, and what a
trigger fired from a state that does not offer it leaves behind.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_customer_headers,
    declare_tl_140, register_customer, register_machine, register_permit,
    setup_available_lot, setup_approved_batch, queue_batch, submit_order,
    log_reading, fiber_balance, furnish_line, sublot, create_run_payload,
    machine_version,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]
LAB = TEST_USERS["lab_headers"]

TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def _queued_batch_against_a_twenty_two_ton_lot(tons_charged):
    """A single AVAILABLE lot of 22.00 tons at 2.00 contamination, one QUEUED batch."""
    declare_tl_140()
    bundle = setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT)
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], tons_charged)])
    return bundle["lot"], batch


def _lot_now(lot_id):
    return get_success_data(api_client.get_inventory_lot(lot_id, OPERATOR))


def test_a_newly_scheduled_run_opens_on_both_axes_at_once():
    """PRD §3.4: "Scheduling a run is a planner act that creates the run in `run_status`
    of `SCHEDULED` and `quality_status` of `PENDING`."
    PRD §3.5: "A production run carries **two status axes that advance independently**."
    PRD §3.5: "A run's `produced_tons` is at all times the sum of `net_tons` over its roll
    sets whose status is anything other than `REWOUND`, rounded to three decimal places."

    Design: Corner/state_machines/production_run_initial_state_is_scheduled_on_both_axes
    """
    machine = register_machine(name="PM1", wire_width_mm=5600, max_tons_per_hour=20.00,
                               changeover_buffer_minutes=30, steam_tph_per_ton=2.500)
    bundle = setup_approved_batch(tons_charged=20.000, measured_reject_tons=2.000)
    assert bundle["batch"]["final_accepted_tons"] == pytest.approx(18.000, abs=1e-6)

    response = api_client.create_run(machine["id"], create_run_payload(
        "TL_140", bundle["batch"]["id"], machine_version(machine["id"]),
        pulp_draw_tons=15.000), PLANNER)
    run = validate_success(response, 201)

    assert run["run_status"] == "SCHEDULED"
    assert run["quality_status"] == "PENDING"
    assert run["machine_id"] == machine["id"]
    assert run["produced_tons"] == pytest.approx(0.000, abs=1e-6)
    assert run["provisional_quality_index"] is None
    assert run["certified_quality_index"] is None
    assert run["off_spec_reel_count"] == 0
    assert run["started_by_user_id"] is None
    assert run["certified_by_user_id"] is None


def test_charging_the_pulper_moves_the_lot_ledger_and_pins_the_book_projection():
    """PRD §3.3: "Charging the pulper moves the batch `QUEUED → PULPING` and is the point
    at which fiber actually leaves inventory."
    PRD §3.3: "As side effects of the charge, each furnish line's `tons_charged` is added
    into its lot's `tons_consumed`, each affected lot's `tons_available` is recomputed,
    and any lot whose recomputed `tons_available` lands on exactly 0.000 flips from
    `AVAILABLE` to `DEPLETED`."
    PRD §2.9: "That imbalance must read exactly zero at every point at which it can be
    observed, including immediately after a pulp batch cancellation releases a
    reservation and immediately after an aborted run returns its drawn pulp."

    Design: Corner/state_machines/pulp_batch_start_reserves_furnish_tonnage_and_pins_provisional_yield
    """
    lot, batch = _queued_batch_against_a_twenty_two_ton_lot(20.000)

    charged = get_success_data(api_client.start_pulp_batch(batch["id"], OPERATOR))
    assert charged["status"] == "PULPING"
    assert charged["charged_tons"] == pytest.approx(20.000, abs=1e-6)
    assert charged["blend_contamination_pct"] == pytest.approx(2.000, abs=1e-6)
    assert charged["provisional_accepted_tons"] == pytest.approx(16.880, abs=1e-6)
    assert charged["final_accepted_tons"] is None

    after = _lot_now(lot["id"])
    assert after["tons_received"] == pytest.approx(22.00, abs=1e-6)
    assert after["tons_consumed"] == pytest.approx(20.000, abs=1e-6)
    assert after["tons_available"] == pytest.approx(2.000, abs=1e-6)
    assert after["status"] == "AVAILABLE"

    balance = fiber_balance()
    assert balance["total_received_tons"] == pytest.approx(22.000, abs=1e-6)
    assert balance["total_consumed_tons"] == pytest.approx(20.000, abs=1e-6)
    assert balance["total_available_tons"] == pytest.approx(2.000, abs=1e-6)
    assert balance["imbalance_tons"] == pytest.approx(0.000, abs=1e-6)


def test_a_charge_three_tons_over_the_lot_writes_nothing_at_all():
    """PRD §3.3: "Each line's `tons_charged` must be covered by that lot's
    `tons_available`, with the boundary inclusive so charging exactly the remaining
    tonnage is allowed; charging more is rejected with `ERR_INSUFFICIENT_FIBER` (HTTP
    409)."
    PRD §3.3: "The charge itself pins three computed figures."

    Design: Corner/state_machines/pulp_batch_start_over_available_tonnage_returns_insufficient_fiber
    """
    lot, batch = _queued_batch_against_a_twenty_two_ton_lot(25.000)

    response = api_client.start_pulp_batch(batch["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FIBER.value, 409)

    still = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert still["status"] == "QUEUED"
    assert still["provisional_accepted_tons"] is None

    after = _lot_now(lot["id"])
    assert after["tons_consumed"] == pytest.approx(0.000, abs=1e-6)
    assert after["tons_available"] == pytest.approx(22.000, abs=1e-6)
    assert after["status"] == "AVAILABLE"


def test_screening_a_batch_that_never_reached_the_pulper_leaks_no_reservation():
    """PRD §3.3: "Screening is the quiet step. Moving `PULPING → SCREENED` requires only
    that the batch be in `PULPING`, and its sole effect is to refresh the batch's
    `updated_at` (and, as with every mutation, bump its `version`)."
    PRD §3.3: "`APPROVED`, `DIVERTED` and `CANCELLED` are terminal batch states;
    requesting a step from a state that does not offer it is rejected with
    `ERR_PULP_BATCH_INVALID_STATE`."

    Design: Corner/state_machines/screen_on_a_queued_batch_rejected_as_wrong_from_state
    """
    lot, batch = _queued_batch_against_a_twenty_two_ton_lot(20.000)

    response = api_client.screen_pulp_batch(batch["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_PULP_BATCH_INVALID_STATE.value, 409)

    assert get_success_data(
        api_client.get_pulp_batch(batch["id"], OPERATOR))["status"] == "QUEUED"
    after = _lot_now(lot["id"])
    assert after["tons_consumed"] == pytest.approx(0.000, abs=1e-6)
    assert after["tons_available"] == pytest.approx(22.000, abs=1e-6)


def test_shipping_a_submitted_order_reports_the_order_state_not_the_missing_certificate():
    """PRD §3.6: "Shipping, `ALLOCATED → SHIPPED`, requires the order to be in
    `ALLOCATED`, requires that every roll set pointing at the order currently reads
    `ALLOCATED`, and requires the order's scheduled run to have `quality_status` of
    `CERTIFIED` — the last of which is reported as `ERR_RUN_NOT_CERTIFIED`."
    PRD §3.6: "A new order opens in `SUBMITTED` with `allocated_tons` of 0.000,
    `shipped_tons` of 0.000, `shortfall_tons` equal to its `ordered_tons`,
    `deschedule_count` of 0, `scheduled_run_id` null, and `version` of 1."

    Design: Corner/state_machines/ship_on_submitted_order_rejected_before_certification_gate
    """
    declare_tl_140()
    customer = register_customer(name="Gulf Coast Box Co",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=6.00)
    assert order["scheduled_run_id"] is None

    response = api_client.ship_customer_order(order["id"], PLANNER)
    validate_error(response, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)

    after = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert after["status"] == "SUBMITTED"
    assert after["shipped_tons"] == pytest.approx(0.000, abs=1e-6)
    assert after["version"] == 1


def test_a_second_cancel_on_a_cancelled_order_does_not_bump_the_version_again():
    """PRD §3.6: "A customer may cancel its own order, `SUBMITTED → CANCELLED`, only
    while the order is in `SUBMITTED`, only when the acting `X-User-ID` equals the order's
    `customer_id`, and only when `allocated_tons` reads exactly 0.000; an order with
    tonnage already allocated is rejected with `ERR_TONNAGE_ALREADY_BOOKED` (HTTP 409).
    `SHIPPED`, `SHORT_CLOSED` and `CANCELLED` are terminal."
    PRD §2.4: "Most resources additionally carry `updated_at` — same ISO 8601 UTC format
    with three fractional digits, refreshed on every mutation of that row — and
    `version`, an integer that starts at 1 on creation and increments by exactly one on
    every mutation."

    Design: Corner/state_machines/second_cancel_on_cancelled_order_is_locked_out
    """
    declare_tl_140()
    customer = register_customer(max_roll_width_mm=2400, max_roll_diameter_mm=1400)
    owner = make_customer_headers(customer["id"])
    order = submit_order(customer, "TL_140", ordered_tons=6.00)
    assert order["version"] == 1
    cancelled = validate_success(api_client.cancel_customer_order(order["id"], owner))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == 2

    response = api_client.cancel_customer_order(order["id"], owner)
    validate_error(response, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)

    after = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert after["status"] == "CANCELLED"
    assert after["version"] == 2
    assert after["allocated_tons"] == pytest.approx(0.000, abs=1e-6)


def test_voiding_a_reading_twice_is_refused_and_the_window_stays_empty():
    """PRD §3.7: "A mis-recorded reading can be voided, which requires the reading's
    `voided` flag to be currently false — voiding an already-voided reading is rejected
    with `ERR_ENV_RECORD_INVALID_STATE` (HTTP 409) — and sets `voided` to true, taking the
    row out of the rolling window entirely."
    PRD §3.7: "If the permit has no non-voided readings at all,
    `rolling_bod_kg_per_day` and `rolling_tss_kg_per_day` are 0.000,
    `exceedance_day_count` is 0, and the posture is `COMPLIANT`."

    Design: Corner/state_machines/voiding_an_already_voided_effluent_reading_is_rejected
    """
    permit = register_permit(permit_number="MILL-NPDES-1",
                             bod_limit_kg_per_day=500.00, tss_limit_kg_per_day=400.00,
                             flow_limit_m3_per_day=9000.00, rolling_window_days=30)
    reading = log_reading(permit["id"], reading_date="2026-08-01", flow_m3=3000.00,
                          bod_kg=200.00, tss_kg=150.00)
    validate_success(api_client.void_effluent_reading(reading["id"], ENV))

    response = api_client.void_effluent_reading(reading["id"], ENV)
    validate_error(response, ApiErrorId.ERR_ENV_RECORD_INVALID_STATE.value, 409)

    assert get_success_data(
        api_client.get_effluent_reading(reading["id"], ENV))["voided"] is True
    after = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert after["rolling_bod_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert after["rolling_tss_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert after["exceedance_day_count"] == 0
    assert after["compliance_posture"] == "COMPLIANT"
