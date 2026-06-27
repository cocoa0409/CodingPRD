"""Breadth tests over RBAC enforcement, optimistic concurrency, cross-entity
cascade reconciliation, and immediate-consistency visibility.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    build_user_headers,
    make_customer_headers,
    create_customer, create_unit,
    setup_offered_trade_in, setup_deposited_special_order,
    setup_submitted_financing,
    read_agreement,
    ApiErrorId,
    create_unit_payload, create_financing_payload, reserve_unit_payload, buyout_payload,
    rent_payment_payload, create_special_order_payload, pay_deposit_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Corner / rbac
# ===========================================================================
def test_customer_cannot_create_unit_forbidden(api):
    """PRD §2.1: "When the role is valid but is not permitted to perform the
    requested operation under the access-control matrix, the request is rejected
    with ERR_FORBIDDEN." (POST /units is authorized for SalesAssociate, StoreManager)

    Design: Corner/rbac/customer_cannot_create_unit_forbidden
    """
    customer = create_customer()
    resp = api.create_unit(create_unit_payload(model_name="Rb1 Guitar"),
                           make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_sales_associate_cannot_approve_financing_forbidden(api):
    """PRD §2.1: "When the role is valid but is not permitted to perform the
    requested operation under the access-control matrix, the request is rejected
    with ERR_FORBIDDEN." (POST /financing-applications/{id}/approve is StoreManager)

    Design: Corner/rbac/sales_associate_cannot_approve_financing_forbidden
    """
    customer, application = setup_submitted_financing(
        credit_score=740, principal_cents=120000, term_months=12
    )
    resp = api.approve_financing(application["id"], SA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    after = validate_success(api.get_financing(application["id"], SM), 200)
    assert after["status"] == "SUBMITTED"


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If the X-User-Role header is missing or does not name one of these
    four declared roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    intruder = build_user_headers("intruder-1", "Intruder")
    resp = api.list_units(intruder)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_luthier_cannot_close_ticket_forbidden(api):
    """PRD §2.1: "When the role is valid but is not permitted to perform the
    requested operation under the access-control matrix, the request is rejected
    with ERR_FORBIDDEN." (POST /repair-tickets/{id}/close is SalesAssociate)

    Design: Corner/rbac/luthier_cannot_close_ticket_forbidden
    """
    from test_helpers import setup_ticket_ready, make_luthier_headers
    ticket = setup_ticket_ready(luthier_id="luthier-1")
    assert ticket["status"] == "READY"
    resp = api.close_ticket(ticket["id"], make_luthier_headers("luthier-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    after = validate_success(api.get_ticket(ticket["id"], make_luthier_headers("luthier-1")), 200)
    assert after["status"] == "READY"


# ===========================================================================
# Corner / cross_cutting_complexity_layers
# ===========================================================================
def test_occ_correct_version_reserve_succeeds_and_bumps(api):
    """PRD §2.8: "A reserve request must carry `expected_inventory_unit_version`, a
    non-optional field whose value is the `version` of the target `InventoryUnit` as
    the client last observed it."
    PRD §3.1: "on success the unit moves `AVAILABLE → RESERVED`, the transient
    `reserved_for_customer_id` marker is set to that customer, and the unit's
    `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_reserve_succeeds_and_bumps
    """
    customer = create_customer()
    unit = create_unit()
    assert unit["version"] == 1
    reserved = validate_success(
        api.reserve_unit(unit["id"], reserve_unit_payload(customer["id"], unit["version"]), SA), 200
    )
    assert reserved["status"] == "RESERVED"
    assert reserved["version"] == 2


def test_occ_stale_buyout_rejected(api):
    """PRD §2.8: "If an intervening rent payment or late-fee accrual has advanced the
    agreement's version since that read, the accrued equity — and therefore the
    payoff figure — has changed, so the buyout is operating on a stale quote and is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_buyout_rejected
    """
    customer = create_customer()
    unit = create_unit(list_price_cents=120000, monthly_rent_cents=10000)
    reserved = validate_success(
        api.reserve_unit(unit["id"], reserve_unit_payload(customer["id"], unit["version"]), SA), 200
    )
    agreement = validate_success(
        api.create_agreement(f.create_agreement_payload(customer["id"], reserved["id"],
                                                        plan="RENT_TO_OWN", equity_rate_pct=0.50), SA),
        201,
    )
    cust_headers = make_customer_headers(customer["id"])
    validate_success(api.post_rent_payment(agreement["id"], rent_payment_payload(1), cust_headers), 201)
    validate_success(api.post_rent_payment(agreement["id"], rent_payment_payload(2), cust_headers), 201)
    stale_version = read_agreement(agreement["id"], customer["id"])["version"]
    # an intervening 3rd payment advances the version, making the captured one stale
    validate_success(api.post_rent_payment(agreement["id"], rent_payment_payload(3), cust_headers), 201)
    resp = api.buyout_agreement(agreement["id"], buyout_payload(110000, stale_version), cust_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = read_agreement(agreement["id"], customer["id"])
    assert after["status"] == "ACTIVE"


def test_tradein_accept_cascade_store_credit_reconciled(api):
    """PRD §3.7: "adds the offer to the customer's `store_credit_cents` (a cascade)."
    PRD §3.7: "the fraction is 0.60 for `NEW`, 0.50 for `USED`, and 0.70 for `VINTAGE`"

    Design: Corner/cross_cutting_complexity_layers/tradein_accept_cascade_store_credit_reconciled
    """
    customer, trade_in = setup_offered_trade_in(condition="USED", appraised_value_cents=50000)
    validate_success(api.accept_trade_in(trade_in["id"], SM), 200)
    cust = validate_success(api.get_customer(customer["id"], SM), 200)
    # floor(50000 * 0.50) = 25000
    assert cust["store_credit_cents"] == 25000


def test_financing_approve_cascades_special_order_to_ordered(api):
    """PRD §3.8: "On approval the application transitions `SUBMITTED → APPROVED`, the
    system computes `apr_pct` and `monthly_payment_cents`, and if the application
    names a special order, that order cascades from `QUOTED` or `DEPOSITED` to
    `ORDERED`."

    Design: Corner/cross_cutting_complexity_layers/financing_approve_cascades_special_order_to_ordered
    """
    # Build a DEPOSITED special order and a financing application linked to it, same customer.
    customer, order = setup_deposited_special_order(quoted_price_cents=200000, deposit_amount=50000)
    application = validate_success(
        api.create_financing(
            create_financing_payload(customer["id"], principal_cents=150000, term_months=12,
                                     special_order_id=order["id"]),
            SA,
        ),
        201,
    )
    approved = validate_success(api.approve_financing(application["id"], SM), 200)
    assert approved["status"] == "APPROVED"
    order_after = validate_success(api.get_special_order(order["id"], SA), 200)
    assert order_after["status"] == "ORDERED"


# ===========================================================================
# Corner / consistency_model
# ===========================================================================
def test_immediate_visibility_reserve_reflected_in_same_response(api):
    """PRD §3.1: "on success the unit moves `AVAILABLE → RESERVED`, the transient
    `reserved_for_customer_id` marker is set to that customer, and the unit's
    `version` increments by 1."

    Design: Corner/consistency_model/immediate_visibility_reserve_reflected_in_same_response
    """
    customer = create_customer()
    unit = create_unit()
    reserved = validate_success(
        api.reserve_unit(unit["id"], reserve_unit_payload(customer["id"], unit["version"]), SA), 200
    )
    # no second read needed — the reserve response itself shows RESERVED
    assert reserved["status"] == "RESERVED"
