"""The price ladder, its two variants, and invoice assembly (PRD 3.1 / 3.5 / 3.9)."""
from datetime import timedelta
from decimal import Decimal

import config
from clock import clock, parse_date
from db import db, new_entity
from response import mark_created, touch
from services.derive import (
    invoice_attempts,
    subscription_holds,
    subscription_invoices,
)
from services.money import dec, rhu


# ---------------------------------------------------------------- the rung walk
def resolve_rung(sub, plan, cycle_index):
    """Returns (price_cents, label). Grandfathering is checked without exception."""
    locked = sub.get("locked_price_cents")
    until = sub.get("grandfathered_until_cycle")
    if locked is not None and until is not None and cycle_index <= until:
        return locked, "GRANDFATHERED"
    if cycle_index <= plan["intro_cycles"]:
        return plan["intro_price_cents"], "INTRO"
    if cycle_index >= plan["standard_from_cycle"]:
        return plan["standard_price_cents"], "STANDARD"
    qualifying = [s for s in plan["step_up_schedule"] if s["from_cycle"] <= cycle_index]
    if qualifying:
        best = max(qualifying, key=lambda s: s["from_cycle"])
        return best["price_cents"], "STEP_UP"
    return plan["standard_price_cents"], "STANDARD"


def retention_fraction(sub):
    if sub.get("retention_discount_cycles_remaining", 0) >= 1:
        return dec(sub.get("retention_discount_pct") or 0)
    return Decimal("0")


# ---------------------------------------------------------------- forward-looking variant
def preview_quote(sub, plan):
    """What the reader will be charged next cycle if nothing changes."""
    next_cycle = sub["cycle_index"] + 1
    price, label = resolve_rung(sub, plan, next_cycle)
    if label == "STANDARD" and plan["price_change_state"] in ("SCHEDULED", "NOTICE_SENT"):
        effective_on = plan.get("pending_effective_on")
        pending = plan.get("pending_price_cents")
        if effective_on is not None and pending is not None:
            next_start = parse_date(sub["cycle_start_on"]) + timedelta(days=plan["cycle_days"])
            if parse_date(effective_on) <= next_start:
                price = pending
    fraction = retention_fraction(sub)
    if fraction > 0:
        price = price - rhu(dec(price) * fraction)
    return price


def recompute_next_price(sub, plan=None):
    plan = plan or db.offer_plans.get(sub["offer_plan_id"])
    if plan is None:
        return
    sub["next_cycle_price_cents"] = preview_quote(sub, plan)


# ---------------------------------------------------------------- billed variant
def billed_amount(sub, plan, cycle_index, cycle_start_on):
    price, label = resolve_rung(sub, plan, cycle_index)
    if label == "STANDARD" and plan["price_change_state"] == "APPLIED":
        effective_on = plan.get("pending_effective_on")
        if effective_on is not None:
            start = parse_date(cycle_start_on)
            end = start + timedelta(days=plan["cycle_days"])
            effective = parse_date(effective_on)
            if start < effective < end:
                old_price = plan.get("_pre_change_standard_price_cents")
                if old_price is None:
                    old_price = price
                days_before = (effective - start).days
                days_after = plan["cycle_days"] - days_before
                first = rhu(dec(old_price) * days_before / dec(plan["cycle_days"]))
                second = rhu(dec(price) * days_after / dec(plan["cycle_days"]))
                return first + second, "PRORATED_SEGMENTS"
    return price, label


# ---------------------------------------------------------------- seat charges
def seat_charge_assembly(sub, plan, cycle_start_on):
    """Per-line rounding, then summation; the sum is never re-rounded."""
    group_account_id = sub.get("group_account_id")
    if group_account_id is None:
        return 0
    window_start = parse_date(cycle_start_on)
    window_end = window_start + timedelta(days=plan["cycle_days"])
    participating = []
    for seat in db.seats.values():
        if seat.get("group_account_id") != group_account_id:
            continue
        if seat["status"] not in ("ACTIVE", "RECLAIMED"):
            continue
        starts_on = parse_date(seat["starts_on"])
        ends_on = parse_date(seat["ends_on"]) if seat.get("ends_on") else None
        if not starts_on < window_end:
            continue
        if ends_on is not None and not ends_on > window_start:
            continue
        participating.append((starts_on, seat["_seq"], seat, ends_on))
    participating.sort(key=lambda row: (row[0], row[1]))
    total = 0
    for starts_on, _seq, seat, ends_on in participating:
        occ_start = max(starts_on, window_start)
        occ_end = min(ends_on if ends_on is not None else window_end, window_end)
        active_days = max(0, (occ_end - occ_start).days)
        total += rhu(dec(plan["per_seat_price_cents"]) * active_days / dec(plan["cycle_days"]))
    return total


# ---------------------------------------------------------------- invoice assembly
def sweepable_credits(sub):
    holds = [
        h
        for h in subscription_holds(sub["id"])
        if h["status"] == "COMPLETED" and not h["credit_applied"]
    ]
    holds.sort(key=lambda h: (parse_date(h["end_date"]), h["_seq"]))
    return holds


def assemble_invoice(sub, plan, cycle_index, cycle_start_on):
    """The pinned eight-step waterfall of PRD 3.5."""
    base_line_cents, price_source = billed_amount(sub, plan, cycle_index, cycle_start_on)
    seat_line_cents = seat_charge_assembly(sub, plan, cycle_start_on)
    subtotal = base_line_cents + seat_line_cents

    fraction = retention_fraction(sub)
    if fraction > 0 and subtotal >= config.HIGH_VALUE_SUBTOTAL_CENTS:
        uplifted = fraction + dec(config.HIGH_VALUE_UPLIFT_PCT)
        fraction = min(uplifted, dec(config.SAVE_OFFER_DISCOUNT_CAP_PCT))
    discount_line_cents = rhu(dec(subtotal) * fraction) if fraction > 0 else 0

    credits = sweepable_credits(sub)
    credit_line_cents = sum(h["credit_cents"] for h in credits)

    total_cents = max(0, subtotal - discount_line_cents - credit_line_cents)

    invoice = new_entity()
    invoice.update(
        {
            "subscription_id": sub["id"],
            "cycle_index": cycle_index,
            "status": "VOID" if total_cents == 0 else "OPEN",
            "price_source": price_source,
            "base_line_cents": base_line_cents,
            "seat_line_cents": seat_line_cents,
            "discount_line_cents": discount_line_cents,
            "credit_line_cents": credit_line_cents,
            "total_cents": total_cents,
            "due_on": clock.date().isoformat(),
            "paid_on": None,
        }
    )
    db.invoices[invoice["id"]] = invoice
    mark_created(invoice)

    for hold in credits:
        hold["credit_applied"] = True
        hold["credit_applied_cycle_index"] = cycle_index
        touch(hold)

    if fraction > 0:
        sub["retention_discount_cycles_remaining"] = max(
            0, sub.get("retention_discount_cycles_remaining", 0) - 1
        )

    if total_cents == 0:
        base = sub.get("paid_through_on") or cycle_start_on
        sub["paid_through_on"] = (
            parse_date(base) + timedelta(days=plan["cycle_days"])
        ).isoformat()

    recompute_next_price(sub, plan)
    return invoice


def invoice_has_open_balance(sub):
    for invoice in subscription_invoices(sub["id"]):
        if invoice["status"] in ("OPEN", "PAST_DUE"):
            return True
    return False


def latest_attempt(invoice):
    attempts = invoice_attempts(invoice["id"])
    return attempts[-1] if attempts else None
