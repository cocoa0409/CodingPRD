"""Domain calculations (SCAFFOLD section 1.3): hold priority, ticket roll-up
allocation, the settlement payout waterfall, recoupment ordering, and the
cancellation policy. All money math is integer cents; explicit ROUND steps
use round-half-up via Decimal.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import store
from errors import biz, invalid_state

HOLD_TTL_HOURS = {"P1": 48, "P2": 24, "COURTESY": 12}
CHALLENGE_WINDOW_HOURS = 24
PRIORITY_RANK = {"P1": 3, "P2": 2, "COURTESY": 1}
DEPOSIT_LEAD_DAYS = 14

TERMINAL_SUPPORT = {"PERFORMED", "BOUGHT_OUT", "CANCELLED"}


def rhu(value):
    """Round half up to whole cents. `value` is a Decimal."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x):
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# DateHold ranking (hold_priority_rank)
# ---------------------------------------------------------------------------
def holds_on_slot(show):
    """All holds sharing this show's (room, show_date) — the competing pool."""
    return [h for h in store.date_holds.values()
            if _hold_room(h) == show["room"] and _hold_date(h) == show["show_date"]]


def _hold_room(h):
    s = store.shows.get(h["show_id"])
    return s["room"] if s else None


def _hold_date(h):
    s = store.shows.get(h["show_id"])
    return s["show_date"] if s else None


def can_confirm_active(hold, show):
    """Unchallenged confirm precondition: no ACTIVE competitor with strictly
    higher priority; among equal priority the earliest created_at wins (FIFO,
    never id). Expiry is evaluated separately (ERR_HOLD_EXPIRED)."""
    for h in holds_on_slot(show):
        if h["id"] == hold["id"] or h["status"] != "ACTIVE":
            continue
        if PRIORITY_RANK[h["priority"]] > PRIORITY_RANK[hold["priority"]]:
            return False
        if PRIORITY_RANK[h["priority"]] == PRIORITY_RANK[hold["priority"]] \
                and (h["created_at"], h["_seq"]) < (hold["created_at"], hold["_seq"]):
            return False
    return True


# ---------------------------------------------------------------------------
# Ticket roll-up allocation (ticket_scaling_tier_advance)
# ---------------------------------------------------------------------------
def allocate_tickets(show, requested_tier, quantity):
    """Return (allocations, gross). allocations = list of (tier, take).
    Raises ERR_INSUFFICIENT_TICKET_CAPACITY when the candidate pool (requested
    tier plus every strictly-higher tier_order tier) cannot fill the request;
    partial fills do not exist."""
    candidates = [requested_tier] + sorted(
        [t for t in store.ticket_tiers.values()
         if t["show_id"] == show["id"] and t["tier_order"] > requested_tier["tier_order"]],
        key=lambda t: (t["tier_order"], t["created_at"], t["_seq"]))
    total_available = sum(t["capacity"] - t["sold_count"] for t in candidates)
    if total_available < quantity:
        raise biz("ERR_INSUFFICIENT_TICKET_CAPACITY",
                  "Requested ticket quantity exceeds total available across roll-up tiers")
    remaining = quantity
    allocations = []
    gross = 0
    for t in candidates:
        avail = t["capacity"] - t["sold_count"]
        take = min(avail, remaining)
        if take > 0:
            allocations.append((t, take))
            gross += take * t["face_price_cents"]
            remaining -= take
        if remaining == 0:
            break
    return allocations, gross


def recompute_show_ticket_counters(show):
    sales = [s for s in store.ticket_sales.values()
             if s["show_id"] == show["id"] and s["refund_status"] == "NONE"]
    show["tickets_sold"] = sum(s["quantity"] for s in sales)
    show["gross_ticket_revenue_cents"] = sum(s["gross_amount_cents"] for s in sales)


def refund_sale(show, sale):
    """Exact unwind: return each tier's contribution, mark the sale REFUNDED."""
    sale["refund_status"] = "REFUNDED"
    for tier_id, qty in sale["_alloc"].items():
        tier = store.ticket_tiers.get(tier_id)
        if tier is not None:
            tier["sold_count"] -= qty
            tier["refund_count"] += qty
            store.touch(tier)
    recompute_show_ticket_counters(show)
    store.bump_show(show)


# ---------------------------------------------------------------------------
# Recoupment ordering (expense_recoupment_ordering)
# ---------------------------------------------------------------------------
def recoupable_expenses(show, deal):
    """Chronological cap discipline: APPROVED + is_recoupable receipts, oldest
    first by created_at; the first cap-crossing receipt is truncated; later
    receipts recoup at zero. Returns the cumulative total (== cap when over)."""
    receipts = sorted(
        [r for r in store.expense_receipts.values()
         if r["show_id"] == show["id"] and r["status"] == "APPROVED" and r["is_recoupable"]],
        key=lambda r: (r["created_at"], r["_seq"]))
    cap = deal.get("expense_budget_cents") or 0
    cumulative = 0
    for r in receipts:
        remaining_cap = cap - cumulative
        if remaining_cap <= 0:
            continue
        if r["amount_cents"] <= remaining_cap:
            cumulative += r["amount_cents"]
        else:
            cumulative = cap
    return cumulative


