"""Entity assertions and domain invariant checkers (PRD sections 2.2, 2.4)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

EVENT_POSTURES = [
    "PLANNING", "REGISTRATION_OPEN", "PUBLISHED", "EVENT_OPEN",
    "RESTRICTED", "COMPLETED", "CANCELLED",
]
RESTRICTION_LEVELS = ["GREEN", "YELLOW", "RED"]
AGREEMENT_STATUSES = ["SUBMITTED", "SIGNED", "SUPERSEDED"]
UNIT_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "SUSPENDED"]
PARTICIPANT_STATUSES = [
    "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "VETTED",
    "CHECKED_IN", "REJECTED", "WITHDRAWN",
]
EQUIPMENT_STATUSES = [
    "DECLARED", "INSPECTION_DUE", "PASSED", "FAILED",
    "WAIVED", "BANNED", "WITHDRAWN",
]
INSPECTION_STATUSES = ["SCHEDULED", "RECORDED_PASS", "RECORDED_FAIL", "WAIVED", "CANCELLED"]
AREA_STATUSES = ["ACTIVE", "CLOSED"]
ALLOCATION_STATUSES = ["ACTIVE", "RELEASED"]
SLOT_STATUSES = ["PROPOSED", "CONFIRMED", "DONE", "CANCELLED"]
ORDER_STATUSES = ["RESERVED", "PAID", "CHECKED_IN", "REFUNDED", "CANCELLED"]
PASS_STATUSES = ["ACTIVE", "VOIDED"]
VENDOR_STATUSES = ["APPLIED", "APPROVED", "CONTRACTED", "SETTLED", "REVOKED"]
ALERT_STATUSES = ["OPEN", "RESOLVED"]


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer mutation counter"
    )


def assert_event(data: dict):
    _assert_common_fields(data, "Event")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert is_iso8601_timestamp(data["event_starts_at"])
    assert is_iso8601_timestamp(data["event_ends_at"])
    for f in ("adult_day_price_cents", "child_day_price_cents",
              "adult_weekend_price_cents", "child_weekend_price_cents",
              "service_fee_cents", "required_liability_cents",
              "max_minor_per_adult", "vendor_frontage_rate_cents",
              "vendor_min_fee_cents", "vendor_late_insurance_surcharge_cents"):
        assert isinstance(data[f], int), f"Event.{f} must be integer cents/count"
    assert data["event_posture"] in EVENT_POSTURES
    assert data["restriction_level"] in RESTRICTION_LEVELS
    assert isinstance(data["approved_combatant_count"], int) and data["approved_combatant_count"] >= 0


def assert_agreement(data: dict):
    _assert_common_fields(data, "Agreement")
    assert data["agreement_type"] in ("LANDOWNER_USE", "INSURANCE_LIABILITY")
    assert isinstance(data["document_ref"], str) and data["document_ref"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in AGREEMENT_STATUSES


def assert_unit(data: dict):
    _assert_common_fields(data, "Unit")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit_type"] in ("MILITARY", "CIVILIAN", "ARTILLERY")
    assert data["status"] in UNIT_STATUSES


def assert_participant(data: dict):
    _assert_common_fields(data, "Participant")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["age_at_event"], int)
    assert data["impression_class"] in ("COMBATANT", "CIVILIAN", "ARTILLERY_CREW")
    assert isinstance(data["is_minor"], bool)
    assert data["status"] in PARTICIPANT_STATUSES


def assert_equipment_item(data: dict):
    _assert_common_fields(data, "EquipmentItem")
    assert isinstance(data["participant_id"], str) and data["participant_id"]
    assert data["item_type"] in ("FIREARM", "EDGED", "CANNON", "CAMP_FLAME", "TENTAGE", "OTHER")
    assert data["status"] in EQUIPMENT_STATUSES
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert isinstance(data["equipment_item_id"], str) and data["equipment_item_id"]
    assert data["inspection_kind"] in ("SAFETY", "AUTHENTICITY")
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["status"] in INSPECTION_STATUSES


def assert_site_area(data: dict):
    _assert_common_fields(data, "SiteArea")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert data["area_kind"] in ("CAMP", "DEMO", "PARKING", "SUTLER", "SPECTATOR")
    assert isinstance(data["capacity_units"], int)
    assert data["status"] in AREA_STATUSES
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0


def assert_allocation(data: dict):
    _assert_common_fields(data, "AreaAllocation")
    assert isinstance(data["site_area_id"], str) and data["site_area_id"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["status"] in ALLOCATION_STATUSES


def assert_program_slot(data: dict):
    _assert_common_fields(data, "ProgramSlot")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["site_area_id"], str) and data["site_area_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in SLOT_STATUSES


def assert_ticket_order(data: dict):
    _assert_common_fields(data, "TicketOrder")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["buyer_user_id"], str) and data["buyer_user_id"]
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["quoted_total_cents"], int) and data["quoted_total_cents"] >= 0


def assert_parking_pass(data: dict):
    _assert_common_fields(data, "ParkingPass")
    assert isinstance(data["ticket_order_id"], str) and data["ticket_order_id"]
    assert isinstance(data["site_area_id"], str) and data["site_area_id"]
    assert isinstance(data["vehicle_plate"], str) and data["vehicle_plate"]
    assert data["vehicle_class"] in ("STANDARD", "OVERSIZE")
    assert data["status"] in PASS_STATUSES
    assert data["units_used"] in (1, 2)


def assert_vendor(data: dict):
    _assert_common_fields(data, "Vendor")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["frontage_feet"], int) and data["frontage_feet"] >= 1
    assert isinstance(data["requested_days"], int) and data["requested_days"] >= 1
    assert data["status"] in VENDOR_STATUSES
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0


def assert_contingency_alert(data: dict):
    _assert_common_fields(data, "ContingencyAlert")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert data["alert_kind"] in ("WEATHER", "FIRE", "SECURITY")
    assert data["severity"] in ("ADVISORY", "WATCH", "RED_FLAG")
    assert data["status"] in ALERT_STATUSES
