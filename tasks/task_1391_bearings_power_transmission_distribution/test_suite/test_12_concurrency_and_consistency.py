"""Optimistic concurrency control on the three versioned write operations,
eager receivables reconciliation, and immediate response consistency."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_product, create_branch, create_customer, create_branch_stock,
    create_order, add_line, create_order_with_line, create_confirmed_order_with_line,
    create_shipped_line, create_active_contract, create_agreement,
    report_consumption, invoice_consumption, publish_price_file,
    reserve_line, set_clock,
    setup_stocked_scenario,
    get_order, get_order_line, get_product, get_agreement,
    get_branch_stock, get_customer, get_price_file,
    ApiErrorId, TEST_USERS,
)

ANALYST = TEST_USERS["pricing_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def test_occ_price_file_publish_stale_version(api):
    """PRD §2.6: "Publishing a price file requires `expected_product_version`,
    the client's last-observed `version` of the product. Publishing supersedes
    the product's currently pending price file, so a writer whose view predates
    another publish would unknowingly supersede a file it never saw; the
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a fresh
    read of the product first."

    Design: Corner/cross_cutting_complexity_layers/occ_price_file_publish_stale_version
    """
    product = create_product(sku="BRG-6050", list_price_cents=1000)
    stale_version = product["version"]
    pf1 = validate_success(api.create_price_file(
        {"product_id": product["id"], "new_list_price_cents": 1500,
         "effective_at": "2026-08-10T00:00:00Z",
         "expected_product_version": stale_version}, ANALYST), 201)

    res = api.create_price_file(
        {"product_id": product["id"], "new_list_price_cents": 1600,
         "effective_at": "2026-08-12T00:00:00Z",
         "expected_product_version": stale_version}, ANALYST)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fresh_version = get_product(product["id"])["version"]
    pf2 = validate_success(api.create_price_file(
        {"product_id": product["id"], "new_list_price_cents": 1600,
         "effective_at": "2026-08-12T00:00:00Z",
         "expected_product_version": fresh_version}, ANALYST), 201)
    assert pf2["status"] == "PENDING"
    assert get_price_file(pf1["id"])["status"] == "SUPERSEDED"


def test_occ_order_reprice_stale_version(api):
    """PRD §2.6: "Re-pricing an order requires `expected_order_version` in the
    request body, holding the client's last-observed `version` of the sales
    order. If the order's current `version` does not match — because a line was
    added, an expedite tier changed, the order was confirmed, or an earlier
    reprice ran since the client last read it — the reprice is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "It is the mechanism for picking up contracts that became
    `ACTIVE` or price files that became `EFFECTIVE` since the last pricing."

    Design: Corner/cross_cutting_complexity_layers/occ_order_reprice_stale_version
    """
    set_clock("2026-08-01T09:00:00Z")
    product = create_product(sku="BRG-6051", list_price_cents=10000)
    branch = create_branch(code="OCC-35")
    customer = create_customer(name="OCC Plant", credit_limit_cents=1000000)
    order = create_order(customer["id"], branch["id"])
    stale_version = order["version"]  # creation-time version
    add_line(order["id"], product["id"], qty=1)
    validate_success(api.confirm_order(order["id"], REP), 200)
    current_version = get_order(order["id"])["version"]
    # A 10% LIST_LESS contract becomes ACTIVE after the confirm.
    create_active_contract(
        customer["id"], family="BEARING", price_basis="LIST_LESS",
        discount_pct=0.10, lag_protection_days=0,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")

    res = api.reprice_order(order["id"],
                            {"expected_order_version": stale_version}, REP)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    repriced = validate_success(api.reprice_order(
        order["id"], {"expected_order_version": current_version}, REP), 200)
    assert repriced["total_cents"] == 9000, (
        f"newly ACTIVE 10% LIST_LESS contract applies at the order anchor; "
        f"got {repriced['total_cents']}")


def test_occ_agreement_amend_stale_version(api):
    """PRD §2.6: "Amending a consignment agreement's quantity requires
    `expected_agreement_version`, the client's last-observed `version` of the
    agreement. A consumption reported after that read legitimately advanced the
    agreement (its `consumed_qty` changed), so a stale amendment is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and must be rebased on a fresh read."
    PRD §3.5: "the shelf `on_hand_qty` adjusts by the delta, `remaining_qty`
    recomputes".

    Design: Corner/cross_cutting_complexity_layers/occ_agreement_amend_stale_version
    """
    product = create_product(sku="BRG-6052", list_price_cents=1000)
    branch = create_branch(code="OCA-36")
    customer = create_customer(name="OCC Consign Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=20)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=10)
    stale_version = agreement["version"]
    report_consumption(agreement["id"], 4, customer["id"])  # advances version

    res = api.amend_consignment_agreement(
        agreement["id"],
        {"consigned_qty": 12, "expected_agreement_version": stale_version},
        CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fresh_version = get_agreement(agreement["id"])["version"]
    amended = validate_success(api.amend_consignment_agreement(
        agreement["id"],
        {"consigned_qty": 12, "expected_agreement_version": fresh_version},
        CONTRACT_ADMIN), 200)
    assert amended["consigned_qty"] == 12
    assert amended["remaining_qty"] == 8  # 12 - 4 consumed
    # Shelf: 20 - 10 placed - 2 pulled by the amendment = 8.
    assert get_branch_stock(stock["id"])["on_hand_qty"] == 8


def test_derived_open_receivables_multi_source_reconciliation(api):
    """PRD §3.9: "It is defined as: the sum over the customer's sales orders in
    `INVOICED` or `PARTIALLY_PAID` billing of `total_cents` minus `paid_cents`;
    plus the sum over consumptions of the customer's agreements in `INVOICED`
    status of `billed_amount_cents` minus `offset_applied_cents`; ... The value
    may go negative, representing a credit balance. Order invoicing and payment,
    consumption invoicing and crediting, call-out fulfillment, warranty credit
    issuance, and return credit issuance each trigger the recomputation."

    Design: Corner/cross_cutting_complexity_layers/derived_open_receivables_multi_source_reconciliation
    """
    p1 = create_product(sku="BRG-6054", list_price_cents=10000)
    p2 = create_product(sku="BRG-6055", list_price_cents=2000)
    branch = create_branch(code="REC-38")
    customer = create_customer(name="Reconcile Plant", credit_limit_cents=1000000)
    stock1 = create_branch_stock(branch["id"], p1["id"], on_hand_qty=5)
    create_branch_stock(branch["id"], p2["id"], on_hand_qty=5)

    order, line, _ = create_shipped_line(
        customer["id"], branch["id"], p1["id"], stock1["id"], qty=1)
    validate_success(api.invoice_order(order["id"], MANAGER), 200)

    agreement = create_agreement(customer["id"], branch["id"], p2["id"],
                                 consigned_qty=3)
    consumption = report_consumption(agreement["id"], 1, customer["id"])
    invoice_consumption(consumption["id"])
    assert get_customer(customer["id"])["open_receivables_cents"] == 12000, (
        "10000 order invoice + 2000 consignment invoice")

    validate_success(api.record_payment(
        order["id"], {"amount_cents": 2500}, MANAGER), 200)
    assert get_customer(customer["id"])["open_receivables_cents"] == 9500, (
        "partial payment 2500 leaves 7500 order balance + 2000")

    validate_success(api.credit_consumption(consumption["id"], MANAGER), 200)
    assert get_customer(customer["id"])["open_receivables_cents"] == 7500, (
        "consumption credit removes its full 2000 billing")


def test_confirm_response_carries_computed_totals_immediately(api):
    """PRD §3.9: "The customer's `open_receivables_cents` is a derived, eagerly
    recomputed figure — visible in the same response that caused any change,
    under immediate consistency."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/confirm_response_carries_computed_totals_immediately
    """
    product = create_product(sku="BRG-6056", list_price_cents=3000)
    branch = create_branch(code="IMM-39")
    customer = create_customer(name="Immediate Plant", credit_limit_cents=1000000)
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=2)
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    # The confirm response itself carries computed totals — no follow-up GET.
    assert confirmed["subtotal_cents"] == 6000
    assert confirmed["total_cents"] == 6000
    assert confirmed["fulfillment_status"] == "CONFIRMED"
