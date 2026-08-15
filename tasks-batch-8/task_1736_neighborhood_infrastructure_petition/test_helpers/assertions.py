"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {type(value)}"
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, what: str = "timestamp"):
    """Assert two ISO 8601 instants denote the same moment regardless of
    fractional-digit rendering."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{what}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict, entity: str, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_district(data: dict):
    _assert_common(data, "District")
    assert isinstance(data["name"], str) and data["name"]
    assert data["methodology"] in ("PER_PARCEL", "FRONT_FOOT")
    assert data["interest_method"] in ("SIMPLE", "COMPOUND")
    assert isinstance(data["annual_interest_rate_bp"], int)
    assert 0 <= data["annual_interest_rate_bp"] <= 2000
    assert data["status"] in (
        "DRAFT", "PETITIONING", "SCOPING", "HEARING_SCHEDULED", "OBJECTION_WINDOW",
        "COUNCIL_REVIEW", "APPROVED", "CONSTRUCTION", "TRUE_UP", "BILLING",
        "ACCEPTED", "ABANDONED",
    )
    assert isinstance(data["remand_count"], int)
    assert isinstance(data["eligible_parcel_count"], int)
    assert isinstance(data["approved_change_total_cents"], int)
    assert isinstance(data["paid_assessment_count"], int)
    assert isinstance(data["total_assessment_count"], int)
    assert isinstance(data["overrun_flag"], bool)
    assert isinstance(data["all_assessments_paid"], bool)


def assert_owner(data: dict):
    _assert_common(data, "PropertyOwner")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["mailing_address"], str)


def assert_parcel(data: dict):
    _assert_common(data, "Parcel")
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_valid_uuid(data.get("owner_id", ""))
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert data["frontage_ft"] > 0
    assert isinstance(data["exempt"], bool)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_petition(data: dict):
    _assert_common(data, "Petition")
    assert is_valid_uuid(data.get("district_id", ""))
    assert data["status"] in ("CIRCULATING", "CLOSED_VERIFIED", "CLOSED_INSUFFICIENT", "VOIDED")
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert isinstance(data["verified_signature_count"], int)
    assert data["verified_signature_count"] >= 0


def assert_signature(data: dict):
    _assert_common(data, "PetitionSignature")
    assert is_valid_uuid(data.get("petition_id", ""))
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "WITHDRAWN", "VOIDED")
    assert is_iso8601_timestamp(data.get("signed_at", ""))


def assert_cost_estimate(data: dict):
    _assert_common(data, "CostEstimate")
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data["estimate_seq"], int) and data["estimate_seq"] >= 1
    assert isinstance(data["contract_price_cents"], int) and data["contract_price_cents"] > 0
    assert isinstance(data["contingency_cents"], int) and data["contingency_cents"] >= 0
    assert data["total_estimated_cost_cents"] == (
        data["contract_price_cents"] + data["contingency_cents"]
    ), "total must equal contract price plus contingency"
    assert data["status"] in ("SUBMITTED", "APPROVED", "SUPERSEDED")


def assert_hearing(data: dict):
    _assert_common(data, "PublicHearing")
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_iso8601_timestamp(data.get("hearing_date", ""))
    assert isinstance(data["venue"], str) and data["venue"]
    assert data["status"] in ("SCHEDULED", "HELD", "CLOSED", "SUPERSEDED", "VOIDED")


def assert_objection(data: dict):
    _assert_common(data, "Objection")
    assert is_valid_uuid(data.get("hearing_id", ""))
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert data["status"] in ("FILED", "UNDER_REVIEW", "SUSTAINED", "OVERRULED", "WITHDRAWN")


def assert_resolution(data: dict):
    _assert_common(data, "CouncilResolution")
    assert data["motion"] in ("APPROVE", "REJECT", "REMAND")
    assert isinstance(data["votes_for"], int) and 0 <= data["votes_for"] <= 5
    assert isinstance(data["votes_against"], int) and 0 <= data["votes_against"] <= 5
    assert data["votes_for"] + data["votes_against"] <= 5
    assert data["outcome"] in ("ADOPTED", "FAILED")
    assert data["required_votes_snapshot"] in (3, 4)


def assert_assessment(data: dict):
    _assert_common(data, "ParcelAssessment")
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert isinstance(data["preliminary_amount_cents"], int)
    assert data["payment_option"] in ("NONE", "PREPAY_FULL", "INSTALLMENTS")
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["total_refunded_cents"], int)
    assert data["status"] in (
        "PRELIMINARY", "SUPERSEDED", "LEVIED", "PREPAID", "SETTLEMENT_DUE",
        "IN_REPAYMENT", "DELINQUENT", "PAID_OFF", "REMOVED",
    )


def assert_phase(data: dict):
    _assert_common(data, "ConstructionPhase")
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data["crew_name"], str) and data["crew_name"]
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] > 0
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_change_order(data: dict):
    _assert_common(data, "ChangeOrder")
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED")
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_invoice(data: dict):
    _assert_common(data, "InstallmentInvoice")
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_valid_uuid(data.get("parcel_assessment_id", ""))
    assert data["kind"] in ("ANNUAL", "SUPPLEMENTAL")
    assert isinstance(data["year_index"], int)
    assert is_iso8601_timestamp(data.get("issue_date", ""))
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in (
        "SCHEDULED", "ISSUED", "PARTIALLY_PAID", "PAID", "DELINQUENT", "VOIDED"
    )


def assert_payment(data: dict):
    """Payment is append-only: id + created_at plus event fields, and never
    version or updated_at."""
    assert is_valid_uuid(data.get("id", "")), "Payment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Payment.created_at must be ISO 8601"
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CHECK", "ACH", "CARD")
    assert isinstance(data["applied_penalty_cents"], int)
    assert isinstance(data["applied_interest_cents"], int)
    assert isinstance(data["applied_principal_cents"], int)
    assert (
        data["applied_penalty_cents"]
        + data["applied_interest_cents"]
        + data["applied_principal_cents"]
        == data["amount_cents"]
    ), "waterfall split must sum to the payment amount"


def assert_assessment_money_identity(assessment: dict):
    """Money conservation across the true-up and refund steps: the net money
    received (total_paid - total_refunded) equals the final levy earned plus
    the credit still held for the owner."""
    if assessment.get("final_levy_cents") is None:
        return
    lhs = assessment["total_paid_cents"] - assessment["total_refunded_cents"]
    rhs = assessment["final_levy_cents"] + assessment["credit_balance_cents"]
    assert lhs == rhs, f"money identity violated: {lhs} != {rhs}"
