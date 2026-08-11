"""Entity serializers. Field sets and names follow §1.1 / §2.4 exactly.

Common-fields entities carry id/created_at/updated_at/version. The three
light types (MemberEnrollmentSegment, OverReadReview, SupplementalRecord)
carry only id and created_at.
"""
from db import format_ts


def season_view(s):
    return {
        "id": s["id"],
        "measurement_year": s["measurement_year"],
        "submission_deadline": format_ts(s["submission_deadline"]),
        "admin_data_cutoff": format_ts(s["admin_data_cutoff"]),
        "approved_supplemental_sources": list(s["approved_supplemental_sources"]),
        "status": s["status"],
        "certified_run_count": s["certified_run_count"],
        "created_at": format_ts(s["created_at"]),
        "updated_at": format_ts(s["updated_at"]),
        "version": s["version"],
    }


def spec_view(sp):
    return {
        "id": sp["id"],
        "season_id": sp["season_id"],
        "hedis_measure_code": sp["hedis_measure_code"],
        "version_label": sp["version_label"],
        "collection_method": sp["collection_method"],
        "hybrid_policy": sp["hybrid_policy"],
        "matching_policy": sp["matching_policy"],
        "sample_size_floor": sp["sample_size_floor"],
        "age_min": sp["age_min"],
        "age_max": sp["age_max"],
        "gender_requirement": sp["gender_requirement"],
        "continuous_enrollment_months": sp["continuous_enrollment_months"],
        "allowable_gap_days": sp["allowable_gap_days"],
        "anchor_date": format_ts(sp["anchor_date"]),
        "reporting_weight": sp["reporting_weight"],
        "status": sp["status"],
        "created_at": format_ts(sp["created_at"]),
        "updated_at": format_ts(sp["updated_at"]),
        "version": sp["version"],
    }


def member_view(m):
    return {
        "id": m["id"],
        "member_ref": m["member_ref"],
        "birth_date": format_ts(m["birth_date"]),
        "gender": m["gender"],
        "attributed_provider_ref": m["attributed_provider_ref"],
        "created_at": format_ts(m["created_at"]),
        "updated_at": format_ts(m["updated_at"]),
        "version": m["version"],
    }


def segment_view(seg):
    return {
        "id": seg["id"],
        "member_id": seg["member_id"],
        "span_start": format_ts(seg["span_start"]),
        "span_end": format_ts(seg["span_end"]),
        "created_at": format_ts(seg["created_at"]),
    }


def provider_view(p):
    return {
        "id": p["id"],
        "provider_ref": p["provider_ref"],
        "name": p["name"],
        "specialty": p["specialty"],
        "open_gap_count": p["open_gap_count"],
        "created_at": format_ts(p["created_at"]),
        "updated_at": format_ts(p["updated_at"]),
        "version": p["version"],
    }


