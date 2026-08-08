"""Prescription lifecycle: suspend/reactivate cycle, intake-clearance gate,
coverage-window buffer, intake expiry, discontinue cascade, coverage expiry.

Difficulty: prescription_active_suspended_cycle, prescription_requires_intake_cleared,
prescription_coverage_buffer_conflict.
Corner: prescription_from_expired_intake, prescription_discontinue_cascade,
refill_approve_after_coverage_end_expires_prescription.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_prescription_payload,
    register_patient, register_provider,
    create_submitted_intake, create_completed_visit,
    setup_active_prescription, request_refill, add_lab_order,
    set_clock,
    make_patient_headers, make_provider_headers, billing_admin_headers,
)


# ---------------------------------------------------------------------------
# ACTIVE <-> SUSPENDED cycle (difficulty)
# ---------------------------------------------------------------------------
def test_prescription_suspend_active_to_suspended(api):
    """PRD §3.4: "A provider may suspend an ACTIVE prescription (ACTIVE →
    SUSPENDED); this is permitted only from ACTIVE, else
    ERR_PRESCRIPTION_INVALID_STATE (409), and an optional reason may accompany
    it."

    Design: Difficulty/non_linear_state_machine/prescription_active_suspended_cycle
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "PROGESTERONE"})
    data = validate_success(
        api.suspend_prescription(ctx["prescription"]["id"], ctx["provider_headers"],
                                 {"reason": "safety hold"}))
    assert data["status"] == "SUSPENDED", f"expected SUSPENDED, got {data['status']}"


def test_prescription_reactivate_suspended_to_active(api):
    """PRD §3.4: "A provider may reactivate a SUSPENDED prescription (SUSPENDED →
    ACTIVE), permitted only from SUSPENDED, else ERR_PRESCRIPTION_INVALID_STATE
    (409)."

    Design: Difficulty/non_linear_state_machine/prescription_active_suspended_cycle
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "PROGESTERONE"})
    rx_id = ctx["prescription"]["id"]
    validate_success(api.suspend_prescription(rx_id, ctx["provider_headers"]))
    data = validate_success(api.reactivate_prescription(rx_id, ctx["provider_headers"]))
    assert data["status"] == "ACTIVE", f"expected ACTIVE after reactivate, got {data['status']}"


# ---------------------------------------------------------------------------
# Prescription requires CLEARED intake (difficulty)
# ---------------------------------------------------------------------------
def _flagged_completed_visit(api):
    patient = register_patient(api)
    provider = register_provider(api)
    intake = create_submitted_intake(api, patient["id"],
                                     symptom_ratings=[{"domain": "VASOMOTOR", "severity": 6}],
                                     reported_conditions=["VTE_HISTORY"])
    visit = create_completed_visit(api, patient["id"], provider["id"], intake["id"])
    return patient, provider, intake, visit, make_provider_headers(provider["id"])


def test_prescription_from_flagged_intake_rejected(api):
    """PRD §3.4: "The source visit must be COMPLETED and its intake must be
    CLEARED; if not, the request is rejected with ERR_INTAKE_NOT_CLEARED (409)."

    Design: Difficulty/cross_entity_state_dependency/prescription_requires_intake_cleared
    """
    patient, provider, intake, visit, prov_h = _flagged_completed_visit(api)
    assert intake["status"] == "FLAGGED", f"precondition: intake FLAGGED, got {intake['status']}"
    resp = api.create_prescription(create_prescription_payload(visit_id=visit["id"]), prov_h)
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_CLEARED)


def test_prescription_succeeds_after_intake_cleared(api):
    """PRD §3.2: "a provider reviewing the case may clear it, transitioning
    FLAGGED → CLEARED."
    PRD §3.4: "On creation the prescription starts ACTIVE, sets refills_remaining
    equal to total_refills_authorized, records coverage_start_date as the current
    logical-clock date."

    Design: Difficulty/cross_entity_state_dependency/prescription_requires_intake_cleared
    """
    patient, provider, intake, visit, prov_h = _flagged_completed_visit(api)
    validate_success(api.clear_intake(intake["id"], prov_h))
    data = validate_success(
        api.create_prescription(create_prescription_payload(visit_id=visit["id"]), prov_h),
        expected_status=201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"


# ---------------------------------------------------------------------------
# Coverage-window buffer conflict (difficulty)
# ---------------------------------------------------------------------------
def _two_completed_visits_for_buffer(api):
    set_clock(api, "2026-06-01T00:00:00Z")
    patient = register_patient(api)
    provider = register_provider(api)
    intake = create_submitted_intake(api, patient["id"])
    v1 = create_completed_visit(api, patient["id"], provider["id"], intake["id"],
                                scheduled_start="2026-06-01T09:00:00Z",
                                scheduled_end="2026-06-01T10:00:00Z")
    prov_h = make_provider_headers(provider["id"])
    # P1: ESTROGEN_PATCH coverage 2026-06-01 .. 2026-06-21
    get_success_data(api.create_prescription(create_prescription_payload(
        visit_id=v1["id"], hrt_type="ESTROGEN_PATCH", days_supply_per_fill=20,
        total_refills_authorized=2, coverage_days=20, refill_price_cents=15000), prov_h))
    set_clock(api, "2026-06-25T00:00:00Z")
    v2 = create_completed_visit(api, patient["id"], provider["id"], intake["id"],
                                scheduled_start="2026-06-25T09:00:00Z",
                                scheduled_end="2026-06-25T10:00:00Z")
    return v2, prov_h


def test_same_type_within_buffer_conflict(api):
    """PRD §3.4: "for the same patient and the same hrt_type, the new window must
    be separated by at least a 7-day buffer from the window of any ACTIVE or
    SUSPENDED prescription of that same type. Windows are treated as closed
    intervals and the buffer is inclusive, so the gap between the two windows
    must be at least 7 days; a smaller gap (including any overlap or touching) is
    rejected with ERR_COVERAGE_WINDOW_CONFLICT (409)."

    Design: Difficulty/resource_temporal_overlap/prescription_coverage_buffer_conflict
    """
    v2, prov_h = _two_completed_visits_for_buffer(api)
    # New ESTROGEN_PATCH window starts 2026-06-25, only 4 days after prior end.
    resp = api.create_prescription(create_prescription_payload(
        visit_id=v2["id"], hrt_type="ESTROGEN_PATCH", days_supply_per_fill=20,
        total_refills_authorized=2, coverage_days=20, refill_price_cents=15000), prov_h)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_CONFLICT)


def test_different_hrt_type_not_blocked_by_buffer(api):
    """PRD §3.4: "for the same patient and the same hrt_type, the new window must
    be separated by at least a 7-day buffer from the window of any ACTIVE or
    SUSPENDED prescription of that same type."

    Design: Difficulty/resource_temporal_overlap/prescription_coverage_buffer_conflict
    """
    v2, prov_h = _two_completed_visits_for_buffer(api)
    data = validate_success(api.create_prescription(create_prescription_payload(
        visit_id=v2["id"], hrt_type="PROGESTERONE", days_supply_per_fill=20,
        total_refills_authorized=2, coverage_days=20, refill_price_cents=15000), prov_h),
        expected_status=201)
    assert data["status"] == "ACTIVE", \
        f"different hrt_type must be accepted, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner: intake expired at prescribing
# ---------------------------------------------------------------------------
def test_prescription_from_expired_intake_returns_intake_expired(api):
    """PRD §3.4: "The backing intake must have been submitted within the last 90
    days of the current logical clock; an older intake yields ERR_INTAKE_EXPIRED
    (409)."

    Design: Corner/validations/prescription_from_expired_intake_returns_intake_expired
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    patient = register_patient(api)
    provider = register_provider(api)
    intake = create_submitted_intake(api, patient["id"])
    visit = create_completed_visit(api, patient["id"], provider["id"], intake["id"],
                                   scheduled_start="2026-06-02T09:00:00Z",
                                   scheduled_end="2026-06-02T10:00:00Z")
    set_clock(api, "2026-09-15T00:00:00Z")
    resp = api.create_prescription(create_prescription_payload(visit_id=visit["id"]),
                                   make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_INTAKE_EXPIRED)


