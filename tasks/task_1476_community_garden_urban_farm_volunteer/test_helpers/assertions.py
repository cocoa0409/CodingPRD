"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} payload must be an object, got {data!r}"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_volunteer(data: dict):
    _assert_common(data, "Volunteer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["is_minor"], bool)
    assert data["orientation_status"] in ("PENDING", "ORIENTED")
    assert data["waiver_status"] in ("UNSIGNED", "SIGNED", "EXPIRED")
    assert data["standing"] in ("GOOD", "PROBATION", "SUSPENDED")
    for flag in ("can_supervise", "produce_safety_certified", "tool_safety_certified"):
        assert isinstance(data[flag], bool), f"Volunteer.{flag} must be boolean"
    for counter in ("total_service_minutes", "no_show_count", "held_key_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_certification(data: dict):
    _assert_common(data, "TrainingCertification")
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["cert_type"] in ("PRODUCE_SAFETY", "SUPERVISION", "TOOL_SAFETY")
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_season(data: dict):
    _assert_common(data, "Season")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["water_budget_gallons"], int)
    for counter in (
        "water_committed_gallons",
        "water_actual_gallons",
        "water_remaining_gallons",
    ):
        assert isinstance(data[counter], int), f"Season.{counter} must be an integer"
    assert data["status"] in (
        "DRAFT",
        "OPEN_ENROLLMENT",
        "PLANTING",
        "GROWING",
        "HARVESTING",
        "RECONCILIATION",
        "CLOSED",
        "CANCELLED",
    )


def assert_water_partition(data: dict):
    """The season water ledger always partitions the budget (PRD §3.3)."""
    total = (
        data["water_committed_gallons"]
        + data["water_actual_gallons"]
        + data["water_remaining_gallons"]
    )
    assert total == data["water_budget_gallons"], (
        f"water partition broken: {data['water_committed_gallons']} + "
        f"{data['water_actual_gallons']} + {data['water_remaining_gallons']} != "
        f"{data['water_budget_gallons']}"
    )


def assert_bed(data: dict):
    _assert_common(data, "GardenBed")
    assert isinstance(data["bed_code"], str) and data["bed_code"]
    assert isinstance(data["size_sq_ft"], int) and data["size_sq_ft"] > 0
    assert data["sun_exposure"] in ("FULL", "PARTIAL", "SHADE")
    assert isinstance(data["irrigation_zone"], str)
    assert isinstance(data["allocated_sq_ft"], int) and data["allocated_sq_ft"] >= 0
    assert data["status"] in (
        "FALLOW",
        "RESERVED",
        "PLANTED",
        "GROWING",
        "HARVEST_OPEN",
        "POST_HARVEST",
        "OUT_OF_SERVICE",
    )


def assert_crop_plan(data: dict):
    _assert_common(data, "CropPlan")
    for fk in ("season_id", "bed_id", "proposer_volunteer_id"):
        assert is_valid_uuid(data.get(fk, "")), f"CropPlan.{fk} must be a UUID"
    assert isinstance(data["crop_type"], str) and data["crop_type"]
    assert isinstance(data["plant_family"], str) and data["plant_family"]
    assert isinstance(data["requested_sq_ft"], int) and data["requested_sq_ft"] > 0
    assert isinstance(data["planned_start_date"], str)
    assert isinstance(data["planned_end_date"], str)
    assert data["status"] in (
        "PROPOSED",
        "APPROVED",
        "REJECTED",
        "PLANTED",
        "HARVESTING",
        "COMPLETE",
        "WITHDRAWN",
    )


def assert_shift_slot(data: dict):
    _assert_common(data, "ShiftSlot")
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["task_type"] in (
        "PLANTING",
        "WEEDING",
        "HARVEST",
        "IRRIGATION",
        "COMPOST",
        "REPAIR",
        "OUTREACH",
    )
    assert isinstance(data["capacity_total"], int) and data["capacity_total"] > 0
    assert isinstance(data["capacity_youth"], int) and data["capacity_youth"] >= 0
    for counter in ("confirmed_count", "confirmed_youth_count", "waitlist_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["status"] in (
        "DRAFT",
        "OPEN",
        "FULL",
        "LOCKED",
        "COMPLETED",
        "CANCELLED",
    )


def assert_shift_signup(data: dict):
    _assert_common(data, "ShiftSignup")
    assert is_valid_uuid(data.get("slot_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert isinstance(data["is_youth"], bool)
    assert isinstance(data["credited_minutes"], int) and data["credited_minutes"] >= 0
    assert data["status"] in (
        "REQUESTED",
        "CONFIRMED",
        "WAITLISTED",
        "CHECKED_IN",
        "COMPLETED",
        "NO_SHOW",
        "CANCELLED",
    )


def assert_group_booking(data: dict):
    _assert_common(data, "GroupBooking")
    assert is_valid_uuid(data.get("slot_id", ""))
    assert is_valid_uuid(data.get("leader_volunteer_id", ""))
    assert isinstance(data["organization_name"], str) and data["organization_name"]
    assert isinstance(data["member_count"], int) and data["member_count"] > 0
    assert isinstance(data["minor_count"], int) and data["minor_count"] >= 0
    assert isinstance(data["chaperone_count"], int) and data["chaperone_count"] >= 0
    assert isinstance(data["required_chaperones"], int)
    assert data["status"] in (
        "REQUESTED",
        "CONFIRMED",
        "CHECKED_IN",
        "COMPLETED",
        "CANCELLED",
        "REJECTED",
    )


def assert_shed_key(data: dict):
    _assert_common(data, "ShedKey")
    assert isinstance(data["key_code"], str) and data["key_code"]
    assert data["status"] in ("AVAILABLE", "CHECKED_OUT", "OVERDUE", "LOST", "RETIRED")


def assert_tool(data: dict):
    _assert_common(data, "ToolItem")
    assert isinstance(data["tool_name"], str) and data["tool_name"]
    assert data["category"] in ("HAND", "POWER", "IRRIGATION", "SAFETY", "OTHER")
    assert isinstance(data["total_count"], int) and data["total_count"] > 0
    for counter in (
        "available_count",
        "checked_out_count",
        "in_maintenance_count",
        "written_off_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["status"] in ("IN_SERVICE", "RETIRED")


def assert_tool_conservation(data: dict):
    """Physical units are conserved: total == available + checked_out +
    in_maintenance + written_off (PRD §3.7)."""
    total = (
        data["available_count"]
        + data["checked_out_count"]
        + data["in_maintenance_count"]
        + data["written_off_count"]
    )
    assert total == data["total_count"], (
        f"tool unit conservation broken: {data['available_count']} + "
        f"{data['checked_out_count']} + {data['in_maintenance_count']} + "
        f"{data['written_off_count']} != {data['total_count']}"
    )


def assert_tool_checkout(data: dict):
    _assert_common(data, "ToolCheckout")
    assert is_valid_uuid(data.get("tool_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] > 0
    assert isinstance(data["qty_returned"], int) and data["qty_returned"] >= 0
    assert data["status"] in (
        "OPEN",
        "PARTIAL_RETURN",
        "RETURNED",
        "CLOSED_LOSS",
        "AUTO_CLOSED",
    )


def assert_harvest_log(data: dict):
    _assert_common(data, "HarvestLog")
    assert is_valid_uuid(data.get("season_id", ""))
    assert is_valid_uuid(data.get("bed_id", ""))
    assert is_valid_uuid(data.get("logged_by_volunteer_id", ""))
    assert isinstance(data["crop_type"], str) and data["crop_type"]
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] > 0
    assert data["quality_grade"] in ("A", "B", "C")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "VERIFIED",
        "SPLIT_FINALIZED",
        "REJECTED",
        "DISCARDED",
    )


def assert_recipient(data: dict):
    _assert_common(data, "DonationRecipient")
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert (
        isinstance(data["weekly_capacity_grams"], int)
        and data["weekly_capacity_grams"] > 0
    )
    assert isinstance(data["priority_tier"], int)
    assert isinstance(data["accepts_grade_c"], bool)
    assert isinstance(data["active"], bool)
    assert isinstance(data["committed_this_week_grams"], int)


def assert_allocation(data: dict):
    _assert_common(data, "DonationAllocation")
    assert is_valid_uuid(data.get("harvest_log_id", ""))
    assert isinstance(data["volunteer_share_grams"], int)
    assert isinstance(data["donatable_grams"], int)
    assert isinstance(data["lines"], list)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "DISTRIBUTED")


def assert_irrigation_schedule(data: dict):
    _assert_common(data, "IrrigationSchedule")
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["zone"], str) and data["zone"]
    assert isinstance(data["planned_gallons"], int) and data["planned_gallons"] > 0
    assert isinstance(data["variance_flag"], bool)
    assert data["status"] in (
        "SCHEDULED",
        "DUE",
        "MISSED",
        "LOGGED",
        "RECONCILED",
        "CANCELLED",
    )
