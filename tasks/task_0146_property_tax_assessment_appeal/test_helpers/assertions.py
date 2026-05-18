"""Entity assertions and domain invariant checkers.

PRD §2.4 common-fields split:
- Mutable resources carry id + created_at + updated_at + version.
- Payment carries ONLY id + created_at (PRD §2.4 exception).
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """Every resource carries id + created_at — PRD §2.4."""
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a bare UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 with three fractional digits, got "
        f"{data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: mutable resources carry updated_at + version (starts
    at 1, incremented by exactly 1 on every mutation).
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601 with three fractional digits, got "
        f"{data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ===========================================================================
# Mutable resources — PRD §2.4
# ===========================================================================
def assert_owner(data: Dict[str, Any]) -> None:
    """PRD §3.1 Owner shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    # veteran_status / disability_rating are optional inputs with
    # defaults (PRD §3.1) — assert types when present.
    if "veteran_status" in data:
        assert isinstance(data["veteran_status"], bool)
    if "disability_rating" in data:
        assert isinstance(data["disability_rating"], int)
        assert 0 <= data["disability_rating"] <= 100, (
            f"disability_rating out of range: {data['disability_rating']}"
        )


def assert_hearing_officer(data: Dict[str, Any]) -> None:
    """PRD §3.1 HearingOfficer shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    if "active" in data:
        assert isinstance(data["active"], bool)


def assert_property(data: Dict[str, Any]) -> None:
    """PRD §3.1 Property shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("parcel_number"), str) and data["parcel_number"]
    assert isinstance(data.get("market_value"), (int, float))
    # capped_value is a derived numeric per PRD §3.1 ("Fetch a Property
    # with derived capped_value").
    assert isinstance(data.get("capped_value"), (int, float))


def assert_assessment(data: Dict[str, Any]) -> None:
    """PRD §3.2 Assessment shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("roll_year"), int)
    assert isinstance(data.get("market_value_at_roll"), (int, float))
    assert data.get("status") in {
        "DRAFT", "ISSUED", "UNDER_APPEAL", "FINALIZED",
    }, f"unexpected assessment status: {data.get('status')!r}"


def assert_exemption_application(data: Dict[str, Any]) -> None:
    """PRD §3.3 ExemptionApplication shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("owner_id"), str)
    assert data.get("exemption_type") in {
        "HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY",
    }, f"unexpected exemption_type: {data.get('exemption_type')!r}"
    assert isinstance(data.get("effective_roll_year"), int)
    assert data.get("status") in {
        "SUBMITTED", "APPROVED", "DENIED", "REVOKED",
    }, f"unexpected exemption status: {data.get('status')!r}"
    rr = data.get("revoked_reason")
    if data["status"] == "REVOKED":
        assert rr in {"OWNERSHIP_CHANGE", "INELIGIBLE", "WITHDRAWN"}, (
            f"REVOKED requires revoked_reason in enum, got {rr!r}"
        )
    else:
        # PRD §2.7: 'revoked_reason ... when revoked' — null otherwise.
        assert rr is None, (
            f"revoked_reason must be null unless REVOKED, got {rr!r}"
        )


def assert_appeal(data: Dict[str, Any]) -> None:
    """PRD §3.5 Appeal shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("assessment_id"), str)
    assert isinstance(data.get("owner_id"), str)
    assert data.get("filed_grounds") in {
        "OVER_MARKET", "EXEMPTION_DENIED",
        "CAP_MISAPPLIED", "CLERICAL_ERROR",
    }, f"unexpected filed_grounds: {data.get('filed_grounds')!r}"
    assert isinstance(data.get("claimed_value"), (int, float))
    assert data.get("status") in {
        "FILED", "SCHEDULED", "HEARD", "DECIDED", "WITHDRAWN",
    }, f"unexpected appeal status: {data.get('status')!r}"
    # PRD §2.7: 'decision_outcome ... null until DECIDED'.
    outcome = data.get("decision_outcome")
    if data["status"] == "DECIDED":
        assert outcome in {"UPHELD", "REDUCED", "INCREASED"}, (
            f"DECIDED requires decision_outcome enum, got {outcome!r}"
        )
        assert isinstance(data.get("decided_value"), (int, float))


def assert_hearing(data: Dict[str, Any]) -> None:
    """PRD §3.5 Hearing shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("appeal_id"), str)
    assert isinstance(data.get("scheduled_start"), str)
    assert isinstance(data.get("scheduled_end"), str)
    assert data.get("hearing_room") in {"ROOM_A", "ROOM_B", "ROOM_C"}, (
        f"unexpected hearing_room: {data.get('hearing_room')!r}"
    )
    assert isinstance(data.get("officer_id"), str)
    assert data.get("status") in {
        "SCHEDULED", "CONDUCTED", "RESCHEDULED", "CANCELLED",
    }, f"unexpected hearing status: {data.get('status')!r}"


