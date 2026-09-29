"""Projections of stored rows onto the wire format."""
from db import fmt_ts
from services import calc


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def club_out(club):
    used = calc.exemption_slots_used(club["id"])
    out = _common(club)
    out.update({
        "name": club["name"],
        "market_code": club["market_code"],
        "exemption_slots_total": club["exemption_slots_total"],
        "compliance_score": club["compliance_score"],
        "adjudicated_compliance_score": club["adjudicated_compliance_score"],
        "escalation_tier": club["escalation_tier"],
        "status": club["status"],
        "outstanding_fine_cents": club["outstanding_fine_cents"],
        "open_violation_count": club["open_violation_count"],
        "exemption_slots_used": used,
        "exemption_slots_available": club["exemption_slots_total"] - used,
    })
    return out


def compliance_summary_out(club):
    used = calc.exemption_slots_used(club["id"])
    return {
        "club_id": club["id"],
        "compliance_score": club["compliance_score"],
        "adjudicated_compliance_score": club["adjudicated_compliance_score"],
        "escalation_tier": club["escalation_tier"],
        "status": club["status"],
        "outstanding_fine_cents": club["outstanding_fine_cents"],
        "open_violation_count": club["open_violation_count"],
        "exemption_slots_total": club["exemption_slots_total"],
        "exemption_slots_used": used,
        "exemption_slots_available": club["exemption_slots_total"] - used,
        "frozen_case_count": calc.frozen_case_count(club["id"]),
    }


def clinician_out(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "affiliation": row["affiliation"],
        "club_id": row.get("club_id"),
        "license_number": row["license_number"],
        "credential_expires_at": fmt_ts(row["credential_expires_at"]),
        "status": row["status"],
        "suspension_reason": row.get("suspension_reason"),
        "cases_cleared_count": row["cases_cleared_count"],
    })
    return out


def player_out(row):
    out = _common(row)
    out.update({
        "club_id": row["club_id"],
        "full_name": row["full_name"],
        "jersey_number": row["jersey_number"],
        "position": row["position"],
        "baseline_status": row["baseline_status"],
        "availability_status": row["availability_status"],
        "public_injury_designation": calc.resolve_public_designation(row["id"]),
        "diagnosed_case_count": calc.diagnosed_case_count(row["id"]),
    })
    return out


def game_out(row):
    out = _common(row)
    out.update({
        "season_year": row["season_year"],
        "week_index": row["week_index"],
        "home_club_id": row["home_club_id"],
        "away_club_id": row["away_club_id"],
        "kickoff_at": fmt_ts(row["kickoff_at"]),
        "status": row["status"],
        "report_window_opens_at": fmt_ts(row["report_window_opens_at"]),
        "report_window_closes_at": fmt_ts(row["report_window_closes_at"]),
    })
    return out


def baseline_out(row):
    out = _common(row)
    out.update({
        "player_id": row["player_id"],
        "administered_by_clinician_id": row["administered_by_clinician_id"],
        "season_year": row["season_year"],
        "composite_score": row["composite_score"],
        "reaction_time_ms": row["reaction_time_ms"],
        "symptom_score": row["symptom_score"],
        "administered_at": fmt_ts(row["administered_at"]),
        "validity_expires_at": fmt_ts(row["validity_expires_at"]),
        "status": row["status"],
        "retest_required_reason": row["retest_required_reason"],
    })
    return out


def evaluation_out(row):
    out = _common(row)
    out.update({
        "player_id": row["player_id"],
        "game_id": row["game_id"],
        "initiating_clinician_id": row["initiating_clinician_id"],
        "evaluating_clinician_id": row.get("evaluating_clinician_id"),
        "inc_clinician_id": row.get("inc_clinician_id"),
        "trigger_source": row["trigger_source"],
        "mandatory_removal": row["mandatory_removal"],
        "status": row["status"],
        "initiated_at": fmt_ts(row["initiated_at"]),
        "protocol_deadline_at": fmt_ts(row["protocol_deadline_at"]),
        "no_go_signs": list(row.get("no_go_signs") or []),
        "screen_symptom_score": row.get("screen_symptom_score"),
        "screened_at": fmt_ts(row.get("screened_at")),
        "exam_started_at": fmt_ts(row.get("exam_started_at")),
        "inc_block_ends_at": fmt_ts(row.get("inc_block_ends_at")),
        "exam_completed_at": fmt_ts(row.get("exam_completed_at")),
        "exam_duration_minutes": row.get("exam_duration_minutes"),
        "diagnosis_outcome": row["diagnosis_outcome"],
        "documentation_note": row.get("documentation_note"),
    })
    return out


