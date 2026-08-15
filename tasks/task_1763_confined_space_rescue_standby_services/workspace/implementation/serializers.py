"""Entity -> public JSON serializers.

Common fields (PRD section 2.4): id, created_at, updated_at, version on most
resources; AtmosphericReading and StatementLine carry only id + created_at.
"""

from helpers import pub_num


def personnel(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "role_qualifications": list(p["role_qualifications"]),
        "certifications": list(p["certifications"]),
        "max_duty_hours": p["max_duty_hours"],
        "status": p["status"],
        "committed_standby_minutes": p["committed_standby_minutes"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def client_account(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "billing_mode": a["billing_mode"],
        "hourly_standby_rate_cents": a["hourly_standby_rate_cents"],
        "event_base_fee_cents": a["event_base_fee_cents"],
        "event_per_rescuer_cents": a["event_per_rescuer_cents"],
        "deployment_surcharge_cents": a["deployment_surcharge_cents"],
        "credit_limit_cents": a["credit_limit_cents"],
        "minimum_billable_hours": pub_num(a["minimum_billable_hours"]),
        "tier1_hours_threshold": pub_num(a["tier1_hours_threshold"]),
        "tier2_multiplier": pub_num(a["tier2_multiplier"]),
        "after_hours_multiplier": pub_num(a["after_hours_multiplier"]),
        "weekend_multiplier": pub_num(a["weekend_multiplier"]),
        "balance_cents": a["balance_cents"],
        "on_credit_hold": a["on_credit_hold"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def confined_space(s):
    return {
        "id": s["id"],
        "client_account_id": s["client_account_id"],
        "space_code": s["space_code"],
        "classification": s["classification"],
        "requires_continuous_monitoring": s["requires_continuous_monitoring"],
        "max_entrants": s["max_entrants"],
        "ventilation_required": s["ventilation_required"],
        "blind_flange_required": s["blind_flange_required"],
        "exposure_standard": s["exposure_standard"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def rescue_plan(p):
    return {
        "id": p["id"],
        "space_id": p["space_id"],
        "required_team_size": p["required_team_size"],
        "required_certifications": list(p["required_certifications"]),
        "retrieval_system_type": p["retrieval_system_type"],
        "plan_revision": p["plan_revision"],
        "status": p["status"],
        "approved_by": p["approved_by"],
        "approved_at": p["approved_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def entry_permit(p):
    return {
        "id": p["id"],
        "space_id": p["space_id"],
        "client_account_id": p["client_account_id"],
        "purpose": p["purpose"],
        "planned_start_at": p["planned_start_at"],
        "planned_end_at": p["planned_end_at"],
        "issued_by": p["issued_by"],
        "issued_at": p["issued_at"],
        "actual_entry_at": p["actual_entry_at"],
        "last_suspended_at": p["last_suspended_at"],
        "closed_at": p["closed_at"],
        "close_reason": p["close_reason"],
        "suspension_count": p["suspension_count"],
        "reentry_count": p["reentry_count"],
        "event_base_billed": p["event_base_billed"],
        "cancellation_fee_billed": p["cancellation_fee_billed"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def isolation_verification(v):
    return {
        "id": v["id"],
        "permit_id": v["permit_id"],
        "isolation_type": v["isolation_type"],
        "evidence_ref": v["evidence_ref"],
        "created_by": v["created_by"],
        "verified_by": v["verified_by"],
        "verified_at": v["verified_at"],
        "expires_at": v["expires_at"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def roster_entry(e):
    return {
        "id": e["id"],
        "permit_id": e["permit_id"],
        "personnel_id": e["personnel_id"],
        "assignment_role": e["assignment_role"],
        "scheduled_start_at": e["scheduled_start_at"],
        "scheduled_end_at": e["scheduled_end_at"],
        "relief_of_entry_id": e["relief_of_entry_id"],
        "checked_in_at": e["checked_in_at"],
        "checked_out_at": e["checked_out_at"],
        "exposure_twa_ppm": pub_num(e["exposure_twa_ppm"]),
        "exposure_peak_ppm": pub_num(e["exposure_peak_ppm"]),
        "exposure_class": e["exposure_class"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def atmospheric_reading(r):
    return {
        "id": r["id"],
        "permit_id": r["permit_id"],
        "recorded_by": r["recorded_by"],
        "reading_kind": r["reading_kind"],
        "o2_pct": pub_num(r["o2_pct"]),
        "lel_pct": pub_num(r["lel_pct"]),
        "h2s_ppm": pub_num(r["h2s_ppm"]),
        "co_ppm": pub_num(r["co_ppm"]),
        "recorded_at": r["recorded_at"],
        "within_limits": r["within_limits"],
        "created_at": r["created_at"],
    }


def standby_assignment(a):
    return {
        "id": a["id"],
        "permit_id": a["permit_id"],
        "rescuer_id": a["rescuer_id"],
        "standby_start_at": a["standby_start_at"],
        "standby_end_at": a["standby_end_at"],
        "checked_in_at": a["checked_in_at"],
        "checked_out_at": a["checked_out_at"],
        "deployed_at": a["deployed_at"],
        "billable_minutes": a["billable_minutes"],
        "line_amount_cents": a["line_amount_cents"],
        "billed": a["billed"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def incident(i):
    return {
        "id": i["id"],
        "permit_id": i["permit_id"],
        "reported_by": i["reported_by"],
        "severity": i["severity"],
        "kind": i["kind"],
        "description": i["description"],
        "triaged_by": i["triaged_by"],
        "resolved_by": i["resolved_by"],
        "resolution_notes": i["resolution_notes"],
        "escalation_level": i["escalation_level"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def billing_statement(s):
    return {
        "id": s["id"],
        "client_account_id": s["client_account_id"],
        "period_start": s["period_start"],
        "period_end": s["period_end"],
        "status": s["status"],
        "total_cents": s["total_cents"],
        "line_count": s["line_count"],
        "finalized_at": s["finalized_at"],
        "billed_balance_contribution_cents": s["billed_balance_contribution_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def statement_line(l):
    return {
        "id": l["id"],
        "statement_id": l["statement_id"],
        "line_kind": l["line_kind"],
        "reference_permit_id": l["reference_permit_id"],
        "reference_assignment_id": l["reference_assignment_id"],
        "quantity": pub_num(l["quantity"]),
        "unit_rate_cents": pub_num(l["unit_rate_cents"]),
        "amount_cents": l["amount_cents"],
        "description": l["description"],
        "created_at": l["created_at"],
    }