def run_view(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "spec_id": r["spec_id"],
        "spec_version_label": r["spec_version_label"],
        "collection_method": r["collection_method"],
        "reporting_status": r["reporting_status"],
        "audit_status": r["audit_status"],
        "denominator_count": r["denominator_count"],
        "exclusion_count": r["exclusion_count"],
        "admin_numerator_count": r["admin_numerator_count"],
        "sample_exclusion_count": r["sample_exclusion_count"],
        "sample_numerator_count": r["sample_numerator_count"],
        "admin_rate": r["admin_rate"],
        "hybrid_rate": r["hybrid_rate"],
        "final_rate": r["final_rate"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "certified_by_user_id": r["certified_by_user_id"],
        "created_at": format_ts(r["created_at"]),
        "updated_at": format_ts(r["updated_at"]),
        "version": r["version"],
    }


def entry_view(e):
    return {
        "id": e["id"],
        "run_id": e["run_id"],
        "member_ref": e["member_ref"],
        "is_excluded": e["is_excluded"],
        "exclusion_reason": e["exclusion_reason"],
        "is_sampled": e["is_sampled"],
        "admin_compliant": e["admin_compliant"],
        "sample_compliant": e["sample_compliant"],
        "created_at": format_ts(e["created_at"]),
        "updated_at": format_ts(e["updated_at"]),
        "version": e["version"],
    }


def sample_view(s):
    return {
        "id": s["id"],
        "run_id": s["run_id"],
        "drawn_size": s["drawn_size"],
        "draw_step": s["draw_step"],
        "status": s["status"],
        "irr_state": s["irr_state"],
        "irr_ratio": s["irr_ratio"],
        "remediation_count": s["remediation_count"],
        "required_overread_fraction": s["required_overread_fraction"],
        "created_at": format_ts(s["created_at"]),
        "updated_at": format_ts(s["updated_at"]),
        "version": s["version"],
    }


def chase_view(c):
    return {
        "id": c["id"],
        "sample_id": c["sample_id"],
        "member_ref": c["member_ref"],
        "provider_ref": c["provider_ref"],
        "status": c["status"],
        "chase_round": c["chase_round"],
        "created_at": format_ts(c["created_at"]),
        "updated_at": format_ts(c["updated_at"]),
        "version": c["version"],
    }


def abstraction_view(a):
    return {
        "id": a["id"],
        "chase_id": a["chase_id"],
        "result": a["result"],
        "abstractor_user_id": a["abstractor_user_id"],
        "requires_overread": a["requires_overread"],
        "status": a["status"],
        "resubmission_count": a["resubmission_count"],
        "submitted_at": format_ts(a["submitted_at"]) if a["submitted_at"] else None,
        "created_at": format_ts(a["created_at"]),
        "updated_at": format_ts(a["updated_at"]),
        "version": a["version"],
    }


def overread_view(o):
    return {
        "id": o["id"],
        "abstraction_id": o["abstraction_id"],
        "reviewer_user_id": o["reviewer_user_id"],
        "outcome": o["outcome"],
        "final_result": o["final_result"],
        "created_at": format_ts(o["created_at"]),
    }


def batch_view(b):
    return {
        "id": b["id"],
        "run_id": b["run_id"],
        "source_type": b["source_type"],
        "status": b["status"],
        "record_count": b["record_count"],
        "accepted_record_count": b["accepted_record_count"],
        "matching_policy_used": b["matching_policy_used"],
        "created_at": format_ts(b["created_at"]),
        "updated_at": format_ts(b["updated_at"]),
        "version": b["version"],
    }


def record_view(rec):
    return {
        "id": rec["id"],
        "batch_id": rec["batch_id"],
        "member_ref": rec["member_ref"],
        "service_date": format_ts(rec["service_date"]),
        "evidence_code": rec["evidence_code"],
        "disposition": rec["disposition"],
        "created_at": format_ts(rec["created_at"]),
    }


def gap_view(g):
    return {
        "id": g["id"],
        "run_id": g["run_id"],
        "member_ref": g["member_ref"],
        "provider_ref": g["provider_ref"],
        "gap_reason": g["gap_reason"],
        "status": g["status"],
        "closure_source": g["closure_source"],
        "created_at": format_ts(g["created_at"]),
        "updated_at": format_ts(g["updated_at"]),
        "version": g["version"],
    }


def engagement_view(e):
    return {
        "id": e["id"],
        "season_id": e["season_id"],
        "measure_run_id": e["measure_run_id"],
        "auditor_user_id": e["auditor_user_id"],
        "window_start": format_ts(e["window_start"]),
        "window_end": format_ts(e["window_end"]),
        "status": e["status"],
        "outcome": e["outcome"],
        "created_at": format_ts(e["created_at"]),
        "updated_at": format_ts(e["updated_at"]),
        "version": e["version"],
    }


def finding_view(f):
    return {
        "id": f["id"],
        "engagement_id": f["engagement_id"],
        "severity": f["severity"],
        "summary": f["summary"],
        "status": f["status"],
        "created_at": format_ts(f["created_at"]),
        "updated_at": format_ts(f["updated_at"]),
        "version": f["version"],
    }
