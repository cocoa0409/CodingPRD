"""Validation priority ordering, authentication, RBAC denials, and
segregation-of-duties precedence."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    build_user_headers, NON_EXISTENT_UUID,
    create_product, create_branch, create_customer, create_branch_stock,
    create_order_with_line, create_confirmed_order_with_line,
    create_shipped_line, create_agreement, report_consumption,
    create_return, create_product_payload, create_contract_payload,
    create_price_file_payload,
    setup_stocked_scenario, get_order, get_return_authorization,
    get_consumption,
    make_customer_plant_headers,
    ApiErrorId, TEST_USERS,
)

ANALYST = TEST_USERS["pricing_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_cancelled_over_limit_order():
    """Customer limit 1000; DRAFT order with one 10000-cent line, cancelled."""
    product = create_product(sku="BRG-6312", list_price_cents=10000)
    branch = create_branch(code="MSP-09")
    customer = create_customer(name="North Star Plant", credit_limit_cents=1000)
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    validate_success(api_client.cancel_order(order["id"], REP), 200)
    return {"product": product, "branch": branch, "customer": customer,
            "order": order, "line": line}


def test_cancelled_order_confirm_reports_state_error_not_credit(api):
    """PRD §2.5: "When a request violates several rules, the first failing
    check by the following priority order determines the response; later checks
    are not evaluated against a request that has already failed."
    PRD §2.5: "Priority 5: the target resource must be in the state the
    requested transition requires (the state-specific 409 errors such as
    `ERR_ORDER_NOT_CONFIRMABLE` or `ERR_CLAIM_NOT_UNDER_ANALYSIS`)."
    PRD §2.5: "Priority 10, last: capacity and credit rules —
    `ERR_INSUFFICIENT_AVAILABLE_STOCK` (409) on reservation and consignment
    placement, `ERR_CUSTOMER_CREDIT_HOLD` (402) and `ERR_CREDIT_LIMIT_EXCEEDED`
    (402) on order confirm."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_order_confirm_state_beats_credit_fiscal
    """
    ctx = _setup_cancelled_over_limit_order()
    res = api.confirm_order(ctx["order"]["id"], REP)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_CONFIRMABLE, expected_status=409)
    order = get_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["total_cents"] == 0, "a rejected confirm fires no pricing side effects"


def test_over_limit_order_confirm_reports_credit_error_before_cancel(api):
    """PRD §3.4: "the customer's `open_receivables_cents` plus the order's
    freshly computed `total_cents` must not exceed `credit_limit_cents`
    (`ERR_CREDIT_LIMIT_EXCEEDED`, 402)."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_order_confirm_state_beats_credit_fiscal
    """
    # Control: the same over-limit order, confirmed while still DRAFT, fails on
    # the fiscal rule — proving both violations coexisted in the cancelled case.
    product = create_product(sku="BRG-6312", list_price_cents=10000)
    branch = create_branch(code="MSP-09")
    customer = create_customer(name="North Star Plant", credit_limit_cents=1000)
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    res = api.confirm_order(order["id"], REP)
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, expected_status=402)
    assert get_order(order["id"])["fulfillment_status"] == "DRAFT"


def _setup_return_over_qty(sku="SEL-220", price=9000):
    """Customer shipped 2 of the product; return qty 5 requested by csr-1."""
    ctx = setup_stocked_scenario(list_price_cents=price, on_hand_qty=10)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=2)
    ret = create_return(ctx["customer"]["id"], ctx["product"]["id"],
                        ctx["branch"]["id"], qty=5, condition="SURPLUS",
                        original_unit_price_cents=price,
                        requester_user_id="csr-1")
    ctx.update({"order": order, "line": line, "return": ret})
    return ctx


def test_return_approve_sod_error_beats_qty_error(api):
    """PRD §2.5: "Priority 6: segregation of duties — ... the return approver
    or rejector must differ from the return's `requested_by`
    (`ERR_RETURN_SOD_APPROVAL`, 403). ... Priority 9: cross-entity referential
    rules (for example ... `ERR_RETURN_QTY_EXCEEDS_SHIPPED` ...)".

    Design: Difficulty/priority_pair_validation_conflict/return_approve_sod_beats_qty_referential
    """
    ctx = _setup_return_over_qty()
    res = api.approve_return(
        ctx["return"]["id"], build_user_headers("csr-1", "BranchManager"))
    validate_error(res, ApiErrorId.ERR_RETURN_SOD_APPROVAL, expected_status=403)
    ret = get_return_authorization(ctx["return"]["id"])
    assert ret["status"] == "REQUESTED"
    assert ret["approved_by"] is None


def test_return_approve_by_distinct_user_reaches_qty_check(api):
    """PRD §3.8: "the approver or rejector's `X-User-ID` must differ from
    `requested_by` (`ERR_RETURN_SOD_APPROVAL`, 403)" and "requires the
    authorized `qty` not exceed the customer's cumulative shipped quantity of
    this product across all orders (`ERR_RETURN_QTY_EXCEEDS_SHIPPED`, 409)".

    Design: Difficulty/priority_pair_validation_conflict/return_approve_sod_beats_qty_referential
    """
    # Control: with SoD satisfied, the coexisting referential violation
    # surfaces — proving both violations coexisted in the SoD case.
    ctx = _setup_return_over_qty()
    res = api.approve_return(
        ctx["return"]["id"], build_user_headers("bm-1", "BranchManager"))
    validate_error(res, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_SHIPPED,
                   expected_status=409)


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)
    before any other check runs."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    res = api.create_product(
        create_product_payload(sku="BRG-6027", list_price_cents=1000), {})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)


def test_not_found_beats_state_check(api):
    """PRD §2.5: "Because existence (priority 3) precedes state (priority 5), a
    request naming a nonexistent product must fail with 404 even when the
    request also violates a state rule".

    Design: Corner/validations/not_found_beats_state_check
    """
    res = api.confirm_order(NON_EXISTENT_UUID, REP)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_FOUND, expected_status=404)


def test_rbac_pricing_analyst_cannot_create_contract(api):
    """PRD §2.1: "If the named role is not permitted to invoke the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)." PRD §4: POST /motion/contracts is authorized for
    ContractAdministrator only.

    Design: Corner/rbac/rbac_pricing_analyst_cannot_create_contract
    """
    customer = create_customer(name="RBAC Plant", credit_limit_cents=1000000)
    res = api.create_contract(
        create_contract_payload(customer["id"], family="BEARING"), ANALYST)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_rbac_contract_admin_cannot_publish_price_file(api):
    """PRD §2.1: "If the named role is not permitted to invoke the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)." PRD §4: POST /motion/price-files is authorized for
    PricingAnalyst only.

    Design: Corner/rbac/rbac_contract_admin_cannot_publish_price_file
    """
    product = create_product(sku="BRG-6047", list_price_cents=1000)
    res = api.create_price_file(
        create_price_file_payload(product["id"], product["version"],
                                  new_list_price_cents=2000,
                                  effective_at="2026-09-01T00:00:00Z"),
        CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_rbac_quality_engineer_cannot_file_claim(api):
    """PRD §2.1: "If the named role is not permitted to invoke the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)." PRD §4: POST /motion/warranty-claims is authorized for
    WarrantyAnalyst only.

    Design: Corner/rbac/rbac_quality_engineer_cannot_file_claim
    """
    product = create_product(sku="BRG-6048", list_price_cents=1000)
    res = api.create_warranty_claim(
        {"product_id": product["id"], "failure_mode": "FATIGUE",
         "operating_hours": 10, "qty": 1},
        build_user_headers("qe-z", "QualityEngineer"))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_rbac_customer_plant_cannot_invoice_consumption(api):
    """PRD §2.1: "If the named role is not permitted to invoke the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)." PRD §4: POST
    /motion/consignment-consumptions/{id}/invoice is authorized for
    BranchManager only.

    Design: Corner/rbac/rbac_customer_plant_cannot_invoice_consumption
    """
    ctx = setup_stocked_scenario(list_price_cents=1000, on_hand_qty=10)
    agreement = create_agreement(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        consigned_qty=5)
    consumption = report_consumption(agreement["id"], 1, ctx["customer"]["id"])
    res = api.invoice_consumption(
        consumption["id"], make_customer_plant_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    assert get_consumption(consumption["id"])["status"] == "REPORTED"
