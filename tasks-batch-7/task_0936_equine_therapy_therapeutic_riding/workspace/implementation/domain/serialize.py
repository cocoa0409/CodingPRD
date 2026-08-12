"""Response projections.  Every derived field is recomputed at read time (§2.10)."""

from core import timeutil as T
from core.constants import BASE_RATE_CENTS_PER_MINUTE, GOAL_STALE_AFTER_DAYS
from core.store import clock, db

from . import derive, policy, workload

raw = T.raw_or_none


def _common(row):
    out = {"id": row["id"], "created_at": row["created_at"].raw}
    if "version" in row:
        out["updated_at"] = row["updated_at"].raw
        out["version"] = row["version"]
    return out


def rider(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "weight_lb": row["weight_lb"],
        "household_income_band": row["household_income_band"],
        "demographic_group": row["demographic_group"],
        "program_code": row["program_code"],
        "funding_mode": row["funding_mode"],
        "payer_rate_cents": row["payer_rate_cents"],
        "condition_codes": list(row["condition_codes"]),
        "status": row["status"],
        "medical_hold_incident_id": row["medical_hold_incident_id"],
        "withdraw_reason": row["withdraw_reason"],
        "independence_level": row["independence_level"],
        "required_sidewalker_count": row["required_sidewalker_count"],
        "requires_leader": row["requires_leader"],
        "sidewalker_hold_type": row["sidewalker_hold_type"],
        "backriding_required": row["backriding_required"],
        "assessment_next_due_at": raw(row["assessment_next_due_at"]),
        "assessment_status": derive.assessment_status(row),
        "active_release_id": None,
        "goals_met_count": derive.goals_met_count(row["id"]),
    })
    active = derive.active_release(row["id"])
    out["active_release_id"] = active["id"] if active else None
    return out


def condition_policy(row):
    out = _common(row)
    out.update({
        "condition_code": row["condition_code"],
        "activity_type": row["activity_type"],
        "tier": row["tier"],
        "min_instructor_tier": row["min_instructor_tier"],
    })
    return out


def medical_release(row):
    out = _common(row)
    out.update({
        "rider_id": row["rider_id"],
        "signed_on": row["signed_on"],
        "physician_name": row["physician_name"],
        "cleared_condition_codes": list(row["cleared_condition_codes"]),
        "expires_at": raw(row["expires_at"]),
        "revoked_at": raw(row.get("revoked_at")),
        "superseded_at": raw(row.get("superseded_at")),
        "status": derive.release_status(row),
    })
    return out


def assessment(row):
    out = _common(row)
    out.update({
        "rider_id": row["rider_id"],
        "assessment_type": row["assessment_type"],
        "performed_on": row["performed_on"],
        "balance_score": row["balance_score"],
        "trunk_control_score": row["trunk_control_score"],
        "rider_weight_lb": row["rider_weight_lb"],
        "backriding_required": row["backriding_required"],
        "combined_score": row["combined_score"],
        "independence_level": row["independence_level"],
        "required_sidewalker_count": row["required_sidewalker_count"],
        "requires_leader": row["requires_leader"],
        "sidewalker_hold_type": row["sidewalker_hold_type"],
        "next_due_at": raw(row["next_due_at"]),
        "status": row["status"],
    })
    return out


def horse(row):
    today = T.day_of(clock.now())
    view_day = workload.day_window(today)
    view_week = workload.week_window(today)
    out = _common(row)
    out.update({
        "name": row["name"],
        "body_weight_lb": row["body_weight_lb"],
        "tack_weight_lb": row["tack_weight_lb"],
        "max_load_lb": row["max_load_lb"],
        "status": row["status"],
        "hold_release_at": raw(row.get("hold_release_at")),
        "hold_reason": row.get("hold_reason"),
        "current_week_start_date": T.date_str(T.week_start(today)),
        "current_week_committed_minutes": workload.minutes_in_window(
            row["id"], view_week, "committed"),
        "current_day_committed_minutes": workload.minutes_in_window(
            row["id"], view_day, "committed"),
        "current_day_session_count": workload.session_count_in_window(
            row["id"], view_day, "committed"),
    })
    return out


def volunteer(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "last_retraining_on": row["last_retraining_on"],
        "age_years": derive.age_years(row["date_of_birth"]),
        "retraining_due_at": raw(row["retraining_due_at"]),
        "suspended_until": raw(row.get("suspended_until")),
        "suspension_reason": row.get("suspension_reason"),
        "status": derive.volunteer_status(row),
        "open_assignment_count": derive.open_assignment_count(row["id"]),
    })
    return out


def qualification(row):
    out = _common(row)
    out.update({
        "volunteer_id": row["volunteer_id"],
        "crew_role": row["crew_role"],
        "training_hours": row["training_hours"],
        "signed_off_on": row.get("signed_off_on"),
        "expires_at": raw(row.get("expires_at")),
        "status": derive.qualification_status(row),
    })
    return out


def instructor(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "certification_level": row["certification_level"],
        "certification_expires_at": row["certification_expires_at"].raw,
        "supervisor_instructor_id": row.get("supervisor_instructor_id"),
        "ce_hours_accrued": row["ce_hours_accrued"],
        "suspended_until": raw(row.get("suspended_until")),
        "certification_status": derive.certification_status(row),
    })
    return out


