"""Breast-pump DME qualification window: the inclusive 30-day boundary, the
hospital-grade always-qualifies branch, and the deny-on-window-miss path.

Depth instances (queue A): boundary_precision_check; plus corner-design breadth
for the hospital-grade branch and the window-not-met adjudication.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_pending_dme, create_completed_consult, set_clock, request_dme,
    create_dme_qualification_payload,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_specialist_headers"]


# ─── boundary_precision_check / dme_window_inclusive_30_days_boundary ───────

def test_standard_electric_at_exactly_30_days_qualifies(api):
    """PRD §3.10: "the flag is true when that age in days is at or below the
    thirty-day window, and false beyond it. The boundary is inclusive: an age of
    exactly thirty days qualifies, while thirty-one days does not."

    Infant DOB 2026-06-01, request clock 2026-07-01 (exactly 30 days):
    qualified == true.

    Design: Difficulty/boundary_precision_check/dme_window_inclusive_30_days_boundary
    """
    ctx = create_pending_dme(
        pump_type="STANDARD_ELECTRIC",
        infant_dob="2026-06-01T00:00:00Z",
        consult_clock="2026-06-20T15:00:00Z",
        request_clock="2026-07-01T00:00:00Z")
    assert ctx["dme"]["qualified"] is True, (
        f"30-day boundary must qualify; got {ctx['dme']['qualified']}")


def test_standard_electric_qualified_dme_adjudicates_to_qualified(api):
    """PRD §3.10: "When the `qualified` flag is true the qualification advances
    `PENDING → QUALIFIED`".

    A STANDARD_ELECTRIC qualification at exactly 30 days (qualified true) adjudicates
    to QUALIFIED.

    Design: Difficulty/boundary_precision_check/dme_window_inclusive_30_days_boundary
    """
    ctx = create_pending_dme(
        pump_type="STANDARD_ELECTRIC",
        infant_dob="2026-06-01T00:00:00Z",
        consult_clock="2026-06-20T15:00:00Z",
        request_clock="2026-07-01T00:00:00Z")
    adjudicated = validate_success(
        api.adjudicate_dme_qualification(ctx["dme"]["id"], BILLING), 200)
    assert adjudicated["status"] == "QUALIFIED", (
        f"expected QUALIFIED, got {adjudicated['status']}")


# ─── Corner: calculations / dme_hospital_grade_always_qualifies ─────────────

def test_hospital_grade_always_qualifies_regardless_of_age(api):
    """PRD §3.10: "if `pump_type` is `HOSPITAL_GRADE`, the flag is true — a
    hospital-grade pump always qualifies off a completed consult."

    HOSPITAL_GRADE DME requested at infant age far beyond 30 days (clock 2026-09-01)
    still qualifies.

    Design: Corner/calculations/dme_hospital_grade_always_qualifies
    """
    ctx = create_pending_dme(
        pump_type="HOSPITAL_GRADE",
        infant_dob="2026-06-01T00:00:00Z",
        consult_clock="2026-06-20T15:00:00Z",
        request_clock="2026-09-01T00:00:00Z")
    assert ctx["dme"]["qualified"] is True, (
        f"hospital-grade must qualify; got {ctx['dme']['qualified']}")


# ─── Corner: state_machines / dme_adjudicate_qualify_window_not_met ─────────

def test_standard_electric_past_window_denied_with_false_flag(api):
    """PRD §3.10: "the flag is true when that age in days is at or below the
    thirty-day window, and false beyond it."
    PRD §3.10: "when the flag is false it advances `PENDING → DENIED`."

    STANDARD_ELECTRIC requested at infant age 31 days has qualified false; the
    PENDING qualification adjudicates to DENIED.

    Design: Corner/state_machines/dme_adjudicate_qualify_window_not_met_returns_error
    """
    ctx = create_pending_dme(
        pump_type="STANDARD_ELECTRIC",
        infant_dob="2026-06-01T00:00:00Z",
        consult_clock="2026-06-20T15:00:00Z",
        request_clock="2026-07-02T00:00:00Z")  # 31 days
    assert ctx["dme"]["qualified"] is False, (
        f"31 days must NOT qualify; got {ctx['dme']['qualified']}")

    adjudicated = validate_success(
        api.adjudicate_dme_qualification(ctx["dme"]["id"], BILLING), 200)
    assert adjudicated["status"] == "DENIED", (
        f"expected DENIED, got {adjudicated['status']}")
