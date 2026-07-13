"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_operator(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["operator_type"] in ("TNC", "TAXI", "LIMO", "SHUTTLE")
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED")
    assert data["suspended_reason"] in (None, "ADMIN", "PENALTY_THRESHOLD")
    assert isinstance(data["rolling_penalty_points"], int)
    assert isinstance(data["lifetime_penalty_points"], int)
    assert isinstance(data["outstanding_fees_cents"], int)


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["plate"], str)
    assert isinstance(data["is_wheelchair_accessible"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["avi_tag_id"], str)
    assert data["permit_status"] in ("ISSUED", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")
    assert data["suspended_reason"] in (None, "OPERATOR_SUSPENDED")


def assert_queue_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["staging_lot_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["status"] in ("WAITING", "RELEASED", "EXITED", "CANCELLED")
    if data["status"] == "WAITING":
        assert isinstance(data["position"], int) and data["position"] >= 1


def assert_curb_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["curb_zone_id"], str)
    assert isinstance(data["trip_id"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_trip(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["trip_kind"] in ("PICKUP", "DEADHEAD")
    assert isinstance(data["is_wheelchair_trip"], bool)
    assert data["status"] in ("DISPATCHED", "PICKED_UP", "COMPLETED", "CANCELLED", "VOIDED")
    assert isinstance(data["provisional_fee_cents"], int)


def assert_violation(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert data["violation_type"] in ("STAGING", "CURB", "AVI_MISMATCH", "NO_DECAL", "WAV_SHORTFALL")
    assert data["source"] in ("MANUAL", "SYSTEM")
    assert isinstance(data["penalty_points"], int)
    assert isinstance(data["fine_cents"], int)
    assert data["status"] in (
        "OPEN", "ASSESSED", "APPEALED", "UPHELD", "OVERTURNED", "DISMISSED", "PAID", "WAIVED"
    )


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["period_year"], int)
    assert 1 <= data["period_month"] <= 12
    assert data["status"] in ("OPEN", "CLOSED", "SETTLED")
    for f in (
        "gross_fees_cents", "admin_fee_cents", "wav_incentive_credit_cents",
        "net_due_cents", "total_trip_count", "wav_trip_count",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"
