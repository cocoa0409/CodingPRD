"""Entity serializers.

Derived counters are computed on read from their constituent rows, which is
what makes the conserved quantities of PRD 2.9 exact: they can never drift
from the rows they summarise, and a compensating action restores them to
precisely their prior value.
"""

from calc import team_compliance_posture
from store import DB


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if "version" in row:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    return out


# --------------------------------------------------------------------------
# derived aggregates
# --------------------------------------------------------------------------

def team_severity_total(team_id):
    total = 0
    members = {w["id"] for w in DB.wrestlers.values() if w.get("team_id") == team_id}
    for flag in DB.flags.values():
        if flag.get("wrestler_id") in members and flag.get("status") in ("OPEN", "ESCALATED"):
            total += int(flag.get("severity") or 0)
    return total


def team_posture(team_id):
    return team_compliance_posture(team_severity_total(team_id))


def team_roster_count(team_id):
    return len([
        w for w in DB.wrestlers.values()
        if w.get("team_id") == team_id
        and w.get("certification_status") != "DISQUALIFIED"
    ])


def open_flag_count(wrestler_id):
    return len([
        f for f in DB.flags.values()
        if f.get("wrestler_id") == wrestler_id
        and f.get("status") in ("OPEN", "ESCALATED")
    ])


def season_team_count(season_id):
    return len([t for t in DB.teams.values() if t.get("season_id") == season_id])


def season_certified_wrestler_count(season_id):
    team_ids = {t["id"] for t in DB.teams.values() if t.get("season_id") == season_id}
    return len([
        w for w in DB.wrestlers.values()
        if w.get("team_id") in team_ids and w.get("certification_status") == "CERTIFIED"
    ])


def assessor_counts(assessor_id):
    validated = 0
    voided = 0
    for row in DB.assessments.values():
        if row.get("assessor_id") != assessor_id:
            continue
        if row.get("status") in ("VALIDATED", "SUPERSEDED"):
            validated += 1
        elif row.get("status") == "VOIDED":
            voided += 1
    return validated, voided


