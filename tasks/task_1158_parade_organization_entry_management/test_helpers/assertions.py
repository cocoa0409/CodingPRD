"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_parade(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in [
        "DRAFT", "PERMIT_PENDING", "PERMIT_GRANTED", "LOCKED",
        "LINEUP_PUBLISHED", "COMPLETED", "CANCELLED",
    ]
    assert data["posture"] in ["RESTRICTED", "OPERATIONAL", "FROZEN"]
    assert isinstance(data["approved_entry_count"], int) and data["approved_entry_count"] >= 0
    assert isinstance(data["sponsor_seconds_allocated"], int) and data["sponsor_seconds_allocated"] >= 0
    assert isinstance(data["script_finalized"], bool)


def assert_route_segment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_index"], int)
    assert data["length_meters"] > 0
    assert data["emergency_lane_width_m"] >= 3.0


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "AGENCY_REVIEW", "GRANTED", "DENIED", "REVOKED"]
    assert isinstance(data["provisional_fee_cents"], int)
    assert data["required_agency_count"] == 4
    assert isinstance(data["endorsed_count"], int) and data["endorsed_count"] >= 0
    if data["status"] == "DRAFT":
        assert data["final_fee_cents"] is None, "final_fee_cents must be null while DRAFT"
        assert data["submitted_at"] is None, "submitted_at must be null while DRAFT"


def assert_endorsement(data: dict):
    _assert_common_fields(data)
    assert data["agency_type"] in ["POLICE", "FIRE", "TRANSIT", "SANITATION"]
    assert data["status"] in ["PENDING", "ENDORSED", "REJECTED"]
    assert isinstance(data["permit_version"], int)
    if data["status"] == "PENDING":
        assert data["decided_at"] is None, "decided_at must be null while PENDING"


def assert_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert data["requested_category"] in ["FLOAT", "BAND", "WALKING_GROUP", "VEHICLE", "EQUESTRIAN"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED",
        "SUSPENDED", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["estimated_participants"], int) and data["estimated_participants"] >= 1
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["fee_paid"], bool)
    if data["status"] in ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED"):
        assert data["assigned_category"] is None, "assigned_category stays null until APPROVED"


def assert_float(data: dict):
    _assert_common_fields(data)
    assert data["length_m"] > 0 and data["width_m"] > 0 and data["height_m"] > 0
    assert data["weight_kg"] > 0
    assert data["vehicle_class"] in ["SELF_PROPELLED", "TOWED", "PUSHED"]
    assert data["fuel_type"] in ["GASOLINE", "DIESEL", "ELECTRIC", "NONE"]
    assert data["compliance_status"] in ["PENDING_INSPECTION", "CERTIFIED", "FAILED"]


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "CANCELLED"]
    if data["status"] == "SCHEDULED":
        assert data["decided_at"] is None, "decided_at must be null while SCHEDULED"


def assert_staging_area(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_slots"], int) and data["reserved_slots"] >= 0


def assert_lineup_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["position_number"], int)
    assert data["status"] in ["TENTATIVE", "CONFIRMED", "CHECKED_IN", "RELEASED", "PULLED", "NO_SHOW"]


def assert_marshal_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["marshal_user_id"], str) and data["marshal_user_id"]
    assert data["status"] in ["ASSIGNED", "CONFIRMED", "COMPLETED", "NO_SHOW"]


def assert_score_sheet(data: dict):
    _assert_common_fields(data)
    for criterion in ("creativity", "craftsmanship", "theme", "crowd_appeal"):
        assert isinstance(data[criterion], int) and 0 <= data[criterion] <= 25
    assert data["sheet_total"] == (
        data["creativity"] + data["craftsmanship"] + data["theme"] + data["crowd_appeal"]
    ), "sheet_total must equal the sum of the four criteria"
    assert data["status"] in ["DRAFT", "SUBMITTED", "FINALIZED"]


def assert_award(data: dict):
    _assert_common_fields(data)
    assert data["award_category"] in ["BEST_FLOAT", "BEST_BAND", "BEST_WALKING", "GRAND_PRIZE"]
    assert data["eligible_entry_category"] in [
        "FLOAT", "BAND", "WALKING_GROUP", "VEHICLE", "EQUESTRIAN", "ANY",
    ]
    assert data["status"] in ["PENDING", "ANNOUNCED", "PRESENTED", "CANCELLED"]
    if data["status"] == "PENDING":
        assert data["winner_entry_id"] is None, "winner_entry_id must be null while PENDING"
        assert data["announced_at"] is None, "announced_at must be null while PENDING"


def assert_sponsor(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ["GOLD", "SILVER", "BRONZE"]
    assert isinstance(data["contribution_cents"], int) and data["contribution_cents"] > 0
    assert data["status"] in ["PLEDGED", "ACTIVE", "FULFILLED", "DEFAULTED"]
    assert isinstance(data["allocated_seconds"], int) and data["allocated_seconds"] >= 0


def assert_script_item(data: dict):
    _assert_common_fields(data)
    assert data["item_type"] in ["SPONSOR_READ", "ENTRY_INTRO", "SAFETY_ANNOUNCEMENT", "AWARD_ANNOUNCEMENT"]
    assert isinstance(data["sequence_index"], int)
    assert data["duration_minutes"] > 0
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 0
    assert data["status"] in ["DRAFT", "APPROVED", "LOCKED", "CANCELLED"]


def assert_dispersal_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]
    assert isinstance(data["dispersal_corridors"], list)
