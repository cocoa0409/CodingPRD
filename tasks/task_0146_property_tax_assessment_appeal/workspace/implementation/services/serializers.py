"""Convert internal record dicts into API-facing dicts."""

from datetime import datetime, timezone


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt


def _money(value):
    if value is None:
        return None
    # Render as float / int via the response serializer; here we leave Decimal alone
    return value


def _common(record):
    return {
        "id": record["id"],
        "created_at": _iso(record["created_at"]),
        "updated_at": _iso(record["updated_at"]),
        "version": record["version"],
    }


def serialize_owner(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "date_of_birth": rec["date_of_birth"],
        "veteran_status": rec.get("veteran_status", False),
        "disability_rating": rec.get("disability_rating", 0),
    })
    return out


def serialize_hearing_officer(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "active": rec.get("active", True),
    })
    return out


def serialize_property(rec):
    out = _common(rec)
    out.update({
        "owner_id": rec["owner_id"],
        "parcel_number": rec["parcel_number"],
        "market_value": _money(rec["market_value"]),
        "capped_value": _money(rec["capped_value"]),
        "ownership_change_date": _iso(rec.get("ownership_change_date")),
        "current_assessment_year": rec.get("current_assessment_year"),
    })
    return out


def serialize_assessment(rec):
    out = _common(rec)
    out.update({
        "property_id": rec["property_id"],
        "roll_year": rec["roll_year"],
        "prior_assessment_id": rec.get("prior_assessment_id"),
        "prior_capped_value": _money(rec.get("prior_capped_value")),
        "market_value_at_roll": _money(rec["market_value_at_roll"]),
        "capped_value": _money(rec.get("capped_value")),
        "cap_reset_applied": rec.get("cap_reset_applied"),
        "status": rec["status"],
        "issued_at": _iso(rec.get("issued_at")),
        "finalized_at": _iso(rec.get("finalized_at")),
        "appeal_window_closes_at": _iso(rec.get("appeal_window_closes_at")),
        "issued_by_user_id": rec.get("issued_by_user_id"),
    })
    return out


def serialize_exemption_application(rec):
    out = _common(rec)
    out.update({
        "property_id": rec["property_id"],
        "owner_id": rec["owner_id"],
        "exemption_type": rec["exemption_type"],
        "effective_roll_year": rec["effective_roll_year"],
        "status": rec["status"],
        "approved_amount": _money(rec.get("approved_amount")),
        "approved_at": _iso(rec.get("approved_at")),
        "revoked_reason": rec.get("revoked_reason"),
    })
    return out


def serialize_appeal(rec):
    out = _common(rec)
    out.update({
        "property_id": rec["property_id"],
        "assessment_id": rec["assessment_id"],
        "assessment_version": rec.get("assessment_version"),
        "owner_id": rec["owner_id"],
        "filed_grounds": rec["filed_grounds"],
        "claimed_value": _money(rec.get("claimed_value")),
        "status": rec["status"],
        "decision_outcome": rec.get("decision_outcome"),
        "decided_value": _money(rec.get("decided_value")),
    })
    return out


def serialize_hearing(rec):
    out = _common(rec)
    out.update({
        "appeal_id": rec["appeal_id"],
        "property_id": rec["property_id"],
        "scheduled_start": _iso(rec["scheduled_start"]),
        "scheduled_end": _iso(rec["scheduled_end"]),
        "hearing_room": rec["hearing_room"],
        "officer_id": rec["officer_id"],
        "status": rec["status"],
    })
    return out


def serialize_tax_bill(rec):
    out = _common(rec)
    out.update({
        "property_id": rec["property_id"],
        "assessment_id": rec.get("assessment_id"),
        "roll_year": rec["roll_year"],
        "taxable_value": _money(rec.get("taxable_value")),
        "total_exemption_amount": _money(rec.get("total_exemption_amount")),
        "mill_rate": _money(rec.get("mill_rate")),
        "base_tax_amount": _money(rec.get("base_tax_amount")),
        "amount_due": _money(rec.get("amount_due")),
        "total_payments_applied": _money(rec.get("total_payments_applied")),
        "status": rec["status"],
        "due_date": _iso(rec.get("due_date")),
        "issued_at": _iso(rec.get("issued_at")),
    })
    return out


def serialize_deferral_plan(rec):
    return {
        "id": rec["id"],
        "created_at": _iso(rec["created_at"]),
        "updated_at": _iso(rec["updated_at"]),
        "version": rec["version"],
        "tax_bill_id": rec["tax_bill_id"],
        "property_id": rec["property_id"],
        "principal_deferred": _money(rec.get("principal_deferred")),
        "annual_interest_rate": _money(rec.get("annual_interest_rate")),
        "accrued_interest": _money(rec.get("accrued_interest")),
        "started_at": _iso(rec.get("started_at")),
        "closed_at": _iso(rec.get("closed_at")),
        "status": rec["status"],
    }


def serialize_payment(rec):
    return {
        "id": rec["id"],
        "created_at": _iso(rec["created_at"]),
        "tax_bill_id": rec["tax_bill_id"],
        "amount": _money(rec["amount"]),
        "applied_at": _iso(rec.get("applied_at")),
        "status": rec["status"],
        "refund_reason": rec.get("refund_reason"),
    }
