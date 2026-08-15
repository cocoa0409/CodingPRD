"""Access control and validation-cascade claims: auth headers, role gates,
existence-before-state."""
from test_helpers import (
    EST,
    NO_AUTH_HEADERS,
    ApiErrorId,
    build_user_headers,
    create_customer,
    create_grade,
    create_submitted_quote,
    validate_error,
    validate_success,
)

SIMPLE = {"bbox_width_mm": 50, "bbox_height_mm": 50, "hole_count": 0,
          "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0,
          "finish": "NONE"}


def test_missing_auth_headers_return_400(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their
    operational capacity. A request missing either header, or carrying a role
    value outside the declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/auth_header_missing_returns_400
    """
    resp = api.list_customers(NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   400)


def test_undeclared_role_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside the declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/auth_header_missing_returns_400
    """
    resp = api.list_customers(build_user_headers("anon-1", "Wizard"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   400)


def test_existence_checked_before_state(api):
    """PRD §2.8: "Where a path contains more than one identifier, the server
    resolves identifiers strictly left to right and rejects with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist,
    before examining later segments, the request body, or any business rule."

    Design: Corner/validations/existence_checked_before_state
    """
    resp = api.submit_quote("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", EST)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_estimator_cannot_accept_quote(api):
    """PRD §2.1: "`CustomerRep` is the customer-facing representative who
    accepts or rejects quotes on the customer's behalf and records payments."
    PRD §2.1: "A caller whose role is not in the endpoint's list is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/estimator_cannot_accept_quote
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=SIMPLE)

    resp = api.accept_quote(submitted["id"], EST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    quote = validate_success(api.get_quote(submitted["id"], EST))
    assert quote["status"] == "SUBMITTED"
