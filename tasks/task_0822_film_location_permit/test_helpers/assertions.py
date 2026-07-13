"""Entity assertions for the Film Location Permit API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_APP_STATUSES = {"DRAFT", "UNDER_REVIEW", "REVISION_REQUIRED", "ISSUED",
                 "WRAP_REQUESTED", "WRAPPED", "WITHDRAWN"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_production_company(data: dict):
    _assert_versioned(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["compliance_score"], int)
    assert 0 <= data["compliance_score"] <= 100, "compliance_score clamped to [0,100]"
    for counter in ("late_wrap_count", "damage_incident_count", "missed_notification_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_officer(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"ACTIVE", "INACTIVE"}
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_application(data: dict):
    _assert_versioned(data)
    assert data["status"] in _APP_STATUSES, f"unexpected status {data.get('status')!r}"
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    for money in ("estimated_fee_cents", "final_fee_cents", "municipal_surcharge_cents",
                  "total_fee_cents", "deposit_cents", "amount_paid_cents",
                  "deposit_held_cents", "damage_cost_cents",
                  "late_wrap_penalty_cents", "deposit_refund_cents"):
        assert isinstance(data[money], int), f"{money} must be an integer number of cents"


def assert_department(data: dict):
    _assert_common(data)
    assert data["code"] in {"POLICE", "PARKING", "FIRE", "PUBLIC_WORKS"}
    assert data["trigger_condition"] in {"ALL_APPLICATIONS", "ROAD_CLOSURE_ONLY", "PARKING_ONLY", "DRONE_ONLY"}
    assert "version" not in data, "Department is immutable-by-design: no version field"


def assert_street_segment(data: dict):
    _assert_common(data)
    assert data["length_m"] > 0
    assert "version" not in data, "StreetSegment is immutable-by-design: no version field"


def assert_location_detail(data: dict):
    _assert_common(data)
    assert data["activity_type"] in {"FILMING", "EQUIPMENT_STAGING", "BASECAMP"}
    assert "version" not in data, "LocationDetail is immutable-by-design: no version field"


def assert_department_review(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED", "REVISION_REQUESTED"}


def assert_insurance_certificate(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"SUBMITTED", "VERIFIED", "REJECTED", "SUPERSEDED"}


def assert_road_closure_booking(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"PENDING", "CONFIRMED", "RELEASED", "BLOCKED"}


def assert_officer_assignment(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"PROPOSED", "CONFIRMED", "CANCELLED", "COMPLETED"}
    assert isinstance(data["billed_cost_cents"], int) and data["billed_cost_cents"] >= 0


def assert_rider(data: dict):
    _assert_versioned(data)
    assert data["rider_type"] in {"DRONE", "STILL_PHOTO"}
    assert data["status"] in {"REQUESTED", "APPROVED", "DENIED"}


def assert_notification(data: dict):
    _assert_common(data)
    assert data["notice_method"] in {"MAILED", "POSTED", "DOOR_HANGER"}
    assert "version" not in data, "NeighborhoodNotification is immutable-by-design: no version field"


def assert_ledger_entry(data: dict):
    _assert_common(data)
    assert data["entry_type"] in {"PERMIT_FEE", "DEPOSIT", "REFUND"}
    assert data["direction"] in {"DEBIT", "CREDIT"}
    assert "version" not in data, "LedgerEntry is immutable-by-design: no version field"
