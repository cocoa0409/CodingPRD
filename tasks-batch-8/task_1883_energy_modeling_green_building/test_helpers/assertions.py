"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LEVELS = ["NONE", "CERTIFIED", "SILVER", "GOLD", "PLATINUM"]
CERTIFIED_LEVELS = ["CERTIFIED", "SILVER", "GOLD", "PLATINUM"]


def _assert_common(data: dict):
    """Common server-managed properties present on every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_team_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["specialty"] in ["MANAGEMENT", "MODELING", "DOCUMENTATION", "COMMISSIONING"]
    assert isinstance(data["is_independent"], bool)


def assert_certification_project(data: dict):
    _assert_common(data)
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["rating_system"] in ["LEED_BD_C", "LEED_ID_C", "LEED_O_M"]
    assert data["compliance_path"] in ["PRESCRIPTIVE", "PERFORMANCE"]
    assert isinstance(data["gross_floor_area_sqft"], int) and data["gross_floor_area_sqft"] > 0
    assert data["target_level"] in CERTIFIED_LEVELS
    assert isinstance(data["fee_budget_cents"], int) and data["fee_budget_cents"] >= 0
    assert isinstance(data["administrator_id"], str) and data["administrator_id"]
    assert data["status"] in [
        "REGISTERED", "STRATEGY_LOCKED", "DESIGN_SUBMITTED", "DESIGN_REVIEWED",
        "CONSTRUCTION_SUBMITTED", "CONSTRUCTION_REVIEWED", "CERTIFIED",
        "PERFORMANCE_REPORTING", "RECERTIFICATION_REVIEW", "LAPSED", "DENIED",
    ]
    assert isinstance(data["fee_balance_cents"], int)
    assert isinstance(data["points_pursued_total"], int)
    assert isinstance(data["points_awarded_total"], int)
    assert data["projected_level"] in LEVELS
    assert data["conservative_level"] in LEVELS
    assert isinstance(data["prerequisites_satisfied"], bool)
    assert data.get("certified_level") is None or data["certified_level"] in CERTIFIED_LEVELS
    assert data.get("certified_at") is None or is_iso8601_timestamp(data["certified_at"])
    assert isinstance(data["plaque_marketing_rights_granted"], bool)


def assert_credit_library_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["credit_code"], str) and data["credit_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["category"] in [
        "ENERGY_ATMOSPHERE", "MATERIALS", "INDOOR_ENVIRONMENT",
        "WATER", "SUSTAINABLE_SITES", "INTEGRATIVE",
    ]
    assert isinstance(data["points_possible"], int) and data["points_possible"] >= 0
    assert isinstance(data["is_prerequisite"], bool)
    assert data["phase_eligibility"] in ["DESIGN", "CONSTRUCTION", "BOTH"]
    assert isinstance(data["requires_energy_model"], bool)


def assert_energy_model(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["model_type"] in ["BASELINE", "PROPOSED"]
    assert data["modeling_standard"] in ["ASHRAE_90_1_2016", "ASHRAE_90_1_2019"]
    assert isinstance(data["annual_energy_cost_modeled_cents"], int)
    assert data["annual_energy_cost_modeled_cents"] > 0
    assert isinstance(data["annual_energy_cost_confirmed_only_cents"], int)
    assert data["annual_energy_cost_confirmed_only_cents"] > 0
    assert isinstance(data["includes_unconfirmed_measures"], bool)
    assert isinstance(data["version_index"], int) and data["version_index"] >= 1
    assert isinstance(data["created_by"], str) and data["created_by"]
    assert data["status"] in ["DRAFT", "LOCKED", "SUPERSEDED"]
    assert data.get("improvement_pct_provisional") is None or isinstance(
        data["improvement_pct_provisional"], (int, float))
    assert data.get("improvement_pct_final") is None or isinstance(
        data["improvement_pct_final"], (int, float))


def assert_credit_attempt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("credit_library_entry_id", ""))
    assert isinstance(data["credit_code"], str) and data["credit_code"]
    assert isinstance(data["points_possible"], int) and data["points_possible"] >= 0
    assert isinstance(data["is_prerequisite"], bool)
    assert data["phase"] in ["DESIGN", "CONSTRUCTION"]
    assert isinstance(data["documentation_owner_id"], str) and data["documentation_owner_id"]
    assert data.get("pinned_proposed_model_id") is None or isinstance(
        data["pinned_proposed_model_id"], str)
    assert isinstance(data["has_stale_model_pin"], bool)
    assert data.get("raw_points_earned") is None or isinstance(
        data["raw_points_earned"], (int, float))
    assert data.get("points_awarded") is None or isinstance(data["points_awarded"], int)
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 0
    assert data["status"] in [
        "SELECTED", "DOCUMENTATION_IN_PROGRESS", "READY_FOR_SUBMITTAL", "SUBMITTED",
        "UNDER_REVIEW", "CLARIFICATION_REQUESTED", "RESUBMITTED", "AWARDED",
        "DENIED", "APPEALED", "DROPPED",
    ]


def assert_review_comment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("credit_attempt_id", ""))
    assert isinstance(data["round"], int) and data["round"] >= 0
    assert data["severity"] in ["CLARIFICATION", "DEFICIENCY"]
    assert isinstance(data["comment_text"], str) and data["comment_text"]
    assert data.get("response_text") is None or isinstance(data["response_text"], str)
    assert data["status"] in ["OPEN", "ADDRESSED", "REOPENED", "ACCEPTED"]


def assert_commissioning_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["task_type"] in [
        "OPR_DOCUMENT", "CX_PLAN", "FUNCTIONAL_TESTING", "SYSTEMS_MANUAL", "CX_REPORT",
    ]
    assert isinstance(data["agent_id"], str) and data["agent_id"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["is_prerequisite_linked"], bool)
    assert data.get("outcome") is None or data["outcome"] in ["PASSED", "FAILED"]
    assert data.get("result_notes") is None or isinstance(data["result_notes"], str)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED"]


def assert_incentive_program(data: dict):
    _assert_common(data)
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["incentive_type"] in ["TAX_CREDIT", "GRANT", "UTILITY_REBATE"]
    assert isinstance(data["benefit_amount_cents"], int) and data["benefit_amount_cents"] > 0
    assert data["minimum_certification_level"] in CERTIFIED_LEVELS
    assert isinstance(data["is_combinable"], bool)


def assert_project_incentive(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("incentive_program_id", ""))
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 0
    assert data["status"] in ["APPLIED", "APPROVED", "DISBURSED"]


def assert_cost_premium_analysis(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["incremental_construction_cost_cents"], int)
    assert data["incremental_construction_cost_cents"] > 0
    assert isinstance(data["annual_energy_savings_cents"], int)
    assert isinstance(data["incentive_total_cents"], int)
    assert isinstance(data["net_cost_premium_cents"], int)
    assert isinstance(data["simple_payback_years"], (int, float))
    assert isinstance(data["analysis_version"], int) and data["analysis_version"] >= 1


def assert_performance_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data["actual_annual_energy_cost_cents"], int)
    assert data["actual_annual_energy_cost_cents"] > 0
    assert isinstance(data["performance_gap_pct"], (int, float))
    assert isinstance(data["within_tolerance"], bool)
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]


# ─── Domain invariants (PRD §3.7 pinned evaluation order) ──

def assert_analysis_invariants(data: dict):
    """The cost premium analysis chain: incentive total never exceeds the cap,
    and net premium is incremental cost minus the incentive total (PRD §3.7)."""
    cap = int(0.40 * data["incremental_construction_cost_cents"])
    assert 0 <= data["incentive_total_cents"] <= cap, (
        f"incentive_total_cents {data['incentive_total_cents']} outside [0, cap {cap}]"
    )
    assert data["net_cost_premium_cents"] == (
        data["incremental_construction_cost_cents"] - data["incentive_total_cents"]
    ), "net_cost_premium_cents must equal incremental cost minus incentive total"
