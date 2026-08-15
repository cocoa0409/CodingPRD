"""Serializers — emit exactly the scaffold-declared fields, nothing internal."""
from domain import compute_strikes, overdue_fee_cents
from helpers import fmt_dt


def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def _opt_dt(v):
    return fmt_dt(v) if v is not None else None


def tier_view(store, t):
    d = _base(t)
    d.update({
        "code": t["code"],
        "annual_dues_cents": t["annual_dues_cents"],
        "observatory_access_level": t["observatory_access_level"],
        "loan_privilege": t["loan_privilege"],
        "max_concurrent_loans": t["max_concurrent_loans"],
    })
    return d


def member_view(store, m):
    d = _base(m)
    d.update({
        "full_name": m["full_name"],
        "email": m["email"],
        "tier_id": m["tier_id"],
        "status": m["status"],
        "dues_paid_through": fmt_dt(m["dues_paid_through"]),
        "effective_access_level": m["effective_access_level"],
        "no_show_strikes": compute_strikes(store, m["id"]),
        "joined_at": fmt_dt(m["joined_at"]),
    })
    return d


def invoice_view(store, i):
    d = _base(i)
    d.update({
        "member_id": i["member_id"],
        "period_start": fmt_dt(i["period_start"]),
        "period_end": fmt_dt(i["period_end"]),
        "amount_cents": i["amount_cents"],
        "status": i["status"],
    })
    return d


def payment_view(store, p):
    # Append-only: id + created_at only, no updated_at/version.
    return {
        "id": p["id"],
        "created_at": fmt_dt(p["created_at"]),
        "invoice_id": p["invoice_id"],
        "member_id": p["member_id"],
        "amount_cents": p["amount_cents"],
        "posted_at": fmt_dt(p["posted_at"]),
        "credit_applied_cents": p["credit_applied_cents"],
    }


def telescope_view(store, t):
    d = _base(t)
    d.update({
        "name": t["name"],
        "equipment_class": t["equipment_class"],
        "status": t["status"],
        "collimation_due_at": fmt_dt(t["collimation_due_at"]),
        "condition_score": t["condition_score"],
    })
    return d


def cert_view(store, c):
    d = _base(c)
    d.update({
        "member_id": c["member_id"],
        "equipment_class": c["equipment_class"],
        "issued_at": fmt_dt(c["issued_at"]),
        "expires_at": fmt_dt(c["expires_at"]),
        "status": c["status"],
    })
    return d


def loan_view(store, l):
    d = _base(l)
    fee = l["overdue_fees_cents"]
    if l["status"] == "OVERDUE":
        fee = overdue_fee_cents(l, store.clock)  # provisional, uncapped, not persisted
    d.update({
        "member_id": l["member_id"],
        "telescope_id": l["telescope_id"],
        "window_start": fmt_dt(l["window_start"]),
        "window_end": fmt_dt(l["window_end"]),
        "status": l["status"],
        "checkout_at": _opt_dt(l["checkout_at"]),
        "returned_at": _opt_dt(l["returned_at"]),
        "overdue_fees_cents": fee,
    })
    return d


def ticket_view(store, t):
    d = _base(t)
    d.update({
        "telescope_id": t["telescope_id"],
        "kind": t["kind"],
        "severity": t["severity"],
        "status": t["status"],
        "opened_at": fmt_dt(t["opened_at"]),
        "closed_at": _opt_dt(t["closed_at"]),
        "condition_delta": t["condition_delta"],
    })
    return d


def event_view(store, e):
    d = _base(e)
    d.update({
        "title": e["title"],
        "event_kind": e["event_kind"],
        "window_start": fmt_dt(e["window_start"]),
        "window_end": fmt_dt(e["window_end"]),
        "status": e["status"],
        "moon_illumination_pct": e["moon_illumination_pct"],
        "weather_cancellation_pct": e["weather_cancellation_pct"],
        "min_operators": e["min_operators"],
        "confirmed_operator_count": e["confirmed_operator_count"],
        "cancellation_reason": e["cancellation_reason"],
    })
    return d


def assignment_view(store, a):
    d = _base(a)
    d.update({
        "event_id": a["event_id"],
        "member_id": a["member_id"],
        "telescope_id": a["telescope_id"],
        "status": a["status"],
        "invited_at": fmt_dt(a["invited_at"]),
    })
    return d


def booking_view(store, b):
    d = _base(b)
    d.update({
        "event_id": b["event_id"],
        "group_name": b["group_name"],
        "party_size": b["party_size"],
        "contact_member_id": b["contact_member_id"],
        "deposit_cents": b["deposit_cents"],
        "status": b["status"],
    })
    return d


def reading_view(store, r):
    # Append-only: id + created_at only, no updated_at/version.
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "taken_by_member_id": r["taken_by_member_id"],
        "event_id": r["event_id"],
        "sqm_value": float(r["sqm_value"]),
        "taken_at": fmt_dt(r["taken_at"]),
    }


def report_view(store, r):
    d = _base(r)
    med = r["median_sqm"]
    d.update({
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "status": r["status"],
        "reading_count": r["reading_count"],
        "median_sqm": float(med) if med is not None else None,
        "advocacy_grade": r["advocacy_grade"],
    })
    return d
