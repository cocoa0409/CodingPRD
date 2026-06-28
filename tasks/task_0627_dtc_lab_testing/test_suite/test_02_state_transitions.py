"""Breadth tests for state-machine transitions, invalid-transition guards,
terminal lockdowns, and the side effects of result/specimen lifecycle steps.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
PHLEB = TEST_USERS["phlebotomy_tech_headers"]
LAB = TEST_USERS["lab_tech_headers"]
LAB2 = TEST_USERS["lab_tech_2_headers"]
PHYSICIAN = TEST_USERS["ordering_physician_headers"]


# ---------------------------------------------------------------------------
# Corner/state_machines/physician_order_decision_on_terminal_approved_returns_409
# ---------------------------------------------------------------------------
def test_decision_on_approved_physician_order_returns_409(api):
    """PRD 3.5: "A decision is allowed only while the order is SUBMITTED; an attempt
    against any other state is rejected with ERR_PHYSICIAN_ORDER_NOT_REVIEWABLE."

    Design: Corner/state_machines/physician_order_decision_on_terminal_approved_returns_409
    """
    ctx = fx.setup_restricted_order(test_code="TSTC", patient_overrides={"state_code": "CA", "date_of_birth": "1990-01-01"}, api=api)
    po = ctx["physician_order"]
    validate_success(api.decide_physician_order(po["id"], F.physician_decision_payload("APPROVE"), PHYSICIAN))
    resp = api.decide_physician_order(po["id"], F.physician_decision_payload("DECLINE"), PHYSICIAN)
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_ORDER_NOT_REVIEWABLE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/resubmit_on_submitted_returns_409
# ---------------------------------------------------------------------------
def test_resubmit_on_submitted_returns_409(api):
    """PRD 3.5: "A resubmission attempted on an order in any other state is rejected
    with ERR_PHYSICIAN_ORDER_NOT_RESUBMITTABLE."

    Design: Corner/state_machines/resubmit_on_submitted_returns_409
    """
    ctx = fx.setup_restricted_order(test_code="TSTD", patient_overrides={"state_code": "CA", "date_of_birth": "1990-01-01"}, api=api)
    po = ctx["physician_order"]
    patient = ctx["patient"]
    resp = api.resubmit_physician_order(po["id"], {"clinical_note": "nope"}, make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_ORDER_NOT_RESUBMITTABLE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/critical_result_parks_pending_callback_then_release_blocked
# ---------------------------------------------------------------------------
def test_critical_result_parks_then_release_blocked_until_ack(api):
    """PRD 3.8: "A freshly minted result whose provisional_flag is CRITICAL is
    parked in PENDING_CRITICAL_CALLBACK".
    PRD 3.8: "A result release moves the result to RELEASED and is permitted only
    when the result is in PROCESSING or PENDING_CRITICAL_CALLBACK (else
    ERR_RESULT_NOT_RELEASABLE), when a critical result has had critical_acknowledged
    set true (else ERR_CRITICAL_CALLBACK_REQUIRED)".

    analyzer_value 500 with critical_high 400 is CRITICAL; release before ack fails
    ERR_CRITICAL_CALLBACK_REQUIRED; after acknowledge it releases.

    Design: Corner/state_machines/critical_result_parks_pending_callback_then_release_blocked
    """
    ctx = fx.setup_processed_result(
        analyzer_value=500,
        fulfillment_mode="HOME_KIT",
        offering_overrides={
            "test_code": "CRT", "display_name": "Crit Test", "list_price_cents": 4000,
            "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100, "critical_high": 400,
        },
        patient_overrides={"state_code": "CA", "consent_share_results": True},
        api=api,
    )
    res = ctx["lab_result"]
    assert res["provisional_flag"] == "CRITICAL"

    blocked = api.release_lab_result(res["id"], LAB2)
    validate_error(blocked, ApiErrorId.ERR_CRITICAL_CALLBACK_REQUIRED.value)

    get_success_data(api.acknowledge_critical(res["id"], LAB2))
    released = validate_success(api.release_lab_result(res["id"], LAB2))
    assert released["status"] == "RELEASED"
    assert released["final_flag"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Corner/state_machines/specimen_reject_excludes_line_from_invoice
# ---------------------------------------------------------------------------
def test_specimen_reject_marks_line_rejected_excludes_from_invoice(api):
    """PRD 3.8: "A specimen rejection moves the Specimen to REJECTED and the order
    line from COLLECTED to REJECTED, excludes that line from the chronological
    invoice, recomputes the order's invoiced total".

    Single-line order: reject the collected specimen; line REJECTED, invoice stays 0.

    Design: Corner/state_machines/specimen_reject_excludes_line_from_invoice
    """
    ctx = fx.setup_collected_line(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "RJ", "display_name": "Reject Test", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    order, line, spec = ctx["order"], ctx["order_line"], ctx["specimen"]
    get_success_data(api.reject_specimen(spec["id"], LAB))
    line_after = validate_success(api.get_order_line(line["id"], ADMIN))
    assert line_after["status"] == "REJECTED"
    order_after = validate_success(api.get_order(order["id"], ADMIN))
    assert order_after["invoiced_total_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/state_machines/amend_released_result_recomputes_flags
# ---------------------------------------------------------------------------
def test_amend_released_result_transitions_and_recomputes_flag(api):
    """PRD 3.8: "A released result may be amended by a LabTech by submitting a
    replacement analyzer_value. Amendment is permitted only on a RELEASED result
    (else ERR_RESULT_NOT_AMENDABLE); it moves the result to AMENDED, replaces the
    analyzer_value, recomputes both flags".

    AM ref 70-100: released at 80 (NORMAL); amend to 120 -> AMENDED, provisional
    ABNORMAL.

    Design: Corner/state_machines/amend_released_result_recomputes_flags
    """
    ctx = fx.setup_released_result(
        analyzer_value=80,
        fulfillment_mode="HOME_KIT",
        offering_overrides={
            "test_code": "AM", "display_name": "Amend Test", "list_price_cents": 4000,
            "specimen_type": "BLOOD", "ref_low": 70, "ref_high": 100,
        },
        patient_overrides={"state_code": "CA", "consent_share_results": True},
        api=api,
    )
    res = ctx["lab_result"]
    amended = validate_success(api.amend_lab_result(res["id"], F.amend_lab_result_payload(120), LAB2))
    assert amended["status"] == "AMENDED"
    assert amended["provisional_flag"] == "ABNORMAL"


# ---------------------------------------------------------------------------
# Corner/state_machines/cancel_order_with_resulted_line_returns_409
# ---------------------------------------------------------------------------
def test_cancel_order_with_resulted_line_returns_409(api):
    """PRD 3.7: "An order may be cancelled while its fulfillment is
    AWAITING_COLLECTION, IN_PROCESSING, or PARTIALLY_RESULTED, but only if no order
    line is RESULTED; a cancellation against an order that already has a resulted
    line is rejected with ERR_ORDER_HAS_RESULTED_LINES".

    Design: Corner/state_machines/cancel_order_with_resulted_line_returns_409
    """
    ctx = fx.setup_released_result(
        analyzer_value=5,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "CX", "display_name": "Cancel Test", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order = ctx["patient"], ctx["order"]
    p_headers = make_patient_headers(patient["id"])
    order_now = validate_success(api.get_order(order["id"], p_headers))
    resp = api.cancel_order(order["id"], {"expected_order_version": order_now["version"]}, p_headers)
    validate_error(resp, ApiErrorId.ERR_ORDER_HAS_RESULTED_LINES.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/capture_before_completed_returns_409
# ---------------------------------------------------------------------------
def test_capture_before_completed_returns_409(api):
    """PRD 3.7: "Payment capture is a Patient action that moves the payment axis
    from AUTHORIZED to CAPTURED. It carries expected_order_version and is permitted
    only when the order's fulfillment_status is COMPLETED (else
    ERR_ORDER_NOT_COMPLETE_FOR_CAPTURE)".

    Design: Corner/state_machines/capture_before_completed_returns_409
    """
    ctx = fx.setup_single_line_order(
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "CAP", "display_name": "Capture Early", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    patient, order = ctx["patient"], ctx["order"]
    p_headers = make_patient_headers(patient["id"])
    resp = api.capture_payment(order["id"], {"expected_order_version": order["version"]}, p_headers)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_COMPLETE_FOR_CAPTURE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/analyzer_run_release_twice_returns_409
# ---------------------------------------------------------------------------
def test_analyzer_run_release_twice_returns_409(api):
    """PRD 3.9: "Releasing a run moves it from RESERVED to RELEASED, freeing the
    slot so it no longer participates in overlap checks; a release attempted when
    the run is not RESERVED is rejected with ERR_ANALYZER_RUN_NOT_RELEASABLE."

    Design: Corner/state_machines/analyzer_run_release_twice_returns_409
    """
    run = get_success_data(api.create_analyzer_run(
        F.create_analyzer_run_payload("CHEM-9", "2026-03-01T09:00:00Z", "2026-03-01T10:00:00Z"), LAB,
    ))
    get_success_data(api.release_analyzer_run(run["id"], LAB))
    resp = api.release_analyzer_run(run["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_ANALYZER_RUN_NOT_RELEASABLE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/process_on_uncollected_specimen_state_guard
# ---------------------------------------------------------------------------
def test_process_specimen_twice_returns_409(api):
    """PRD 3.8: "Processing is permitted only on a specimen in COLLECTED; an attempt
    otherwise is rejected with ERR_RESULT_NOT_PROCESSABLE. Processing advances the
    specimen from COLLECTED to IN_ANALYSIS".

    A second process on a specimen now in IN_ANALYSIS is rejected.

    Design: Corner/state_machines/process_on_uncollected_specimen_state_guard
    """
    ctx = fx.setup_processed_result(
        analyzer_value=5,
        fulfillment_mode="HOME_KIT",
        offering_overrides={"test_code": "PR", "display_name": "Process Twice", "list_price_cents": 4000, "specimen_type": "BLOOD"},
        patient_overrides={"state_code": "CA"},
        api=api,
    )
    spec = ctx["specimen"]
    resp = api.process_specimen(spec["id"], F.process_specimen_payload(6), LAB)
    validate_error(resp, ApiErrorId.ERR_RESULT_NOT_PROCESSABLE.value)
