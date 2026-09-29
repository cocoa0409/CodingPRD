"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMPLIANCE_STATUSES,
    DOWNTIME_POSTURES,
    WORK_STATUSES,
)


def assert_common_fields(data: dict):
    """Every resource carries a server-minted UUID id, ISO 8601 UTC stamps and a version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), "id must not carry a type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_millisecond_timestamp(value: str):
    """ISO 8601 in UTC with exactly three fractional-second digits."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert value.endswith("Z"), f"timestamp must be UTC and end with Z: {value!r}"
    assert "." in value, f"timestamp must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


def assert_jurisdiction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code_edition_year"], int)
    assert 2000 <= data["code_edition_year"] <= 2030
    assert isinstance(data["fire_service_required"], bool)
    assert isinstance(data["door_protection_required"], bool)
    assert isinstance(data["witness_test_required"], bool)
    assert 0 <= data["seismic_zone"] <= 4
    assert isinstance(data["inspection_lead_days"], int) and data["inspection_lead_days"] >= 0
    assert isinstance(data["reinspection_extension_hours"], int)
    assert 0.0 <= float(data["permit_surcharge_pct"]) <= 0.25


def assert_project(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SURVEY", "SCOPING", "EXECUTION", "CLOSEOUT", "COMPLETED",
    )
    assert data["occupancy_type"] in ("OCCUPIED", "VACANT")
    assert data["downtime_posture"] in DOWNTIME_POSTURES
    assert data["staging_area_sqft"] >= 1
    assert data["max_concurrent_outages"] >= 1
    assert_project_ledger_invariants(data)


def assert_project_ledger_invariants(data: dict):
    """The four derived counters are non-negative integers."""
    for field in (
        "car_count",
        "approved_scope_value_cents",
        "staging_committed_sqft",
        "active_outage_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"


def assert_elevator_group(data: dict):
    assert_common_fields(data)
    assert isinstance(data["group_label"], str) and data["group_label"]
    assert data["min_cars_in_service"] >= 0
    assert data["car_count"] >= 0
    assert data["cars_in_service"] >= 0
    assert data["cars_in_service"] <= data["car_count"]


def assert_elevator_car(data: dict):
    assert_common_fields(data)
    assert data["work_status"] in WORK_STATUSES
    assert data["compliance_status"] in COMPLIANCE_STATUSES
    assert data["controller_type_legacy"] in (
        "RELAY", "SOLID_STATE_ANALOG", "MICROPROCESSOR",
    )
    assert data["machine_type"] in ("GEARED", "GEARLESS", "MRL_GEARLESS")
    assert data["rated_load_lbs"] >= 500
    assert data["duty_rank"] >= 1
    if data.get("condition_score") is not None:
        assert_two_decimal_places(data["condition_score"])


def assert_equipment_survey(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "COUNTERSIGNED", "VOID")
    for field in ("controller_condition", "machine_condition", "door_equipment_condition"):
        assert data[field] in (
            "EXCELLENT", "GOOD", "FAIR", "POOR", "FAILED", "NOT_OBSERVED",
        )
    if data.get("provisional_score") is not None:
        assert_two_decimal_places(data["provisional_score"])
    if data.get("final_score") is not None:
        assert_two_decimal_places(data["final_score"])


def assert_scope_option(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")
    assert data["tier"] in (
        "CONTROLLER_ONLY", "CONTROLLER_DOOR", "CONTROLLER_MACHINE", "FULL_REPLACEMENT",
    )
    for field in (
        "base_price_cents",
        "code_upgrade_cents",
        "escalation_fee_cents",
        "volume_discount_cents",
        "total_price_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert_four_decimal_places(data["escalation_pct"])
    assert_four_decimal_places(data["volume_discount_pct"])


def assert_code_trigger(data: dict):
    assert_common_fields(data)
    assert data["trigger_type"] in (
        "FIRE_SERVICE_PHASE_I_II",
        "SEISMIC_RESTRAINT",
        "DOOR_PROTECTION_REOPENING",
        "MACHINE_BRAKE_MONITOR",
    )
    assert data["status"] in ("REQUIRED", "PRICED", "WAIVED", "SATISFIED")
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0


def assert_procurement_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ORDERED", "STAGED", "INSTALLED", "CANCELLED")
    assert data["item_type"] in ("CONTROLLER", "MACHINE", "DOOR_OPERATOR", "POWER_UNIT")
    assert data["lead_time_days"] >= 0
    assert data["required_staging_sqft"] >= 0


def assert_staging_reservation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("HELD", "RELEASED")
    assert isinstance(data["sqft"], int) and data["sqft"] >= 0
    assert data["hold_end"] > data["hold_start"], "hold_end must be after hold_start"


def assert_outage_window(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert data["temporary_service_plan"] in (
        "STAIRS_ONLY", "ADJACENT_CAR", "ATTENDANT_SERVICE",
    )
    assert data["end_at"] > data["start_at"], "end_at must be after start_at"
    assert isinstance(data["notice_count"], int) and data["notice_count"] >= 0
    assert isinstance(data["extension_hours"], int) and data["extension_hours"] >= 0
    if data.get("notice_lead_hours") is not None:
        assert_two_decimal_places(data["notice_lead_hours"])


def assert_inspection_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "PASSED", "CONDITIONAL", "FAILED", "CANCELLED",
    )
    assert isinstance(data["witness_requested"], bool)
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert isinstance(data["punch_list_count"], int) and data["punch_list_count"] >= 0


def assert_warranty_transition(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "ENROLLED", "UNDER_CONTRACT", "LAPSED")
    assert 12 <= data["warranty_months"] <= 60
    for field in ("provisional_credit_cents", "final_credit_cents"):
        if data.get(field) is not None:
            assert isinstance(data[field], int), f"{field} must be whole cents"
            assert data[field] >= 0, f"{field} must be non-negative"


def assert_maintenance_contract(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE")
    for field in ("monthly_base_cents", "monthly_total_cents", "total_final_credit_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert isinstance(data["cars_covered"], int) and data["cars_covered"] >= 0


def assert_two_decimal_places(value):
    """Scores are carried to exactly two decimal places."""
    assert isinstance(value, (int, float)), f"expected a number, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{value} must be carried to two decimal places"
    )


def assert_four_decimal_places(value):
    """Percentages are exact to four decimal places and never rounded."""
    assert isinstance(value, (int, float)), f"expected a number, got {value!r}"
    assert round(float(value), 4) == float(value), (
        f"{value} must be exact to four decimal places"
    )


def assert_posture_read(data: dict):
    """The posture read carries the posture and the three inputs that decided it."""
    assert data["downtime_posture"] in DOWNTIME_POSTURES
    assert isinstance(data["active_outage_count"], int) and data["active_outage_count"] >= 0
    assert isinstance(data["staging_committed_sqft"], int)
    assert data["staging_committed_sqft"] >= 0
    assert isinstance(data["groups_below_floor"], int) and data["groups_below_floor"] >= 0


def assert_score_preview(data: dict, expected_basis: str):
    assert data["basis"] == expected_basis
    assert_two_decimal_places(data["score"])
    assert data["recommended_scope_tier"] in (
        "CONTROLLER_ONLY", "CONTROLLER_DOOR", "CONTROLLER_MACHINE", "FULL_REPLACEMENT",
    )
    assert_four_decimal_places(data["observed_weight_total"])


def assert_credit_preview(data: dict, expected_basis: str):
    assert data["basis"] == expected_basis
    assert isinstance(data["day_count"], int) and data["day_count"] >= 0
    assert isinstance(data["per_car_monthly_cents"], int)
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
