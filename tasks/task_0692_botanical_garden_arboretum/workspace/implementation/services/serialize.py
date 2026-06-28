"""Serializers: internal record dict -> API output dict.

Common fields (id, created_at, updated_at, version) are emitted on every entity.
datetime-valued fields are rendered ISO8601 UTC with three fractional digits.
Internal keys (those starting with '_') are never serialized.
"""
from db import iso

_COMMON = ["id", "created_at", "updated_at", "version"]


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def garden(rec):
    out = _base(rec)
    out.update({
        "name": rec["name"],
        "timezone": rec["timezone"],
        "reciprocal_network_code": rec["reciprocal_network_code"],
        "reciprocal_discount_pct": rec["reciprocal_discount_pct"],
        "household_member_cap": rec["household_member_cap"],
        "guest_pass_grant_household": rec["guest_pass_grant_household"],
        "guest_pass_grant_patron": rec["guest_pass_grant_patron"],
    })
    return out


def membership_plan(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "tier": rec["tier"],
        "annual_fee_cents": rec["annual_fee_cents"],
        "admission_included": rec["admission_included"],
        "event_discount_pct": rec["event_discount_pct"],
        "program_discount_pct": rec["program_discount_pct"],
        "active": rec["active"],
    })
    return out


def membership(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "plan_id": rec["plan_id"],
        "primary_member_name": rec["primary_member_name"],
        "household_member_names": rec["household_member_names"],
        "status": rec["status"],
        "auto_renew": rec["auto_renew"],
        "term_start": iso(rec["term_start"]),
        "term_end": iso(rec["term_end"]),
        "paid_total_cents": rec["paid_total_cents"],
        "guest_passes_remaining": rec["guest_passes_remaining"],
        "renewal_count": rec["renewal_count"],
    })
    return out


def time_slot(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "starts_at": iso(rec["starts_at"]),
        "ends_at": iso(rec["ends_at"]),
        "capacity": rec["capacity"],
        "ga_price_cents": rec["ga_price_cents"],
        "held_count": rec["held_count"],
        "status": rec["status"],
    })
    return out


def reservation(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "time_slot_id": rec["time_slot_id"],
        "membership_id": rec["membership_id"],
        "member_heads": rec["member_heads"],
        "guest_heads": rec["guest_heads"],
        "paid_heads": rec["paid_heads"],
        "reciprocal": rec["reciprocal"],
        "party_size": rec["party_size"],
        "admission_cents": rec["admission_cents"],
        "status": rec["status"],
    })
    return out


def event_ticket(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "membership_id": rec["membership_id"],
        "exhibit_name": rec["exhibit_name"],
        "list_price_cents": rec["list_price_cents"],
        "quantity": rec["quantity"],
        "charged_cents": rec["charged_cents"],
        "status": rec["status"],
    })
    return out


def program_session(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "title": rec["title"],
        "starts_at": iso(rec["starts_at"]),
        "capacity": rec["capacity"],
        "tuition_cents": rec["tuition_cents"],
        "enrolled_count": rec["enrolled_count"],
        "status": rec["status"],
    })
    return out


def registration(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "program_session_id": rec["program_session_id"],
        "membership_id": rec["membership_id"],
        "participant_name": rec["participant_name"],
        "charged_cents": rec["charged_cents"],
        "status": rec["status"],
        "waitlist_rank": rec["waitlist_rank"],
    })
    return out


def venue(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "name": rec["name"],
        "hourly_rate_cents": rec["hourly_rate_cents"],
        "buffer_minutes": rec["buffer_minutes"],
        "member_rental_discount_pct": rec["member_rental_discount_pct"],
    })
    return out


def rental(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "venue_id": rec["venue_id"],
        "membership_id": rec["membership_id"],
        "starts_at": iso(rec["starts_at"]),
        "ends_at": iso(rec["ends_at"]),
        "quoted_cents": rec["quoted_cents"],
        "final_cents": rec["final_cents"],
        "status": rec["status"],
    })
    return out


def donation(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "membership_id": rec["membership_id"],
        "amount_cents": rec["amount_cents"],
        "designation": rec["designation"],
        "tax_deductible_cents": rec["tax_deductible_cents"],
        "status": rec["status"],
    })
    return out


def conservancy_fund(rec):
    out = _base(rec)
    out.update({
        "garden_id": rec["garden_id"],
        "pledged_total_cents": rec["pledged_total_cents"],
        "matched_total_cents": rec["matched_total_cents"],
        "match_ratio": rec["match_ratio"],
        "match_cap_cents": rec["match_cap_cents"],
        "campaign_status": rec["campaign_status"],
    })
    return out
