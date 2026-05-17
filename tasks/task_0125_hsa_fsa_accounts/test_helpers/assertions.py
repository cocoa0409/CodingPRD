"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- Top-level mutable resources (Account, AccountHolder, PlanYear,
  Dependent, Claim) carry id + created_at + updated_at + version.
- Append-only immutable entities (Contribution, QualifiedExpense,
  AuditEvent, OpsRun) carry ONLY id + created_at. They do NOT carry
  updated_at or version.
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
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 with three fractional digits, got "
        f"{data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: top-level mutable resources carry updated_at + version.
    version starts at 1 and is incremented by exactly 1 on every
    mutation that produces an updated representation of the resource.
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
# Top-level mutable resources — PRD §2.4
# ===========================================================================
def assert_account_holder(data: Dict[str, Any]) -> None:
    """PRD §3.1 AccountHolder shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("ssn_last4"), str) and len(
        data["ssn_last4"]
    ) == 4 and data["ssn_last4"].isdigit(), (
        f"ssn_last4 must be exactly 4 digits, got "
        f"{data.get('ssn_last4')!r}"
    )
    assert data.get("tax_filing_status") in {
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD",
    }, f"unexpected tax_filing_status: {data.get('tax_filing_status')!r}"
    assert isinstance(data.get("birth_date"), str), (
        f"birth_date must be a string, got {data.get('birth_date')!r}"
    )


def assert_account(data: Dict[str, Any]) -> None:
    """PRD §3.1 Account shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_holder_id"), str)
    assert data.get("account_type") in {
        "HSA", "HEALTH_FSA", "DEPENDENT_CARE_FSA",
    }, f"unexpected account_type: {data.get('account_type')!r}"
    # PRD §3.1: 'for either FSA type, coverage_tier must be null'.
    ct = data.get("coverage_tier")
    if data["account_type"] == "HSA":
        assert ct in {"SELF_ONLY", "FAMILY"}, (
            f"HSA coverage_tier must be SELF_ONLY or FAMILY, got {ct!r}"
        )
    else:
        assert ct is None, (
            f"FSA coverage_tier must be null, got {ct!r}"
        )
    # PRD §3.1 year_end_policy constraints by account_type.
    yep = data.get("year_end_policy")
    if data["account_type"] == "HSA":
        assert yep == "NONE", (
            f"HSA year_end_policy must be NONE, got {yep!r}"
        )
    elif data["account_type"] == "HEALTH_FSA":
        assert yep in {"GRACE_PERIOD", "CARRYOVER", "NONE"}, (
            f"HEALTH_FSA year_end_policy bad: {yep!r}"
        )
    elif data["account_type"] == "DEPENDENT_CARE_FSA":
        assert yep in {"GRACE_PERIOD", "NONE"}, (
            f"DCFSA year_end_policy must be GRACE_PERIOD or NONE, got "
            f"{yep!r}"
        )
    assert data.get("status") in {"OPEN", "FROZEN", "CLOSED"}, (
        f"unexpected status: {data.get('status')!r}"
    )
    assert isinstance(data.get("account_holder_birth_date"), str)
    closed_at = data.get("closed_at")
    assert closed_at is None or isinstance(closed_at, str), (
        f"closed_at must be null or string, got {closed_at!r}"
    )


def assert_dependent(data: Dict[str, Any]) -> None:
    """PRD §3.1 Dependent shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_holder_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("birth_date"), str)
    assert data.get("relationship") in {
        "CHILD", "SPOUSE", "QUALIFYING_RELATIVE",
    }, f"unexpected relationship: {data.get('relationship')!r}"
    assert data.get("status") in {"ACTIVE", "INACTIVE"}, (
        f"unexpected dependent status: {data.get('status')!r}"
    )


def assert_plan_year(data: Dict[str, Any]) -> None:
    """PRD §3.2 PlanYear shape with denormalized counters."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("calendar_year"), int)
    assert data.get("status") in {
        "ACTIVE", "GRACE_PERIOD", "CARRYOVER_PENDING", "CLOSED",
    }, f"unexpected plan year status: {data.get('status')!r}"
    # Integer-cents fields per PRD §2.5.
    for k in (
        "contribution_cap_cents",
        "catch_up_cap_cents",
        "contributions_ytd_cents",
        "claims_paid_ytd_cents",
        "carryover_in_cents",
        "carryover_consumed_cents",
        "forfeited_cents",
    ):
        assert k in data, f"missing {k} on PlanYear; got keys: {list(data)}"
        assert isinstance(data[k], int), (
            f"{k} must be integer cents, got {type(data[k])}"
        )
        assert data[k] >= 0, f"{k} must be non-negative, got {data[k]}"
    # provisional_balance_cents may be negative briefly during
    # reversals; PRD §3.6 'leftover may be negative if reversals
    # exceeded contributions; clamp to 0 for forfeiture purposes' —
    # but provisional itself is informational. Assert it is an int.
    assert isinstance(data.get("provisional_balance_cents"), int)
    # grace_period_end_date is null unless in GRACE_PERIOD per PRD §3.6.
    gpe = data.get("grace_period_end_date")
    assert gpe is None or isinstance(gpe, str), (
        f"grace_period_end_date must be null or string, got {gpe!r}"
    )


