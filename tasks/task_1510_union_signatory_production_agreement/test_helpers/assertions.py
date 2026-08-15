"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_producer_company(data: dict):
    _assert_common_fields(data, "ProducerCompany")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]
    assert data["status"] in ("PENDING", "SIGNATORY", "SUSPENDED")


def assert_signatory_application(data: dict):
    _assert_common_fields(data, "SignatoryApplication")
    assert data["requested_agreement_scope"] in ("THEATRICAL", "TELEVISION", "NEW_MEDIA")
    assert isinstance(data["estimated_slate_budget_cents"], int)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert isinstance(data["review_rounds"], int) and 0 <= data["review_rounds"] <= 3


def assert_production(data: dict):
    _assert_common_fields(data, "Production")
    assert isinstance(data["title"], str) and data["title"]
    assert data["agreement_tier"] in (
        "ULTRA_LOW_BUDGET", "MODIFIED_LOW_BUDGET", "LOW_BUDGET", "BASIC",
    )
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["status"] in (
        "REGISTERED", "STAFFING", "IN_PRODUCTION", "SUSPENDED", "WRAPPED", "CLOSED",
    )
    assert data["compliance_posture"] in ("CLEAR", "RESTRICTED", "FROZEN")


def assert_bond(data: dict):
    _assert_common_fields(data, "Bond")
    assert isinstance(data["amount_required_cents"], int) and data["amount_required_cents"] > 0
    assert isinstance(data["amount_held_cents"], int) and data["amount_held_cents"] >= 0
    assert isinstance(data["total_posted_cents"], int) and data["total_posted_cents"] >= 0
    assert isinstance(data["total_released_cents"], int) and data["total_released_cents"] >= 0
    assert isinstance(data["total_forfeited_cents"], int) and data["total_forfeited_cents"] >= 0
    assert data["status"] in ("PENDING", "POSTED", "UNDERFUNDED", "RELEASED", "FORFEITED")


def assert_bond_ledger_conservation(bond: dict):
    """PRD §3.2 invariant: amount_held_cents is always the posted total minus
    the released total minus the forfeited total."""
    assert bond["amount_held_cents"] == (
        bond["total_posted_cents"] - bond["total_released_cents"] - bond["total_forfeited_cents"]
    ), (
        f"Bond ledger drift: held {bond['amount_held_cents']} != "
        f"posted {bond['total_posted_cents']} - released {bond['total_released_cents']} "
        f"- forfeited {bond['total_forfeited_cents']}"
    )


def assert_crew_assignment(data: dict):
    _assert_common_fields(data, "CrewAssignment")
    assert isinstance(data["crew_member_ref"], str) and data["crew_member_ref"]
    assert data["department"] in ("CAMERA", "GRIP_ELECTRIC", "SOUND")
    assert data["classification"] in (
        "DIRECTOR_OF_PHOTOGRAPHY", "CAMERA_OPERATOR", "GAFFER",
        "KEY_GRIP", "BOOM_OPERATOR", "SOUND_MIXER",
    )
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert data["status"] in ("HIRED", "ACTIVE", "WRAPPED", "TERMINATED")


def assert_work_day_log(data: dict):
    _assert_common_fields(data, "WorkDayLog")
    assert isinstance(data["work_date"], str) and data["work_date"]
    assert 0 <= data["call_time_minutes"] < 1440
    assert 0 <= data["wrap_time_minutes"] < 1440
    assert data["wrap_time_minutes"] > data["call_time_minutes"]
    assert isinstance(data["meal_breaks"], list)
    assert isinstance(data["meal_penalty_units"], int) and data["meal_penalty_units"] >= 0
    assert isinstance(data["meal_penalty_cents"], int) and data["meal_penalty_cents"] >= 0
    assert isinstance(data["turnaround_violation"], bool)
    assert isinstance(data["turnaround_penalty_cents"], int) and data["turnaround_penalty_cents"] >= 0
    assert data["penalty_cents"] == data["meal_penalty_cents"] + data["turnaround_penalty_cents"], (
        "penalty_cents must be the sum of the meal and turnaround penalties (PRD §3.5)"
    )
    assert data["status"] in ("OPEN", "SUBMITTED", "VOIDED")


def assert_grievance(data: dict):
    _assert_common_fields(data, "Grievance")
    assert data["category"] in ("WORK_RULE", "PAY", "CLASSIFICATION", "SAFETY", "OTHER")
    assert isinstance(data["incident_date"], str) and data["incident_date"]
    assert isinstance(data["description"], str)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["proposal_status"] in ("NONE", "OPEN", "SUPERSEDED", "ACCEPTED", "REJECTED")
    assert isinstance(data["settlement_agreed_cents"], int) and data["settlement_agreed_cents"] >= 0
    assert isinstance(data["settlement_paid_cents"], int)
    assert data["status"] in (
        "FILED", "INVESTIGATING", "PROPOSED_SETTLEMENT", "ESCALATED",
        "RESOLVED", "DECIDED", "CLOSED",
    )


def assert_contribution_report(data: dict):
    _assert_common_fields(data, "ContributionReport")
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["work_day_log_ids"], list)
    assert isinstance(data["provisional_gross_wages_cents"], int)
    assert isinstance(data["provisional_contributions_due_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_audit(data: dict):
    _assert_common_fields(data, "Audit")
    assert isinstance(data["scope_period_indices"], list) and data["scope_period_indices"]
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert isinstance(data["assessment_paid_cents"], int) and data["assessment_paid_cents"] >= 0
    assert data["status"] in ("OPEN", "FINDINGS_ISSUED", "CLOSED")


def assert_force_majeure_event(data: dict):
    _assert_common_fields(data, "ForceMajeureEvent")
    assert data["event_type"] in ("STRIKE", "NATURAL_DISASTER", "OTHER")
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert data["status"] in ("ACTIVE", "LIFTED")
