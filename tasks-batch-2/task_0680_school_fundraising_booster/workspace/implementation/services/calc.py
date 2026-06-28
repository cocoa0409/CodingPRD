"""Computed roll-ups and monetary calculations (scaffold §1.3, PRD §3.4-3.8).

All money is integer cents. Rounding appears in exactly two places — order tax
and reconciliation school-profit — both round-half-up, applied once.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db

TAX_RATE = Decimal("0.0825")


def round_half_up_cents(value):
    """Round a Decimal cents figure to a whole integer of cents, round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# order_totals (scaffold calculations.order_totals) — SUM-THEN-ROUND
# ---------------------------------------------------------------------------

def compute_order_totals(lines, products_by_id):
    """gross = exact sum of unit_price * qty; tax = round_half_up(gross * TAX_RATE)
    once on the order-level gross; total = gross + tax."""
    gross = 0
    for line in lines:
        product = products_by_id[line["product_id"]]
        gross += product["unit_price_cents"] * line["quantity"]
    tax = round_half_up_cents(Decimal(gross) * TAX_RATE)
    total = gross + tax
    return gross, tax, total


# ---------------------------------------------------------------------------
# product_reserved_qty (scaffold calculations.product_reserved_qty)
# ---------------------------------------------------------------------------

def compute_reserved_qty(product):
    """Sum line quantities over orders of this product's campaign whose
    fulfillment_status in {PLACED, CONFIRMED}, for lines naming this product."""
    campaign_id = product["campaign_id"]
    pid = product["id"]
    total = 0
    for order in db.orders.values():
        if order["campaign_id"] != campaign_id:
            continue
        if order["fulfillment_status"] not in ("PLACED", "CONFIRMED"):
            continue
        for line in order["lines"]:
            if line["product_id"] == pid:
                total += line["quantity"]
    return total


# ---------------------------------------------------------------------------
# pledge_amount_due (scaffold calculations.pledge_amount_due)
# ---------------------------------------------------------------------------

def compute_pledged_amount(pledge):
    """raw = flat + per_unit * units_recorded; cap==0 means uncapped, else min."""
    raw = pledge["flat_cents"] + pledge["per_unit_cents"] * pledge["units_recorded"]
    cap = pledge["cap_cents"]
    if cap == 0:
        return raw
    return min(raw, cap)


# ---------------------------------------------------------------------------
# seller_credited (FINAL) + prize_tier_earned (scaffold calculations)
# ---------------------------------------------------------------------------

def settled_orders_for_seller(seller_id):
    return [o for o in db.orders.values()
            if o["seller_id"] == seller_id and o["payment_status"] == "PAID"]


def collected_pledges_for_seller(seller_id):
    return [p for p in db.pledges.values()
            if p["seller_id"] == seller_id and p["status"] == "COLLECTED"]


def compute_seller_credited(seller):
    """FINAL: sum total_charged_cents over PAID orders + sum collected_cents over
    COLLECTED pledges crediting this seller."""
    sid = seller["id"]
    total = 0
    for o in settled_orders_for_seller(sid):
        total += o["total_charged_cents"]
    for p in collected_pledges_for_seller(sid):
        total += p["collected_cents"]
    return total


def compute_forecast_credited(seller):
    """FORWARD-LOOKING: sum total_charged_cents over orders PENDING|PAID +
    sum pledged_amount_cents over pledges RECORDED|COLLECTED crediting this seller."""
    sid = seller["id"]
    total = 0
    for o in db.orders.values():
        if o["seller_id"] == sid and o["payment_status"] in ("PENDING", "PAID"):
            total += o["total_charged_cents"]
    for p in db.pledges.values():
        if p["seller_id"] == sid and p["status"] in ("RECORDED", "COLLECTED"):
            total += compute_pledged_amount(p)
    return total


def compute_earned_prize_tier_id(seller, credited_cents):
    """Highest PrizeTier whose threshold_cents <= credited_cents (inclusive >=);
    null if none. thresholds unique within campaign so max is unambiguous."""
    campaign_id = seller["campaign_id"]
    eligible = [t for t in db.prize_tiers.values()
                if t["campaign_id"] == campaign_id
                and t["threshold_cents"] <= credited_cents]
    if not eligible:
        return None
    best = max(eligible, key=lambda t: t["threshold_cents"])
    return best["id"]


