"""Resource serializers — shape the JSON `data` payload for each entity.

Field names and sources trace to SCAFFOLD entities and PRD §2.4 (every primary
resource carries id, created_at, updated_at, version). Derived figures
(seats_taken, expected_headcount) are recomputed on read from current state.
"""
from services import departures as departure_svc


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def tour_product(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "theme": rec["theme"],
        "base_price_per_person_cents": rec["base_price_per_person_cents"],
        "gratuity_pct": rec["gratuity_pct"],
        "charter_fee_cents": rec["charter_fee_cents"],
        "min_guest_age": rec["min_guest_age"],
        "status": rec["status"],
    })
    return out


def add_on(rec):
    out = _common(rec)
    out.update({
        "tour_product_id": rec["tour_product_id"],
        "name": rec["name"],
        "price_per_person_cents": rec["price_per_person_cents"],
        "status": rec["status"],
    })
    return out


def vehicle(rec):
    out = _common(rec)
    out.update({
        "label": rec["label"],
        "seat_capacity": rec["seat_capacity"],
        "status": rec["status"],
    })
    return out


def partner_venue(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "kind": rec["kind"],
        "commission_pct": rec["commission_pct"],
        "tasting_cost_per_guest_cents": rec["tasting_cost_per_guest_cents"],
        "status": rec["status"],
    })
    return out


def pickup_point(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "address": rec["address"],
        "status": rec["status"],
    })
    return out


def departure(rec):
    out = _common(rec)
    out.update({
        "tour_product_id": rec["tour_product_id"],
        "vehicle_id": rec["vehicle_id"],
        "depart_at": rec["depart_at"],
        "return_at": rec["return_at"],
        "is_private_charter": rec["is_private_charter"],
        "seat_capacity": rec["seat_capacity"],
        "seats_taken": departure_svc.compute_seats_taken(rec["id"]),
        "expected_headcount": departure_svc.compute_expected_headcount(rec["id"]),
        "status": rec["status"],
        "cancel_reason": rec.get("cancel_reason"),
    })
    return out


def stop(rec):
    out = _common(rec)
    out.update({
        "departure_id": rec["departure_id"],
        "partner_venue_id": rec["partner_venue_id"],
        "sequence": rec["sequence"],
        "dwell_minutes": rec["dwell_minutes"],
        "estimated_commission_cents": rec["estimated_commission_cents"],
        "settled_commission_cents": rec["settled_commission_cents"],
        "status": rec["status"],
    })
    return out


def venue_confirmation(rec):
    out = _common(rec)
    out.update({
        "stop_id": rec["stop_id"],
        "partner_venue_id": rec["partner_venue_id"],
        "requested_headcount": rec["requested_headcount"],
        "revision_count": rec["revision_count"],
        "decline_note": rec.get("decline_note"),
        "status": rec["status"],
    })
    return out


def guest(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "birth_date": rec["birth_date"],
        "age_verified": rec["age_verified"],
        "waiver_signed": rec["waiver_signed"],
    })
    return out


def booking(rec):
    out = _common(rec)
    out.update({
        "departure_id": rec["departure_id"],
        "lead_guest_id": rec["lead_guest_id"],
        "pickup_point_id": rec["pickup_point_id"],
        "party_size": rec["party_size"],
        "add_on_id": rec.get("add_on_id"),
        "subtotal_cents": rec["subtotal_cents"],
        "gratuity_cents": rec["gratuity_cents"],
        "total_cents": rec["total_cents"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "refund_cents": rec["refund_cents"],
        "status": rec["status"],
        "payment_status": rec["payment_status"],
    })
    return out
