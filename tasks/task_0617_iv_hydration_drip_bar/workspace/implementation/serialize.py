"""Serialize internal records into API resource objects.

Each entity exposes its persisted fields plus the common system fields id,
created_at, updated_at, version. Datetime-typed fields are rendered ISO 8601
UTC with three fractional digits.
"""
import db


def _common(record):
    return {
        "id": record["id"],
        "created_at": db.iso(record["created_at"]),
        "updated_at": db.iso(record["updated_at"]),
        "version": record["version"],
    }


def menu_item(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "tier": r["tier"],
        "base_price_cents": r["base_price_cents"],
        "requires_standing_order": r["requires_standing_order"],
        "g6pd_sensitive": r["g6pd_sensitive"],
        "active": r["active"],
    })
    return out


def add_on(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "code": r["code"],
        "price_cents": r["price_cents"],
        "active": r["active"],
    })
    return out


def patient(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "date_of_birth": db.iso(r["date_of_birth"]),
        "membership_id": r["membership_id"],
        "open_adverse_event_count": r["open_adverse_event_count"],
    })
    return out


def membership(r):
    out = _common(r)
    out.update({
        "tier": r["tier"],
        "covered_drip_tier": r["covered_drip_tier"],
        "drip_credits_total": r["drip_credits_total"],
        "drip_credits_remaining": r["drip_credits_remaining"],
        "addon_credits_total": r["addon_credits_total"],
        "addon_credits_remaining": r["addon_credits_remaining"],
        "status": r["status"],
    })
    return out


def standing_order(r):
    out = _common(r)
    out.update({
        "medical_director_user_id": r["medical_director_user_id"],
        "covered_tier": r["covered_tier"],
        "effective_from": db.iso(r["effective_from"]),
        "expires_at": db.iso(r["expires_at"]),
        "status": r["status"],
    })
    return out


def nurse(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "license_number": r["license_number"],
        "home_lounge_id": r["home_lounge_id"],
        "status": r["status"],
    })
    return out


def lounge(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "bay_count": r["bay_count"],
        "open_minute_of_day": r["open_minute_of_day"],
        "close_minute_of_day": r["close_minute_of_day"],
    })
    return out


def appointment(r):
    out = _common(r)
    out.update({
        "patient_id": r["patient_id"],
        "menu_item_id": r["menu_item_id"],
        "addon_ids": list(r["addon_ids"]),
        "location_type": r["location_type"],
        "lounge_id": r["lounge_id"],
        "route_id": r["route_id"],
        "nurse_id": r["nurse_id"],
        "standing_order_id": r["standing_order_id"],
        "start_at": db.iso(r["start_at"]),
        "duration_minutes": r["duration_minutes"],
        "membership_id": r["membership_id"],
        "status": r["status"],
        "amount_charged_cents": r["amount_charged_cents"],
        "drip_credit_used": r["drip_credit_used"],
        "addon_credits_used": r["addon_credits_used"],
    })
    return out


def intake_screening(r):
    out = _common(r)
    out.update({
        "appointment_id": r["appointment_id"],
        "author_user_id": r["author_user_id"],
        "pregnancy": r["pregnancy"],
        "renal_impairment": r["renal_impairment"],
        "cardiac_history": r["cardiac_history"],
        "g6pd_deficiency": r["g6pd_deficiency"],
        "recent_adverse_event": r["recent_adverse_event"],
        "contraindication_score": r["contraindication_score"],
        "outcome": r["outcome"],
        "status": r["status"],
    })
    return out


def consent(r):
    out = _common(r)
    out.update({
        "appointment_id": r["appointment_id"],
        "signed_by_patient": r["signed_by_patient"],
        "witness_user_id": r["witness_user_id"],
        "status": r["status"],
    })
    return out


def supply_lot(r):
    out = _common(r)
    out.update({
        "item_kind": r["item_kind"],
        "tier_or_code": r["tier_or_code"],
        "lot_number": r["lot_number"],
        "units_total": r["units_total"],
        "units_reserved": r["units_reserved"],
        "units_consumed": r["units_consumed"],
        "expires_at": db.iso(r["expires_at"]),
        "status": r["status"],
    })
    return out


def dispatch_route(r):
    out = _common(r)
    out.update({
        "nurse_id": r["nurse_id"],
        "service_date": db.iso(r["service_date"]),
        "turnaround_minutes": r["turnaround_minutes"],
        "stop_count": r["stop_count"],
        "status": r["status"],
    })
    return out


def adverse_event(r):
    out = _common(r)
    out.update({
        "appointment_id": r["appointment_id"],
        "reported_by_user_id": r["reported_by_user_id"],
        "severity": r["severity"],
        "description": r["description"],
        "status": r["status"],
    })
    return out
