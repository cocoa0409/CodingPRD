"""Entity assertions and domain invariant checkers.

PRD §2.4 splits entities into two shapes:

    common-fields (Veteran, Dependent, Claim, School, Enrollment,
    YellowRibbonContribution, VocRehabPlan):
        id, created_at, updated_at, version

    append-only (HousingPayment, PaymentLedgerEntry):
        "Two entities in this domain are append-only ledger rows and
        therefore carry only id and created_at: HousingPayment and
        PaymentLedgerEntry. Once written, neither row is updated, so
        neither carries updated_at or version."
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    COMBINED_RATING_MAX,
    COMBINED_RATING_MIN,
    ENTITLEMENT_CAP,
    RATING_LADDER,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'The version starts at 1 on creation and increments by
    exactly 1 on every server-side mutation ... updated_at is rewritten
    to the current server clock on every such mutation.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: common-fields entities expose id, created_at,
    updated_at, version."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'Two entities in this domain are append-only ledger
    rows and therefore carry only id and created_at: HousingPayment and
    PaymentLedgerEntry. Once written, neither row is updated, so neither
    carries updated_at or version.'"""
    _assert_id_and_created_at(data)


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: 'version starts at 1 on creation and increments by
    exactly 1 on every server-side mutation'."""
    before_v = before.get("version")
    after_v = after.get("version")
    assert isinstance(before_v, int) and isinstance(after_v, int), (
        f"version comparison needs int versions, "
        f"got {before_v!r}, {after_v!r}"
    )
    assert after_v >= before_v + delta, (
        f"expected version >= {before_v} + {delta} = {before_v + delta}, "
        f"got {after_v}"
    )


# ---------------------------------------------------------------------------
# Veteran — PRD §3.1
# ---------------------------------------------------------------------------
_VETERAN_BRANCHES = {
    "ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE",
}
_VETERAN_DISCHARGE = {
    "HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE",
    "BAD_CONDUCT", "DISHONORABLE",
}
_TIER_VALUES = {0, 40, 50, 60, 70, 80, 90, 100}


def assert_veteran(data: Dict[str, Any]) -> None:
    """PRD §3.1: 'a Veteran record that captures the legal full_name (1
    to 120 characters), the service branch ..., the
    aggregate_active_duty_days count ..., and the discharge_status'."""
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert 1 <= len(data["full_name"]) <= 120
    assert data.get("branch") in _VETERAN_BRANCHES, (
        f"unexpected branch: {data.get('branch')!r}"
    )
    assert isinstance(data.get("aggregate_active_duty_days"), int)
    assert data["aggregate_active_duty_days"] >= 0
    assert data.get("discharge_status") in _VETERAN_DISCHARGE, (
        f"unexpected discharge_status: {data.get('discharge_status')!r}"
    )
    # PRD §2.6: "combined_rating is an integer in the set {0,10,20,...,100}"
    assert data.get("combined_rating") in RATING_LADDER, (
        f"combined_rating must be on the ladder, got "
        f"{data.get('combined_rating')!r}"
    )
    # PRD §3.1: "post_911_eligibility_tier is an integer in
    # {0, 40, 50, 60, 70, 80, 90, 100}"
    assert data.get("post_911_eligibility_tier") in _TIER_VALUES, (
        f"post_911_eligibility_tier off-ladder: "
        f"{data.get('post_911_eligibility_tier')!r}"
    )
    # PRD §2.6: "months_entitlement_used and months_consumed carry two
    # decimal places ... the entitlement counter is capped at 36.00"
    me = data.get("months_entitlement_used")
    assert isinstance(me, (int, float)) and 0 <= me <= ENTITLEMENT_CAP, (
        f"months_entitlement_used must be in [0, 36.00], got {me!r}"
    )


# ---------------------------------------------------------------------------
# Dependent — PRD §3.2
# ---------------------------------------------------------------------------
_DEPENDENT_STATUS = {"ACTIVE", "REMOVED"}
_DEPENDENT_RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT"}


