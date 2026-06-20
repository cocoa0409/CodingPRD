"""Order and exam state-machine transitions: invalid transitions, terminal
lockdown, cascade-cancel, bubble-up, acquisition preconditions, ack idempotency,
and the critical-result-required sign-off gate.

Translates Corner/state_machines instances (the report-addendum first-loop stub
is owned by Difficulty/non_linear_state_machine and is NOT translated here).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_order_payload, create_series_payload, finalize_series_payload,
    create_report_payload, claim_read_payload,
    TEST_USERS, make_nurse_headers, make_technologist_headers, make_radiologist_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


def test_benefit_check_from_screen_cleared_invalid_state(api):
    """PRD §3.2: "The benefit check is the fiscal gate that advances the order
    from `REQUESTED` to `BENEFIT_CHECKED`. It may only run while the order is
    `REQUESTED` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/benefit_check_from_screen_cleared_invalid_state
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False, clock=None)
    order_id, _ = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    res = api.benefit_check(order_id, {}, CLERK)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_cancel_already_cancelled_order_invalid_state(api):
    """PRD §3.4: "an order may be cancelled when it is not in `SIGNED_OFF`,
    `ADDENDUM_REQUESTED`, or `CANCELLED`; an attempt to cancel from one of those
    states is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_order_invalid_state
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False, clock=None)
    order = fx.create_order(topo["center_id"], topo["modality_id"])
    validate_success(api.cancel_order(order["id"], CLERK), 200)
    res = api.cancel_order(order["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_cancel_order_cascade_cancels_booked_exam(api):
    """PRD §3.4: "Cancelling an order moves it to `CANCELLED` and, if an exam
    exists for it in a non-terminal pre-acquisition state (`BOOKED` or
    `CHECKED_IN`), cascade-cancels that exam, which releases the room and
    technologist intervals."

    Design: Corner/state_machines/cancel_order_cascade_cancels_booked_exam
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T08:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    validate_success(api.cancel_order(order_id, CLERK), 200)
    order = validate_success(api.get_order(order_id, CLERK), 200)
    exam_after = validate_success(api.get_exam(exam["id"], CLERK), 200)
    assert order["status"] == "CANCELLED"
    assert exam_after["status"] == "CANCELLED"


def test_finish_acquisition_initial_state_and_bubble_up(api):
    """PRD §3.5: "Finishing acquisition moves the exam from `ACQUIRING` to
    `ACQUIRED`."
    PRD §3.5: "On finishing, the exam's `acquired_at_utc` is stamped from the
    center's `now_utc`, and the parent order bubbles up from `SCHEDULED` to
    `READ_PENDING`."

    Design: Corner/state_machines/finish_acquisition_initial_state_and_bubble_up
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T09:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    th = make_technologist_headers(topo["tech_id"])
    validate_success(api.check_in(exam["id"], th), 200)
    validate_success(api.start_acquisition(exam["id"], th), 200)
    ser = validate_success(api.create_series(exam["id"], create_series_payload("PA"), th), 201)
    validate_success(api.finalize_series(ser["id"], finalize_series_payload("ACCEPTED"), th), 200)
    acquired = validate_success(api.finish_acquisition(exam["id"], th), 200)
    assert acquired["status"] == "ACQUIRED"
    assert acquired["acquired_at_utc"] == "2026-06-01T09:00:00.000Z"
    order = validate_success(api.get_order(order_id, CLERK), 200)
    assert order["status"] == "READ_PENDING"


def test_finish_acquisition_no_accepted_series_rejected(api):
    """PRD §3.5: "It requires the exam to be `ACQUIRING`, at least one
    `ImageSeries` on the exam to have outcome `ACCEPTED` (otherwise
    `ERR_NO_ACCEPTED_SERIES`)".

    Design: Corner/state_machines/finish_acquisition_no_accepted_series_rejected
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=200.0)
    th = make_technologist_headers(acq["topo"]["tech_id"])
    ser = validate_success(api.create_series(acq["exam_id"], create_series_payload("BAD"), th), 201)
    validate_success(api.finalize_series(ser["id"],
                     finalize_series_payload("REJECTED", reject_reason="ARTIFACT"), th), 200)
    res = api.finish_acquisition(acq["exam_id"], th)
    validate_error(res, "ERR_NO_ACCEPTED_SERIES", 409)


def test_finish_acquisition_series_still_capturing_rejected(api):
    """PRD §3.5: "and no `ImageSeries` on the exam to still be `CAPTURING`
    (otherwise `ERR_SERIES_STILL_CAPTURING`)."

    Design: Corner/state_machines/finish_acquisition_series_still_capturing_rejected
    """
    acq = fx.setup_acquiring_exam(modality_type="XRAY", repeat_rate_threshold_pct=200.0)
    th = make_technologist_headers(acq["topo"]["tech_id"])
    ok = validate_success(api.create_series(acq["exam_id"], create_series_payload("OK"), th), 201)
    validate_success(api.finalize_series(ok["id"], finalize_series_payload("ACCEPTED"), th), 200)
    validate_success(api.create_series(acq["exam_id"], create_series_payload("PENDING"), th), 201)
    res = api.finish_acquisition(acq["exam_id"], th)
    validate_error(res, "ERR_SERIES_STILL_CAPTURING", 409)


def test_check_in_too_early_rejected(api):
    """PRD §3.5: "may not happen before the appointment — the center's
    `now_utc` must be at or after the exam's `scheduled_start_utc`, otherwise
    the check-in is rejected with `ERR_TOO_EARLY_TO_CHECK_IN`."

    Design: Corner/state_machines/check_in_too_early_rejected
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T08:00:00Z")
    order_id, ov = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam = fx.schedule_exam(topo, order_id, ov, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    # clock remains at 08:00 < 09:00 scheduled start
    res = api.check_in(exam["id"], make_technologist_headers(topo["tech_id"]))
    validate_error(res, "ERR_TOO_EARLY_TO_CHECK_IN", 409)


def test_critical_result_ack_idempotency_second_ack_invalid(api):
    """PRD §3.7: "Acknowledging a critical result moves it from
    `UNACKNOWLEDGED` to `ACKNOWLEDGED`, requiring it to be `UNACKNOWLEDGED`
    (otherwise `ERR_INVALID_STATE`)."
    PRD §3.7: "`sla_breached` is set true when `minutes_to_ack` is strictly
    greater than the center's `critical_ack_sla_minutes`."

    Design: Corner/state_machines/critical_result_ack_idempotency_second_ack_invalid
    """
    setup = fx.setup_critical_result(modality_type="XRAY", critical_ack_sla_minutes=60,
                                     raised_clock="2026-06-01T09:00:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T09:30:00Z")
    acked = validate_success(api.acknowledge_critical_result(setup["cr_id"], rh), 200)
    assert acked["minutes_to_ack"] == 30.0
    assert acked["sla_breached"] is False
    res = api.acknowledge_critical_result(setup["cr_id"], rh)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_critical_result_required_on_signoff_with_critical_finding(api):
    """PRD §3.6: "if the report's `has_critical_finding` is true, a
    `CriticalResult` must already have been raised for that report, or the
    sign-off is rejected with `ERR_CRITICAL_RESULT_REQUIRED`."

    Design: Corner/state_machines/critical_result_required_on_signoff_with_critical_finding
    """
    setup = fx.setup_read_complete(modality_type="XRAY", has_critical_finding=True,
                                   acquired_clock="2026-06-01T09:00:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    res = api.sign_off(setup["exam_id"], rh)
    validate_error(res, "ERR_CRITICAL_RESULT_REQUIRED", 409)
