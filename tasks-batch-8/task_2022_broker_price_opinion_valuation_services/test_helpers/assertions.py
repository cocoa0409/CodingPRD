"""Entity assertions and small domain helpers.

Append-only records (PhotoEvidence, QCRevisionRequest, VolumeForecast) must
carry id + created_at only — PRD §2.4 states updated_at and version are
absent on those types, so the assertions also verify their absence.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (accepts trailing 'Z' or offset)."""
    assert isinstance(value, str) and value, f"Expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_client_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_code"], str) and data["client_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["sla_hours_standard"], int)
    assert isinstance(data["sla_hours_rush"], int)
    assert isinstance(data["late_penalty_bps_per_day"], int)
    for field in ("scorecard_weight_turnaround", "scorecard_weight_quality",
                  "scorecard_weight_revision"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_broker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["broker_code"], str) and data["broker_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["max_concurrent_orders"], int)
    assert data["status"] in ("PENDING_ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["composite_score"], (int, float)), "composite_score must be numeric"
    assert 0 <= data["composite_score"] <= 100, "composite_score is clamped to [0, 100]"


def assert_broker_license(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["broker_id"], str) and data["broker_id"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["license_kind"] in ("BPO", "APPRAISAL")
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert is_iso8601_timestamp(data["expires_on"]), "expires_on must be ISO 8601"
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_state_regulation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["bpo_permitted"], bool)
    assert isinstance(data["appraisal_required_for_interior"], bool)
    assert isinstance(data["min_driveby_radius_miles"], (int, float))
    assert isinstance(data["min_interior_radius_miles"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["street_address"], str) and data["street_address"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert isinstance(data["living_area_sqft"], int) and data["living_area_sqft"] > 0
    assert isinstance(data["lot_area_sqft"], int) and data["lot_area_sqft"] > 0
    assert isinstance(data["year_built"], int) and 1700 <= data["year_built"] <= 2100
    assert data["property_type"] in (
        "SINGLE_FAMILY", "CONDO", "TOWNHOME", "MULTI_FAMILY", "MANUFACTURED")
    assert data["status"] in ("REGISTERED", "ARCHIVED")


def assert_valuation_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["property_id"], str) and data["property_id"]
    assert data["order_kind"] in ("BPO", "APPRAISAL")
    assert data["inspection_level"] in ("DRIVE_BY", "INTERIOR")
    assert data["priority"] in ("STANDARD", "RUSH")
    assert isinstance(data["agreed_fee_cents"], int)
    assert data["fulfillment_status"] in (
        "INTAKE", "READY_FOR_DISPATCH", "DISPATCHED", "IN_PROGRESS",
        "REPORT_SUBMITTED", "QC_REVIEW", "REVISION_REQUESTED", "ACCEPTED",
        "COMPLETED", "CANCELLED", "REJECTED")
    assert data["payment_status"] in (
        "UNBILLED", "INVOICED", "PAID", "PARTIALLY_PAID", "WAIVED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_comparable(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert isinstance(data["source_property_id"], str) and data["source_property_id"]
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0
    assert is_iso8601_timestamp(data["sale_date"]), "sale_date must be ISO 8601"
    assert isinstance(data["distance_miles"], (int, float))
    assert isinstance(data["adjustment_cents"], int)
    assert isinstance(data["adjusted_value_cents"], int)
    assert data["adjusted_value_cents"] == data["sale_price_cents"] + data["adjustment_cents"], (
        "adjusted_value_cents must equal sale_price_cents + adjustment_cents")
    assert data["status"] in ("DRAFT", "SELECTED", "REJECTED")


def assert_photo_evidence(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert data["photo_kind"] in (
        "FRONT", "REAR", "STREET", "INTERIOR_LIVING", "INTERIOR_KITCHEN",
        "INTERIOR_BATH", "DEFECT", "OTHER")
    assert isinstance(data["file_url"], str) and data["file_url"]
    assert is_iso8601_timestamp(data["captured_at"]), "captured_at must be ISO 8601"
    assert isinstance(data["uploaded_by_broker_id"], str) and data["uploaded_by_broker_id"]


def assert_fee_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert data["fee_kind"] in (
        "BASE", "RUSH_SURCHARGE", "INTERIOR_SURCHARGE", "APPRAISAL_SURCHARGE",
        "TRAVEL", "MISC")
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("DRAFT", "CONFIRMED", "CANCELLED")


def assert_qc_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert isinstance(data["reviewer_id"], str) and data["reviewer_id"]
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["is_segregation_violation"], bool)


def assert_revision_request(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert isinstance(data["qc_review_id"], str) and data["qc_review_id"]
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert is_iso8601_timestamp(data["due_at"]), "due_at must be ISO 8601"
    assert data["outcome"] in ("OPEN", "RESOLVED_ON_TIME", "RESOLVED_LATE", "EXPIRED")


def assert_payout_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["broker_id"], str) and data["broker_id"]
    assert is_iso8601_timestamp(data["period_start"]), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data["period_end"]), "period_end must be ISO 8601"
    assert isinstance(data["total_payable_cents"], int)
    assert isinstance(data["order_count"], int) and data["order_count"] >= 0
    assert data["status"] in ("OPEN", "APPROVED", "DISBURSED", "VOIDED")


def assert_volume_forecast(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["forecast_month"], str) and len(data["forecast_month"]) == 7
    assert isinstance(data["predicted_order_count"], int)
    assert isinstance(data["model_version"], str) and data["model_version"]
    assert is_iso8601_timestamp(data["generated_at"]), "generated_at must be ISO 8601"