def assert_tax_bill(data: Dict[str, Any]) -> None:
    """PRD §3.4 TaxBill shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("roll_year"), int)
    assert isinstance(data.get("mill_rate"), (int, float))
    assert isinstance(data.get("taxable_value"), (int, float))
    assert isinstance(data.get("total_exemption_amount"), (int, float))
    assert isinstance(data.get("base_tax_amount"), (int, float))
    assert isinstance(data.get("amount_due"), (int, float))
    # PRD §3.4: 'taxable_value ... then floored at zero — so the
    # taxable value never goes negative'.
    assert data["taxable_value"] >= 0, (
        f"taxable_value must be >= 0, got {data['taxable_value']}"
    )
    # PRD §3.4: 'amount_due ... then floored at zero'.
    assert data["amount_due"] >= 0, (
        f"amount_due must be >= 0, got {data['amount_due']}"
    )
    assert data.get("status") in {
        "PENDING", "ISSUED", "PARTIALLY_PAID", "PAID",
        "IN_DEFERRAL", "DELINQUENT",
    }, f"unexpected tax bill status: {data.get('status')!r}"


def assert_deferral_plan(data: Dict[str, Any]) -> None:
    """PRD §3.6 DeferralPlan shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("tax_bill_id"), str)
    assert data.get("status") in {
        "REQUESTED", "ACTIVE", "COMPLETED", "DEFAULTED",
    }, f"unexpected deferral status: {data.get('status')!r}"
    if data["status"] in {"ACTIVE", "COMPLETED", "DEFAULTED"}:
        assert isinstance(data.get("principal_deferred"), (int, float))
        assert isinstance(data.get("annual_interest_rate"), (int, float))
        assert isinstance(data.get("accrued_interest"), (int, float))
        assert data["accrued_interest"] >= 0, (
            f"accrued_interest must be >= 0, got {data['accrued_interest']}"
        )


# ===========================================================================
# Payment — PRD §2.4 exception: id + created_at only
# ===========================================================================
def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'a Payment carries id and created_at and ... Payment
    therefore exposes neither updated_at nor version.'"""
    _assert_id_and_created_at(data)
    # PRD §3.4: 'applied_at doubles as their created_at'.
    assert isinstance(data.get("applied_at"), str)
    assert is_iso8601_timestamp(data["applied_at"]), (
        f"applied_at must be ISO 8601, got {data['applied_at']!r}"
    )
    assert isinstance(data.get("amount"), (int, float))
    assert data.get("status") in {"APPLIED", "REFUNDED"}, (
        f"unexpected payment status: {data.get('status')!r}"
    )
    rr = data.get("refund_reason")
    if data["status"] == "REFUNDED":
        assert rr in {"APPEAL_REDUCED", "OVERPAYMENT"}, (
            f"REFUNDED requires refund_reason enum, got {rr!r}"
        )
    else:
        # PRD §2.7: 'remains null otherwise'.
        assert rr is None, (
            f"refund_reason must be null when APPLIED, got {rr!r}"
        )


# ===========================================================================
# Domain invariant helpers
# ===========================================================================
def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer starting at 1 and incremented
    by exactly 1 on every mutation.'"""
    assert "version" in prev and "version" in curr, (
        "both records must carry version"
    )
    assert curr["version"] == prev["version"] + 1, (
        f"version expected to increment by exactly 1: "
        f"prev={prev['version']} curr={curr['version']}"
    )


def assert_two_decimal_precision(value: float, name: str = "value") -> None:
    """PRD §2.6: 'All money in the system ... is stored and returned
    as a JSON number with at most two decimal places.'"""
    # Convert to string and inspect the fractional part. Avoid float
    # comparison pitfalls by rounding then comparing.
    assert isinstance(value, (int, float)), (
        f"{name} must be numeric, got {type(value)}"
    )
    rounded = round(float(value), 2)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{name} must have at most 2 decimal places, got {value!r}"
    )


def assert_taxable_value_identity(bill: Dict[str, Any],
                                  capped_value: float,
                                  tol: float = 0.01) -> None:
    """PRD §3.4: 'Compute taxable_value as capped_value minus
    total_exemption_amount, rounded half up to two decimal places,
    then floored at zero.'"""
    expected = max(
        round(capped_value - bill["total_exemption_amount"], 2),
        0.0,
    )
    assert abs(bill["taxable_value"] - expected) <= tol, (
        f"taxable_value identity failed: bill.taxable_value="
        f"{bill['taxable_value']}, expected {expected}"
    )


def assert_base_tax_identity(bill: Dict[str, Any],
                             tol: float = 0.01) -> None:
    """PRD §3.4: 'Compute base_tax_amount as taxable_value multiplied
    by mill_rate, then divided by 1,000, then rounded half up to two
    decimal places.'"""
    expected = round(
        bill["taxable_value"] * bill["mill_rate"] / 1000.0, 2,
    )
    assert abs(bill["base_tax_amount"] - expected) <= tol, (
        f"base_tax_amount identity failed: bill.base_tax_amount="
        f"{bill['base_tax_amount']}, expected {expected}"
    )


__all__ = [
    "assert_owner",
    "assert_hearing_officer",
    "assert_property",
    "assert_assessment",
    "assert_exemption_application",
    "assert_appeal",
    "assert_hearing",
    "assert_tax_bill",
    "assert_deferral_plan",
    "assert_payment",
    "assert_version_incremented_by_one",
    "assert_two_decimal_precision",
    "assert_taxable_value_identity",
    "assert_base_tax_identity",
]