def last_audit_outcome(assessor_id):
    rows = [
        a for a in DB.audits.values()
        if a.get("assessor_id") == assessor_id and a.get("status") == "FINALIZED"
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    return rows[-1].get("outcome")


def plan_milestone_counts(plan_id):
    total = 0
    missed = 0
    for row in DB.milestones.values():
        if row.get("plan_id") != plan_id:
            continue
        total += 1
        if row.get("status") == "MISSED":
            missed += 1
    return total, missed


def event_counters(event_id):
    entry_count = 0
    weighed_in = 0
    seeded = 0
    seed_sum = 0
    for row in DB.entries.values():
        if row.get("event_id") != event_id:
            continue
        entry_count += 1
        if row.get("status") in ("WEIGHED_IN", "SEEDED"):
            weighed_in += 1
        if row.get("seed_number") is not None:
            seeded += 1
            seed_sum += int(row.get("seed_number"))
    return entry_count, weighed_in, seeded, seed_sum


# --------------------------------------------------------------------------
# entity serializers
# --------------------------------------------------------------------------

SEASON_CONSTANTS = (
    "weight_classes",
    "min_body_fat_pct_male",
    "min_body_fat_pct_female",
    "hydration_max_specific_gravity",
    "max_weekly_descent_pct",
    "assessor_min_training_hours",
    "audit_fail_threshold_pct",
    "audit_min_sample_count",
    "max_consecutive_day_allowance_lbs",
    "appeal_filing_window_days",
    "max_appeal_retest_rounds",
    "assessor_daily_assessment_capacity",
    "plan_breach_limit",
)


def season(row):
    out = {"name": row.get("name"), "start_date": row.get("start_date")}
    for field in SEASON_CONSTANTS:
        out[field] = row.get(field)
    out["status"] = row.get("status")
    out["team_count"] = season_team_count(row["id"])
    out["certified_wrestler_count"] = season_certified_wrestler_count(row["id"])
    return _common(row, out)


def team(row):
    total = team_severity_total(row["id"])
    out = {
        "season_id": row.get("season_id"),
        "school_name": row.get("school_name"),
        "roster_count": team_roster_count(row["id"]),
        "open_flag_severity_total": total,
        "compliance_status": team_compliance_posture(total),
    }
    return _common(row, out)


def assessor(row):
    validated, voided = assessor_counts(row["id"])
    out = {
        "full_name": row.get("full_name"),
        "credential_number": row.get("credential_number"),
        "certified_methods": list(row.get("certified_methods") or []),
        "certification_expires_on": row.get("certification_expires_on"),
        "training_hours_completed": row.get("training_hours_completed"),
        "status": row.get("status"),
        "validated_assessment_count": validated,
        "voided_assessment_count": voided,
        "last_audit_outcome": last_audit_outcome(row["id"]),
        "suspension_reason": row.get("suspension_reason"),
    }
    return _common(row, out)


def wrestler(row):
    out = {
        "team_id": row.get("team_id"),
        "source_assessment_id": row.get("source_assessment_id"),
        "full_name": row.get("full_name"),
        "sex": row.get("sex"),
        "grade": row.get("grade"),
        "certification_status": row.get("certification_status"),
        "eligibility_status": row.get("eligibility_status"),
        "alpha_weight_lbs": row.get("alpha_weight_lbs"),
        "body_fat_pct": row.get("body_fat_pct"),
        "minimum_certified_weight_lbs": row.get("minimum_certified_weight_lbs"),
        "min_weight_class_lbs": row.get("min_weight_class_lbs"),
        "lowest_eligible_class_lbs": row.get("lowest_eligible_class_lbs"),
        "open_health_flag_count": open_flag_count(row["id"]),
        "disqualified_at": row.get("disqualified_at"),
        "certification_hold_reason": row.get("certification_hold_reason"),
    }
    return _common(row, out)


def assessment(row):
    out = {
        "wrestler_id": row.get("wrestler_id"),
        "assessor_id": row.get("assessor_id"),
        "retest_of_assessment_id": row.get("retest_of_assessment_id"),
        "appeal_id": row.get("appeal_id"),
        "method": row.get("method"),
        "assessed_at": row.get("assessed_at"),
        "measured_weight_lbs": row.get("measured_weight_lbs"),
        "body_fat_pct": row.get("body_fat_pct"),
        "urine_specific_gravity": row.get("urine_specific_gravity"),
        "status": row.get("status"),
        "hydration_passed": row.get("hydration_passed"),
        "lean_body_weight_lbs": row.get("lean_body_weight_lbs"),
        "minimum_certified_weight_lbs": row.get("minimum_certified_weight_lbs"),
        "min_weight_class_lbs": row.get("min_weight_class_lbs"),
        "alpha_weight_lbs": row.get("alpha_weight_lbs"),
        "void_reason": row.get("void_reason"),
    }
    return _common(row, out)


def appeal(row):
    out = {
        "assessment_id": row.get("assessment_id"),
        "team_id": row.get("team_id"),
        "reviewing_assessor_id": row.get("reviewing_assessor_id"),
        "retest_assessment_id": row.get("retest_assessment_id"),
        "reason": row.get("reason"),
        "filed_at": row.get("filed_at"),
        "status": row.get("status"),
        "retest_round_count": row.get("retest_round_count"),
        "decision_note": row.get("decision_note"),
    }
    return _common(row, out)


def plan(row):
    milestone_count, missed = plan_milestone_counts(row["id"])
    out = {
        "wrestler_id": row.get("wrestler_id"),
        "source_assessment_id": row.get("source_assessment_id"),
        "supersedes_plan_id": row.get("supersedes_plan_id"),
        "plan_variant": row.get("plan_variant"),
        "target_class_lbs": row.get("target_class_lbs"),
        "plan_start_date": row.get("plan_start_date"),
        "weekly_rate_pct": row.get("weekly_rate_pct"),
        "weekly_delta_lbs": row.get("weekly_delta_lbs"),
        "status": row.get("status"),
        "total_weeks": row.get("total_weeks"),
        "milestone_count": milestone_count,
        "projected_certification_date": row.get("projected_certification_date"),
        "missed_milestone_count": missed,
        "breach_count": row.get("breach_count"),
        "revision_count": row.get("revision_count"),
        "cancel_reason": row.get("cancel_reason"),
    }
    return _common(row, out)


def milestone(row):
    out = {
        "plan_id": row.get("plan_id"),
        "week_index": row.get("week_index"),
        "effective_date": row.get("effective_date"),
        "allowable_weight_lbs": row.get("allowable_weight_lbs"),
        "min_eligible_class_lbs": row.get("min_eligible_class_lbs"),
        "status": row.get("status"),
        "evaluated_recorded_weight_lbs": row.get("evaluated_recorded_weight_lbs"),
    }
    return _common(row, out)


def event(row):
    entry_count, weighed_in, seeded, seed_sum = event_counters(row["id"])
    out = {
        "season_id": row.get("season_id"),
        "name": row.get("name"),
        "event_type": row.get("event_type"),
        "event_date": row.get("event_date"),
        "competition_days": row.get("competition_days"),
        "weigh_in_days": row.get("weigh_in_days"),
        "consecutive_day_allowance_lbs": row.get("consecutive_day_allowance_lbs"),
        "status": row.get("status"),
        "bracket_locked": row.get("bracket_locked"),
        "reseed_required": row.get("reseed_required"),
        "entry_count": entry_count,
        "weighed_in_count": weighed_in,
        "seeded_entry_count": seeded,
        "seed_integrity_sum": seed_sum,
    }
    return _common(row, out)


def entry(row):
    out = {
        "event_id": row.get("event_id"),
        "wrestler_id": row.get("wrestler_id"),
        "weight_class_lbs": row.get("weight_class_lbs"),
        "season_win_count": row.get("season_win_count"),
        "status": row.get("status"),
        "seed_number": row.get("seed_number"),
        "latest_effective_weight_lbs": row.get("latest_effective_weight_lbs"),
        "weight_class_change_count": row.get("weight_class_change_count"),
        "scratch_reason": row.get("scratch_reason"),
    }
    return _common(row, out)


def weigh_in(row):
    out = {
        "event_id": row.get("event_id"),
        "wrestler_id": row.get("wrestler_id"),
        "entry_id": row.get("entry_id"),
        "day_index": row.get("day_index"),
        "recorded_weight_lbs": row.get("recorded_weight_lbs"),
        "recorded_at": row.get("recorded_at"),
        "official_user_id": row.get("official_user_id"),
        "allowance_lbs": row.get("allowance_lbs"),
        "effective_limit_lbs": row.get("effective_limit_lbs"),
        "result": row.get("result"),
        "below_minimum": row.get("below_minimum"),
    }
    return _common(row, out)


def eligibility_check(row):
    out = {
        "wrestler_id": row.get("wrestler_id"),
        "event_id": row.get("event_id"),
        "requested_class_lbs": row.get("requested_class_lbs"),
        "checked_at": row.get("checked_at"),
        "as_of_date": row.get("as_of_date"),
        "growth_allowance_lbs": row.get("growth_allowance_lbs"),
        "schedule_allowable_weight_lbs": row.get("schedule_allowable_weight_lbs"),
        "lowest_eligible_class_lbs": row.get("lowest_eligible_class_lbs"),
        "outcome": row.get("outcome"),
        "blocking_error_id": row.get("blocking_error_id"),
    }
    return _common(row, out)


def growth_allowance(row):
    out = {
        "season_id": row.get("season_id"),
        "effective_date": row.get("effective_date"),
        "allowance_lbs": row.get("allowance_lbs"),
        "note": row.get("note"),
    }
    return _common(row, out)


def health_flag(row):
    out = {
        "wrestler_id": row.get("wrestler_id"),
        "weigh_in_id": row.get("weigh_in_id"),
        "source": row.get("source"),
        "severity": row.get("severity"),
        "status": row.get("status"),
        "raised_at": row.get("raised_at"),
        "review_note": row.get("review_note"),
        "reviewer_user_id": row.get("reviewer_user_id"),
    }
    return _common(row, out)


def audit(row):
    samples = [
        {
            "assessment_id": s.get("assessment_id"),
            "remeasured_body_fat_pct": s.get("remeasured_body_fat_pct"),
        }
        for s in (row.get("samples") or [])
    ]
    out = {
        "season_id": row.get("season_id"),
        "assessor_id": row.get("assessor_id"),
        "audit_type": row.get("audit_type"),
        "scoring_variant": row.get("scoring_variant"),
        "sample_window_start": row.get("sample_window_start"),
        "samples": samples,
        "sample_count": row.get("sample_count"),
        "discrepancy_score": row.get("discrepancy_score"),
        "outcome": row.get("outcome"),
        "voided_assessment_count": row.get("voided_assessment_count"),
        "status": row.get("status"),
    }
    return _common(row, out)
