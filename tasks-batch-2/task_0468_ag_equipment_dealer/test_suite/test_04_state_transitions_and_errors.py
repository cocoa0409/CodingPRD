"""State-machine guards, terminal-state lockdown, precondition enforcement, and
single-error scenarios.

Covers idempotent re-transitions, funding before approval, reconditioning a
retired unit, retiring a floor-planned unit, opening an auction before its
window, the stale-version guard on funding, and bidding on a non-live lot.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_unit_payload, create_customer_payload, create_deal_payload,
    create_floor_plan_note_payload, create_auction_lot_payload, create_bid_payload,
    create_customer, create_unit, create_quoted_deal, create_approved_deal,
    create_active_floor_plan_note, get_unit_version, create_draft_lot,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
AUCTION = TEST_USERS["auction_clerk_headers"]


# ─── Idempotency: re-approve an APPROVED deal (Corner/state_machines) ────────

def test_approve_already_approved_deal_rejected(api):
    """PRD §3.4: "A finance manager approves a quoted deal, moving it
    `QUOTED → APPROVED` and recording the credit decision; approval is permitted
    only when the deal is `QUOTED`".

    Design: Corner/state_machines/approve_deal_from_already_approved_returns_invalid_state
    """
    unit, _, deal = create_approved_deal(
        unit_overrides={"condition": "NEW", "model_code": "6R155",
                        "dealer_cost_cents": 7000000, "list_price_cents": 9000000},
        customer_overrides={"name": "Idem Cust", "customer_type": "RETAIL"},
        deal_overrides={"deal_type": "SALE", "sale_price_cents": 9000000},
    )
    assert deal["status"] == "APPROVED"
    # Re-approving is undefined from APPROVED.
    validate_error(api.approve_deal(deal["id"], FINANCE), ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_deal(deal["id"], FINANCE), 200)
    assert after["status"] == "APPROVED"


# ─── Invalid transition: fund a QUOTED deal (Corner/state_machines) ──────────

def test_fund_quoted_deal_without_approval_rejected(api):
    """PRD §3.4: "Funding moves the deal `APPROVED → FUNDED` and requires that the
    deal be `APPROVED`, that the referenced unit be `RESERVED` (otherwise
    `ERR_UNIT_NOT_RESERVABLE`)".

    Design: Corner/state_machines/fund_deal_from_quoted_without_approval_returns_invalid_state
    """
    cust = create_customer(name="Skip Cust", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="6R175", dealer_cost_cents=7000000,
                       list_price_cents=9000000)
    deal = create_quoted_deal(unit["id"], cust["id"], deal_type="SALE", sale_price_cents=9000000)
    assert deal["status"] == "QUOTED"
    unit_v = get_unit_version(unit["id"])
    # Fund is defined only from APPROVED; from QUOTED the state gate fires.
    validate_error(api.fund_deal(deal["id"], {"expected_unit_version": unit_v}, FINANCE),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_deal(deal["id"], FINANCE), 200)
    assert after["status"] == "QUOTED"


# ─── Terminal lockdown: recondition a RETIRED unit (Corner/state_machines) ───

def test_recondition_retired_unit_rejected(api):
    """PRD §3.1: "Reconditioning is permitted only when the unit is currently
    `REPOSSESSED`."

    Design: Corner/state_machines/terminal_retired_unit_cannot_recondition
    """
    unit = create_unit(condition="NEW", model_code="5045E", dealer_cost_cents=3000000,
                       list_price_cents=4000000)
    retired = validate_success(api.retire_unit(unit["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"
    # RETIRED is terminal; recondition is undefined from it.
    validate_error(api.recondition_unit(unit["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_unit(unit["id"], ADMIN), 200)
    assert after["status"] == "RETIRED"


# ─── Precondition: retire a floor-planned unit (Corner/state_machines) ───────

def test_retire_floor_planned_unit_rejected(api):
    """PRD §3.1: "a `DealerAdmin` may retire a unit, moving it `AVAILABLE → RETIRED`
    (terminal), but only when the unit is `AVAILABLE` and its `floor_planned` flag
    is `false` — a unit still under floor-plan financing cannot be retired."

    Design: Corner/state_machines/retire_floor_planned_unit_rejected
    """
    unit = create_unit(condition="NEW", model_code="8R370", dealer_cost_cents=9000000,
                       list_price_cents=12000000)
    create_active_floor_plan_note(unit["id"], principal_cents=9000000, annual_rate_bps=850)
    before = validate_success(api.get_unit(unit["id"], ADMIN), 200)
    assert before["floor_planned"] is True
    # AVAILABLE but floor_planned -> retire precondition fails.
    validate_error(api.retire_unit(unit["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_unit(unit["id"], ADMIN), 200)
    assert after["status"] == "AVAILABLE"
    assert after["floor_planned"] is True


# ─── Guarded transition: open auction before opens_at (Corner/state_machines) ──

def test_open_auction_before_opens_at_rejected(api):
    """PRD §3.5: "An auction clerk opens a draft lot, moving it `DRAFT → LIVE`;
    opening is permitted only when the lot is `DRAFT` and the current clock is at or
    after `opens_at`. Opening or closing outside the permitted clock window is
    rejected with `ERR_AUCTION_WINDOW`."

    Design: Corner/state_machines/open_auction_before_opens_at_rejected
    """
    # Default clock is 2026-01-01; opens_at is in the future.
    _, lot = create_draft_lot(
        unit_overrides={"model_code": "S790", "engine_hours": 2200},
        lot_overrides={"reserve_price_cents": 5000000, "opens_at": "2026-05-01T00:00:00Z",
                       "closes_at": "2026-06-01T00:00:00Z"},
    )
    validate_error(api.open_auction_lot(lot["id"], AUCTION), ApiErrorId.ERR_AUCTION_WINDOW.value)
    after = validate_success(api.get_auction_lot(lot["id"], AUCTION), 200)
    assert after["status"] == "DRAFT"


# ─── Stale unit version on fund (Corner/errors) ──────────────────────────────

def test_fund_with_stale_unit_version_rejected(api):
    """PRD §2.7: "A request to fund a deal must carry `expected_unit_version`, a
    non-optional field whose value is the unit `version` the client last observed.
    If that value does not match the current `version` of the unit referenced by the
    deal, the funding request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_unit_version_on_fund
    """
    unit, _, deal = create_approved_deal(
        unit_overrides={"condition": "NEW", "model_code": "8R280",
                        "dealer_cost_cents": 6000000, "list_price_cents": 8000000},
        customer_overrides={"name": "Stale Cust", "customer_type": "RETAIL"},
        deal_overrides={"deal_type": "SALE", "sale_price_cents": 8000000},
    )
    current_v = get_unit_version(unit["id"])
    # A version one behind current is stale.
    validate_error(api.fund_deal(deal["id"], {"expected_unit_version": current_v - 1}, FINANCE),
                   ApiErrorId.ERR_STALE_UNIT_VERSION.value)
    after = validate_success(api.get_deal(deal["id"], FINANCE), 200)
    assert after["status"] == "APPROVED"


# ─── Bid on non-live lot (Corner/errors) ─────────────────────────────────────

def test_bid_on_draft_lot_rejected(api):
    """PRD §3.5: "The lot must be `LIVE` and the current clock must be within the
    window — at or after `opens_at` and strictly before `closes_at`. A bid that is
    not strictly greater than the current high, or that arrives when the lot is not
    live or the clock is outside the window, is rejected with `ERR_BID_TOO_LOW`
    (HTTP 409)."

    Design: Corner/errors/bid_on_non_live_lot_rejected
    """
    bidder = create_customer(name="DB Cust", customer_type="COMMERCIAL_AG")
    # A never-opened lot is DRAFT, not LIVE.
    _, lot = create_draft_lot(
        unit_overrides={"model_code": "S780", "engine_hours": 2400},
        lot_overrides={"reserve_price_cents": 4500000, "closes_at": "2026-06-01T00:00:00Z"},
    )
    assert lot["status"] == "DRAFT"
    validate_error(api.place_bid(lot["id"], create_bid_payload(bidder["id"], 5000000), AUCTION),
                   ApiErrorId.ERR_BID_TOO_LOW.value)
    after = validate_success(api.get_auction_lot(lot["id"], AUCTION), 200)
    assert after["status"] == "DRAFT"
