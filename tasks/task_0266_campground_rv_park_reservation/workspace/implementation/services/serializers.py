"""Serializers: produce the public JSON shape for each entity.

Computed fields (booked_night_count, nights, amount_paid_cents, balance_cents,
completed_stays_count, lifetime_spend_cents) are derived here so reads always
reflect the truth their inputs imply (PRD §2.7).
"""
from db import store
from services.common import parse_date

# Reservation statuses that count toward a site's booked nights (PRD §3.5).
ACTIVE_RES_STATUSES = {"REQUESTED", "CONFIRMED", "CHECKED_IN"}


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_park(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "timezone": p["timezone"],
        "check_in_time": p["check_in_time"],
        "check_out_time": p["check_out_time"],
        "quiet_hours_start": p["quiet_hours_start"],
        "quiet_hours_end": p["quiet_hours_end"],
        "deposit_pct": p["deposit_pct"],
        "tax_rate": p["tax_rate"],
        "long_stay_nights_threshold": p["long_stay_nights_threshold"],
    }
    out.update(_common(p))
    return out


def serialize_rate_plan(r):
    out = {
        "id": r["id"],
        "park_id": r["park_id"],
        "site_type": r["site_type"],
        "nightly_rate_cents": r["nightly_rate_cents"],
        "weekly_rate_cents": r["weekly_rate_cents"],
        "monthly_rate_cents": r["monthly_rate_cents"],
    }
    out.update(_common(r))
    return out


def serialize_season(s):
    out = {
        "id": s["id"],
        "park_id": s["park_id"],
        "name": s["name"],
        "start_date": s["start_date"],
        "end_date": s["end_date"],
        "surcharge_pct": s["surcharge_pct"],
    }
    out.update(_common(s))
    return out


def serialize_cancellation_policy(c):
    out = {
        "id": c["id"],
        "park_id": c["park_id"],
        "full_refund_min_days": c["full_refund_min_days"],
        "half_refund_min_days": c["half_refund_min_days"],
    }
    out.update(_common(c))
    return out


def compute_booked_night_count(site_id):
    """Sum of nights across the site's REQUESTED/CONFIRMED/CHECKED_IN reservations."""
    total = 0
    for r in store.reservations.values():
        if r["site_id"] == site_id and r["reservation_status"] in ACTIVE_RES_STATUSES:
            total += r["nights"]
    return max(0, total)


def serialize_site(s):
    out = {
        "id": s["id"],
        "park_id": s["park_id"],
        "rate_plan_id": s["rate_plan_id"],
        "label": s["label"],
        "site_type": s["site_type"],
        "hookup_level": s["hookup_level"],
        "max_length_of_stay_nights": s["max_length_of_stay_nights"],
        "turnover_buffer_days": s["turnover_buffer_days"],
        "status": s["status"],
        "booked_night_count": compute_booked_night_count(s["id"]),
    }
    out.update(_common(s))
    return out


def serialize_maintenance_hold(h):
    out = {
        "id": h["id"],
        "site_id": h["site_id"],
        "start_date": h["start_date"],
        "end_date": h["end_date"],
        "reason": h.get("reason"),
        "status": h["status"],
    }
    out.update(_common(h))
    return out


def compute_amount_paid(reservation_id):
    """Replay the ledger chronologically: DEPOSIT+BALANCE add, REFUND subtracts."""
    payments = [
        p for p in store.payments.values() if p["reservation_id"] == reservation_id
    ]
    payments.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = 0
    for p in payments:
        if p["type"] in ("DEPOSIT", "BALANCE"):
            total += p["amount_cents"]
        elif p["type"] == "REFUND":
            total -= p["amount_cents"]
    return total


def serialize_guest(g):
    completed = 0
    lifetime = 0
    for r in store.reservations.values():
        if r["guest_id"] == g["id"] and r["reservation_status"] == "CHECKED_OUT":
            completed += 1
            lifetime += r["total_due_cents"]
    out = {
        "id": g["id"],
        "email": g["email"],
        "full_name": g["full_name"],
        "completed_stays_count": completed,
        "lifetime_spend_cents": lifetime,
    }
    out.update(_common(g))
    return out


def serialize_reservation(r):
    amount_paid = compute_amount_paid(r["id"])
    balance = r["total_due_cents"] - amount_paid
    out = {
        "id": r["id"],
        "site_id": r["site_id"],
        "guest_id": r["guest_id"],
        "check_in_date": r["check_in_date"],
        "check_out_date": r["check_out_date"],
        "nights": r["nights"],
        "actual_check_out_date": r.get("actual_check_out_date"),
        "stay_class": r["stay_class"],
        "reservation_status": r["reservation_status"],
        "payment_status": r["payment_status"],
        "stay_charge_cents": r["stay_charge_cents"],
        "season_surcharge_cents": r["season_surcharge_cents"],
        "addon_total_cents": r["addon_total_cents"],
        "discount_cents": r["discount_cents"],
        "tax_cents": r["tax_cents"],
        "total_due_cents": r["total_due_cents"],
        "deposit_due_cents": r["deposit_due_cents"],
        "amount_paid_cents": amount_paid,
        "balance_cents": balance,
        "priced_nights": r["priced_nights"],
    }
    out.update(_common(r))
    return out


def serialize_addon(a):
    out = {
        "id": a["id"],
        "reservation_id": a["reservation_id"],
        "kind": a["kind"],
        "amount_cents": a["amount_cents"],
        "taxable": a["taxable"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def serialize_payment(p):
    # Payment is append-only: only id, reservation_id, type, amount_cents,
    # reason, created_at (no updated_at, no version) — PRD §2.4.
    return {
        "id": p["id"],
        "reservation_id": p["reservation_id"],
        "type": p["type"],
        "amount_cents": p["amount_cents"],
        "reason": p.get("reason"),
        "created_at": p["created_at"],
    }
