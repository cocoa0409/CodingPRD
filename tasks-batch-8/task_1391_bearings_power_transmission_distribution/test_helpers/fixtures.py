"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"setup failed" errors. Every helper builds preconditions from scratch via the
PRD-declared endpoints (each test runs against an empty database).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_product_payload, create_customer_payload, create_branch_payload,
    create_branch_stock_payload, create_contract_payload, create_order_payload,
    create_order_line_payload, create_price_file_payload,
    create_consignment_agreement_payload, create_consumption_payload,
    create_warranty_claim_payload, create_return_authorization_payload,
    create_service_shop_payload, create_service_referral_payload,
    create_call_out_payload, create_interchange_record_payload,
)
from .test_users import TEST_USERS, make_customer_plant_headers, make_service_shop_headers

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["pricing_analyst_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]
TECH = TEST_USERS["on_call_technician_headers"]
WARRANTY_ANALYST = TEST_USERS["warranty_analyst_headers"]
QUALITY_ENGINEER = TEST_USERS["quality_engineer_headers"]


# ─── Tier 0: single-entity creation shortcuts ────────────────

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_product(sku=None, list_price_cents=10000, family="BEARING", **overrides):
    payload = create_product_payload(
        list_price_cents=list_price_cents, family=family, **overrides)
    if sku is not None:
        payload["sku"] = sku
    return get_success_data(api_client.create_product(payload, ANALYST))


def create_branch(code=None, **overrides):
    payload = create_branch_payload(**overrides)
    if code is not None:
        payload["code"] = code
    return get_success_data(api_client.create_branch(payload, ADMIN))


def create_customer(name=None, credit_limit_cents=100000000):
    payload = create_customer_payload(credit_limit_cents=credit_limit_cents)
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_customer(payload, CONTRACT_ADMIN))


def create_branch_stock(branch_id, product_id, on_hand_qty=10, factory_lead_time_days=5):
    return get_success_data(api_client.create_branch_stock(
        create_branch_stock_payload(
            branch_id, product_id,
            on_hand_qty=on_hand_qty, factory_lead_time_days=factory_lead_time_days),
        MANAGER))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ANALYST))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, REP))


def get_order_line(line_id):
    return get_success_data(api_client.get_order_line(line_id, REP))


def get_branch_stock(stock_id):
    return get_success_data(api_client.get_branch_stock(stock_id, MANAGER))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, CONTRACT_ADMIN))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, CONTRACT_ADMIN))


def get_reservation(reservation_id):
    return get_success_data(api_client.get_stock_reservation(reservation_id, REP))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_consignment_agreement(agreement_id, CONTRACT_ADMIN))


def get_consumption(consumption_id):
    return get_success_data(api_client.get_consumption(consumption_id, MANAGER))


def get_claim(claim_id):
    return get_success_data(api_client.get_warranty_claim(claim_id, WARRANTY_ANALYST))


def get_return_authorization(return_id):
    return get_success_data(api_client.get_return_authorization(return_id, MANAGER))


def get_price_file(price_file_id):
    return get_success_data(api_client.get_price_file(price_file_id, ANALYST))


def get_call_out(call_out_id):
    return get_success_data(api_client.get_call_out(call_out_id, TECH))


def get_referral(referral_id):
    return get_success_data(api_client.get_service_referral(referral_id, WARRANTY_ANALYST))


def publish_price_file(product_id, new_list_price_cents, effective_at):
    """Publish a price file with a fresh OCC read of the product version."""
    product = get_product(product_id)
    return get_success_data(api_client.create_price_file(
        create_price_file_payload(
            product_id, product["version"],
            new_list_price_cents=new_list_price_cents, effective_at=effective_at),
        ANALYST))


# ─── Tier 1: contracts ───────────────────────────────────────

def create_draft_contract(customer_id, family="BEARING", price_basis="LIST_LESS",
                          discount_pct=0.10, fixed_unit_price_cents=None,
                          lag_protection_days=0,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_to="2027-01-01T00:00:00Z"):
    payload = create_contract_payload(
        customer_id, family=family, price_basis=price_basis,
        discount_pct=discount_pct, lag_protection_days=lag_protection_days,
        effective_from=effective_from, effective_to=effective_to)
    if fixed_unit_price_cents is not None:
        payload["fixed_unit_price_cents"] = fixed_unit_price_cents
    return get_success_data(api_client.create_contract(payload, CONTRACT_ADMIN))


