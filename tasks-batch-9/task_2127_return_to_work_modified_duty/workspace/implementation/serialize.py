"""Resource serialisation. Every computed field is (re)derived here so that the
response always reflects the post-cascade world."""
from store import db
import calc


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if "version" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def employee(row):
    open_claims = sum(
        1 for c in db.claims.values()
        if c["employee_id"] == row["id"]
        and c["claim_status"] in ("OPEN", "RTW_ELIGIBLE", "SUSPENDED"))
    return _common(row, {
        "full_name": row["full_name"],
        "employee_number": row["employee_number"],
        "department_code": row["department_code"],
        "pre_injury_weekly_wage_cents": row["pre_injury_weekly_wage_cents"],
        "pre_injury_weekly_hours": row["pre_injury_weekly_hours"],
        "benefit_tier": row["benefit_tier"],
        "employment_status": row["employment_status"],
        "open_claim_count": open_claims,
    })


def claim(row):
    active_rs = calc.active_restriction_set(row["id"])
    return _common(row, {
        "employee_id": row["employee_id"],
        "claim_number": row["claim_number"],
        "adjuster_user_id": row["adjuster_user_id"],
        "injury_date": row["injury_date"],
        "claim_status": row["claim_status"],
        "max_authorized_weekly_cost_cents": row["max_authorized_weekly_cost_cents"],
        "rtw_posture": calc.claim_rtw_posture(row),
        "cumulative_transitional_days":
            calc.claim_cumulative_transitional_days(row["id"]),
        "wage_differential_paid_cents":
            calc.claim_wage_differential_paid_cents(row["id"]),
        "active_restriction_set_id": active_rs["id"] if active_rs else None,
    })


def provider(row):
    return _common(row, {
        "full_name": row["full_name"],
        "npi": row["npi"],
        "specialty": row["specialty"],
        "credential_status": row["credential_status"],
    })


def restriction_set(row):
    active_count = sum(
        1 for p in db.placements.values()
        if p["restriction_set_id"] == row["id"]
        and p["placement_status"] in calc.LIVE_PLACEMENT_STATUSES)
    return _common(row, {
        "claim_id": row["claim_id"],
        "treating_provider_id": row["treating_provider_id"],
        "supersedes_restriction_set_id": row["supersedes_restriction_set_id"],
        "status": row["status"],
        "effective_from": row["effective_from"],
        "valid_through": row["valid_through"],
        "max_lift_lbs": row["max_lift_lbs"],
        "max_continuous_standing_minutes": row["max_continuous_standing_minutes"],
        "max_hours_per_day": row["max_hours_per_day"],
        "keyboard_minutes_per_hour": row["keyboard_minutes_per_hour"],
        "overhead_reach_allowed": row["overhead_reach_allowed"],
        "driving_allowed": row["driving_allowed"],
        "clarification_note": row["clarification_note"],
        "clarification_round_count": row["clarification_round_count"],
        "severity_index": calc.restriction_severity_index(row),
        "active_placement_count": active_count,
    })


def supervisor(row):
    strike_points = calc.supervisor_compliance_strike_points(row["id"])
    return _common(row, {
        "full_name": row["full_name"],
        "department_code": row["department_code"],
        "oversight_status": row["oversight_status"],
        "compliance_strike_points": strike_points,
        "strike_forgiveness_points": row["strike_forgiveness_points"],
        "effective_strike_points":
            max(0, strike_points - row["strike_forgiveness_points"]),
        "training_status": calc.supervisor_training_status(row["id"]),
    })


def training_record(row):
    return _common(row, {
        "supervisor_id": row["supervisor_id"],
        "curriculum_code": row["curriculum_code"],
        "completed_on": row["completed_on"],
        "valid_through": row["valid_through"],
        "record_status": row["record_status"],
        "renewal_count": row["renewal_count"],
    })


def transitional_job(row):
    filled = sum(1 for p in db.placements.values()
                 if p["transitional_job_id"] == row["id"]
                 and p["placement_status"] in calc.SEAT_HOLDING_STATUSES)
    return _common(row, {
        "supervisor_id": row["supervisor_id"],
        "title": row["title"],
        "department_code": row["department_code"],
        "seat_capacity": row["seat_capacity"],
        "filled_seats": filled,
        "demand_lift_lbs": row["demand_lift_lbs"],
        "demand_standing_minutes": row["demand_standing_minutes"],
        "demand_hours_per_day": row["demand_hours_per_day"],
        "demand_keyboard_minutes_per_hour": row["demand_keyboard_minutes_per_hour"],
        "requires_overhead_reach": row["requires_overhead_reach"],
        "requires_driving": row["requires_driving"],
        "hourly_rate_cents": row["hourly_rate_cents"],
        "risk_class": row["risk_class"],
        "job_status": row["job_status"],
    })


def _current_directive(placement_id):
    live = [d for d in calc.directives_of_placement(placement_id)
            if d["directive_status"] != "SUPERSEDED"]
    if not live:
        return None
    return live[-1]


