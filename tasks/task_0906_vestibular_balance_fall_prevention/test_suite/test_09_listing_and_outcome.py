"""Listing/filtering, pagination envelope, and the outcome-summary projection."""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    TEST_USERS,
    register_patient, register_referral,
    setup_plan_with_approved_auth, schedule_session,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


# --- B: corner_sessions_filtered_list_by_care_plan ---------------------------

def test_list_sessions_filtered_by_care_plan(api):
    """PRD §2.3: "Sessions may be filtered by `care_plan_id`, `clinician_id`,
    `room_id`, `authorization_id`, `attendance_status`, and `billing_status`."

    Design: Corner/endpoints/corner_sessions_filtered_list_by_care_plan
    """
    ctx = setup_plan_with_approved_auth(api)
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    resp = api.list_sessions(SUPER, params={"care_plan_id": ctx["care_plan"]["id"]})
    data, meta = validate_paginated(resp)
    ids = [row["id"] for row in data]
    assert ids == [s["id"]]


# --- B: corner_pagination_on_referrals_list ----------------------------------

def test_referrals_pagination_first_page(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100." PRD §2.3: "Every
    list response includes `limit`, `offset`, `total_count`, and `has_more` in the
    `meta` object."

    Design: Corner/endpoints/corner_pagination_on_referrals_list
    """
    patient = register_patient(api, insurance_member_id="MEM-C-14")
    register_referral(api, patient["id"], reason="falls one")
    register_referral(api, patient["id"], reason="falls two")
    resp = api.list_referrals(INTAKE, params={"patient_id": patient["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# --- B: corner_outcome_summary_no_reassessment -------------------------------

def test_outcome_summary_without_reassessment(api):
    """PRD §3.9: "when the plan has no finalized reassessment, `clinical_score_delta`
    is null." PRD §3.9: "`improvement_flag`, which is true only when
    `clinical_score_delta` is present and less than zero".

    Design: Corner/calculations/corner_outcome_summary_no_reassessment
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"allowed_amount_cents": 15000, "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    outcome = validate_success(api.get_care_plan_outcome(ctx["care_plan"]["id"], SUPER), 200)
    assert outcome["tier_at_intake"] == "HIGH"
    assert outcome["tier_current"] == "HIGH"
    assert outcome["clinical_score_delta"] is None
    assert outcome["attended_visit_count"] == 1
    assert outcome["total_patient_responsibility_cents"] == 3000
    assert outcome["improvement_flag"] is False
