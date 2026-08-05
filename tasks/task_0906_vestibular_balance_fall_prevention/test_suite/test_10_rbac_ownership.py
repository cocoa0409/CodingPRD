"""RBAC role denials and clinician ownership checks."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_clinician_headers,
    register_patient, register_referral, register_clinician,
    setup_plan_with_approved_auth, schedule_session,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


# --- B: corner_intake_cannot_create_clinician_returns_403 --------------------

def test_intake_cannot_create_clinician(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/corner_intake_cannot_create_clinician_returns_403
    """
    resp = api.create_clinician({"full_name": "Dr PT", "discipline": "PT", "npi": "2000000012"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


# --- B: corner_supervisor_cannot_attend_session_returns_403 ------------------

def test_supervisor_cannot_attend_session(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/corner_supervisor_cannot_attend_session_returns_403
    """
    ctx = setup_plan_with_approved_auth(api)
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    resp = api.attend_session(s["id"], SUPER)  # attend is Clinician-exclusive
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


# --- B: corner_finalize_assessment_not_owner_returns_403 ---------------------

def test_finalize_assessment_by_non_owner_rejected(api):
    """PRD §2.1: "finalizing an assessment or a reassessment, and marking a session
    attended or no-show, all require that the acting clinician's X-User-ID equal
    the target resource's clinician_id. When it does not, the request is rejected
    with ERR_NOT_OWNER."

    Design: Corner/rbac/corner_finalize_assessment_not_owner_returns_403
    """
    patient = register_patient(api, insurance_member_id="MEM-C-17")
    referral = register_referral(api, patient["id"])
    clin1 = register_clinician(api, full_name="Dr PT One")
    clin2 = register_clinician(api, full_name="Dr PT Two")
    assessment = get_success_data(api.create_assessment(
        {"patient_id": patient["id"], "referral_id": referral["id"],
         "clinician_id": clin1["id"], "gait_speed_m_s": 0.55, "tug_seconds": 14.0,
         "berg_balance_score": 18, "medication_count": 5, "self_report_fall_count": 2},
        make_clinician_headers(clin1["id"]),
    ))
    # clin2 (not the owner) attempts to finalize.
    resp = api.finalize_assessment(assessment["id"], make_clinician_headers(clin2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER, 403)
