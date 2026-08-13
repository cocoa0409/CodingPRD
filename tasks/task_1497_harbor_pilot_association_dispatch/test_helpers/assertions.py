"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant ('Z' or offset, with or without fractional digits)."""
    assert isinstance(value, str) and value.strip(), f"expected ISO 8601 string, got {value!r}"
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str):
    """Two ISO 8601 strings denote the same instant (serialization may differ)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_pilot(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["share_units"], int) and data["share_units"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data.get("rest_until") is None or is_iso8601_timestamp(data["rest_until"])
    assert isinstance(data["duty_minutes_rolling_7d"], int) and data["duty_minutes_rolling_7d"] >= 0


def assert_license_endorsement(data: dict):
    _assert_common(data)
    assert data["endorsement_class"] in ("HARBOR", "COASTAL", "UNLIMITED")
    assert isinstance(data["tonnage_cap_gt"], int) and data["tonnage_cap_gt"] > 0
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ("CURRENT", "SUPERSEDED")


def assert_rotation_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["position"], int) and data["position"] >= 1
    assert data.get("previous_position") is None or isinstance(data["previous_position"], int)
    assert data["status"] in ("IN_ROTATION", "OFF_BOARD")


def assert_vessel_order(data: dict):
    _assert_common(data)
    assert isinstance(data["vessel_name"], str) and data["vessel_name"]
    assert isinstance(data["gt"], int) and data["gt"] > 0
    assert isinstance(data["draft_dm"], int) and data["draft_dm"] > 0
    assert data["order_type"] in ("ARRIVAL", "DEPARTURE", "SHIFT")
    assert is_iso8601_timestamp(data.get("eta", ""))
    assert isinstance(data["provisional_fee_cents"], int)
    assert data["status"] in ("BOOKED", "DISPATCHED", "IN_SERVICE", "COMPLETED", "CANCELLED")


def assert_pilot_boat(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_persons"], int) and data["capacity_persons"] >= 1
    assert data["status"] in ("AVAILABLE", "ON_RUN")


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("pilot_id", ""))
    assert is_valid_uuid(data.get("boat_id", ""))
    assert data.get("apprentice_id") is None or is_valid_uuid(data["apprentice_id"])
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data.get("actual_start") is None or is_iso8601_timestamp(data["actual_start"])
    assert data.get("actual_end") is None or is_iso8601_timestamp(data["actual_end"])
    assert data["service_status"] in (
        "ASSIGNED", "EN_ROUTE", "ABOARD", "COMPLETED", "RECALLED", "CANCELLED",
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "SETTLED")
    assert isinstance(data["recall_count"], int) and data["recall_count"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    for field in ("base_fee_cents", "detention_fee_cents", "delay_fee_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["total_cents"] == (
        data["base_fee_cents"] + data["detention_fee_cents"] + data["delay_fee_cents"]
    ), "total_cents must equal the sum of the three rounded components (PRD §3.6)"
    assert data["status"] in ("ISSUED", "FINALIZED", "DISTRIBUTED")
    assert data.get("finalized_at") is None or is_iso8601_timestamp(data["finalized_at"])


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("pilot_id", ""))
    assert data["incident_type"] in ("GROUNDING", "COLLISION", "NEAR_MISS", "EQUIPMENT", "CONDUCT")
    assert isinstance(data["description"], str) and data["description"]
    assert data.get("corrective_note") is None or isinstance(data["corrective_note"], str)
    assert data["status"] in ("REPORTED", "UNDER_REVIEW", "DISMISSED", "SUBSTANTIATED", "CLOSED")


def assert_apprentice(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["track"] in ("STANDARD", "ACCELERATED")
    assert isinstance(data["trips_completed"], int) and data["trips_completed"] >= 0
    assert isinstance(data["evaluations_count"], int) and data["evaluations_count"] >= 0
    assert isinstance(data["evaluation_avg"], (int, float))
    assert data["status"] in ("ENROLLED", "QUALIFIED", "CERTIFIED")


def assert_tariff_schedule(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    for tier in data["tiers"]:
        assert isinstance(tier["min_gt_exclusive"], int)
        assert tier["max_gt_inclusive"] is None or isinstance(tier["max_gt_inclusive"], int)
        assert isinstance(tier["rate_cents_per_gt"], int)
    assert isinstance(data["draft_surcharge_threshold_dm"], int)
    assert isinstance(data["detention_free_minutes"], int)
    assert isinstance(data["detention_rate_cents_per_minute"], int)
    assert isinstance(data["delay_rate_cents_per_minute"], int)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "SUPERSEDED")


def assert_distribution_run(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    for field in ("gross_pool_cents", "levy_cents", "net_pool_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["net_pool_cents"] == data["gross_pool_cents"] - data["levy_cents"]
    assert isinstance(data["shares"], list)
    for share in data["shares"]:
        assert is_valid_uuid(share.get("pilot_id", ""))
        assert isinstance(share["share_units"], int)
        assert isinstance(share["share_cents"], int)
    assert isinstance(data["invoice_ids"], list)
    assert data["status"] in ("COMPUTED", "SETTLED", "VOID")
