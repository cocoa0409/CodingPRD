"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4 splits entities into two shapes:

    common-fields (Claimant, Employer, Claim, WeeklyCertification,
    Overpayment, Appeal, EmployerCharge, PandemicExtension):
        id, created_at, updated_at, version

    append-only (WageRecord, WorkSearchEntry, BenefitPayment):
        id and created_at only — no updated_at, no version.

    SystemClock (singleton): carries only `now`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

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
    """PRD §2.4: 'The version is a non-negative integer that starts at 1
    on creation and increments by one on every server-side mutation.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: common-fields entities expose id, created_at, updated_at,
    version."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only entities (WageRecord, WorkSearchEntry,
    BenefitPayment) carry only id and created_at."""
    _assert_id_and_created_at(data)


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.6: 'each resource whose state, computed field, or
    relationship changes has its own updated_at refreshed and its own
    version incremented'."""
    before_v = before.get("version")
    after_v = after.get("version")
    assert isinstance(before_v, int) and isinstance(after_v, int), (
        f"version comparison needs int versions, "
        f"got {before_v!r}, {after_v!r}"
    )
    assert after_v >= before_v + delta, (
        f"expected version >= {before_v}+{delta} = {before_v + delta}, "
        f"got {after_v}"
    )


# ---------------------------------------------------------------------------
# Claimant — PRD §3.1
# ---------------------------------------------------------------------------
def assert_claimant(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("ssn_last4"), str), (
        f"ssn_last4 must be string, got {data.get('ssn_last4')!r}"
    )
    assert len(data["ssn_last4"]) == 4 and data["ssn_last4"].isdigit(), (
        f"ssn_last4 must be exactly 4 digits, got {data['ssn_last4']!r}"
    )
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("state_residence"), str)
    assert len(data["state_residence"]) == 2, (
        "state_residence must be two-letter US state code"
    )
    assert isinstance(data.get("date_of_birth"), str)
    # PRD §3.1: "lifetime_overpayment_balance_cents initialised to 0;
    # that field is server-computed".
    assert isinstance(data.get("lifetime_overpayment_balance_cents"), int)
    assert data["lifetime_overpayment_balance_cents"] >= 0


# ---------------------------------------------------------------------------
# Employer — PRD §3.1
# ---------------------------------------------------------------------------
def assert_employer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("ein"), str)
    assert len(data["ein"]) == 9 and data["ein"].isdigit(), (
        f"ein must be exactly 9 digits, got {data['ein']!r}"
    )
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("reserve_ratio_basis_cents"), int)
    assert data["reserve_ratio_basis_cents"] > 0, (
        "reserve_ratio_basis_cents must be strictly greater than zero"
    )
    assert isinstance(data.get("taxable_payroll_cents"), int)
    assert data["taxable_payroll_cents"] >= 0
    # PRD §3.1: "The persisted experience_rate_bps is bounded between the
    # 1.00% floor (100 basis points) and the 5.40% ceiling (540 basis
    # points)."
    assert isinstance(data.get("experience_rate_bps"), int)
    assert 100 <= data["experience_rate_bps"] <= 540, (
        f"experience_rate_bps must be in [100, 540], "
        f"got {data['experience_rate_bps']}"
    )


