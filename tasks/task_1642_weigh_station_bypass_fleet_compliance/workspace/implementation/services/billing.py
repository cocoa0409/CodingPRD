"""Billing close, invoice preview, and ROI reporting (PRD 3.8; calculations
subscription_period_invoice, provisional_invoice_projection, roi_report).

Rounding order is pinned: each line is rounded HALF_UP to a whole cent, then
lines are summed into gross. Tier is an average rate: one rate applies to ALL
lines based on billed_line_count.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store
from util import fmt_ts
from services.credit import append_ledger, REASON_INVOICE_APPLICATION
from services.sweep import past_due_sweep

TIER_1_RATE_CENTS = 1799
TIER_2_RATE_CENTS = 1599
TIER_3_RATE_CENTS = 1399
PILOT_SURCHARGE_CENTS = 200
NET_TERMS_DAYS = 14
AVOIDED_COST_PER_BYPASS_CENTS = 1275


def _tier_for(count):
    if count >= 51:
        return "TIER_3", TIER_3_RATE_CENTS
    if count >= 11:
        return "TIER_2", TIER_2_RATE_CENTS
    return "TIER_1", TIER_1_RATE_CENTS


def _round_half_up(numer, denom):
    return int(
        (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def compute_lines(carrier, year, month):
    """One line per subscription whose service window intersects the period.
    overlap days are inclusive; paused days = accumulated counter plus the
    still-open pause interval confined to the overlap; billable = overlap -
    paused. Pilot surcharge applies when the vehicle's home state config is
    PILOT at evaluation time."""
    first = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last = date(year, month, days_in_month)
    configs_by_state = {c["state_code"]: c for c in store.configs.values()}

    raw = []
    subs = sorted(
        (s for s in store.subscriptions.values() if s["carrier_id"] == carrier["id"]),
        key=lambda s: s["_seq"],
    )
    for sub in subs:
        o_start = max(sub["_start"], first)
        o_end = min(sub["_end"], last)
        overlap_days = (o_end - o_start).days + 1
        if overlap_days <= 0:
            continue
        paused = sub["paused_days_current_period"]
        if sub["status"] == "PAUSED" and sub["paused_at"]:
            p_start = max(date.fromisoformat(sub["paused_at"]), o_start)
            seg = (o_end - p_start).days + 1
            if seg > 0:
                paused += seg
        billable = max(0, overlap_days - paused)
        surcharge = 0
        vehicle = store.vehicles.get(sub["vehicle_id"])
        if vehicle is not None:
            cfg = configs_by_state.get(vehicle["home_state_code"])
            if cfg is not None and cfg["participation_status"] == "PILOT":
                surcharge = PILOT_SURCHARGE_CENTS
        raw.append(
            {
                "vehicle_id": sub["vehicle_id"],
                "subscription_id": sub["id"],
                "surcharge_cents": surcharge,
                "billable_days": billable,
            }
        )

    count = len(raw)
    tier_name, tier_rate = _tier_for(count)
    lines = []
    for rl in raw:
        net = _round_half_up(
            (tier_rate + rl["surcharge_cents"]) * rl["billable_days"], days_in_month
        )
        lines.append(
            {
                "vehicle_id": rl["vehicle_id"],
                "subscription_id": rl["subscription_id"],
                "tier_rate_cents": tier_rate,
                "surcharge_cents": rl["surcharge_cents"],
                "billable_days": rl["billable_days"],
                "line_net_cents": net,
            }
        )
    gross = sum(l["line_net_cents"] for l in lines)
    return lines, count, tier_name, gross


def close_billing_period(carrier, year, month):
    """Persisted final close (variant final_at_close). Caller has already
    validated the period is fully elapsed and not already closed."""
    lines, count, tier_name, gross = compute_lines(carrier, year, month)
    credit_applied = min(carrier["credit_balance_cents"], gross)
    amount_due = gross - credit_applied
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    due = next_first + timedelta(days=NET_TERMS_DAYS)

    inv = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "carrier_id": carrier["id"],
        "period_year": year,
        "period_month": month,
        "lines": lines,
        "billed_line_count": count,
        "tier_applied": tier_name,
        "gross_cents": gross,
        "credit_applied_cents": credit_applied,
        "amount_due_cents": amount_due,
        "due_date": due.isoformat(),
        "status": "ISSUED",
        "issued_at": fmt_ts(db.now()),
        "version": 1,
    }
    db.stamp(inv)
    store.invoices[inv["id"]] = inv

    if credit_applied > 0:
        append_ledger(
            carrier, -credit_applied, REASON_INVOICE_APPLICATION, inv["id"]
        )
    if amount_due == 0:
        # Credit covered the gross in full (or nothing was billable): born PAID.
        inv["status"] = "PAID"

    # Reset pause bookkeeping on all of the carrier's subscriptions (a
    # still-paused row keeps its paused_at).
    for sub in store.subscriptions.values():
        if sub["carrier_id"] == carrier["id"] and sub["paused_days_current_period"] != 0:
            sub["paused_days_current_period"] = 0
            db.bump(sub)

    carrier["closed_billing_periods"].append(f"{year:04d}-{month:02d}")
    past_due_sweep(carrier_id=carrier["id"])
    carrier["version"] += 1
    carrier["updated_at"] = fmt_ts(db.now())
    return inv


def invoice_preview(carrier, year, month):
    """Forward-looking projection (variant provisional_preview): same line,
    tier, surcharge, and half-up rounding math; never persists, never applies
    credit (reports the credit that WOULD apply given the current balance)."""
    lines, count, tier_name, gross = compute_lines(carrier, year, month)
    credit_would = min(carrier["credit_balance_cents"], gross)
    return {
        "lines": lines,
        "billed_line_count": count,
        "tier_applied": tier_name,
        "gross_cents": gross,
        "credit_applied_cents": credit_would,
        "amount_due_cents": gross - credit_would,
        "period_year": year,
        "period_month": month,
    }


def roi_report(carrier, year, month, variant):
    events = [
        e
        for e in store.events.values()
        if e["carrier_id"] == carrier["id"]
        and (e["_approach_dt"].year, e["_approach_dt"].month) == (year, month)
    ]
    total = len(events)
    granted = sum(1 for e in events if e["decision"] == "BYPASS_GRANTED")
    pull_ins = total - granted
    verified = sum(
        1
        for e in events
        if e["decision"] == "BYPASS_GRANTED"
        and e["weight_verified"]
        and e["credentials_complete"]
    )
    bypass_rate_bps = 0 if total == 0 else (granted * 10000) // total
    counted = granted if variant == "STANDARD" else verified
    savings = counted * AVOIDED_COST_PER_BYPASS_CENTS
    inv = next(
        (
            i
            for i in store.invoices.values()
            if i["carrier_id"] == carrier["id"]
            and i["period_year"] == year
            and i["period_month"] == month
        ),
        None,
    )
    fees = inv["gross_cents"] if inv is not None else 0
    if fees == 0:
        roi_bps = None
    else:
        roi_bps = _round_half_up((savings - fees) * 10000, fees)
    inspections = sum(
        1
        for r in store.reports.values()
        if r["carrier_id"] == carrier["id"]
        and (r["_inspected_dt"].year, r["_inspected_dt"].month) == (year, month)
    )
    return {
        "period_year": year,
        "period_month": month,
        "variant": variant,
        "total_approaches": total,
        "bypasses_granted": granted,
        "pull_ins": pull_ins,
        "verified_bypasses": verified,
        "bypass_rate_bps": bypass_rate_bps,
        "estimated_savings_cents": savings,
        "subscription_fees_cents": fees,
        "roi_bps": roi_bps,
        "inspections_recorded": inspections,
        "inspection_reduction_bps": bypass_rate_bps,
    }