def create_active_contract(customer_id, **kwargs):
    contract = create_draft_contract(customer_id, **kwargs)
    return get_success_data(api_client.activate_contract(contract["id"], CONTRACT_ADMIN))


# ─── Tier 2: entity hierarchy (product + branch + customer + stock) ──

def setup_product_branch_customer(sku=None, list_price_cents=10000,
                                  family="BEARING", branch_code=None,
                                  credit_limit_cents=100000000, **branch_overrides):
    """Product + branch + customer. Returns dict of the three entities."""
    product = create_product(sku=sku, list_price_cents=list_price_cents, family=family)
    branch = create_branch(code=branch_code, **branch_overrides)
    customer = create_customer(credit_limit_cents=credit_limit_cents)
    return {"product": product, "branch": branch, "customer": customer}


def setup_stocked_scenario(sku=None, list_price_cents=10000, family="BEARING",
                           on_hand_qty=10, factory_lead_time_days=5,
                           credit_limit_cents=100000000, **branch_overrides):
    """Product + branch + customer + branch stock. Most common setup."""
    ctx = setup_product_branch_customer(
        sku=sku, list_price_cents=list_price_cents, family=family,
        credit_limit_cents=credit_limit_cents, **branch_overrides)
    ctx["stock"] = create_branch_stock(
        ctx["branch"]["id"], ctx["product"]["id"],
        on_hand_qty=on_hand_qty, factory_lead_time_days=factory_lead_time_days)
    return ctx


# ─── Tier 3: order lifecycle shortcuts ───────────────────────

def create_order(customer_id, branch_id, price_variant=None):
    payload = create_order_payload(customer_id, branch_id)
    if price_variant is not None:
        payload["price_variant"] = price_variant
    return get_success_data(api_client.create_order(payload, REP))


def add_line(order_id, product_id, qty=1, expedite_tier=None):
    payload = create_order_line_payload(product_id, qty=qty)
    if expedite_tier is not None:
        payload["expedite_tier"] = expedite_tier
    return get_success_data(api_client.add_order_line(order_id, payload, REP))


def create_order_with_line(customer_id, branch_id, product_id, qty=1,
                           price_variant=None, expedite_tier=None):
    """DRAFT order with one line. Returns (order, line)."""
    order = create_order(customer_id, branch_id, price_variant=price_variant)
    line = add_line(order["id"], product_id, qty=qty, expedite_tier=expedite_tier)
    return order, line


def create_confirmed_order_with_line(customer_id, branch_id, product_id, qty=1,
                                     price_variant=None, expedite_tier=None):
    """Order with one line, confirmed. Returns (order, line)."""
    order, line = create_order_with_line(
        customer_id, branch_id, product_id, qty=qty,
        price_variant=price_variant, expedite_tier=expedite_tier)
    order = get_success_data(api_client.confirm_order(order["id"], REP))
    return order, line


def reserve_line(line_id, branch_stock_id, qty):
    return get_success_data(api_client.reserve_line(
        line_id, {"branch_stock_id": branch_stock_id, "qty": qty}, REP))


def allocate_line(line_id):
    return get_success_data(api_client.allocate_line(line_id, MANAGER))


def ship_line(line_id):
    return get_success_data(api_client.ship_line(line_id, MANAGER))


def create_shipped_line(customer_id, branch_id, product_id, branch_stock_id,
                        qty=1, price_variant=None, expedite_tier=None):
    """Confirmed order with one line walked to SHIPPED.

    Returns (order, line, reservation).
    """
    order, line = create_confirmed_order_with_line(
        customer_id, branch_id, product_id, qty=qty,
        price_variant=price_variant, expedite_tier=expedite_tier)
    reservation = reserve_line(line["id"], branch_stock_id, qty)
    line = allocate_line(line["id"])
    line = ship_line(line["id"])
    order = get_order(order["id"])
    return order, line, reservation


# ─── Tier 3: consignment lifecycle ───────────────────────────

