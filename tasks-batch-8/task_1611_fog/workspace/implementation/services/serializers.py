"""Entity -> JSON-serializable dict serializers (computed fields resolved live)."""
from db import now
from services.calculations import (
    pumping_frequency_days,
    pumping_overdue,
    missed_pump_windows,
    open_violation_count,
    campaign_remaining_budget,
)
from validation import fmt_dt


def ser_establishment(est):
    current = now()
    return {
        "id": est["id"],
        "name": est["name"],
        "street_address": est["street_address"],
        "seating_capacity": est["seating_capacity"],
        "fryer_count": est["fryer_count"],
        "has_charbroiler": est["has_charbroiler"],
        "cuisine_profile": est["cuisine_profile"],
        "risk_score": est["risk_score"],
        "risk_class": est["risk_class"],
        "compliance_status": est["compliance_status"],
        "open_violation_count": open_violation_count(est["id"]),
        "last_verified_pump_at": fmt_dt(est["last_verified_pump_at"]),
        "variance_override_frequency_days": est["variance_override_frequency_days"],
        "pumping_frequency_days": pumping_frequency_days(est),
        "pumping_overdue": pumping_overdue(est, current),
        "missed_pump_windows": missed_pump_windows(est, current),
        "created_at": fmt_dt(est["created_at"]),
        "updated_at": fmt_dt(est["updated_at"]),
        "version": est["version"],
    }


def ser_interceptor(ic):
    return {
        "id": ic["id"],
        "establishment_id": ic["establishment_id"],
        "nominal_capacity_gal": ic["nominal_capacity_gal"],
        "measured_flow_gpm": ic["measured_flow_gpm"],
        "provisional_required_gal": ic["provisional_required_gal"],
        "required_min_capacity_gal": ic["required_min_capacity_gal"],
        "sizing_method": ic["sizing_method"],
        "status": ic["status"],
        "approved_by_user_id": ic["approved_by_user_id"],
        "commissioned_by_user_id": ic["commissioned_by_user_id"],
        "created_at": fmt_dt(ic["created_at"]),
        "updated_at": fmt_dt(ic["updated_at"]),
        "version": ic["version"],
    }


def ser_inspection(insp):
    return {
        "id": insp["id"],
        "establishment_id": insp["establishment_id"],
        "items": insp["items"],
        "inspector_user_id": insp["inspector_user_id"],
        "score": insp["score"],
        "passed": insp["passed"],
        "created_at": fmt_dt(insp["created_at"]),
    }


def ser_violation(v):
    return {
        "id": v["id"],
        "establishment_id": v["establishment_id"],
        "inspection_id": v["inspection_id"],
        "severity": v["severity"],
        "status": v["status"],
        "cure_deadline": fmt_dt(v["cure_deadline"]),
        "fine_cents": v["fine_cents"],
        "recorded_by_user_id": v["recorded_by_user_id"],
        "escalated_at": fmt_dt(v["escalated_at"]),
        "resolved_at": fmt_dt(v["resolved_at"]),
        "dismissed_at": fmt_dt(v["dismissed_at"]),
        "dismissed_by_user_id": v["dismissed_by_user_id"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def ser_manifest(m):
    return {
        "id": m["id"],
        "establishment_id": m["establishment_id"],
        "interceptor_id": m["interceptor_id"],
        "hauler_id": m["hauler_id"],
        "pump_date": fmt_dt(m["pump_date"]),
        "pumped_volume_gal": m["pumped_volume_gal"],
        "status": m["status"],
        "submitted_by_user_id": m["submitted_by_user_id"],
        "reject_reason": m["reject_reason"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_hauler(h):
    return {
        "id": h["id"],
        "name": h["name"],
        "permit_number": h["permit_number"],
        "insurance_expires_on": fmt_dt(h["insurance_expires_on"]),
        "status": h["status"],
        "mismatch_count": h["mismatch_count"],
        "created_at": fmt_dt(h["created_at"]),
        "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def ser_disposal(d):
    return {
        "id": d["id"],
        "hauler_id": d["hauler_id"],
        "manifest_id": d["manifest_id"],
        "disposed_volume_gal": d["disposed_volume_gal"],
        "disposal_site_name": d["disposal_site_name"],
        "disposed_at": fmt_dt(d["disposed_at"]),
        "created_at": fmt_dt(d["created_at"]),
    }


def ser_blockage(be):
    return {
        "id": be["id"],
        "location_description": be["location_description"],
        "status": be["status"],
        "total_cleanup_cost_cents": be["total_cleanup_cost_cents"],
        "contributions": [
            {
                "establishment_id": c["establishment_id"],
                "weight_percent": c["weight_percent"],
                "share_cents": c.get("share_cents"),
                "paid_at": fmt_dt(c.get("paid_at")),
            }
            for c in be["contributions"]
        ],
        "reported_by_user_id": be["reported_by_user_id"],
        "assessed_by_user_id": be["assessed_by_user_id"],
        "closed_by_user_id": be["closed_by_user_id"],
        "created_at": fmt_dt(be["created_at"]),
        "updated_at": fmt_dt(be["updated_at"]),
        "version": be["version"],
    }


def ser_variance(v):
    return {
        "id": v["id"],
        "establishment_id": v["establishment_id"],
        "scope": v["scope"],
        "requested_frequency_days": v["requested_frequency_days"],
        "justification": v["justification"],
        "effective_from": fmt_dt(v["effective_from"]),
        "effective_to": fmt_dt(v["effective_to"]),
        "status": v["status"],
        "approved_by_user_id": v["approved_by_user_id"],
        "decided_at": fmt_dt(v["decided_at"]),
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def ser_campaign(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "outreach_zone": c["outreach_zone"],
        "start_date": fmt_dt(c["start_date"]),
        "end_date": fmt_dt(c["end_date"]),
        "budget_cents": c["budget_cents"],
        "remaining_budget_cents": campaign_remaining_budget(c),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_outreach_event(e):
    return {
        "id": e["id"],
        "campaign_id": e["campaign_id"],
        "event_date": fmt_dt(e["event_date"]),
        "venue_name": e["venue_name"],
        "attendance_count": e["attendance_count"],
        "cost_cents": e["cost_cents"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }
