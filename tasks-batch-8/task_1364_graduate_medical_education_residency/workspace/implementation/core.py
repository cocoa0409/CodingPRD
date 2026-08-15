"""Entity lookups (existence, left-to-right), common-field stamping, serializers."""
from db import DB, new_id, next_seq, now_iso
from errors import ApiError


def not_found(label):
    return ApiError("ERR_NOT_FOUND", 404, f"{label} not found")


def _lookup(store, rid, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise not_found(label)
    return rec


def get_program(rid):
    return _lookup("programs", rid, "ResidencyProgram")


def get_year(rid):
    return _lookup("academic_years", rid, "AcademicYear")


def get_block(rid):
    return _lookup("schedule_blocks", rid, "ScheduleBlock")


def get_complement(rid):
    return _lookup("complement_approvals", rid, "ComplementApproval")


def get_resident(rid):
    return _lookup("residents", rid, "Resident")


def get_rotation(rid):
    return _lookup("rotations", rid, "Rotation")


def get_assignment(rid):
    return _lookup("rotation_assignments", rid, "RotationAssignment")


def get_duty_log(rid):
    return _lookup("duty_hour_logs", rid, "DutyHourLog")


def get_violation(rid):
    return _lookup("duty_hour_violations", rid, "DutyHourViolation")


def get_moonlighting(rid):
    return _lookup("moonlighting_requests", rid, "MoonlightingRequest")


def get_evaluation(rid):
    return _lookup("milestone_evaluations", rid, "MilestoneEvaluation")


def get_ccc_review(rid):
    return _lookup("ccc_reviews", rid, "CCCReview")


def get_case_log(rid):
    return _lookup("procedure_case_logs", rid, "ProcedureCaseLog")


def get_requirement(rid):
    return _lookup("case_requirements", rid, "CaseRequirement")


def get_plan(rid):
    return _lookup("remediation_plans", rid, "RemediationPlan")


def get_probation(rid):
    return _lookup("probation_cases", rid, "ProbationCase")


def get_citation(rid):
    return _lookup("accreditation_citations", rid, "AccreditationCitation")


def get_survey(rid):
    return _lookup("annual_surveys", rid, "AnnualSurvey")


# ---------------------------------------------------------------------------
# Common fields (PRD section 2.5): version starts at 1 and increments by 1 on
# every mutation, including cascaded side effects.
# ---------------------------------------------------------------------------

def stamp(rec):
    t = now_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next_seq()


def stamp_immutable(rec):
    """common_fields: false entities carry only id + created_at."""
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Serializers (public API views). Internal keys are prefixed with "_" and
# never emitted. Input datetime fields echo the raw submitted string.
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def pub_program(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "specialty": p["specialty"],
        "acgme_program_code": p["acgme_program_code"],
        "accreditation_status": p["accreditation_status"],
    }
    out.update(_common(p))
    return out


def pub_year(y):
    out = {
        "id": y["id"],
        "program_id": y["program_id"],
        "year_label": y["year_label"],
        "start_date": y["start_date"],
        "end_date": y["end_date"],
        "status": y["status"],
    }
    out.update(_common(y))
    return out


def pub_block(b):
    out = {
        "id": b["id"],
        "academic_year_id": b["academic_year_id"],
        "block_index": b["block_index"],
        "start_date": b["start_date"],
        "end_date": b["end_date"],
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def pub_complement(c, fill=None):
    """fill = (filled_headcount, filled_funded_census Decimal) computed live."""
    if fill is None:
        from calc import complement_fill
        fill = complement_fill(c)
    headcount, census = fill
    out = {
        "id": c["id"],
        "program_id": c["program_id"],
        "academic_year_id": c["academic_year_id"],
        "pgy_level": c["pgy_level"],
        "approved_positions": c["approved_positions"],
        "annual_funding_budget_cents": c["annual_funding_budget_cents"],
        "blended_stipend_cents": c["blended_stipend_cents"],
        "resident_year_stipend_cents": c["resident_year_stipend_cents"],
        "effective_funded_positions": c["effective_funded_positions"],
        "filled_headcount": headcount,
        "filled_funded_census": float(census),
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def pub_resident(r):
    out = {
        "id": r["id"],
        "program_id": r["program_id"],
        "entry_academic_year_id": r["entry_academic_year_id"],
        "pgy_level": r["pgy_level"],
        "full_name": r["full_name"],
        "email": r["email"],
        "hire_date": r["hire_date"],
        "expected_graduation_date": r["expected_graduation_date"],
        "lifecycle_status": r["lifecycle_status"],
        "standing_status": r["standing_status"],
    }
    out.update(_common(r))
    return out


def pub_rotation(rot):
    out = {
        "id": rot["id"],
        "program_id": rot["program_id"],
        "name": rot["name"],
        "min_pgy_level": rot["min_pgy_level"],
        "max_residents_per_block": rot["max_residents_per_block"],
        "is_night_float": rot["is_night_float"],
        "status": rot["status"],
    }
    out.update(_common(rot))
    return out


def pub_assignment(a):
    out = {
        "id": a["id"],
        "resident_id": a["resident_id"],
        "schedule_block_id": a["schedule_block_id"],
        "rotation_id": a["rotation_id"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def pub_duty_log(log):
    out = {
        "id": log["id"],
        "resident_id": log["resident_id"],
        "started_at": log["started_at"],
        "ended_at": log["ended_at"],
        "duration_hours": float(log["_duration"]),
        "status": log["status"],
        "void_reason": log.get("void_reason"),
    }
    out.update(_common(log))
    return out


def pub_violation(v):
    out = {
        "id": v["id"],
        "resident_id": v["resident_id"],
        "duty_hour_log_id": v["duty_hour_log_id"],
        "rule_code": v["rule_code"],
        "window_start": v["window_start"],
        "window_end": v["window_end"],
        "measured_value": float(v["_measured"]),
        "threshold_value": float(v["_threshold"]),
        "status": v["status"],
        "resolution_note": v.get("resolution_note"),
    }
    out.update(_common(v))
    return out


def pub_moonlighting(m):
    out = {
        "id": m["id"],
        "resident_id": m["resident_id"],
        "type": m["type"],
        "site_name": m["site_name"],
        "start_date": m["start_date"],
        "end_date": m["end_date"],
        "hours_per_week": float(m["_hpw"]),
        "status": m["status"],
        "decision_reason": m.get("decision_reason"),
    }
    out.update(_common(m))
    return out


def pub_evaluation(e):
    """MilestoneEvaluation: common_fields false — id + created_at only."""
    return {
        "id": e["id"],
        "resident_id": e["resident_id"],
        "academic_year_id": e["academic_year_id"],
        "reporting_period": e["reporting_period"],
        "evaluator_id": e["evaluator_id"],
        "evaluator_role": e["evaluator_role"],
        "competency_ratings": e["competency_ratings"],
        "created_at": e["created_at"],
    }


def pub_ccc_review(c):
    out = {
        "id": c["id"],
        "resident_id": c["resident_id"],
        "academic_year_id": c["academic_year_id"],
        "reporting_period": c["reporting_period"],
        "status": c["status"],
        "outcome": c.get("outcome"),
        "milestone_levels": c.get("milestone_levels"),
        "composite_snapshot": c.get("composite_snapshot"),
    }
    out.update(_common(c))
    return out


def pub_case_log(log):
    out = {
        "id": log["id"],
        "resident_id": log["resident_id"],
        "rotation_id": log["rotation_id"],
        "procedure_category": log["procedure_category"],
        "performed_date": log["performed_date"],
        "role": log["role"],
        "status": log["status"],
        "decision_reason": log.get("decision_reason"),
    }
    out.update(_common(log))
    return out


def pub_requirement(q):
    out = {
        "id": q["id"],
        "program_id": q["program_id"],
        "procedure_category": q["procedure_category"],
        "required_count": q["required_count"],
        "required_primary_count": q["required_primary_count"],
    }
    out.update(_common(q))
    return out


def pub_plan(p):
    out = {
        "id": p["id"],
        "resident_id": p["resident_id"],
        "ccc_review_id": p.get("ccc_review_id"),
        "trigger_source": p["trigger_source"],
        "goals": p["goals"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "outcome": p.get("outcome"),
        "status": p["status"],
        "cancel_reason": p.get("cancel_reason"),
    }
    out.update(_common(p))
    return out


def pub_probation(c):
    out = {
        "id": c["id"],
        "resident_id": c["resident_id"],
        "remediation_plan_id": c.get("remediation_plan_id"),
        "reason": c["reason"],
        "status": c["status"],
        "recommended_by": c.get("recommended_by"),
    }
    out.update(_common(c))
    return out


def pub_citation(c):
    out = {
        "id": c["id"],
        "program_id": c["program_id"],
        "annual_survey_id": c.get("annual_survey_id"),
        "citation_code": c["citation_code"],
        "area_code": c["area_code"],
        "severity": c["severity"],
        "received_date": c["received_date"],
        "due_date": c["due_date"],
        "status": c["status"],
        "response_text": c.get("response_text"),
        "resolution_note": c.get("resolution_note"),
        "escalation_reason": c.get("escalation_reason"),
    }
    out.update(_common(c))
    return out


def pub_survey(s):
    out = {
        "id": s["id"],
        "program_id": s["program_id"],
        "academic_year_id": s["academic_year_id"],
        "status": s["status"],
        "resident_response_rate": (
            None if s.get("_rrate") is None else float(s["_rrate"])
        ),
        "faculty_response_rate": (
            None if s.get("_frate") is None else float(s["_frate"])
        ),
        "area_results": s.get("area_results"),
        "flagged_area_count": s.get("flagged_area_count"),
    }
    out.update(_common(s))
    return out
