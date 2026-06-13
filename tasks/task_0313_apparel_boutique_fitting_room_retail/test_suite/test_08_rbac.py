"""Role-based access control: role-exclusive operations, ownership gating, and auth.

Queue B (Corner): rbac section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId, make_customer_headers,
    create_style_payload,
    create_boutique, create_customer, create_style, create_variant,
    create_fitting_room, setup_completed_order_scenario, file_refund_return,
)
from test_helpers.api_client import api_client

ASSOCIATE = TEST_USERS["store_associate_headers"]
MERCH = TEST_USERS["merchandiser_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


def test_customer_cannot_create_style(api):
    """PRD §2.1: "A Merchandiser owns the product catalog: styles, SKU variants, restocks,
    markdown schedules, and lookbooks."
    PRD §2.1: "When an authenticated principal attempts an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    A Customer calling POST /styles (Merchandiser-exclusive) is rejected with
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/customer_cannot_create_style
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])

    res = api.create_style(
        create_style_payload(bq["id"], style_code="X", name="X", category="TOPS",
                             season="SPRING", list_price_cents=1000),
        make_customer_headers(cu["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_associate_cannot_reject_return(api):
    """PRD §2.1: "A StoreManager is the operational override and administrative surface:
    boutique setup, the store clock, store-credit grants, return rejection and voiding,
    and the stylist roster."
    PRD §3.7: "Rejecting a return (REQUESTED -> REJECTED) is a StoreManager action".

    A StoreAssociate calling POST /returns/{id}/reject (StoreManager-exclusive) is rejected
    with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/associate_cannot_reject_return
    """
    bq, cu, style, variant, order, line = setup_completed_order_scenario(
        tax_rate_bps=0, list_price_cents=5000, return_window_days=30)
    rr = file_refund_return(order["id"], line["id"])

    res = api.reject_return(rr["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_release_other_customers_hold(api):
    """PRD §2.1: "a shopper may only create or act on a fitting-room hold, styling
    appointment, return, or special order whose customer_id is their own id, and a
    violation is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Customer A owns a hold; Customer B releasing it (ownership mismatch) is rejected with
    ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/customer_cannot_act_on_other_customers_hold
    """
    bq = create_boutique(tax_rate_bps=875)
    cust_a = create_customer(bq["id"])
    cust_b = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=5)
    room = create_fitting_room(bq["id"])

    hold = get_success_data(api.create_hold(
        {"fitting_room_id": room["id"], "customer_id": cust_a["id"],
         "sku_variant_id": variant["id"], "start_minute": 600, "end_minute": 660},
        make_customer_headers(cust_a["id"])))

    res = api.release_hold(hold["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a role the
    system recognizes, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    A request with an unrecognized X-User-Role to POST /boutiques returns
    ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    bogus_headers = {"X-User-ID": "nobody", "X-User-Role": "Nobody"}
    res = api_client.create_boutique(
        {"name": "X", "state_code": "CA", "tax_rate_bps": 875}, bogus_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
