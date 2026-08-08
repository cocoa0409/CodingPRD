"""Role-based access control and entity ownership.

Queue B (Corner): section `rbac`.
"""
from test_helpers import validate_error, ApiErrorId
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import make_clinician_headers, make_physician_headers


def test_clinician_cannot_create_program_returns_forbidden(api):
    """PRD §3.3: "Once a referral is `ACCEPTED`, a `RehabCoordinator` creates the
    `RehabProgram` from it."
    PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation — or an ownership check fails — the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/clinician_cannot_create_program_returns_forbidden
    """
    referral = X.create_accepted_referral(api, risk_stratification="LOW")
    clinician = X.create_clinician(api)
    resp = api.create_program(
        F.create_program_payload(referral["id"]), make_clinician_headers(clinician["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_coordinator_cannot_complete_session_returns_forbidden(api):
    """PRD §3.5: "A `RehabClinician` completes a scheduled session, at which point the
    exercise vitals are recorded".
    PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation — or an ownership check fails — the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/coordinator_cannot_complete_session_returns_forbidden
    """
    ctx = X.setup_active_program(api)
    session = X.schedule_session(ctx)
    resp = api.complete_session(session["id"], {"post_spo2": 96, "rpe": 12}, ctx["coord"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_referral_physician_ownership_mismatch_returns_forbidden(api):
    """PRD §2.1: "in particular, a referring physician may only create a referral in
    which the `physician_id` equals their own `X-User-ID`."

    Design: Corner/rbac/referral_physician_ownership_mismatch_returns_forbidden
    """
    patient = X.create_patient(api)
    physician_1 = X.create_physician(api)
    physician_2 = X.create_physician(api)
    payload = F.create_referral_payload(patient["id"], physician_2["id"], risk_stratification="LOW")
    # Acting as physician_1 but naming physician_2 as physician_id.
    resp = api.create_referral(payload, make_physician_headers(physician_1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
