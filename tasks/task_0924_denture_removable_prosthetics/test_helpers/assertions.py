"""Entity assertions, instant comparison, and domain invariant checkers."""

import re
from datetime import datetime, timezone
from typing import Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ADJUSTMENT_ALLOWANCE_COUNT

# ─────────────────────────────────────────────────────────────────────────
# Instant handling
#
# The PRD renders every instant as an ISO 8601 UTC timestamp with three
# fractional digits. Tests must nevertheless compare instants *semantically*:
# "2026-05-01T00:00:00Z" and "2026-05-01T00:00:00.000Z" denote the same
# moment and must never be compared as raw strings.
# ─────────────────────────────────────────────────────────────────────────

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"
    r"(Z|[+-]\d{2}:?\d{2})$"
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Accepts an optional fractional-second component of any length and either a
    trailing ``Z`` or a numeric UTC offset, so two renderings of the same
    moment always parse to the same value.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 instant string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"Not a parseable ISO 8601 instant: {value!r}"
    year, month, day, hour, minute, second, frac, offset = match.groups()
    micro = int((frac or "0").ljust(6, "0"))
    parsed = datetime(
        int(year), int(month), int(day), int(hour), int(minute), int(second), micro,
        tzinfo=timezone.utc,
    )
    if offset not in ("Z", "+00:00", "+0000", "-00:00", "-0000"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta_minutes = sign * (int(body[:2]) * 60 + int(body[2:]))
        parsed = datetime.fromtimestamp(
            parsed.timestamp() - delta_minutes * 60, tz=timezone.utc
        )
    return parsed


def assert_same_instant(actual, expected, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment.

    Comparison is semantic, never a raw string equality, so a server that
    renders ``...T00:00:00.000Z`` matches an expectation written as
    ``...T00:00:00Z`` and vice versa.
    """
    assert actual is not None, f"{label} must not be null (expected {expected})"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected}, got {actual}"


def assert_instant_rendering(value, label: str = "instant") -> None:
    """Assert a field is rendered as an ISO 8601 UTC timestamp."""
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 UTC instant, got {value!r}"


def assert_null(value, label: str = "field") -> None:
    assert value is None, f"{label} must be null, got {value!r}"


# ─────────────────────────────────────────────────────────────────────────
# Money
# ─────────────────────────────────────────────────────────────────────────

def assert_money(actual, expected, label: str = "amount") -> None:
    """Assert a monetary field equals the expected value to the cent."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert float(actual) == pytest.approx(float(expected), abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─────────────────────────────────────────────────────────────────────────
# Common-field assertions
# ─────────────────────────────────────────────────────────────────────────

def assert_common_fields(data: dict, entity: str = "resource") -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a bare uuid with no type prefix, got {data.get('id')!r}"
    )
    assert_instant_rendering(data.get("created_at"), f"{entity}.created_at")
    assert_instant_rendering(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


# ─────────────────────────────────────────────────────────────────────────
# Per-entity assertions
# ─────────────────────────────────────────────────────────────────────────

def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["write_gate_active"], bool)
    assert isinstance(data["delivered_prosthesis_count"], int)
    assert "last_frequency_anchor_at" in data, "last_frequency_anchor_at is always present"


def assert_coverage(data: dict) -> None:
    assert_common_fields(data, "Coverage")
    assert data["rank"] in ("PRIMARY", "SECONDARY")
    assert data["cob_convention"] in ("STANDARD", "NON_DUPLICATION")
    assert_instant_rendering(data["effective_date"], "Coverage.effective_date")
    assert_coverage_benefit_conserved(data)


def assert_dental_lab(data: dict) -> None:
    assert_common_fields(data, "DentalLab")
    assert isinstance(data["bench_line_count"], int)
    assert_lab_credit_conserved(data)


def assert_prosthesis_case(data: dict) -> None:
    assert_common_fields(data, "ProsthesisCase")
    assert data["case_status"] in (
        "INTAKE", "EXAM_COMPLETE", "IN_FABRICATION", "DELIVERED", "CLOSED", "CANCELLED",
    )
    assert data["prosthesis_type"] in (
        "COMPLETE_DENTURE", "IMMEDIATE_DENTURE", "CAST_PARTIAL",
        "FLEXIBLE_PARTIAL", "OVERDENTURE", "IMPLANT_RETAINED_OVERDENTURE",
    )
    assert isinstance(data["predetermination_required"], bool)


def assert_case_arch(data: dict) -> None:
    assert_common_fields(data, "CaseArch")
    assert data["arch_position"] in ("MAXILLARY", "MANDIBULAR")
    assert data["arch_status"] in (
        "PLANNED", "IMPRESSION_PENDING", "MILESTONE_PENDING", "LAB_FABRICATION",
        "READY_FOR_DELIVERY", "DELIVERED", "REMAKE_PENDING", "ARCH_CLOSED", "ARCH_ABANDONED",
    )
    assert isinstance(data["required_milestones"], list), (
        "required_milestones is always present as a JSON array"
    )
    assert isinstance(data["completed_milestones"], list), (
        "completed_milestones is always present as a JSON array"
    )
    assert data["remake_eligibility"] in ("ELIGIBLE", "FINAL_DENIED")


def assert_impression_record(data: dict) -> None:
    assert_common_fields(data, "ImpressionRecord")
    assert data["capture_method"] in ("PHYSICAL_IMPRESSION", "DIGITAL_SCAN")
    assert data["quality_status"] in (
        "PENDING_REVIEW", "ACCEPTED", "PROVISIONAL_ACCEPTED", "REJECTED", "SUPERSEDED",
    )
    assert isinstance(data["attempt_number"], int)
    assert isinstance(data["retake_required"], bool)


def assert_try_in_milestone(data: dict) -> None:
    assert_common_fields(data, "TryInMilestone")
    assert data["milestone_kind"] in ("WAX", "FRAMEWORK", "FINISH")
    assert data["approval_status"] in (
        "PENDING_APPROVAL", "ADJUST_REQUESTED", "APPROVED", "REJECTED_FOR_REMAKE", "CANCELLED",
    )
    assert isinstance(data["adjust_count"], int)


def assert_lab_case(data: dict) -> None:
    assert_common_fields(data, "LabCase")
    assert data["turnaround_class"] in ("STANDARD", "RUSH")
    assert data["purpose"] in (
        "FABRICATION", "RELINE", "REBASE", "REPAIR", "ADDITION", "REMAKE",
    )
    assert data["lab_status"] in (
        "DRAFT", "DISPATCHED", "RETURNED", "QC_PASSED", "QC_FAILED",
        "RESENT", "EXPIRED", "CANCELLED",
    )
    assert 1 <= data["unit_count"] <= 32


def assert_prosthesis(data: dict) -> None:
    assert_common_fields(data, "Prosthesis")
    assert data["warranty_status"] in (
        "IN_WARRANTY", "WARRANTY_CONSUMED", "WARRANTY_EXPIRED", "WARRANTY_VOIDED",
    )
    assert data["recall_status"] in (
        "RECALL_SCHEDULED", "RECALL_DUE", "RECALL_OVERDUE",
        "RECALL_COMPLETED", "RECALL_CLOSED_SUPERSEDED",
    )
    assert isinstance(data["is_remake"], bool)
    assert isinstance(data["in_patient_possession"], bool)
    assert_adjustment_allowance_conserved(data)


def assert_post_delivery_service(data: dict) -> None:
    assert_common_fields(data, "PostDeliveryService")
    assert data["service_type"] in (
        "ADJUSTMENT", "SOFT_RELINE_CHAIRSIDE", "HARD_RELINE_LAB", "REBASE",
        "REPAIR", "TOOTH_ADDITION", "CLASP_ADDITION",
    )
    assert data["service_status"] in (
        "REQUESTED", "IN_CHAIR", "AT_LAB", "COMPLETED", "VOIDED",
    )


def assert_warranty_claim(data: dict) -> None:
    assert_common_fields(data, "WarrantyClaim")
    assert data["claim_status"] in (
        "SUBMITTED", "CLINICAL_REVIEW", "CLINIC_FAULT", "LAB_FAULT", "PATIENT_FAULT",
    )
    assert isinstance(data["warranty_consumed"], bool)


def assert_remake_request(data: dict) -> None:
    assert_common_fields(data, "RemakeRequest")
    assert data["reason_code"] in (
        "TRYIN_REJECTED", "FIT_FAILURE", "LAB_DEFECT",
        "PATIENT_DISSATISFACTION", "RECALL_EVALUATION",
    )
    assert data["authorization_status"] in (
        "PENDING_APPROVAL", "APPROVED", "DENIED", "FINAL_DENIED",
    )
    assert data["charge_basis"] in ("NO_CHARGE", "CHARGEABLE")


def assert_predetermination(data: dict) -> None:
    assert_common_fields(data, "Predetermination")
    assert data["determination_status"] in (
        "SUBMITTED", "APPROVED", "DENIED", "ALTERNATE_BENEFIT", "EXPIRED",
    )


def assert_claim(data: dict) -> None:
    assert_common_fields(data, "Claim")
    assert data["adjudication_status"] in (
        "DRAFT", "SUBMITTED_PRIMARY", "PRIMARY_PAID", "SUBMITTED_SECONDARY",
        "SECONDARY_PAID", "CLOSED", "DENIED", "REVERSED",
    )
    assert data["submission_target"] in ("PRIMARY", "SECONDARY")


def assert_payment_plan(data: dict) -> None:
    assert_common_fields(data, "PaymentPlan")
    assert data["plan_status"] in (
        "ACTIVE", "DELINQUENT", "DEFAULTED", "PAID_OFF", "SUPERSEDED",
    )
    assert data["frequency"] in ("MONTHLY", "BIWEEKLY")
    assert_payment_plan_conserved(data)


def assert_installment(data: dict) -> None:
    assert_common_fields(data, "Installment")
    assert data["installment_status"] in ("SCHEDULED", "MISSED", "PAID", "WAIVED")
    assert isinstance(data["sequence_number"], int)
    assert isinstance(data["is_residual_installment"], bool)


# ─────────────────────────────────────────────────────────────────────────
# Conserved quantities
# ─────────────────────────────────────────────────────────────────────────

def assert_adjustment_allowance_conserved(prosthesis: dict) -> None:
    """adjustments_used plus adjustments_remaining always equals 4."""
    total = prosthesis["adjustments_used"] + prosthesis["adjustments_remaining"]
    assert total == ADJUSTMENT_ALLOWANCE_COUNT, (
        f"adjustments_used ({prosthesis['adjustments_used']}) plus adjustments_remaining "
        f"({prosthesis['adjustments_remaining']}) must equal {ADJUSTMENT_ALLOWANCE_COUNT}"
    )


def assert_payment_plan_conserved(plan: dict) -> None:
    """paid_amount plus outstanding_amount always equals principal_amount."""
    assert_money(
        plan["paid_amount"] + plan["outstanding_amount"],
        plan["principal_amount"],
        "paid_amount plus outstanding_amount",
    )


def assert_lab_credit_conserved(lab: dict) -> None:
    """credit_issued_total minus credit_applied_total equals credit_available_balance."""
    assert_money(
        lab["credit_issued_total"] - lab["credit_applied_total"],
        lab["credit_available_balance"],
        "credit_issued_total minus credit_applied_total",
    )


def assert_coverage_benefit_conserved(coverage: dict) -> None:
    """benefit_used_ytd plus benefit_remaining equals annual_maximum_amount."""
    assert_money(
        coverage["benefit_used_ytd"] + coverage["benefit_remaining"],
        coverage["annual_maximum_amount"],
        "benefit_used_ytd plus benefit_remaining",
    )


# ─────────────────────────────────────────────────────────────────────────
# Collection helpers
# ─────────────────────────────────────────────────────────────────────────

def by_sequence_number(rows: list, sequence_number: int) -> Optional[dict]:
    for row in rows:
        if row.get("sequence_number") == sequence_number:
            return row
    return None


def sorted_by_sequence(rows: list) -> list:
    return sorted(rows, key=lambda row: row["sequence_number"])
