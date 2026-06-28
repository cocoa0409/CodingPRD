"""Entity -> response-dict serializers (scaffold §1.1 field lists).

Records are stored as plain dicts already shaped close to the output contract.
Computed/derived fields are kept reconciled on the record by the services layer
(PRD §2.6) and emitted here. Internal bookkeeping keys (prefixed '_') are never
emitted.
"""

from clock import format_iso8601_ms
from services.compute import (
    subscription_current_cycle_end_at_iso,
)


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def serialize_location(loc):
    out = _common(loc)
    out.update({
        "name": loc["name"],
        "state_code": loc["state_code"],
        "timezone": loc["timezone"],
        "status": loc["status"],
        "open_booking_count": loc["open_booking_count"],
    })
    return out


def serialize_service_type(st):
    out = _common(st)
    out.update({
        "code": st["code"],
        "name": st["name"],
        "duration_minutes": st["duration_minutes"],
        "buffer_minutes": st["buffer_minutes"],
        "credit_cost": st["credit_cost"],
        "requires_medical_clearance": st["requires_medical_clearance"],
        "active": st["active"],
    })
    return out


def serialize_room(room):
    out = _common(room)
    out.update({
        "location_id": room["location_id"],
        "service_type_id": room["service_type_id"],
        "name": room["name"],
        "status": room["status"],
    })
    return out


def serialize_technician(tech):
    out = _common(tech)
    out.update({
        "location_id": tech["location_id"],
        "full_name": tech["full_name"],
        "status": tech["status"],
    })
    return out


def serialize_shift(shift):
    out = _common(shift)
    out.update({
        "technician_id": shift["technician_id"],
        "location_id": shift["location_id"],
        "starts_at": shift["starts_at"],
        "ends_at": shift["ends_at"],
        "status": shift["status"],
    })
    return out


def serialize_membership_plan(plan):
    out = _common(plan)
    out.update({
        "tier": plan["tier"],
        "monthly_fee_cents": plan["monthly_fee_cents"],
        "monthly_credit_grant": plan["monthly_credit_grant"],
        "rollover_cap": plan["rollover_cap"],
        "late_cancel_fee_waived": plan["late_cancel_fee_waived"],
        "active": plan["active"],
    })
    return out


def serialize_member(member):
    out = _common(member)
    out.update({
        "home_location_id": member["home_location_id"],
        "email": member["email"],
        "full_name": member["full_name"],
        "state_code": member["state_code"],
        "contraindication_flag": member["contraindication_flag"],
        "intro_offer_used": member["intro_offer_used"],
        "credit_balance": member["credit_balance"],
        "status": member["status"],
    })
    return out


def serialize_waiver(waiver):
    out = _common(waiver)
    out.update({
        "member_id": waiver["member_id"],
        "screening_answers": waiver["screening_answers"],
        "has_contraindication": waiver["has_contraindication"],
        "signed_at": waiver["signed_at"],
        "status": waiver["status"],
    })
    return out


def serialize_subscription(sub):
    out = _common(sub)
    out.update({
        "member_id": sub["member_id"],
        "plan_id": sub["plan_id"],
        "status": sub["status"],
        "cycle_anchor_at": sub["cycle_anchor_at"],
        "current_cycle_end_at": subscription_current_cycle_end_at_iso(sub),
        "granted_credits_remaining": sub["granted_credits_remaining"],
        "freeze_cycles_remaining": sub["freeze_cycles_remaining"],
        "lifetime_paid_cents": sub["lifetime_paid_cents"],
    })
    return out


def serialize_credit_pack(pack):
    out = _common(pack)
    out.update({
        "member_id": pack["member_id"],
        "is_intro": pack["is_intro"],
        "total_credits": pack["total_credits"],
        "remaining_credits": pack["remaining_credits"],
        "price_paid_cents": pack["price_paid_cents"],
        "status": pack["status"],
        "expires_at": pack["expires_at"],
    })
    return out


def serialize_booking(booking):
    out = _common(booking)
    out.update({
        "member_id": booking["member_id"],
        "location_id": booking["location_id"],
        "room_id": booking["room_id"],
        "service_type_id": booking["service_type_id"],
        "starts_at": booking["starts_at"],
        "occupies_until_at": booking["occupies_until_at"],
        "credits_charged": booking["credits_charged"],
        "credit_source": booking["credit_source"],
        "fee_charged_cents": booking["fee_charged_cents"],
        "status": booking["status"],
    })
    return out


def serialize_invoice(inv):
    # Append-only, immutable: only id + created_at common fields (PRD §2.4).
    return {
        "id": inv["id"],
        "created_at": inv["created_at"],
        "subscription_id": inv["subscription_id"],
        "kind": inv["kind"],
        "amount_cents": inv["amount_cents"],
        "status": inv["status"],
    }
