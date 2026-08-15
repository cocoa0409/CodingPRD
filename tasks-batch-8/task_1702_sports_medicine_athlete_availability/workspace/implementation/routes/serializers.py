"""Entity serializers — explicit field lists; strips internal '_' fields."""
from services.reports import compute_report_rows, materialize_lazy_expiry

COACHING_ATHLETE_FIELDS = [
    "id", "team_id", "full_name", "position", "roster_status",
    "availability_tier", "created_at", "updated_at", "version",
]


def team_json(t):
    return {
        "id": t["id"], "name": t["name"], "sport": t["sport"],
        "season_start_date": t["season_start_date"],
        "season_end_date": t["season_end_date"],
        "hipaa_mode": t["hipaa_mode"], "acwr_variant": t["acwr_variant"],
        "current_utc": t["current_utc"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def athlete_json(a, role=None):
    if role == "CoachingStaff":
        return {k: a[k] for k in COACHING_ATHLETE_FIELDS}
    return {
        "id": a["id"], "team_id": a["team_id"], "full_name": a["full_name"],
        "position": a["position"], "enrollment_date": a["enrollment_date"],
        "roster_status": a["roster_status"],
        "availability_tier": a["availability_tier"],
        "acute_chronic_workload_ratio": a["acute_chronic_workload_ratio"],
        "load_flag": a["load_flag"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def diagnosis_code_json(d):
    return {
        "id": d["id"], "code": d["code"], "body_region": d["body_region"],
        "severity_class": d["severity_class"], "is_concussion": d["is_concussion"],
        "created_at": d["created_at"],
    }


def injury_case_json(c):
    return {
        "id": c["id"], "athlete_id": c["athlete_id"], "team_id": c["team_id"],
        "diagnosis_code_id": c["diagnosis_code_id"],
        "occurred_on": c["occurred_on"], "surface": c["surface"],
        "mechanism": c["mechanism"], "status": c["status"],
        "reported_by_user_id": c["reported_by_user_id"],
        "severity_class_snapshot": c["severity_class_snapshot"],
        "is_concussion_snapshot": c["is_concussion_snapshot"],
        "cleared_on": c["cleared_on"], "closed_on": c["closed_on"],
        "days_lost": c["days_lost"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def treatment_plan_json(p):
    return {
        "id": p["id"], "injury_case_id": p["injury_case_id"],
        "athlete_id": p["athlete_id"], "title": p["title"],
        "planned_sessions_per_week": p["planned_sessions_per_week"],
        "estimated_duration_weeks": p["estimated_duration_weeks"],
        "status": p["status"], "suspension_reason": p["suspension_reason"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def daily_status_entry_json(e):
    return {
        "id": e["id"], "injury_case_id": e["injury_case_id"],
        "athlete_id": e["athlete_id"], "entry_date": e["entry_date"],
        "designation": e["designation"], "symptom_free": e["symptom_free"],
        "functional_test_score": e["functional_test_score"],
        "notes": e["notes"], "recorded_by_user_id": e["recorded_by_user_id"],
        "supersedes_entry_id": e["supersedes_entry_id"],
        "is_current": e["is_current"], "created_at": e["created_at"],
    }


def rtp_protocol_json(p):
    return {
        "id": p["id"], "injury_case_id": p["injury_case_id"],
        "athlete_id": p["athlete_id"], "total_stages": p["total_stages"],
        "current_stage_index": p["current_stage_index"],
        "current_stage_entered_on": p["current_stage_entered_on"],
        "regression_count": p["regression_count"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def rtp_stage_advance_json(a):
    return {
        "id": a["id"], "rtp_protocol_id": a["rtp_protocol_id"],
        "from_stage_index": a["from_stage_index"],
        "to_stage_index": a["to_stage_index"], "kind": a["kind"],
        "advanced_by_user_id": a["advanced_by_user_id"],
        "readiness_snapshot": a["readiness_snapshot"],
        "created_at": a["created_at"],
    }


def clearance_json(c):
    return {
        "id": c["id"], "rtp_protocol_id": c["rtp_protocol_id"],
        "injury_case_id": c["injury_case_id"], "athlete_id": c["athlete_id"],
        "requested_by_user_id": c["requested_by_user_id"],
        "decided_by_user_id": c["decided_by_user_id"],
        "decision": c["decision"], "status": c["status"],
        "requested_at": c["requested_at"], "decided_at": c["decided_at"],
        "expires_at": c["expires_at"], "request_notes": c["request_notes"],
        "decision_notes": c["decision_notes"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def workload_session_json(s):
    return {
        "id": s["id"], "athlete_id": s["athlete_id"], "team_id": s["team_id"],
        "session_date": s["session_date"], "session_type": s["session_type"],
        "surface": s["surface"], "duration_minutes": s["duration_minutes"],
        "rpe": s["rpe"], "session_load": s["session_load"],
        "counts_as_exposure": s["counts_as_exposure"],
        "ingested_by_user_id": s["ingested_by_user_id"],
        "created_at": s["created_at"],
    }


def insurance_policy_json(p):
    return {
        "id": p["id"], "athlete_id": p["athlete_id"],
        "payer_name": p["payer_name"], "policy_number": p["policy_number"],
        "deductible_cents": p["deductible_cents"],
        "deductible_met_cents": p["deductible_met_cents"],
        "coinsurance_pct": p["coinsurance_pct"],
        "oop_max_cents": p["oop_max_cents"],
        "oop_accrued_cents": p["oop_accrued_cents"],
        "policy_year_start": p["policy_year_start"],
        "policy_year_end": p["policy_year_end"], "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def claim_json(c):
    return {
        "id": c["id"], "injury_case_id": c["injury_case_id"],
        "athlete_id": c["athlete_id"],
        "insurance_policy_id": c["insurance_policy_id"],
        "billed_amount_cents": c["billed_amount_cents"],
        "line_items": c["line_items"], "status": c["status"],
        "submitted_at": c["submitted_at"],
        "adjudicated_at": c["adjudicated_at"],
        "payer_paid_cents": c["payer_paid_cents"],
        "patient_resp_cents": c["patient_resp_cents"],
        "deductible_applied_cents": c["deductible_applied_cents"],
        "appeals_count": c["appeals_count"],
        "supersedes_claim_id": c["supersedes_claim_id"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def disclosure_grant_json(g):
    materialize_lazy_expiry(g)
    return {
        "id": g["id"], "athlete_id": g["athlete_id"],
        "grantee_role": g["grantee_role"], "scope": g["scope"],
        "effective_from": g["effective_from"], "effective_to": g["effective_to"],
        "status": g["status"],
        "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"],
    }


def availability_report_json(r):
    return {
        "id": r["id"], "team_id": r["team_id"], "report_date": r["report_date"],
        "generated_by_user_id": r["generated_by_user_id"],
        "generated_for_role": r["generated_for_role"],
        "rows": compute_report_rows(r["team_id"], r["generated_for_role"]),
        "created_at": r["created_at"],
    }


def sorted_items(coll):
    return sorted(coll.values(), key=lambda e: e["created_at"])
