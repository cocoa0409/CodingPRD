"""Entity assertions, instant comparison helpers and conservation-identity checkers."""

import re
from datetime import datetime, timezone
from typing import Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdjudicationVariant,
    AgeBand,
    AssessmentPurpose,
    AssessmentStatus,
    AssessmentType,
    AuthorizationStatus,
    BillingStatus,
    ClaimStatus,
    CoverageStatus,
    Credential,
    DiagnosisCategory,
    Eye,
    ItemClass,
    LoanStatus,
    MetricCode,
    Modality,
    OcclusionStatus,
    PatientClinicalStatus,
    PayerType,
    PhaseStatus,
    PlanStatus,
    ProgressState,
    ReferralDirection,
    ReferralStatus,
    ReferralUrgency,
    ScheduleStatus,
    ServiceClass,
)

# --------------------------------------------------------------------------
# Timestamps: always compare instants semantically, never as raw strings
# --------------------------------------------------------------------------

_FRACTIONAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC rendering into a timezone-aware datetime.

    A faithful implementation may render fractional seconds differently from
    the string that was supplied on input, so every instant comparison in this
    suite goes through this helper rather than comparing raw strings.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 strings denote the same moment in time."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected} but got {actual} "
        f"({parse_instant(actual)} != {parse_instant(expected)})"
    )


def assert_instant_after(later: str, earlier: str, label: str = "instant") -> None:
    assert parse_instant(later) > parse_instant(earlier), (
        f"{label}: expected {later} to be strictly after {earlier}"
    )


