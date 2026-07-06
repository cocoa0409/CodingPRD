"""Buying from the public (1099-B reporting threshold, ID and approval guards),
IRA account lifecycle, and the IRA-allocation guards enforced at sell settlement.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    set_spot_rate,
    create_product,
    create_inventory_lot,
    create_customer,
    create_pending_ira,
    create_active_ira,
    create_placed_buy_order,
    create_placed_sell_order,
    TEST_USERS,
)

TRADER = TEST_USERS["trader_headers"]
SALES = TEST_USERS["sales_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _reportable_buy_product():
    """GOLD spot 500000; BULLION 1oz product buy_spread 0 → unit_buy_payout 500000."""
    set_spot_rate("GOLD", 500_000)
    return create_product(sku="AU-REP", product_type="BULLION", metal="GOLD",
                          weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                          buy_spread_pct=0.0)


# ─── Rule 6a: reportable threshold exact >= boundary ──────────────────────

def test_buy_order_reportable_true_at_exact_threshold(api):
    """PRD §3.4: "it is true when total_payout_cents is at least the reporting
    threshold of $10,000.00 (that is, 1,000,000 cents), and false otherwise."

    Design: Difficulty/boundary_precision_check/reportable_threshold_exact_boundary
    """
    product = _reportable_buy_product()
    customer = create_customer("Boundary Seller")
    order = create_placed_buy_order(product["id"], customer["id"], quantity=2)
    assert order["total_payout_cents"] == 1_000_000
    assert order["reportable"] is True


def test_buy_order_reportable_false_just_below_threshold(api):
    """PRD §3.4: "it is true when total_payout_cents is at least the reporting
    threshold of $10,000.00 (that is, 1,000,000 cents), and false otherwise."

    Design: Difficulty/boundary_precision_check/reportable_threshold_exact_boundary
    """
    set_spot_rate("GOLD", 499_999)
    product = create_product(sku="AU-REP-BELOW", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.0)
    customer = create_customer("Just Below Seller")
    order = create_placed_buy_order(product["id"], customer["id"], quantity=2)
    assert order["total_payout_cents"] == 999_998
    assert order["reportable"] is False


# ─── Corner: reportable buy blocked without id on file ────────────────────

def test_reportable_buy_without_id_on_file_rejected(api):
    """PRD §3.4: "First, the selling customer must have id_document_on_file set to
    true; if not, settlement is rejected with ERR_ID_REQUIRED_FOR_REPORTABLE
    (HTTP 422)."

    Design: Corner/validations/reportable_buy_without_id_on_file_returns_error
    """
    product = _reportable_buy_product()
    customer = create_customer("No ID Seller", id_document_on_file=False)
    order = create_placed_buy_order(product["id"], customer["id"], quantity=2)
    assert order["reportable"] is True

    res = api.settle_buy_order(order["id"], SALES)
    validate_error(res, "ERR_ID_REQUIRED_FOR_REPORTABLE")


# ─── Corner: reportable buy blocked without compliance approval ───────────

def test_reportable_buy_not_approved_rejected(api):
    """PRD §3.4: "Second, a ComplianceOfficer must have separately approved the
    reportable buy, setting an approval flag on the order; without that approval,
    settlement is rejected with ERR_REPORTABLE_NOT_APPROVED (HTTP 422)."

    Design: Corner/errors/reportable_buy_not_approved_returns_error
    """
    product = _reportable_buy_product()
    customer = create_customer("ID Seller", id_document_on_file=True)
    order = create_placed_buy_order(product["id"], customer["id"], quantity=2)

    res = api.settle_buy_order(order["id"], SALES)
    validate_error(res, "ERR_REPORTABLE_NOT_APPROVED")
    stayed = validate_success(api.get_buy_order(order["id"], SALES), 200)
    assert stayed["status"] == "PLACED"


# ─── Corner + consistency: non-reportable buy settle effects immediate ────

def test_buy_settle_effects_visible_in_response(api):
    """PRD §3.4: "increments the selling customer's lifetime_buy_payout_cents by the
    order's total_payout_cents; and sets the order status to SETTLED."

    Design: Corner/consistency_model/buy_settle_effects_visible_same_request
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-IMM", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    customer = create_customer("Immediate Seller", id_document_on_file=True)
    order = create_placed_buy_order(product["id"], customer["id"], quantity=1)

    settled = validate_success(api.settle_buy_order(order["id"], SALES), 200)
    assert settled["status"] == "SETTLED"
    cust = validate_success(api.get_customer(customer["id"], SALES), 200)
    assert cust["lifetime_buy_payout_cents"] == 192_000


