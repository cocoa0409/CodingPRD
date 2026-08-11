"""Authentication and the traveller's order-membership test."""

from test_helpers import (
    NO_AUTH_HEADERS,
    ApiErrorId,
    make_traveler_headers,
    new_applicant,
    new_catalog_item,
    new_order,
    quote,
    read_order,
    set_clock,
    validate_error,
)


def test_a_request_without_a_role_header_is_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is absent, or whose value is not one
    of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "| 1 | `ERR_UNAUTHENTICATED` | 401 | `X-User-Role` is present and names one
    of the six declared roles; `X-User-ID` is present whenever the role is `CaseManager`,
    `Traveler`, `ComplianceOfficer`, `AgencyLiaison` or `CourierOps`. Applies to every
    endpoint. |"

    Design: Corner/rbac/corner_missing_role_header_returns_unauthenticated
    """
    set_clock()
    resp = api.get_order("00000000-0000-4000-8000-000000000000", NO_AUTH_HEADERS)
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert error["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND.value, (
        "the authentication rung runs before any existence rung"
    )


def test_a_traveller_from_another_order_may_not_pay(api):
    """PRD §2.1: "When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting
    `Applicant` row. A `Traveler` may only act on, or read, an order that carries an
    applicant whose `id` equals `X-User-ID`."
    PRD §2.1: "A `Traveler` request that resolves to an order carrying no such applicant is
    rejected with `ERR_NOT_ORDER_MEMBER` (HTTP 403)."

    Design: Corner/rbac/corner_traveler_from_another_order_cannot_pay
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order_a = new_order(catalog["id"], travel_date="2026-09-01", return_date="2026-09-20")
    order_b = new_order(catalog["id"], travel_date="2026-09-02", return_date="2026-09-21")
    applicant_a = new_applicant(order_a["id"], full_name="Owner A")
    new_applicant(order_b["id"], full_name="Owner B", date_of_birth="1991-04-05")
    quote(order_b["id"])

    resp = api.create_payment(
        order_b["id"], {"amount_cents": 26500}, make_traveler_headers(applicant_a["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ORDER_MEMBER.value)

    stored = read_order(order_b["id"])
    assert stored["collected_cents"] == 0
    assert stored["payment_status"] == "UNPAID"
