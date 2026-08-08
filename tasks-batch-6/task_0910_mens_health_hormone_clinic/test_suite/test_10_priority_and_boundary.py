"""Validation-priority conflicts and numeric boundary precision."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_patient, create_reviewed_panel, get_prescription, get_plan,
    create_prescription_payload, create_refill_order_payload,
    setup_active_plan, setup_plan_with_prescription, make_plan_titration_pending,
    set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


# --------------------------------------------------------------------- priority pair 1
def test_refill_suspended_state_beats_delinquent_fiscal(api):
    """PRD §3.6: "the referenced prescription must not be `SUSPENDED` or `REVOKED` — an
    `EXHAUSTED` prescription passes this particular check — or the request is rejected
    with `ERR_PRESCRIPTION_SUSPENDED`; then the membership's `subscription_status` must
    be `ACTIVE`, or the request is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`; then the
    membership's `payment_status` must be `CURRENT`, or the request is rejected with
    `ERR_MEMBERSHIP_DELINQUENT`."

    Design: Difficulty/priority_pair_validation_conflict/refill_suspended_state_beats_delinquent_fiscal
    """
    ctx = setup_plan_with_prescription()
    get_success_data(api.record_payment(ctx["membership_id"], {"outcome": "FAILED"}, ADMIN))
    # Unsafe monitoring review suspends the prescription via the hold cascade.
    create_reviewed_panel(
        ctx["patient_id"], ctx["clinician_id"], panel_type="MONITORING",
        results={"total_testosterone_ng_dl": 500, "psa_ng_ml": 1.5, "hematocrit_pct": 56.0, "drawn_at": "2026-04-28T09:00:00Z"},
    )
    assert get_prescription(ctx["rx_id"])["status"] == "SUSPENDED"
    rx_version = get_prescription(ctx["rx_id"])["version"]
    payload = create_refill_order_payload(ctx["rx_id"], ctx["membership_id"], ctx["patient_id"], rx_version)
    validate_error(api.create_refill_order(payload, ADMIN), ApiErrorId.ERR_PRESCRIPTION_SUSPENDED, 409)


def test_refill_delinquent_alone_surfaces_fiscal_error(api):
    """PRD §3.6: "then the membership's `payment_status` must be `CURRENT`, or the
    request is rejected with `ERR_MEMBERSHIP_DELINQUENT`."

    Design: Difficulty/priority_pair_validation_conflict/refill_suspended_state_beats_delinquent_fiscal
    """
    ctx = setup_plan_with_prescription()  # prescription stays ISSUED (no suspension)
    get_success_data(api.record_payment(ctx["membership_id"], {"outcome": "FAILED"}, ADMIN))
    rx_version = get_prescription(ctx["rx_id"])["version"]
    payload = create_refill_order_payload(ctx["rx_id"], ctx["membership_id"], ctx["patient_id"], rx_version)
    validate_error(api.create_refill_order(payload, ADMIN), ApiErrorId.ERR_MEMBERSHIP_DELINQUENT, 402)


# --------------------------------------------------------------------- priority pair 2
def test_prescribe_patient_mismatch_beats_monitoring_overdue(api):
    """PRD §3.6: "the body's `patient_id` must equal the referenced plan's `patient_id`,
    or issuance fails with `ERR_PATIENT_MISMATCH`".
    PRD §3.6: "A safety guard then requires that the patient have at least one
    `REVIEWED` lab panel whose `drawn_at` is no more than ninety days before the current
    logical clock; absent such recent monitoring, issuance is rejected with
    `ERR_MONITORING_OVERDUE`."

    Design: Difficulty/priority_pair_validation_conflict/prescribe_patient_mismatch_beats_monitoring_overdue
    """
    ctx = setup_active_plan(baseline_results={"drawn_at": "2026-05-01T09:00:00Z"})
    other_patient = create_patient()
    set_clock("2026-09-01T00:00:00Z")  # baseline now > 90 days old: monitoring is overdue too
    payload = create_prescription_payload(ctx["plan_id"], other_patient["id"])
    validate_error(api.create_prescription(payload, ctx["clinician_headers"]), ApiErrorId.ERR_PATIENT_MISMATCH, 409)


def test_prescribe_patient_mismatch_fires_with_current_monitoring(api):
    """PRD §3.6: "the body's `patient_id` must equal the referenced plan's `patient_id`,
    or issuance fails with `ERR_PATIENT_MISMATCH`".

    Design: Difficulty/priority_pair_validation_conflict/prescribe_patient_mismatch_beats_monitoring_overdue
    """
    ctx = setup_active_plan()  # baseline within window; monitoring is current
    other_patient = create_patient()
    payload = create_prescription_payload(ctx["plan_id"], other_patient["id"])
    validate_error(api.create_prescription(payload, ctx["clinician_headers"]), ApiErrorId.ERR_PATIENT_MISMATCH, 409)


# --------------------------------------------------------------------- boundary 1: hematocrit
def _setup_titration_pending_with_monitoring(hct):
    ctx = setup_active_plan(baseline_results={"drawn_at": "2026-04-15T09:00:00Z"}, starting_dose_mg=100)
    make_plan_titration_pending(ctx, proposed_dose_mg=120)
    create_reviewed_panel(
        ctx["patient_id"], ctx["clinician_id"], panel_type="MONITORING",
        results={"total_testosterone_ng_dl": 500, "psa_ng_ml": 1.5, "hematocrit_pct": hct, "drawn_at": "2026-04-27T09:00:00Z"},
    )
    return ctx


def test_hematocrit_at_54_blocks_titration_confirm(api):
    """PRD §3.5: "it requires that the patient's latest `REVIEWED` lab panel have a
    `hematocrit_pct` below 54.0, failing otherwise with `ERR_HEMATOCRIT_UNSAFE`."

    Design: Difficulty/boundary_precision_check/hematocrit_at_54_blocks_titration_confirm
    """
    ctx = _setup_titration_pending_with_monitoring(54.0)
    validate_error(
        api.confirm_titration(ctx["plan_id"], ctx["titration_id"], ctx["clinician_headers"]),
        ApiErrorId.ERR_HEMATOCRIT_UNSAFE, 422,
    )
    assert get_plan(ctx["plan_id"])["status"] == "TITRATION_PENDING"


def test_hematocrit_below_54_allows_titration_confirm(api):
    """PRD §3.5: "it requires that the patient's latest `REVIEWED` lab panel have a
    `hematocrit_pct` below 54.0, failing otherwise with `ERR_HEMATOCRIT_UNSAFE`."
    PRD §3.5: "Confirming a pending titration moves the plan from `TITRATION_PENDING`
    back to `ACTIVE`".

    Design: Difficulty/boundary_precision_check/hematocrit_at_54_blocks_titration_confirm
    """
    ctx = _setup_titration_pending_with_monitoring(53.9)
    titration = validate_success(
        api.confirm_titration(ctx["plan_id"], ctx["titration_id"], ctx["clinician_headers"]), 200
    )
    assert titration["status"] == "CONFIRMED"
    plan = get_plan(ctx["plan_id"])
    assert plan["status"] == "ACTIVE"
    assert plan["current_dose_mg"] == 120


# --------------------------------------------------------------------- boundary 2: monitoring window
def test_prescribe_with_zero_reviewed_panels_in_window(api):
    """PRD §3.6: "A safety guard then requires that the patient have at least one
    `REVIEWED` lab panel whose `drawn_at` is no more than ninety days before the current
    logical clock; absent such recent monitoring, issuance is rejected with
    `ERR_MONITORING_OVERDUE`."

    Design: Difficulty/boundary_precision_check/prescribe_with_zero_reviewed_panels_in_window
    """
    ctx = setup_active_plan(baseline_results={"drawn_at": "2026-05-01T09:00:00Z"})
    set_clock("2026-09-01T00:00:00Z")  # only reviewed panel now falls outside the 90-day window
    payload = create_prescription_payload(ctx["plan_id"], ctx["patient_id"])
    validate_error(api.create_prescription(payload, ctx["clinician_headers"]), ApiErrorId.ERR_MONITORING_OVERDUE, 422)


def test_prescribe_with_reviewed_panel_in_window_succeeds(api):
    """PRD §3.6: "On success the prescription's `prescriber_id` is set from `X-User-ID`,
    its `refills_remaining` is initialized to `refills_authorized`, and its `status` is
    `ISSUED`."

    Design: Difficulty/boundary_precision_check/prescribe_with_zero_reviewed_panels_in_window
    """
    ctx = setup_active_plan()  # baseline drawn 2026-04-20, clock at startup 2026-05-01 -> in window
    payload = create_prescription_payload(ctx["plan_id"], ctx["patient_id"])
    data = validate_success(api.create_prescription(payload, ctx["clinician_headers"]), 201)
    assert data["status"] == "ISSUED"
    assert data["refills_remaining"] == 3
