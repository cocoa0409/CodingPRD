"""Cross-cutting access control, pagination, and clock guards."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_headers,
    create_subject_payload,
    create_case_payload,
    register_subject,
    file_referral,
    accept_referral,
)

INTAKE = TEST_USERS["intake_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_unknown_role_rejected(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_role_header
    """
    headers = make_headers("NotARole", "no-auth-1")
    resp = api.create_subject(create_subject_payload(name="No Auth", ssn_last4="3535"), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_intake_forbidden_from_opening_case(api):
    """PRD 2.1: "If the headers are valid but the acting role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD 3.2: "An `Investigator` opens a **Case** from an `ACCEPTED` referral by supplying
    its `referral_id`."

    Design: Corner/validations/forbidden_intake_opens_case
    """
    subject = register_subject(api)
    referral = file_referral(api, subject["id"], source="PUBLIC", summary="RBAC case")
    accept_referral(api, referral["id"])
    # Opening a case is an Investigator-exclusive operation; Intake is forbidden.
    resp = api.create_case(create_case_payload(referral["id"]), INTAKE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_pagination_limit_zero_rejected(api):
    """PRD 2.3: "A `limit` outside the inclusive range from 1 to 100, or a negative
    `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/pagination_invalid_limit_zero
    """
    resp = api.list_referrals(INTAKE, params={"limit": 0, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_clock_backwards_rejected(api):
    """PRD 2.6: "The clock may only move forward: an attempt to set it to a value earlier
    than its current reading is rejected with `ERR_CLOCK_BACKWARDS` (HTTP 422)."

    Design: Corner/validations/clock_backwards_rejected
    """
    resp = api.set_clock({"to_iso8601": "2026-04-01T00:00:00Z"}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_CLOCK_BACKWARDS.value)
