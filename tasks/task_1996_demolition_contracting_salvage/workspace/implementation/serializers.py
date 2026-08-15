"""Entity serializers: convert internal records (datetimes, Decimals) into
JSON-safe dicts. DustNoiseLog is append-only: id + created_at only, no
updated_at, no version."""

from util import fmt_ts, num


def ser_project(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "address": p["address"],
        "lot_area_sqft": p["lot_area_sqft"],
        "required_diversion_rate": num(p["required_diversion_rate"]),
        "blackout_dates": list(p["blackout_dates"]),
        "status": p["status"],
        "work_posture": p["work_posture"],
        "pinned_engineering_survey_id": p["pinned_engineering_survey_id"],
        "pinned_engineering_revision": p["pinned_engineering_revision"],
        "cumulative_exposure_score": num(p["cumulative_exposure_score"]),
        "in_transit_tons": num(p["in_transit_tons"]),
        "landfill_tons": num(p["landfill_tons"]),
        "diverted_tons": num(p["diverted_tons"]),
        "removed_tons": num(p["removed_tons"]),
        "diversion_rate": num(p["diversion_rate"]),
        "diversion_tier": p["diversion_tier"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_structure_survey(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "structure_label": s["structure_label"],
        "survey_type": s["survey_type"],
        "status": s["status"],
        "hazmat_found": s["hazmat_found"],
        "findings_summary": s["findings_summary"],
        "completed_at": fmt_ts(s["completed_at"]),
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_abatement(a):
    return {
        "id": a["id"],
        "structure_survey_id": a["structure_survey_id"],
        "material_type": a["material_type"],
        "description": a["description"],
        "containment_method": a["containment_method"],
        "status": a["status"],
        "started_by_user_id": a["started_by_user_id"],
        "certified_by_user_id": a["certified_by_user_id"],
        "certified_at": fmt_ts(a["certified_at"]),
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_utility_disconnect(u):
    return {
        "id": u["id"],
        "project_id": u["project_id"],
        "utility_type": u["utility_type"],
        "provider_name": u["provider_name"],
        "disconnect_window_start": fmt_ts(u["disconnect_window_start"]),
        "disconnect_window_end": fmt_ts(u["disconnect_window_end"]),
        "disconnect_status": u["disconnect_status"],
        "verification_status": u["verification_status"],
        "reported_by_user_id": u["reported_by_user_id"],
        "verified_by_user_id": u["verified_by_user_id"],
        "confirmed_by_user_id": u["confirmed_by_user_id"],
        "created_at": fmt_ts(u["created_at"]),
        "updated_at": fmt_ts(u["updated_at"]),
        "version": u["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "permit_number": p["permit_number"],
        "gross_floor_area_sqft": p["gross_floor_area_sqft"],
        "fee_cents": p["fee_cents"],
        "status": p["status"],
        "revision_count": p["revision_count"],
        "renewal_count": p["renewal_count"],
        "activated_at": fmt_ts(p["activated_at"]),
        "expires_at": fmt_ts(p["expires_at"]),
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_engineering_survey(e):
    return {
        "id": e["id"],
        "project_id": e["project_id"],
        "revision_number": e["revision_number"],
        "demolition_method": e["demolition_method"],
        "structural_stability_rating": e["structural_stability_rating"],
        "max_structure_height_ft": e["max_structure_height_ft"],
        "adjacent_structure_distance_ft": e["adjacent_structure_distance_ft"],
        "author_user_id": e["author_user_id"],
        "certified_by_user_id": e["certified_by_user_id"],
        "status": e["status"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_salvage_manifest(m):
    return {
        "id": m["id"],
        "project_id": m["project_id"],
        "valuation_policy": m["valuation_policy"],
        "processing_fee_cents": m["processing_fee_cents"],
        "status": m["status"],
        "optimistic_total_cents": m["optimistic_total_cents"],
        "conservative_total_cents": m["conservative_total_cents"],
        "net_credit_cents": m["net_credit_cents"],
        "amendment_count": m["amendment_count"],
        "finalized_at": fmt_ts(m["finalized_at"]),
        "created_at": fmt_ts(m["created_at"]),
        "updated_at": fmt_ts(m["updated_at"]),
        "version": m["version"],
    }


def ser_salvage_item(i):
    return {
        "id": i["id"],
        "salvage_manifest_id": i["salvage_manifest_id"],
        "material": i["material"],
        "description": i["description"],
        "quantity": i["quantity"],
        "unit": i["unit"],
        "low_unit_value_cents": i["low_unit_value_cents"],
        "high_unit_value_cents": i["high_unit_value_cents"],
        "is_amendment_line": i["is_amendment_line"],
        "extended_value_cents": i["extended_value_cents"],
        "created_at": fmt_ts(i["created_at"]),
        "updated_at": fmt_ts(i["updated_at"]),
        "version": i["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "project_id": n["project_id"],
        "address": n["address"],
        "notice_method": n["notice_method"],
        "scheduled_delivery_date": n["scheduled_delivery_date"],
        "status": n["status"],
        "delivered_at": fmt_ts(n["delivered_at"]),
        "created_at": fmt_ts(n["created_at"]),
        "updated_at": fmt_ts(n["updated_at"]),
        "version": n["version"],
    }


def ser_dust_log(d):
    return {
        "id": d["id"],
        "project_id": d["project_id"],
        "reading_type": d["reading_type"],
        "measured_value": num(d["measured_value"]),
        "wind_speed_mph": num(d["wind_speed_mph"]),
        "duration_hours": num(d["duration_hours"]),
        "exposure_score": num(d["exposure_score"]),
        "is_exceedance": d["is_exceedance"],
        "recorded_at": fmt_ts(d["recorded_at"]),
        "created_at": fmt_ts(d["created_at"]),
    }


def ser_debris_ticket(t):
    return {
        "id": t["id"],
        "project_id": t["project_id"],
        "ticket_number": t["ticket_number"],
        "facility_type": t["facility_type"],
        "material_class": t["material_class"],
        "gross_tons": num(t["gross_tons"]),
        "diverted_tons": num(t["diverted_tons"]),
        "disposed_tons": num(t["disposed_tons"]),
        "status": t["status"],
        "received_at": fmt_ts(t["received_at"]),
        "created_at": fmt_ts(t["created_at"]),
        "updated_at": fmt_ts(t["updated_at"]),
        "version": t["version"],
    }


def ser_backfill_plan(b):
    return {
        "id": b["id"],
        "project_id": b["project_id"],
        "design_disturbed_area_sqft": b["design_disturbed_area_sqft"],
        "planned_protected_area_sqft": b["planned_protected_area_sqft"],
        "fill_volume_cu_yd": b["fill_volume_cu_yd"],
        "required_compaction_pct": num(b["required_compaction_pct"]),
        "status": b["status"],
        "provisional_coverage_ratio": num(b["provisional_coverage_ratio"]),
        "compaction_pct_achieved": num(b["compaction_pct_achieved"]) if b["compaction_pct_achieved"] is not None else None,
        "measured_disturbed_area_sqft": b["measured_disturbed_area_sqft"],
        "measured_protected_area_sqft": b["measured_protected_area_sqft"],
        "final_coverage_ratio": num(b["final_coverage_ratio"]),
        "created_at": fmt_ts(b["created_at"]),
        "updated_at": fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def ser_final_inspection(i):
    return {
        "id": i["id"],
        "project_id": i["project_id"],
        "inspection_type": i["inspection_type"],
        "scheduled_date": i["scheduled_date"],
        "status": i["status"],
        "attempt_count": i["attempt_count"],
        "inspector_note": i["inspector_note"],
        "passed_at": fmt_ts(i["passed_at"]),
        "created_at": fmt_ts(i["created_at"]),
        "updated_at": fmt_ts(i["updated_at"]),
        "version": i["version"],
    }
