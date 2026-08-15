"""Entity -> JSON serializers. Datetimes serialized via util.iso (3dp Z)."""
from util import iso
import services


def ser_complainant(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c.get("phone"),
        "address_line": c["address_line"],
        "zone_code": c["zone_code"],
        "outreach_opt_in": c["outreach_opt_in"],
        "standing": c["standing"],
        "complaints_90d": c["complaints_90d"],
        "filed_total": c["filed_total"],
        "open_count": c["open_count"],
        "closed_count": c["closed_count"],
        "withdrawn_count": c["withdrawn_count"],
        "substantiated_count": c["substantiated_count"],
        "repeat_baseline_at": iso(c.get("repeat_baseline_at")),
        "low_priority_flag": c["low_priority_flag"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_complaint(c):
    return {
        "id": c["id"],
        "complainant_id": c["complainant_id"],
        "occurred_at": iso(c["occurred_at"]),
        "channel": c["channel"],
        "disturbance_type": c["disturbance_type"],
        "narrative": c.get("narrative"),
        "status": c["status"],
        "correlated_flight_id": c.get("correlated_flight_id"),
        "correlated_event_id": c.get("correlated_event_id"),
        "correlation_confidence": c["correlation_confidence"],
        "correlation_variant_used": c["correlation_variant_used"],
        "substantiation_eligible": c["substantiation_eligible"],
        "closure_outcome": c.get("closure_outcome"),
        "closed_at": iso(c.get("closed_at")),
        "reopen_count": c["reopen_count"],
        "info_request_note": c.get("info_request_note"),
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_flight(f):
    return {
        "id": f["id"],
        "flight_number": f["flight_number"],
        "operator_id": f["operator_id"],
        "aircraft_type": f["aircraft_type"],
        "engine_class": f["engine_class"],
        "operation_type": f["operation_type"],
        "runway_code": f["runway_code"],
        "scheduled_at": iso(f["scheduled_at"]),
        "actual_at": iso(f.get("actual_at")),
        "status": f["status"],
        "exemption_code": f["exemption_code"],
        "zone_code": f["zone_code"],
        "linked_complaint_count": f["linked_complaint_count"],
        "linked_event_count": f["linked_event_count"],
        "curfew_movement": f["curfew_movement"],
        "curfew_violation": f["curfew_violation"],
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


def ser_operator(o):
    return {
        "id": o["id"],
        "name": o["name"],
        "iata_code": o["iata_code"],
        "contact_email": o["contact_email"],
        "compliance_standing": o["compliance_standing"],
        "curfew_grace_minutes": o["curfew_grace_minutes"],
        "compliance_score_latest": o.get("compliance_score_latest"),
        "on_time_responses_90d": services.on_time_responses_90d(o["id"]),
        "notifications_sent_total": o["notifications_sent_total"],
        "notifications_open": o["notifications_open"],
        "notifications_closed": o["notifications_closed"],
        "notifications_draft": o["notifications_draft"],
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def ser_monitor(m):
    return {
        "id": m["id"],
        "station_code": m["station_code"],
        "zone_code": m["zone_code"],
        "latitude": m["latitude"],
        "longitude": m["longitude"],
        "commissioned_at": iso(m["commissioned_at"]),
        "status": m["status"],
        "uptime_pct_30d": services.monitor_uptime(m["id"]),
        "events_captured_total": m["events_captured_total"],
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "monitor_id": e["monitor_id"],
        "started_at": iso(e["started_at"]),
        "duration_seconds": e["duration_seconds"],
        "lmax_db": e["lmax_db"],
        "sel_db": e["sel_db"],
        "status": e["status"],
        "flight_id": e.get("flight_id"),
        "classification_basis": e.get("classification_basis"),
        "classification_confidence": e["classification_confidence"],
        "reclassify_count": e["reclassify_count"],
        "exceeds_threshold": e["exceeds_threshold"],
        "quarter_key": e["quarter_key"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_outage(o):
    return {
        "id": o["id"],
        "monitor_id": o["monitor_id"],
        "start_at": iso(o["start_at"]),
        "end_at": iso(o["end_at"]),
        "outage_type": o["outage_type"],
        "reason": o.get("reason"),
        "created_at": iso(o["created_at"]),
    }


def ser_curfew_rule(r):
    return {
        "id": r["id"],
        "runway_code": r["runway_code"],
        "season": r["season"],
        "window_start_minute": r["window_start_minute"],
        "window_end_minute": r["window_end_minute"],
        "applies_to": r["applies_to"],
        "grace_minutes": r["grace_minutes"],
        "effective_from": r["effective_from"].isoformat(),
        "effective_to": r["effective_to"].isoformat(),
        "status": r["status"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "operator_id": n["operator_id"],
        "complaint_id": n.get("complaint_id"),
        "noise_event_id": n.get("noise_event_id"),
        "severity": n["severity"],
        "subject": n["subject"],
        "body": n["body"],
        "status": n["status"],
        "sent_at": iso(n.get("sent_at")),
        "due_at": iso(n.get("due_at")),
        "acknowledged_at": iso(n.get("acknowledged_at")),
        "responded_at": iso(n.get("responded_at")),
        "closed_at": iso(n.get("closed_at")),
        "response_text": n.get("response_text"),
        "escalation_reason": n.get("escalation_reason"),
        "closed_outcome": n.get("closed_outcome"),
        "created_at": iso(n["created_at"]),
        "updated_at": iso(n["updated_at"]),
        "version": n["version"],
    }


def ser_study(s):
    return {
        "id": s["id"],
        "title": s["title"],
        "baseline_year": s["baseline_year"],
        "description": s.get("description"),
        "supersedes_study_id": s.get("supersedes_study_id"),
        "status": s["status"],
        "adopted_at": iso(s.get("adopted_at")),
        "revision_count": s["revision_count"],
        "parcels_assessed_count": s["parcels_assessed_count"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_parcel(p):
    return {
        "id": p["id"],
        "study_id": p["study_id"],
        "parcel_ref": p["parcel_ref"],
        "land_use": p["land_use"],
        "dnl_db_measured": p["dnl_db_measured"],
        "dnl_db_modeled": p["dnl_db_modeled"],
        "zone_code": p["zone_code"],
        "dnl_db_effective": p["dnl_db_effective"],
        "dnl_band": p["dnl_band"],
        "compatibility_status": p["compatibility_status"],
        "insulation_eligible": p["insulation_eligible"],
        "reassessed_at": iso(p.get("reassessed_at")),
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "parcel_id": a["parcel_id"],
        "complainant_id": a.get("complainant_id"),
        "dwelling_type": a["dwelling_type"],
        "rooms_count": a["rooms_count"],
        "est_cost_cents": a["est_cost_cents"],
        "actual_cost_cents": a.get("actual_cost_cents"),
        "eligibility_status": a["eligibility_status"],
        "funding_status": a["funding_status"],
        "fund_id": a.get("fund_id"),
        "priority_score": a["priority_score"],
        "tier_cap_cents": a["tier_cap_cents"],
        "offered_amount_cents": a.get("offered_amount_cents"),
        "offer_issued_at": iso(a.get("offer_issued_at")),
        "offer_expires_at": iso(a.get("offer_expires_at")),
        "last_offer_expired_at": iso(a.get("last_offer_expired_at")),
        "disbursed_cents": a.get("disbursed_cents"),
        "appeal_count": a["appeal_count"],
        "submitted_at": iso(a.get("submitted_at")),
        "decided_at": iso(a.get("decided_at")),
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_fund(f):
    return {
        "id": f["id"],
        "fiscal_year": f["fiscal_year"],
        "total_allocation_cents": f["total_allocation_cents"],
        "intake_opens_at": iso(f["intake_opens_at"]),
        "intake_closes_at": iso(f["intake_closes_at"]),
        "status": f["status"],
        "available_cents": f["total_allocation_cents"] - f["reserved_cents"] - f["disbursed_cents"],
        "reserved_cents": f["reserved_cents"],
        "disbursed_cents": f["disbursed_cents"],
        "projected_pipeline_cents": services.projected_pipeline(),
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


def ser_outreach_case(c):
    return {
        "id": c["id"],
        "complainant_id": c["complainant_id"],
        "trigger_reason": c["trigger_reason"],
        "status": c["status"],
        "contact_attempts": c["contact_attempts"],
        "opened_at": iso(c["opened_at"]),
        "resolved_at": iso(c.get("resolved_at")),
        "resolution_summary": c.get("resolution_summary"),
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "quarter_label": r["quarter_label"],
        "period_start": iso(r["period_start"]),
        "period_end": iso(r["period_end"]),
        "status": r["status"],
        "notes": r.get("notes"),
        "created_by_user_id": r["created_by_user_id"],
        "approved_by_user_id": r.get("approved_by_user_id"),
        "published_at": iso(r.get("published_at")),
        "revision_round_count": r["revision_round_count"],
        "complaints_received_count": r["complaints_received_count"],
        "complaints_substantiated_count": r["complaints_substantiated_count"],
        "distinct_complainants_count": r["distinct_complainants_count"],
        "events_aircraft_count": r["events_aircraft_count"],
        "events_community_count": r["events_community_count"],
        "events_mixed_count": r["events_mixed_count"],
        "curfew_movements_count": r["curfew_movements_count"],
        "curfew_violations_count": r["curfew_violations_count"],
        "avg_operator_compliance_score": r["avg_operator_compliance_score"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }
