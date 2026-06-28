"""Composite setup helpers for multi-step test prerequisites.

Each test starts against an empty database (the harness restarts the server
before every test), so every helper builds its preconditions from scratch using
only PRD-declared endpoints. Helpers use get_success_data() (lenient validator)
so setup failures surface as clear "setup failed" errors.

All roles are opaque (PRD §2.1), so the shared TEST_USERS constants are the
canonical header source for every call.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_unit_payload,
    create_floor_plan_note_payload,
    create_customer_payload,
    create_trade_in_payload,
    create_deal_payload,
    create_auction_lot_payload,
    create_bid_payload,
    create_part_payload,
    create_work_order_payload,
    create_part_line_payload,
    create_warranty_claim_payload,
    create_whole_goods_order_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]
AUCTION = TEST_USERS["auction_clerk_headers"]


# ─── Primitives ──────────────────────────────────────────────────────────────

def create_customer(**overrides):
    """Create a Customer (DealerAdmin). Returns the Customer dict."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_unit(**overrides):
    """Create a Unit AVAILABLE (DealerAdmin). Returns the Unit dict."""
    return get_success_data(
        api_client.create_unit(create_unit_payload(**overrides), ADMIN)
    )


def create_part(**overrides):
    """Create a catalog Part (PartsClerk). Returns the Part dict."""
    return get_success_data(
        api_client.create_part(create_part_payload(**overrides), PARTS)
    )


def get_unit_version(unit_id: str) -> int:
    """Read the current Unit.version (the value an OCC fund/settle call must carry)."""
    return get_success_data(api_client.get_unit(unit_id, FINANCE))["version"]


# ─── Floor-plan notes ────────────────────────────────────────────────────────

def create_active_floor_plan_note(unit_id: str, **note_overrides):
    """Draft a FloorPlanNote on a unit and activate it (-> ACTIVE, floor_planned true).

    Returns the activated note dict.
    """
    note = get_success_data(
        api_client.create_floor_plan_note(
            create_floor_plan_note_payload(unit_id, **note_overrides), FINANCE
        )
    )
    return get_success_data(api_client.activate_floor_plan_note(note["id"], FINANCE))


def setup_unit_with_active_floor_plan(unit_overrides=None, note_overrides=None):
    """Create a Unit + an ACTIVE FloorPlanNote financing it.

    Returns (unit, note).
    """
    unit = create_unit(**(unit_overrides or {}))
    note = create_active_floor_plan_note(unit["id"], **(note_overrides or {}))
    return unit, note


def setup_curtailment_due_note(principal_cents=30000000, annual_rate_bps=875,
                               to_iso8601="2026-04-01T00:00:00Z"):
    """ACTIVE note advanced to a curtailment breakpoint via clock + recompute.

    Default 90-day advance on principal 30000000 yields stage 1, required 3000000.
    Returns (unit, note_after_recompute).
    """
    unit = create_unit(condition="NEW", dealer_cost_cents=principal_cents,
                       list_price_cents=principal_cents + 12000000)
    note = create_active_floor_plan_note(
        unit["id"], principal_cents=principal_cents, annual_rate_bps=annual_rate_bps
    )
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))
    note = get_success_data(api_client.recompute_floor_plan_note(note["id"], FINANCE))
    return unit, note


# ─── Trade-ins ───────────────────────────────────────────────────────────────

def create_offered_trade_in(customer_id: str, **overrides):
    """Appraise a trade-in then offer it (-> OFFERED). Returns the offered trade dict."""
    ti = get_success_data(
        api_client.create_trade_in(create_trade_in_payload(customer_id, **overrides), SALES)
    )
    return get_success_data(api_client.offer_trade_in(ti["id"], SALES))


# ─── Deals ───────────────────────────────────────────────────────────────────

def create_quoted_deal(unit_id: str, customer_id: str, **overrides):
    """Quote a deal (-> QUOTED; unit RESERVED for SALE/LEASE). Returns the deal dict."""
    return get_success_data(
        api_client.create_deal(create_deal_payload(unit_id, customer_id, **overrides), SALES)
    )


def create_approved_deal(unit_overrides=None, customer_overrides=None, deal_overrides=None):
    """Customer + Unit + a QUOTED then APPROVED deal.

    Returns (unit, customer, deal).
    """
    customer = create_customer(**(customer_overrides or {}))
    unit = create_unit(**(unit_overrides or {}))
    deal = create_quoted_deal(unit["id"], customer["id"], **(deal_overrides or {}))
    deal = get_success_data(api_client.approve_deal(deal["id"], FINANCE))
    return unit, customer, deal