def create_agreement(customer_id, branch_id, product_id, consigned_qty=10,
                     billing_variant=None):
    payload = create_consignment_agreement_payload(
        customer_id, branch_id, product_id, consigned_qty=consigned_qty)
    if billing_variant is not None:
        payload["billing_variant"] = billing_variant
    return get_success_data(api_client.create_consignment_agreement(payload, CONTRACT_ADMIN))


def report_consumption(agreement_id, qty, customer_id):
    """Report consumption; identity-threaded as the owning CustomerPlant."""
    return get_success_data(api_client.report_consumption(
        agreement_id, create_consumption_payload(qty=qty),
        make_customer_plant_headers(customer_id)))


def invoice_consumption(consumption_id):
    return get_success_data(api_client.invoice_consumption(consumption_id, MANAGER))


def setup_agreement_with_invoiced_consumption(consigned_qty=10, consume_qty=3,
                                              list_price_cents=1000,
                                              billing_variant=None):
    """Agreement + one REPORTED-then-INVOICED consumption.

    Returns dict with product/branch/customer/stock/agreement/consumption.
    """
    ctx = setup_stocked_scenario(
        list_price_cents=list_price_cents, on_hand_qty=consigned_qty + 10)
    agreement = create_agreement(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        consigned_qty=consigned_qty, billing_variant=billing_variant)
    consumption = report_consumption(agreement["id"], consume_qty, ctx["customer"]["id"])
    consumption = invoice_consumption(consumption["id"])
    ctx["agreement"] = agreement
    ctx["consumption"] = consumption
    return ctx


# ─── Tier 3: warranty lifecycle ──────────────────────────────

def file_claim(product_id, filed_by_user_id, order_line_id=None,
               consumption_id=None, failure_mode="FATIGUE",
               operating_hours=100, qty=1):
    """File a warranty claim as WarrantyAnalyst with the given user id."""
    from prd_bench_local_runner.testing import build_user_headers
    payload = create_warranty_claim_payload(
        product_id, failure_mode=failure_mode,
        operating_hours=operating_hours, qty=qty)
    if order_line_id is not None:
        payload["order_line_id"] = order_line_id
    if consumption_id is not None:
        payload["consumption_id"] = consumption_id
    return get_success_data(api_client.create_warranty_claim(
        payload, build_user_headers(filed_by_user_id, "WarrantyAnalyst")))


def begin_analysis(claim_id, engineer_user_id):
    from prd_bench_local_runner.testing import build_user_headers
    return get_success_data(api_client.begin_analysis(
        claim_id, build_user_headers(engineer_user_id, "QualityEngineer")))


def render_verdict(claim_id, verdict, engineer_user_id):
    from prd_bench_local_runner.testing import build_user_headers
    return get_success_data(api_client.render_verdict(
        claim_id, {"verdict": verdict},
        build_user_headers(engineer_user_id, "QualityEngineer")))


def setup_claim_under_analysis(filed_by="wa-1", engineer="qe-1",
                               operating_hours=100, claim_qty=1,
                               line_qty=2, list_price_cents=10000,
                               failure_mode="FATIGUE"):
    """Shipped order line + claim filed and moved to UNDER_ANALYSIS.

    Returns dict with product/branch/customer/stock/order/line/claim.
    """
    ctx = setup_stocked_scenario(list_price_cents=list_price_cents,
                                 on_hand_qty=max(line_qty + 3, 10))
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=line_qty)
    claim = file_claim(ctx["product"]["id"], filed_by,
                       order_line_id=line["id"],
                       operating_hours=operating_hours, qty=claim_qty)
    claim = begin_analysis(claim["id"], engineer)
    ctx.update({"order": order, "line": line, "claim": claim})
    return ctx


def setup_verdicted_claim(verdict, filed_by="wa-1", engineer="qe-1",
                          operating_hours=100, claim_qty=1, line_qty=2,
                          list_price_cents=10000, failure_mode="MISALIGNMENT"):
    """Claim carried through to APPROVED (CONFIRMED_DEFECT) or DENIED."""
    ctx = setup_claim_under_analysis(
        filed_by=filed_by, engineer=engineer, operating_hours=operating_hours,
        claim_qty=claim_qty, line_qty=line_qty, list_price_cents=list_price_cents,
        failure_mode=failure_mode)
    ctx["claim"] = render_verdict(ctx["claim"]["id"], verdict, engineer)
    return ctx


