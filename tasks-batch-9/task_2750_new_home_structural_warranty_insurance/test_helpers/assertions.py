"""Entity assertions, timestamp canonicalisation and domain invariants."""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AffectedElement,
    BuilderUnderwritingStatus,
    ClaimStatus,
    CoverageStatus,
    CoverageTermStatus,
    CoverageType,
    DefectCategory,
    EscalationCaseStatus,
    EscalationStage,
    MonitoringPosture,
    NeutralCredential,
    NeutralStatus,
    Obligor,
    PremiumStatus,
    ReserveEntryType,
    RiskBasis,
    RiskClass,
    StateCode,
    TermKind,
    TransferStatus,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)

# --------------------------------------------------------------------------
# Timestamp handling
#
# The PRD pins created_at / updated_at to ISO 8601 UTC with exactly three
# fractional-second digits. Comparisons between two server-produced instants
# go through canonicalize_instant() so that a difference in sub-second width
# alone can never masquerade as a domain defect; the strict three-digit shape
# is asserted only where the PRD sentence about the format is being tested.
# --------------------------------------------------------------------------
def canonicalize_instant(value: str) -> str:
    """Normalise an ISO 8601 instant to 'YYYY-MM-DDTHH:MM:SS.mmmZ' in UTC."""
    assert isinstance(value, str) and value, f"not an instant: {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"not an ISO 8601 instant: {value!r}"
    date_part, time_part, fraction, zone = match.groups()
    millis = (fraction or "")[:3].ljust(3, "0")
    if zone in (None, "Z", "+00:00", "+0000"):
        return f"{date_part}T{time_part}.{millis}Z"
    sign = 1 if zone[0] == "+" else -1
    digits = zone[1:].replace(":", "")
    offset_minutes = sign * (int(digits[:2]) * 60 + int(digits[2:]))
    from datetime import datetime, timedelta

    naive = datetime.strptime(f"{date_part}T{time_part}", "%Y-%m-%dT%H:%M:%S")
    shifted = naive - timedelta(minutes=offset_minutes)
    return shifted.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis}Z"


def assert_same_instant(actual: str, expected: str) -> None:
    """Compare two instants at millisecond resolution."""
    assert canonicalize_instant(actual) == canonicalize_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def assert_iso8601_utc_millis(value: str) -> None:
    """Assert an instant carries exactly three fractional-second digits in UTC."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), (
        f"expected ISO 8601 UTC with exactly three fractional digits, got {value!r}"
    )


def assert_calendar_date(value: str) -> None:
    """Assert a YYYY-MM-DD calendar date with no time component."""
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"expected a YYYY-MM-DD calendar date, got {value!r}"
    )


# --------------------------------------------------------------------------
# Money and precision
# --------------------------------------------------------------------------
def assert_money_cents(value: Any, field_name: str = "amount") -> None:
    """Every monetary amount is an integer number of cents, never a decimal
    and never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


def assert_decimal_places(value: float, places: int, field_name: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field_name} must be numeric, got {value!r}"
    )
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{field_name} must carry at most {places} decimal places, got {value!r}"
    )