# ---------------------------------------------------------------------------
# campaign_gross (FINAL + forecast) (scaffold calculations.campaign_gross)
# ---------------------------------------------------------------------------

def compute_campaign_gross_collected(campaign):
    """FINAL: sum total_charged_cents over PAID orders + sum collected_cents over
    COLLECTED pledges of this campaign. REFUNDED excluded."""
    cid = campaign["id"]
    total = 0
    for o in db.orders.values():
        if o["campaign_id"] == cid and o["payment_status"] == "PAID":
            total += o["total_charged_cents"]
    for p in db.pledges.values():
        if p["campaign_id"] == cid and p["status"] == "COLLECTED":
            total += p["collected_cents"]
    return total


def compute_campaign_forecast_gross(campaign):
    """FORECAST: sum total_charged_cents over orders PENDING|PAID +
    sum pledged_amount_cents over pledges RECORDED|COLLECTED of this campaign."""
    cid = campaign["id"]
    total = 0
    for o in db.orders.values():
        if o["campaign_id"] == cid and o["payment_status"] in ("PENDING", "PAID"):
            total += o["total_charged_cents"]
    for p in db.pledges.values():
        if p["campaign_id"] == cid and p["status"] in ("RECORDED", "COLLECTED"):
            total += compute_pledged_amount(p)
    return total


# ---------------------------------------------------------------------------
# profit_split_reconciliation (scaffold calculations.profit_split_reconciliation)
# ---------------------------------------------------------------------------

def compute_profit_split(campaign, products_by_id):
    """Pinned waterfall at reconcile. Returns (school_profit, vendor_payable)."""
    cid = campaign["id"]
    paid_orders = [o for o in db.orders.values()
                   if o["campaign_id"] == cid and o["payment_status"] == "PAID"]
    collected_pledges = [p for p in db.pledges.values()
                         if p["campaign_id"] == cid and p["status"] == "COLLECTED"]

    # STEP 1 — settled product revenue (pre-tax), pledge revenue, tax separate
    product_revenue = sum(o["gross_cents"] for o in paid_orders)
    pledge_revenue = sum(p["collected_cents"] for p in collected_pledges)
    # tax_collected tracked separately; remitted apart from either payout bucket.

    # STEP 2 — vendor COGS over PAID orders only
    vendor_cogs = 0
    for o in paid_orders:
        for line in o["lines"]:
            product = products_by_id.get(line["product_id"])
            if product is not None:
                vendor_cogs += product["unit_cost_cents"] * line["quantity"]

    # STEP 3 — split base = (product_revenue - vendor_cogs) + pledge_revenue, floor 0
    split_base = (product_revenue - vendor_cogs) + pledge_revenue
    if split_base < 0:
        split_base = 0

    # STEP 4 — waterfall: school takes profit_split_pct of split base (round once);
    # vendor gets COGS + exact residual.
    pct = Decimal(str(campaign["profit_split_pct"]))
    school_profit = round_half_up_cents(Decimal(split_base) * pct)
    vendor_payable = vendor_cogs + (split_base - school_profit)
    return school_profit, vendor_payable


# ---------------------------------------------------------------------------
# volunteer_committed_minutes (scaffold calculations.volunteer_committed_minutes)
# ---------------------------------------------------------------------------

def compute_committed_minutes(volunteer):
    """Sum of whole minutes between starts_at and ends_at over this volunteer's
    BOOKED shifts. setup_buffer_minutes excluded."""
    from clock import parse_iso8601
    vid = volunteer["id"]
    total = 0
    for shift in db.shifts.values():
        if shift.get("volunteer_id") != vid:
            continue
        if shift["status"] != "BOOKED":
            continue
        start = parse_iso8601(shift["starts_at"])
        end = parse_iso8601(shift["ends_at"])
        delta_seconds = (end - start).total_seconds()
        total += int(delta_seconds // 60)
    return total
