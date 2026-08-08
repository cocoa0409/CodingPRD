"""Entity assertions, instant comparison and program-wide invariant checkers."""

import re
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY_TOLERANCE = 0.005

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|[+-]\d{2}:\d{2})$"
)


# ─── Instant comparison ────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any number of fractional digits.

    Timestamps are compared as instants rather than as strings so that two
    renderings of the same moment — with and without a fractional part — are
    treated as equal.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"Not a parseable ISO 8601 UTC instant: {value!r}"
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    frac = match.group(7) or "0"
    micros = int((frac + "000000")[:6])
    offset = match.group(8)
    dt = datetime(year, month, day, hour, minute, second, micros, tzinfo=timezone.utc)
    if offset not in ("Z", "+00:00", "-00:00"):
        sign = 1 if offset[0] == "+" else -1
        oh, om = int(offset[1:3]), int(offset[4:6])
        from datetime import timedelta

        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def assert_same_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants semantically, not lexically."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected}, got {actual}"


def assert_is_timestamp(value: Any, label: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )
    assert_cost_precision(float(actual))


# ─── Common envelope fields ────────────────────────────────────────────────

def assert_common_fields(data: dict, entity: str) -> None:
    """Fourteen of the fifteen resource types carry id, created_at, updated_at
    and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data!r}"
    assert_is_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_is_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


# ─── Per-entity assertions ─────────────────────────────────────────────────

def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["mrn"], str) and data["mrn"], "Patient.mrn must be non-empty"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_distance_km"], (int, float))
    assert data["home_distance_km"] >= 0
    assert data["primary_diagnosis_code"] in [
        "CHF_EXAC", "COPD_EXAC", "CAP_PNEUMONIA", "CELLULITIS",
        "UTI_COMPLICATED", "COVID_MODERATE", "OTHER",
    ]
    assert data["diet_restriction"] in [
        "NONE", "LOW_SODIUM", "RENAL", "CARB_CONTROLLED", "PUREED",
    ]
    assert isinstance(data["broadband_verified"], bool)
    assert isinstance(data["caregiver_present"], bool)
    assert data["status"] in ["REGISTERED", "IN_PROGRAM", "DISCHARGED"]


def assert_referral(data: dict) -> None:
    assert_common_fields(data, "Referral")
    assert is_valid_uuid(data["patient_id"])
    assert data["origin"] in ["ED", "INPATIENT_WARD", "CLINIC", "SNF"]
    assert data["qualifying_condition_code"] in [
        "CHF_EXAC", "COPD_EXAC", "CAP_PNEUMONIA", "CELLULITIS",
        "UTI_COMPLICATED", "COVID_MODERATE", "OTHER",
    ]
    assert data["acuity"] in ["STANDARD", "HIGH"]
    assert isinstance(data["referring_physician_user_id"], str)
    assert data["status"] in [
        "SUBMITTED", "SCREENING", "ELIGIBLE", "ADMITTED", "CLOSED",
    ]


def assert_eligibility_assessment(data: dict) -> None:
    assert_common_fields(data, "EligibilityAssessment")
    assert is_valid_uuid(data["referral_id"])
    assert_is_timestamp(data["in_person_eval_at"], "EligibilityAssessment.in_person_eval_at")
    assert data["home_safety_outcome"] in ["PASS", "CONDITIONAL", "FAIL"]
    assert data["broadband_check"] in ["PASS", "FAIL"]
    assert isinstance(data["caregiver_present_confirmed"], bool)
    assert isinstance(data["consent_signed"], bool)
    assert isinstance(data["assessor_user_id"], str)


def assert_episode(data: dict) -> None:
    assert_common_fields(data, "Episode")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["referral_id"])
    assert data["program_track"] in ["CMS_WAIVER", "FEE_FOR_SERVICE"]
    assert data["acuity"] in ["STANDARD", "HIGH"]
    assert data["status"] in [
        "ACTIVE", "ESCALATED", "RETURNED_TO_FACILITY",
        "DISCHARGE_PENDING", "DISCHARGED",
    ]
    assert_is_timestamp(data["admitted_at"], "Episode.admitted_at")
    assert isinstance(data["readmission_count"], int)
    assert isinstance(data["med_rec_signed"], bool)
    for counter in (
        "service_day_count", "billable_day_count",
        "carved_out_day_count", "pending_day_count", "open_escalation_count",
    ):
        assert isinstance(data[counter], int), f"Episode.{counter} must be an integer"
        assert data[counter] >= 0
    for amount in (
        "reimbursement_amount_usd", "meal_credit_total_usd",
        "travel_reimbursement_total_usd",
    ):
        assert isinstance(data[amount], (int, float))
        assert_cost_precision(float(data[amount]))
    assert_episode_day_ledger_balanced(data)


def assert_visit(data: dict) -> None:
    assert_common_fields(data, "Visit")
    assert is_valid_uuid(data["episode_id"])
    assert data["visit_type"] in [
        "RN_IN_PERSON", "PARAMEDIC_IN_PERSON",
        "PHYSICIAN_IN_PERSON", "PHYSICIAN_TELEHEALTH",
    ]
    assert isinstance(data["staff_user_id"], str) and data["staff_user_id"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["service_date"]), (
        f"Visit.service_date must be YYYY-MM-DD, got {data['service_date']!r}"
    )
    assert_is_timestamp(data["scheduled_start_at"], "Visit.scheduled_start_at")
    assert_is_timestamp(data["scheduled_end_at"], "Visit.scheduled_end_at")
    assert parse_instant(data["scheduled_end_at"]) > parse_instant(
        data["scheduled_start_at"]
    )
    assert isinstance(data["distance_km"], (int, float)) and data["distance_km"] >= 0
    assert data["scheduling_status"] in [
        "SCHEDULED", "EN_ROUTE", "COMPLETED", "NO_SHOW", "CANCELLED",
    ]
    assert data["attestation_status"] in ["UNATTESTED", "ATTESTED", "AMENDED"]


def assert_compliance_record(data: dict) -> None:
    assert_common_fields(data, "DailyComplianceRecord")
    assert is_valid_uuid(data["episode_id"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["service_date"])
    assert isinstance(data["qualified_in_person_visit_count"], int)
    assert isinstance(data["physician_eval_present"], bool)
    assert isinstance(data["monitoring_lapse_minutes"], int)
    assert isinstance(data["kit_deployed_all_day"], bool)
    assert data["status"] in ["PENDING", "COMPLIANT", "CARVED_OUT"]
    if data["status"] == "CARVED_OUT":
        assert data["carve_out_reason"] in [
            "INSUFFICIENT_IN_PERSON_VISITS", "MISSING_PHYSICIAN_EVAL",
            "MONITORING_LAPSE_EXCEEDED", "KIT_NOT_DEPLOYED",
        ]
    if data["status"] == "PENDING":
        assert data["finalized_at"] is None, (
            "A PENDING compliance record carries no finalized_at"
        )


def assert_device_kit(data: dict) -> None:
    assert_common_fields(data, "DeviceKit")
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["status"] in ["AVAILABLE", "DEPLOYED", "IN_REFURB", "RETIRED"]
    assert isinstance(data["refurb_cycle_count"], int)
    assert isinstance(data["component_count"], int)
    assert isinstance(data["unreconciled_component_count"], int)


def assert_device_component(data: dict) -> None:
    assert_common_fields(data, "DeviceComponent")
    assert is_valid_uuid(data["kit_id"])
    assert data["component_type"] in [
        "TABLET", "BP_CUFF", "PULSE_OX", "SCALE", "THERMOMETER", "GATEWAY",
    ]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["replacement_cost_usd"] >= 0
    assert data["reconciliation_status"] in [
        "IN_STOCK", "DEPLOYED", "PENDING_RECONCILIATION", "RETURNED", "WRITTEN_OFF",
    ]


def assert_monitoring_lapse(data: dict) -> None:
    """A telemetry gap is append-only: id and created_at, but no updated_at and
    no version."""
    assert is_valid_uuid(data.get("id", "")), "MonitoringLapse.id must be a UUID"
    assert_is_timestamp(data.get("created_at"), "MonitoringLapse.created_at")
    assert "updated_at" not in data, (
        "MonitoringLapse must not expose an updated_at field"
    )
    assert "version" not in data, "MonitoringLapse must not expose a version field"
    assert is_valid_uuid(data["episode_id"])
    assert_is_timestamp(data["gap_start_at"], "MonitoringLapse.gap_start_at")
    assert_is_timestamp(data["gap_end_at"], "MonitoringLapse.gap_end_at")
    assert data["cause"] in [
        "DEVICE_OFFLINE", "CONNECTIVITY_LOSS", "PATIENT_REMOVED", "UNKNOWN",
    ]


def assert_delivery_order(data: dict) -> None:
    assert_common_fields(data, "DeliveryOrder")
    assert is_valid_uuid(data["episode_id"])
    assert data["order_kind"] in ["MEDICATION", "DME"]
    assert isinstance(data["is_controlled"], bool)
    assert isinstance(data["cold_chain_required"], bool)
    assert data["weight_kg"] >= 0
    assert data["status"] in [
        "PENDING_AUTHORIZATION", "AUTHORIZED", "OUT_FOR_DELIVERY",
        "DELIVERED", "REFUSED", "FAILED", "CANCELLED",
    ]
    assert isinstance(data["redelivery_count"], int)
    assert_cost_precision(float(data["handling_fee_usd"]))


def assert_meal_plan(data: dict) -> None:
    assert_common_fields(data, "MealPlan")
    assert is_valid_uuid(data["episode_id"])
    assert data["diet_code"] in [
        "NONE", "LOW_SODIUM", "RENAL", "CARB_CONTROLLED", "PUREED",
    ]
    assert 1 <= data["daily_delivery_count"] <= 3
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["activated_on_date"])
    assert data["status"] in ["ACTIVE", "SUSPENDED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["suspension_day_count"], int)
    assert isinstance(data["credited_day_count"], int)
    assert data["credited_day_count"] >= 0
    assert_cost_precision(float(data["meal_credit_total_usd"]))


def assert_escalation_event(data: dict) -> None:
    assert_common_fields(data, "EscalationEvent")
    assert is_valid_uuid(data["episode_id"])
    assert data["reason"] in [
        "VITALS_OUT_OF_RANGE", "PATIENT_REQUEST", "TELEMETRY_LOSS",
        "MEDICATION_FAILURE", "FALL",
    ]
    assert data["status"] in [
        "TIER1_OPEN", "TIER1_ACKED", "TIER2_OPEN", "TIER2_ACKED",
        "TIER3_OPEN", "TIER3_ACKED", "TIER4_OPEN", "TIER4_ACKED",
        "RESOLVED", "BED_RETURN_CONVERTED",
    ]
    assert data["current_tier"] in (1, 2, 3, 4)
    assert_is_timestamp(data["tier_entered_at"], "EscalationEvent.tier_entered_at")
    assert isinstance(data["promotion_count"], int)


def assert_inpatient_unit(data: dict) -> None:
    assert_common_fields(data, "InpatientUnit")
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["total_beds"] >= 1
    assert_bed_census_balanced(data)


def assert_bed_reservation(data: dict) -> None:
    assert_common_fields(data, "BedReservation")
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["episode_id"])
    assert data["status"] in ["HELD", "OCCUPIED", "RELEASED", "EXPIRED"]
    assert_is_timestamp(data["held_at"], "BedReservation.held_at")
    assert_is_timestamp(data["hold_expires_at"], "BedReservation.hold_expires_at")


def assert_billing_claim(data: dict) -> None:
    assert_common_fields(data, "BillingClaim")
    assert is_valid_uuid(data["episode_id"])
    assert isinstance(data["billed_day_count"], int)
    assert data["status"] in [
        "BUILT", "SUBMITTED", "PAID", "DENIED", "APPEALED", "CLOSED", "VOIDED",
    ]
    assert isinstance(data["appeal_count"], int)
    for amount in (
        "gross_amount_usd", "withhold_amount_usd",
        "net_payable_usd", "paid_amount_usd",
    ):
        assert_cost_precision(float(data[amount]))


# ─── Program invariants ────────────────────────────────────────────────────

def assert_episode_day_ledger_balanced(episode: dict) -> None:
    """service_day_count always equals billable + carved_out + pending."""
    total = (
        episode["billable_day_count"]
        + episode["carved_out_day_count"]
        + episode["pending_day_count"]
    )
    assert episode["service_day_count"] == total, (
        "Episode day ledger out of balance: service_day_count "
        f"{episode['service_day_count']} != {episode['billable_day_count']} + "
        f"{episode['carved_out_day_count']} + {episode['pending_day_count']}"
    )


def assert_ledger_matches_episode(ledger: dict, episode: dict) -> None:
    """The dedicated ledger read returns exactly the same seven numbers the
    episode resource carries."""
    for field in (
        "service_day_count", "billable_day_count", "carved_out_day_count",
        "pending_day_count",
    ):
        assert ledger[field] == episode[field], (
            f"ledger.{field} ({ledger[field]}) != episode.{field} ({episode[field]})"
        )
    for field in (
        "reimbursement_amount_usd", "meal_credit_total_usd",
        "travel_reimbursement_total_usd",
    ):
        assert ledger[field] == pytest.approx(episode[field], abs=MONEY_TOLERANCE), (
            f"ledger.{field} ({ledger[field]}) != episode.{field} ({episode[field]})"
        )


def assert_kit_census_balanced(census: dict) -> None:
    """total_kits equals the sum of the four buckets."""
    total = (
        census["available_count"]
        + census["deployed_count"]
        + census["in_refurb_count"]
        + census["retired_count"]
    )
    assert census["total_kits"] == total, (
        "Kit census out of balance: total_kits "
        f"{census['total_kits']} != {census['available_count']} + "
        f"{census['deployed_count']} + {census['in_refurb_count']} + "
        f"{census['retired_count']}"
    )


def assert_bed_census_balanced(unit: dict) -> None:
    """total_beds equals available + held + occupied."""
    total = (
        unit["available_bed_count"] + unit["held_bed_count"] + unit["occupied_bed_count"]
    )
    assert unit["total_beds"] == total, (
        "Bed census out of balance: total_beds "
        f"{unit['total_beds']} != {unit['available_bed_count']} + "
        f"{unit['held_bed_count']} + {unit['occupied_bed_count']}"
    )


def assert_bed_census(
    unit: dict, available: int, held: int, occupied: int
) -> None:
    assert unit["available_bed_count"] == available, (
        f"available_bed_count: expected {available}, got {unit['available_bed_count']}"
    )
    assert unit["held_bed_count"] == held, (
        f"held_bed_count: expected {held}, got {unit['held_bed_count']}"
    )
    assert unit["occupied_bed_count"] == occupied, (
        f"occupied_bed_count: expected {occupied}, got {unit['occupied_bed_count']}"
    )
    assert_bed_census_balanced(unit)


def assert_day_ledger(
    episode: dict,
    service: int,
    billable: int,
    carved_out: int,
    pending: int,
) -> None:
    assert episode["service_day_count"] == service, (
        f"service_day_count: expected {service}, got {episode['service_day_count']}"
    )
    assert episode["billable_day_count"] == billable, (
        f"billable_day_count: expected {billable}, got {episode['billable_day_count']}"
    )
    assert episode["carved_out_day_count"] == carved_out, (
        f"carved_out_day_count: expected {carved_out}, "
        f"got {episode['carved_out_day_count']}"
    )
    assert episode["pending_day_count"] == pending, (
        f"pending_day_count: expected {pending}, got {episode['pending_day_count']}"
    )
    assert_episode_day_ledger_balanced(episode)


def assert_no_version_regression(new_version: int, old_version: int, label: str) -> None:
    assert new_version > old_version, (
        f"{label}: version must strictly increase, {old_version} -> {new_version}"
    )


def assert_unchanged_version(new_version: int, old_version: int, label: str) -> None:
    assert new_version == old_version, (
        f"{label}: a rejected request must not mutate the row "
        f"(version {old_version} -> {new_version})"
    )


def assert_field_absent(data: dict, field: str, entity: str) -> None:
    assert field not in data, f"{entity} response must not carry a {field} field"


def assert_null(value: Optional[Any], label: str) -> None:
    assert value is None, f"{label} must be null, got {value!r}"
