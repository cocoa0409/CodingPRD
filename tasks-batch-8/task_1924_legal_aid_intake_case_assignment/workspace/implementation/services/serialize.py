"""Entity serializers: internal records -> public JSON dicts.

Decimals serialize as JSON numbers; datetimes as ISO 8601 UTC strings with
three fractional digits; internal bookkeeping keys (_seq) are stripped.
"""
from db import fmt_dt
from services import derived
from services.calc import utilization_pct


def _num(d):
    return float(d) if d is not None else None


def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def client_json(c):
    out = {
        "id": c["id"],
        "full_name": c["full_name"],
        "residence_county": c["residence_county"],
        "household_size": c["household_size"],
        "annual_gross_income_cents": c["annual_gross_income_cents"],
        "annual_countable_income_cents": c["annual_countable_income_cents"],
        "receives_means_tested_benefits": c["receives_means_tested_benefits"],
        "vulnerability_factors": list(c["vulnerability_factors"]),
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def application_json(a):
    out = {
        "id": a["id"],
        "client_id": a["client_id"],
        "case_type": a["case_type"],
        "opposing_party_name": a["opposing_party_name"],
        "incident_county": a["incident_county"],
        "incident_description": a["incident_description"],
        "status": a["status"],
        "venue": a["venue"],
        "gross_poverty_percentage": _num(a["gross_poverty_percentage"]),
        "countable_poverty_percentage": _num(a["countable_poverty_percentage"]),
        "priority_score": _num(a["priority_score"]),
        "eligibility_determination": a["eligibility_determination"],
        "screened_by_staff_id": a["screened_by_staff_id"],
        "screened_at": fmt_dt(a["screened_at"]),
        "promoted_from_waitlist": a["promoted_from_waitlist"],
    }
    out.update(_common(a))
    return out


def conflict_check_json(c):
    out = {
        "id": c["id"],
        "application_id": c["application_id"],
        "result": c["result"],
        "checked_by_staff_id": c["checked_by_staff_id"],
        "checked_at": fmt_dt(c["checked_at"]),
        "valid_until": fmt_dt(c["valid_until"]),
        "notes": c["notes"],
        "waiver_reason": c["waiver_reason"],
        "resolved_by_staff_id": c["resolved_by_staff_id"],
        "resolved_at": fmt_dt(c["resolved_at"]),
    }
    out.update(_common(c))
    return out


def case_json(c):
    out = {
        "id": c["id"],
        "application_id": c["application_id"],
        "grant_program_id": c["grant_program_id"],
        "assigned_attorney_id": c["assigned_attorney_id"],
        "assigned_paralegal_id": c["assigned_paralegal_id"],
        "service_level": c["service_level"],
        "venue": c["venue"],
        "placement": c["placement"],
        "status": c["status"],
        "funding_status": c["funding_status"],
        "case_weight": c["case_weight"],
        "reserved_cents": c["reserved_cents"],
        "outcome_code": c["outcome_code"],
        "closure_reason": c["closure_reason"],
        "advice_deadline": fmt_dt(c["advice_deadline"]),
        "opened_at": fmt_dt(c["opened_at"]),
        "closed_at": fmt_dt(c["closed_at"]),
    }
    out.update(_common(c))
    return out


def staff_json(m):
    weight, count = derived.attorney_load_count(m["id"])
    out = {
        "id": m["id"],
        "full_name": m["full_name"],
        "staff_type": m["staff_type"],
        "admitted_counties": list(m["admitted_counties"]),
        "practice_areas": list(m["practice_areas"]),
        "max_units": m["max_units"],
        "supervising_attorney_id": m["supervising_attorney_id"],
        "status": m["status"],
        "weighted_open_units": weight,
        "open_case_count": count,
    }
    out.update(_common(m))
    return out


def panel_member_json(m):
    out = {
        "id": m["id"],
        "full_name": m["full_name"],
        "firm_name": m["firm_name"],
        "practice_areas": list(m["practice_areas"]),
        "counties": list(m["counties"]),
        "max_active_referrals": m["max_active_referrals"],
        "active_referral_count": derived.panel_active_count(m["id"]),
        "status": m["status"],
    }
    out.update(_common(m))
    return out


def referral_json(r):
    out = {
        "id": r["id"],
        "case_id": r["case_id"],
        "panel_member_id": r["panel_member_id"],
        "status": r["status"],
        "notes": r["notes"],
        "offered_at": fmt_dt(r["offered_at"]),
        "response_deadline": fmt_dt(r["response_deadline"]),
        "responded_at": fmt_dt(r["responded_at"]),
        "service_start_date": r["service_start_date"],
        "service_end_date": r["service_end_date"],
        "decline_reason": r["decline_reason"],
    }
    out.update(_common(r))
    return out


def grant_program_json(g):
    reserved = derived.grant_reserved_cents(g["id"])
    spent = derived.grant_spent_cents(g["id"])
    out = {
        "id": g["id"],
        "name": g["name"],
        "funder": g["funder"],
        "period_start": g["period_start"],
        "period_end": g["period_end"],
        "allowed_case_types": list(g["allowed_case_types"]),
        "allowed_counties": list(g["allowed_counties"]),
        "income_cap_percentage": _num(g["income_cap_percentage"]),
        "per_case_rate_cents": g["per_case_rate_cents"],
        "total_budget_cents": g["total_budget_cents"],
        "reserved_cents": reserved,
        "spent_cents": spent,
        "available_cents": g["total_budget_cents"] - reserved - spent,
        "status": g["status"],
    }
    out.update(_common(g))
    return out


def grant_report_json(r):
    out = {
        "id": r["id"],
        "grant_program_id": r["grant_program_id"],
        "period_label": r["period_label"],
        "status": r["status"],
        "cases_opened_count": r["cases_opened_count"],
        "cases_closed_count": r["cases_closed_count"],
        "total_hours": _num(r["total_hours"]),
        "reserved_cents_snapshot": r["reserved_cents_snapshot"],
        "spent_cents_snapshot": r["spent_cents_snapshot"],
        "generated_by_user_id": r["generated_by_user_id"],
        "return_reason": r["return_reason"],
    }
    out.update(_common(r))
    return out


def venue_rule_json(r):
    return {
        "id": r["id"],
        "county": r["county"],
        "case_type": r["case_type"],
        "venue": r["venue"],
        "priority_base_weight": r["priority_base_weight"],
        "extended_eligible": r["extended_eligible"],
        "created_at": fmt_dt(r["created_at"]),
    }


def time_entry_json(t):
    return {
        "id": t["id"],
        "case_id": t["case_id"],
        "staff_id": t["staff_id"],
        "hours": _num(t["hours"]),
        "activity_code": t["activity_code"],
        "work_date": t["work_date"],
        "created_at": fmt_dt(t["created_at"]),
    }


def survey_json(s):
    return {
        "id": s["id"],
        "case_id": s["case_id"],
        "score": s["score"],
        "would_recommend": s["would_recommend"],
        "comments": s["comments"],
        "created_at": fmt_dt(s["created_at"]),
    }


def unmet_record_json(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "reason_code": r["reason_code"],
        "case_type": r["case_type"],
        "incident_county": r["incident_county"],
        "created_at": fmt_dt(r["created_at"]),
    }


def waitlist_entry_json(e):
    return {
        "id": e["id"],
        "application_id": e["application_id"],
        "priority_score_snapshot": _num(e["priority_score_snapshot"]),
        "required_weight": e["required_weight"],
        "created_at": fmt_dt(e["created_at"]),
    }


def caseload_json(member):
    weight, count = derived.attorney_load_count(member["id"])
    return {
        "weighted_open_units": weight,
        "open_case_count": count,
        "max_units": member["max_units"],
        "available_units": member["max_units"] - weight,
        "utilization_pct": utilization_pct(weight, member["max_units"]),
    }


def grant_utilization_json(program):
    reserved = derived.grant_reserved_cents(program["id"])
    spent = derived.grant_spent_cents(program["id"])
    total = program["total_budget_cents"]
    return {
        "total_budget_cents": total,
        "reserved_cents": reserved,
        "spent_cents": spent,
        "available_cents": total - reserved - spent,
        "utilization_pct": utilization_pct(reserved + spent, total),
    }
