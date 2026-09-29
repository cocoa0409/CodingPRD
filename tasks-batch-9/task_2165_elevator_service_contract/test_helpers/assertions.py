"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CONTRACT_STATUSES = [
    "DRAFT",
    "ACTIVE",
    "SERVICE_ALERT",
    "UNDER_RENEGOTIATION",
    "TERMINATED",
]
AVAILABILITY_STATES = [
    "IN_SERVICE",
    "OUT_OF_SERVICE",
    "UNDER_MODERNIZATION",
    "DECOMMISSIONED",
]
COMPLIANCE_STATES = [
    "CERTIFIED",
    "INSPECTION_DUE",
    "RED_TAGGED",
    "CERTIFICATE_EXPIRED",
]
VISIT_STATUSES = [
    "SCHEDULED",
    "PERFORMED",
    "VERIFIED",
    "DISPUTED",
    "REJECTED",
    "MISSED",
]
CALLBACK_STATUSES = ["REPORTED", "ESCALATED", "ON_SITE", "CLEARED", "CANCELLED"]
INSPECTION_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
CERTIFICATE_STATES = ["NONE", "ISSUED", "POSTED", "EXPIRED", "SUPERSEDED"]
PROJECT_STATUSES = [
    "PLANNED",
    "APPROVED",
    "IN_PROGRESS",
    "AT_RISK",
    "COMPLETE",
    "CANCELLED",
]
WINDOW_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED", "RESCHEDULE_REQUIRED"]
PART_LIFECYCLE_STATES = ["ACTIVE", "OBSOLETE", "DISCONTINUED"]
PART_ORDER_STATUSES = ["ORDERED", "SUBSTITUTED", "RECEIVED", "CANCELLED"]
PENALTY_STATUSES = [
    "ISSUED",
    "DISPUTED",
    "UPHELD",
    "WAIVED",
    "CREDITED",
    "SUPERSEDED",
]
ROUND_STATUSES = ["OPEN", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN"]


def assert_common_fields(data: dict) -> None:
    """PRD §2.4: every persisted resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_service_contract(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in CONTRACT_STATUSES, f"bad contract status {data['status']!r}"
    assert data["scope_type"] in ["FULL_MAINTENANCE", "OIL_AND_GREASE"]
    assert data["penalty_schedule"] in ["SCHEDULE_A", "SCHEDULE_B"]
    assert isinstance(data["monthly_base_fee_cents"], int)
    assert isinstance(data["callback_response_minutes"], int)
    assert isinstance(data["entrapment_response_minutes"], int)
    assert isinstance(data["cars_out_of_service_count"], int)
    assert_contract_ledger_invariant(data)


def assert_contract_ledger_invariant(data: dict) -> None:
    """PRD §3.8: penalty_balance_cents == assessed - waived - credited."""
    expected = (
        data["penalty_lifetime_assessed_cents"]
        - data["penalty_lifetime_waived_cents"]
        - data["penalty_lifetime_credited_cents"]
    )
    assert data["penalty_balance_cents"] == expected, (
        "penalty_balance_cents must equal assessed - waived - credited, got "
        f"{data['penalty_balance_cents']} vs {expected}"
    )


def assert_elevator_car(data: dict) -> None:
    assert_common_fields(data)
    assert data["availability_state"] in AVAILABILITY_STATES
    assert data["compliance_state"] in COMPLIANCE_STATES
    assert data["car_type"] in ["TRACTION", "HYDRAULIC"]
    assert isinstance(data["scheduled_downtime_minutes"], int)
    assert data["scheduled_downtime_minutes"] >= 0
    assert isinstance(data["open_part_order_count"], int)
    assert data["open_part_order_count"] >= 0


def assert_maintenance_visit(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in VISIT_STATUSES
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["completed_task_codes"], list)
    assert isinstance(data["missing_task_codes"], list)
    assert data["completed_task_codes"] == sorted(data["completed_task_codes"]), (
        "completed_task_codes must be sorted ascending"
    )
    assert data["missing_task_codes"] == sorted(data["missing_task_codes"]), (
        "missing_task_codes must be sorted ascending"
    )


def assert_callback(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in CALLBACK_STATUSES
    assert data["callback_type"] in ["ENTRAPMENT", "MALFUNCTION", "NUISANCE"]
    assert isinstance(data["passengers_trapped"], int)
    assert data["passengers_trapped"] >= 0
    assert isinstance(data["out_of_service"], bool)
    assert is_iso8601_timestamp(data.get("reported_at", ""))


def assert_state_inspection(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in INSPECTION_STATUSES
    assert data["certificate_state"] in CERTIFICATE_STATES
    assert data["inspection_type"] in [
        "PERIODIC",
        "FIVE_YEAR_FULL_LOAD",
        "REINSPECTION",
    ]
    if data.get("result") is not None:
        assert data["result"] in ["PASS", "PASS_WITH_DEFICIENCIES", "FAIL"]
    assert isinstance(data["deficiency_codes"], list)


def assert_modernization_project(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in PROJECT_STATUSES
    assert isinstance(data["window_count"], int) and data["window_count"] >= 0
    assert isinstance(data["budget_cents"], int)


def assert_downtime_window(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in WINDOW_STATUSES
    assert data["window_type"] in ["MODERNIZATION", "INSPECTION", "REPAIR"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["reschedule_count"], int)


def assert_spare_part(data: dict) -> None:
    assert_common_fields(data)
    assert data["lifecycle_state"] in PART_LIFECYCLE_STATES
    assert data["part_class"] in [
        "LUBRICATION",
        "WEAR_ITEM",
        "COMPONENT",
        "CONTROLLER_BOARD",
    ]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["lead_time_days"], int)


def assert_part_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in PART_ORDER_STATUSES
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["expedite_surcharge_cents"], int)
    assert isinstance(data["total_cost_cents"], int)
    assert data["total_cost_cents"] == (
        data["subtotal_cents"] + data["expedite_surcharge_cents"]
    ), "total_cost_cents must equal subtotal_cents + expedite_surcharge_cents"
    assert isinstance(data["substitution_hops"], int)
    assert isinstance(data["lead_time_days_applied"], int)


def assert_penalty_assessment(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in PENALTY_STATUSES
    assert data["schedule_applied"] in ["SCHEDULE_A", "SCHEDULE_B"]
    assert data["uptime_variant_applied"] in ["EXCLUSIVE", "INCLUSIVE"]
    assert data["amount_cents"] == min(
        data["raw_amount_cents"], data["cap_amount_cents"]
    ), "amount_cents must be the smaller of raw_amount_cents and cap_amount_cents"
    for field in (
        "late_callback_count",
        "entrapment_breach_count",
        "missed_visit_count",
        "service_credit_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_renegotiation_round(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ROUND_STATUSES
    assert data["proposed_scope_type"] in ["FULL_MAINTENANCE", "OIL_AND_GREASE"]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_uptime_report(data: dict) -> None:
    """PRD §3.7: shape of GET /elevator-program/cars/{carId}/uptime-report."""
    for field in (
        "period_minutes",
        "unplanned_outage_minutes",
        "planned_downtime_minutes",
        "available_minutes",
        "outage_interval_count",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole-minute integer"
    assert data["available_minutes"] == (
        data["period_minutes"]
        - data["planned_downtime_minutes"]
        - data["unplanned_outage_minutes"]
    ), "available_minutes must be period minus planned minus unplanned"
    for field in ("uptime_pct_exclusive", "uptime_pct_inclusive"):
        value = data[field]
        assert isinstance(value, (int, float)), f"{field} must be numeric"
        assert round(float(value), 2) == float(value), (
            f"{field} must carry at most 2 decimal places, got {value}"
        )


def assert_percentage_2dp(value, label: str = "value") -> None:
    """PRD §2.9: percentages are carried to 2 decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimal places, got {value}"
    )


def parse_instant(value: str):
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    from datetime import datetime

    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"instants must be rendered in UTC with a Z suffix: {value!r}"
    text = text[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise AssertionError(f"not a parseable ISO 8601 UTC instant: {value!r}")


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment.

    Compared as instants rather than as strings so that a fractional-second
    suffix does not change the meaning of the assertion.
    """
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
