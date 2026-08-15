"""Record -> API shape. Every primary resource carries id, created_at,
updated_at (ISO 8601 UTC, three fractional digits) and version (PRD 2.4).
Date fields render as YYYY-MM-DD strings; nullable fields render as null."""
from db import store
from util import fmt_date, fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_dt"]),
        "updated_at": fmt_dt(rec["updated_dt"]),
        "version": rec["version"],
    }


def ser_plan(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "plan_type": p["plan_type"],
        "issues_per_week": p["issues_per_week"],
        "base_weekly_rate_cents": p["base_weekly_rate_cents"],
        "step_up_schedule": [dict(s) for s in p["step_up_schedule"]],
        "proration_method": p["proration_method"],
        "min_weekly_rate_cents": p["min_weekly_rate_cents"],
        "status": p["status"],
    })
    return out


def ser_subscriber(s):
    out = _common(s)
    out.update({
        "display_name": s["display_name"],
        "email": s["email"],
        "service_address": s["service_address"],
        "status": s["status"],
        "balance_due_cents": s["balance_due_cents"],
        "unapplied_cash_cents": s["unapplied_cash_cents"],
    })
    return out


def ser_subscription(s):
    out = _common(s)
    out.update({
        "subscriber_id": s["subscriber_id"],
        "plan_id": s["plan_id"],
        "start_date": fmt_date(s["start_date"]),
        "billing_status": s["billing_status"],
        "delivery_status": s["delivery_status"],
        "next_charge_date": fmt_date(s["next_charge_date"]),
        "pending_plan_id": s["pending_plan_id"],
        "pending_plan_effective_date": fmt_date(s["pending_plan_effective_date"]),
        "save_discount_pct": s["save_discount_pct"],
        "save_discount_until": fmt_date(s["save_discount_until"]),
        "cancel_reason": s["cancel_reason"],
        "ended_at": fmt_date(s["ended_at"]),
    })
    return out


def ser_route(r):
    out = _common(r)
    out.update({
        "route_code": r["route_code"],
        "carrier_id": r["carrier_id"],
        "max_stops": r["max_stops"],
        "assigned_stop_count": r["assigned_stop_count"],
        "status": r["status"],
    })
    return out


def ser_carrier(c):
    out = _common(c)
    out.update({
        "display_name": c["display_name"],
        "compensation_model": c["compensation_model"],
        "per_copy_rate_cents": c["per_copy_rate_cents"],
        "status": c["status"],
    })
    return out


def ser_assignment(a):
    out = _common(a)
    out.update({
        "subscription_id": a["subscription_id"],
        "route_id": a["route_id"],
        "start_date": fmt_date(a["start_date"]),
        "end_date": fmt_date(a["end_date"]),
        "status": a["status"],
    })
    return out


def ser_hold(h):
    out = _common(h)
    out.update({
        "subscription_id": h["subscription_id"],
        "start_date": fmt_date(h["start_date"]),
        "end_date": fmt_date(h["end_date"]),
        "resolution": h["resolution"],
        "status": h["status"],
        "weekly_rate_snapshot_cents": h["weekly_rate_snapshot_cents"],
        "credit_amount_cents": h["credit_amount_cents"],
    })
    return out


def ser_complaint(c):
    out = _common(c)
    out.update({
        "subscription_id": c["subscription_id"],
        "service_date": fmt_date(c["service_date"]),
        "complaint_type": c["complaint_type"],
        "route_id": c["route_id"],
        "status": c["status"],
        "credit_amount_cents": c["credit_amount_cents"],
        "deny_reason": c["deny_reason"],
    })
    return out


def ser_credit_memo(m):
    out = _common(m)
    out.update({
        "subscriber_id": m["subscriber_id"],
        "source": m["source"],
        "complaint_id": m["complaint_id"],
        "hold_id": m["hold_id"],
        "amount_cents": m["amount_cents"],
        "applied_cents": m["applied_cents"],
        "reason": m["reason"],
        "status": m["status"],
    })
    return out


def ser_save_offer(o):
    out = _common(o)
    out.update({
        "subscription_id": o["subscription_id"],
        "offer_type": o["offer_type"],
        "discount_pct": o["discount_pct"],
        "duration_weeks": o["duration_weeks"],
        "origin": o["origin"],
        "status": o["status"],
        "expires_at": fmt_date(o["expires_at"]),
    })
    return out


def ser_rack(r):
    out = _common(r)
    out.update({
        "location_name": r["location_name"],
        "address": r["address"],
        "price_per_copy_cents": r["price_per_copy_cents"],
        "status": r["status"],
    })
    return out


def rack_copies_sold(r):
    return r["copies_delivered"] - r["copies_returned"]


def ser_rack_report(r):
    rack = store.racks.get(r["rack_location_id"])
    price = rack["price_per_copy_cents"] if rack else 0
    sold = rack_copies_sold(r)
    reported = r["reported_sold_copies"]
    variance = 0 if reported is None else reported - sold
    out = _common(r)
    out.update({
        "rack_location_id": r["rack_location_id"],
        "week_start_date": fmt_date(r["week_start_date"]),
        "copies_delivered": r["copies_delivered"],
        "copies_returned": r["copies_returned"],
        "reported_sold_copies": reported,
        "copies_sold": sold,
        "amount_due_cents": sold * price,
        "variance_copies": variance,
        "variance_flag": abs(variance) > 2,  # VARIANCE_TOLERANCE; == 2 not flagged
        "status": r["status"],
    })
    return out


def ser_payment(p):
    out = _common(p)
    out.update({
        "subscriber_id": p["subscriber_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "status": p["status"],
        "allocations": [dict(a) for a in p["allocations"]],
    })
    return out


def ser_charge(c):
    out = _common(c)
    out.update({
        "subscription_id": c["subscription_id"],
        "subscriber_id": c["subscriber_id"],
        "period_start": fmt_date(c["period_start"]),
        "period_end": fmt_date(c["period_end"]),
        "due_date": fmt_date(c["due_date"]),
        "amount_cents": c["amount_cents"],
        "paid_amount_cents": c["paid_amount_cents"],
        "credit_applied_cents": c["credit_applied_cents"],
        "status": c["status"],
    })
    return out


def ser_audit(a):
    out = _common(a)
    out.update({
        "period_start": fmt_date(a["period_start"]),
        "period_end": fmt_date(a["period_end"]),
        "paid_print_subscribers": a["paid_print_subscribers"],
        "paid_digital_subscribers": a["paid_digital_subscribers"],
        "single_copy_copies": a["single_copy_copies"],
        "status": a["status"],
        "certified_at": fmt_dt(a["certified_at"]) if a["certified_at"] else None,
    })
    return out
