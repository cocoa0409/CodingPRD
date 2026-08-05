"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_id_and_created(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_id_and_created(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_parcel(data: dict):
    """Parcel is a lightweight record: id + created_at, no version/updated_at (PRD §2.4)."""
    _assert_id_and_created(data)
    assert data["zoning_district"] in ["COMMERCIAL", "INDUSTRIAL", "RESIDENTIAL", "MIXED_USE"]
    assert isinstance(data["historic_overlay"], bool)
    assert isinstance(data["corridor_overlay"], bool)
    assert data["allowed_illumination"] in ["NONE", "EXTERNAL", "DIGITAL_DISPLAY"]
    assert isinstance(data["max_signs"], int)
    assert isinstance(data["active_permit_count"], int) and data["active_permit_count"] >= 0
    assert isinstance(data["available_sign_slots"], int) and data["available_sign_slots"] >= 0
    assert_parcel_slot_invariant(data)


def assert_parcel_slot_invariant(data: dict):
    """active_permit_count + available_sign_slots == max_signs, always (PRD §2.7)."""
    assert data["active_permit_count"] + data["available_sign_slots"] == data["max_signs"], (
        f"slot partition broken: {data['active_permit_count']} + "
        f"{data['available_sign_slots']} != {data['max_signs']}"
    )


def assert_applicant(data: dict):
    _assert_id_and_created(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_inspector(data: dict):
    _assert_id_and_created(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_application(data: dict):
    _assert_versioned(data)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert data["sign_type"] in ["WALL", "MONUMENT", "DIGITAL"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "PERMITTED"]
    assert data["dimensional_review"] in ["PENDING", "PASS", "FAIL"]
    assert data["overlay_review"] in [
        "PENDING", "CLEARED", "VARIANCE_REQUIRED", "VARIANCE_GRANTED"
    ]


def assert_variance(data: dict):
    _assert_versioned(data)
    assert isinstance(data["application_id"], str)
    assert data["kind"] in ["AREA", "HEIGHT", "SETBACK", "HISTORIC", "ILLUMINATION"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "GRANTED", "DENIED"
    ]


def assert_permit(data: dict):
    _assert_versioned(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["fee_charged_cents"], int)
    assert isinstance(data["fee_paid"], bool)
    assert isinstance(data["fee_refunded_cents"], int)
    assert data["status"] in ["ISSUED", "ACTIVE", "EXPIRED", "REVOKED"]


def assert_inspection(data: dict):
    _assert_versioned(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "CANCELLED"]


def assert_non_conforming(data: dict):
    _assert_versioned(data)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["original_value_cents"], int)
    assert isinstance(data["straight_line_value_cents"], int)
    assert isinstance(data["declining_balance_value_cents"], int)
    assert data["status"] in ["ACTIVE", "AMORTIZED"]


def assert_violation(data: dict):
    _assert_versioned(data)
    assert isinstance(data["parcel_id"], str)
    assert data["kind"] in ["NO_PERMIT", "EXCEEDS_PERMIT", "ILLEGAL_ILLUMINATION", "ABANDONED"]
    assert data["status"] in ["OPEN", "CURED", "ESCALATED"]


def assert_removal_order(data: dict):
    """Removal order is append-only: id + created_at, no version/updated_at (PRD §2.4, §3.7)."""
    _assert_id_and_created(data)
    assert isinstance(data["violation_id"], str)
    assert data["status"] == "ISSUED"


def assert_billboard(data: dict):
    _assert_versioned(data)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["face_count"], int)
    assert isinstance(data["is_digital"], bool)
    assert data["registration_status"] in ["UNREGISTERED", "REGISTERED", "LAPSED"]
    assert isinstance(data["registration_fee_collected_cents"], int)


def assert_lease(data: dict):
    _assert_versioned(data)
    assert isinstance(data["billboard_id"], str)
    assert isinstance(data["lessee_name"], str)
    assert data["status"] in ["ACTIVE", "TERMINATED", "EXPIRED", "SUSPENDED"]
