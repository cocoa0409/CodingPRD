"""Role-based access control and optimistic-concurrency behavior.

Covers forbidden cross-role operations, the unknown-role authentication gate, the
happy-path OCC fund, the stale-version settle rejection, and lazy floor-plan
accrual recompute on a clock advance.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_unit_payload, create_customer_payload, create_deal_payload,
    create_work_order_payload, create_floor_plan_note_payload,
    create_customer, create_unit, create_approved_deal, get_unit_version,
    create_active_floor_plan_note, create_closed_no_sale_lot,
    build_user_headers, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]
AUCTION = TEST_USERS["auction_clerk_headers"]


# ─── RBAC: SalesRep cannot fund (Corner/rbac) ────────────────────────────────

def test_salesrep_cannot_fund_deal_forbidden(api):
    """PRD §4: "POST `/deals/{id}/fund` Fund an approved deal (sells/leases the
    unit, runs cascades) FinanceManager".
    PRD §2.1: "When a request is well-authenticated but the acting role is not
    permitted to perform the requested operation under the access matrix described
    in Section 4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/salesrep_cannot_fund_deal_forbidden
    """
    unit, _, deal = create_approved_deal(
        unit_overrides={"condition": "NEW", "model_code": "6R185",
                        "dealer_cost_cents": 7000000, "list_price_cents": 9000000},
        customer_overrides={"name": "RB Cust", "customer_type": "RETAIL"},
        deal_overrides={"deal_type": "SALE", "sale_price_cents": 9000000},
    )
    unit_v = get_unit_version(unit["id"])
    # Funding is FinanceManager-exclusive; a SalesRep is forbidden.
    validate_error(api.fund_deal(deal["id"], {"expected_unit_version": unit_v}, SALES),
                   ApiErrorId.ERR_FORBIDDEN.value)
    after = validate_success(api.get_deal(deal["id"], FINANCE), 200)
    assert after["status"] == "APPROVED"


# ─── RBAC: PartsClerk cannot create work orders (Corner/rbac) ────────────────

def test_partsclerk_cannot_create_work_order_forbidden(api):
    """PRD §4: "POST `/work-orders` Open a work order ServiceAdvisor, DealerAdmin".
    PRD §2.1: "When a request is well-authenticated but the acting role is not
    permitted to perform the requested operation under the access matrix described
    in Section 4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/partsclerk_cannot_create_work_order_forbidden
    """
    customer = create_customer(name="PC Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5075M", engine_hours=1000)
    validate_error(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="x", labor_rate_cents=13000,
        flat_rate_hours=1.0), PARTS), ApiErrorId.ERR_FORBIDDEN.value)


# ─── Auth: unknown role rejected (Corner/rbac) ───────────────────────────────

def test_unknown_role_rejected_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_unknown_role_rejected
    """
    ghost = build_user_headers("ghost-1", "GhostRole")
    validate_error(api.list_units(ghost), ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── OCC: correct version funds (Corner/cross_cutting_complexity_layers) ─────

def test_fund_with_correct_unit_version_succeeds(api):
    """PRD §2.7: "A request to fund a deal must carry `expected_unit_version`, a
    non-optional field whose value is the unit `version` the client last observed.
    If that value does not match the current `version` of the unit referenced by the
    deal, the funding request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_unit_version_funds_successfully
    """
    unit, _, deal = create_approved_deal(
        unit_overrides={"condition": "NEW", "model_code": "8R230",
                        "dealer_cost_cents": 6000000, "list_price_cents": 8000000},
        customer_overrides={"name": "OK Cust", "customer_type": "RETAIL"},
        deal_overrides={"deal_type": "SALE", "sale_price_cents": 8000000},
    )
    current_v = get_unit_version(unit["id"])
    funded = validate_success(
        api.fund_deal(deal["id"], {"expected_unit_version": current_v}, FINANCE), 200)
    assert funded["status"] == "FUNDED"
    after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert after["status"] == "SOLD"


# ─── OCC: stale version on settle (Corner/cross_cutting_complexity_layers) ───

def test_settle_with_stale_unit_version_rejected(api):
    """PRD §2.7: "A request to settle an auction lot must likewise carry
    `expected_unit_version` matching the current `version` of the consigned unit. If
    the unit's version has advanced since the clerk last read it ... the settlement
    is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/auction_settle_stale_unit_version_rejected
    """
    unit, lot = create_closed_no_sale_lot(reserve_price_cents=4500000)
    current_v = get_unit_version(unit["id"])
    # One behind current is stale.
    validate_error(api.settle_auction_lot(lot["id"], {"expected_unit_version": current_v - 1}, AUCTION),
                   ApiErrorId.ERR_STALE_UNIT_VERSION.value)
    after = validate_success(api.get_auction_lot(lot["id"], AUCTION), 200)
    assert after["status"] == "CLOSED_NO_SALE"


# ─── Lazy accrual recompute on clock advance (Corner/cross_cutting_complexity_layers) ──

def test_floorplan_accrual_recomputed_on_clock_advance(api):
    """PRD §2.9: "An administrative capability accepts a `to_iso8601` instant and
    sets the clock to that value; advancing the clock triggers a recompute of
    interest accrual and curtailment stage on every floor-plan note that is
    currently `ACTIVE` or `CURTAILMENT_DUE`."
    PRD §3.2: "The accrued interest is that outstanding base multiplied by the daily
    rate and multiplied by `days_outstanding`, with the result rounded half up to
    whole cents and stored in `interest_accrued_cents`."

    Design: Corner/cross_cutting_complexity_layers/floorplan_accrual_recomputed_on_clock_advance
    """
    unit = create_unit(condition="NEW", model_code="9520R", dealer_cost_cents=30000000,
                       list_price_cents=42000000)
    note = create_active_floor_plan_note(unit["id"], principal_cents=30000000, annual_rate_bps=875)
    get_success_data(api.set_clock({"to_iso8601": "2026-04-11T00:00:00Z"}, ADMIN))
    # Observable via GET (read-time recompute also applies). 100 days of accrual.
    fetched = validate_success(api.get_floor_plan_note(note["id"], FINANCE), 200)
    assert fetched["days_outstanding"] == 100
    assert fetched["interest_accrued_cents"] == 719178
