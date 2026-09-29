"""Entity assertions and domain invariant checkers for the floorplan API."""
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AbortReasonCode,
    AdvanceReasonCode,
    AdvanceStatus,
    AuditStatus,
    AuditType,
    CovenantResult,
    CreditLineStatus,
    DealerStatus,
    EligibilityStatus,
    ExceptionStatus,
    FranchiseType,
    FundingStatus,
    IncidentStatus,
    IneligibilityReasonCode,
    InventoryClass,
    JustificationCode,
    ObligationStatus,
    ObservationClassification,
    ObservedCondition,
    RemedyActionType,
    RemedyReasonCode,
    RemedyStatus,
    RemittanceIntent,
    RemittanceStatus,
    RiskRating,
    TitleCustodyStatus,
    TitleDocumentType,
)

_TIMESTAMP_SUFFIX = "Z"


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_identifier(value: Any, label: str = "id") -> None:
    assert is_valid_uuid(value or ""), f"{label} must be a UUID with no prefix, got {value!r}"


def assert_utc_millisecond_timestamp(value: Any, label: str = "timestamp") -> None:
    """Timestamps are ISO 8601 UTC with exactly three fractional-second digits."""
    assert isinstance(value, str) and value, f"{label} must be a non-empty string"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"
    assert value.endswith(_TIMESTAMP_SUFFIX), f"{label} must end in Z, got {value!r}"


def assert_common_mutable_fields(data: Dict[str, Any], label: str) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert_identifier(data.get("id"), f"{label}.id")
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any], label: str) -> None:
    """An immutable resource carries only id and created_at — never updated_at/version."""
    assert_identifier(data.get("id"), f"{label}.id")
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at"
    assert "updated_at" not in data, f"{label} must not expose updated_at"
    assert "version" not in data, f"{label} must not expose version"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def assert_dealer(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "Dealer")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    assert data["dba_name"] is None or isinstance(data["dba_name"], str)
    assert data["franchise_type"] in _values(FranchiseType)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper()
    assert data["status"] in _values(DealerStatus)
    assert 0 <= data["risk_score"] <= 100, "risk_score is clamped to 0..100"
    assert data["risk_rating"] in _values(RiskRating)
    assert isinstance(data["audit_frequency_days"], int)
    assert data["next_audit_due_at"] is None or is_iso8601_timestamp(
        data["next_audit_due_at"]
    )
    for counter in (
        "open_sot_incident_count",
        "open_sot_exposure_cents",
        "delinquent_unit_count",
        "covenant_breach_count",
        "unapplied_credit_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert data["last_covenant_result"] is None or data["last_covenant_result"] in _values(
        CovenantResult
    )
    assert isinstance(data["audit_in_progress"], bool)


