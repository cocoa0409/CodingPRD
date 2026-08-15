"""Entity serializers: internal storage uses date/datetime objects; output
uses ISO strings. Common fields per PRD 2.4."""

from util import ts3


def _base(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _dt(v):
    return ts3(v) if v is not None else None


def _d(v):
    return v.isoformat() if v is not None else None


def rate_card_out(r):
    out = _base(r)
    out.update({
        "market_code": r["market_code"],
        "display_type": r["display_type"],
        "base_weekly_cents": r["base_weekly_cents"],
        "illumination_premium_pct": r["illumination_premium_pct"],
        "traffic_tier_1_threshold": r["traffic_tier_1_threshold"],
        "traffic_tier_1_uplift_pct": r["traffic_tier_1_uplift_pct"],
        "traffic_tier_2_threshold": r["traffic_tier_2_threshold"],
        "traffic_tier_2_uplift_pct": r["traffic_tier_2_uplift_pct"],
        "status": r["status"],
    })
    return out


def face_out(r):
    out = _base(r)
    out.update({
        "face_code": r["face_code"],
        "structure_code": r["structure_code"],
        "market_code": r["market_code"],
        "display_type": r["display_type"],
        "illuminated": r["illuminated"],
        "daily_traffic_count": r["daily_traffic_count"],
        "width_inches": r["width_inches"],
        "height_inches": r["height_inches"],
        "loop_slots_total": r["loop_slots_total"],
        "status": r["status"],
        "booking_posture": r["booking_posture"],
        "current_permit_id": r["current_permit_id"],
    })
    return out


def permit_out(r):
    out = _base(r)
    out.update({
        "face_id": r["face_id"],
        "supersedes_permit_id": r["supersedes_permit_id"],
        "permit_number": r["permit_number"],
        "jurisdiction": r["jurisdiction"],
        "issued_on": _dt(r["issued_on"]),
        "expires_on": _dt(r["expires_on"]),
        "status": r["status"],
    })
    return out


def work_order_out(r):
    out = _base(r)
    out.update({
        "face_id": r["face_id"],
        "order_type": r["order_type"],
        "description": r["description"],
        "scheduled_start": _dt(r["scheduled_start"]),
        "scheduled_end": _dt(r["scheduled_end"]),
        "started_at": _dt(r["started_at"]),
        "completed_at": _dt(r["completed_at"]),
        "status": r["status"],
        "reopen_count": r["reopen_count"],
        "downtime_hours": r["downtime_hours"],
    })
    return out


def advertiser_out(r):
    out = _base(r)
    out.update({
        "name": r["name"],
        "credit_limit_cents": r["credit_limit_cents"],
        "credit_balance_cents": r["credit_balance_cents"],
        "exposure_cents": r["exposure_cents"],
        "status": r["status"],
    })
    return out


def campaign_out(r):
    out = _base(r)
    out.update({
        "advertiser_id": r["advertiser_id"],
        "name": r["name"],
        "start_date": _d(r["start_date"]),
        "end_date": _d(r["end_date"]),
        "status": r["status"],
        "billing_status": r["billing_status"],
        "contracted_cents": r["contracted_cents"],
        "discount_pct": r["discount_pct"],
        "net_contracted_cents": r["net_contracted_cents"],
        "cancellation_fees_cents": r["cancellation_fees_cents"],
        "production_charges_cents": r["production_charges_cents"],
        "delivery_posture": r["delivery_posture"],
    })
    return out


def flight_out(r):
    out = _base(r)
    entries = [{
        "period_start": _d(e["period_start"]),
        "period_end": _d(e["period_end"]),
        "source": e["source"],
        "impressions": e["impressions"],
    } for e in r["impression_entries"]]
    out.update({
        "campaign_id": r["campaign_id"],
        "face_id": r["face_id"],
        "rate_card_id": r["rate_card_id"],
        "predecessor_flight_id": r["predecessor_flight_id"],
        "start_date": _d(r["start_date"]),
        "end_date": _d(r["end_date"]),
        "loop_slots": r["loop_slots"],
        "held_until": _dt(r["held_until"]),
        "weeks": r["weeks"],
        "pinned_weekly_cents": r["pinned_weekly_cents"],
        "gross_cents": r["gross_cents"],
        "discount_pct": r["discount_pct"],
        "net_cents": r["net_cents"],
        "pinned_rate_card_version": r["pinned_rate_card_version"],
        "status": r["status"],
        "cancellation_fee_cents": r["cancellation_fee_cents"],
        "missed_days": r["missed_days"],
        "suspension_started_at": _dt(r["suspension_started_at"]),
        "suspension_days_accrued": r["suspension_days_accrued"],
        "holdover_weeks": r["holdover_weeks"],
        "holdover_charge_cents": r["holdover_charge_cents"],
        "impression_entries": entries,
        "estimated_impressions": r["estimated_impressions"],
        "delivered_impressions": r["delivered_impressions"],
        "delivery_ratio": r["delivery_ratio"],
    })
    return out


def artwork_out(r):
    out = _base(r)
    out.update({
        "flight_id": r["flight_id"],
        "creative_code": r["creative_code"],
        "material": r["material"],
        "width_inches": r["width_inches"],
        "height_inches": r["height_inches"],
        "revision_count": r["revision_count"],
        "production_charge_cents": r["production_charge_cents"],
        "status": r["status"],
    })
    return out


def posting_out(r):
    out = _base(r)
    out.update({
        "flight_id": r["flight_id"],
        "installer_user_id": r["installer_user_id"],
        "posted_on": _d(r["posted_on"]),
        "photo_proof_url": r["photo_proof_url"],
        "notes": r["notes"],
        "status": r["status"],
        "verified_by_user_id": r["verified_by_user_id"],
        "rejection_reason": r["rejection_reason"],
    })
    return out


def make_good_out(r):
    out = _base(r)
    out.update({
        "flight_id": r["flight_id"],
        "reason": r["reason"],
        "credit_cents": r["credit_cents"],
        "status": r["status"],
        "proposed_by": r["proposed_by"],
    })
    return out
