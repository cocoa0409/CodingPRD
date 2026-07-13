"""Intake, client registration, enrollment creation, eligibility, and RBAC gates."""
import pytest
from test_helpers import (
    api_client as _ac,
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_client,
    create_client_payload,
    create_enrollment_payload,
    create_assignment_payload,
    create_client,
    create_prospect_enrollment,
    setup_enrolled_enrollment,
    make_nurse_headers,
    TEST_USERS,
)


# ─── Difficulty: gestational-age eligibility boundary ───
def test_enrollment_at_gestational_age_ceiling_is_accepted(api, intake_headers):
    """PRD 3.2: "Her gestational age must not exceed the program's intake ceiling of 28
    completed weeks — a value of exactly 28 weeks is eligible and 29 weeks is not;
    exceeding the ceiling is rejected with ERR_GESTATIONAL_AGE_INELIGIBLE."
    PRD 3.2: "A new enrollment starts in PROSPECT status and immediately snapshots the
    mother's current gestational_age_weeks into gestational_age_at_enrollment."

    Design: Difficulty/boundary_precision_check/gestational_age_28_enrolls_29_ineligible
    """
    client = create_client(full_name="C 28", gestational_age_weeks=28)
    res = api.create_enrollment(create_enrollment_payload(client["id"]), intake_headers)
    enrollment = validate_success(res, 201)
    assert enrollment["status"] == "PROSPECT"
    assert enrollment["gestational_age_at_enrollment"] == 28


def test_enrollment_one_week_over_ceiling_is_ineligible(api, intake_headers):
    """PRD 3.2: "Her gestational age must not exceed the program's intake ceiling of 28
    completed weeks — a value of exactly 28 weeks is eligible and 29 weeks is not;
    exceeding the ceiling is rejected with ERR_GESTATIONAL_AGE_INELIGIBLE."

    Design: Difficulty/boundary_precision_check/gestational_age_28_enrolls_29_ineligible
    """
    client = create_client(full_name="C 29", gestational_age_weeks=29)
    res = api.create_enrollment(create_enrollment_payload(client["id"]), intake_headers)
    validate_error(res, ApiErrorId.ERR_GESTATIONAL_AGE_INELIGIBLE.value)


# ─── Corner: client creation defaults ───────────────────
def test_client_create_returns_defaults(api, intake_headers):
    """PRD 3.1: "consent_signed, which starts false and can be flipped to true only
    through the dedicated consent-capture action".
    PRD 3.1: "Every client carries a computed risk_tier, one of LOW, MODERATE, or HIGH,
    defaulting to LOW before any screening exists."

    Design: Corner/entities/client_create_returns_all_fields
    """
    payload = create_client_payload(
        full_name="C New", mother_dob="2002-01-01", first_time_mother=True,
        gestational_age_weeks=22,
    )
    res = api.create_client(payload, intake_headers)
    client = validate_success(res, 201)
    assert_client(client)
    assert client["consent_signed"] is False
    assert client["risk_tier"] == "LOW"


# ─── Corner: not-found on unknown enrollment ────────────
def test_get_unknown_enrollment_returns_not_found(api, intake_headers):
    """PRD 2.8: "every path id and every foreign key supplied in the body must resolve
    to an existing entity, validated left-to-right in the order they appear in the path
    and then the body, and the first unresolved reference yields ERR_NOT_FOUND (404)."

    Design: Corner/entities/enrollment_get_nonexistent_returns_not_found
    """
    res = api.get_enrollment(NON_EXISTENT_UUID, intake_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Corner: missing required field ─────────────────────
def test_create_enrollment_without_client_id_is_validation_error(api, intake_headers):
    """PRD 2.8: "A required body field that is missing, or a field value that violates
    its declared type or enum constraint, yields ERR_VALIDATION (HTTP 422)."

    Design: Corner/entities/enrollment_create_missing_client_id_returns_validation
    """
    res = api.create_enrollment({}, intake_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ─── Corner: one non-exited enrollment per client ───────
def test_second_non_exited_enrollment_for_client_rejected(api, intake_headers):
    """PRD 3.2: "a client may hold at most one enrollment that has not been exited: if
    the client already has an enrollment in any status other than EXITED, creation is
    rejected with ERR_ENROLLMENT_EXISTS."

    Design: Corner/validations/enrollment_second_active_for_client_rejected
    """
    client = create_client(full_name="C Dup", gestational_age_weeks=18)
    create_prospect_enrollment(client["id"])
    res = api.create_enrollment(create_enrollment_payload(client["id"]), intake_headers)
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_EXISTS.value)


# ─── Corner: RBAC denials ───────────────────────────────
def test_nurse_cannot_create_client(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested endpoint per the access matrix in Section 4, the request is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/nurse_cannot_create_client
    """
    nurse = validate_success(
        api.create_nurse(
            {"full_name": "N Rb", "credential_type": "RN"},
            TEST_USERS["program_admin_headers"],
        ),
        201,
    )
    res = api.create_client(
        create_client_payload(full_name="C Rb", gestational_age_weeks=20),
        make_nurse_headers(nurse["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_intake_coordinator_cannot_create_assignment(api, intake_headers):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested endpoint per the access matrix in Section 4, the request is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/intake_cannot_create_assignment
    """
    ctx = setup_enrolled_enrollment()
    payload = create_assignment_payload(
        ctx.enrollment_id, ctx.nurse_id, ctx.enrollment_version
    )
    res = api.create_assignment(payload, intake_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
