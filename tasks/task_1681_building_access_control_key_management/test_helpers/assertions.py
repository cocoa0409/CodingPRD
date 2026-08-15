"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_building(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["audit_retention_days"], int)
    assert isinstance(data["alert_escalation_minutes"], int)
    assert isinstance(data["vendor_badge_pool_max"], int)
    assert isinstance(data["default_propped_threshold_seconds"], int)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["per_door_fee_cents"], int)
    assert isinstance(data["per_key_reissue_fee_cents"], int)
    assert isinstance(data["emergency_surcharge_pct"], int)
    assert isinstance(data["ops_run_index"], int)


def assert_key_node(data: dict):
    _assert_common(data)
    assert data["level"] in ["GRAND_MASTER", "MASTER", "SUB_MASTER", "CHANGE"]
    assert data["status"] in ["ACTIVE", "COMPROMISED", "RETIRED"]
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["stock_credential_count"], int)
    assert isinstance(data["issued_credential_count"], int)
    assert isinstance(data["lost_credential_count"], int)


def assert_door(data: dict):
    _assert_common(data)
    assert isinstance(data["door_code"], str) and data["door_code"]
    assert data["hardware_status"] in ["OPERATIONAL", "UNDER_MAINTENANCE"]
    assert data["core_status"] in ["ACTIVE", "REKEY_REQUIRED"]
    assert isinstance(data["propped_threshold_seconds"], int)
    assert data["propped_threshold_seconds"] >= 1


def assert_person(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["kind"] in ["RESIDENT", "STAFF", "VENDOR"]
    assert data["status"] in ["ACTIVE", "MOVED_OUT", "TERMINATED"]
    assert isinstance(data["key_deposit_cents"], int)


def assert_credential(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    assert data["type"] in ["METAL_KEY", "FOB", "CARD"]
    assert data["status"] in ["IN_STOCK", "ISSUED", "LOST", "DEACTIVATED"]


def assert_access_group(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["door_ids"], list)
    assert isinstance(data["person_ids"], list)
    assert isinstance(data["days_of_week"], list) and len(data["days_of_week"]) >= 1


def assert_access_event(data: dict):
    """Append-only audit row: id + created_at, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "AccessEvent must not expose updated_at"
    assert "version" not in data, "AccessEvent must not expose version"
    assert data["outcome"] in [
        "GRANTED",
        "DENIED_CREDENTIAL_NOT_ISSUED",
        "DENIED_CREDENTIAL_EXPIRED",
        "DENIED_NOT_AUTHORIZED",
        "DENIED_OUTSIDE_WINDOW",
    ]
    assert isinstance(data["archived"], bool)


def assert_propped_alert(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED"]
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at must be ISO 8601"


def assert_incident(data: dict):
    _assert_common(data)
    assert data["type"] in ["LOST_CREDENTIAL", "PROPPED_DOOR"]
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "RESOLVED", "DISMISSED"]


def assert_rekey_campaign(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert data["bill_to"] in ["BUILDING", "PERSON"]
    assert isinstance(data["affected_door_count"], int)
    assert isinstance(data["affected_credential_count"], int)
    assert isinstance(data["estimated_cost_cents"], int)


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["type"] in ["HARDWARE_REPAIR", "INSPECTION", "BATTERY_REPLACE", "REKEY"]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


def assert_charge(data: dict):
    _assert_common(data)
    assert data["kind"] in ["MOVE_OUT_SETTLEMENT", "REKEY_CAMPAIGN", "KEY_REISSUE"]
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    assert isinstance(data["amount_cents"], int)


def assert_timestamp_equals(actual: str, expected_iso: str):
    """Compare an ISO 8601 timestamp against an expected instant, tolerant of the
    three-fractional-digits rendering (PRD §2.4): '.000Z' and 'Z' are the same."""
    assert actual is not None, f"expected {expected_iso}, got None"
    normalized = actual.replace(".000Z", "Z")
    assert normalized == expected_iso, f"expected {expected_iso}, got {actual}"


def assert_node_counts(node: dict, stock: int, issued: int, lost: int):
    """Per-node credential counters (exact-node aggregation, PRD §3.1)."""
    assert node["stock_credential_count"] == stock, (
        f"stock_credential_count: expected {stock}, got {node['stock_credential_count']}"
    )
    assert node["issued_credential_count"] == issued, (
        f"issued_credential_count: expected {issued}, got {node['issued_credential_count']}"
    )
    assert node["lost_credential_count"] == lost, (
        f"lost_credential_count: expected {lost}, got {node['lost_credential_count']}"
    )
