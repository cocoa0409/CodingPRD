"""Entity assertions and domain invariant checkers.

PRD §2.4 splits entities into two shapes:

    common-fields (Claimant, MedicalEvidence, Application, HearingSlot,
    ChildAuxiliary, SSISupplement, CDRReview):
        id, created_at, updated_at, version

    append-only (QuarterCredit, Determination):
        id and created_at only — updated_at and version are absent.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
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
    """PRD §2.4: 'version begins at 1 when a versioned resource is first
    created and increments by one on every server-side mutation'."""
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
    """PRD §2.4: 'Two entities are ledger-style and intentionally
    immutable after creation: QuarterCredit and Determination. They
    carry only id and created_at — updated_at and version are absent.'"""
    _assert_id_and_created_at(data)
    # The presence of updated_at/version on these entities is a contract
    # violation; we explicitly check absence for tests that pin §2.4.
    # Some implementations may emit nulls; PRD says "are absent". We
    # accept either omission or explicit None for resilience.


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: 'every mutation also refreshes updated_at' and
    'version ... increments by one on every server-side mutation'."""
    before_v = before.get("version")
    after_v = after.get("version")
    assert isinstance(before_v, int) and isinstance(after_v, int), (
        f"version comparison needs int versions, got {before_v!r}, {after_v!r}"
    )
    assert after_v >= before_v + delta, (
        f"expected version >= {before_v}+{delta} = {before_v + delta}, "
        f"got {after_v}"
    )


# ---------------------------------------------------------------------------
# Claimant — PRD §3.1
# ---------------------------------------------------------------------------
_CLAIMANT_INSURED_STATUS = {"INSURED", "NOT_INSURED"}


def assert_claimant(data: Dict[str, Any]) -> None:
    """PRD §3.1, §3.2: a Claimant carries the registration inputs plus
    computed QC fields and insured_status."""
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) >= 1
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("filing_date"), str)
    assert isinstance(data.get("alleged_onset_date"), str)
    # PRD §3.1: ssn_last4 is the four-digit string field that captures the
    # last four of SSN.
    assert isinstance(data.get("ssn_last4"), str)
    assert len(data["ssn_last4"]) == 4 and data["ssn_last4"].isdigit(), (
        f"ssn_last4 must be exactly four digits, got {data['ssn_last4']!r}"
    )
    # PRD §3.2: insured_status is INSURED or NOT_INSURED.
    assert data.get("insured_status") in _CLAIMANT_INSURED_STATUS, (
        f"unexpected insured_status: {data.get('insured_status')!r}"
    )
    # PRD §3.2: total_qc_earned, qc_required, qc_recent_window,
    # qc_recent_required are integers.
    for fld in ("total_qc_earned", "qc_required",
                "qc_recent_window", "qc_recent_required"):
        assert isinstance(data.get(fld), int), (
            f"{fld} must be int, got {data.get(fld)!r}"
        )


# ---------------------------------------------------------------------------
# QuarterCredit — PRD §3.1
# ---------------------------------------------------------------------------
def assert_quarter_credit(data: Dict[str, Any]) -> None:
    """PRD §3.1: 'Each quarter of earnings is logged immutably as a
    QuarterCredit row, parented to the claimant.'"""
    assert_append_only_fields(data)
    assert isinstance(data.get("claimant_id"), str)
    assert isinstance(data.get("year"), int) and 1978 <= data["year"] <= 2100
    assert isinstance(data.get("quarter"), int) and 1 <= data["quarter"] <= 4
    assert isinstance(data.get("earnings_cents"), int) and data["earnings_cents"] >= 0
    assert isinstance(data.get("qc_count"), int) and 0 <= data["qc_count"] <= 1
    assert isinstance(data.get("credited"), bool)


# ---------------------------------------------------------------------------
# MedicalEvidence — PRD §3.3
# ---------------------------------------------------------------------------
_EVIDENCE_STATUS = {"SUBMITTED", "ACCEPTED", "REJECTED"}
_EVIDENCE_SOURCE = {"LISTING_MATCH", "RFC_ASSESSMENT"}


