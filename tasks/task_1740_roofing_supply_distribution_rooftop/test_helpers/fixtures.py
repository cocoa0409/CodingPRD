"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only: branch -> product -> lot -> contractor account ->
job account -> takeoff -> quote -> convert -> confirm -> slot -> delivery ->
dispatch/complete -> invoice -> payment, plus the surge-event / allocation and
lien chains.

Identity threading: Contractor calls are entity-backed by ContractorAccount —
every ownership-gated call uses make_contractor_headers(account["id"]).
Setup calls use the lenient get_success_data validator so a broken
precondition surfaces as a clear setup error rather than an assertion maze.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_branch_payload,
    create_delivery_slot_payload,
    create_job_account_payload,
    create_product_payload,
    create_surge_event_payload,
    create_takeoff_payload,
    file_damage_claim_payload,
    receive_inventory_lot_payload,
    request_allocation_payload,
    request_return_payload,
    create_contractor_account_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def make_branch(code="BR-T1", **overrides):
    payload = create_branch_payload(branch_code=code, **overrides)
    return get_success_data(api_client.create_branch(payload, ADMIN))


def make_product(sku="SH-T1", price=2000, bps=3.0, **overrides):
    payload = create_product_payload(
        sku=sku, base_price_per_bundle_cents=price, bundles_per_square=bps,
        **overrides)
    return get_success_data(api_client.create_product(payload, ADMIN))


def make_lot(branch_id, product_id, on_hand=500, lot_code="LOT-1"):
    payload = receive_inventory_lot_payload(
        product_id, lot_code=lot_code, on_hand_bundles=on_hand)
    return get_success_data(
        api_client.receive_inventory_lot(branch_id, payload, WAREHOUSE))


def make_account(credit_limit=10_000_000, tier="STANDARD", certs=None,
                 name="Test Roofing Co"):
    overrides = {}
    if certs is not None:
        overrides["manufacturer_certifications"] = certs
    payload = create_contractor_account_payload(
        company_name=name, credit_limit_cents=credit_limit, pricing_tier=tier,
        **overrides)
    return get_success_data(api_client.create_contractor_account(payload, CREDIT))


def make_job(account_id, job_name="Test Job", site_address="1 Oak St"):
    payload = create_job_account_payload(job_name=job_name,
                                         site_address=site_address)
    return get_success_data(
        api_client.create_job_account(account_id, payload, CREDIT))


def make_slot(branch_id, slot_date="2026-08-12", window="AM",
              equipment_type="GROUND", capacity=2):
    payload = create_delivery_slot_payload(
        slot_date=slot_date, window=window, equipment_type=equipment_type,
        capacity=capacity)
    return get_success_data(api_client.create_delivery_slot(branch_id, payload,
                                                            DISPATCH))


# ---------------------------------------------------------------------------
# Tier 2: takeoff -> order chain
# ---------------------------------------------------------------------------

def create_takeoff(job_account_id, product_id, roof_squares=5.0,
                   waste_factor_pct=0, valley_ridge_linear_feet=0):
    """Create a takeoff (born DRAFT). Returns the takeoff."""
    payload = create_takeoff_payload(
        product_id, roof_squares=roof_squares, waste_factor_pct=waste_factor_pct,
        valley_ridge_linear_feet=valley_ridge_linear_feet)
    return get_success_data(api_client.create_takeoff(job_account_id, payload, SALES))


def create_quoted_takeoff(job_account_id, product_id, roof_squares=5.0,
                          waste_factor_pct=0, valley_ridge_linear_feet=0):
    """Create + quote. Returns the QUOTED takeoff."""
    takeoff = create_takeoff(job_account_id, product_id, roof_squares,
                             waste_factor_pct, valley_ridge_linear_feet)
    return get_success_data(api_client.quote_takeoff(takeoff["id"], SALES))


def convert_to_order(takeoff_id, branch_id, account_id):
    """QUOTED takeoff -> QUOTED order, by the owning contractor."""
    return get_success_data(api_client.convert_takeoff(
        takeoff_id, branch_id, make_contractor_headers(account_id)))


def confirm_order(order_id, account_id):
    """Confirm with a fresh account version read (OCC). Returns the CONFIRMED
    order."""
    account = get_success_data(api_client.get_contractor_account(account_id, CREDIT))
    return get_success_data(api_client.confirm_order(
        order_id, account["version"], make_contractor_headers(account_id)))


# ---------------------------------------------------------------------------
# Tier 3: the order workspace (branch + product + lot + account + job + order)
# ---------------------------------------------------------------------------