def fund_deal(deal_id: str, unit_id: str):
    """Fund an APPROVED deal carrying the current unit version. Returns the funded deal dict."""
    version = get_unit_version(unit_id)
    return get_success_data(
        api_client.fund_deal(deal_id, {"expected_unit_version": version}, FINANCE)
    )


def create_funded_sale_deal(sale_price_cents=6000000, customer_overrides=None,
                            unit_overrides=None):
    """Customer + Unit + SALE deal quoted, approved, and funded (Unit -> SOLD).

    Returns (unit, customer, deal).
    """
    unit, customer, deal = create_approved_deal(
        unit_overrides=unit_overrides,
        customer_overrides=customer_overrides,
        deal_overrides={"deal_type": "SALE", "sale_price_cents": sale_price_cents},
    )
    deal = fund_deal(deal["id"], unit["id"])
    return unit, customer, deal


def create_funded_sale_with_trade(sale_price_cents=8000000, trade_overrides=None):
    """SALE deal with an attached trade, funded so the trade is ACCEPTED and a unit minted.

    Returns (unit, customer, deal, trade_after, minted_unit_id).
    """
    customer = create_customer()
    unit = create_unit(condition="NEW", dealer_cost_cents=6000000,
                       list_price_cents=sale_price_cents)
    trade = create_offered_trade_in(customer["id"], **(trade_overrides or {}))
    deal = create_quoted_deal(
        unit["id"], customer["id"], deal_type="SALE",
        sale_price_cents=sale_price_cents, tradein_id=trade["id"],
    )
    deal = get_success_data(api_client.approve_deal(deal["id"], FINANCE))
    deal = fund_deal(deal["id"], unit["id"])
    trade_after = get_success_data(api_client.get_trade_in(trade["id"], FINANCE))
    return unit, customer, deal, trade_after, trade_after["minted_unit_id"]


# ─── Auction lots ────────────────────────────────────────────────────────────

def create_draft_lot(unit_overrides=None, lot_overrides=None):
    """A USED Unit consigned to auction (lot DRAFT, unit AUCTION_LISTED).

    Returns (unit, lot).
    """
    uo = {"condition": "USED", "engine_hours": 1500}
    uo.update(unit_overrides or {})
    unit = create_unit(**uo)
    lot = get_success_data(
        api_client.create_auction_lot(
            create_auction_lot_payload(unit["id"], **(lot_overrides or {})), AUCTION
        )
    )
    return unit, lot


def create_live_lot(unit_overrides=None, lot_overrides=None):
    """A consigned lot opened to LIVE (default opens_at 2026-01-01, within clock).

    Returns (unit, lot).
    """
    unit, lot = create_draft_lot(unit_overrides=unit_overrides, lot_overrides=lot_overrides)
    lot = get_success_data(api_client.open_auction_lot(lot["id"], AUCTION))
    return unit, lot


def place_bid(lot_id: str, bidder_customer_id: str, amount_cents: int):
    """Place a bid on a LIVE lot. Returns the bid dict."""
    return get_success_data(
        api_client.place_bid(
            lot_id, create_bid_payload(bidder_customer_id, amount_cents), AUCTION
        )
    )


def create_closed_no_sale_lot(reserve_price_cents=4500000,
                              closes_at="2026-02-01T00:00:00Z",
                              advance_to="2026-02-02T00:00:00Z"):
    """A LIVE lot with no qualifying bid, advanced past closes_at and CLOSED_NO_SALE.

    Returns (unit, lot).
    """
    unit, lot = create_live_lot(
        lot_overrides={"reserve_price_cents": reserve_price_cents, "closes_at": closes_at}
    )
    get_success_data(api_client.set_clock({"to_iso8601": advance_to}, ADMIN))
    lot = get_success_data(api_client.close_auction_lot(lot["id"], AUCTION))
    return unit, lot


def create_closed_met_lot(reserve_price_cents=4000000, bid_amount_cents=4800000,
                          closes_at="2026-02-01T00:00:00Z",
                          advance_to="2026-02-02T00:00:00Z"):
    """A LIVE lot with a reserve-meeting bid, advanced past closes_at and CLOSED_MET.

    Returns (unit, lot, bidder).
    """
    bidder = create_customer(name="Winner", customer_type="COMMERCIAL_AG")
    unit, lot = create_live_lot(
        lot_overrides={"reserve_price_cents": reserve_price_cents, "closes_at": closes_at}
    )
    place_bid(lot["id"], bidder["id"], bid_amount_cents)
    get_success_data(api_client.set_clock({"to_iso8601": advance_to}, ADMIN))
    lot = get_success_data(api_client.close_auction_lot(lot["id"], AUCTION))
    return unit, lot, bidder


# ─── Work orders & parts ─────────────────────────────────────────────────────

