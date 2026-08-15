"""Entity assertions and domain invariant checkers."""
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_same_instant(actual: str, expected: str, msg: str = ""):
    """Compare two ISO-8601 timestamps by instant, not by byte format.

    The PRD pins the three-fractional-digit format only for `created_at`,
    `updated_at`, and `api_request_timestamp` (sections 2.2/2.5); every other
    datetime field (collection_date, service_date, ...) carries an instant,
    so equality is asserted on the parsed instant.
    """
    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert _parse(actual) == _parse(expected), \
        msg or f"{actual} != {expected} (instant mismatch)"


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_append_only_fields(data: dict, entity: str):
    """Append-only records carry only id + created_at (PRD section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert is_iso8601_timestamp(data.get("window_start", "")), \
        "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), \
        "window_end must be ISO 8601"
    assert isinstance(data["target_diversion_rate"], (int, float))
    assert data["status"] in ["DRAFT", "PUBLISHED", "ACTIVE", "CLOSED"]
    assert data["posture"] in ["NORMAL", "RESTRICTED"]
    assert isinstance(data["open_ticket_count"], int)
    assert isinstance(data["mulch_produced_cy"], (int, float))
    assert isinstance(data["mulch_allocated_participant_cy"], (int, float))
    assert isinstance(data["mulch_allocated_general_cy"], (int, float))
    assert isinstance(data["participant_remaining_cy"], (int, float))
    assert isinstance(data["general_remaining_cy"], (int, float))


def assert_site(data: dict):
    _assert_common_fields(data, "DropOffSite")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["capacity_cy"], (int, float))
    assert is_iso8601_timestamp(data.get("open_date", "")), \
        "open_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("close_date", "")), \
        "close_date must be ISO 8601"
    assert isinstance(data["volunteer_slots_per_role"], int)
    assert data["status"] in ["PLANNED", "OPEN", "SUSPENDED", "CLOSING", "CLOSED"]
    assert isinstance(data["stockpile_cy"], (int, float))


def assert_zone(data: dict):
    _assert_common_fields(data, "ServiceZone")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert is_iso8601_timestamp(data.get("collection_date", "")), \
        "collection_date must be ISO 8601"
    assert isinstance(data["daily_tree_capacity"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["reserved_trees"], int)
    assert isinstance(data["remaining_capacity"], int)
    assert isinstance(data["projected_tons_provisional"], (int, float))
    assert isinstance(data["collected_tons_actual"], (int, float))


def assert_household(data: dict):
    _assert_common_fields(data, "Household")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["zone_id"], str) and data["zone_id"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["strike_count"], int)
    assert isinstance(data["curbside_eligible"], bool)


def assert_booking(data: dict):
    _assert_common_fields(data, "CurbsideBooking")
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert isinstance(data["zone_id"], str) and data["zone_id"]
    assert isinstance(data["tree_count"], int)
    assert data["size_class"] in ["SMALL", "MEDIUM", "LARGE", "MIXED"]
    assert data["status"] in [
        "CONFIRMED", "SERVICED", "MISSED", "CANCELLED", "REJECTED_CONTAMINATED",
    ]
    assert is_iso8601_timestamp(data.get("service_date", "")), \
        "service_date must be ISO 8601"
    assert data.get("actual_tons") is None or \
        isinstance(data["actual_tons"], (int, float))
    assert isinstance(data["estimated_tons"], (int, float))


def assert_intake_event(data: dict):
    _assert_append_only_fields(data, "IntakeEvent")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert data["source_type"] in [
        "RESIDENT_SELF_HAUL", "COMMERCIAL_LANDSCAPER", "CITY_CREW",
    ]
    assert isinstance(data["tree_count"], int)
    assert data["size_class"] in ["SMALL", "MEDIUM", "LARGE", "MIXED"]
    assert isinstance(data["gross_volume_cy"], (int, float))
    assert isinstance(data["net_volume_cy"], (int, float))
    assert isinstance(data["estimated_tons"], (int, float))
    assert isinstance(data["report_tons"], (int, float))
    assert is_iso8601_timestamp(data.get("recorded_at", "")), \
        "recorded_at must be ISO 8601"
    assert data["status"] in ["RECORDED", "VOIDED"]


def assert_ticket(data: dict):
    _assert_common_fields(data, "ContaminationTicket")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["category"] in [
        "DECORATIONS", "STAND_ATTACHED", "FLOCKED_TREE", "WREATH_WITH_WIRE",
        "OTHER",
    ]
    assert isinstance(data["reporter_user_id"], str)
    assert isinstance(data["reporter_role"], str)
    assert data["status"] in [
        "OPEN", "UPHELD", "DISMISSED", "APPEALED", "UPHELD_FINAL", "OVERTURNED",
    ]


def assert_chipping_run(data: dict):
    _assert_common_fields(data, "ChippingRun")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), \
        "scheduled_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("scheduled_end", "")), \
        "scheduled_end must be ISO 8601"
    assert data["material_class"] in ["MIXED_CONIFER", "HARDWOOD", "MIXED_LOAD"]
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_mulch_event(data: dict):
    _assert_common_fields(data, "MulchEvent")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data.get("claim_open_at", "")), \
        "claim_open_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("claim_close_at", "")), \
        "claim_close_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("pickup_start", "")), \
        "pickup_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("pickup_end", "")), \
        "pickup_end must be ISO 8601"
    assert isinstance(data["per_household_cap_cy"], (int, float))
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED"]


def assert_mulch_claim(data: dict):
    _assert_common_fields(data, "MulchClaim")
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert isinstance(data["requested_cy"], (int, float))
    assert data["tier"] in ["PARTICIPANT", "GENERAL"]
    assert isinstance(data["allocated_cy"], (int, float))
    assert data["status"] in [
        "CONFIRMED", "WAITLISTED", "FULFILLED", "CANCELLED", "EXPIRED",
    ]


def assert_volunteer(data: dict):
    _assert_common_fields(data, "Volunteer")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ["APPLIED", "APPROVED", "SUSPENDED"]
    assert isinstance(data["no_show_count"], int)


def assert_volunteer_shift(data: dict):
    _assert_common_fields(data, "VolunteerShift")
    assert isinstance(data["volunteer_id"], str) and data["volunteer_id"]
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert is_iso8601_timestamp(data.get("start_at", "")), \
        "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), \
        "end_at must be ISO 8601"
    assert data["shift_role"] in ["GREETER", "TRAFFIC_CONTROL", "LOADER"]
    assert data["status"] in ["SIGNED_UP", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_notification(data: dict):
    _assert_append_only_fields(data, "NotificationLog")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["kind"] in [
        "PROGRAM_PUBLISHED", "ZONE_RESCHEDULED", "BOOKING_AUTO_CANCELLED",
        "CLAIM_PROMOTED", "SITE_CLOSING", "MULCH_EVENT_OPENED",
    ]
    assert isinstance(data["message"], str)


def assert_diversion_report(data: dict):
    _assert_common_fields(data, "DiversionReport")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert is_iso8601_timestamp(data.get("period_start", "")), \
        "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), \
        "period_end must be ISO 8601"
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["collected_tons"], (int, float))
    assert isinstance(data["diverted_tons"], (int, float))
    assert isinstance(data["disposed_tons"], (int, float))
    assert isinstance(data["diversion_rate"], (int, float))
    assert data["grade"] in ["NO_DATA", "A", "B", "C"]
    assert isinstance(data["below_target"], bool)


def assert_zone_capacity_invariant(zone: dict):
    """reserved_trees + remaining_capacity == daily_tree_capacity always."""
    assert zone["reserved_trees"] + zone["remaining_capacity"] == \
        zone["daily_tree_capacity"], (
        f"route capacity invariant violated: {zone['reserved_trees']} + "
        f"{zone['remaining_capacity']} != {zone['daily_tree_capacity']}"
    )


def assert_program_pool_invariants(program: dict):
    """Pool accounting: remaining figures derive from produced and allocations."""
    produced = program["mulch_produced_cy"]
    participant_pool = round(0.60 * produced + 1e-9, 2)
    general_pool = round(produced - participant_pool, 2)
    assert program["participant_remaining_cy"] == pytest.approx(
        participant_pool - program["mulch_allocated_participant_cy"],
        abs=1e-6), (
        f"participant_remaining_cy mismatch: {program['participant_remaining_cy']}"
    )
    assert program["general_remaining_cy"] == pytest.approx(
        general_pool - program["mulch_allocated_general_cy"], abs=1e-6), (
        f"general_remaining_cy mismatch: {program['general_remaining_cy']}"
    )