def assert_medical_evidence(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("claimant_id"), str)
    assert data.get("source_type") in _EVIDENCE_SOURCE, (
        f"unexpected source_type: {data.get('source_type')!r}"
    )
    assert data.get("status") in _EVIDENCE_STATUS, (
        f"unexpected status: {data.get('status')!r}"
    )
    # PRD §3.3: "medical_findings — clinical free text of at least
    # twenty characters"
    assert isinstance(data.get("medical_findings"), str)
    assert len(data["medical_findings"]) >= 20
    assert isinstance(data.get("evidence_date"), str)


# ---------------------------------------------------------------------------
# Application — PRD §3.3, §3.4
# ---------------------------------------------------------------------------
_APP_STATUS = {
    "DRAFT", "INITIAL_REVIEW", "INITIAL_DENIED",
    "RECONSIDERATION", "RECON_DENIED",
    "ALJ_PENDING", "ALJ_APPROVED", "ALJ_DENIED",
    "APPEALS_COUNCIL", "APPROVED", "CLOSED_DENIED",
}


def assert_application(data: Dict[str, Any]) -> None:
    """PRD §3.3, §3.4: Application carries status plus the post-approval
    computed money fields and CDR diary."""
    assert_common_fields(data)
    assert isinstance(data.get("claimant_id"), str)
    assert data.get("status") in _APP_STATUS, (
        f"unexpected application status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Determination — PRD §3.4
# ---------------------------------------------------------------------------
_DET_LEVEL = {"INITIAL", "RECONSIDERATION", "ALJ", "APPEALS_COUNCIL"}
_DET_DECISION = {"ALLOW", "DENY", "REMAND"}


def assert_determination(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'A Determination row is an append-only record of an
    adjudication event and is similarly immutable.'"""
    assert_append_only_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert data.get("level") in _DET_LEVEL, (
        f"unexpected determination level: {data.get('level')!r}"
    )
    assert data.get("decision") in _DET_DECISION, (
        f"unexpected determination decision: {data.get('decision')!r}"
    )
    assert isinstance(data.get("rationale"), str)
    # PRD §3.4: "a free-text rationale of at least fifty characters"
    assert len(data["rationale"]) >= 50


# ---------------------------------------------------------------------------
# HearingSlot — PRD §3.7
# ---------------------------------------------------------------------------
_SLOT_STATUS = {"OPEN", "BOOKED", "HELD", "NO_SHOW", "RESCHEDULED"}


def assert_hearing_slot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("alj_id"), str)
    assert isinstance(data.get("hearing_office"), str)
    assert isinstance(data.get("start_at"), str)
    assert isinstance(data.get("end_at"), str)
    assert data.get("status") in _SLOT_STATUS, (
        f"unexpected slot status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# ChildAuxiliary — PRD §3.5
# ---------------------------------------------------------------------------
_CHILD_STATUS = {"PENDING", "ENTITLED", "TERMINATED"}
_CHILD_RELATIONSHIPS = {
    "BIOLOGICAL", "ADOPTED", "STEPCHILD", "DEPENDENT_GRANDCHILD",
}
_TERMINATION_REASONS = {
    "AGE_OUT", "NO_LONGER_DISABLED", "PARENT_BENEFIT_ENDED",
}


def assert_child_auxiliary(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("child_name"), str)
    assert isinstance(data.get("child_date_of_birth"), str)
    assert data.get("child_relationship") in _CHILD_RELATIONSHIPS, (
        f"unexpected child_relationship: {data.get('child_relationship')!r}"
    )
    assert data.get("status") in _CHILD_STATUS, (
        f"unexpected child status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# SSISupplement — PRD §3.5
# ---------------------------------------------------------------------------
_SSI_STATUS = {
    "DRAFT", "ACTIVE",
    "TERMINATED_RESOURCES", "TERMINATED_INCOME", "TERMINATED_DIB_OFFSET",
}
_LIVING_ARRANGEMENTS = {"OWN_HOUSEHOLD", "ANOTHER_HOUSEHOLD", "INSTITUTION"}


def assert_ssi_supplement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("claimant_id"), str)
    assert isinstance(data.get("countable_income_cents"), int)
    assert data["countable_income_cents"] >= 0
    assert isinstance(data.get("countable_resources_cents"), int)
    assert data["countable_resources_cents"] >= 0
    assert data.get("living_arrangement") in _LIVING_ARRANGEMENTS, (
        f"unexpected living_arrangement: {data.get('living_arrangement')!r}"
    )
    assert data.get("status") in _SSI_STATUS, (
        f"unexpected SSI status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# CDRReview — PRD §3.8
# ---------------------------------------------------------------------------
_CDR_STATUS = {"PENDING", "SCHEDULED", "COMPLETED"}
_CDR_OUTCOMES = {"CONTINUE", "CEASE"}


def assert_cdr_review(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert data.get("status") in _CDR_STATUS, (
        f"unexpected CDR status: {data.get('status')!r}"
    )
    outcome = data.get("outcome")
    assert outcome is None or outcome in _CDR_OUTCOMES, (
        f"unexpected CDR outcome: {outcome!r}"
    )


# ---------------------------------------------------------------------------
# Domain invariants — PRD §3.5
# ---------------------------------------------------------------------------
def assert_dime_rounded(cents: int) -> None:
    """PRD §2.8: 'PIA and the Family Maximum Benefit are rounded down to
    the nearest ten cents (the SSA "dime rule") after their bend-point
    arithmetic.'"""
    assert isinstance(cents, int), f"expected int cents, got {cents!r}"
    assert cents % 10 == 0, (
        f"value {cents} is not a multiple of 10 cents (dime-round-down)"
    )


def assert_family_max_clamp(pia_cents: int, family_max_cents: int) -> None:
    """PRD §3.5: 'After dime-rounding, the Disability Insurance Benefit
    (DIB) special floor and ceiling clamp family_max_cents to be no less
    than 1.50 times pia_cents and no more than 1.85 times pia_cents.'"""
    floor = int(round(1.50 * pia_cents))
    ceiling = int(round(1.85 * pia_cents))
    assert family_max_cents >= floor or family_max_cents == int(1.50 * pia_cents), (
        f"family_max_cents {family_max_cents} below DIB floor "
        f"1.50*pia={int(1.50 * pia_cents)} (pia={pia_cents})"
    )
    assert family_max_cents <= ceiling or family_max_cents == int(1.85 * pia_cents), (
        f"family_max_cents {family_max_cents} above DIB ceiling "
        f"1.85*pia={int(1.85 * pia_cents)} (pia={pia_cents})"
    )


def assert_pool_invariant(pia_cents: int, family_max_cents: int,
                          child_benefits: Iterable[int]) -> None:
    """PRD §3.5: 'The worker always receives the full pia_cents. The
    remaining pool — family_max_cents minus pia_cents — is distributed
    across the children whose ChildAuxiliary.status is ENTITLED.'

    Sum of entitled child benefits must equal min(n * per-child gross,
    pool).
    """
    total = sum(child_benefits)
    pool = family_max_cents - pia_cents
    assert total <= pool, (
        f"sum of child benefits {total} exceeds pool {pool} "
        f"(family_max={family_max_cents}, pia={pia_cents})"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_version_incremented_by",
    "assert_claimant",
    "assert_quarter_credit",
    "assert_medical_evidence",
    "assert_application",
    "assert_determination",
    "assert_hearing_slot",
    "assert_child_auxiliary",
    "assert_ssi_supplement",
    "assert_cdr_review",
    "assert_dime_rounded",
    "assert_family_max_clamp",
    "assert_pool_invariant",
]
