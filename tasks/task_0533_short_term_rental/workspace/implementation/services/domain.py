"""Core domain: entity records, serialization, lazy transitions, cascades."""
from datetime import datetime, timezone

from db import db, new_id
from clock import format_iso_ms, add_days
from services import calc

# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------


def _common_new():
    now = db.clock.now
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Refresh updated_at and bump version on a mutation."""
    rec["updated_at"] = db.clock.now
    rec["version"] += 1


def _fmt(dt):
    return format_iso_ms(dt) if dt is not None else None


# ---------------------------------------------------------------------------
# Lazy time-driven transitions
# ---------------------------------------------------------------------------


def apply_permit_expiry(permit):
    """Auto-transition ISSUED/ACTIVE -> EXPIRED when clock >= expires_at."""
    if permit["status"] in ("ISSUED", "ACTIVE") and permit.get("expires_at") is not None:
        if db.clock.now >= permit["expires_at"]:
            permit["status"] = "EXPIRED"
            _dec_zone_count(permit["zone_id"])
            touch(permit)


def apply_filing_delinquency(filing):
    """Auto-transition FILED -> DELINQUENT when clock >= due_at and underpaid."""
    if filing["status"] == "FILED" and filing.get("due_at") is not None:
        if db.clock.now >= filing["due_at"] and filing["amount_remitted_cents"] < filing["tot_due_cents"]:
            delta = db.clock.now - filing["due_at"]
            days_late = delta.days  # floor of days, non-negative
            filing["penalty_cents"] = calc.tax_penalty(
                filing["tot_due_cents"], filing["amount_remitted_cents"], days_late
            )
            filing["status"] = "DELINQUENT"
            touch(filing)


# ---------------------------------------------------------------------------
# Zone density count
# ---------------------------------------------------------------------------


def recompute_zone_count(zone):
    """Count permits linked to this zone whose status IN {ACTIVE, SUSPENDED}.
    (The stored active_permit_count also tracks ISSUED for cap purposes via
    increment/decrement bookkeeping; the GET recompute per PRD §3.1 counts
    ACTIVE/SUSPENDED.)"""
    # Per PRD §3.1: recompute from linked permits (ACTIVE or SUSPENDED) plus
    # ISSUED which also occupies a seat (§2.6). We keep the running counter as
    # the source of truth for cap arithmetic, but on GET we recompute the
    # occupying set to guarantee consistency.
    count = 0
    for p in db.permits.values():
        if p["zone_id"] == zone["id"] and p["status"] in ("ISSUED", "ACTIVE", "SUSPENDED"):
            count += 1
    zone["active_permit_count"] = count
    return count


def _dec_zone_count(zone_id):
    zone = db.zones.get(zone_id)
    if zone is not None and zone["active_permit_count"] > 0:
        zone["active_permit_count"] -= 1
        touch(zone)


def _inc_zone_count(zone_id):
    zone = db.zones.get(zone_id)
    if zone is not None:
        zone["active_permit_count"] += 1
        touch(zone)


# ---------------------------------------------------------------------------
# Strike aggregation
# ---------------------------------------------------------------------------


def permit_upheld_strikes(permit_id):
    total = 0
    for c in db.complaints.values():
        if c["permit_id"] == permit_id and c["status"] == "UPHELD":
            total += c["strike_points"]
    return total


def host_strike_total(host_id):
    total = 0
    permit_ids = {p["id"] for p in db.permits.values() if p["host_id"] == host_id}
    for c in db.complaints.values():
        if c["status"] == "UPHELD" and c["permit_id"] in permit_ids:
            total += c["strike_points"]
    return total


def recompute_host_standing(host):
    total = host_strike_total(host["id"])
    new_standing = "BARRED" if total >= 3 else "GOOD"
    changed = host["strike_total"] != total or host["standing"] != new_standing
    host["strike_total"] = total
    host["standing"] = new_standing
    if changed:
        touch(host)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def ser_zone(z):
    return {
        "id": z["id"],
        "zone_code": z["zone_code"],
        "str_eligible": z["str_eligible"],
        "whole_home_allowed": z["whole_home_allowed"],
        "permit_cap": z["permit_cap"],
        "active_permit_count": z["active_permit_count"],
        "lottery_enabled": z["lottery_enabled"],
        "created_at": _fmt(z["created_at"]),
        "updated_at": _fmt(z["updated_at"]),
        "version": z["version"],
    }


def ser_host(h):
    return {
        "id": h["id"],
        "email": h["email"],
        "full_name": h["full_name"],
        "primary_residence_property_id": h["primary_residence_property_id"],
        "strike_total": h["strike_total"],
        "standing": h["standing"],
        "created_at": _fmt(h["created_at"]),
        "updated_at": _fmt(h["updated_at"]),
        "version": h["version"],
    }


def ser_property(p):
    return {
        "id": p["id"],
        "host_id": p["host_id"],
        "zone_id": p["zone_id"],
        "street_address": p["street_address"],
        "bedroom_count": p["bedroom_count"],
        "is_primary_residence": p["is_primary_residence"],
        "max_occupancy": p["max_occupancy"],
        "created_at": _fmt(p["created_at"]),
        "updated_at": _fmt(p["updated_at"]),
        "version": p["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "property_id": p["property_id"],
        "host_id": p["host_id"],
        "zone_id": p["zone_id"],
        "permit_type": p["permit_type"],
        "attested_occupancy": p["attested_occupancy"],
        "safety_attested": p["safety_attested"],
        "issued_at": _fmt(p["issued_at"]),
        "expires_at": _fmt(p["expires_at"]),
        "nightly_base_rate_cents": p["nightly_base_rate_cents"],
        "status": p["status"],
        "created_at": _fmt(p["created_at"]),
        "updated_at": _fmt(p["updated_at"]),
        "version": p["version"],
    }


def ser_lottery(l):
    return {
        "id": l["id"],
        "zone_id": l["zone_id"],
        "seats_available": l["seats_available"],
        "awarded_permit_ids": l["awarded_permit_ids"],
        "status": l["status"],
        "created_at": _fmt(l["created_at"]),
        "updated_at": _fmt(l["updated_at"]),
        "version": l["version"],
    }


def ser_complaint(c):
    return {
        "id": c["id"],
        "permit_id": c["permit_id"],
        "category": c["category"],
        "strike_points": c["strike_points"],
        "status": c["status"],
        "created_at": _fmt(c["created_at"]),
        "updated_at": _fmt(c["updated_at"]),
        "version": c["version"],
    }


def ser_filing(f):
    return {
        "id": f["id"],
        "permit_id": f["permit_id"],
        "period_year": f["period_year"],
        "period_month": f["period_month"],
        "nights_booked": f["nights_booked"],
        "gross_revenue_cents": f["gross_revenue_cents"],
        "tot_due_cents": f["tot_due_cents"],
        "penalty_cents": f["penalty_cents"],
        "amount_remitted_cents": f["amount_remitted_cents"],
        "due_at": _fmt(f["due_at"]),
        "status": f["status"],
        "created_at": _fmt(f["created_at"]),
        "updated_at": _fmt(f["updated_at"]),
        "version": f["version"],
    }


def ser_listing_report(r):
    return {
        "id": r["id"],
        "platform_id": r["platform_id"],
        "claimed_permit_number": r["claimed_permit_number"],
        "street_address": r["street_address"],
        "reported_nights": r["reported_nights"],
        "match_result": r["match_result"],
        "matched_permit_id": r["matched_permit_id"],
        "created_at": _fmt(r["created_at"]),
    }


def ser_platform(p):
    return {
        "id": p["id"],
        "platform_name": p["platform_name"],
        "api_key": p["api_key"],
        "created_at": _fmt(p["created_at"]),
        "updated_at": _fmt(p["updated_at"]),
        "version": p["version"],
    }