def create_open_work_order(wo_overrides=None, customer_overrides=None, unit_overrides=None):
    """Customer + Unit + an OPEN WorkOrder. Returns (unit, customer, work_order)."""
    customer = create_customer(**(customer_overrides or {}))
    uo = {"condition": "USED", "engine_hours": 1000}
    uo.update(unit_overrides or {})
    unit = create_unit(**uo)
    wo = get_success_data(
        api_client.create_work_order(
            create_work_order_payload(unit["id"], customer["id"], **(wo_overrides or {})),
            SERVICE,
        )
    )
    return unit, customer, wo


def add_part_line(wo_id: str, part_id: str, quantity: int):
    """Add a PartLine to a work order. Returns the part line dict."""
    return get_success_data(
        api_client.add_part_line(wo_id, create_part_line_payload(part_id, quantity), PARTS)
    )


def create_in_progress_work_order(wo_overrides=None, part_qty=None, part_overrides=None):
    """An OPEN WorkOrder started to IN_PROGRESS, optionally with a PartLine.

    If part_qty is given, a Part is created (part_overrides control its stock/price)
    and a PartLine of that quantity is attached before starting.
    Returns (unit, customer, work_order, part_or_none, part_line_or_none).
    """
    unit, customer, wo = create_open_work_order(wo_overrides=wo_overrides)
    part = None
    part_line = None
    if part_qty is not None:
        part = create_part(**(part_overrides or {}))
        part_line = add_part_line(wo["id"], part["id"], part_qty)
    wo = get_success_data(api_client.start_work_order(wo["id"], SERVICE))
    return unit, customer, wo, part, part_line


def create_closed_work_order_for_claim(claim_id: str, unit_id: str, customer_id: str,
                                       labor_rate_cents=15000, flat_rate_hours=4.0,
                                       actual_hours=4.0, part_overrides=None, part_qty=2):
    """A WorkOrder routed to a claim, taken through OPEN -> IN_PROGRESS -> CLOSED.

    Returns the closed work order dict.
    """
    wo = get_success_data(
        api_client.create_work_order(
            create_work_order_payload(
                unit_id, customer_id, labor_rate_cents=labor_rate_cents,
                flat_rate_hours=flat_rate_hours, warranty_claim_id=claim_id,
            ),
            SERVICE,
        )
    )
    if part_qty:
        part = create_part(**(part_overrides or {}))
        add_part_line(wo["id"], part["id"], part_qty)
    get_success_data(api_client.start_work_order(wo["id"], SERVICE))
    return get_success_data(
        api_client.close_work_order(wo["id"], {"actual_hours": actual_hours}, SERVICE)
    )


def setup_submitted_claim(claim_type="WARRANTY", campaign_code=None,
                          labor_rate_cents=15000, flat_rate_hours=4.0, actual_hours=4.0,
                          part_qty=2):
    """A claim with one CLOSED work order linked, then submitted (-> SUBMITTED).

    Default WO economics: 4 actual hrs @ 15000 = 60000 labor + 2 parts @ 25000 = 50000
    -> total 110000, frozen into claimed_cents at submission.
    Returns (unit, customer, claim_after_submit, wo).
    """
    customer = create_customer()
    unit = create_unit(condition="USED", engine_hours=700)
    claim_payload = create_warranty_claim_payload(unit["id"], claim_type=claim_type)
    if campaign_code is not None:
        claim_payload["campaign_code"] = campaign_code
    claim = get_success_data(api_client.create_warranty_claim(claim_payload, SERVICE))
    wo = create_closed_work_order_for_claim(
        claim["id"], unit["id"], customer["id"],
        labor_rate_cents=labor_rate_cents, flat_rate_hours=flat_rate_hours,
        actual_hours=actual_hours, part_qty=part_qty,
    )
    claim = get_success_data(api_client.submit_warranty_claim(claim["id"], SERVICE))
    return unit, customer, claim, wo


# ─── Whole-goods orders ──────────────────────────────────────────────────────

def create_placed_order(customer_overrides=None, order_overrides=None):
    """A PLACED WholeGoodsOrder. Returns (customer, order)."""
    customer = get_success_data(
        api_client.create_customer(create_customer_payload(**(customer_overrides or {})), SALES)
    )
    order = get_success_data(
        api_client.create_whole_goods_order(
            create_whole_goods_order_payload(customer["id"], **(order_overrides or {})), SALES
        )
    )
    return customer, order


def create_confirmed_order(customer_overrides=None, order_overrides=None):
    """A CONFIRMED WholeGoodsOrder (deposit computed). Returns (customer, order)."""
    customer, order = create_placed_order(
        customer_overrides=customer_overrides, order_overrides=order_overrides
    )
    order = get_success_data(api_client.confirm_whole_goods_order(order["id"], SALES))
    return customer, order
