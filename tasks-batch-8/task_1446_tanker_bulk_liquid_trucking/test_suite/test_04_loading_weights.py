"""Rack check-in, metering, weight verification, and placard confirmation claims."""
import pytest

from test_helpers import (
    OP_METER,
    OP_SCALE,
    TEST_USERS,
    check_in,
    close_meter,
    create_shipment_payload,
    confirm_placards,
    list_meter_tickets_for_shipment,
    make_terminal_operator_headers,
    plan_shipment,
    plan_shipment_payload,
    record_weights,
    set_clock,
    setup_draft_shipment,
    setup_loaded_shipment,
    setup_loading_shipment,
    setup_planned_shipment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_checkin_outside_window_rejected(api):
    """PRD 3.4: "the logical clock must fall within the reserved rack window, at or
    after `rack_window_start` and strictly before `rack_window_end` (outside that
    half-open window the check-in is rejected with `ERR_RACK_WINDOW_NOT_ACTIVE`)".

    Design: Corner/validations/checkin_outside_window_rejected
    """
    scenario = setup_planned_shipment()
    set_clock("2026-08-02T13:00:00Z")  # window is [10:00, 12:00)
    res = api.check_in_shipment(scenario["ship"]["id"], make_terminal_operator_headers(OP_METER))
    validate_error(res, "ERR_RACK_WINDOW_NOT_ACTIVE", expected_status=422)


def test_closemeter_sets_trailer_last_product_group(api):
    """PRD 3.1: "A trailer's `last_product_group` starts null — the trailer has hauled
    nothing yet — and is stamped with each product's compatibility group when a meter
    ticket closes."

    Design: Corner/state_machines/closemeter_sets_trailer_last_product_group
    """
    scenario = setup_loading_shipment()
    before = validate_success(api.get_trailer(scenario["trl"]["id"], DISP), 200)
    assert before["last_product_group"] is None

    close_meter(scenario, meter_end_gal=1000, observed_temp_F=60)

    after = validate_success(api.get_trailer(scenario["trl"]["id"], DISP), 200)
    assert after["last_product_group"] == "PETROLEUM"


def test_abort_loading_cycle_voids_ticket_and_reopens(api):
    """PRD 3.4: "aborting returns the shipment `LOADING → PLANNED` (any other state
    draws `ERR_SHIPMENT_INVALID_STATE`) and voids the open meter ticket
    `OPEN → VOIDED`, retaining it in history." And check-in "opens a MeterTicket:
    status `OPEN`" — a second check-in mints a fresh ticket.

    Design: Difficulty/non_linear_state_machine/shipment_loading_abort_cycle
    """
    scenario = setup_loading_shipment()

    aborted = validate_success(
        api.abort_loading(scenario["ship"]["id"], make_terminal_operator_headers(OP_METER)), 200)
    assert aborted["status"] == "PLANNED"

    reloaded = validate_success(
        api.check_in_shipment(scenario["ship"]["id"], make_terminal_operator_headers(OP_METER)), 200)
    assert reloaded["status"] == "LOADING"

    tickets, meta = list_meter_tickets_for_shipment(scenario["ship"]["id"])
    assert len(tickets) == 2, f"expected 2 meter tickets in history, got {len(tickets)}"
    # PRD 2.3: list endpoints sort by created_at ascending.
    assert tickets[0]["status"] == "VOIDED"
    assert tickets[1]["status"] == "OPEN"
    assert tickets[0]["id"] != tickets[1]["id"]


def test_abort_loading_from_planned_rejected(api):
    """PRD 3.4: "aborting returns the shipment `LOADING → PLANNED` (any other state
    draws `ERR_SHIPMENT_INVALID_STATE`)".

    Design: Difficulty/non_linear_state_machine/shipment_loading_abort_cycle
    """
    scenario = setup_planned_shipment()
    res = api.abort_loading(scenario["ship"]["id"], make_terminal_operator_headers(OP_METER))
    validate_error(res, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)


def test_placard_mismatch_rejected(api):
    """PRD 3.4: "it must equal the product's `placard_code` exactly or the
    confirmation fails with `ERR_PLACARD_MISMATCH`; success sets `placards_confirmed`
    to true." (On failure it stays false.)

    Design: Corner/errors/placard_mismatch_rejected
    """
    scenario = setup_loaded_shipment(weigh=False, placard=False)
    res = api.confirm_placards(
        scenario["ship"]["id"], {"observed_placard_code": "UN1203"},
        make_terminal_operator_headers(OP_METER))
    validate_error(res, "ERR_PLACARD_MISMATCH", expected_status=422)

    ship = validate_success(api.get_shipment(scenario["ship"]["id"], DISP), 200)
    assert ship["placards_confirmed"] is False


def test_weights_already_verified_rejected(api):
    """PRD 3.4: "It can be performed only once — if `weights_verified_at` is already
    set, the attempt is rejected with `ERR_WEIGHTS_ALREADY_VERIFIED`".

    Design: Corner/errors/weights_already_verified_rejected
    """
    scenario = setup_loaded_shipment(weigh=True, placard=False)
    res = api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 6600, "drive_lb": 12500, "trailer_lb": 12900},
        make_terminal_operator_headers("op-scale-2"))
    validate_error(res, "ERR_WEIGHTS_ALREADY_VERIFIED", expected_status=409)


