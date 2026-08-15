"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

EPISODE_STATUSES = ["STANDBY", "ACTIVATING", "ACTIVE", "DEACTIVATING",
                    "DEACTIVATED", "CLOSED"]
SITE_ACTIVATION_STATUSES = ["OPENING", "OPEN", "DRAINING", "CLOSED"]
STAY_STATUSES = ["RESERVED", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW",
                 "CANCELLED", "TRANSFERRED_OUT"]
DISPATCH_STATUSES = ["REQUESTED", "ASSIGNED", "ARRIVED", "CANCELLED"]
SHIFT_STATUSES = ["PLANNED", "CONFIRMED", "COMPLETED", "CANCELLED"]
DONATION_STATUSES = ["PLEDGED", "RECEIVED"]
MEAL_SERVICE_STATUSES = ["PLANNED", "SERVED"]
INCIDENT_STATUSES = ["REPORTED", "ESCALATED", "RESOLVED"]
AAR_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED"]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant for value comparison (rendering format —
    fractional digits or a 'Z' suffix — is left to the implementation)."""
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"


def _assert_versioned_fields(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_episode(data: dict):
    _assert_versioned_fields(data)
    assert data["mode"] in ("WARMING", "COOLING")
    assert isinstance(data["threshold_f"], (int, float))
    assert isinstance(data["sustained_hours_required"], int)
    assert data["status"] in EPISODE_STATUSES
    assert isinstance(data["trigger_met"], bool)
    assert isinstance(data["breach_run_minutes"], int)
    assert isinstance(data["extension_count"], int)
    assert isinstance(data["ops_run_index"], int)
    for nullable in ("activated_at", "deactivated_at"):
        if data.get(nullable) is not None:
            assert is_iso8601_timestamp(data[nullable])


def assert_weather_reading(data: dict):
    """A weather reading is an append-only event log entry carrying only `id`
    and `created_at` as common fields (PRD §2.5): no updated_at, no version."""
    _assert_common_fields(data)
    assert "updated_at" not in data, "append-only reading must not carry updated_at"
    assert "version" not in data, "append-only reading must not carry version"
    assert isinstance(data.get("episode_id"), str)
    assert isinstance(data.get("observed_at"), str)
    assert isinstance(data["temp_f"], (int, float))
    assert isinstance(data["heat_index_f"], (int, float))
    assert data.get("source") in ("NWS", "MANUAL")


def assert_site(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    for cap in ("bed_capacity", "pet_capacity", "locker_capacity"):
        assert isinstance(data[cap], int) and data[cap] >= 0


def assert_site_activation(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("episode_id"), str)
    assert isinstance(data.get("site_id"), str)
    assert data["status"] in SITE_ACTIVATION_STATUSES
    # Computed stock and coverage figures are part of the read contract (PRD §4:
    # the activation read includes computed capacity, coverage and stock fields).
    assert isinstance(data["meal_stock_on_hand"], int)
    assert isinstance(data["meal_stock_projected"], int)
    assert isinstance(data["overnight_coverage_gap_minutes"], int)
    assert isinstance(data["lead_coverage_ok"], bool)
    for pool in ("beds_effective", "occupied_beds", "reserved_beds", "beds_free",
                 "pet_slots_free", "lockers_free"):
        if data.get(pool) is not None:
            assert isinstance(data[pool], int), f"{pool} must be an int when present"
    if data.get("opened_at") is not None:
        assert is_iso8601_timestamp(data["opened_at"])


def assert_staff_member(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["skills"], list)
    assert isinstance(data["active"], bool)


def assert_shift(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("site_activation_id"), str)
    assert isinstance(data.get("staff_member_id"), str)
    assert data["role_on_shift"] in ("INTAKE", "MEDICAL", "OUTREACH",
                                     "SITE_LEAD", "GENERAL")
    assert data["status"] in SHIFT_STATUSES


def assert_guest(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data["alias"], str) and data["alias"]
    assert isinstance(data["has_pets"], bool)
    assert isinstance(data["pet_count"], int)
    assert isinstance(data["bag_count"], int)
    assert isinstance(data["medical_flag"], bool)
    assert isinstance(data["medical_hold_active"], bool)


def assert_guest_stay(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("site_activation_id"), str)
    assert isinstance(data.get("guest_id"), str)
    assert data["status"] in STAY_STATUSES
    assert isinstance(data["pet_slots_used"], int)
    assert isinstance(data["lockers_used"], int)
    assert isinstance(data["transfer_sequence"], int)
    for ts in ("checked_in_at", "checked_out_at"):
        if data.get(ts) is not None:
            assert is_iso8601_timestamp(data[ts])
    for nights in ("bed_nights_provisional", "bed_nights_final"):
        if data.get(nights) is not None:
            assert isinstance(data[nights], int)


def assert_vehicle(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0


def assert_transport_dispatch(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("site_activation_id"), str)
    assert isinstance(data.get("guest_ids"), list) and len(data["guest_ids"]) >= 1
    assert data["status"] in DISPATCH_STATUSES
    assert isinstance(data["reserved_bed_count"], int)
    if data.get("arrived_at") is not None:
        assert is_iso8601_timestamp(data["arrived_at"])


def assert_donation(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("site_activation_id"), str)
    assert isinstance(data["partner_name"], str) and data["partner_name"]
    assert data["category"] in ("MEAL", "WATER", "BEDDING", "HYGIENE", "PET_SUPPLIES")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in DONATION_STATUSES


def assert_meal_service(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("site_activation_id"), str)
    assert data["meal_period"] in ("BREAKFAST", "LUNCH", "DINNER")
    assert isinstance(data["planned_meals"], int)
    assert data["status"] in MEAL_SERVICE_STATUSES


def assert_incident(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("site_activation_id"), str)
    assert data["kind"] in ("MEDICAL", "BEHAVIORAL")
    assert data["severity"] in (1, 2, 3)
    assert data["status"] in INCIDENT_STATUSES
    assert isinstance(data.get("reporter_user_id"), str)


def assert_after_action_report(data: dict):
    _assert_versioned_fields(data)
    assert isinstance(data.get("episode_id"), str)
    assert data["status"] in AAR_STATUSES
    assert isinstance(data["total_unique_guests"], int)
    assert isinstance(data["total_bed_nights"], int)
    assert isinstance(data["meals_served"], int)
    assert isinstance(data["incidents_by_severity"], dict)
    assert isinstance(data["transports_arrived"], int)


def assert_bed_conservation(site_activation: dict):
    """PRD §2.6: beds_effective always equals occupied_beds + reserved_beds +
    beds_free — the bed-conservation invariant holds at all times."""
    total = (site_activation["occupied_beds"] + site_activation["reserved_beds"]
             + site_activation["beds_free"])
    assert site_activation["beds_effective"] == total, (
        f"bed conservation violated: beds_effective "
        f"{site_activation['beds_effective']} != occupied "
        f"{site_activation['occupied_beds']} + reserved "
        f"{site_activation['reserved_beds']} + free {site_activation['beds_free']}"
    )