# ---------------------------------------------------------------------------
# WageRecord — PRD §3.1
# ---------------------------------------------------------------------------
def assert_wage_record(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'a WageRecord is filed once and corrected only by filing
    a new WageRecord for the same employer-quarter'. Append-only — only
    id and created_at."""
    assert_append_only_fields(data)
    assert isinstance(data.get("claimant_id"), str)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("quarter_year"), int)
    assert isinstance(data.get("quarter_index"), int)
    assert 1 <= data["quarter_index"] <= 4
    assert isinstance(data.get("wages_cents"), int)
    assert data["wages_cents"] >= 0
    # Append-only: must NOT carry updated_at / version
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "WageRecord is append-only; updated_at must not be present"
    )
    assert "version" not in data or data.get("version") is None, (
        "WageRecord is append-only; version must not be present"
    )


# ---------------------------------------------------------------------------
# Claim — PRD §3.2
# ---------------------------------------------------------------------------
CLAIM_STATES = {
    "DRAFT", "PENDING_ADJUDICATION", "MONETARILY_ELIGIBLE", "DENIED",
    "ACTIVE", "EXHAUSTED", "EXTENDED", "CLOSED",
}


def assert_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("claimant_id"), str)
    assert data.get("status") in CLAIM_STATES, (
        f"unexpected claim status: {data.get('status')!r}"
    )
    # weeks_paid and weeks_remaining are computed integers; PRD §3.2
    # "weeks_paid (the count of APPROVED certifications under this
    # claim)".
    assert isinstance(data.get("weeks_paid", 0), int)
    assert data.get("weeks_paid", 0) >= 0
    # PRD §3.2: weeks_remaining is floored at zero.
    if "weeks_remaining" in data and data["weeks_remaining"] is not None:
        assert isinstance(data["weeks_remaining"], int)
        assert data["weeks_remaining"] >= 0


def assert_claim_monetary_fields_set(data: Dict[str, Any]) -> None:
    """For claims past PENDING_ADJUDICATION: monetary computations should
    be populated (PRD §3.2 submit cascade)."""
    assert data.get("base_period_variant") in ("STANDARD", "ALTERNATE")
    assert isinstance(data.get("base_period_total_wages_cents"), int)
    assert isinstance(data.get("high_quarter_wages_cents"), int)
    assert isinstance(data.get("weekly_benefit_amount_cents"), int)
    assert isinstance(data.get("max_weeks_of_eligibility"), int)


# ---------------------------------------------------------------------------
# WeeklyCertification — PRD §3.3
# ---------------------------------------------------------------------------
WC_STATES = {"SUBMITTED", "APPROVED", "DENIED", "OVERPAID"}


def assert_weekly_certification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("claim_id"), str)
    assert isinstance(data.get("week_ending_date"), str)
    assert data.get("status") in WC_STATES, (
        f"unexpected weekly-certification status: {data.get('status')!r}"
    )
    assert isinstance(data.get("earnings_reported_cents", 0), int)
    assert data.get("earnings_reported_cents", 0) >= 0
    assert isinstance(data.get("able_and_available"), bool)
    assert isinstance(data.get("work_search_count", 0), int)
    assert isinstance(data.get("payable_amount_cents", 0), int)
    assert data.get("payable_amount_cents", 0) >= 0


# ---------------------------------------------------------------------------
# WorkSearchEntry — PRD §3.3, §2.4
# ---------------------------------------------------------------------------
CONTACT_METHODS = {
    "ONLINE_APPLICATION", "IN_PERSON", "PHONE", "EMAIL", "REFERRAL",
}


def assert_work_search_entry(data: Dict[str, Any]) -> None:
    """PRD §2.4: WorkSearchEntry is append-only."""
    assert_append_only_fields(data)
    assert isinstance(data.get("certification_id"), str)
    assert isinstance(data.get("contact_date"), str)
    assert isinstance(data.get("employer_name"), str)
    assert data.get("contact_method") in CONTACT_METHODS, (
        f"unexpected contact_method: {data.get('contact_method')!r}"
    )


# ---------------------------------------------------------------------------
# BenefitPayment — PRD §3.3, §2.4
# ---------------------------------------------------------------------------
BENEFIT_PAYMENT_STATES = {"ISSUED", "REVERSED"}


def assert_benefit_payment(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'A BenefitPayment is likewise structurally append-only —
    once issued it carries only id and created_at, and a reversal is
    represented by mutating its own status to REVERSED (with the
    human-supplied reversed_reason field populated) rather than by
    deleting and rewriting it; for the same reason a BenefitPayment
    does not expose updated_at or version.'"""
    assert_append_only_fields(data)
    assert isinstance(data.get("claim_id"), str)
    assert isinstance(data.get("certification_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert isinstance(data.get("issued_at"), str)
    assert data.get("status") in BENEFIT_PAYMENT_STATES, (
        f"unexpected payment status: {data.get('status')!r}"
    )
    # PRD §3.3: "starts at ISSUED with reversed_reason null".
    if data.get("status") == "ISSUED":
        assert data.get("reversed_reason") in (None, ""), (
            "ISSUED payment must have reversed_reason null"
        )
    # Append-only: must NOT carry updated_at / version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "BenefitPayment is append-only; updated_at must not be present"
    )
    assert "version" not in data or data.get("version") is None, (
        "BenefitPayment is append-only; version must not be present"
    )


# ---------------------------------------------------------------------------
# Overpayment — PRD §3.5
# ---------------------------------------------------------------------------
OVERPAYMENT_STATES = {"OUTSTANDING", "REPAID", "WAIVED", "WRITTEN_OFF"}
OVERPAYMENT_CLASSIFICATIONS = {"AGENCY_ERROR", "NON_FRAUD", "FRAUD"}


def assert_overpayment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("claim_id"), str)
    assert isinstance(data.get("principal_cents"), int)
    assert data["principal_cents"] > 0
    assert isinstance(data.get("balance_cents"), int)
    assert data["balance_cents"] >= 0
    assert data.get("classification") in OVERPAYMENT_CLASSIFICATIONS, (
        f"unexpected classification: {data.get('classification')!r}"
    )
    assert data.get("status") in OVERPAYMENT_STATES, (
        f"unexpected overpayment status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Appeal — PRD §3.6
# ---------------------------------------------------------------------------
APPEAL_SUBJECT_TYPES = {
    "MONETARY_DETERMINATION", "WEEKLY_DENIAL", "OVERPAYMENT_ASSESSMENT",
}
APPEAL_STATES = {
    "FILED", "IN_HEARING", "SUSTAINED", "REVERSED",
    "WITHDRAWN", "DISMISSED_LATE",
}


def assert_appeal(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("claim_id"), str)
    assert data.get("subject_type") in APPEAL_SUBJECT_TYPES, (
        f"unexpected subject_type: {data.get('subject_type')!r}"
    )
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("subject_locked_version"), int)
    assert isinstance(data.get("assigned_adjudicator_id"), str)
    assert isinstance(data.get("assigned_appeal_officer_id"), str)
    assert isinstance(data.get("filed_at"), str)
    assert isinstance(data.get("deadline_at"), str)
    assert data.get("status") in APPEAL_STATES, (
        f"unexpected appeal status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# EmployerCharge — PRD §3.3, §3.7
# ---------------------------------------------------------------------------
EMPLOYER_CHARGE_STATES = {"ACTIVE", "REVERSED", "RELIEVED"}


def assert_employer_charge(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("claim_id"), str)
    assert isinstance(data.get("payment_id"), str)
    assert isinstance(data.get("charge_cents"), int)
    assert data["charge_cents"] >= 0
    assert data.get("status") in EMPLOYER_CHARGE_STATES, (
        f"unexpected charge status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# PandemicExtension — PRD §3.4
# ---------------------------------------------------------------------------
PANDEMIC_EXTENSION_STATES = {"SCHEDULED", "ACTIVE", "EXPIRED"}


def assert_pandemic_extension(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("program_name"), str)
    assert isinstance(data.get("effective_start"), str)
    assert isinstance(data.get("effective_end"), str)
    assert isinstance(data.get("extra_weeks"), int)
    # PRD §3.4: "an extra_weeks count between 1 and 26 inclusive."
    assert 1 <= data["extra_weeks"] <= 26
    assert data.get("status") in PANDEMIC_EXTENSION_STATES, (
        f"unexpected extension status: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Domain invariants — cross-entity sums, conservation properties
# ---------------------------------------------------------------------------
def assert_charge_dollar_conservation(
    charges: List[Dict[str, Any]],
    payment_amount_cents: int,
    counted_statuses: Iterable[str] = ("ACTIVE",),
) -> None:
    """PRD §2.8: 'Round half up for per-employer charge allocation, with
    a residual-reconciliation pass guaranteeing that the sum of issued
    EmployerCharge.charge_cents equals the originating
    BenefitPayment.amount_cents exactly.'"""
    counted = set(counted_statuses)
    total = sum(
        c["charge_cents"] for c in charges
        if c.get("status") in counted
    )
    assert total == payment_amount_cents, (
        f"charge dollar conservation violated: "
        f"sum(charge_cents) = {total}, expected {payment_amount_cents}"
    )


def assert_weeks_invariant(claim: Dict[str, Any]) -> None:
    """PRD §3.3: 'weeks_remaining (the claim's max_weeks_of_eligibility
    plus any pandemic_extension_weeks_granted, minus weeks_paid, floored
    at zero).'"""
    max_w = claim.get("max_weeks_of_eligibility")
    paid = claim.get("weeks_paid", 0)
    rem = claim.get("weeks_remaining")
    granted = claim.get("pandemic_extension_weeks_granted", 0) or 0
    if max_w is None or rem is None:
        return  # Only meaningful after submit; skip for DRAFT claims.
    expected = max(0, max_w + granted - paid)
    assert rem == expected, (
        f"weeks_remaining invariant violated: "
        f"weeks_remaining={rem}, expected max(0, "
        f"{max_w}+{granted}-{paid})={expected}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_version_incremented_by",
    "assert_claimant",
    "assert_employer",
    "assert_wage_record",
    "assert_claim",
    "assert_claim_monetary_fields_set",
    "assert_weekly_certification",
    "assert_work_search_entry",
    "assert_benefit_payment",
    "assert_overpayment",
    "assert_appeal",
    "assert_employer_charge",
    "assert_pandemic_extension",
    "assert_charge_dollar_conservation",
    "assert_weeks_invariant",
    "CLAIM_STATES",
    "WC_STATES",
    "CONTACT_METHODS",
    "BENEFIT_PAYMENT_STATES",
    "OVERPAYMENT_STATES",
    "OVERPAYMENT_CLASSIFICATIONS",
    "APPEAL_SUBJECT_TYPES",
    "APPEAL_STATES",
    "EMPLOYER_CHARGE_STATES",
    "PANDEMIC_EXTENSION_STATES",
]
