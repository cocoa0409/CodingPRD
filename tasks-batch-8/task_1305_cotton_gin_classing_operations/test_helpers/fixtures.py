"""Composite setup helpers.

Every test starts against an empty database, so these helpers build complete
precondition chains (grower -> shift -> module -> ginning -> bales -> classing
-> receipts -> pledges -> orders -> settlements) out of PRD-declared endpoints
only.

Segregation of duties: gin modules with one operator id (default "gin-op-1")
and issue receipts with a different warehouse-manager id (default "wm-1").
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_bale_entry,
    create_classing_result_payload,
    create_gin_shift_payload,
    create_grade_schedule_payload,
    create_grower_payload,
    create_ledger_adjustment_payload,
    create_module_payload,
    create_seed_sale_payload,
    create_settlement_payload,
    create_shipping_order_payload,
    create_warehouse_payload,
    create_warehouse_receipt_payload,
)
from .test_users import (
    TEST_USERS,
    make_gin_operator_headers,
    make_warehouse_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
CLERK = TEST_USERS["classing_clerk_headers"]
WM = TEST_USERS["warehouse_manager_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

DEFAULT_OPERATOR_ID = "gin-op-1"
DEFAULT_WM_ID = "wm-1"


# ---------------------------------------------------------------------------
# Tier 0: thin entity creators / readers
# ---------------------------------------------------------------------------

def create_grower(membership_number="MB-1", legal_name="Test Farm", **overrides):
    resp = api_client.create_grower(
        create_grower_payload(membership_number=membership_number,
                              legal_name=legal_name, **overrides), ADMIN)
    return get_success_data(resp)


def create_grade_schedule(grade_code="31-3", premium_discount_points=265,
                          loan_rate_points=5450,
                          effective_from="2026-01-01T00:00:00Z",
                          effective_to="2027-01-01T00:00:00Z"):
    resp = api_client.create_grade_schedule(
        create_grade_schedule_payload(
            grade_code=grade_code, premium_discount_points=premium_discount_points,
            loan_rate_points=loan_rate_points, effective_from=effective_from,
            effective_to=effective_to), ADMIN)
    return get_success_data(resp)


def create_warehouse(name="WH-1", capacity_bales=5, dock_count=1):
    resp = api_client.create_warehouse(
        create_warehouse_payload(name=name, capacity_bales=capacity_bales,
                                 dock_count=dock_count), ADMIN)
    return get_success_data(resp)


def create_shift(season="2026", stand_label="STAND-A"):
    resp = api_client.create_gin_shift(
        create_gin_shift_payload(season=season, stand_label=stand_label), OPERATOR)
    return get_success_data(resp)


def create_module(grower_id, season="2026", ticket_number="T-1", module_tag="MT-1",
                  gross_weight_lbs=11000, tare_weight_lbs=1000, moisture_pct=8.0,
                  foreign_matter_pct=4.0):
    resp = api_client.create_module(
        create_module_payload(
            grower_id, season=season, ticket_number=ticket_number,
            module_tag=module_tag, gross_weight_lbs=gross_weight_lbs,
            tare_weight_lbs=tare_weight_lbs, moisture_pct=moisture_pct,
            foreign_matter_pct=foreign_matter_pct), OPERATOR)
    return get_success_data(resp)


def get_grower(grower_id):
    return get_success_data(api_client.get_grower(grower_id, ACCOUNTANT))


def get_module(module_id):
    return get_success_data(api_client.get_module(module_id, OPERATOR))


def get_bale(bale_id):
    return get_success_data(api_client.get_bale(bale_id, CLERK))


def get_shift(shift_id):
    return get_success_data(api_client.get_gin_shift(shift_id, OPERATOR))


def get_warehouse(warehouse_id):
    return get_success_data(api_client.get_warehouse(warehouse_id, ADMIN))


def get_receipt(receipt_id):
    return get_success_data(api_client.get_warehouse_receipt(receipt_id, WM))


def get_pledge(pledge_id):
    return get_success_data(api_client.get_loan_pledge(pledge_id, ACCOUNTANT))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, ACCOUNTANT))


def get_order(order_id):
    return get_success_data(api_client.get_shipping_order(order_id, WM))


def list_ledger_entries(**filters):
    """Filtered ledger list; returns the data array."""
    data, _meta = validate_paginated(
        api_client.list_ledger_entries(ACCOUNTANT, params=filters or None))
    return data


def list_module_bales(module_id):
    data, _meta = validate_paginated(
        api_client.list_module_bales(module_id, CLERK))
    return data


def bales_by_tag(module_id):
    """Map bale_tag -> bale for a module (robust to list ordering)."""
    return {b["bale_tag"]: b for b in list_module_bales(module_id)}


def list_classing_results(bale_id):
    data, _meta = validate_paginated(
        api_client.list_classing_results(bale_id, CLERK))
    return data


def list_receipts(**filters):
    data, _meta = validate_paginated(
        api_client.list_warehouse_receipts(WM, params=filters or None))
    return data


def list_pledges_for_receipt(receipt_id):
    data, _meta = validate_paginated(
        api_client.list_receipt_loan_pledges(receipt_id, ACCOUNTANT))
    return data


def list_shift_seed_sales(shift_id):
    data, _meta = validate_paginated(
        api_client.list_shift_seed_sales(shift_id, ACCOUNTANT))
    return data


def list_grower_settlements(grower_id):
    data, _meta = validate_paginated(
        api_client.list_grower_settlements(grower_id, ACCOUNTANT))
    return data


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: module state progression
# ---------------------------------------------------------------------------

def queue_module(module_id, shift_id):
    return get_success_data(
        api_client.queue_module(module_id, {"gin_shift_id": shift_id}, OPERATOR))


def start_ginning(module_id):
    return get_success_data(api_client.start_ginning(module_id, OPERATOR))


def complete_ginning(module_id, bales, operator_user_id=DEFAULT_OPERATOR_ID):
    """bales: list of (tag, net_weight_lbs) tuples or ready dicts."""
    entries = [b if isinstance(b, dict) else create_bale_entry(bale_tag=b[0],
                                                               net_weight_lbs=b[1])
               for b in bales]
    return get_success_data(api_client.complete_ginning(
        module_id, {"bales": entries},
        make_gin_operator_headers(operator_user_id)))


def gin_module(module_id, shift_id, bales, operator_user_id=DEFAULT_OPERATOR_ID):
    """Walk a RECEIVED module through QUEUED -> GINNING -> GINNED."""
    queue_module(module_id, shift_id)
    start_ginning(module_id)
    return complete_ginning(module_id, bales, operator_user_id=operator_user_id)


def create_ginned_module(grower_id, shift_id, season="2026", ticket_number="T-1",
                         module_tag="MT-1", gross_weight_lbs=11000,
                         tare_weight_lbs=1000, moisture_pct=8.0,
                         foreign_matter_pct=4.0, bales=(("B-01", 500),),
                         operator_user_id=DEFAULT_OPERATOR_ID):
    """Create + gin a module. Returns the GINNED module dict."""
    module = create_module(
        grower_id, season=season, ticket_number=ticket_number, module_tag=module_tag,
        gross_weight_lbs=gross_weight_lbs, tare_weight_lbs=tare_weight_lbs,
        moisture_pct=moisture_pct, foreign_matter_pct=foreign_matter_pct)
    return gin_module(module["id"], shift_id, list(bales),
                      operator_user_id=operator_user_id)


# ---------------------------------------------------------------------------
# Tier 2: shift close / reconcile / seed sale
# ---------------------------------------------------------------------------

def close_shift(shift_id, actual_lint_scale_lbs, actual_seed_scale_lbs, waste_lbs):
    return get_success_data(api_client.close_gin_shift(
        shift_id, {"actual_lint_scale_lbs": actual_lint_scale_lbs,
                   "actual_seed_scale_lbs": actual_seed_scale_lbs,
                   "waste_lbs": waste_lbs}, OPERATOR))


def reconcile_shift(shift_id):
    return get_success_data(api_client.reconcile_gin_shift(shift_id, OPERATOR))


def sell_seed(shift_id, buyer_name="Delta Oil Mill", price_cents_per_lb=20):
    return get_success_data(api_client.create_seed_sale(
        create_seed_sale_payload(shift_id, buyer_name=buyer_name,
                                 price_cents_per_lb=price_cents_per_lb), ACCOUNTANT))


def close_reconcile_sell(shift_id, lint, seed, waste, buyer_name="Delta Oil Mill",
                         price_cents_per_lb=20):
    close_shift(shift_id, lint, seed, waste)
    reconcile_shift(shift_id)
    return sell_seed(shift_id, buyer_name=buyer_name,
                     price_cents_per_lb=price_cents_per_lb)


# ---------------------------------------------------------------------------
# Tier 3: classing
# ---------------------------------------------------------------------------

def class_bale(bale_id, expected_bale_version, grade_code="31-3", micronaire=4.0,
               strength_gpt=28.0, staple_32nds=36, classing_office="USDA-MEMPHIS",
               result_date="2026-03-10T00:00:00Z"):
    return get_success_data(api_client.create_classing_result(
        bale_id,
        create_classing_result_payload(
            expected_bale_version, grade_code=grade_code, micronaire=micronaire,
            strength_gpt=strength_gpt, staple_32nds=staple_32nds,
            classing_office=classing_office, result_date=result_date),
        CLERK))


# ---------------------------------------------------------------------------
# Tier 4: warehouse receipts / pledges
# ---------------------------------------------------------------------------

def issue_receipt(bale_id, warehouse_id, wm_user_id=DEFAULT_WM_ID):
    return get_success_data(api_client.create_warehouse_receipt(
        create_warehouse_receipt_payload(bale_id, warehouse_id),
        make_warehouse_manager_headers(wm_user_id)))


def pledge_receipt(receipt_id):
    return get_success_data(api_client.create_loan_pledge(
        {"warehouse_receipt_id": receipt_id}, ACCOUNTANT))


def redeem_pledge(pledge_id):
    return get_success_data(api_client.redeem_loan_pledge(pledge_id, ACCOUNTANT))


def forfeit_pledge(pledge_id):
    return get_success_data(api_client.forfeit_loan_pledge(pledge_id, ACCOUNTANT))


# ---------------------------------------------------------------------------
# Tier 5: composite scenarios
# ---------------------------------------------------------------------------

def setup_ginned_bale(membership_number="MB-1", legal_name="Test Farm",
                      bale_weight=500, bale_tag="B-01", season="2026",
                      stand_label="STAND-A", gross_weight_lbs=11000,
                      tare_weight_lbs=1000, moisture_pct=8.0,
                      foreign_matter_pct=4.0, operator_user_id=DEFAULT_OPERATOR_ID):
    """Grower + OPEN shift + one GINNED module with a single bale.

    Returns dict(grower, shift, module, bale).
    """
    grower = create_grower(membership_number, legal_name)
    shift = create_shift(season, stand_label)
    module = create_ginned_module(
        grower["id"], shift["id"], season=season, gross_weight_lbs=gross_weight_lbs,
        tare_weight_lbs=tare_weight_lbs, moisture_pct=moisture_pct,
        foreign_matter_pct=foreign_matter_pct, bales=[(bale_tag, bale_weight)],
        operator_user_id=operator_user_id)
    bale = bales_by_tag(module["id"])[bale_tag]
    return {"grower": grower, "shift": shift, "module": module, "bale": bale}


def setup_classed_bale(grade_code="31-3", premium_discount_points=265,
                       loan_rate_points=5450, micronaire=4.0, strength_gpt=28.0,
                       staple_32nds=36, result_date="2026-03-10T00:00:00Z",
                       **kwargs):
    """setup_ginned_bale + covering grade schedule + first classing result.

    Returns dict(grower, shift, module, bale, schedule, classing_result).
    """
    schedule = create_grade_schedule(
        grade_code=grade_code, premium_discount_points=premium_discount_points,
        loan_rate_points=loan_rate_points)
    ctx = setup_ginned_bale(**kwargs)
    result = class_bale(ctx["bale"]["id"], ctx["bale"]["version"],
                        grade_code=grade_code, micronaire=micronaire,
                        strength_gpt=strength_gpt, staple_32nds=staple_32nds,
                        result_date=result_date)
    ctx["schedule"] = schedule
    ctx["classing_result"] = result
    ctx["bale"] = get_bale(ctx["bale"]["id"])
    return ctx


def setup_receipted_bale(warehouse_name="WH-1", capacity_bales=5, dock_count=1,
                         wm_user_id=DEFAULT_WM_ID, **kwargs):
    """setup_classed_bale + warehouse + ACTIVE receipt for the bale.

    Returns dict(..., warehouse, receipt).
    """
    ctx = setup_classed_bale(**kwargs)
    warehouse = create_warehouse(warehouse_name, capacity_bales, dock_count)
    receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                            wm_user_id=wm_user_id)
    ctx["warehouse"] = warehouse
    ctx["receipt"] = receipt
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: settlements / adjustments
# ---------------------------------------------------------------------------

def create_settlement_for_grower(grower_id, season="2026"):
    """Fetch the grower's current version and create a settlement under OCC."""
    grower = get_grower(grower_id)
    return get_success_data(api_client.create_settlement(
        grower_id,
        create_settlement_payload(season, grower["version"]),
        ACCOUNTANT))


def post_adjustment(grower_id, amount_cents, season="2026", memo="manual correction"):
    return get_success_data(api_client.create_ledger_adjustment(
        grower_id,
        create_ledger_adjustment_payload(season=season, amount_cents=amount_cents,
                                         memo=memo),
        ACCOUNTANT))


# ---------------------------------------------------------------------------
# Tier 7: shipping orders
# ---------------------------------------------------------------------------

def create_order(warehouse_id, grower_id, bale_ids, dock_number=1,
                 load_start="2026-08-10T10:00:00Z", load_end="2026-08-10T11:00:00Z",
                 headers=None):
    return get_success_data(api_client.create_shipping_order(
        create_shipping_order_payload(
            warehouse_id, grower_id, bale_ids, dock_number=dock_number,
            load_start=load_start, load_end=load_end),
        headers or WM))


def create_confirmed_order(warehouse_id, grower_id, bale_ids, dock_number=1,
                           load_start="2026-08-10T10:00:00Z",
                           load_end="2026-08-10T11:00:00Z"):
    order = create_order(warehouse_id, grower_id, bale_ids, dock_number,
                         load_start, load_end)
    get_success_data(api_client.confirm_shipping_order(order["id"], WM))
    return get_order(order["id"])
