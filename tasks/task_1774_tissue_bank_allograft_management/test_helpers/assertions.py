"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Common resource properties carried by every primary resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_supplier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in (
        "PENDING_QUALIFICATION",
        "QUALIFIED",
        "SUSPENDED",
        "DISQUALIFIED",
    ), f"unexpected supplier status {data['status']!r}"
    assert isinstance(data["qualification_score_provisional"], (int, float))
    assert isinstance(data["qualification_score_final"], (int, float))
    assert data["qualification_score_provisional"] >= 0, "scores are floored at 0 (PRD §3.8)"
    assert data["qualification_score_final"] >= 0, "scores are floored at 0 (PRD §3.8)"
    assert "suspended_at" in data


def assert_supplier_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert data["doc_type"] in (
        "AATB_ACCREDITATION",
        "FDA_REGISTRATION",
        "STATE_LICENSE",
        "ISO_CERTIFICATE",
    )
    assert isinstance(data["document_ref"], str) and data["document_ref"]
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_to"])
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")
    assert "verified_by_user_id" in data


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert is_valid_uuid(data.get("freezer_id", ""))
    assert data["status"] in ("RECEIVED", "ACCEPTED", "REJECTED")
    assert isinstance(data["total_declared_value_cents"], int)
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert is_iso8601_timestamp(data["received_at"])


def assert_tissue_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert is_valid_uuid(data.get("freezer_id", ""))
    assert data["tissue_type"] in ("BONE", "SOFT_TISSUE", "CARDIOVASCULAR", "SKIN", "CORNEA")
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["criticality_tier"] in ("STANDARD", "SENSITIVE", "CRITICAL")
    assert is_iso8601_timestamp(data["expiration_at"])
    assert data["status"] in (
        "QUARANTINED",
        "AVAILABLE",
        "RESERVED",
        "ISSUED",
        "IMPLANTED",
        "DISCARDED",
        "RETURNED_TO_SUPPLIER",
        "EXPIRED",
    )
    assert data["hold_reason"] in ("NONE", "EXCURSION", "RECALL", "MANUAL")
    assert isinstance(data["recall_flag"], bool)


def assert_freezer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["min_celsius"] < data["max_celsius"], "in-range band must be strictly ordered"
    assert isinstance(data["nominal_capacity"], int) and data["nominal_capacity"] >= 1
    assert data["status"] in ("OPERATIONAL", "EXCURSION_ACTIVE")
    assert isinstance(data["occupied_count"], int) and data["occupied_count"] >= 0
    assert isinstance(data["utilization_pct"], (int, float))
    assert isinstance(data["quarantine_reserve_slots"], int)
    assert isinstance(data["effective_capacity"], int)
    assert data["effective_capacity"] == data["nominal_capacity"] - data["quarantine_reserve_slots"], (
        "effective_capacity is nominal_capacity minus quarantine_reserve_slots (PRD §3.3)"
    )
    assert "current_excursion_id" in data


def assert_temperature_reading(data: dict):
    """TemperatureReading is an immutable observation: id + created_at only,
    with version and updated_at both absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "TemperatureReading must not carry version"
    assert "updated_at" not in data, "TemperatureReading must not carry updated_at"
    assert is_valid_uuid(data.get("freezer_id", ""))
    assert isinstance(data["temp_celsius"], (int, float))
    assert isinstance(data["in_range"], bool)
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert "excursion_id" in data


def assert_temperature_excursion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("freezer_id", ""))
    assert data["origin"] in ("AUTO_READING", "MANUAL_REPORT")
    assert data["status"] in (
        "OPEN",
        "UNDER_INVESTIGATION",
        "RESOLVED_RELEASE",
        "RESOLVED_DESTROY",
    )
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["max_deviation_celsius"], (int, float))
    assert data["max_deviation_celsius"] >= 0
    assert isinstance(data["affected_unit_count"], int) and data["affected_unit_count"] >= 0
    assert isinstance(data["severity_score"], int)
    assert 0 <= data["severity_score"] <= 100, "severity is scored 0..100 (PRD §3.3)"
    assert data["severity_class"] in ("LOW", "MEDIUM", "HIGH")


def assert_implant_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["surgeon_id"], str) and data["surgeon_id"]
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert isinstance(data["or_room_id"], str) and data["or_room_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["implanted_unit_count"], int) and data["implanted_unit_count"] >= 0


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("implant_case_id", ""))
    assert is_valid_uuid(data.get("tissue_unit_id", ""))
    assert data["status"] in ("ACTIVE", "RELEASED", "FULFILLED", "EXPIRED")
    assert is_iso8601_timestamp(data["hold_until"])
    assert data["release_reason"] in (
        "NONE",
        "MANUAL",
        "EXCURSION",
        "RECALL",
        "CASE_CANCELLED",
        "CASE_COMPLETED",
        "CLOCK_EXPIRED",
    )


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert isinstance(data["lot_numbers"], list) and len(data["lot_numbers"]) >= 1
    assert is_iso8601_timestamp(data["received_window_start"])
    assert is_iso8601_timestamp(data["received_window_end"])
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert data["closure_reason"] in ("NONE", "NO_MATCH", "RESOLVED")
    assert isinstance(data["affected_unit_count"], int) and data["affected_unit_count"] >= 0


def assert_adverse_reaction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("implant_case_id", ""))
    assert is_valid_uuid(data.get("tissue_unit_id", ""))
    assert isinstance(data["reporter_user_id"], str) and data["reporter_user_id"]
    assert data["reaction_type"] in ("INFECTION", "REJECTION", "OTHER")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str) and len(data["description"]) >= 10
    assert data["status"] in (
        "REPORTED",
        "UNDER_INVESTIGATION",
        "CLOSED_CONFIRMED",
        "CLOSED_UNCONFIRMED",
        "REOPENED",
    )
    assert isinstance(data["reopened_count"], int) and data["reopened_count"] >= 0


def assert_par_level_policy(data: dict):
    _assert_common_fields(data)
    assert data["tissue_type"] in ("BONE", "SOFT_TISSUE", "CARDIOVASCULAR", "SKIN", "CORNEA")
    assert isinstance(data["par_quantity"], int) and data["par_quantity"] >= 0
    assert isinstance(data["max_inventory_value_cents"], int)
    assert data["max_inventory_value_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["on_hand_available"], int) and data["on_hand_available"] >= 0
    assert isinstance(data["deficit"], int) and data["deficit"] >= 0
    assert isinstance(data["needs_reorder"], bool)


def assert_disposition_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tissue_unit_id", ""))
    assert data["disposition_type"] in (
        "IMPLANTED",
        "DESTROYED",
        "RETURNED_TO_SUPPLIER",
        "EXPIRED",
    )
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_supplier_scores(data: dict, provisional: float, final: float):
    """Domain invariant: both qualification scores match the expected values."""
    assert data["qualification_score_provisional"] == provisional, (
        f"provisional score: expected {provisional}, got {data['qualification_score_provisional']}"
    )
    assert data["qualification_score_final"] == final, (
        f"final score: expected {final}, got {data['qualification_score_final']}"
    )
