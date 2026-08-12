"""Authentication, role authorization, ownership scoping, and id-resolution errors."""
from test_helpers import (
    ADMIN,
    ANON,
    COORD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_caregiver_payload,
    create_program,
    api_client,
    make_caregiver_headers,
    validate_error,
    validate_success,
)

_NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and `X-User-Role`."
    PRD §2.1: "Both must be present, and the role must be one of the five declared
    roles — `Anonymous`, `Caregiver`, `Provider`, `Coordinator`, `FunderAdmin`.
    Missing or malformed headers are rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    program = create_program()
    res = api.get_program(program["id"], headers=_NO_AUTH_HEADERS)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_anonymous_cannot_read_caregiver(api):
    """PRD §2.1: "A role that is authenticated but not named in the endpoint's role
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: GET /respite/caregivers/{id} is authorized for Caregiver, Coordinator,
    FunderAdmin — not Anonymous.

    Design: Corner/rbac/anonymous_cannot_read_caregiver
    """
    create_program()
    caregiver = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
    res = api.get_caregiver(caregiver["id"], ANON)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_caregiver_cannot_read_other_caregiver(api):
    """PRD §2.1: "A third check applies when the acting role is entity-backed: if the
    `X-User-ID` does not match the resource's owning caregiver or provider field, the
    request is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/caregiver_cannot_read_other_caregiver
    """
    create_program()
    caregiver_a = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
    caregiver_b = validate_success(
        api.create_caregiver(
            create_caregiver_payload(full_name="Kim Care", email="kim@x.com",
                                     care_recipient_name="Sam Care",
                                     care_recipient_condition="als"),
            ANON),
        201)
    res = api.get_caregiver(caregiver_a["id"], make_caregiver_headers(caregiver_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)


def test_cancel_nonexistent_booking_not_found(api):
    """PRD §2.9: "(5) path and body id resolution (the appropriate
    `ERR_*_NOT_FOUND`)"
    PRD §5: ERR_BOOKING_NOT_FOUND maps to HTTP 404.

    Design: Corner/validations/existence_before_state_not_found_wins
    """
    create_program()
    res = api.cancel_booking(NON_EXISTENT_UUID, {"reason": "ghost"}, COORD)
    validate_error(res, ApiErrorId.ERR_BOOKING_NOT_FOUND, expected_status=404)
