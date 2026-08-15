"""Entity assertions and domain invariant checkers.

Each assert_*() checks the system-managed common properties plus the
resource's declared field set, using PRD-exact field names.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PLAN_YEAR_STATUSES = ["DRAFT", "OPEN", "SUBMISSIONS_CLOSED", "RECONCILED",
                      "COMMUNICATED", "LOCKED"]
TERRITORY_STATUSES = ["DRAFT", "ACTIVE", "RETIRED"]
RULE_STATUSES = ["ACTIVE", "DISABLED"]
RULE_TYPES = ["NAMED_ACCOUNT", "GEO_SEGMENT"]
SEGMENTS = ["ENTERPRISE", "MID_MARKET", "SMB"]
ASSIGNMENT_SOURCES = ["UNASSIGNED", "NAMED_RULE", "GEO_RULE", "MANUAL_CHANGE",
                      "DISPUTE_RESOLUTION"]
REP_ASSIGNMENT_STATUSES = ["ACTIVE", "ENDED"]
ALLOCATION_STATUSES = ["DRAFT", "APPLIED", "SUPERSEDED", "DISCARDED"]
SUBMISSION_STATUSES = ["SUBMITTED", "WITHDRAWN", "LOCKED_IN"]
RECONCILIATION_STATUSES = ["COMPUTED", "APPLIED", "DISCARDED"]
RECONCILIATION_POLICIES = ["TOP_DOWN_WINS", "BLENDED"]
CREDIT_TRANSITION_POLICIES = ["PRORATE_BY_DAY", "MONTH_SNAPSHOT"]
CHANGE_REQUEST_STATUSES = ["PENDING", "APPROVED", "APPLIED", "REJECTED",
                           "CANCELLED"]
CREDIT_EVENT_TYPES = ["BOOKING", "TRANSFER_OUT", "TRANSFER_IN"]
CREDIT_EVENT_STATUSES = ["POSTED", "REVERSED"]
DISPUTE_STATUSES = ["FILED", "UNDER_REVIEW", "ESCALATED", "RESOLVED_UPHELD",
                    "RESOLVED_OVERRULED", "WITHDRAWN"]
COVERAGE_STATUSES = ["NO_QUOTA", "GAP", "UNDERSTAFFED", "COVERED"]


def _assert_common(data: dict):
    """Every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1: {data.get('version')!r}"


def assert_plan_year(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["company_target_cents"], int)
    assert isinstance(data["productivity_per_rep_cents"], int)
    assert data["reconciliation_policy"] in RECONCILIATION_POLICIES
    assert data["credit_transition_policy"] in CREDIT_TRANSITION_POLICIES
    assert isinstance(data["lock_date"], str)
    assert data["status"] in PLAN_YEAR_STATUSES
    if data["communicated_at"] is not None:
        assert is_iso8601_timestamp(data["communicated_at"])
    if data["locked_at"] is not None:
        assert is_iso8601_timestamp(data["locked_at"])


def assert_territory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    if data["parent_territory_id"] is not None:
        assert is_valid_uuid(data["parent_territory_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["potential_cents"], int)
    assert data["potential_cents"] >= 0
    assert isinstance(data["headcount_capacity"], int)
    assert data["headcount_capacity"] >= 1
    if data["assigned_quota_cents"] is not None:
        assert isinstance(data["assigned_quota_cents"], int)
    if data["final_quota_cents"] is not None:
        assert isinstance(data["final_quota_cents"], int)
    assert data["status"] in TERRITORY_STATUSES


def assert_assignment_rule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert data["rule_type"] in RULE_TYPES
    assert isinstance(data["priority"], int)
    assert is_valid_uuid(data["territory_id"])
    assert data["status"] in RULE_STATUSES
    for f in ("country_code", "state_code", "segment", "named_account_id"):
        assert f in data, f"missing field {f}"


def assert_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str)
    assert data["segment"] in SEGMENTS
    assert isinstance(data["annual_potential_cents"], int)
    assert data["annual_potential_cents"] >= 0
    if data["assigned_territory_id"] is not None:
        assert is_valid_uuid(data["assigned_territory_id"])
    assert data["assignment_source"] in ASSIGNMENT_SOURCES
    if data["assignment_rule_id"] is not None:
        assert is_valid_uuid(data["assignment_rule_id"])


def assert_sales_rep(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["hire_date"], str)


def assert_ramp_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["multipliers"], list)
    assert len(data["multipliers"]) == 12