def test_weights_sod_same_operator_rejected(api):
    """PRD 3.4: "segregation of duties forbids the operator who closed the meter from
    verifying the weights, so the caller's `X-User-ID` must differ from the meter
    ticket's `closed_by_user_id` (`ERR_SAME_OPERATOR_SEGREGATION`, 403)".

    Design: Corner/complexity_layers/weights_sod_same_operator_rejected
    """
    scenario = setup_loaded_shipment(weigh=False, placard=False)
    # Meter was closed by OP_METER inside the fixture.
    res = api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 6600, "drive_lb": 12500, "trailer_lb": 12900},
        make_terminal_operator_headers(OP_METER))
    validate_error(res, "ERR_SAME_OPERATOR_SEGREGATION", expected_status=403)

    ok = validate_success(api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 6600, "drive_lb": 12500, "trailer_lb": 12900},
        make_terminal_operator_headers(OP_SCALE)), 200)
    assert ok["weights_verified_at"] is not None


def test_axle_rating_equality_passes(api):
    """PRD 3.4: "any axle over its inclusive rating is `ERR_AXLE_LIMIT_EXCEEDED`" —
    with "equality passing" per the pinned check order, so drive_lb 34001 over the
    34000 rating fails while exactly 34000 passes. (Net60 4860.0 gal of density-7.0
    product: expected gross = 25000 + 34020 = 59020 lb; measured 10200+34000+14820 =
    59020.)

    Design: Difficulty/boundary_precision_check/axle_rating_equality_passes
    """
    scenario = setup_loaded_shipment(
        ordered_gallons=4860, meter_end_gal=4860, observed_temp_F=60, weigh=False, placard=False)
    res = api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 10200, "drive_lb": 34001, "trailer_lb": 14819},
        make_terminal_operator_headers(OP_SCALE))
    validate_error(res, "ERR_AXLE_LIMIT_EXCEEDED", expected_status=422)

    ok = validate_success(api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 10200, "drive_lb": 34000, "trailer_lb": 14820},
        make_terminal_operator_headers(OP_SCALE)), 200)
    assert ok["weights_verified_at"] is not None


def test_steer_axle_equality_also_passes(api):
    """PRD 3.4: "First, `steer_lb` must not exceed the trailer's
    `steer_axle_rating_lb`, with equality passing". (steer 12000 == rating 12000;
    measured sum 12000+32000+15020 = 59020 == expected gross 59020.)

    Design: Difficulty/boundary_precision_check/axle_rating_equality_passes
    """
    scenario = setup_loaded_shipment(
        ordered_gallons=4860, meter_end_gal=4860, observed_temp_F=60, weigh=False, placard=False)
    ok = validate_success(api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 12000, "drive_lb": 32000, "trailer_lb": 15020},
        make_terminal_operator_headers(OP_SCALE)), 200)
    assert ok["weights_verified_at"] is not None


def test_gvwr_exceeded_rejected(api):
    """PRD 3.4: "the sum of the three measured axles must not exceed `gvwr_lb`, again
    with equality passing, else `ERR_GVWR_EXCEEDED`". (Each axle within its rating on
    a gvwr-70000 trailer, but 11000+33000+33000 = 77000 > 70000.)

    Design: Corner/errors/gvwr_exceeded_rejected
    """
    scenario = setup_loaded_shipment(
        weigh=False, placard=False,
        trailer_overrides={"gvwr_lb": 70000})
    res = api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 11000, "drive_lb": 33000, "trailer_lb": 33000},
        make_terminal_operator_headers(OP_SCALE))
    validate_error(res, "ERR_GVWR_EXCEEDED", expected_status=422)


def test_weight_sum_inconsistent_rejected(api):
    """PRD 3.4: "if the absolute difference between the measured sum and the expected
    gross exceeds 3% of the expected gross — the 3% boundary itself is inclusive and
    passes — the check fails with `ERR_WEIGHT_SUM_INCONSISTENT`". (Expected gross =
    25000 tare + 1000.0 gal x 7.0 lb/gal = 32000 lb; measured 25000 deviates 21.9%.)

    Design: Corner/errors/weight_sum_inconsistent_rejected
    """
    scenario = setup_loaded_shipment(weigh=False, placard=False)
    res = api.record_weights(
        scenario["ship"]["id"],
        {"steer_lb": 6000, "drive_lb": 9000, "trailer_lb": 10000},
        make_terminal_operator_headers(OP_SCALE))
    validate_error(res, "ERR_WEIGHT_SUM_INCONSISTENT", expected_status=422)
