"""Role-based access control: forbidden operations and unauthenticated requests."""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
    create_unit_payload,
)

SALES = TEST_USERS["sales_rep_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]
UNKNOWN = TEST_USERS["unknown_role_headers"]


def test_salesrep_cannot_create_unit(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: `POST` `/units` — "Create a unit (INTAKE)" — authorized role `Manager`.

    Design: Corner/endpoints/salesrep_cannot_create_unit_forbidden
    """
    validate_error(api.create_unit(create_unit_payload(), SALES),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_partsclerk_cannot_fund_deal(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.3: "Funding advances a `SIGNED` deal to `FUNDED` and is a `Manager` action."

    Design: Corner/endpoints/partsclerk_cannot_fund_deal_forbidden
    """
    _unit, deal = fixtures.create_signed_deal(
        unit_overrides={"acquisition_type": "CASH"},
        deal_overrides={"sale_price_cents": 9500000, "down_payment_cents": 4000000},
    )
    validate_error(api.fund_deal(deal["id"], PARTS), ApiErrorId.ERR_FORBIDDEN.value)


def test_unrecognized_role_rejected_as_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or its value is not one of
    these four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_unknown_role_rejected
    """
    validate_error(api.create_unit(create_unit_payload(), UNKNOWN),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)
