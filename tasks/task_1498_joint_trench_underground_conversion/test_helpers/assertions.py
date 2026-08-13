"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

from .types import ProjectStatus


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"Not a valid ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Two timestamps denote the same instant regardless of fractional-digit rendering."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_project(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["rule20_credit_cents"], int) and data["rule20_credit_cents"] >= 0
    assert isinstance(data["estimated_total_cost_cents"], int) and data["estimated_total_cost_cents"] > 0
    assert isinstance(data["contingency_days"], int) and data["contingency_days"] >= 0
    assert is_iso8601_timestamp(data["target_cutover_on"])
    assert data["status"] in [s.value for s in ProjectStatus]
    assert data["posture"] in ("CLEAR", "CONDITIONAL", "FROZEN")
    assert isinstance(data["cumulative_delay_days"], int)
    assert isinstance(data["liquidated_damages_cents"], int)
    assert "latest_true_up_run_id" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_participation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["utility_name"], str) and len(data["utility_name"]) > 0
    assert data["utility_type"] in ("ELECTRIC", "TELECOM", "CATV")
    assert isinstance(data["cost_share_bp"], int)
    assert isinstance(data["sequence_order"], int) and data["sequence_order"] >= 1
    assert isinstance(data["has_separation_waiver"], bool)
    assert data["status"] in (
        "INVITED", "COMMITTED", "MOBILIZED", "INSTALLED", "BILLED", "SETTLED", "WITHDRAWN"
    )
    assert isinstance(data["provisional_share_cents"], int)
    assert "final_share_cents" in data
    assert isinstance(data["variance_flag"], bool)
    assert "withdrawn_on" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_trench_segment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["segment_code"], str) and len(data["segment_code"]) > 0
    assert isinstance(data["length_ft"], int) and data["length_ft"] > 0
    assert isinstance(data["max_depth_inches"], int) and data["max_depth_inches"] > 0
    assert isinstance(data["parcel_ids"], list)
    assert "excavation_start_on" in data
    assert "excavation_end_on" in data
    assert data["status"] in ("PLANNED", "SCHEDULED", "EXCAVATING", "BACKFILLING", "BACKFILLED", "CLOSED")
    assert isinstance(data["occupied_depth_inches"], int)
    assert isinstance(data["available_depth_inches"], int)
    assert isinstance(data["frozen"], bool)
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_occupancy_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["trench_segment_id"])
    assert is_valid_uuid(data["participation_id"])
    assert isinstance(data["depth_top_inches"], int)
    assert isinstance(data["depth_bottom_inches"], int)
    assert is_iso8601_timestamp(data["install_start_at"])
    assert is_iso8601_timestamp(data["install_end_at"])
    assert data["status"] in ("RESERVED", "INSTALLING", "INSTALL_FAILED", "INSTALLED", "VERIFIED", "RELEASED")
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_parcel(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["owner_name"], str) and len(data["owner_name"]) > 0
    assert isinstance(data["existing_panel_amps"], int) and data["existing_panel_amps"] > 0
    assert isinstance(data["load_calc_amps"], int) and data["load_calc_amps"] > 0
    assert isinstance(data["panel_upgrade_required"], bool)
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_easement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["parcel_id"])
    assert data["easement_type"] in ("TRENCH", "ACCESS", "ANCHOR")
    assert data["status"] in ("DRAFT", "REQUESTED", "SIGNED", "RECORDED", "REFUSED")
    assert "requested_on" in data
    assert "signed_on" in data
    assert "recorded_on" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_permit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert data["permit_type"] in ("ENCROACHMENT", "TRAFFIC_CONTROL", "GRADING")
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_to"])
    assert data["status"] in ("APPLICATION", "SUBMITTED", "ISSUED", "EXPIRED", "REVOKED", "CLOSED")
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_service_conversion(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["project_id"])
    assert data["work_status"] in (
        "PLANNED", "ROUGH_IN", "PANEL_SET", "READY_TO_ENERGIZE", "ENERGIZED", "INSPECTED", "COMPLETE"
    )
    assert data["temp_service_status"] in ("NONE", "TEMP_INSTALLED", "TEMP_ACTIVE", "TEMP_REMOVED")
    assert "panel_capacity_amps" in data
    assert "last_inspection_outcome" in data
    assert "energized_on" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_outage_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["feeder_id"], str) and len(data["feeder_id"]) > 0
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["conversion_ids"], list)
    assert data["status"] in ("PROPOSED", "APPROVED", "NOTIFIED", "EXECUTED", "CLOSED", "CANCELLED")
    assert "notified_at" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_change_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["description"], str)
    assert isinstance(data["segment_ids"], list)
    assert "delta_cost_cents" in data
    assert "delta_delay_days" in data
    assert "delay_cause" in data
    assert data["status"] in ("PROPOSED", "PRICED", "APPROVED", "INCORPORATED", "REJECTED", "WITHDRAWN")
    assert isinstance(data["revision_count"], int)
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_actual_cost_entry(data: dict):
    """Append-only ledger entry: id + created_at present; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert data["cost_code"] in ("JOINT_TRENCH", "EXCLUSIVE", "RESTORATION", "PROGRAM_OVERHEAD")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["incurred_on"])
    assert isinstance(data["submitted_by_user_id"], str)
    assert is_iso8601_timestamp(data["created_at"])
    assert "updated_at" not in data, "append-only entry must not expose updated_at"
    assert "version" not in data, "append-only entry must not expose version"


def assert_true_up_run(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["project_id"])
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "SETTLED")
    assert isinstance(data["created_by_user_id"], str)
    assert "published_by_user_id" in data
    assert isinstance(data["total_actual_cost_cents"], int)
    assert isinstance(data["rule20_credit_applied_cents"], int)
    assert isinstance(data["lines"], list)
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["true_up_run_id"])
    assert is_valid_uuid(data["participation_id"])
    assert isinstance(data["principal_cents"], int)
    assert is_iso8601_timestamp(data["issued_on"])
    assert is_iso8601_timestamp(data["due_on"])
    assert data["status"] in ("ISSUED", "PAID", "DISPUTED", "VOID")
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert "paid_on" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_restoration_task(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data["trench_segment_id"])
    assert is_valid_uuid(data["parcel_id"])
    assert data["task_type"] in ("HARDSCAPE", "LANDSCAPE", "IRRIGATION")
    assert data["status"] in ("OPEN", "IN_WORK", "COMPLETE", "ACCEPTED", "WARRANTY_CLAIM")
    assert "completed_on" in data
    assert "accepted_on" in data
    assert "warranty_expires_on" in data
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_provisional_shares_conserve_total(shares: list, estimated_total_cost_cents: int):
    """PRD §3.1 invariant: provisional shares of active participants sum to the estimate."""
    assert sum(shares) == estimated_total_cost_cents, (
        f"Provisional shares {shares} must sum to estimated total {estimated_total_cost_cents}"
    )