def _current_progression_review(placement_id):
    pool = [r for r in calc.reviews_of_placement(placement_id)
            if r["review_status"] in ("SCHEDULED", "IN_REVIEW")]
    if not pool:
        return None
    best = None
    for review in pool:
        if best is None or review["step_index"] > best["step_index"]:
            best = review
    return best


def _open_case_review(placement_id):
    for cr in calc.case_reviews_of_placement(placement_id):
        if cr["review_status"] in ("OPEN", "VOTING"):
            return cr
    return None


def placement(row):
    job = db.jobs[row["transitional_job_id"]]
    claim_row = db.claims[row["claim_id"]]
    employee_row = db.employees[claim_row["employee_id"]]
    employer_share, employee_share = calc.premium_split(employee_row)
    directive = _current_directive(row["id"])
    review = _current_progression_review(row["id"])
    panel = _open_case_review(row["id"])
    return _common(row, {
        "claim_id": row["claim_id"],
        "restriction_set_id": row["restriction_set_id"],
        "transitional_job_id": row["transitional_job_id"],
        "supervisor_id": row["supervisor_id"],
        "created_by_user_id": row["created_by_user_id"],
        "placement_status": row["placement_status"],
        "compliance_status": row["compliance_status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "scheduled_hours_per_day": row["scheduled_hours_per_day"],
        "activated_on": row["activated_on"],
        "ended_on": row["ended_on"],
        "suspension_reason": row["suspension_reason"],
        "decline_reason": row["decline_reason"],
        "logged_hours": [dict(e) for e in row["logged_hours"]],
        "progression_step": row["progression_step"],
        "match_score": row["match_score"],
        "reinjury_risk_score": row["reinjury_risk_score"],
        "reinjury_risk_variant": row["reinjury_risk_variant"],
        "cumulative_days": calc.cumulative_days(row),
        "employer_premium_share_cents": employer_share,
        "employee_premium_share_cents": employee_share,
        "benefit_continuation_status":
            calc.benefit_continuation_status(row, employee_row),
        "projected_weekly_cost_cents":
            calc.projected_weekly_cost_cents(row, job, employee_row),
        "current_adjuster_directive_id": directive["id"] if directive else None,
        "current_progression_review_id": review["id"] if review else None,
        "open_case_review_id": panel["id"] if panel else None,
    })


def directive(row):
    return _common(row, {
        "placement_id": row["placement_id"],
        "directive_status": row["directive_status"],
        "requested_weekly_cost_cents": row["requested_weekly_cost_cents"],
        "authorized_weekly_cost_cents": row["authorized_weekly_cost_cents"],
        "condition_note": row["condition_note"],
        "denial_reason": row["denial_reason"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": row["decided_at"],
    })


def progression_review(row):
    return _common(row, {
        "placement_id": row["placement_id"],
        "step_index": row["step_index"],
        "due_date": row["due_date"],
        "review_status": row["review_status"],
        "deferral_count": row["deferral_count"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "target_hours_per_day": row["target_hours_per_day"],
        "target_lift_lbs": row["target_lift_lbs"],
        "outcome_note": row["outcome_note"],
    })


def compliance_audit(row):
    return _common(row, {
        "placement_id": row["placement_id"],
        "auditor_user_id": row["auditor_user_id"],
        "observed_on": row["observed_on"],
        "finding_severity": row["finding_severity"],
        "finding_code": row["finding_code"],
        "restriction_deviation_detected": row["restriction_deviation_detected"],
        "corrective_action_note": row["corrective_action_note"],
    })


def wage_entry(row):
    return _common(row, {
        "placement_id": row["placement_id"],
        "claim_id": row["claim_id"],
        "reverses_entry_id": row["reverses_entry_id"],
        "variant": row["variant"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "counted_day_count": row["counted_day_count"],
        "tier_multiplier": row["tier_multiplier"],
        "gross_differential_cents": row["gross_differential_cents"],
        "offset_cents": row["offset_cents"],
        "net_amount_cents": row["net_amount_cents"],
        "entry_status": row["entry_status"],
    })


def reinjury_report(row):
    return _common(row, {
        "placement_id": row["placement_id"],
        "reported_by_user_id": row["reported_by_user_id"],
        "occurred_on": row["occurred_on"],
        "severity": row["severity"],
        "body_part_code": row["body_part_code"],
        "mechanism_code": row["mechanism_code"],
        "report_status": row["report_status"],
        "triage_note": row["triage_note"],
        "risk_points_applied": row["risk_points_applied"],
    })


def case_review(row):
    tally = calc.case_review_tally(row)
    out = _common(row, {
        "placement_id": row["placement_id"],
        "trigger_reason": row["trigger_reason"],
        "review_status": row["review_status"],
        "quorum_required": row["quorum_required"],
        "opened_by_user_id": row["opened_by_user_id"],
        "closed_by_user_id": row["closed_by_user_id"],
    })
    out.update(tally)
    return out


def case_review_vote(row):
    return _common(row, {
        "case_review_id": row["case_review_id"],
        "voter_user_id": row["voter_user_id"],
        "voter_role": row["voter_role"],
        "ballot": row["ballot"],
        "rationale": row["rationale"],
        "vote_status": row["vote_status"],
    })
