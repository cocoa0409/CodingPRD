"""Entity assertions and domain invariant checkers."""
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional seconds)."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v)


def assert_instant_equals(actual: str, expected: str) -> None:
    """Two ISO 8601 strings denote the same instant (compared to the second)."""
    a = parse_instant(actual)
    b = parse_instant(expected)
    assert a == b, f"Expected instant {expected}, got {actual}"


def _assert_common_fields(data: dict) -> None:
    """Standard system-managed fields on primary resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_event_fields(data: dict) -> None:
    """Append-only event records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_plant(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["establishment_number"], str) and data["establishment_number"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert data["cooler_capacity_lbs"] > 0
    assert data["operating_status"] in ("ACTIVE", "SUSPENDED")
    assert data["cooler_occupied_lbs"] >= 0
    assert data["cooler_occupied_lbs"] <= data["cooler_capacity_lbs"]
    assert 0 <= data["provisional_compliance_score"] <= 100
    assert 0 <= data["official_compliance_score"] <= 100


def assert_haccp_plan(data: dict) -> None:
    _assert_common_fields(data)
    assert data["process_type"] in ("SLAUGHTER", "RAW_GROUND", "RAW_INTACT", "COOKED_RTE")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EFFECTIVE", "SUPERSEDED",
    )
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0


def assert_ccp(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["ccp_code"], str) and data["ccp_code"]
    assert data["hazard_category"] in ("BIOLOGICAL", "CHEMICAL", "PHYSICAL")
    assert data["deviation_severity"] in ("MINOR", "MAJOR")
    assert data["monitoring_frequency_minutes"] > 0


def assert_observation(data: dict) -> None:
    _assert_event_fields(data)
    assert isinstance(data["observed_value_f"], (int, float))
    assert isinstance(data["within_limit"], bool)
    assert isinstance(data["monitor_user_id"], str) and data["monitor_user_id"]


def assert_deviation(data: dict) -> None:
    _assert_common_fields(data)
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("OPEN", "ACTION_LOGGED", "VERIFIED")


def assert_inspector_shift(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert data["status"] in ("SCHEDULED", "ON_PREMISE", "DEPARTED", "NO_SHOW")


def assert_production_day(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("PLANNED", "OPEN", "SUSPENDED", "CLOSED")
    assert data["posture"] in ("CLEAR", "RESTRICTED")
    assert data["process_type"] in ("SLAUGHTER", "RAW_GROUND", "RAW_INTACT", "COOKED_RTE")


def assert_carcass_lot(data: dict) -> None:
    _assert_common_fields(data)
    assert data["species"] in ("BOVINE", "SWINE", "OVINE", "POULTRY")
    assert data["status"] in (
        "RECEIVED", "CLEARED", "HARVESTED", "CHILLED", "FABRICATING",
        "FABRICATED", "HELD", "RELEASED", "CONDEMNED",
    )
    assert data["head_count"] > 0
    assert data["live_weight_lbs"] > 0


def assert_cut_record(data: dict) -> None:
    _assert_event_fields(data)
    assert data["primal_type"] in (
        "CHUCK", "RIB", "LOIN", "ROUND", "BRISKET", "BELLY", "HAM", "OTHER",
    )
    assert data["weight_lbs"] > 0


def assert_pathogen_sample(data: dict) -> None:
    _assert_common_fields(data)
    assert data["organism"] in (
        "ECOLI_O157H7", "SALMONELLA", "LISTERIA_MONOCYTOGENES", "GENERIC_ECOLI",
    )
    assert data["sample_type"] in ("CARCASS_SWAB", "GROUND_PRODUCT", "ENVIRONMENTAL")
    assert data["result"] in ("PENDING", "NEGATIVE", "POSITIVE")
    assert isinstance(data["is_confirmation"], bool)


def assert_label_approval(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert isinstance(data["claims"], list)
    assert isinstance(data["substantiation_doc_refs"], list)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert data["formulation_version"] >= 1


def assert_finished_lot(data: dict) -> None:
    _assert_common_fields(data)
    assert data["units_produced"] > 0
    assert data["unit_weight_lbs"] > 0
    assert data["shelf_life_days"] > 0
    assert data["status"] in ("PRODUCED", "SHIPPED", "QUARANTINED", "SPOILED")
    assert isinstance(data["temperature_logs"], list)


def assert_humane_audit(data: dict) -> None:
    _assert_event_fields(data)
    assert 0 <= data["stunning_efficacy_pct"] <= 100
    assert 0 <= data["slips_falls_pct"] <= 100
    assert 0 <= data["vocalization_pct"] <= 100
    assert data["outcome"] in ("PASSED", "FAILED")


def assert_noncompliance_record(data: dict) -> None:
    _assert_common_fields(data)
    assert data["category"] in (
        "HUMANE_HANDLING", "TRACEABILITY", "PATHOGEN_CONTROL", "SANITATION",
    )
    assert data["severity"] in ("MAJOR", "CRITICAL")
    assert data["status"] in ("OPEN", "APPEALED", "CLOSED")


def assert_recall_exercise(data: dict) -> None:
    _assert_common_fields(data)
    assert data["scope"] in ("ONE_STEP_BACK", "ONE_STEP_FORWARD", "FULL")
    assert data["status"] in ("INITIATED", "PASSED", "FAILED")
    assert data["basis_weight_lbs"] > 0


def assert_pct(value: float, expected: float) -> None:
    """Percentage/weight assertion with round-half-up 2dp tolerance."""
    assert value == pytest.approx(expected, abs=1e-6), (
        f"Expected {expected}, got {value}"
    )