def setup_order_scenario(*, branch_code="BR-S1", sku="SH-S1", price=2000,
                         bps=3.0, on_hand=500, lot_code="LOT-1",
                         credit_limit=10_000_000, tier="STANDARD", certs=None,
                         company_name="Scenario Roofing Co",
                         manufacturer_name=None, requires_certified_installer=False,
                         roof_squares=5.0, waste_factor_pct=0,
                         valley_ridge_linear_feet=0, confirm=True):
    """Branch + product + lot + account + job + QUOTED takeoff converted to an
    order. When confirm=True the order is CONFIRMED. Returns a context dict."""
    branch = make_branch(branch_code)
    product_kwargs = {}
    if manufacturer_name is not None:
        product_kwargs["manufacturer_name"] = manufacturer_name
    if requires_certified_installer:
        product_kwargs["requires_certified_installer"] = True
    product = make_product(sku, price=price, bps=bps, **product_kwargs)
    lot = make_lot(branch["id"], product["id"], on_hand=on_hand,
                   lot_code=lot_code)
    account = make_account(credit_limit=credit_limit, tier=tier, certs=certs,
                           name=company_name)
    job = make_job(account["id"])
    takeoff = create_quoted_takeoff(job["id"], product["id"], roof_squares,
                                    waste_factor_pct, valley_ridge_linear_feet)
    order = convert_to_order(takeoff["id"], branch["id"], account["id"])
    ctx = {"branch": branch, "product": product, "lot": lot,
           "account": account, "job": job, "takeoff": takeoff, "order": order}
    if confirm:
        ctx["order"] = confirm_order(order["id"], account["id"])
    return ctx


def schedule_delivery(order_id, branch_id, slot_date="2026-08-12", window="AM",
                      equipment_type="GROUND", capacity=2):
    """Create a slot + schedule the delivery into it. Returns (slot, delivery)."""
    slot = make_slot(branch_id, slot_date=slot_date, window=window,
                     equipment_type=equipment_type, capacity=capacity)
    delivery = get_success_data(api_client.schedule_delivery(
        order_id, slot["id"], equipment_type, DISPATCH))
    return slot, delivery


def dispatch_and_complete(delivery_id):
    """SCHEDULED -> EN_ROUTE -> DELIVERED. Returns the DELIVERED delivery."""
    get_success_data(api_client.dispatch_delivery(delivery_id, DISPATCH))
    return get_success_data(api_client.complete_delivery(delivery_id, DISPATCH))


# ---------------------------------------------------------------------------
# Tier 4: lifecycle shortcuts (delivered / invoiced / paid orders)
# ---------------------------------------------------------------------------

def setup_delivered_order(*, slot_date="2026-08-12", equipment_type="GROUND",
                          **scenario_kwargs):
    """CONFIRMED order with one fully DELIVERED delivery covering all lines."""
    ctx = setup_order_scenario(confirm=True, **scenario_kwargs)
    slot, delivery = schedule_delivery(
        ctx["order"]["id"], ctx["branch"]["id"], slot_date=slot_date,
        equipment_type=equipment_type)
    ctx["slot"] = slot
    ctx["delivery"] = dispatch_and_complete(delivery["id"])
    ctx["order"] = get_success_data(
        api_client.get_order(ctx["order"]["id"], CREDIT))
    return ctx