def assert_three_fractional_digits(value: str, label: str = "timestamp") -> None:
    """PRD §2.4 requires ISO 8601 UTC with exactly three fractional-second digits."""
    assert _FRACTIONAL_UTC.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional digits, got {value!r}"
    )


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """id / created_at / updated_at / version, as PRD §2.4 requires."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a plain UUID"
    assert "_" not in str(data.get("id", "")), f"{entity}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["diagnosis_category"] in _enum_values(DiagnosisCategory)
    assert data["clinical_status"] in _enum_values(PatientClinicalStatus)


def assert_payer(data: dict) -> None:
    assert_common_fields(data, "Payer")
    assert data["payer_type"] in _enum_values(PayerType)
    assert isinstance(data["frequency_limit_months"], int)


def assert_coverage(data: dict) -> None:
    assert_common_fields(data, "Coverage")
    assert data["status"] in _enum_values(CoverageStatus)
    assert_vision_allowance_identity(data)


def assert_authorization(data: dict) -> None:
    assert_common_fields(data, "Authorization")
    assert data["status"] in _enum_values(AuthorizationStatus)
    assert_visit_unit_identity(data)


def assert_therapist(data: dict) -> None:
    assert_common_fields(data, "Therapist")
    assert data["credential"] in _enum_values(Credential)


def assert_assessment(data: dict) -> None:
    assert_common_fields(data, "Assessment")
    assert data["assessment_type"] in _enum_values(AssessmentType)
    assert data["purpose"] in _enum_values(AssessmentPurpose)
    assert data["status"] in _enum_values(AssessmentStatus)
    assert isinstance(data["patient_age_years"], int)
    assert isinstance(data["therapy_indicated"], bool)
    assert isinstance(data["discharge_metric_met"], bool)
    assert isinstance(data["red_flag_present"], bool)


def assert_measurement(data: dict) -> None:
    """A measurement row carries id and created_at only from the common set."""
    assert is_valid_uuid(data.get("id", "")), "BinocularMeasurement.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "BinocularMeasurement.created_at must be ISO 8601"
    )
    assert "version" not in data, "BinocularMeasurement must not carry version"
    assert "updated_at" not in data, "BinocularMeasurement must not carry updated_at"
    assert data["metric_code"] in _enum_values(MetricCode)
    assert data["eye"] in _enum_values(Eye)


def assert_therapy_plan(data: dict) -> None:
    assert_common_fields(data, "TherapyPlan")
    assert data["status"] in _enum_values(PlanStatus)
    assert data["progress_state"] in _enum_values(ProgressState)
    assert isinstance(data["current_phase_index"], int)
    assert 0.00 <= float(data["home_compliance_pct"]) <= 100.00


def assert_plan_phase(data: dict) -> None:
    assert_common_fields(data, "PlanPhase")
    assert data["status"] in _enum_values(PhaseStatus)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1


def assert_session(data: dict) -> None:
    assert_common_fields(data, "TherapySession")
    assert data["modality"] in _enum_values(Modality)
    assert data["schedule_status"] in _enum_values(ScheduleStatus)
    assert data["billing_status"] in _enum_values(BillingStatus)
    assert isinstance(data["billable_units"], int) and data["billable_units"] >= 0


def assert_kit_item(data: dict) -> None:
    assert_common_fields(data, "KitItem")
    assert data["item_class"] in _enum_values(ItemClass)
    assert_kit_unit_identity(data)


def assert_kit_loan(data: dict) -> None:
    assert_common_fields(data, "KitLoan")
    assert data["status"] in _enum_values(LoanStatus)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0


def assert_claim(data: dict) -> None:
    assert_common_fields(data, "Claim")
    assert data["status"] in _enum_values(ClaimStatus)
    assert data["service_class"] in _enum_values(ServiceClass)
    if data.get("adjudication_variant") is not None:
        assert data["adjudication_variant"] in _enum_values(AdjudicationVariant)


def assert_referral(data: dict) -> None:
    assert_common_fields(data, "Referral")
    assert data["direction"] in _enum_values(ReferralDirection)
    assert data["urgency"] in _enum_values(ReferralUrgency)
    assert data["status"] in _enum_values(ReferralStatus)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 1


def assert_occlusion_prescription(data: dict) -> None:
    assert_common_fields(data, "OcclusionPrescription")
    assert data["status"] in _enum_values(OcclusionStatus)
    assert data["age_band"] in _enum_values(AgeBand)
    assert isinstance(data["prescribed_daily_hours"], int)
    assert isinstance(data["current_daily_hours"], int)


# --------------------------------------------------------------------------
# Conservation identities (PRD §2.10)
# --------------------------------------------------------------------------


def assert_visit_unit_identity(auth: dict) -> None:
    """visits_authorized + visits_released == visits_consumed + visits_remaining."""
    left = auth["visits_authorized"] + auth["visits_released"]
    right = auth["visits_consumed"] + auth["visits_remaining"]
    assert left == right, (
        "visit-unit identity broken: "
        f"{auth['visits_authorized']} + {auth['visits_released']} != "
        f"{auth['visits_consumed']} + {auth['visits_remaining']}"
    )


def assert_kit_unit_identity(item: dict) -> None:
    """initial_qty == on_hand_qty + on_loan_qty + dispensed_qty + retired_qty."""
    total = (
        item["on_hand_qty"] + item["on_loan_qty"] + item["dispensed_qty"] + item["retired_qty"]
    )
    assert item["initial_qty"] == total, (
        "kit-unit identity broken: "
        f"{item['initial_qty']} != {item['on_hand_qty']} + {item['on_loan_qty']} + "
        f"{item['dispensed_qty']} + {item['retired_qty']}"
    )


def assert_claim_dollar_identity(claim: dict) -> None:
    """billed_amount == plan_paid + patient_responsibility + contractual_adjustment + denied."""
    total = (
        claim["plan_paid_amount"]
        + claim["patient_responsibility_amount"]
        + claim["contractual_adjustment_amount"]
        + claim["denied_amount"]
    )
    assert float(claim["billed_amount"]) == pytest.approx(total, abs=0.005), (
        "claim-dollar identity broken: "
        f"{claim['billed_amount']} != {claim['plan_paid_amount']} + "
        f"{claim['patient_responsibility_amount']} + "
        f"{claim['contractual_adjustment_amount']} + {claim['denied_amount']}"
    )


def assert_vision_allowance_identity(coverage: dict) -> None:
    """vision_allowance_total == vision_allowance_used + vision_allowance_remaining."""
    total = coverage["vision_allowance_used"] + coverage["vision_allowance_remaining"]
    assert float(coverage["vision_allowance_total"]) == pytest.approx(total, abs=0.005), (
        "vision-allowance identity broken: "
        f"{coverage['vision_allowance_total']} != {coverage['vision_allowance_used']} + "
        f"{coverage['vision_allowance_remaining']}"
    )


# --------------------------------------------------------------------------
# Money / percentage helpers
# --------------------------------------------------------------------------


def assert_money(actual, expected, label: str = "amount") -> None:
    assert float(actual) == pytest.approx(float(expected), abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct(actual, expected, label: str = "percentage") -> None:
    assert float(actual) == pytest.approx(float(expected), abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_minutes(actual, expected, label: str = "minutes") -> None:
    assert float(actual) == pytest.approx(float(expected), abs=0.05), (
        f"{label}: expected {expected}, got {actual}"
    )


def find_by_id(rows: list, row_id: str) -> Optional[dict]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
