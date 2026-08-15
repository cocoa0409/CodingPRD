"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

UNIT_STATUSES = ["OCCUPIED", "NOTICE", "IN_TURN", "READY"]
TURN_STATUSES = ["OPEN", "SCOPED", "IN_PROGRESS", "REWORK", "READY", "CLOSED",
                 "CANCELLED"]
SCOPE_CATEGORIES = ["REPAIR", "PAINT", "CARPET", "CLEAN", "APPLIANCE",
                    "FIXTURE", "OTHER"]
SCOPE_ITEM_STATUSES = ["PLANNED", "PENDING_APPROVAL", "SCHEDULED", "COMPLETED",
                       "FAILED", "VOIDED", "REJECTED"]
ASSIGNMENT_STATUSES = ["SCHEDULED", "ACCEPTED", "COMPLETED", "DECLINED",
                       "CANCELLED"]
COMMITMENT_STATUSES = ["ACTIVE", "AT_RISK", "FULFILLED", "BREACHED",
                       "CANCELLED"]
CLASSIFICATIONS = ["EXPENSE", "CAPITAL"]
APPROVAL_TIERS = ["NONE", "PM", "RM"]
VENDOR_TRADES = ["REPAIR", "PAINT", "CARPET", "CLEAN"]
REPLACEMENT_POLICIES = ["PERCENT_OF_REPLACE", "COST_PER_YEAR"]
DECISIONS = ["REPAIR", "REPLACE"]


def assert_common_fields(data: dict, what: str = "resource"):
    """System-managed fields carried by every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{what}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{what}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_immutable_record(data: dict, what: str = "record"):
    """Inspections and ReplacementDecisions carry id + created_at only (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what}.created_at must be ISO 8601"
    )
    assert "version" not in data, f"{what} must not carry version (immutable)"
    assert "updated_at" not in data, f"{what} must not carry updated_at (immutable)"


def assert_property(data: dict):
    assert_common_fields(data, "Property")
    assert isinstance(data["name"], str) and data["name"]
    for field in ("days_to_ready_target", "pm_threshold_bp", "rm_threshold_bp",
                  "capital_threshold_cents", "benchmark_turn_count",
                  "avg_booked_expense_cents", "avg_days_to_ready"):
        assert isinstance(data[field], int), f"Property.{field} must be int"
    assert data["replacement_policy"] in REPLACEMENT_POLICIES


def assert_unit(data: dict):
    assert_common_fields(data, "Unit")
    assert is_valid_uuid(data.get("property_id", "")), "Unit.property_id UUID"
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["square_feet"], int)
    assert data["status"] in UNIT_STATUSES


def assert_turn(data: dict):
    assert_common_fields(data, "Turn")
    assert is_valid_uuid(data.get("unit_id", "")), "Turn.unit_id UUID"
    assert isinstance(data["notice_date"], str)
    assert isinstance(data["move_out_date"], str)
    assert data["status"] in TURN_STATUSES
    for field in ("approved_budget_cents", "estimated_cost_cents",
                  "expense_actual_cents", "capital_actual_cents",
                  "total_actual_cents", "booked_expense_cents"):
        assert isinstance(data[field], int), f"Turn.{field} must be int cents"
    for field in ("started_on", "target_ready_date", "actual_ready_date",
                  "projected_ready_date"):
        assert data[field] is None or isinstance(data[field], str), (
            f"Turn.{field} must be null or an ISO date"
        )


def assert_scope_item(data: dict):
    assert_common_fields(data, "ScopeItem")
    assert is_valid_uuid(data.get("turn_id", "")), "ScopeItem.turn_id UUID"
    assert data["category"] in SCOPE_CATEGORIES
    assert isinstance(data["description"], str)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["actual_cost_cents"] is None or isinstance(
        data["actual_cost_cents"], int)
    assert data["classification"] in CLASSIFICATIONS
    assert isinstance(data["sequence_rank"], int)
    assert data["approval_tier"] in APPROVAL_TIERS
    assert data["status"] in SCOPE_ITEM_STATUSES
    assert data["rework_of_item_id"] is None or is_valid_uuid(
        data["rework_of_item_id"])


def assert_vendor(data: dict):
    assert_common_fields(data, "Vendor")
    assert isinstance(data["name"], str) and data["name"]
    assert data["trade"] in VENDOR_TRADES
    assert isinstance(data["open_assignment_count"], int)
    assert data["open_assignment_count"] >= 0


def assert_vendor_assignment(data: dict):
    assert_common_fields(data, "VendorAssignment")
    assert is_valid_uuid(data.get("scope_item_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["actual_cost_cents"] is None or isinstance(
        data["actual_cost_cents"], int)


def assert_inspection(data: dict):
    assert_immutable_record(data, "Inspection")
    assert data["result"] in ("PASS", "FAIL")


def assert_replacement_decision(data: dict):
    assert_immutable_record(data, "ReplacementDecision")
    assert is_valid_uuid(data.get("scope_item_id", ""))
    for field in ("repair_estimate_cents", "replace_estimate_cents",
                  "repair_life_years", "remaining_life_years"):
        assert isinstance(data[field], int), f"ReplacementDecision.{field} int"
    assert data["decision"] in DECISIONS
    assert data["policy_applied"] in REPLACEMENT_POLICIES
    assert data["resulting_classification"] in CLASSIFICATIONS


def assert_lease_commitment(data: dict):
    assert_common_fields(data, "LeaseCommitment")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["applicant_name"], str) and data["applicant_name"]
    assert isinstance(data["committed_delivery_date"], str)
    assert data["status"] in COMMITMENT_STATUSES


def assert_turn_money_partition(data: dict):
    """PRD §2.7: every booked cent lands in precisely one bucket."""
    assert data["total_actual_cents"] == (
        data["expense_actual_cents"] + data["capital_actual_cents"]
    ), (
        f"partition invariant violated: total {data['total_actual_cents']} != "
        f"expense {data['expense_actual_cents']} + "
        f"capital {data['capital_actual_cents']}"
    )
