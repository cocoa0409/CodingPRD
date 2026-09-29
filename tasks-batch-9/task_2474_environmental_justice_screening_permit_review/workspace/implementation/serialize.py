"""Entity -> JSON projections.

Field sets follow SCAFFOLD Table 1 exactly.  ApplicabilityDetermination and
PublicComment declare common_fields: false, so they expose only id + created_at
(no updated_at, no version).  Decimal values are emitted as JSON numbers.
"""
from decimal import Decimal

_INTERNAL = ("_seq",)


def num(value):
    """Decimal -> JSON number, preserving the stored scale."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _audit(row, full=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if full:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def screening_area(row):
    out = _audit(row)
    out.update(
        {
            "area_code": row["area_code"],
            "county": row["county"],
            "population": row["population"],
            "limited_english_pct": num(row["limited_english_pct"]),
            "required_translation_languages": list(row["required_translation_languages"]),
            "baseline_load_tpy": num(row["baseline_load_tpy"]),
            "demographic_component_statewide": num(row["demographic_component_statewide"]),
            "health_component_statewide": num(row["health_component_statewide"]),
            "pollution_component_statewide": num(row["pollution_component_statewide"]),
            "ej_screen_score_statewide": num(row["ej_screen_score_statewide"]),
            "ej_screen_score_county": num(row["ej_screen_score_county"]),
            "enforcement_burden_points": row["enforcement_burden_points"],
            "designation": row["designation"],
            "data_status": row["data_status"],
            "active_indicator_count": row["active_indicator_count"],
            "permitted_load_tpy": num(row["permitted_load_tpy"]),
            "open_complaint_count": row["open_complaint_count"],
            "open_plan_count": row["open_plan_count"],
            "translation_required": row["translation_required"],
        }
    )
    return out


def burden_indicator(row):
    out = _audit(row)
    out.update(
        {
            "screening_area_id": row["screening_area_id"],
            "indicator_code": row["indicator_code"],
            "category": row["category"],
            "raw_value": num(row["raw_value"]),
            "statewide_percentile": num(row["statewide_percentile"]),
            "county_percentile": num(row["county_percentile"]),
            "vintage_year": row["vintage_year"],
            "status": row["status"],
            "area_version_after": row["area_version_after"],
            "superseded_indicator_id": row["superseded_indicator_id"],
        }
    )
    return out


def facility(row):
    out = _audit(row)
    out.update(
        {
            "screening_area_id": row["screening_area_id"],
            "name": row["name"],
            "facility_type": row["facility_type"],
            "distance_to_area_centroid_m": row["distance_to_area_centroid_m"],
            "existing_load_tpy": num(row["existing_load_tpy"]),
            "compliance_status": row["compliance_status"],
            "confirmed_violation_count": row["confirmed_violation_count"],
        }
    )
    return out


def permit_application(row):
    out = _audit(row)
    out.update(
        {
            "facility_id": row["facility_id"],
            "prior_application_id": row["prior_application_id"],
            "permit_type": row["permit_type"],
            "proposed_emissions_tpy": num(row["proposed_emissions_tpy"]),
            "proposed_operating_hours_per_year": row["proposed_operating_hours_per_year"],
            "status": row["status"],
            "review_track": row["review_track"],
            "revision_round": row["revision_round"],
            "screening_stale_flag": row["screening_stale_flag"],
            "pre_mitigation_index": num(row["pre_mitigation_index"]),
            "total_mitigation_credit_tpy": num(row["total_mitigation_credit_tpy"]),
            "residual_impact_index": num(row["residual_impact_index"]),
            "approved_net_emissions_tpy": num(row["approved_net_emissions_tpy"]),
        }
    )
    return out


def applicability_determination(row):
    out = _audit(row, full=False)
    out.update(
        {
            "permit_application_id": row["permit_application_id"],
            "result": row["result"],
            "trigger_codes": list(row["trigger_codes"]),
            "area_designation_snapshot": row["area_designation_snapshot"],
            "ej_screen_score_snapshot": num(row["ej_screen_score_snapshot"]),
            "revision_round": row["revision_round"],
            "determined_by_user_id": row["determined_by_user_id"],
            "application_version_after": row["application_version_after"],
        }
    )
    return out


def assessment(row):
    out = _audit(row)
    out.update(
        {
            "permit_application_id": row["permit_application_id"],
            "method": row["method"],
            "dispersion_factor": num(row["dispersion_factor"]),
            "receptor_distance_m": row["receptor_distance_m"],
            "author_user_id": row["author_user_id"],
            "qa_user_id": row["qa_user_id"],
            "baseline_burden_score": num(row["baseline_burden_score"]),
            "proposed_increment_pct": num(row["proposed_increment_pct"]),
            "exposure_factor": num(row["exposure_factor"]),
            "cumulative_impact_index": num(row["cumulative_impact_index"]),
            "disproportionate_flag": row["disproportionate_flag"],
            "data_confidence": row["data_confidence"],
            "status": row["status"],
            "application_version_after": row["application_version_after"],
        }
    )
    return out


def participation_plan(row):
    out = _audit(row)
    out.update(
        {
            "permit_application_id": row["permit_application_id"],
            "required_comment_days": row["required_comment_days"],
            "granted_extension_days": row["granted_extension_days"],
            "comment_start_date": row["comment_start_date"].isoformat()
            if row["comment_start_date"] is not None
            else None,
            "comment_end_date": row["comment_end_date"].isoformat()
            if row["comment_end_date"] is not None
            else None,
            "translated_languages": list(row["translated_languages"]),
            "materials_translated": row["materials_translated"],
            "meeting_count": row["meeting_count"],
            "comment_count": row["comment_count"],
            "adequacy_status": row["adequacy_status"],
            "deficiency_codes": list(row["deficiency_codes"]),
            "status": row["status"],
        }
    )
    return out


def venue(row):
    out = _audit(row)
    out.update(
        {
            "name": row["name"],
            "address": row["address"],
            "capacity": row["capacity"],
            "transit_accessible": row["transit_accessible"],
            "ada_accessible": row["ada_accessible"],
            "interpretation_capable": row["interpretation_capable"],
            "status": row["status"],
            "booked_meeting_count": row["booked_meeting_count"],
        }
    )
    return out


def public_meeting(row):
    out = _audit(row)
    out.update(
        {
            "participation_plan_id": row["participation_plan_id"],
            "venue_id": row["venue_id"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "interpretation_languages": list(row["interpretation_languages"]),
            "accessibility_verified": row["accessibility_verified"],
            "status": row["status"],
        }
    )
    return out


def public_comment(row):
    out = _audit(row, full=False)
    out.update(
        {
            "participation_plan_id": row["participation_plan_id"],
            "submitter_name": row["submitter_name"],
            "language": row["language"],
            "body": row["body"],
            "requires_response": row["requires_response"],
            "in_required_language": row["in_required_language"],
        }
    )
    return out


def permit_condition(row):
    out = _audit(row)
    out.update(
        {
            "permit_application_id": row["permit_application_id"],
            "condition_type": row["condition_type"],
            "reduction_tpy": num(row["reduction_tpy"]),
            "enforceable": row["enforceable"],
            "monitoring_frequency": row["monitoring_frequency"],
            "benefit_value_usd": num(row["benefit_value_usd"]),
            "credit_tpy": num(row["credit_tpy"]),
            "status": row["status"],
            "application_version_after": row["application_version_after"],
        }
    )
    return out


def permit_decision(row):
    out = _audit(row)
    out.update(
        {
            "permit_application_id": row["permit_application_id"],
            "disposition": row["disposition"],
            "denial_basis": row["denial_basis"],
            "community_benefit_base_usd": num(row["community_benefit_base_usd"]),
            "community_benefit_surcharge_usd": num(row["community_benefit_surcharge_usd"]),
            "community_benefit_total_usd": num(row["community_benefit_total_usd"]),
            "residual_index_at_decision": num(row["residual_index_at_decision"]),
            "approved_net_emissions_tpy": num(row["approved_net_emissions_tpy"]),
            "decided_by_user_id": row["decided_by_user_id"],
            "status": row["status"],
        }
    )
    return out


def community_complaint(row):
    out = _audit(row)
    out.update(
        {
            "screening_area_id": row["screening_area_id"],
            "facility_id": row["facility_id"],
            "complaint_type": row["complaint_type"],
            "severity": row["severity"],
            "description": row["description"],
            "submitter_language": row["submitter_language"],
            "repeat_count_180d": row["repeat_count_180d"],
            "priority_score": num(row["priority_score"]),
            "priority_tier": row["priority_tier"],
            "reopen_count": row["reopen_count"],
            "status": row["status"],
        }
    )
    return out


def inspection(row):
    out = _audit(row)
    out.update(
        {
            "community_complaint_id": row["community_complaint_id"],
            "facility_id": row["facility_id"],
            "inspector_user_id": row["inspector_user_id"],
            "scheduled_date": row["scheduled_date"].isoformat()
            if row["scheduled_date"] is not None
            else None,
            "priority_score_at_assignment": num(row["priority_score_at_assignment"]),
            "finding": row["finding"],
            "status": row["status"],
        }
    )
    return out


def many(fn, rows):
    return [fn(r) for r in rows]