def setup_invoiced_order(**scenario_kwargs):
    """Delivered order with the invoice posted (payment_status INVOICED)."""
    ctx = setup_delivered_order(**scenario_kwargs)
    ctx["order"] = get_success_data(
        api_client.invoice_order(ctx["order"]["id"], CREDIT))
    ctx["account"] = get_success_data(
        api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
    ctx["job"] = get_success_data(
        api_client.get_job_account(ctx["job"]["id"], CREDIT))
    return ctx


def setup_paid_order(**scenario_kwargs):
    """Invoiced order fully paid (payment_status PAID)."""
    ctx = setup_invoiced_order(**scenario_kwargs)
    total = ctx["order"]["total_cents"]
    get_success_data(api_client.post_payment(
        ctx["account"]["id"],
        {"amount_cents": total, "job_account_id": ctx["job"]["id"]}, CREDIT))
    ctx["order"] = get_success_data(
        api_client.get_order(ctx["order"]["id"], CREDIT))
    ctx["account"] = get_success_data(
        api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
    return ctx


def first_order_line(order_id):
    """Fetch the single OrderLine of a converted order."""
    lines, _meta = _list_order_lines(order_id)
    assert len(lines) == 1, f"expected exactly 1 order line, got {len(lines)}"
    return lines[0]


def _list_order_lines(order_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_order_lines(order_id, WAREHOUSE))


# ---------------------------------------------------------------------------
# Tier 5: returns, claims, warranty, lien, surge chains
# ---------------------------------------------------------------------------

def setup_approved_return(quantity_bundles, opened_bundles=0, *, roof_squares=5.0,
                          bps=3.0, price=2000, branch_code="BR-R1", sku="SH-R1"):
    """Delivered order + APPROVED return. Returns ctx incl. return_ and line."""
    ctx = setup_delivered_order(branch_code=branch_code, sku=sku,
                                roof_squares=roof_squares, bps=bps, price=price)
    line = first_order_line(ctx["order"]["id"])
    ret = get_success_data(api_client.request_return(
        ctx["order"]["id"],
        request_return_payload(line["id"], quantity_bundles=quantity_bundles,
                               opened_bundles=opened_bundles),
        make_contractor_headers(ctx["account"]["id"])))
    ret = get_success_data(api_client.approve_return(ret["id"], MANAGER))
    ctx["line"] = line
    ctx["return"] = ret
    return ctx


def setup_filed_claim(claimed_bundles=5, *, branch_code="BR-C1", sku="SH-C1",
                      price=3000, roof_squares=10.0, bps=3.0):
    """Delivered order + FILED damage claim by the owning contractor."""
    ctx = setup_delivered_order(branch_code=branch_code, sku=sku, price=price,
                                roof_squares=roof_squares, bps=bps)
    claim = get_success_data(api_client.file_damage_claim(
        ctx["delivery"]["id"],
        file_damage_claim_payload(claimed_bundles=claimed_bundles),
        make_contractor_headers(ctx["account"]["id"])))
    ctx["claim"] = claim
    return ctx


def setup_approved_claim(approved_amount_cents=5000, approver_id="test-adj-1",
                         **claim_kwargs):
    """Damage claim driven FILED -> UNDER_REVIEW -> APPROVED.

    approver_id pins the X-User-ID recorded as the approver so that
    segregation-of-duties tests can reuse or vary it at crediting time.
    """
    from prd_bench_local_runner.testing import build_user_headers
    ctx = setup_filed_claim(**claim_kwargs)
    adjuster = build_user_headers(approver_id, "ClaimsAdjuster")
    get_success_data(api_client.start_claim_review(ctx["claim"]["id"], adjuster))
    claim = get_success_data(api_client.approve_claim(
        ctx["claim"]["id"], approved_amount_cents, adjuster))
    ctx["claim"] = claim
    ctx["approver_id"] = approver_id
    return ctx


def setup_active_surge_event(branch_id, *, event_name="Hail-Test",
                             surge_multiplier_pct=10, allocation_pool_bundles=1000,
                             activate_at="2026-08-05T00:00:00Z"):
    """DECLARED event -> clock advanced past starts_at -> ACTIVE, branch SURGE."""
    event = get_success_data(api_client.create_surge_event(
        branch_id,
        create_surge_event_payload(event_name=event_name,
                                   surge_multiplier_pct=surge_multiplier_pct,
                                   allocation_pool_bundles=allocation_pool_bundles),
        MANAGER))
    get_success_data(api_client.set_clock(activate_at, ADMIN))
    return get_success_data(api_client.get_surge_event(event["id"], MANAGER))


def request_and_grant_allocation(event_id, account_id, product_id,
                                 requested_bundles=100):
    """Contractor requests PENDING allocation; BranchManager grants it (OCC
    version read fresh). Returns the GRANTED allocation."""
    allocation = get_success_data(api_client.request_allocation(
        event_id,
        request_allocation_payload(account_id, product_id,
                                   requested_bundles=requested_bundles),
        make_contractor_headers(account_id)))
    event = get_success_data(api_client.get_surge_event(event_id, MANAGER))
    return get_success_data(api_client.grant_allocation(
        allocation["id"], event["version"], MANAGER))


def setup_job_with_invoice_balance(*, roof_squares=5.0, price=2000, bps=3.0,
                                   branch_code="BR-L1", sku="SH-L1"):
    """Invoiced delivered order — the job carries a positive job_balance."""
    return setup_invoiced_order(branch_code=branch_code, sku=sku,
                                roof_squares=roof_squares, price=price, bps=bps)


def file_lien_notice(job_id, lien_notice_amount_cents):
    return get_success_data(
        api_client.file_lien_notice(job_id, lien_notice_amount_cents, CREDIT))


def advance_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