def session(row):
    rider_row = db["riders"].get(row["rider_id"])
    horse_row = db["horses"].get(row["horse_id"])
    result = policy.evaluate_precaution(rider_row, row["activity_type"]) if rider_row else None
    out = _common(row)
    out.update({
        "rider_id": row["rider_id"],
        "horse_id": row["horse_id"],
        "instructor_id": row["instructor_id"],
        "supervising_instructor_id": row.get("supervising_instructor_id"),
        "activity_type": row["activity_type"],
        "scheduled_start": row["scheduled_start"].raw,
        "duration_minutes": row["duration_minutes"],
        "scheduled_end": row["scheduled_end"].raw,
        "mounted_minutes": row.get("mounted_minutes"),
        "schedule_status": row["schedule_status"],
        "billing_status": row["billing_status"],
        "cancellation_reason": row.get("cancellation_reason"),
        "crew_satisfied": derive.crew_satisfied(row),
        "effective_load_lb": (policy.effective_load_lb(rider_row, horse_row)
                              if rider_row and horse_row else None),
        "precaution_tier": result.tier if result else None,
        "required_instructor_tier": (policy.required_instructor_tier(
            rider_row, row["activity_type"]) if rider_row else None),
        "quoted_fee_cents": (row["duration_minutes"]
                             * BASE_RATE_CENTS_PER_MINUTE[row["activity_type"]]),
        "service_hours": derive.session_service_hours(row),
    })
    return out


def crew_assignment(row):
    out = _common(row)
    out.update({
        "session_id": row["session_id"],
        "volunteer_id": row["volunteer_id"],
        "crew_role": row["crew_role"],
        "hold_type": row.get("hold_type"),
        "status": row["status"],
        "release_reason": row.get("release_reason"),
    })
    return out


def goal(row):
    anchor = row.get("last_rated_at") or row["created_at"]
    out = _common(row)
    out.update({
        "rider_id": row["rider_id"],
        "domain": row["domain"],
        "objective": row["objective"],
        "baseline_rating": row["baseline_rating"],
        "target_rating": row["target_rating"],
        "current_rating": row.get("current_rating"),
        "consecutive_target_hits": row["consecutive_target_hits"],
        "last_rated_at": raw(row.get("last_rated_at")),
        "stale_after": T.minted(T.plus_days(anchor.dt, GOAL_STALE_AFTER_DAYS)).raw,
        "status": row["status"],
        "discontinue_reason": row.get("discontinue_reason"),
    })
    return out


def progress_note(row):
    out = _common(row)
    out.update({
        "session_id": row["session_id"],
        "rider_id": row["rider_id"],
        "author_instructor_id": row["author_instructor_id"],
        "narrative": row["narrative"],
        "goal_ratings": [dict(entry) for entry in row["goal_ratings"]],
        "status": row["status"],
        "finalized_at": raw(row.get("finalized_at")),
        "recorded_service_hours": row["recorded_service_hours"],
    })
    return out


def grant(row):
    allocated = derive.grant_allocated(row["id"])
    out = _common(row)
    out.update({
        "grant_name": row["grant_name"],
        "funder_name": row["funder_name"],
        "awarded_amount_cents": row["awarded_amount_cents"],
        "restricted_program_code": row.get("restricted_program_code"),
        "restricted_demographic": row.get("restricted_demographic"),
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "allocated_amount_cents": allocated,
        "remaining_amount_cents": row["awarded_amount_cents"] - allocated,
        "status": derive.grant_status(row),
    })
    return out


def scholarship_award(row):
    out = _common(row)
    out.update({
        "rider_id": row["rider_id"],
        "cap_pct": row["cap_pct"],
        "period_cap_cents": row["period_cap_cents"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "period_used_cents": derive.award_used(row["id"]),
        "superseded_at": raw(row.get("superseded_at")),
        "status": derive.award_status(row),
    })
    return out


def charge(row):
    reversed_at = row.get("reversed_at")
    out = _common(row)
    out.update({
        "session_id": row["session_id"],
        "charge_type": row["charge_type"],
        "amount_cents": row["amount_cents"],
        "allocated_cents": 0 if reversed_at else derive.allocated_cents(row["id"]),
        "balance_due_cents": 0 if reversed_at else derive.balance_due_cents(row["id"]),
        "scholarship_excluded": row["scholarship_excluded"],
        "status": derive.charge_status(row),
        "reversed_at": raw(reversed_at),
        "reversal_reason": row.get("reversal_reason"),
    })
    return out


def funding_allocation(row):
    out = _common(row)
    out.update({
        "charge_id": row["charge_id"],
        "grant_id": row.get("grant_id"),
        "scholarship_award_id": row.get("scholarship_award_id"),
        "source_type": row["source_type"],
        "sequence_index": row["sequence_index"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
    })
    return out


def incident(row):
    out = _common(row)
    out.update({
        "session_id": row["session_id"],
        "implicated_volunteer_id": row.get("implicated_volunteer_id"),
        "incident_type": row["incident_type"],
        "injury_reported": row["injury_reported"],
        "occurred_at": row["occurred_at"].raw,
        "narrative": row["narrative"],
        "severity": row["severity"],
        "reported_at": row["reported_at"].raw,
        "report_due_at": row["report_due_at"].raw,
        "reported_late": row["reported_late"],
        "rider_hold_applied": row["rider_hold_applied"],
        "horse_hold_applied": row["horse_hold_applied"],
        "volunteer_suspension_applied": row["volunteer_suspension_applied"],
        "instructor_suspension_applied": row["instructor_suspension_applied"],
        "cancelled_session_count": row["cancelled_session_count"],
        "status": row["status"],
        "reviewer_notes": row.get("reviewer_notes"),
        "resolution": row.get("resolution"),
    })
    return out
