"""Entity assertions and domain invariant checkers."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AcceptancePolicy,
    AppointmentStatus,
    CompatibilityClass,
    ContainerStatus,
    ContainmentStatus,
    Disposition,
    EligibilityStatus,
    LaneAssignmentStatus,
    LifecycleStatus,
    ManifestStatus,
    Posture,
    PostureOverride,
    SiteStatus,
    StafferStatus,
)


def _members(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity: str = "resource"):
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 UTC instant"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 UTC instant"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_program(data: dict):
    assert_common_fields(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fiscal_year"], int)
    assert 2020 <= data["fiscal_year"] <= 2100
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert data["cost_per_participant_ceiling_cents"] > 0
    assert data["staff_hourly_rate_cents"] > 0
    assert isinstance(data["eligible_jurisdiction_codes"], list)
    assert len(data["eligible_jurisdiction_codes"]) >= 1
    assert data["posture"] in _members(Posture)
    assert data["posture_override"] in _members(PostureOverride)
    for counter in (
        "budget_encumbered_cents",
        "budget_in_transit_cents",
        "budget_spent_cents",
        "open_containment_deficiency_count",
        "budget_alert_count",
        "participant_count_ytd",
    ):
        assert isinstance(data[counter], int), f"Program.{counter} must be an integer"
        assert data[counter] >= 0, f"Program.{counter} must not go negative"
    assert data["tonnage_ytd_kg"] >= 0


def assert_site(data: dict):
    assert_common_fields(data, "Site")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["impervious_surface"], bool)
    assert data["secondary_containment_liters"] >= 0
    assert data["storm_drain_distance_m"] >= 0
    assert data["lane_count"] >= 1
    assert data["status"] in _members(SiteStatus)
    assert data["last_inspection_result"] in (None, "PASS", "FAIL")


def assert_material_category(data: dict):
    assert_common_fields(data, "MaterialCategory")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["acceptance_policy"] in _members(AcceptancePolicy)
    assert data["compatibility_class"] in _members(CompatibilityClass)
    assert isinstance(data["dot_hazard_class"], str)
    assert data["max_kg_per_resident_per_event"] > 0
    assert data["max_kg_per_resident_per_year"] > 0
    assert data["disposal_rate_cents_per_kg"] >= 0
    assert isinstance(data["business_referral_program_code"], str)


def assert_resident(data: dict):
    assert_common_fields(data, "Resident")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["street_address"], str) and data["street_address"]
    assert isinstance(data["claimed_jurisdiction_code"], str)
    assert data["eligibility_status"] in _members(EligibilityStatus)
    assert data["annual_quantity_reserved_kg"] >= 0
    assert data["annual_quantity_settled_kg"] >= 0
    assert data["no_show_strike_count"] >= 0
    assert data["completed_visit_count"] >= 0


def assert_collection_event(data: dict):
    assert_common_fields(data, "CollectionEvent")
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["site_id"])
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["lifecycle_status"] in _members(LifecycleStatus)
    assert data["containment_status"] in _members(ContainmentStatus)
    assert data["event_date"] == data["window_start_utc"][:10]
    assert data["window_duration_hours"] > 0
    assert data["min_viable_registrations"] >= 0
    for counter in (
        "open_lane_count",
        "slot_capacity",
        "reserved_slot_count",
        "participant_count",
        "staffing_cost_cents",
        "projected_cost_per_participant_cents",
        "discrepancy_container_count",
    ):
        assert isinstance(data[counter], int), f"CollectionEvent.{counter} must be an integer"
        assert data[counter] >= 0, f"CollectionEvent.{counter} must not go negative"
    assert data["certified_staff_hours"] >= 0
    assert data["accepted_tonnage_kg"] >= 0
    assert data["rejected_tonnage_kg"] >= 0


def assert_staffer(data: dict):
    assert_common_fields(data, "Staffer")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_code"] in ("TRAFFIC", "UNLOAD", "CHEMIST", "SUPERVISOR")
    assert isinstance(data["hazwoper_expires_on"], str)
    assert len(data["hazwoper_expires_on"]) == 10
    assert data["status"] in _members(StafferStatus)
    assert data["assigned_hours"] >= 0


def assert_lane_assignment(data: dict):
    assert_common_fields(data, "LaneAssignment")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["staffer_id"])
    assert data["lane_number"] >= 1
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert 0 < data["duration_hours"] <= 12.0
    assert data["status"] in _members(LaneAssignmentStatus)


def assert_appointment(data: dict):
    assert_common_fields(data, "Appointment")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["resident_id"])
    assert is_iso8601_timestamp(data["slot_start_utc"])
    assert data["waste_origin"] in ("HOUSEHOLD", "BUSINESS")
    assert data["declared_total_kg"] > 0
    assert isinstance(data["declared_category_ids"], list)
    assert len(data["declared_category_ids"]) >= 1
    assert data["vehicle_count"] in (1, 2)
    assert data["status"] in _members(AppointmentStatus)
    assert data["waitlist_reason"] in (None, "CAPACITY", "CONTAINMENT_DEFICIENCY")
    assert isinstance(data["queue_seq"], int) and data["queue_seq"] >= 1
    assert data["reserved_kg"] >= 0
    assert data["settled_kg"] >= 0


def assert_dropoff_line(data: dict):
    assert_common_fields(data, "DropoffLine")
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["material_category_id"])
    assert data["declared_kg"] >= 0
    assert data["net_weight_kg"] > 0
    assert data["disposition"] in _members(Disposition)
    assert data["estimated_disposal_cost_cents"] >= 0
    assert isinstance(data["screened_by_user_id"], str)


def assert_packed_container(data: dict):
    assert_common_fields(data, "PackedContainer")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["container_code"], str) and data["container_code"]
    assert data["compatibility_class"] in _members(CompatibilityClass)
    assert data["capacity_kg"] > 0
    assert data["status"] in _members(ContainerStatus)
    assert data["line_count"] >= 0
    assert data["net_weight_kg"] >= 0
    assert data["estimated_disposal_cost_cents"] >= 0
    assert isinstance(data["discrepancy_flag"], bool)


def assert_manifest(data: dict):
    assert_common_fields(data, "Manifest")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["manifest_tracking_number"], str)
    assert isinstance(data["tsdf_epa_id"], str)
    assert data["status"] in _members(ManifestStatus)
    assert isinstance(data["container_ids"], list)
    assert data["net_weight_kg"] >= 0
    assert data["estimated_disposal_cost_cents"] >= 0
    assert data["blended_rate_cents_per_kg"] >= 0
    assert data["invoiced_disposal_cost_cents"] >= 0


# ─── Domain invariant checkers ────────────────────────

def assert_kg(actual, expected, label="mass"):
    """Mass is carried to three decimal places."""
    assert actual == pytest.approx(expected, abs=0.0005), (
        f"Expected {label} of {expected} kg, got {actual}"
    )


def assert_hours(actual, expected, label="duration"):
    """Durations are carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {label} of {expected} h, got {actual}"
    )


def assert_rate(actual, expected, label="blended rate"):
    """The blended disposal rate is carried to four decimal places."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"Expected {label} of {expected} cents/kg, got {actual}"
    )


def assert_no_write(before: dict, after: dict, label="row"):
    """A rejected request writes nothing: no version movement, no timestamp refresh."""
    assert after["version"] == before["version"], (
        f"{label} version moved from {before['version']} to {after['version']} "
        f"on a rejected request"
    )
    assert after["updated_at"] == before["updated_at"], (
        f"{label} updated_at was refreshed on a rejected request"
    )


def assert_program_invariants(data: dict):
    """Budget buckets never go negative and the alert counter never decrements."""
    assert data["budget_encumbered_cents"] >= 0
    assert data["budget_in_transit_cents"] >= 0
    assert data["budget_spent_cents"] >= 0
    assert data["budget_alert_count"] >= 0
    assert data["posture"] in _members(Posture)


def assert_containment_finding(entry: dict, origin: str, result: str):
    """One element of the append-only containment findings log."""
    assert entry.get("origin") == origin, (
        f"Expected a finding with origin {origin}, got {entry.get('origin')}"
    )
    assert entry.get("result") == result, (
        f"Expected a finding with result {result}, got {entry.get('result')}"
    )
