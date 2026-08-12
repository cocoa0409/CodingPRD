"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso8601(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp regardless of fractional-digit rendering."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str, msg: str = ""):
    """PRD pins the instant a clock-stamped field must hold, not its string
    rendering (only created_at is pinned to three fractional digits, §2.4)."""
    assert parse_iso8601(actual) == parse_iso8601(expected), (
        msg or f"instant mismatch: {actual!r} != {expected!r}"
    )

JOB_STATUSES = [
    "INTAKE", "DISPATCHED", "ON_SITE", "SECURED", "BREACH_HOLD",
    "READY_FOR_REMOVAL", "REMOVED", "CLOSED",
]
ASSIGNMENT_STATUSES = [
    "OFFERED", "ACCEPTED", "ARRIVED", "COMPLETED", "DECLINED", "EXPIRED", "CANCELLED",
]
ASSESSMENT_STATUSES = ["SUBMITTED", "MITIGATION_REQUIRED", "CLEARED", "SUPERSEDED"]
SCOPE_ITEM_STATUSES = ["PLANNED", "INSTALLED", "VOIDED"]
SERVICE_STATUSES = ["ACTIVE", "PAUSED", "COMPLETED"]
VISIT_STATUSES = ["SCHEDULED", "CHECKED_IN", "MISSED"]
PERMIT_STATUSES = ["PENDING", "FILED", "APPROVED", "REJECTED", "EXPIRED"]
PACKAGE_STATUSES = ["INCOMPLETE", "COMPLETE", "LOCKED", "AMENDED"]
INVOICE_STATUSES = ["DRAFT", "SUBMITTED", "DISPUTED", "PAID"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_market(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    for field in ("sla_minutes_p1", "sla_minutes_p2", "sla_minutes_p3",
                  "notification_deadline_hours", "late_notification_fee_cents",
                  "board_rate_per_sheet_cents", "tarp_rate_per_sqft_cents",
                  "fence_rate_per_linear_ft_cents", "patrol_visit_fee_cents",
                  "temp_power_daily_rate_cents", "temp_lighting_daily_rate_cents",
                  "generator_pool_units", "removal_flat_fee_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["notification_required"], bool)


def assert_subcontractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for field in ("completed_job_count", "breached_job_count",
                  "expired_offer_count", "active_assignment_count"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"
    for field in ("reliability_score_lenient", "reliability_score_strict"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert 0.0 <= data[field] <= 1.0, f"{field} must be within [0, 1]"


def assert_coverage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["subcontractor_id"])
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["max_concurrent_jobs"], int) and data["max_concurrent_jobs"] >= 1
    assert isinstance(data["rank"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["kind"] in ("OWNER", "ADJUSTER")


def assert_property(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert data["wind_zone"] in ("LOW", "HIGH")


def assert_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["incident_type"] in ("FIRE", "STORM", "VANDALISM")
    assert data["priority"] in ("P1", "P2", "P3")
    assert isinstance(data["sla_minutes"], int) and data["sla_minutes"] > 0
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["work_status"] in JOB_STATUSES
    assert isinstance(data["safety_cleared"], bool)
    assert isinstance(data["compliance_breach"], bool)
    assert isinstance(data["total_planned_sheets"], int) and data["total_planned_sheets"] >= 0


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["subcontractor_id"])
    assert isinstance(data["offer_seq"], int) and data["offer_seq"] >= 1
    assert data["status"] in ASSIGNMENT_STATUSES
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["offer_expires_at"])


def assert_safety_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["assessor_subcontractor_id"])
    assert isinstance(data["hazards"], list)
    for hazard in data["hazards"]:
        assert hazard in ("COLLAPSE", "ELECTRICAL", "GAS", "WATER", "ASBESTOS")
    assert isinstance(data["structural_risk_score"], int)
    assert 0 <= data["structural_risk_score"] <= 100
    assert data["hazard_level"] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["moderate_ppe_required"], bool)
    assert data["status"] in ASSESSMENT_STATUSES


def assert_scope_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert data["kind"] in ("BOARD", "TARP", "FENCE")
    assert data["unit"] in ("SHEETS", "SQFT", "LINEAR_FT")
    assert data["status"] in SCOPE_ITEM_STATUSES
    assert isinstance(data["planned_qty"], (int, float)) and data["planned_qty"] > 0
    assert isinstance(data["door_count"], int) and data["door_count"] >= 0


def assert_temporary_service(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert data["kind"] in ("POWER", "LIGHTING", "PATROL")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert data["status"] in SERVICE_STATUSES


def assert_patrol_visit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["temporary_service_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in VISIT_STATUSES
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_permit_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert data["kind"] in ("PERMIT", "NOTIFICATION")
    assert data["status"] in PERMIT_STATUSES
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["penalty_billed"], bool)


def assert_document_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0
    assert isinstance(data["authorization_signed"], bool)
    assert isinstance(data["measurement_sheet_recorded"], bool)
    assert isinstance(data["required_photo_count"], int) and data["required_photo_count"] >= 0
    assert data["status"] in PACKAGE_STATUSES


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in INVOICE_STATUSES
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["label"], str)
        assert isinstance(line["quantity"], (int, float))
        assert line["unit"] in ("SHEETS", "SQFT", "LINEAR_FT")
        assert isinstance(line["rate_cents"], int)
        assert isinstance(line["multiplier"], (int, float))
        assert isinstance(line["line_cents"], int)
    for field in ("work_subtotal_cents", "service_subtotal_cents", "removal_fee_cents",
                  "penalty_cents", "discount_cents", "pre_discount_total_cents",
                  "total_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be integer cents >= 0"


def assert_invoice_invariants(data: dict):
    """Money invariants that must hold on every invoice (PRD billing section):
    total = pre_discount_total - discount, and pre_discount_total is the sum of
    work + services + removal fee + penalty."""
    assert_invoice(data)
    assert data["pre_discount_total_cents"] == (
        data["work_subtotal_cents"]
        + data["service_subtotal_cents"]
        + data["removal_fee_cents"]
        + data["penalty_cents"]
    ), "pre_discount_total_cents must equal work + services + removal + penalty"
    assert data["total_cents"] == data["pre_discount_total_cents"] - data["discount_cents"], (
        "total_cents must equal pre_discount_total_cents minus discount_cents"
    )
