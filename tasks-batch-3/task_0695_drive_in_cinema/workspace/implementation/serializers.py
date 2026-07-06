"""Serialize internal entity dicts to public JSON payloads.

Internal entities carry private bookkeeping keys (prefixed with '_' such as
'_seq', plus datetime objects in *_dt fields). Serializers expose only the
PRD-specified fields, formatting datetimes per PRD §2.2/§2.4.

Common fields (PRD §2.4):
  - Film, WeatherEvent, RefundRecord carry ONLY id and created_at.
  - All other entities carry id, created_at, updated_at, version.
"""
from util import iso_now


def _common(e, include_updated_version=True):
    out = {"id": e["id"], "created_at": iso_now(e["_created_at"])}
    if include_updated_version:
        out["updated_at"] = iso_now(e["_updated_at"])
        out["version"] = e["version"]
    return out


def venue(e):
    out = _common(e)
    out.update({
        "name": e["name"],
        "timezone": e["timezone"],
        "fm_channel_pool": list(e["fm_channel_pool"]),
        "turnaround_buffer_minutes": e["turnaround_buffer_minutes"],
        "no_show_grace_minutes": e["no_show_grace_minutes"],
    })
    return out


def lot(e):
    out = _common(e)
    out.update({
        "venue_id": e["venue_id"],
        "name": e["name"],
        "stall_count": e["stall_count"],
        "person_capacity": e["person_capacity"],
        "status": e["status"],
    })
    return out


def film(e):
    out = _common(e, include_updated_version=False)
    out.update({
        "title": e["title"],
        "runtime_minutes": e["runtime_minutes"],
        "rating": e["rating"],
    })
    return out


def showtime(e):
    out = _common(e)
    out.update({
        "venue_id": e["venue_id"],
        "lot_id": e["lot_id"],
        "primary_film_id": e["primary_film_id"],
        "secondary_film_id": e["secondary_film_id"],
        "is_double_feature": e["is_double_feature"],
        "start_utc": iso_now(e["_start_dt"]),
        "end_utc": iso_now(e["_end_dt"]),
        "pricing_mode": e["pricing_mode"],
        "base_price_cents": e["base_price_cents"],
        "included_occupants": e["included_occupants"],
        "per_extra_person_cents": e["per_extra_person_cents"],
        "double_feature_surcharge_cents": e["double_feature_surcharge_cents"],
        "status": e["status"],
        "reserved_stall_count": e["reserved_stall_count"],
        "reserved_person_count": e["reserved_person_count"],
    })
    return out


def fm_channel_assignment(e):
    out = _common(e)
    out.update({
        "showtime_id": e["showtime_id"],
        "venue_id": e["venue_id"],
        "frequency": e["frequency"],
        "status": e["status"],
    })
    return out


def season_pass(e):
    out = _common(e)
    out.update({
        "patron_id": e["patron_id"],
        "tier": e["tier"],
        "max_redemptions": e["max_redemptions"],
        "redemptions_used": e["redemptions_used"],
        "valid_from_utc": iso_now(e["_valid_from_dt"]),
        "valid_to_utc": iso_now(e["_valid_to_dt"]),
        "status": e["status"],
    })
    return out


def reservation(e):
    out = _common(e)
    out.update({
        "showtime_id": e["showtime_id"],
        "lot_id": e["lot_id"],
        "patron_id": e["patron_id"],
        "occupant_count": e["occupant_count"],
        "season_pass_id": e["season_pass_id"],
        "promo_pct": e["promo_pct"],
        "amount_due_cents": e["amount_due_cents"],
        "amount_paid_cents": e["amount_paid_cents"],
        "stalls_used": e["stalls_used"],
        "gate_code": e["gate_code"],
        "occupancy_status": e["occupancy_status"],
        "payment_status": e["payment_status"],
    })
    return out


def concession_item(e):
    out = _common(e)
    out.update({
        "venue_id": e["venue_id"],
        "name": e["name"],
        "unit_price_cents": e["unit_price_cents"],
        "tax_rate": e["tax_rate"],
        "available": e["available"],
    })
    return out


def concession_order(e):
    out = _common(e)
    out.update({
        "reservation_id": e["reservation_id"],
        "lines": [dict(line) for line in e["lines"]],
        "subtotal_cents": e["subtotal_cents"],
        "tax_cents": e["tax_cents"],
        "service_fee_cents": e["service_fee_cents"],
        "total_cents": e["total_cents"],
        "status": e["status"],
    })
    return out


def private_rental(e):
    out = _common(e)
    out.update({
        "venue_id": e["venue_id"],
        "lot_id": e["lot_id"],
        "organizer_id": e["organizer_id"],
        "start_utc": iso_now(e["_start_dt"]),
        "end_utc": iso_now(e["_end_dt"]),
        "flat_venue_fee_cents": e["flat_venue_fee_cents"],
        "per_hour_cents": e["per_hour_cents"],
        "quote_cents": e["quote_cents"],
        "status": e["status"],
    })
    return out


def weather_event(e):
    out = _common(e, include_updated_version=False)
    out.update({
        "showtime_id": e["showtime_id"],
        "severity": e["severity"],
        "features_remaining": e["features_remaining"],
    })
    return out


def refund_record(e):
    out = _common(e, include_updated_version=False)
    out.update({
        "source_type": e["source_type"],
        "reservation_id": e["reservation_id"],
        "concession_order_id": e["concession_order_id"],
        "reason": e["reason"],
        "amount_cents": e["amount_cents"],
    })
    return out