# ─── Tier 3: referral lifecycle ──────────────────────────────

def create_shop(name=None, capabilities=None, region="R1", labor_rate_cents=8000):
    payload = create_service_shop_payload(
        region=region, labor_rate_cents=labor_rate_cents,
        capabilities=capabilities if capabilities is not None else ["BEARING"])
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_service_shop(payload, ADMIN))


def create_referral(claim_id, region, analyst_user_id="wa-1"):
    from prd_bench_local_runner.testing import build_user_headers
    return get_success_data(api_client.create_service_referral(
        create_service_referral_payload(claim_id, region=region),
        build_user_headers(analyst_user_id, "WarrantyAnalyst")))


def setup_misapplication_referral(shop_specs=((8000, "R1"),), referral_region="R1",
                                  filed_by="wa-1", engineer="qe-1"):
    """MISAPPLICATION-verdict claim + shops + one OPEN referral.

    shop_specs: iterable of (labor_rate_cents, region).
    Returns dict with product/branch/customer/stock/order/line/claim/shops/referral.
    """
    ctx = setup_verdicted_claim(
        "MISAPPLICATION", filed_by=filed_by, engineer=engineer,
        failure_mode="MISALIGNMENT")
    shops = [create_shop(region=region, labor_rate_cents=rate)
             for rate, region in shop_specs]
    referral = create_referral(ctx["claim"]["id"], referral_region,
                               analyst_user_id=filed_by)
    ctx.update({"shops": shops, "referral": referral})
    return ctx


# ─── Tier 3: returns lifecycle ───────────────────────────────

def create_return(customer_id, product_id, branch_id, qty=1,
                  condition="SURPLUS", original_unit_price_cents=1000,
                  requester_role="CounterSalesRep", requester_user_id="csr-1"):
    from prd_bench_local_runner.testing import build_user_headers
    if requester_role == "CustomerPlant":
        headers = make_customer_plant_headers(customer_id)
    else:
        headers = build_user_headers(requester_user_id, requester_role)
    return get_success_data(api_client.create_return_authorization(
        create_return_authorization_payload(
            customer_id, product_id, branch_id, qty=qty, condition=condition,
            original_unit_price_cents=original_unit_price_cents),
        headers))


def approve_return(return_id, approver_user_id="bm-1"):
    from prd_bench_local_runner.testing import build_user_headers
    return get_success_data(api_client.approve_return(
        return_id, build_user_headers(approver_user_id, "BranchManager")))


def setup_approved_return(qty=1, condition="SURPLUS", original_unit_price_cents=1000,
                          shipped_qty=3, list_price_cents=1000,
                          requester_user_id="csr-1", approver_user_id="bm-1"):
    """Customer with shipped units + an APPROVED return authorization."""
    ctx = setup_stocked_scenario(list_price_cents=list_price_cents,
                                 on_hand_qty=shipped_qty + 5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=shipped_qty)
    ret = create_return(
        ctx["customer"]["id"], ctx["product"]["id"], ctx["branch"]["id"],
        qty=qty, condition=condition,
        original_unit_price_cents=original_unit_price_cents,
        requester_user_id=requester_user_id)
    ret = approve_return(ret["id"], approver_user_id=approver_user_id)
    ctx.update({"order": order, "line": line, "return": ret})
    return ctx


# ─── Tier 3: call-out lifecycle ──────────────────────────────

def create_call_out(branch_id, customer_id, product_id, qty=1, as_customer=True):
    if as_customer:
        headers = make_customer_plant_headers(customer_id)
    else:
        headers = REP
    return get_success_data(api_client.create_call_out(
        create_call_out_payload(branch_id, customer_id, product_id, qty=qty),
        headers))


def dispatch_call_out(call_out_id, technician_user_id):
    from prd_bench_local_runner.testing import build_user_headers
    return get_success_data(api_client.dispatch_call_out(
        call_out_id, build_user_headers(technician_user_id, "OnCallTechnician")))
