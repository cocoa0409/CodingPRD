"""Entity assertions and domain invariant checkers.

Each assert_* validates the system quadruple (id/created_at/updated_at/version
— PRD 2.4) plus the entity's declared fields and status vocabulary.
"""
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_quadruple(data: Dict[str, Any], label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_fee_schedule(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "FeeSchedule")
    assert isinstance(data["schedule_label"], str) and data["schedule_label"]
    assert is_iso8601_timestamp(data["effective_date"])
    for field in (
        "rate_transportation_res",
        "rate_parks_res",
        "rate_fire_res",
        "rate_water_res",
        "rate_sewer_res",
        "rate_transportation_com",
        "rate_parks_com",
        "rate_fire_com",
        "rate_water_com",
        "rate_sewer_com",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be a number"
        assert_cost_precision(data[field])
    assert data["status"] in ("DRAFT", "ADOPTED", "SUPERSEDED")


def assert_applicant(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "Applicant")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_staff_reviewer(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "StaffReviewer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["disciplines"], list)


def assert_decision_authority(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "DecisionAuthority")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["body"] in ("PLANNING_COMMISSION", "CITY_COUNCIL", "STAFF_DIRECTOR")


def assert_project(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "EntitlementProject")
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert data["land_use_type"] in ("RESIDENTIAL", "COMMERCIAL")
    assert isinstance(data["dwelling_units"], int) and data["dwelling_units"] >= 0
    assert isinstance(data["affordable_units"], int) and data["affordable_units"] >= 0
    assert data["affordable_units"] <= data["dwelling_units"]
    assert isinstance(data["floor_area_sqft"], int) and data["floor_area_sqft"] >= 0
    assert data["status"] in ("ACTIVE", "WITHDRAWN", "COMPLETE")


def assert_application(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "EntitlementApplication")
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["application_type"] in (
        "REZONE",
        "CONDITIONAL_USE",
        "PLANNED_DEVELOPMENT",
    )
    assert isinstance(data["submittal_package"], list)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "HEARING_SCHEDULED",
        "DECISION_PENDING",
        "APPROVED",
        "DENIED",
        "WITHDRAWN",
    )


def assert_review_comment(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "ReviewComment")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["discipline"] in (
        "TRANSPORTATION",
        "PARKS",
        "FIRE",
        "WATER",
        "SEWER",
        "PLANNING",
    )
    assert data["severity"] in ("INFO", "REQUIRED", "BLOCKING")
    assert isinstance(data["round_number"], int)
    assert data["status"] in ("OPEN", "ADDRESSED", "VERIFIED", "WAIVED")


def assert_outreach_event(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "OutreachEvent")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["disposition"] in ("SUPPORT", "NEUTRAL", "OPPOSE", "ORGANIZED_OPPOSITION")
    assert isinstance(data["attendee_count"], int) and data["attendee_count"] >= 1
    expected_weight = {
        "SUPPORT": -2,
        "NEUTRAL": 0,
        "OPPOSE": 5,
        "ORGANIZED_OPPOSITION": 12,
    }[data["disposition"]]
    assert data.get("weight") == expected_weight, (
        f"weight must be {expected_weight} for {data['disposition']} (PRD 3.5)"
    )


def assert_hearing(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "PublicHearing")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_iso8601_timestamp(data["hearing_date"])
    assert is_iso8601_timestamp(data["notice_posted_date"])
    assert data["hearing_body"] in ("PLANNING_COMMISSION", "CITY_COUNCIL")
    assert data["status"] in ("SCHEDULED", "HELD", "CONTINUED", "CANCELLED")


def assert_condition(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "ConditionOfApproval")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["category"] in ("FEE", "IMPROVEMENT", "DESIGN", "ENVIRONMENTAL")
    assert data["required_before"] in (
        "PERMIT_ISSUANCE",
        "CERTIFICATE_OF_OCCUPANCY",
        "FINAL_INSPECTION",
    )
    assert data["status"] in ("PENDING", "SATISFIED", "WAIVED", "BREACHED")


def assert_assessment(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "ImpactFeeAssessment")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "DEFERRED", "REFUNDED")
    for field in (
        "gross_total",
        "prior_use_credit_total",
        "improvement_credit_total",
        "net_total",
        "outstanding_balance",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be a number"
        assert_cost_precision(data[field])


def assert_payment(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "FeePayment")
    assert is_valid_uuid(data.get("assessment_id", ""))
    assert isinstance(data["amount"], (int, float)) and data["amount"] > 0
    assert_cost_precision(data["amount"])
    assert is_iso8601_timestamp(data["paid_at"])
    assert isinstance(data["late_fee"], (int, float))
    assert_cost_precision(data["late_fee"])
    # PRD 3.7: "The applied_amount always equals the tendered amount".
    assert data["applied_amount"] == data["amount"], (
        f"applied_amount {data['applied_amount']} must equal amount {data['amount']}"
    )


def assert_development_agreement(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "DevelopmentAgreement")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["agreement_number"], str) and data["agreement_number"]
    assert 1 <= data["vesting_term_years"] <= 15
    assert isinstance(data["registered_voters"], int) and data["registered_voters"] > 0
    assert data["vesting_status"] in (
        "PENDING_REFERENDUM",
        "VESTED",
        "LAPSED",
        "INVALIDATED",
    )
    assert data["status"] in ("DRAFT", "ADOPTED", "EFFECTIVE", "REPEALED")


def assert_petition(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "ReferendumPetition")
    assert is_valid_uuid(data.get("development_agreement_id", ""))
    assert isinstance(data["valid_signature_count"], int)
    assert data["valid_signature_count"] >= 0
    assert data["status"] in (
        "FILED",
        "CERTIFIED_QUALIFIED",
        "CERTIFIED_INSUFFICIENT",
        "REJECTED_UNTIMELY",
    )


def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "Appeal")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["appellant_name"], str) and data["appellant_name"]
    assert is_iso8601_timestamp(data["filed_at"])
    assert data["status"] in ("FILED", "UPHELD", "REVERSED", "DISMISSED_UNTIMELY")


