"""Entity assertions and domain invariant checkers.

Uses the framework generic validators internally. Every entity carries the four
common fields (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str)
    assert isinstance(data["outstanding_fines_cents"], int)
    assert data["outstanding_fines_cents"] >= 0
    assert data["compliance_status"] in ("COMPLIANT", "DELINQUENT")


def assert_animal(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REPORTED", "AT_LARGE", "CAPTURED", "UNDER_OBSERVATION",
        "RELEASED", "DECEASED", "EUTHANIZED",
    )
    assert data["disposition"] in ("NONE", "RELEASED", "DECEASED", "EUTHANIZED")
    assert data["control_status"] in ("NONE", "DISPATCH_REQUESTED", "CAPTURED")


def assert_bite_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "OBSERVATION_PENDING", "LAB_PENDING",
        "CONFIRMED_RABID", "CLEARED", "CLOSED",
    )
    assert data["risk_level"] in ("NONE", "LOW", "MODERATE", "HIGH")
    assert data["pep_indication"] in ("NOT_INDICATED", "DEFER", "INITIATE")
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0


def assert_quarantine_facility(data: dict):
    _assert_common(data)
    assert data["facility_type"] in ("SHELTER", "VET_CLINIC")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["daily_boarding_cents"], int) and data["daily_boarding_cents"] >= 0
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0


def assert_quarantine_order(data: dict):
    _assert_common(data)
    assert data["order_type"] in ("HOME_CONFINEMENT", "FACILITY")
    assert data["status"] in ("ACTIVE", "COMPLETED", "BREACHED", "CONVERTED_TO_SPECIMEN")
    assert data["observation_outcome"] in ("PENDING", "HEALTHY", "SYMPTOMATIC", "DECEASED")
    assert isinstance(data["boarding_cost_cents"], int) and data["boarding_cost_cents"] >= 0


def assert_specimen(data: dict):
    _assert_common(data)
    assert data["condition"] in ("SATISFACTORY", "AUTOLYZED", "UNSATISFACTORY")
    assert data["status"] in ("SUBMITTED", "RESULTED", "REJECTED")
    assert data["result"] in ("PENDING", "POSITIVE", "NEGATIVE", "INDETERMINATE")


def assert_pep_recommendation(data: dict):
    _assert_common(data)
    assert data["indication"] in ("NOT_INDICATED", "DEFER", "INITIATE")
    assert data["status"] in (
        "NOT_INDICATED", "RECOMMENDED", "INITIATED",
        "COMPLETED", "DISCONTINUED", "SUPERSEDED",
    )
    assert isinstance(data["projected_doses"], int) and data["projected_doses"] >= 0
    assert isinstance(data["projected_cost_cents"], int) and data["projected_cost_cents"] >= 0
    assert isinstance(data["final_cost_cents"], int) and data["final_cost_cents"] >= 0
    assert isinstance(data["doses_administered"], int) and data["doses_administered"] >= 0


def assert_citation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "CONTESTED", "UPHELD", "DISMISSED", "PAID")
    assert isinstance(data["violations"], list) and len(data["violations"]) >= 1
    assert isinstance(data["base_fine_cents"], int) and data["base_fine_cents"] >= 0
    assert isinstance(data["total_fine_cents"], int) and data["total_fine_cents"] >= 0


def assert_surveillance_region(data: dict):
    _assert_common(data)
    assert data["alert_status"] in ("NORMAL", "ELEVATED", "OUTBREAK")
    assert isinstance(data["confirmed_positive_count"], int) and data["confirmed_positive_count"] >= 0
    assert isinstance(data["wildlife_exposure_count"], int) and data["wildlife_exposure_count"] >= 0
    assert isinstance(data["positive_threshold"], int) and data["positive_threshold"] >= 1


def assert_wildlife_report(data: dict):
    _assert_common(data)
    assert data["exposure_type"] in ("DIRECT_CONTACT", "BITE", "INDOOR_FOUND_BAT")
    assert data["disposition"] in ("RELEASED", "EUTHANIZED", "ESCAPED", "TESTED")