def assert_credit_line(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "CreditLine")
    assert_identifier(data.get("dealer_id"), "CreditLine.dealer_id")
    assert data["status"] in _values(CreditLineStatus)
    assert data["credit_limit_cents"] >= 100000
    for rate in (
        "advance_rate_bps_new",
        "advance_rate_bps_used",
        "advance_rate_bps_demonstrator",
    ):
        assert 0 <= data[rate] <= 10000, f"{rate} must be within 0..10000"
    for cap in (
        "max_unit_advance_cents_new",
        "max_unit_advance_cents_used",
        "max_unit_advance_cents_demonstrator",
        "class_sublimit_cents_used",
        "class_sublimit_cents_demonstrator",
    ):
        assert data[cap] > 0, f"{cap} must be strictly positive"
    assert 0 <= data["curtailment_grace_days"] <= 30
    for money in (
        "outstanding_principal_cents",
        "charged_off_principal_cents",
        "eligible_collateral_cents",
        "borrowing_base_deficiency_cents",
        "class_outstanding_cents_used",
        "class_outstanding_cents_demonstrator",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, money
    assert isinstance(data["available_credit_cents"], int)
    assert data["activated_at"] is None or is_iso8601_timestamp(data["activated_at"])
    assert data["suspension_reason_code"] is None or isinstance(
        data["suspension_reason_code"], str
    )


def assert_credit_line_capacity_identity(data: Dict[str, Any]) -> None:
    """credit_limit_cents == available + outstanding + charged_off, always."""
    total = (
        data["available_credit_cents"]
        + data["outstanding_principal_cents"]
        + data["charged_off_principal_cents"]
    )
    assert data["credit_limit_cents"] == total, (
        "credit_limit_cents must equal available_credit_cents + "
        f"outstanding_principal_cents + charged_off_principal_cents; got "
        f"{data['credit_limit_cents']} vs {total}"
    )
    expected_deficiency = max(
        0, data["outstanding_principal_cents"] - data["eligible_collateral_cents"]
    )
    assert data["borrowing_base_deficiency_cents"] == expected_deficiency, (
        "borrowing_base_deficiency_cents must be max(0, outstanding - eligible)"
    )


def assert_curtailment_tier(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data, "CurtailmentTier")
    assert_identifier(data.get("credit_line_id"), "CurtailmentTier.credit_line_id")
    assert data["inventory_class"] in _values(InventoryClass)
    assert isinstance(data["age_days_from"], int) and data["age_days_from"] >= 0
    assert data["age_days_to"] is None or data["age_days_to"] > data["age_days_from"]
    assert 0 <= data["cumulative_paydown_bps"] <= 10000


def assert_inventory_unit(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "InventoryUnit")
    assert_identifier(data.get("dealer_id"), "InventoryUnit.dealer_id")
    assert_identifier(data.get("credit_line_id"), "InventoryUnit.credit_line_id")
    vin = data["vin"]
    assert isinstance(vin, str) and len(vin) == 17, "vin must be exactly 17 characters"
    assert vin.isalnum() and vin.upper() == vin, "vin must be uppercase alphanumeric"
    assert data["inventory_class"] in _values(InventoryClass)
    assert data["invoice_amount_cents"] > 0
    assert data["title_document_type"] in _values(TitleDocumentType)
    assert data["funding_status"] in _values(FundingStatus)
    assert data["title_custody_status"] in _values(TitleCustodyStatus)
    assert data["eligibility_status"] in _values(EligibilityStatus)
    for money in (
        "advance_amount_cents",
        "outstanding_principal_cents",
        "principal_paid_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, money
    assert data["floored_at"] is None or is_iso8601_timestamp(data["floored_at"])
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["aging_exception_count"], int)
    assert isinstance(data["curtailment_extension_days_total"], int)
    assert data["ineligibility_reason_code"] is None or data[
        "ineligibility_reason_code"
    ] in _values(IneligibilityReasonCode)


def assert_funding_advance(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "FundingAdvance")
    assert_identifier(data.get("unit_id"), "FundingAdvance.unit_id")
    assert_identifier(data.get("credit_line_id"), "FundingAdvance.credit_line_id")
    assert data["status"] in _values(AdvanceStatus)
    assert data["requested_amount_cents"] > 0
    assert isinstance(data["dealer_invoice_reference"], str)
    assert isinstance(data["approved_advance_amount_cents"], int)
    assert 0 <= data["effective_advance_rate_bps"] <= 10000
    assert isinstance(data["rate_adjustment_codes"], list)
    for code in data["rate_adjustment_codes"]:
        assert code in ("HIGH_MILEAGE_DEMO", "AGED_INVOICE"), code
    assert data["reason_code"] is None or data["reason_code"] in _values(
        AdvanceReasonCode
    )
    assert data["funded_at"] is None or is_iso8601_timestamp(data["funded_at"])


def assert_curtailment_obligation(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "CurtailmentObligation")
    assert_identifier(data.get("unit_id"), "CurtailmentObligation.unit_id")
    assert_identifier(data.get("dealer_id"), "CurtailmentObligation.dealer_id")
    assert data["status"] in _values(ObligationStatus)
    assert isinstance(data["tier_age_days_from"], int)
    assert isinstance(data["tier_cumulative_paydown_bps"], int)
    assert is_iso8601_timestamp(data["due_date"]) or isinstance(data["due_date"], str)
    for money in (
        "projected_principal_cents",
        "required_principal_cents",
        "late_fee_cents",
        "total_amount_due_cents",
        "principal_paid_cents",
        "fee_paid_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, money
    assert data["late_fee_cents"] <= 50000, "late_fee_cents is capped at 50000"
    assert isinstance(data["extension_days_applied"], int)


def assert_aging_exception_request(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "AgingExceptionRequest")
    assert_identifier(data.get("obligation_id"), "AgingExceptionRequest.obligation_id")
    assert data["status"] in _values(ExceptionStatus)
    assert 1 <= data["requested_extension_days"] <= 45
    assert data["justification_code"] in _values(JustificationCode)
    assert isinstance(data["requested_by_user_id"], str)


def assert_floor_plan_audit(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "FloorPlanAudit")
    assert_identifier(data.get("dealer_id"), "FloorPlanAudit.dealer_id")
    assert data["audit_type"] in _values(AuditType)
    assert data["status"] in _values(AuditStatus)
    for counter in (
        "units_in_scope_count",
        "units_verified_count",
        "units_exception_count",
        "units_unobserved_count",
        "sot_exposure_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert isinstance(data["observer_user_ids"], list)
    assert data["abort_reason_code"] is None or data["abort_reason_code"] in _values(
        AbortReasonCode
    )


def assert_audit_scope_identity(data: Dict[str, Any]) -> None:
    """units_in_scope_count == verified + exception + unobserved, always."""
    total = (
        data["units_verified_count"]
        + data["units_exception_count"]
        + data["units_unobserved_count"]
    )
    assert data["units_in_scope_count"] == total, (
        "units_in_scope_count must equal units_verified_count + "
        f"units_exception_count + units_unobserved_count; got "
        f"{data['units_in_scope_count']} vs {total}"
    )


def assert_unit_audit_observation(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data, "UnitAuditObservation")
    assert_identifier(data.get("audit_id"), "UnitAuditObservation.audit_id")
    assert_identifier(data.get("unit_id"), "UnitAuditObservation.unit_id")
    assert data["observed_condition"] in _values(ObservedCondition)
    assert isinstance(data["title_verified"], bool)
    assert data["classification"] in _values(ObservationClassification)
    assert isinstance(data["is_out_of_trust"], bool)
    assert isinstance(data["observed_by_user_id"], str)
    assert isinstance(data["unit_outstanding_principal_cents_at_observation"], int)


def assert_out_of_trust_incident(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "OutOfTrustIncident")
    for ref in ("dealer_id", "unit_id", "audit_id", "observation_id"):
        assert_identifier(data.get(ref), f"OutOfTrustIncident.{ref}")
    assert data["status"] in _values(IncidentStatus)
    assert isinstance(data["exposure_cents"], int) and data["exposure_cents"] >= 0
    assert is_iso8601_timestamp(data["cure_deadline_at"])


def assert_payment_remittance(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "PaymentRemittance")
    assert_identifier(data.get("dealer_id"), "PaymentRemittance.dealer_id")
    assert data["intent"] in _values(RemittanceIntent)
    assert data["amount_cents"] > 0
    assert data["status"] in _values(RemittanceStatus)
    for money in (
        "applied_principal_cents",
        "applied_fee_cents",
        "applied_sot_cure_cents",
        "unapplied_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, money
    assert isinstance(data["allocation_breakdown"], list)


def assert_remittance_money_conservation(data: Dict[str, Any]) -> None:
    """amount_cents == principal + fee + sot cure + unapplied."""
    total = (
        data["applied_principal_cents"]
        + data["applied_fee_cents"]
        + data["applied_sot_cure_cents"]
        + data["unapplied_cents"]
    )
    assert data["amount_cents"] == total, (
        "amount_cents must equal applied_principal_cents + applied_fee_cents + "
        f"applied_sot_cure_cents + unapplied_cents; got {data['amount_cents']} vs {total}"
    )


def assert_covenant_test(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data, "CovenantTest")
    assert_identifier(data.get("dealer_id"), "CovenantTest.dealer_id")
    assert data["result"] in _values(CovenantResult)
    assert isinstance(data["failure_reason_codes"], list)
    for code in data["failure_reason_codes"]:
        assert code in ("CAPITAL", "CASH_FLOW", "OUT_OF_TRUST"), code
    assert isinstance(data["required_tangible_net_worth_cents"], int)
    assert isinstance(data["trailing_sot_incident_count"], int)
    assert_dscr_precision(data["dscr_lender_standard"], "dscr_lender_standard")
    assert_dscr_precision(data["dscr_dealer_adjusted"], "dscr_dealer_adjusted")


def assert_dscr_precision(value: Any, label: str = "dscr") -> None:
    """DSCRs are the only non-integers and carry exactly four decimal places."""
    if isinstance(value, str):
        integral, _, fraction = value.partition(".")
        assert integral, f"{label} must have an integral part, got {value!r}"
        assert len(fraction) == 4, f"{label} must carry four decimals, got {value!r}"
        return
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    scaled = round(float(value) * 10000)
    assert abs(float(value) * 10000 - scaled) < 1e-6, (
        f"{label} must be expressible in exactly four decimal places, got {value!r}"
    )


def assert_remedy_action(data: Dict[str, Any]) -> None:
    assert_common_mutable_fields(data, "RemedyAction")
    assert_identifier(data.get("dealer_id"), "RemedyAction.dealer_id")
    assert data["action_type"] in _values(RemedyActionType)
    assert data["status"] in _values(RemedyStatus)
    assert data["reason_code"] in _values(RemedyReasonCode)
    assert isinstance(data["justification_snapshot"], dict)
    assert isinstance(data["issued_by_user_id"], str)


# ---------------------------------------------------------------------------
# Cross-cutting helpers
# ---------------------------------------------------------------------------
def dscr_as_string(value: Any) -> str:
    """Normalise a DSCR to its four-decimal textual form for comparison."""
    if isinstance(value, str):
        return value
    return f"{float(value):.4f}"


def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int, total: int,
                           has_more: bool) -> None:
    assert meta["limit"] == limit, f"limit should be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset should be {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"total_count should be {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more should be {has_more}, got {meta['has_more']}"
    )
