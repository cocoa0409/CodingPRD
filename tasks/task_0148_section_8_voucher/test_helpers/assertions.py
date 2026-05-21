"""Entity assertions and domain invariant checkers — PRD §2.4, §2.11, §3.

For entities with `common_fields` (Applicant, Voucher, Unit, Tenancy,
Inspection, AnnualReview, PortabilityRequest) we expect id +
created_at + updated_at + version (PRD §2.4).

For the three append-only entities (PaymentStandard,
RentReasonablenessRecord, HAPPayment) we expect ONLY id + created_at —
the implementer is correctly told NOT to serialize updated_at/version
on these, so asserting their presence would force a wrong serializer.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field helpers — PRD §2.4
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: id + created_at + updated_at + version on every full entity."""
    assert "id" in data, f"missing id on {data!r}"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601: {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601: {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: PaymentStandard, RentReasonablenessRecord, and HAPPayment
    carry only id + created_at — updated_at and version are absent."""
    assert "id" in data, "missing id"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601: {data['created_at']!r}"
    )


# ---------------------------------------------------------------------------
# Entity-specific assertions — PRD §2.11 enums and §3 prose.
# ---------------------------------------------------------------------------
_APPLICANT_INCOME_BANDS = {
    "EXTREMELY_LOW", "VERY_LOW", "LOW", "OVER_INCOME",
}
_APPLICANT_ELIGIBILITY = {"PENDING", "ELIGIBLE", "INELIGIBLE"}


def assert_applicant(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("household_name"), str) and data["household_name"]
    assert isinstance(data.get("household_size"), int)
    assert 1 <= data["household_size"] <= 20
    assert isinstance(data.get("dependents_count"), int)
    assert 0 <= data["dependents_count"] <= data["household_size"]
    assert isinstance(data.get("elderly_or_disabled_head"), bool)
    assert isinstance(data.get("gross_annual_income_cents"), int)
    assert data["gross_annual_income_cents"] >= 0
    assert isinstance(data.get("adjusted_annual_income_cents"), int)
    assert data["adjusted_annual_income_cents"] >= 0
    assert data["income_band"] in _APPLICANT_INCOME_BANDS, (
        f"unknown income_band {data.get('income_band')!r}"
    )
    assert data["eligibility_status"] in _APPLICANT_ELIGIBILITY, (
        f"unknown eligibility_status {data.get('eligibility_status')!r}"
    )


_VOUCHER_STATES = {
    "ISSUED", "SEARCHING", "LEASED", "SEARCHING_REISSUED",
    "PORTED_OUT", "EXPIRED", "TERMINATED", "REVOKED",
}
_ZONES = {"ZONE_A", "ZONE_B", "ZONE_C"}


def assert_voucher(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("applicant_id"), str) and is_valid_uuid(
        data["applicant_id"]
    )
    assert isinstance(data.get("bedroom_size"), int)
    assert 0 <= data["bedroom_size"] <= 5
    assert is_iso8601_timestamp(str(data.get("issued_at"))), (
        f"issued_at must be ISO 8601: {data.get('issued_at')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("search_deadline"))), (
        f"search_deadline must be ISO 8601: {data.get('search_deadline')!r}"
    )
    assert data["zone"] in _ZONES, f"unknown zone {data.get('zone')!r}"
    assert isinstance(data.get("special_mobility_flag"), bool)
    assert data["status"] in _VOUCHER_STATES, (
        f"unknown voucher status {data.get('status')!r}"
    )
    assert isinstance(data.get("administering_pha_id"), str)


_TENANCY_STATES = {
    "PENDING_INSPECTION", "PENDING_RENT_REASONABLE", "ACTIVE",
    "ABATED", "TERMINATED", "REJECTED",
}


def assert_tenancy(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["status"] in _TENANCY_STATES, (
        f"unknown tenancy status {data.get('status')!r}"
    )
    assert isinstance(data.get("voucher_id"), str)
    assert isinstance(data.get("unit_id"), str)
    assert isinstance(data.get("gross_rent_cents"), int)
    assert data["gross_rent_cents"] > 0
    assert isinstance(data.get("applicable_payment_standard_cents"), int)


_INSPECTION_STATES = {
    "SCHEDULED", "COMPLETED_PASS", "COMPLETED_FAIL_CURABLE",
    "COMPLETED_FAIL_LIFETHREAT", "CURED", "EXPIRED_UNCURED",
}
_INSPECTION_TYPES = {"INITIAL", "ANNUAL", "REINSPECTION"}


def assert_inspection(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["status"] in _INSPECTION_STATES, (
        f"unknown inspection status {data.get('status')!r}"
    )
    assert data["inspection_type"] in _INSPECTION_TYPES, (
        f"unknown inspection_type {data.get('inspection_type')!r}"
    )
    assert isinstance(data.get("tenancy_id"), str)
    assert isinstance(data.get("unit_id"), str)


_AR_STATES = {"DUE", "SUBMITTED", "DEFICIENT", "APPROVED", "DENIED"}


def assert_annual_review(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["status"] in _AR_STATES, (
        f"unknown annual review status {data.get('status')!r}"
    )
    assert isinstance(data.get("tenancy_id"), str)


_UNIT_OCC = {"VACANT", "OCCUPIED_PENDING", "OCCUPIED_ACTIVE", "OCCUPIED_ABATED"}


def assert_unit(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("landlord_id"), str)
    assert isinstance(data.get("street_address"), str)
    assert data["zone"] in _ZONES
    assert isinstance(data.get("bedroom_count"), int)
    assert 0 <= data["bedroom_count"] <= 6
    assert isinstance(data.get("asking_rent_cents"), int)
    assert data["asking_rent_cents"] > 0
    assert data["occupancy_status"] in _UNIT_OCC, (
        f"unknown occupancy_status {data.get('occupancy_status')!r}"
    )


def assert_payment_standard(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert data["zone"] in _ZONES
    assert isinstance(data.get("bedroom_size"), int)
    assert 0 <= data["bedroom_size"] <= 5
    assert isinstance(data.get("standard_amount_cents"), int)
    assert data["standard_amount_cents"] > 0
    assert isinstance(data.get("mobility_amount_cents"), int)
    assert data["mobility_amount_cents"] >= data["standard_amount_cents"]
    assert is_iso8601_timestamp(str(data.get("effective_from")))


def assert_rent_reasonableness_record(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert isinstance(data.get("tenancy_id"), str)
    assert isinstance(data.get("comparable_rents_cents"), list)
    assert isinstance(data.get("median_comparable_cents"), int)
    assert isinstance(data.get("reasonable_threshold_cents"), int)
    assert isinstance(data.get("is_reasonable"), bool)


_HAP_STATUSES = {"PAID", "ABATED_SUSPENDED", "VOIDED_RETROACTIVE"}
_HAP_EVENT_TYPES = {
    "SCHEDULED_MONTHLY", "ABATEMENT", "AR_RECALC", "PORTABILITY_CLOSEOUT",
}


def assert_hap_payment(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert isinstance(data.get("tenancy_id"), str)
    assert isinstance(data.get("pay_period_month"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert data["status"] in _HAP_STATUSES, (
        f"unknown HAP status {data.get('status')!r}"
    )
    assert data["event_ref_type"] in _HAP_EVENT_TYPES, (
        f"unknown event_ref_type {data.get('event_ref_type')!r}"
    )


def assert_portability_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["outcome"] in {
        "INITIATED", "ABSORBED", "BILLED", "DENIED",
    }, f"unknown outcome {data.get('outcome')!r}"
    assert isinstance(data.get("voucher_id"), str)
    assert isinstance(data.get("receiving_pha_id"), str)


# ---------------------------------------------------------------------------
# Domain invariants — PRD §3.7, §3.11
# ---------------------------------------------------------------------------
def assert_hap_plus_ttp_equals_gross_rent(t: Dict[str, Any]) -> None:
    """PRD §3.7: HAP is the smaller of applicable_payment_standard_cents
    and gross_rent_cents, minus TTP, floored at zero. So for ACTIVE
    Tenancies, HAP + TTP + max(0, gross_rent - PS) == gross_rent."""
    hap = t["current_hap_cents"]
    ttp = t["current_total_tenant_payment_cents"]
    gross = t["gross_rent_cents"]
    ps = t["applicable_payment_standard_cents"]
    overage = max(0, gross - ps)
    assert hap + ttp + overage == gross, (
        f"HAP+TTP+overage = {hap}+{ttp}+{overage} != gross_rent {gross}"
    )


def assert_version_incremented_by(
    before: Dict[str, Any],
    after: Dict[str, Any],
    expected_delta: int = 1,
) -> None:
    """PRD §2.4: version increments on every mutation, including
    cascade-driven mutations."""
    assert (after["version"] - before["version"]) == expected_delta, (
        f"version delta = {after['version'] - before['version']}, "
        f"expected {expected_delta}"
    )


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_applicant",
    "assert_voucher",
    "assert_tenancy",
    "assert_inspection",
    "assert_annual_review",
    "assert_unit",
    "assert_payment_standard",
    "assert_rent_reasonableness_record",
    "assert_hap_payment",
    "assert_portability_request",
    "assert_hap_plus_ttp_equals_gross_rent",
    "assert_version_incremented_by",
]