def case_out(row):
    out = _common(row)
    out.update({
        "player_id": row["player_id"],
        "club_id": row["club_id"],
        "sideline_evaluation_id": row["sideline_evaluation_id"],
        "diagnosing_clinician_id": row["diagnosing_clinician_id"],
        "prior_case_id": row.get("prior_case_id"),
        "season_year": row["season_year"],
        "diagnosis_at": fmt_ts(row["diagnosis_at"]),
        "initial_symptom_score": row["initial_symptom_score"],
        "diagnosis_composite_score": row["diagnosis_composite_score"],
        "baseline_deviation_points": row["baseline_deviation_points"],
        "severity_index": row["severity_index"],
        "recurrence_count": row["recurrence_count"],
        "rtp_stage": row["rtp_stage"],
        "case_status": row["case_status"],
        "frozen_from_status": row.get("frozen_from_status"),
        "monitoring_status": row["monitoring_status"],
        "roster_exemption_status": row["roster_exemption_status"],
        "heightened_review_required": row["heightened_review_required"],
        "projected_return_at": fmt_ts(row.get("projected_return_at")),
        "earliest_return_at": fmt_ts(row.get("earliest_return_at")),
        "cleared_for_contact_at": fmt_ts(row.get("cleared_for_contact_at")),
        "last_symptom_check_score": row.get("last_symptom_check_score"),
        "last_symptomatic_at": fmt_ts(row.get("last_symptomatic_at")),
        "days_since_diagnosis": calc.days_since_diagnosis(row),
    })
    return out


def step_out(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "stage_index": row["stage_index"],
        "stage_name": row["stage_name"],
        "attempt_index": row["attempt_index"],
        "status": row["status"],
        "started_at": fmt_ts(row["started_at"]),
        "min_start_at": fmt_ts(row.get("min_start_at")),
        "dwell_complete_at": fmt_ts(row["dwell_complete_at"]),
        "evaluated_at": fmt_ts(row.get("evaluated_at")),
        "cleared_by_clinician_id": row.get("cleared_by_clinician_id"),
        "evaluation_symptom_score": row.get("evaluation_symptom_score"),
    })
    return out


def clearance_out(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "inc_clinician_id": row["inc_clinician_id"],
        "requested_by_clinician_id": row["requested_by_clinician_id"],
        "requested_at": fmt_ts(row["requested_at"]),
        "decided_at": fmt_ts(row.get("decided_at")),
        "expires_at": fmt_ts(row.get("expires_at")),
        "status": row["status"],
        "decision_notes": row.get("decision_notes"),
        "documented_stage_count": row["documented_stage_count"],
    })
    return out


def audit_out(row):
    out = _common(row)
    out.update({
        "club_id": row["club_id"],
        "case_id": row.get("case_id"),
        "sideline_evaluation_id": row.get("sideline_evaluation_id"),
        "opened_by_user_id": row.get("opened_by_user_id"),
        "auto_opened": row["auto_opened"],
        "status": row["status"],
        "violation_codes": list(row.get("violation_codes") or []),
        "exposure_days": row["exposure_days"],
        "escalation_tier_at_issuance": row.get("escalation_tier_at_issuance"),
        "assessed_fine_cents": row["assessed_fine_cents"],
        "response_round_count": row["response_round_count"],
        "club_response_note": row.get("club_response_note"),
        "findings_issued_by_user_id": row.get("findings_issued_by_user_id"),
        "closed_by_user_id": row.get("closed_by_user_id"),
        "disposition": row["disposition"],
        "findings_issued_at": fmt_ts(row.get("findings_issued_at")),
        "closed_at": fmt_ts(row.get("closed_at")),
        "closing_note": row.get("closing_note"),
    })
    return out


def report_out(row):
    out = _common(row)
    out.update({
        "game_id": row["game_id"],
        "player_id": row["player_id"],
        "club_id": row["club_id"],
        "practice_participation": row["practice_participation"],
        "designation": row["designation"],
        "required_designation": row["required_designation"],
        "filed_at": fmt_ts(row["filed_at"]),
        "amended_at": fmt_ts(row.get("amended_at")),
        "amended_from_designation": row.get("amended_from_designation"),
        "status": row["status"],
    })
    return out
