"""Entity assertions and domain invariant checkers (PRD §2.5 common properties)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert isinstance(data["school_year"], str) and data["school_year"]
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] > 0
    assert isinstance(data["benefit_threshold_minutes"], int)
    assert isinstance(data["benefit_surcharge_pct"], (int, float))
    assert isinstance(data["travel_buffer_minutes"], int)
    assert isinstance(data["committed_cost_cents"], int)
    assert isinstance(data["settled_cost_cents"], int)
    assert isinstance(data["cost_balance_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RECONCILING", "CLOSED")


def assert_building(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert isinstance(data["hardship_factor"], (int, float))


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["building_id"], str)
    assert isinstance(data["student_ref"], str) and data["student_ref"]
    assert data["iep_service_level"] in ("ONE_TO_ONE", "SHARED_SUPPORT", "TRANSITIONAL")
    assert isinstance(data["iep_minutes_per_week"], int) and data["iep_minutes_per_week"] > 0
    assert data["required_qualification"] in ("NONE", "BEHAVIOR_SUPPORT", "MEDICAL_DELEGATION", "SIGN_LANGUAGE")
    assert data["status"] in ("REGISTERED", "ACTIVE_IEP", "SERVICE_CHANGE_PENDING", "EXITED")


def assert_para(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["home_building_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["base_hourly_wage_cents"], int) and data["base_hourly_wage_cents"] > 0
    assert isinstance(data["contracted_max_weekly_minutes"], int) and data["contracted_max_weekly_minutes"] > 0
    assert isinstance(data["hire_date"], str) and data["hire_date"]
    assert isinstance(data["qualifications"], list)
    assert isinstance(data["weekly_scheduled_minutes"], int)
    assert isinstance(data["benefit_eligible"], bool)
    assert data.get("confirmed_benefit_eligible") in (True, False, None)
    assert isinstance(data["benefit_variance_cents"], int)
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "SEPARATED")


def assert_change_order(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["student_id"], str)
    assert data["change_type"] in ("MINUTES_CHANGE", "QUALIFICATION_CHANGE", "BUILDING_TRANSFER", "EXIT")
    assert isinstance(data["reason"], str)
    assert data["status"] in ("FILED", "APPROVED", "EFFECTIVE", "CANCELLED")


def assert_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["para_id"], str)
    assert isinstance(data["building_id"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["days_of_week"], list) and len(data["days_of_week"]) >= 1
    assert isinstance(data["daily_start_minute"], int)
    assert isinstance(data["daily_end_minute"], int)
    assert data["daily_end_minute"] > data["daily_start_minute"]
    assert data["service_level_snapshot"] in ("ONE_TO_ONE", "SHARED_SUPPORT", "TRANSITIONAL")
    assert data["required_qualification_snapshot"] in ("NONE", "BEHAVIOR_SUPPORT", "MEDICAL_DELEGATION", "SIGN_LANGUAGE")
    assert isinstance(data["base_wage_snapshot_cents"], int)
    assert isinstance(data["daily_cost_cents"], int)
    assert isinstance(data["projected_weekly_cost_cents"], int)
    assert isinstance(data["weekly_minutes"], int)
    assert data.get("end_reason") in (None, "SERVICE_CHANGED", "COORDINATOR_ENDED", "PLAN_CLOSED")
    assert data["status"] in ("PROPOSED", "QUALIFICATION_VERIFIED", "ACTIVE", "SUSPENDED", "ENDED")
    assert data["funding_status"] in ("PROVISIONALLY_FUNDED", "UNFUNDED", "FUNDED", "SETTLED")


def assert_coverage_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["building_id"], str)
    assert isinstance(data["coverage_date"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "LOCKED", "RECONCILED")
    assert data["coverage_posture"] in ("OPEN", "GAPS_OPEN", "FROZEN")


def assert_absence(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["assignment_id"], str)
    assert isinstance(data["coverage_plan_id"], str)
    assert isinstance(data["absence_date"], str)
    assert isinstance(data["absence_minutes"], int)
    assert isinstance(data["reason"], str)
    assert isinstance(data["reported_by_role"], str)
    assert isinstance(data["declined_para_ids"], list)
    assert data["status"] in ("REPORTED", "BACKFILL_PENDING", "ESCALATED", "COVERED", "CANCELLED", "UNCOVERED")


def assert_backfill(data: dict):
    _assert_common(data)
    assert isinstance(data["absence_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["substitute_para_id"], str)
    assert isinstance(data["coverage_minutes"], int)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "CANCELLED", "COMPLETED")


def assert_timesheet(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["para_id"], str)
    assert isinstance(data["assignment_id"], str)
    assert isinstance(data["work_date"], str)
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert isinstance(data["minutes_worked"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED")


def assert_evaluation(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["para_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["professionalism_score"] in (1, 2, 3, 4, 5)
    assert data["instructional_support_score"] in (1, 2, 3, 4, 5)
    assert isinstance(data["comments"], str)
    assert isinstance(data["created_by_user_id"], str)
    assert data.get("countersigned_by_user_id") is None or isinstance(data["countersigned_by_user_id"], str)
    assert data.get("resolution_note") is None or isinstance(data["resolution_note"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "COUNTERSIGNED", "ACKNOWLEDGED", "DISPUTED", "RESOLVED")


def assert_formula(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["base_grant_cents"], int) and data["base_grant_cents"] >= 0
    assert isinstance(data["per_minute_rate_cents"], int) and data["per_minute_rate_cents"] > 0
    assert isinstance(data["weight_one_to_one"], (int, float))
    assert isinstance(data["weight_shared_support"], (int, float))
    assert isinstance(data["weight_transitional"], (int, float))
    assert isinstance(data["period_weeks"], int) and data["period_weeks"] > 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_funding_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["building_id"], str)
    assert isinstance(data["formula_id"], str)
    assert isinstance(data["period_label"], str)
    assert isinstance(data["provisional_amount_cents"], int)
    assert data.get("final_amount_cents") is None or isinstance(data["final_amount_cents"], int)
    assert data.get("variance_cents") is None or isinstance(data["variance_cents"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED")


def assert_plan_ledger_invariants(plan: dict):
    """PRD §2.9: cost_balance_cents = total_budget_cents - committed - settled."""
    assert plan["cost_balance_cents"] == (
        plan["total_budget_cents"] - plan["committed_cost_cents"] - plan["settled_cost_cents"]
    ), (
        f"ledger imbalance: balance {plan['cost_balance_cents']} != "
        f"{plan['total_budget_cents']} - {plan['committed_cost_cents']} - {plan['settled_cost_cents']}"
    )