# ---------------------------------------------------------------------------
# Corner: discontinue cascade cancels labs + denies refills
# ---------------------------------------------------------------------------
def test_prescription_discontinue_cascade_cancels_labs_denies_refills(api):
    """PRD §3.4: "Discontinuation cascades twice: every lab order of the
    prescription still in PENDING is cancelled (PENDING → CANCELLED), and every
    refill still in REQUESTED or APPROVED is denied with the denial reason
    "prescription discontinued"."

    Design: Corner/state_machines/prescription_discontinue_cascade_cancels_labs_denies_refills
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "COMBINED",
                                                       "total_refills_authorized": 3})
    lab = add_lab_order(api, ctx, panel_type="LIVER")
    refill = request_refill(api, ctx)
    data = validate_success(
        api.discontinue_prescription(ctx["prescription"]["id"], ctx["provider_headers"],
                                     {"reason": "adverse event"}))
    assert data["status"] == "DISCONTINUED", f"expected DISCONTINUED, got {data['status']}"
    lab_after = get_success_data(api.get_lab_order(lab["id"], ctx["provider_headers"]))
    assert lab_after["status"] == "CANCELLED", f"lab must be CANCELLED, got {lab_after['status']}"
    refill_after = get_success_data(api.get_refill(refill["id"], ctx["provider_headers"]))
    assert refill_after["status"] == "DENIED", f"refill must be DENIED, got {refill_after['status']}"


# ---------------------------------------------------------------------------
# Corner: refill approval after coverage end expires the prescription
# ---------------------------------------------------------------------------
def test_refill_approve_after_coverage_end_expires_prescription(api):
    """PRD §3.4: "A prescription becomes EXPIRED by system action when a refill
    request or approval is attempted after its coverage_end_date — that is, when
    the current logical-clock date is later than coverage_end_date."
    PRD §3.6: "the parent prescription to be ACTIVE, else ERR_PRESCRIPTION_NOT_ACTIVE
    (409)."

    Design: Corner/state_machines/refill_approve_after_coverage_end_expires_prescription
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    ctx = setup_active_prescription(api, rx_overrides={
        "days_supply_per_fill": 20, "total_refills_authorized": 3, "coverage_days": 20})
    refill = request_refill(api, ctx)
    set_clock(api, "2026-07-01T00:00:00Z")
    resp = api.approve_refill(refill["id"], ctx["provider_headers"])
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE)
    rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                     ctx["provider_headers"]))
    assert rx_after["status"] == "EXPIRED", f"expected EXPIRED, got {rx_after['status']}"