def assert_decision(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "EntitlementDecision")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["decision"] in ("APPROVE", "DENY")
    assert is_iso8601_timestamp(data["decision_effective_date"])
    assert is_iso8601_timestamp(data["appeal_deadline"])
    assert isinstance(data["via_hearing"], bool)
    assert data["status"] in (
        "RENDERED",
        "FINAL",
        "STAYED_ON_APPEAL",
        "REVERSED_ON_APPEAL",
    )


def assert_permit_sequence(data: Dict[str, Any]) -> None:
    _assert_quadruple(data, "PermitSequence")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["permit_type"] in ("GRADING", "BUILDING", "UTILITY", "OCCUPANCY")
    expected_rank = {"GRADING": 1, "BUILDING": 2, "UTILITY": 2, "OCCUPANCY": 3}[
        data["permit_type"]
    ]
    assert data.get("sequence_rank") == expected_rank, (
        f"sequence_rank must be {expected_rank} for {data['permit_type']} (PRD 3.9)"
    )
    assert data["status"] in ("REQUESTED", "ISSUED", "BLOCKED")


# --- Domain invariants ---


def category_line(assessment: Dict[str, Any], category: str) -> Dict[str, Any]:
    """Extract one category line from an assessment's category_lines."""
    for line in assessment.get("category_lines", []):
        if line.get("category") == category:
            return line
    raise AssertionError(
        f"category_lines lacks a {category} entry: {assessment.get('category_lines')}"
    )


def assert_assessment_conservation(data: Dict[str, Any]) -> None:
    """Dollar conservation (PRD 3.3): each net is gross minus both credits, and
    net_total equals gross_total minus the two credit totals exactly."""
    assert data["net_total"] == round(
        data["gross_total"]
        - data["prior_use_credit_total"]
        - data["improvement_credit_total"],
        2,
    ), (
        f"net_total {data['net_total']} != gross {data['gross_total']} "
        f"- prior {data['prior_use_credit_total']} "
        f"- improvement {data['improvement_credit_total']}"
    )


def assert_same_instant(actual: str, expected_iso_prefix: str, label: str = "timestamp") -> None:
    """Compare an ISO-8601 timestamp against an expected instant, tolerant of
    fractional-second rendering (the PRD requires three fractional digits)."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601, got {actual!r}"
    norm = actual.replace("Z", "+00:00")
    from datetime import datetime

    actual_dt = datetime.fromisoformat(norm)
    expected_dt = datetime.fromisoformat(expected_iso_prefix.replace("Z", "+00:00"))
    assert actual_dt == expected_dt, f"{label}: expected {expected_iso_prefix}, got {actual}"