# ─── Corner: IRA approve PENDING -> ACTIVE ────────────────────────────────

def test_approve_ira_account_moves_to_active(api):
    """PRD §3.3: "Approving a pending account moves it from PENDING to ACTIVE, but
    only when the owning customer's id_document_on_file is true".

    Design: Corner/state_machines/approve_ira_account_moves_pending_to_active
    """
    customer = create_customer("IRA Approve", id_document_on_file=True, as_role=COMPLIANCE)
    ira = create_pending_ira(customer["id"], custodian_name="Trust Co", custodian_account_ref="TC-1")
    approved = validate_success(api.approve_ira_account(ira["id"], COMPLIANCE), 200)
    assert approved["status"] == "ACTIVE"


# ─── Corner: IRA placement guard — product not IRA-eligible ───────────────

def test_ira_sell_order_on_non_eligible_product_rejected(api):
    """PRD §3.3: "the referenced product's ira_eligible must be true, or the order
    is rejected with ERR_PRODUCT_NOT_IRA_ELIGIBLE (HTTP 422)".

    Design: Corner/errors/product_not_ira_eligible_on_sell_returns_error
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-NONIRA", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04, ira_eligible=False)
    create_inventory_lot(product["id"], total_qty=5, acquisition_unit_cost_cents=100_000)
    customer = create_customer("IRA NonEligible", id_document_on_file=True, as_role=COMPLIANCE)
    ira = create_active_ira(customer["id"], custodian_name="Trust", custodian_account_ref="T-NE")

    res = api.create_sell_order(
        {"customer_id": customer["id"], "product_id": product["id"], "quantity": 1,
         "ira_account_id": ira["id"]}, SALES)
    validate_error(res, "ERR_PRODUCT_NOT_IRA_ELIGIBLE")


# ─── Rule 7a: sell settle re-checks IRA account is ACTIVE ─────────────────
# NOTE: A PLACED IRA-allocation order cannot reference a non-ACTIVE IRA (§3.3
# placement guard), and IRA status never returns to PENDING; the reachable way
# to make the referenced account non-ACTIVE after a valid placement is to CLOSE
# it. Settlement then re-applies the ACTIVE check (§3.3).

def _placed_ira_order_active():
    """Reachable PLACED IRA-allocation sell order with an ACTIVE IRA + inventory."""
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-IRA-2", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04, ira_eligible=True)
    create_inventory_lot(product["id"], total_qty=5, acquisition_unit_cost_cents=100_000)
    customer = create_customer("IRA Owner Two", id_document_on_file=True, as_role=COMPLIANCE)
    ira = create_active_ira(customer["id"], custodian_name="Vault Trust", custodian_account_ref="VT-9")
    order = create_placed_sell_order(product["id"], customer["id"], quantity=1, ira_account_id=ira["id"])
    return order, ira


def test_sell_settle_rejected_when_ira_not_active(api):
    """PRD §3.3: "When the order is an IRA allocation, the referenced IRA account's
    status must still be ACTIVE at settlement, again guarded by ERR_IRA_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/sell_settle_depends_on_ira_account_active
    """
    order, ira = _placed_ira_order_active()
    validate_success(api.close_ira_account(ira["id"], COMPLIANCE), 200)

    res = api.settle_sell_order(order["id"], SALES)
    validate_error(res, "ERR_IRA_NOT_ACTIVE")
    stayed = validate_success(api.get_sell_order(order["id"], SALES), 200)
    assert stayed["status"] == "PLACED"


def test_sell_settle_succeeds_when_ira_active(api):
    """PRD §3.3: "If the order carries an ira_account_id, the referenced IRA
    account's allocated_value_cents is increased by the order's total_price_cents.
    Finally the order status becomes SETTLED."

    Design: Difficulty/cross_entity_state_dependency/sell_settle_depends_on_ira_account_active
    """
    order, ira = _placed_ira_order_active()
    settled = validate_success(api.settle_sell_order(order["id"], SALES), 200)
    assert settled["status"] == "SETTLED"

    ira_after = validate_success(api.get_ira_account(ira["id"], COMPLIANCE), 200)
    assert ira_after["allocated_value_cents"] == settled["total_price_cents"]