def assert_common_audit_fields(data: Dict[str, Any]) -> None:
    """id + created_at + updated_at + version, for a mutable row."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_journal_audit_fields(data: Dict[str, Any]) -> None:
    """id + created_at only — an immutable journal or reference row exposes
    neither updated_at nor version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        "an immutable row must not expose updated_at"
    )
    assert "version" not in data, "an immutable row must not expose version"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_builder(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"].strip()
    assert data["state_code"] in [s.value for s in StateCode]
    assert isinstance(data["years_in_business"], int)
    assert isinstance(data["homes_closed_last_year"], int)
    assert isinstance(data["claims_history_score"], int)
    assert data["financial_strength_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["underwriting_status"] in [s.value for s in BuilderUnderwritingStatus]
    if data["risk_score"] is not None:
        assert_decimal_places(data["risk_score"], 2, "risk_score")
        assert 0 <= float(data["risk_score"]) <= 100
    if data["risk_class"] is not None:
        assert data["risk_class"] in [c.value for c in RiskClass]
    if data["risk_basis"] is not None:
        assert data["risk_basis"] in [b.value for b in RiskBasis]
    assert data["obligation_period_years"] == 2
    assert_money_cents(data["earned_premium_cents"], "earned_premium_cents")
    assert_money_cents(data["incurred_loss_cents"], "incurred_loss_cents")
    assert_decimal_places(data["loss_ratio"], 4, "loss_ratio")
    assert data["monitoring_posture"] in [p.value for p in MonitoringPosture]


def assert_underwriting_review(data: Dict[str, Any]) -> None:
    assert_journal_audit_fields(data)
    assert is_valid_uuid(data["builder_id"])
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]
    assert data["decision"] in ("APPROVE", "DECLINE", "REFER")
    assert_decimal_places(data["risk_score_snapshot"], 2, "risk_score_snapshot")
    assert data["risk_class_snapshot"] in [c.value for c in RiskClass]
    assert data["resulting_underwriting_status"] in ("APPROVED", "DECLINED", "REFERRED")


def assert_homeowner(data: Dict[str, Any]) -> None:
    assert_journal_audit_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"].strip()
    assert "@" in data["email"]
    assert data["state_code"] in [s.value for s in StateCode]


def assert_neutral(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"].strip()
    assert data["credential"] in [c.value for c in NeutralCredential]
    assert data["state_code"] in [s.value for s in StateCode]
    assert data["status"] in [s.value for s in NeutralStatus]
    assert isinstance(data["booked_session_count"], int)
    assert data["booked_session_count"] >= 0


def assert_policy(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert is_valid_uuid(data["builder_id"])
    assert is_valid_uuid(data["initial_owner_id"])
    assert is_valid_uuid(data["current_owner_id"])
    assert isinstance(data["street_address"], str) and data["street_address"].strip()
    assert data["state_code"] in [s.value for s in StateCode]
    assert_money_cents(data["purchase_price_cents"], "purchase_price_cents")
    assert_calendar_date(data["closing_date"])
    assert_calendar_date(data["coverage_start_date"])
    assert_calendar_date(data["builder_obligation_end_date"])
    assert data["risk_class_at_enrollment"] in [c.value for c in RiskClass]
    for field in ("premium_component_workmanship_cents",
                  "premium_component_systems_cents",
                  "premium_component_structural_cents",
                  "state_surcharge_cents", "premium_cents"):
        assert_money_cents(data[field], field)
    assert data["coverage_status"] in [s.value for s in CoverageStatus]
    assert data["premium_status"] in [s.value for s in PremiumStatus]
    assert isinstance(data["transfer_count"], int) and data["transfer_count"] >= 0
    assert isinstance(data["enrollment_hold"], bool)


def assert_coverage_term(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert data["coverage_type"] in [c.value for c in CoverageType]
    assert data["term_kind"] in [k.value for k in TermKind]
    assert_calendar_date(data["start_date"])
    assert_calendar_date(data["end_date"])
    assert data["end_date"] >= data["start_date"]
    for field in ("limit_cents", "deductible_cents",
                  "consumed_limit_cents", "remaining_limit_cents"):
        assert_money_cents(data[field], field)
    assert data["status"] in [s.value for s in CoverageTermStatus]
    assert_coverage_capacity_conserved(data)


def assert_transfer(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["new_owner_id"])
    assert is_valid_uuid(data["requested_by_owner_id"])
    assert_calendar_date(data["transfer_date"])
    assert_money_cents(data["transfer_fee_cents"], "transfer_fee_cents")
    assert data["status"] in [s.value for s in TransferStatus]


def assert_claim(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["coverage_term_id"])
    assert is_valid_uuid(data["filed_by_owner_id"])
    assert data["coverage_type"] in [c.value for c in CoverageType]
    assert data["defect_category"] in [c.value for c in DefectCategory]
    assert isinstance(data["damage_description"], str)
    assert_money_cents(data["claimed_amount_cents"], "claimed_amount_cents")
    assert_calendar_date(data["reported_date"])
    assert data["obligor"] in [o.value for o in Obligor]
    assert isinstance(data["designated_structural"], bool)
    if data["substantiation_ratio"] is not None:
        assert_decimal_places(data["substantiation_ratio"], 2, "substantiation_ratio")
        assert 0.0 <= float(data["substantiation_ratio"]) <= 1.0
    for field in ("gross_adjusted_cents", "deductible_applied_cents",
                  "betterment_cents", "net_payable_cents", "reserve_cents",
                  "paid_cents", "released_cents", "incurred_authorized_cents"):
        assert_money_cents(data[field], field)
    assert data["status"] in [s.value for s in ClaimStatus]
    assert_claim_money_conserved(data)


def assert_structural_assessment(data: Dict[str, Any]) -> None:
    assert_journal_audit_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["affected_elements"], list)
    assert len(data["affected_elements"]) == len(set(data["affected_elements"]))
    for element in data["affected_elements"]:
        assert element in [e.value for e in AffectedElement]
    assert_decimal_places(data["deflection_ratio"], 4, "deflection_ratio")
    assert 0.0 <= float(data["deflection_ratio"]) <= 0.5
    assert isinstance(data["load_bearing_affected"], bool)
    assert isinstance(data["designated_structural"], bool)
    assert isinstance(data["assessed_by_user_id"], str) and data["assessed_by_user_id"]
    assert_calendar_date(data["assessment_date"])


def assert_reserve_entry(data: Dict[str, Any]) -> None:
    assert_journal_audit_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["entry_type"] in [t.value for t in ReserveEntryType]
    assert_money_cents(data["amount_cents"], "amount_cents")
    assert data["amount_cents"] >= 1
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert_money_cents(data["balance_after_reserve_cents"],
                       "balance_after_reserve_cents")
    assert_money_cents(data["balance_after_paid_cents"], "balance_after_paid_cents")
    if data["entry_type"] != "PAYMENT_REVERSAL":
        assert data.get("reversed_entry_id") is None, (
            "reversed_entry_id is null on every entry type other than PAYMENT_REVERSAL"
        )


def assert_escalation_case(data: Dict[str, Any]) -> None:
    assert_common_audit_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["neutral_id"])
    assert data["stage"] in [s.value for s in EscalationStage]
    assert data["status"] in [s.value for s in EscalationCaseStatus]
    assert isinstance(data["binding"], bool)
    assert data["binding"] is (data["stage"] == "ARBITRATION")
    canonicalize_instant(data["window_start"])
    canonicalize_instant(data["window_end"])
    assert canonicalize_instant(data["window_end"]) > canonicalize_instant(
        data["window_start"]
    )
    if data.get("settlement_amount_cents") is not None:
        assert_money_cents(data["settlement_amount_cents"], "settlement_amount_cents")
    if data.get("award_amount_cents") is not None:
        assert_money_cents(data["award_amount_cents"], "award_amount_cents")


# --------------------------------------------------------------------------
# The two conserved quantities (PRD Section 2.9)
# --------------------------------------------------------------------------
def assert_claim_money_conserved(claim: Dict[str, Any]) -> None:
    """reserve_cents + paid_cents + released_cents == incurred_authorized_cents."""
    total = claim["reserve_cents"] + claim["paid_cents"] + claim["released_cents"]
    assert total == claim["incurred_authorized_cents"], (
        "claim money identity broken: "
        f"{claim['reserve_cents']} + {claim['paid_cents']} + "
        f"{claim['released_cents']} != {claim['incurred_authorized_cents']}"
    )
    assert claim["reserve_cents"] >= 0, "reserve_cents may never go negative"


def assert_coverage_capacity_conserved(term: Dict[str, Any]) -> None:
    """remaining_limit_cents + consumed_limit_cents == limit_cents."""
    total = term["remaining_limit_cents"] + term["consumed_limit_cents"]
    assert total == term["limit_cents"], (
        "coverage capacity identity broken: "
        f"{term['remaining_limit_cents']} + {term['consumed_limit_cents']} "
        f"!= {term['limit_cents']}"
    )
    assert term["remaining_limit_cents"] >= 0


def assert_loss_monitor(data: Dict[str, Any]) -> None:
    assert_money_cents(data["earned_premium_cents"], "earned_premium_cents")
    assert_money_cents(data["incurred_loss_cents"], "incurred_loss_cents")
    assert_decimal_places(data["loss_ratio"], 4, "loss_ratio")
    assert data["monitoring_posture"] in [p.value for p in MonitoringPosture]
    assert isinstance(data["policy_count"], int) and data["policy_count"] >= 0
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0


def assert_envelope_meta(meta: Dict[str, Any]) -> None:
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert_iso8601_utc_millis(meta["api_request_timestamp"])


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"ordering mismatch: {[row['id'] for row in rows]} != {expected_ids}"
    )