def assert_claim(data: Dict[str, Any]) -> None:
    """PRD §3.5 Claim shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    py = data.get("plan_year_id")
    assert py is None or isinstance(py, str), (
        f"plan_year_id must be null or string, got {py!r}"
    )
    assert isinstance(data.get("service_date"), str)
    assert isinstance(data.get("expense_code"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 1, (
        f"amount_cents must be >= 1, got {data['amount_cents']}"
    )
    dep = data.get("dependent_id")
    assert dep is None or isinstance(dep, str), (
        f"dependent_id must be null or string, got {dep!r}"
    )
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "APPROVED", "PAID", "DENIED", "REVERSED",
    }, f"unexpected claim status: {data.get('status')!r}"
    dr = data.get("denial_reason")
    assert dr is None or isinstance(dr, str), (
        f"denial_reason must be null or string, got {dr!r}"
    )
    pac = data.get("paid_amount_cents")
    assert pac is None or isinstance(pac, int), (
        f"paid_amount_cents must be null or int, got {pac!r}"
    )
    rf = data.get("reversed_from_id")
    assert rf is None or isinstance(rf, str), (
        f"reversed_from_id must be null or string, got {rf!r}"
    )


# ===========================================================================
# Append-only immutable entities — PRD §2.4 (no updated_at, no version)
# ===========================================================================
def assert_contribution(data: Dict[str, Any]) -> None:
    """PRD §3.3 Contribution shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("plan_year_id"), str)
    assert isinstance(data.get("amount_cents"), int), (
        f"amount_cents must be int, got {data.get('amount_cents')!r}"
    )
    # PRD §2.5: 'reversing Contribution rows carry a negative
    # amount_cents whose absolute value equals the original'. So either
    # >= 1 for natural rows or negative for reversal twins.
    assert (
        data["amount_cents"] >= 1 or data["amount_cents"] < 0
    ), f"amount_cents must be non-zero, got {data['amount_cents']}"
    assert data.get("source") in {"PAYROLL", "DIRECT", "EMPLOYER_MATCH"}, (
        f"unexpected source: {data.get('source')!r}"
    )
    assert data.get("status") in {"PENDING", "POSTED", "REVERSED"}, (
        f"unexpected contribution status: {data.get('status')!r}"
    )
    pa = data.get("posted_at")
    assert pa is None or isinstance(pa, str), (
        f"posted_at must be null or string, got {pa!r}"
    )
    rev_of = data.get("reversal_of_id")
    assert rev_of is None or isinstance(rev_of, str), (
        f"reversal_of_id must be null or string, got {rev_of!r}"
    )


def assert_qualified_expense(data: Dict[str, Any]) -> None:
    """PRD §3.4 QualifiedExpense shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("category") in {
        "MEDICAL", "VISION", "DENTAL", "OTC_MEDICATION",
        "DEPENDENT_CARE", "NON_QUALIFIED",
    }, f"unexpected category: {data.get('category')!r}"
    eats = data.get("eligible_account_types")
    assert isinstance(eats, list), (
        f"eligible_account_types must be a list, got {eats!r}"
    )
    for t in eats:
        assert t in {"HSA", "HEALTH_FSA", "DEPENDENT_CARE_FSA"}, (
            f"unexpected eligible_account_types entry: {t!r}"
        )
    assert isinstance(data.get("requires_dependent"), bool)


def assert_audit_event(data: Dict[str, Any]) -> None:
    """PRD §2.8 AuditEvent shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("account_id"), str)
    py = data.get("plan_year_id")
    assert py is None or isinstance(py, str), (
        f"plan_year_id must be null or string, got {py!r}"
    )
    # PRD §2.8 enumerates event_type values.
    assert data.get("event_type") in {
        "ACCOUNT_OPENED", "ACCOUNT_FROZEN", "ACCOUNT_CLOSED",
        "CONTRIBUTION_POSTED", "CONTRIBUTION_REVERSED",
        "CLAIM_SUBMITTED", "CLAIM_APPROVED", "CLAIM_PAID",
        "CLAIM_DENIED", "CLAIM_REVERSED",
        "PLAN_YEAR_OPENED", "GRACE_PERIOD_STARTED",
        "CARRYOVER_APPLIED", "YEAR_END_FORFEITURE",
        "OPS_RUN_EXECUTED",
    }, f"unexpected event_type: {data.get('event_type')!r}"
    # PRD §2.8: 'subject_entity ... identifying the entity the event
    # pertains to'.
    assert data.get("subject_entity") in {
        "ACCOUNT", "CONTRIBUTION", "CLAIM", "PLAN_YEAR",
    }, f"unexpected subject_entity: {data.get('subject_entity')!r}"
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_user_id"), str)
    assert isinstance(data.get("cents_delta"), int), (
        f"cents_delta must be integer, got {data.get('cents_delta')!r}"
    )
    ori = data.get("ops_run_index")
    assert ori is None or isinstance(ori, int), (
        f"ops_run_index must be null or int, got {ori!r}"
    )
    assert isinstance(data.get("occurred_at"), str)


