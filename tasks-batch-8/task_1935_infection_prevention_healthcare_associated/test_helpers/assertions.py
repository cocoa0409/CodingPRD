"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3).

Timestamp comparisons normalize both sides to an instant, because the PRD pins
the *value* of computed timestamps (e.g. "at 00:00:00Z") while a response may
serialize the same instant with or without fractional digits.
"""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"Expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    """Assert two timestamps denote the same instant regardless of formatting."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_approx_equal(actual: float, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict, label: str = "resource") -> None:
    """PRD §2.4: id (bare UUID), created_at/updated_at (ISO 8601), version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_facility(data: dict) -> None:
    assert_common_fields(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["nhsn_org_id"], str) and data["nhsn_org_id"]
    for field in (
        "clabsi_baseline_per_1000",
        "cauti_baseline_per_1000",
        "ssi_baseline_per_procedure",
        "sir_high_threshold",
    ):
        assert isinstance(data[field], (int, float)), f"Facility.{field} must be numeric"
    assert isinstance(data["hh_min_opportunities"], int)


def assert_unit(data: dict) -> None:
    assert_common_fields(data, "Unit")
    assert data["unit_type"] in ("ICU", "WARD", "STEP_DOWN", "OR")
    assert data["surveillance_posture"] in ("NORMAL", "ELEVATED", "OUTBREAK")


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert data["status"] in ("ADMITTED", "DISCHARGED")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["unit_stays"], list) and len(data["unit_stays"]) >= 1
    for stay in data["unit_stays"]:
        assert "unit_id" in stay and "arrived_at" in stay and "departed_at" in stay


def assert_employee(data: dict) -> None:
    assert_common_fields(data, "Employee")
    assert isinstance(data["employee_code"], str) and data["employee_code"]


def assert_device_episode(data: dict) -> None:
    assert_common_fields(data, "DeviceEpisode")
    assert data["device_type"] in ("CENTRAL_LINE", "URINARY_CATHETER", "VENTILATOR")
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_surgical_procedure(data: dict) -> None:
    assert_common_fields(data, "SurgicalProcedure")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert 1 <= data["asa_score"] <= 5
    assert data["wound_class"] in ("CLEAN", "CLEAN_CONTAMINATED", "CONTAMINATED", "DIRTY")


def assert_infection_case(data: dict) -> None:
    assert_common_fields(data, "InfectionCase")
    assert data["case_type"] in ("CLABSI", "CAUTI", "SSI", "OTHER_BSI")
    assert data["status"] in (
        "SUSPECTED",
        "UNDER_REVIEW",
        "ADJUDICATED_HAI",
        "RULED_OUT",
        "REOPENED",
    )
    assert is_iso8601_timestamp(data["infection_window_start"])
    assert is_iso8601_timestamp(data["infection_window_end"])


def assert_device_day_count(data: dict) -> None:
    assert_common_fields(data, "DeviceDayCount")
    assert data["status"] in ("DRAFT", "LOCKED")
    for field in ("central_line_days", "urinary_catheter_days", "ventilator_days", "patient_days"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_monthly_summary(data: dict) -> None:
    assert_common_fields(data, "MonthlySummary")
    assert data["status"] in ("OPEN", "SUBMITTED", "ACCEPTED", "REJECTED", "UNDER_AMENDMENT")
    assert data["sir_flag"] in ("HIGH", "NORMAL", "NOT_CALCULATED")
    for field in (
        "central_line_days",
        "urinary_catheter_days",
        "ventilator_days",
        "patient_days_total",
        "procedure_count",
        "clabsi_count",
        "cauti_count",
        "ssi_count",
        "provisional_clabsi_count",
        "provisional_cauti_count",
        "provisional_ssi_count",
        "amendment_count",
    ):
        assert isinstance(data[field], int), f"MonthlySummary.{field} must be an integer"
    for field in ("predicted_clabsi", "predicted_cauti", "predicted_ssi"):
        assert isinstance(data[field], (int, float)), (
            f"MonthlySummary.{field} must be numeric"
        )
    for field in (
        "sir_clabsi",
        "sir_cauti",
        "sir_ssi",
        "provisional_sir_clabsi",
        "provisional_sir_cauti",
        "provisional_sir_ssi",
    ):
        assert data[field] is None or isinstance(data[field], (int, float)), (
            f"MonthlySummary.{field} must be null or numeric"
        )


def assert_outbreak_investigation(data: dict) -> None:
    assert_common_fields(data, "OutbreakInvestigation")
    assert data["status"] in ("TRIGGERED", "CONFIRMED", "RULED_OUT", "CLOSED")
    assert data["origin"] in ("AUTO_THRESHOLD", "MANUAL")
    assert isinstance(data["trigger_case_ids"], list)
    assert isinstance(data["contributing_case_count"], int)


def assert_isolation_order(data: dict) -> None:
    assert_common_fields(data, "IsolationOrder")
    assert data["status"] in ("ORDERED", "ACTIVE", "DISCONTINUED")
    assert data["compliance_status"] in ("NOT_AUDITED", "COMPLIANT", "NON_COMPLIANT")
    assert data["precaution_type"] in ("CONTACT", "DROPLET", "AIRBORNE")


def assert_isolation_audit(data: dict) -> None:
    assert_common_fields(data, "IsolationComplianceAudit")
    assert data["outcome"] in ("COMPLIANT", "NON_COMPLIANT")
    assert isinstance(data["elements_checked"], int) and data["elements_checked"] >= 1
    assert isinstance(data["elements_passed"], int) and data["elements_passed"] >= 0
    assert isinstance(data["compliance_pct"], (int, float))


def assert_observation(data: dict) -> None:
    assert_common_fields(data, "HandHygieneObservation")
    assert data["opportunity_type"] in (
        "BEFORE_PATIENT_CONTACT",
        "AFTER_PATIENT_CONTACT",
        "ASEPTIC_TASK",
        "BODY_FLUID_RISK",
        "AFTER_SURROUNDINGS",
    )
    assert data["action"] in ("COMPLIANT", "MISSED")


def assert_exposure(data: dict) -> None:
    assert_common_fields(data, "EmployeeExposure")
    assert data["status"] in (
        "REPORTED",
        "SOURCE_EVALUATED",
        "BASELINE_COMPLETE",
        "FOLLOWUP_IN_PROGRESS",
        "COMPLETED",
        "LOST_TO_FOLLOWUP",
    )
    assert data["exposure_type"] in ("PERCUTANEOUS", "MUCOUS_MEMBRANE", "SKIN")
    assert isinstance(data["recorded_stages"], list)


def assert_cap(data: dict) -> None:
    assert_common_fields(data, "CorrectiveActionPlan")
    assert data["status"] in ("DRAFT", "ACTIVE", "VERIFICATION_PENDING", "VERIFIED", "ESCALATED")
    assert data["source_type"] in ("OUTBREAK", "ISOLATION_AUDIT", "HAND_HYGIENE", "SIR_HIGH")
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0
