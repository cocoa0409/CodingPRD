"""Shared business logic: calculations (SCAFFOLD calculations table) and
cross-aggregate helpers. All money math is integer cents via Decimal with
ROUND_HALF_UP exactly where the calculation says so (PRD §2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store, now


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- publisher agreements -------------------------------------------------

def active_agreement(publisher_id, at=None):
    """The agreement covering publisher_id at the given instant: current UTC
    date inside the closed [start_date, end_date] interval (PRD §2.9)."""
    d = (at or now()).date().isoformat()
    for ag in store.agreements.values():
        if ag["publisher_id"] != publisher_id:
            continue
        if ag["start_date"] <= d <= ag["end_date"]:
            return ag
    return None


# --- shelf pricing (calculations.shelf_price_resolution) -------------------

USED_RATIO = Decimal("0.75")
RENTAL_TIER_1_MAX_WEEKS = 8
RENTAL_TIER_1_PCT = Decimal("0.40")
RENTAL_TIER_2_MAX_WEEKS = 16
RENTAL_TIER_2_PCT = Decimal("0.50")
RENTAL_TIER_3_PCT = Decimal("0.60")

STOCK_FIELD = {"NEW": "new_stock_qty", "USED": "used_stock_qty",
               "RENTAL": "rental_stock_qty"}
OFFERED_FIELD = {"NEW": "has_new", "USED": "has_used",
                 "RENTAL": "has_rental", "DIGITAL": "has_digital"}
FORMATS = ("NEW", "USED", "RENTAL", "DIGITAL")


def shelf_base_price(fmt, title, term, agreement):
    """Format base price in integer cents, round-half-up per line before the
    HEOA min() cap is applied."""
    lp = title["list_price_cents"]
    if fmt == "NEW":
        return lp
    if fmt == "USED":
        return round_half_up_cents(USED_RATIO * lp)
    if fmt == "RENTAL":
        w = term["length_weeks"]
        if w <= RENTAL_TIER_1_MAX_WEEKS:
            pct = RENTAL_TIER_1_PCT
        elif w <= RENTAL_TIER_2_MAX_WEEKS:
            pct = RENTAL_TIER_2_PCT
        else:
            pct = RENTAL_TIER_3_PCT
        return round_half_up_cents(pct * lp)
    # DIGITAL
    dd = Decimal(str(agreement["digital_discount_pct"]))
    return round_half_up_cents(Decimal(lp) * (Decimal(1) - dd))


# --- buyback pricing (calculations.buyback_offer_price) --------------------

NEEDS_RATIO = Decimal("0.50")
QUOTE_TTL_HOURS = 24


def demand_quota(title_id, upcoming_term_id):
    """sum(qty_used_requested) over APPROVED adoptions of (title, term)."""
    total = 0
    for ad in store.adoptions.values():
        if ad["title_id"] == title_id and ad["status"] == "APPROVED":
            sec = store.sections.get(ad["section_id"])
            if sec is not None and sec["term_id"] == upcoming_term_id:
                total += ad["qty_used_requested"]
    return total


def accepted_count(title_id, upcoming_term_id):
    return sum(
        1 for t in store.buyback_tickets.values()
        if t["title_id"] == title_id
        and t["upcoming_term_id"] == upcoming_term_id
        and t["status"] in ("ACCEPTED", "PAID")
    )


def active_wholesale_quote(title_id, condition, at=None):
    """The unique quote whose half-open [effective_from, effective_to) window
    contains now."""
    n = at or now()
    for q in store.wholesale_quotes.values():
        if q["title_id"] == title_id and q["condition"] == condition:
            if q["effective_from"] <= n < q["effective_to"]:
                return q
    return None


def buyback_window_open():
    n = now()
    return any(
        t["status"] == "BUYBACK_OPEN"
        and t["buyback_window_start_at"] <= n <= t["buyback_window_end_at"]
        for t in store.terms.values()
    )


# --- buy-plan landed cost (calculations.buyplan_landed_cost) ---------------

TIER_QTY = 100
TIER_BONUS_PCT = Decimal("0.02")


def plan_units(plan):
    return plan["qty_new"] + plan["qty_used"] + plan["qty_rental"] + plan["qty_digital"]


def plan_term_id(plan):
    adoption = store.adoptions[plan["adoption_id"]]
    section = store.sections[adoption["section_id"]]
    return section["term_id"]


def plan_publisher_id(plan):
    adoption = store.adoptions[plan["adoption_id"]]
    title = store.titles[adoption["title_id"]]
    return title["publisher_id"]


def compute_landed_cost(plan, agreement):
    """Pinned evaluation order: gross units -> projected units (incl. this
    plan) -> tier bonus -> discount -> unit new cost (round half-up) ->
    landed cost. Bonus applies only to this plan; no retroactive repricing."""
    gross_units = plan_units(plan)
    term_id = plan_term_id(plan)
    publisher_id = plan_publisher_id(plan)
    projected = gross_units
    for other in store.buy_plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["status"] not in ("COMMITTED", "RECEIVED"):
            continue
        if plan_term_id(other) != term_id:
            continue
        if plan_publisher_id(other) != publisher_id:
            continue
        projected += plan_units(other)
    tier_bonus = TIER_BONUS_PCT if projected >= TIER_QTY else Decimal("0")
    discount = Decimal(str(agreement["discount_pct"])) + tier_bonus
    adoption = store.adoptions[plan["adoption_id"]]
    title = store.titles[adoption["title_id"]]
    unit_new_cost = round_half_up_cents(
        Decimal(title["list_price_cents"]) * (Decimal(1) - discount))
    landed = plan["qty_new"] * unit_new_cost
    return {
        "discount_pct_applied": float(discount),
        "tier_bonus_applied": tier_bonus > 0,
        "landed_cost_cents": landed,
    }


def committed_landed_total(term_id, exclude_plan_id=None):
    total = 0
    for p in store.buy_plans.values():
        if p["id"] == exclude_plan_id:
            continue
        if p["status"] in ("COMMITTED", "RECEIVED") and plan_term_id(p) == term_id:
            total += p["landed_cost_cents"]
    return total


# --- publisher commission (calculations.publisher_commission) --------------

def compute_commission(publisher_id, term_id):
    """Per-title round THEN sum. Both FULFILLED and RETURNED lines contribute
    gross; returns counted are those processed before calculation time."""
    ag = active_agreement(publisher_id)
    pct = Decimal(str(ag["commission_pct"])) if ag else Decimal("0")
    gross = 0
    returns = 0
    commission = 0
    titles = [t for t in store.titles.values() if t["publisher_id"] == publisher_id]
    for t in titles:
        lines = [
            l for l in store.order_lines.values()
            if l["title_id"] == t["id"]
            and store.orders[l["order_id"]]["term_id"] == term_id
        ]
        title_gross = sum(l["line_total_cents"] for l in lines)
        title_returns = sum(
            l["aid_refunded_cents"] + l["card_refunded_cents"] for l in lines)
        title_net = title_gross - title_returns
        title_commission = round_half_up_cents(Decimal(title_net) * pct)
        gross += title_gross
        returns += title_returns
        commission += title_commission
    return {
        "gross_sales_cents": gross,
        "returns_cents": returns,
        "net_sales_cents": gross - returns,
        "commission_cents": commission,
    }
