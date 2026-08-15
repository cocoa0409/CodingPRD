"""Entity assertions and domain invariant checkers (PRD §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_STUDY_STATUSES = ["DRAFT", "SUBMITTED", "ADOPTED", "SUPERSEDED", "WITHDRAWN"]
_STUDY_TYPES = ["FULL", "UPDATE_WITH_VISIT", "UPDATE_NO_VISIT"]
_PLAN_TYPES = ["BASELINE", "THRESHOLD", "FULL"]
_PLAN_STATUSES = ["DRAFT", "RECOMMENDED", "SELECTED", "RETIRED"]
_COMPONENT_STATUSES = ["ACTIVE", "RETIRED"]
_COMPONENT_CATEGORIES = ["ROOFING", "PAVING", "MECHANICAL", "EXTERIOR",
                         "INTERIOR", "RECREATION", "OTHER"]
_VISIT_STATUSES = ["SCHEDULED", "COMPLETED"]
_APPROVAL_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "REVERSED"]
_RECONCILIATION_STATUSES = ["UNRECONCILED", "MATCHED", "VARIANCE_ACCEPTED",
                            "NOT_APPLICABLE"]
_EXPENDITURE_KINDS = ["PLANNED_REPLACEMENT", "UNPLANNED_REPAIR"]
_DISCLOSURE_TYPES = ["ADOPTION_SUMMARY", "ANNUAL_STATEMENT"]
_DISCLOSURE_STATUSES = ["PENDING", "DISTRIBUTED", "VOIDED"]
_COMPLIANCE_STATUSES = ["COMPLIANCE_UNKNOWN", "COMPLIANT", "NON_COMPLIANT"]


def _assert_common_fields(data: dict):
    """PRD §2.7: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_state_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["min_percent_funded_pct"], (int, float))
    assert 0 <= data["min_percent_funded_pct"] <= 100
    assert isinstance(data["allowed_plan_types"], list) and data["allowed_plan_types"]
    assert all(t in _PLAN_TYPES for t in data["allowed_plan_types"])
    assert isinstance(data["site_visit_interval_years"], int)
    assert isinstance(data["disclosure_deadline_days"], int)
    assert isinstance(data["annual_update_required"], bool)


def assert_association(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["fiscal_year_end_month"], int)
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert isinstance(data["reserve_cash_balance_cents"], int)
    assert isinstance(data["current_annual_contribution_cents"], int)
    assert data["last_annual_update_fiscal_year"] is None or \
        isinstance(data["last_annual_update_fiscal_year"], int)
    assert data["statutory_compliance_status"] in _COMPLIANCE_STATUSES
    assert data["next_site_visit_due_date"] is None or \
        isinstance(data["next_site_visit_due_date"], str)
    assert isinstance(data["annual_update_overdue"], bool)


def assert_study(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["association_id"], str)
    assert isinstance(data["fiscal_year"], int)
    assert data["study_type"] in _STUDY_TYPES
    assert isinstance(data["inflation_rate"], (int, float))
    assert data["inflation_rate"] >= 0
    assert isinstance(data["interest_rate"], (int, float))
    assert data["interest_rate"] >= 0
    assert data["status"] in _STUDY_STATUSES
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date_exclusive"], str)
    assert isinstance(data["fully_funded_balance_cents"], int)
    assert data["fully_funded_balance_cents"] >= 0
    assert isinstance(data["percent_funded"], (int, float))
    assert data["adopted_at"] is None or isinstance(data["adopted_at"], str)
    assert data["adopted_plan_id"] is None or isinstance(data["adopted_plan_id"], str)


def assert_component(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in _COMPONENT_CATEGORIES
    assert isinstance(data["useful_life_years"], int)
    assert data["useful_life_years"] >= 1
    assert isinstance(data["remaining_useful_life_years"], int)
    assert 0 <= data["remaining_useful_life_years"] <= data["useful_life_years"]
    assert isinstance(data["current_replacement_cost_cents"], int)
    assert data["current_replacement_cost_cents"] > 0
    assert isinstance(data["is_included_in_funding"], bool)
    assert data["status"] in _COMPONENT_STATUSES
    assert isinstance(data["actual_expenditure_cents"], int)
    assert data["last_replaced_fiscal_year"] is None or \
        isinstance(data["last_replaced_fiscal_year"], int)


def assert_funding_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str)
    assert data["plan_type"] in _PLAN_TYPES
    assert data["status"] in _PLAN_STATUSES
    assert isinstance(data["starting_cash_cents"], int)
    assert isinstance(data["annual_contribution_cents"], int)
    assert data["annual_contribution_cents"] >= 0
    assert data["threshold_floor_cents"] is None or \
        isinstance(data["threshold_floor_cents"], int)
    assert isinstance(data["computed_at"], str)


def assert_site_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["association_id"], str)
    assert isinstance(data["visit_date"], str)
    assert data["status"] in _VISIT_STATUSES
    assert data["completed_at"] is None or isinstance(data["completed_at"], str)


def assert_expenditure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["association_id"], str)
    assert isinstance(data["component_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert isinstance(data["incurred_date"], str)
    assert data["kind"] in _EXPENDITURE_KINDS
    assert isinstance(data["fiscal_year"], int)
    assert data["approval_status"] in _APPROVAL_STATUSES
    assert data["reconciliation_status"] in _RECONCILIATION_STATUSES
    for field in ("planned_chronological_cents", "variance_chronological_cents",
                  "planned_forward_cents", "variance_forward_cents",
                  "component_rul_before_years"):
        assert data[field] is None or isinstance(data[field], int), \
            f"{field} must be null or an integer"
    assert data["approved_at"] is None or isinstance(data["approved_at"], str)


def assert_disclosure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str)
    assert data["disclosure_type"] in _DISCLOSURE_TYPES
    assert data["status"] in _DISCLOSURE_STATUSES
    assert isinstance(data["due_date"], str)
    assert data["distributed_at"] is None or isinstance(data["distributed_at"], str)
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["allocation_lines"], list)


def line_share_cents(line: dict) -> int:
    """Extract the per-line share from an allocation line.

    The PRD pins the line VALUES (the floored share plus any largest-remainder
    cent) and their ordering (created_at ascending), but does not name the
    per-line keys — so the share is recovered as the single integer value on
    the line rather than by a hard-coded key.
    """
    ints = [v for v in line.values()
            if isinstance(v, int) and not isinstance(v, bool)]
    assert len(ints) == 1, \
        f"allocation line must carry exactly one integer share value, got {line}"
    return ints[0]
