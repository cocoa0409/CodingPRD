"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, *, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_no_version_fields(data: dict, entity: str):
    assert "version" not in data, f"{entity} is an immutable event row: no version field"
    assert "updated_at" not in data, f"{entity} is an immutable event row: no updated_at field"


def assert_donor(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["donor_type"] in ("INDIVIDUAL", "ORGANIZATION")
    assert data["receipt_method"] in ("FLAT_SCHEDULE", "FMV_COMPARABLE")
    assert isinstance(data["donated_bike_count"], int) and data["donated_bike_count"] >= 0
    assert isinstance(data["lifetime_receipt_value_cents"], int)


def assert_bike(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "RECEIVED", "TRIAGED", "IN_REFURBISHMENT", "SAFETY_REVIEW",
        "READY_FOR_DISPOSITION", "RESERVED_FOR_GRADUATE", "SOLD", "GIFTED",
        "HARVEST_QUEUE", "HARVESTED", "SCRAP_PENDING", "SCRAPPED",
    )
    assert data["bike_type"] in ("ROAD", "MTB", "HYBRID", "KIDS", "BMX", "CARGO")
    assert isinstance(data["parts_cost_cents"], int) and data["parts_cost_cents"] >= 0
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    if data["condition_grade"] is not None:
        assert data["condition_grade"] in ("A", "B", "C", "D")
    if data["latest_inspection_result"] is not None:
        assert data["latest_inspection_result"] in ("PASS", "FAIL")


def assert_part(data: dict):
    _assert_common(data)
    assert data["category"] in (
        "DRIVETRAIN", "BRAKES", "WHEELS", "FRAME", "COCKPIT", "SADDLE",
        "TIRES", "HELMET", "MISC",
    )
    if data["category"] == "HELMET":
        assert data["helmet_size"] in ("XS", "S", "M", "L", "XL")
    else:
        assert data.get("helmet_size") in (None,)
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert data["low_stock"] == (data["quantity_on_hand"] <= data["reorder_threshold"])


def assert_volunteer(data: dict):
    _assert_common(data)
    assert data["skill_level"] in ("TRAINEE", "APPRENTICE", "JOURNEYMAN", "LEAD_MECHANIC")
    assert data["engagement_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["training_hours"], int) and data["training_hours"] >= 0
    assert isinstance(data["sessions_attended"], int) and data["sessions_attended"] >= 0
    assert isinstance(data["inspections_conducted"], int) and data["inspections_conducted"] >= 0
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert isinstance(data["shift_minutes"], int) and data["shift_minutes"] >= 0


def assert_training_session(data: dict):
    _assert_common(data)
    assert data["level"] in ("BASIC", "ADVANCED", "LEAD_CERT")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] >= 1
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and 0 <= data["enrolled_count"] <= data["capacity"]


def assert_attendance(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW", "DROPPED")


def assert_shift(data: dict):
    _assert_common(data)
    assert data["shift_role"] in ("MECHANIC", "INTAKE", "FLOOR")
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_participant(data: dict):
    _assert_common(data)
    assert data["age_group"] in ("YOUTH", "ADULT")
    assert data["status"] in ("ENROLLED", "HOURS_MET", "GRADUATED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["required_hours"], int)
    assert isinstance(data["hours_earned"], int) and data["hours_earned"] >= 0
    expected = 8 if data["age_group"] == "YOUTH" else 12
    assert data["required_hours"] == expected, "required_hours must derive from age_group"


def assert_hour_log(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "VOIDED")
    assert data["activity_type"] in ("REFURB_WORK", "SHOP_HELP", "OUTREACH", "TRAINING_ASSIST")
    assert isinstance(data["hours"], int) and 1 <= data["hours"] <= 6


def assert_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "COMPLETED", "VOIDED")
    assert isinstance(data["quoted_price_cents"], int)
    if data["status"] == "COMPLETED":
        assert isinstance(data["final_price_cents"], int)
        assert isinstance(data["grand_total_cents"], int)
        assert isinstance(data["donation_cents"], int)
        assert data["grand_total_cents"] == data["final_price_cents"] + data["donation_cents"]


def assert_award(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "FULFILLED", "CANCELLED")
    assert data["recipient_age_group"] in ("YOUTH", "ADULT")


def assert_membership(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PRO")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "IN_USE", "CLOSED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["stand_number"], int) and 1 <= data["stand_number"] <= 4


def assert_scrap_ticket(data: dict):
    _assert_common(data)
    assert data["material"] in ("STEEL", "ALUMINUM", "MIXED")
    assert data["status"] in ("OPEN", "PICKED_UP")
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0


def assert_part_harvest(data: dict):
    _assert_common(data, versioned=False)
    _assert_no_version_fields(data, "PartHarvest")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_part_usage(data: dict):
    _assert_common(data, versioned=False)
    _assert_no_version_fields(data, "PartUsage")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("COMMITTED", "VOIDED")
    assert isinstance(data["unit_cost_cents"], int)


def assert_safety_inspection(data: dict):
    _assert_common(data, versioned=False)
    _assert_no_version_fields(data, "SafetyInspection")
    assert data["result"] in ("PASS", "FAIL")
    checklist = data["checklist"]
    for key in ("brakes", "steering", "tires", "drivetrain", "reflectors"):
        assert isinstance(checklist.get(key), bool), f"checklist.{key} must be boolean"
    if data["result"] == "PASS":
        assert all(checklist.values()), "PASS implies all checklist items true"


def assert_helmet_distribution(data: dict):
    _assert_common(data, versioned=False)
    _assert_no_version_fields(data, "HelmetDistribution")
    assert data["recipient_kind"] in (
        "EARN_A_BIKE_GRADUATE", "SALE_BUYER", "GIVEAWAY_RECIPIENT", "COMMUNITY",
    )
