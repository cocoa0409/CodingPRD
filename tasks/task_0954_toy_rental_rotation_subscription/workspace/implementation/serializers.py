"""Resource serializers.  Computed fields are derived at read time."""
from datetime import timedelta

from store import DB, clock, clock_date
from timestamps import calendar_months, iso3, stage_for, whole_days


# ---------------------------------------------------------------------------
# Shared internals
# ---------------------------------------------------------------------------

def _common(obj):
    return {
        "id": obj["id"],
        "created_at": obj["created_at"],
        "updated_at": obj["updated_at"],
        "version": obj["version"],
    }


def wallet_of(member_id):
    return sum(e["amount_cents"] for e in DB.ledger.values() if e["member_id"] == member_id)


def paused_days_used(sub):
    """Sum over windows starting within the trailing 365 days of the clock.

    Closed windows contribute consumed_days; the currently open (active)
    window contributes days elapsed so far; scheduled windows contribute
    their full duration.
    """
    today = clock_date()
    horizon = today - timedelta(days=365)
    used = 0
    for w in sub["pause_windows"]:
        if w["start_date"] < horizon:
            continue
        if w["closed"]:
            used += w["consumed_days"] or 0
        elif w["start_date"] > today:
            used += (w["end_date"] - w["start_date"]).days
        else:
            used += max(0, (min(today, w["end_date"]) - w["start_date"]).days)
    return used


def serialize_member(m):
    out = _common(m)
    out.update({
        "email": m["email"],
        "full_name": m["full_name"],
        "status": m["status"],
        "wallet_credit_cents": wallet_of(m["id"]),
    })
    return out


def serialize_child(c):
    out = _common(c)
    months = calendar_months(c["birthdate"], clock_date())
    out.update({
        "member_id": c["member_id"],
        "name": c["name"],
        "birthdate": c["birthdate"].isoformat(),
        "age_months": months,
        "developmental_stage": stage_for(months),
    })
    return out


def serialize_plan(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "toys_per_box": p["toys_per_box"],
        "swap_allowance_per_cycle": p["swap_allowance_per_cycle"],
        "max_holds": p["max_holds"],
        "rotation_cadence_days": p["rotation_cadence_days"],
        "rental_period_days": p["rental_period_days"],
        "buyout_discount_pct": p["buyout_discount_pct"],
    })
    return out


def serialize_subscription(s):
    out = _common(s)
    windows = []
    for w in s["pause_windows"]:
        windows.append({
            "start_date": w["start_date"].isoformat(),
            "end_date": w["end_date"].isoformat(),
            "consumed_days": w["consumed_days"],
            "closed": w["closed"],
        })
    out.update({
        "member_id": s["member_id"],
        "plan_id": s["plan_id"],
        "status": s["status"],
        "next_cycle_due_at": iso3(s["next_cycle_due_at"]),
        "pause_windows": windows,
        "current_pause_end": iso3(s["current_pause_end"]) if s["current_pause_end"] else None,
        "paused_days_used_365d": paused_days_used(s),
        "cancel_reason": s["cancel_reason"],
    })
    return out


def serialize_catalog_item(it):
    out = _common(it)
    out.update({
        "title": it["title"],
        "description": it["description"],
        "min_age_months": it["min_age_months"],
        "max_age_months": it["max_age_months"],
        "developmental_stages": list(it["developmental_stages"]),
        "piece_count": it["piece_count"],
        "retail_value_cents": it["retail_value_cents"],
        "replacement_value_cents": it["replacement_value_cents"],
        "status": it["status"],
    })
    return out


def serialize_copy(c):
    out = _common(c)
    out.update({
        "catalog_item_id": c["catalog_item_id"],
        "barcode": c["barcode"],
        "condition_grade": c["condition_grade"],
        "status": c["status"],
        "reserved_member_id": c["reserved_member_id"],
        "sanitization_started_at": iso3(c["sanitization_started_at"]) if c["sanitization_started_at"] else None,
        "last_sanitized_at": iso3(c["last_sanitized_at"]) if c["last_sanitized_at"] else None,
        "sanitization_cycle_count": c["sanitization_cycle_count"],
    })
    return out


def serialize_wishlist_entry(e):
    out = _common(e)
    out.update({
        "member_id": e["member_id"],
        "catalog_item_id": e["catalog_item_id"],
        "rank": e["rank"],
        "status": e["status"],
        "held_copy_id": e["held_copy_id"],
        "hold_expires_at": iso3(e["hold_expires_at"]) if e["hold_expires_at"] else None,
    })
    return out


def _replacement_cap_cents(box):
    total = 0
    for it in DB.box_items.values():
        if it["rotation_box_id"] != box["id"]:
            continue
        if it["loan_status"] not in ("PENDING_RETURN", "RETURNED"):
            continue
        copy = DB.copies.get(it["toy_copy_id"])
        if not copy:
            continue
        cat = DB.catalog_items.get(copy["catalog_item_id"])
        if cat:
            total += cat["replacement_value_cents"]
    return total


def projected_late_fee(box):
    """Forward-looking late fee; 0 when not DELIVERED or not yet late."""
    if box["status"] != "DELIVERED" or box["due_date"] is None:
        return 0
    days_late = max(0, whole_days(box["due_date"], clock()))
    raw = days_late * 150
    return min(raw, _replacement_cap_cents(box))


def serialize_box(b):
    out = _common(b)
    out.update({
        "subscription_id": b["subscription_id"],
        "cycle_number": b["cycle_number"],
        "status": b["status"],
        "swap_count": b["swap_count"],
        "delivered_at": b["delivered_at"],
        "due_date": iso3(b["due_date"]) if b["due_date"] else None,
        "received_at": b["received_at"],
        "projected_late_fee_cents": projected_late_fee(b),
    })
    return out


def serialize_box_item(it):
    out = _common(it)
    out.update({
        "rotation_box_id": it["rotation_box_id"],
        "toy_copy_id": it["toy_copy_id"],
        "swapped_from_item_id": it["swapped_from_item_id"],
        "loan_status": it["loan_status"],
        "resolution_status": it["resolution_status"],
        "condition_returned": it["condition_returned"],
        "damage_severity": it["damage_severity"],
        "missing_piece_count": it["missing_piece_count"],
        "buyout_price_cents": it["buyout_price_cents"],
        "wallet_applied_cents": it["wallet_applied_cents"],
        "net_charge_cents": it["net_charge_cents"],
    })
    return out


def serialize_fee(f):
    out = _common(f)
    out.update({
        "subscription_id": f["subscription_id"],
        "box_item_id": f["box_item_id"],
        "rotation_box_id": f["rotation_box_id"],
        "fee_type": f["fee_type"],
        "amount_cents": f["amount_cents"],
        "status": f["status"],
        "dispute_rounds": f["dispute_rounds"],
    })
    return out


def serialize_shipment(s):
    out = _common(s)
    out.update({
        "rotation_box_id": s["rotation_box_id"],
        "direction": s["direction"],
        "carrier": s["carrier"],
        "tracking_number": s["tracking_number"],
        "status": s["status"],
        "events": [dict(ev) for ev in s["events"]],
    })
    return out


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "member_id": e["member_id"],
        "amount_cents": e["amount_cents"],
        "reason": e["reason"],
        "note": e["note"],
    }