def assert_dependent(data: Dict[str, Any]) -> None:
    """PRD §3.2: 'A Dependent row starts in ACTIVE status with
    removed_at null, and ages or removals later flip it to REMOVED.'"""
    assert_common_fields(data)
    assert isinstance(data.get("veteran_id"), str)
    assert data.get("relationship") in _DEPENDENT_RELATIONSHIPS, (
        f"unexpected relationship: {data.get('relationship')!r}"
    )
    assert isinstance(data.get("date_of_birth"), str)
    assert data.get("status") in _DEPENDENT_STATUS, (
        f"unexpected dependent status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Claim — PRD §3.3
# ---------------------------------------------------------------------------
_CLAIM_STATUS = {
    "SUBMITTED", "UNDER_REVIEW", "GRANTED",
    "DENIED", "APPEALED", "DENIED_FINAL",
}
_CLAIM_TYPES = {"ORIGINAL", "SUPPLEMENTAL"}


def assert_claim(data: Dict[str, Any]) -> None:
    """PRD §3.3: 'A Claim represents a single condition the veteran
    asserts as service-connected.'"""
    assert_common_fields(data)
    assert isinstance(data.get("veteran_id"), str)
    assert isinstance(data.get("condition_code"), str)
    assert 1 <= len(data["condition_code"]) <= 32
    assert data.get("claim_type") in _CLAIM_TYPES, (
        f"unexpected claim_type: {data.get('claim_type')!r}"
    )
    assert data.get("status") in _CLAIM_STATUS, (
        f"unexpected claim status: {data.get('status')!r}"
    )
    # PRD §3.3: proposed_rating is "an integer in
    # {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}"
    assert data.get("proposed_rating") in RATING_LADDER, (
        f"proposed_rating off-ladder: {data.get('proposed_rating')!r}"
    )
    granted = data.get("granted_rating")
    assert granted is None or granted in RATING_LADDER, (
        f"granted_rating off-ladder: {granted!r}"
    )


# ---------------------------------------------------------------------------
# School — PRD §3.5
# ---------------------------------------------------------------------------
_PROGRAM_TYPES = {"PUBLIC_IN_STATE", "PRIVATE_NATIONAL", "FOREIGN", "VOC_TECH"}


def assert_school(data: Dict[str, Any]) -> None:
    """PRD §3.5: 'A School is registered by a PlatformAdmin and carries
    an institutional name (1 to 200 characters), an 8-character
    facility_code unique across all schools, a program_type ... a
    yellow_ribbon_enrolled boolean flag ... and a 5-digit numeric
    zip_bah_code'."""
    assert_common_fields(data)
    assert isinstance(data.get("name"), str)
    assert 1 <= len(data["name"]) <= 200
    fc = data.get("facility_code")
    assert isinstance(fc, str) and len(fc) == 8, (
        f"facility_code must be 8 chars, got {fc!r}"
    )
    assert data.get("program_type") in _PROGRAM_TYPES, (
        f"unexpected program_type: {data.get('program_type')!r}"
    )
    assert isinstance(data.get("yellow_ribbon_enrolled"), bool)
    zip_code = data.get("zip_bah_code")
    assert (isinstance(zip_code, str) and len(zip_code) == 5
            and zip_code.isdigit()), (
        f"zip_bah_code must be 5 digits, got {zip_code!r}"
    )


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.6
# ---------------------------------------------------------------------------
_ENROLLMENT_STATUS = {
    "SUBMITTED", "CERTIFIED", "ACTIVE",
    "COMPLETED", "WITHDRAWN", "CANCELED",
}
_TRAINING_TIMES = {"FULL_TIME", "THREE_QUARTER", "HALF_TIME", "LESS_THAN_HALF"}
_DELIVERY_MODES = {"IN_PERSON", "ONLINE_ONLY"}


def assert_enrollment(data: Dict[str, Any]) -> None:
    """PRD §3.6: 'An enrollment is the unit of academic activity.'"""
    assert_common_fields(data)
    assert isinstance(data.get("veteran_id"), str)
    assert isinstance(data.get("school_id"), str)
    assert isinstance(data.get("term_start"), str)
    assert isinstance(data.get("term_end"), str)
    assert isinstance(data.get("tuition_charged"), (int, float))
    assert data["tuition_charged"] >= 0
    assert data.get("training_time") in _TRAINING_TIMES, (
        f"unexpected training_time: {data.get('training_time')!r}"
    )
    assert data.get("delivery_mode") in _DELIVERY_MODES, (
        f"unexpected delivery_mode: {data.get('delivery_mode')!r}"
    )
    assert data.get("status") in _ENROLLMENT_STATUS, (
        f"unexpected enrollment status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# YellowRibbonContribution — PRD §3.7
# ---------------------------------------------------------------------------
def assert_yellow_ribbon(data: Dict[str, Any]) -> None:
    """PRD §3.7: 'a YellowRibbonContribution that is created' carries
    tuition_gap, school_contribution, va_match, student_responsibility."""
    assert_common_fields(data)
    assert isinstance(data.get("enrollment_id"), str)
    for fld in ("tuition_gap", "school_contribution",
                "va_match", "student_responsibility"):
        assert isinstance(data.get(fld), (int, float)), (
            f"{fld} must be number, got {data.get(fld)!r}"
        )
        assert data[fld] >= 0, f"{fld} must be >= 0, got {data[fld]!r}"


# ---------------------------------------------------------------------------
# VocRehabPlan — PRD §3.11
# ---------------------------------------------------------------------------
_VOC_REHAB_STATUS = {
    "DRAFT", "APPROVED", "ACTIVE",
    "SUSPENDED", "COMPLETED", "TERMINATED",
}
_VOC_REHAB_TRAINING_MODES = {
    "FULL_TIME_INSTITUTIONAL", "THREE_QUARTER_INSTITUTIONAL",
    "HALF_TIME_INSTITUTIONAL", "FARM_COOP", "NON_PAY_OJT",
}


def assert_voc_rehab_plan(data: Dict[str, Any]) -> None:
    """PRD §3.11: 'A Counselor may create a Voc Rehab plan for a
    veteran by submitting the owning veteran_id and the training_mode
    ... The plan is created in DRAFT status with counselor_id null,
    suspension_count zero, and monthly_subsistence null.'"""
    assert_common_fields(data)
    assert isinstance(data.get("veteran_id"), str)
    assert data.get("training_mode") in _VOC_REHAB_TRAINING_MODES, (
        f"unexpected training_mode: {data.get('training_mode')!r}"
    )
    assert data.get("status") in _VOC_REHAB_STATUS, (
        f"unexpected voc rehab plan status: {data.get('status')!r}"
    )
    sc = data.get("suspension_count")
    assert isinstance(sc, int) and sc >= 0, (
        f"suspension_count must be non-negative int, got {sc!r}"
    )


# ---------------------------------------------------------------------------
# HousingPayment — PRD §3.10 (append-only)
# ---------------------------------------------------------------------------
_HOUSING_BASIS = {
    "IN_PERSON_TIERED", "ONLINE_HALF_NATIONAL", "PRORATED_PARTIAL_MONTH",
}


def assert_housing_payment(data: Dict[str, Any]) -> None:
    """PRD §3.10: 'A successful posting computes the housing allowance
    and creates a HousingPayment row recording the enrollment_id, the
    month_year, the computed amount (dollars to two decimal places),
    and the computation_basis'."""
    assert_append_only_fields(data)
    assert isinstance(data.get("enrollment_id"), str)
    my = data.get("month_year")
    assert isinstance(my, str) and len(my) == 7 and my[4] == "-", (
        f"month_year must be YYYY-MM, got {my!r}"
    )
    assert isinstance(data.get("amount"), (int, float))
    assert data["amount"] >= 0
    assert data.get("computation_basis") in _HOUSING_BASIS, (
        f"unexpected computation_basis: {data.get('computation_basis')!r}"
    )


# ---------------------------------------------------------------------------
# PaymentLedgerEntry — PRD §2.10 (append-only)
# ---------------------------------------------------------------------------
_LEDGER_SOURCES = {
    "TUITION_PAYMENT", "HOUSING_PAYMENT", "YELLOW_RIBBON_VA_MATCH",
    "VOC_REHAB_SUBSISTENCE", "ENTITLEMENT_DEBIT",
}


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    """PRD §2.10: 'Each entry records the veteran_id it belongs to, the
    source_entity that produced it ... the source_id of the producing
    row ... the amount_dollars ... and a server-stamped posted_at ISO
    8601 UTC timestamp set to the moment of emission.'"""
    assert_append_only_fields(data)
    assert isinstance(data.get("veteran_id"), str)
    assert data.get("source_entity") in _LEDGER_SOURCES, (
        f"unexpected source_entity: {data.get('source_entity')!r}"
    )
    assert isinstance(data.get("source_id"), str)
    assert isinstance(data.get("amount_dollars"), (int, float))
    assert isinstance(data.get("posted_at"), str)
    assert is_iso8601_timestamp(data["posted_at"]), (
        f"posted_at must be ISO 8601, got {data['posted_at']!r}"
    )


# ---------------------------------------------------------------------------
# Money & rating invariants — PRD §2.6
# ---------------------------------------------------------------------------
def assert_two_decimal_places(value: float) -> None:
    """PRD §2.6: 'All monetary fields ... are recorded with exactly two
    decimal places.'"""
    cents = round(value * 100)
    assert abs(value * 100 - cents) < 1e-6, (
        f"value {value!r} is not at 2 decimal places"
    )


def assert_combined_rating_clamped(rating: int) -> None:
    """PRD §3.4: 'The final figure is clamped into the inclusive range
    from 0 to 100 and written to Veteran.combined_rating.'"""
    assert isinstance(rating, int)
    assert COMBINED_RATING_MIN <= rating <= COMBINED_RATING_MAX, (
        f"combined_rating {rating} outside [{COMBINED_RATING_MIN}, "
        f"{COMBINED_RATING_MAX}]"
    )
    assert rating in RATING_LADDER, (
        f"combined_rating {rating} not on multiples-of-ten ladder"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_version_incremented_by",
    "assert_veteran",
    "assert_dependent",
    "assert_claim",
    "assert_school",
    "assert_enrollment",
    "assert_yellow_ribbon",
    "assert_voc_rehab_plan",
    "assert_housing_payment",
    "assert_ledger_entry",
    "assert_two_decimal_places",
    "assert_combined_rating_clamped",
]
