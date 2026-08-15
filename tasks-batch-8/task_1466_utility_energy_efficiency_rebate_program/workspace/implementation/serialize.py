"""Entity serializers — exact public field sets per scaffold entity table."""


def program_year_out(r):
    return {
        "id": r["id"],
        "program_code": r["program_code"],
        "program_year_label": r["program_year_label"],
        "budget_cap_cents": r["budget_cap_cents"],
        "savings_goal_kwh": r["savings_goal_kwh"],
        "committed_cents": r["committed_cents"],
        "paid_cents": r["paid_cents"],
        "reported_kwh": r["reported_kwh"],
        "adjusted_kwh": r["adjusted_kwh"],
        "goal_attainment_pct": r["goal_attainment_pct"],
        "status": r["status"],
        "opened_at": r["opened_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def measure_out(r):
    return {
        "id": r["id"],
        "program_year_id": r["program_year_id"],
        "measure_code": r["measure_code"],
        "measure_name": r["measure_name"],
        "base_rate_cents": r["base_rate_cents"],
        "deemed_kwh_per_unit": r["deemed_kwh_per_unit"],
        "requires_post_inspection": r["requires_post_inspection"],
        "is_active": r["is_active"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def trade_ally_out(r):
    return {
        "id": r["id"],
        "ally_name": r["ally_name"],
        "license_number": r["license_number"],
        "performance_score": r["performance_score"],
        "standing_tier": r["standing_tier"],
        "enroll_status": r["enroll_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def application_out(r):
    return {
        "id": r["id"],
        "program_year_id": r["program_year_id"],
        "trade_ally_id": r["trade_ally_id"],
        "customer_account_number": r["customer_account_number"],
        "service_address": r["service_address"],
        "invoice_number": r["invoice_number"],
        "invoice_date": r["invoice_date"],
        "incentive_total_cents": r["incentive_total_cents"],
        "claimed_kwh": r["claimed_kwh"],
        "final_kwh": r["final_kwh"],
        "inspection_required": r["inspection_required"],
        "risk_score": r["risk_score"],
        "auto_flag_status": r["auto_flag_status"],
        "status": r["status"],
        "submitted_at": r["submitted_at"],
        "verified_by": r["verified_by"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def line_item_out(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "measure_id": r["measure_id"],
        "quantity": r["quantity"],
        "pacing_tier_at_submit": r["pacing_tier_at_submit"],
        "incentive_cents": r["incentive_cents"],
        "claimed_kwh": r["claimed_kwh"],
        "measured_kwh": r["measured_kwh"],
        "final_kwh": r["final_kwh"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def savings_claim_out(r):
    return {
        "id": r["id"],
        "line_item_id": r["line_item_id"],
        "claim_method": r["claim_method"],
        "pre_annual_kwh": r["pre_annual_kwh"],
        "post_annual_kwh": r["post_annual_kwh"],
        "computed_kwh": r["computed_kwh"],
        "created_at": r["created_at"],
    }


def inspection_out(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "inspection_kind": r["inspection_kind"],
        "scheduled_on": r["scheduled_on"],
        "completed_on": r["completed_on"],
        "outcome": r["outcome"],
        "fail_reason": r["fail_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def adjustment_out(r):
    return {
        "id": r["id"],
        "program_year_id": r["program_year_id"],
        "realization_rate_pct": r["realization_rate_pct"],
        "effective_on": r["effective_on"],
        "notes": r["notes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def fraud_flag_out(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "flag_kind": r["flag_kind"],
        "weight": r["weight"],
        "detail": r["detail"],
        "created_at": r["created_at"],
    }