def assert_rep_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert is_valid_uuid(data["rep_id"])
    assert is_valid_uuid(data["territory_id"])
    if data["ramp_schedule_id"] is not None:
        assert is_valid_uuid(data["ramp_schedule_id"])
    assert isinstance(data["effective_from"], str)
    if data["effective_to"] is not None:
        assert isinstance(data["effective_to"], str)
    assert data["status"] in REP_ASSIGNMENT_STATUSES
    if data["base_quota_cents"] is not None:
        assert isinstance(data["base_quota_cents"], int)
    if data["ramped_quota_cents"] is not None:
        assert isinstance(data["ramped_quota_cents"], int)
    if data["final_quota_cents"] is not None:
        assert isinstance(data["final_quota_cents"], int)
    assert isinstance(data["attainment_cents"], int)
    if data["attainment_pct"] is not None:
        assert isinstance(data["attainment_pct"], (int, float))


def assert_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert is_valid_uuid(data["scope_territory_id"])
    assert isinstance(data["pool_cents"], int)
    assert data["status"] in ALLOCATION_STATUSES
    if data["results"] is not None:
        assert isinstance(data["results"], list)
        for row in data["results"]:
            assert is_valid_uuid(row["territory_id"])
            assert isinstance(row["allocated_cents"], int)


def assert_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert is_valid_uuid(data["territory_id"])
    assert is_valid_uuid(data["submitted_by_rep_id"])
    assert isinstance(data["proposed_quota_cents"], int)
    assert data["status"] in SUBMISSION_STATUSES


def assert_reconciliation_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert data["policy_used"] in RECONCILIATION_POLICIES
    assert data["status"] in RECONCILIATION_STATUSES
    assert isinstance(data["results"], list)
    for row in data["results"]:
        assert is_valid_uuid(row["territory_id"])
        assert isinstance(row["top_down_cents"], int)
        if row["bottom_up_cents"] is not None:
            assert isinstance(row["bottom_up_cents"], int)
        if row["deviation_pct"] is not None:
            assert isinstance(row["deviation_pct"], (int, float))
        assert isinstance(row["final_cents"], int)
        assert isinstance(row["escalated"], bool)


def assert_change_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["from_territory_id"])
    assert is_valid_uuid(data["to_territory_id"])
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["created_by_user_id"], str)
    if data["decided_by_user_id"] is not None:
        assert isinstance(data["decided_by_user_id"], str)
    if data["quota_transfer_cents"] is not None:
        assert isinstance(data["quota_transfer_cents"], int)
    assert data["status"] in CHANGE_REQUEST_STATUSES


def assert_credit_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["rep_id"])
    assert data["event_type"] in CREDIT_EVENT_TYPES
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["booking_date"], str)
    if data["source_change_request_id"] is not None:
        assert is_valid_uuid(data["source_change_request_id"])
    if data["parent_credit_event_id"] is not None:
        assert is_valid_uuid(data["parent_credit_event_id"])
    assert data["status"] in CREDIT_EVENT_STATUSES


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_year_id"])
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["claimant_territory_id"])
    assert is_valid_uuid(data["filed_by_rep_id"])
    assert isinstance(data["reason"], str)
    assert isinstance(data["filed_date"], str)
    assert data["status"] in DISPUTE_STATUSES


def get_results_row(run: dict, territory_id: str) -> dict:
    """Fetch one territory row out of a reconciliation run's results."""
    for row in run["results"]:
        if row["territory_id"] == territory_id:
            return row
    raise AssertionError(
        f"No results row for territory {territory_id} in run {run['id']}")


def get_coverage_row(report: dict, territory_id: str) -> dict:
    """Fetch one territory row out of a coverage report's rows."""
    for row in report["rows"]:
        if row["territory_id"] == territory_id:
            return row
    raise AssertionError(
        f"No coverage row for territory {territory_id} "
        f"in report for plan {report.get('plan_year_id')}")