# ---------------------------------------------------------------------------
# Settlement payout waterfall (artist_payout + versus_threshold_straddle)
# ---------------------------------------------------------------------------
def compute_settlement_fields(show):
    deal = store.deals.get(show["deal_id"])
    sales = [s for s in store.ticket_sales.values()
             if s["show_id"] == show["id"] and s["refund_status"] == "NONE"]
    gross = sum(s["gross_amount_cents"] for s in sales)

    recoupable = recoupable_expenses(show, deal)
    net_door = max(0, gross - recoupable)

    guarantee = deal.get("guarantee_cents") or 0
    kind = deal["deal_kind"]
    if kind == "FLAT_GUARANTEE":
        door_share = guarantee
        guarantee_paid = guarantee
        bonus = 0
    elif kind == "DOOR_SPLIT":
        door_share = rhu(Decimal(net_door) * dec(deal.get("artist_split_pct") or 0))
        guarantee_paid = 0
        bonus = 0
    else:  # VERSUS: guarantee plus marginal split above threshold, ">" strict
        threshold = deal.get("versus_threshold_cents") or 0
        component = rhu(Decimal(max(0, net_door - threshold)) * dec(deal.get("artist_split_pct") or 0))
        if net_door > threshold:
            door_share = guarantee + component
            guarantee_paid = guarantee
            bonus = component
        else:
            door_share = guarantee
            guarantee_paid = guarantee
            bonus = 0

    bar_rows = [a for a in store.ancillary_revenues.values()
                if a["show_id"] == show["id"] and a["kind"] == "BAR"]
    bar_gross = sum(a["gross_cents"] for a in bar_rows)
    bar_cost = sum(a["cost_cents"] for a in bar_rows)
    bar_share = rhu(Decimal(max(0, bar_gross - bar_cost)) * dec(deal.get("bar_split_pct") or 0))

    merch_rows = [a for a in store.ancillary_revenues.values()
                  if a["show_id"] == show["id"] and a["kind"] == "MERCH"]
    merch_gross = sum(a["gross_cents"] for a in merch_rows)
    merch_share = rhu(Decimal(merch_gross) * dec(deal.get("merch_split_pct") or 0))

    support_payouts = sum(a["paid_cents"] for a in store.support_acts.values()
                          if a["show_id"] == show["id"])

    deposit_credit = show["deposit_paid_cents"]
    artist_total = max(0, door_share + bar_share - deposit_credit)
    venue_net = (net_door - door_share - support_payouts + merch_share
                 + max(0, bar_gross - bar_cost - bar_share))

    return {
        "gross_ticket_revenue_cents": gross,
        "recoupable_expenses_cents": recoupable,
        "net_door_cents": net_door,
        "artist_door_share_cents": door_share,
        "guarantee_paid_cents": guarantee_paid,
        "bonus_cents": bonus,
        "bar_artist_share_cents": bar_share,
        "merch_venue_share_cents": merch_share,
        "support_payouts_cents": support_payouts,
        "deposit_credit_cents": deposit_credit,
        "artist_total_due_cents": artist_total,
        "venue_net_cents": venue_net,
    }


def recompute_draft_settlement(settlement):
    """Refresh a DRAFT settlement from current show state."""
    show = store.shows.get(settlement["show_id"])
    if show is None or show.get("deal_id") is None:
        return
    settlement.update(compute_settlement_fields(show))
    store.touch(settlement)


# ---------------------------------------------------------------------------
# Cancellation policy (cancellation_policy)
# ---------------------------------------------------------------------------
def low_sales_threshold(total_capacity):
    return math.ceil(Fraction(3, 10) * total_capacity)


def cancellation_figures(show, reason, deal, confirmed_supports):
    declared = store.now()
    show_date = show["_show_date_obj"]
    days = (show_date - declared.date()).days
    days = max(0, days)

    guarantee = (deal or {}).get("guarantee_cents") or 0

    if reason == "ARTIST":
        if days >= 60:
            pct = 0.0
        elif days >= 30:
            pct = 0.25
        elif days >= 14:
            pct = 0.50
        elif days >= 7:
            pct = 0.75
        else:
            pct = 1.00
        penalty_cents = rhu(Decimal(guarantee) * dec(pct))
        refundable = 0
    elif reason == "VENUE":
        pct = 0.0
        penalty_cents = 0
        refundable = 0
    elif reason == "FORCE_MAJEURE":
        pct = 0.0
        penalty_cents = 0
        refundable = show["deposit_paid_cents"]
    else:  # LOW_TICKET_SALES
        pct = 0.0
        penalty_cents = 0
        refundable = show["deposit_paid_cents"]

    if reason in ("ARTIST", "VENUE", "LOW_TICKET_SALES"):
        kill_fee = sum(rhu(Decimal(a["agreed_fee_cents"]) * Decimal("0.5"))
                       for a in confirmed_supports)
    else:
        kill_fee = 0

    return {
        "days_before_show": days,
        "artist_penalty_pct": pct,
        "artist_penalty_cents": penalty_cents,
        "deposit_refundable_cents": refundable,
        "support_kill_fee_cents": kill_fee,
    }


def support_budget_usage(show, extra_confirmed=None, extra_bought_out=None):
    """Cumulative support spend: buyout fees across BOUGHT_OUT acts plus
    agreed fees across CONFIRMED acts on the show."""
    total = 0
    for a in store.support_acts.values():
        if a["show_id"] != show["id"]:
            continue
        if a["status"] == "BOUGHT_OUT":
            total += a["buyout_fee_cents"]
        elif a["status"] == "CONFIRMED":
            total += a["agreed_fee_cents"]
    if extra_bought_out is not None:
        total += extra_bought_out
    if extra_confirmed is not None:
        total += extra_confirmed
    return total


def check_support_budget(show, extra_confirmed=None, extra_bought_out=None):
    deal = store.deals.get(show.get("deal_id")) if show.get("deal_id") else None
    if deal is None:
        return
    cap = deal.get("support_budget_cents")
    if cap is None:
        return
    usage = support_budget_usage(show, extra_confirmed, extra_bought_out)
    if usage > cap:
        raise biz("ERR_SUPPORT_BUDGET_EXCEEDED",
                  "Cumulative support spend would exceed the deal's support budget")
