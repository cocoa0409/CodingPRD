"""Serialize internal records into JSON-safe API resource dicts.

Internal records store datetimes as aware datetime objects and bookkeeping under
keys prefixed with '_'. Serializers emit the public field set per entity with
ISO 8601 timestamps (3 fractional digits) and id/created_at/updated_at/version.
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


def patron(rec):
    out = _base(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "residency": rec["residency"],
        "residency_verified": rec["residency_verified"],
        "standing": rec["standing"],
        "no_show_strikes": rec["no_show_strikes"],
        "wallet_credit_cents": rec["wallet_credit_cents"],
    })
    return out


def facility(rec):
    out = _base(rec)
    out.update({
        "name": rec["name"],
        "facility_type": rec["facility_type"],
        "status": rec["status"],
        "hourly_rate_cents": rec["hourly_rate_cents"],
        "resident_discount_pct": rec["resident_discount_pct"],
        "prime_multiplier": rec["prime_multiplier"],
        "prime_start_hour": rec["prime_start_hour"],
        "prime_end_hour": rec["prime_end_hour"],
        "buffer_minutes": rec["buffer_minutes"],
        "deposit_cents": rec["deposit_cents"],
        "requires_coi": rec["requires_coi"],
        "min_coi_coverage_cents": rec["min_coi_coverage_cents"],
        "granted_permit_count": rec["granted_permit_count"],
    })
    return out


def insurance_certificate(rec):
    out = _base(rec)
    out.update({
        "patron_id": rec["patron_id"],
        "coverage_amount_cents": rec["coverage_amount_cents"],
        "effective_date": iso(rec["effective_date"]),
        "expiry_date": iso(rec["expiry_date"]),
        "status": rec["status"],
    })
    return out


def league_series(rec):
    out = _base(rec)
    out.update({
        "facility_id": rec["facility_id"],
        "patron_id": rec["patron_id"],
        "coi_id": rec["coi_id"],
        "weekday": rec["weekday"],
        "start_hour": rec["start_hour"],
        "duration_minutes": rec["duration_minutes"],
        "first_date": iso(rec["first_date"]),
        "occurrences": rec["occurrences"],
        "status": rec["status"],
        "granted_occurrence_count": rec["granted_occurrence_count"],
        "conflicted_occurrence_count": rec["conflicted_occurrence_count"],
    })
    return out


def permit(rec):
    out = _base(rec)
    out.update({
        "facility_id": rec["facility_id"],
        "patron_id": rec["patron_id"],
        "coi_id": rec["coi_id"],
        "league_id": rec["league_id"],
        "lottery_round_id": rec["lottery_round_id"],
        "start_at": iso(rec["start_at"]),
        "end_at": iso(rec["end_at"]),
        "is_prime_requested": rec["is_prime_requested"],
        "status": rec["status"],
        "pricing_residency": rec["pricing_residency"],
        "quoted_fee_cents": rec["quoted_fee_cents"],
        "final_fee_cents": rec["final_fee_cents"],
        "deposit_held_cents": rec["deposit_held_cents"],
        "refunded_cents": rec["refunded_cents"],
        "cancelled_lead_hours": rec["cancelled_lead_hours"],
    })
    return out


def payment(rec):
    out = _base(rec)
    out.update({
        "permit_id": rec["permit_id"],
        "fee_component_cents": rec["fee_component_cents"],
        "deposit_component_cents": rec["deposit_component_cents"],
        "status": rec["status"],
    })
    return out


def refund(rec):
    out = _base(rec)
    out.update({
        "permit_id": rec["permit_id"],
        "payment_id": rec["payment_id"],
        "refund_destination": rec["refund_destination"],
        "fee_refund_cents": rec["fee_refund_cents"],
        "deposit_refund_cents": rec["deposit_refund_cents"],
        "total_refund_cents": rec["total_refund_cents"],
    })
    return out


def lottery_round(rec):
    out = _base(rec)
    out.update({
        "facility_id": rec["facility_id"],
        "slot_start_at": iso(rec["slot_start_at"]),
        "slot_end_at": iso(rec["slot_end_at"]),
        "opens_at": iso(rec["opens_at"]),
        "closes_at": iso(rec["closes_at"]),
        "status": rec["status"],
        "entry_count": rec["entry_count"],
        "winning_entry_id": rec["winning_entry_id"],
    })
    return out


def lottery_entry(rec):
    out = _base(rec)
    out.update({
        "lottery_round_id": rec["lottery_round_id"],
        "patron_id": rec["patron_id"],
        "priority_weight": rec["priority_weight"],
        "entry_seq": rec["entry_seq"],
        "status": rec["status"],
    })
    return out
