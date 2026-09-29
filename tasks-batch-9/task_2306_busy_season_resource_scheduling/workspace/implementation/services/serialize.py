"""Resource serialization.

Every ``source: computed`` field is evaluated here, at read time, from the
current rows and the current logical clock.
"""

from decimal import Decimal

import db
from services import calc


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def day(value):
    return None if value is None else value.isoformat()


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def client(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "industry_code": row["industry_code"],
            "public_interest_entity": row["public_interest_entity"],
            "fiscal_year_end": day(row["fiscal_year_end"]),
            "partner_rotation_limit_years": calc.partner_rotation_limit_years(row),
            "engagement_count": calc.engagement_count(row["id"]),
        }
    )
    return out


def staff_member(row):
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "level": row["level"],
            "service_center": row["service_center"],
            "industry_specialization": row["industry_specialization"],
            "cpa_licensed": row["cpa_licensed"],
            "base_weekly_cap_hours": num(row["base_weekly_cap_hours"]),
            "hourly_bill_rate": num(row["hourly_bill_rate"]),
            "review_capable": calc.review_capable(row),
            "committed_hours_current_week": num(calc.committed_hours_current_week(row)),
            "effective_weekly_cap_hours": num(
                calc.effective_weekly_cap(row, calc.current_week_start())
            ),
            "daily_capacity_hours": num(calc.daily_capacity_hours(row)),
            "workload_status": calc.workload_status(row),
            "burnout_risk_score_actual": num(calc.burnout_risk_score_actual(row)),
            "burnout_risk_score_committed": num(calc.burnout_risk_score_committed(row)),
            "turnover_risk_band": calc.turnover_risk_band(row),
        }
    )
    return out


def engagement(row):
    figures = calc.realization(row)
    out = _common(row)
    out.update(
        {
            "client_id": row["client_id"],
            "engagement_partner_staff_id": row["engagement_partner_staff_id"],
            "service_line": row["service_line"],
            "busy_season_year": row["busy_season_year"],
            "deadline_date": day(row["deadline_date"]),
            "budget_fee_amount": num(row["budget_fee_amount"]),
            "status": row["status"],
            "pre_block_status": row["pre_block_status"],
            "client_block_count": row["client_block_count"],
            "scope_change_count": row["scope_change_count"],
            "staffing_completion_pct": num(calc.staffing_completion_pct(row)),
            "schedule_risk_band": calc.schedule_risk_band(row),
            "realization_pct_provisional": num(figures["realization_pct_provisional"]),
            "realization_pct_final": num(figures["realization_pct_final"]),
        }
    )
    return out


def phase(row):
    out = _common(row)
    out.update(
        {
            "engagement_id": row["engagement_id"],
            "phase_type": row["phase_type"],
            "expected_hours": num(row["expected_hours"]),
            "window_start_date": day(row["window_start_date"]),
            "window_end_date": day(row["window_end_date"]),
            "required_level": row["required_level"],
            "required_industry_specialization": row["required_industry_specialization"],
            "requires_cpa_licensed": row["requires_cpa_licensed"],
            "staffing_status": row["staffing_status"],
            "staffed_hours": num(calc.phase_staffed_hours(row)),
            "unstaffed_hours": num(calc.phase_unstaffed_hours(row)),
        }
    )
    return out


def assignment(row):
    out = _common(row)
    out.update(
        {
            "engagement_phase_id": row["engagement_phase_id"],
            "staff_member_id": row["staff_member_id"],
            "start_date": day(row["start_date"]),
            "end_date": day(row["end_date"]),
            "allocated_hours": num(row["allocated_hours"]),
            "review_owner_staff_id": row["review_owner_staff_id"],
            "review_capacity_window_id": row["review_capacity_window_id"],
            "daily_hours": num(row["daily_hours"]),
            "calendar_day_count": row["calendar_day_count"],
            "rate_model": row["rate_model"],
            "review_hours_charged": num(row["review_hours_charged"]),
            "fit_score": num(row["fit_score"]),
            "staffing_status": row["staffing_status"],
            "review_status": row["review_status"],
            "rework_cycles": row["rework_cycles"],
            "superseded_by_assignment_id": row["superseded_by_assignment_id"],
        }
    )
    return out


def availability_exception(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "staff_member_id": row["staff_member_id"],
        "exception_type": row["exception_type"],
        "start_date": day(row["start_date"]),
        "end_date": day(row["end_date"]),
        "available_hours_per_day": num(row["available_hours_per_day"]),
    }


def time_entry(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "assignment_id": row["assignment_id"],
        "work_date": day(row["work_date"]),
        "hours": num(row["hours"]),
        "entry_type": row["entry_type"],
    }


def restriction(row):
    out = _common(row)
    out.update(
        {
            "client_id": row["client_id"],
            "staff_member_id": row["staff_member_id"],
            "restriction_type": row["restriction_type"],
            "effective_start_date": day(row["effective_start_date"]),
            "effective_end_date": day(row["effective_end_date"]),
            "status": row["status"],
            "released_assignment_count": row["released_assignment_count"],
        }
    )
    return out


def review_window(row):
    committed = calc.committed_review_hours(row["id"])
    out = _common(row)
    out.update(
        {
            "reviewer_staff_id": row["reviewer_staff_id"],
            "week_start_date": day(row["week_start_date"]),
            "review_capacity_hours": num(row["review_capacity_hours"]),
            "committed_review_hours": num(committed),
            "remaining_review_hours": num(
                calc.r2(calc.D(row["review_capacity_hours"]) - committed)
            ),
        }
    )
    return out


def reschedule_plan(row):
    out = _common(row)
    out.update(
        {
            "engagement_id": row["engagement_id"],
            "trigger_reason": row["trigger_reason"],
            "shift_days": row["shift_days"],
            "added_hours": num(row["added_hours"]),
            "status": row["status"],
            "target_phase_id": row["target_phase_id"],
            "simulated_at_engagement_version": row["simulated_at_engagement_version"],
            "simulation_stale": calc.simulation_stale(row),
            "projected_unstaffed_hours": num(row["projected_unstaffed_hours"]),
            "projected_dropped_assignment_count": row["projected_dropped_assignment_count"],
            "projected_cap_breach_count": row["projected_cap_breach_count"],
            "projected_realization_pct": num(row["projected_realization_pct"]),
        }
    )
    return out


def waiver(row):
    out = _common(row)
    out.update(
        {
            "staff_member_id": row["staff_member_id"],
            "engagement_id": row["engagement_id"],
            "week_start_date": day(row["week_start_date"]),
            "extra_hours_allowance": num(row["extra_hours_allowance"]),
            "status": row["status"],
            "approved_by_user_id": row["approved_by_user_id"],
            "expiry_reason": row["expiry_reason"],
            "justification_note": row["justification_note"],
        }
    )
    return out