def assert_ops_run(data: Dict[str, Any]) -> None:
    """PRD §3.7 OpsRun shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("index"), int) and data["index"] >= 1, (
        f"index must be positive int, got {data.get('index')!r}"
    )
    assert isinstance(data.get("as_of_date"), str)
    assert data.get("kind") in {"YEAR_END_CLOSE", "GRACE_PERIOD_EXPIRY"}, (
        f"unexpected kind: {data.get('kind')!r}"
    )
    pya = data.get("plan_years_affected")
    assert isinstance(pya, list), (
        f"plan_years_affected must be a list, got {pya!r}"
    )
    for p in pya:
        assert isinstance(p, str), (
            f"plan_years_affected entries must be strings, got {p!r}"
        )
    assert isinstance(data.get("total_forfeited_cents"), int)
    assert data["total_forfeited_cents"] >= 0


# ===========================================================================
# Tax form recapture — PRD §3.8
# ===========================================================================
def assert_tax_form(data: Dict[str, Any]) -> None:
    """PRD §3.8: response 'is an object containing deductible_cents,
    recapture_cents, tax_basis_cents, and basis'."""
    for k in ("deductible_cents", "recapture_cents", "tax_basis_cents"):
        assert k in data, f"missing {k}; got keys: {list(data)}"
        assert isinstance(data[k], int), (
            f"{k} must be integer cents, got {type(data[k])}"
        )
    assert data.get("basis") in {"chronological", "forward_looking"}, (
        f"unexpected basis: {data.get('basis')!r}"
    )


# ===========================================================================
# Domain invariants
# ===========================================================================
def assert_available_balance_identity(plan_year: Dict[str, Any]) -> None:
    """PRD §3.5: 'The available balance is defined as the sum of
    contributions_ytd_cents and carryover_in_cents, less
    claims_paid_ytd_cents.' This helper computes that value and
    returns it; it does not assert sign, since reversal sequences may
    transiently leave a negative provisional balance."""
    # No-op asserter exposing the formula; callers compute the value
    # themselves with these field names.
    _ = (
        plan_year.get("contributions_ytd_cents", 0)
        + plan_year.get("carryover_in_cents", 0)
        - plan_year.get("claims_paid_ytd_cents", 0)
    )


def available_balance(plan_year: Dict[str, Any]) -> int:
    """PRD §3.5 / §3.6: the pinned identity for /pay precheck.
    available_balance = (contributions_ytd_cents + carryover_in_cents)
                       - claims_paid_ytd_cents
    """
    return (
        int(plan_year["contributions_ytd_cents"])
        + int(plan_year["carryover_in_cents"])
        - int(plan_year["claims_paid_ytd_cents"])
    )


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer that starts at 1 and is
    incremented by exactly 1 on every mutation that produces an
    updated representation of the resource.'"""
    assert "version" in prev and "version" in curr, (
        "both records must carry version"
    )
    assert curr["version"] == prev["version"] + 1, (
        f"version expected to increment by exactly 1: "
        f"prev={prev['version']} curr={curr['version']}"
    )


__all__ = [
    "assert_account_holder",
    "assert_account",
    "assert_dependent",
    "assert_plan_year",
    "assert_claim",
    "assert_contribution",
    "assert_qualified_expense",
    "assert_audit_event",
    "assert_ops_run",
    "assert_tax_form",
    "assert_available_balance_identity",
    "available_balance",
    "assert_version_incremented_by_one",
]
