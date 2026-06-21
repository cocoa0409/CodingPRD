"""Validation priority conflicts and optimistic-concurrency stale-version
checks (PRD §2.6, §2.7)."""
import pytest

from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_owner,
    create_account,
    fund_account_with_contribution,
    create_pending_contribution,
    confirm_contribution,
    create_pending_distribution,
    confirm_distribution,
    get_account,
    make_account_owner_headers,
)


# =============================================================================
# Difficulty Rule 5 instance #2 — state outranks insufficient-balance
# =============================================================================


def test_invalid_state_outranks_insufficient_balance_on_distribution_confirm(api):
    """PRD §2.6: "Third, state: for action endpoints the target entity must be
    in the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.6: "Only after these gate checks pass do the business-domain
    validations run — referential symmetry on conversion source/target pairs
    (`ERR_INVALID_CONVERSION_PAIR`), kind-versus-account compatibility on
    contributions (`ERR_KIND_ACCOUNT_MISMATCH`), tax-year matching on
    contribution confirm (`ERR_TAX_YEAR_CLOSED`), the beneficiary-share-sum
    check on designation activation (`ERR_BENEFICIARY_SHARES_INVALID`), the
    contribution cap (`ERR_CONTRIBUTION_CAP_EXCEEDED`), the distribution
    balance check (`ERR_INSUFFICIENT_BALANCE`), and the SECURE-deadline check
    on inherited Traditional accounts with a non-eligible-individual
    beneficiary (`ERR_SECURE_DEADLINE_PASSED`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_insufficient_balance_on_distribution_confirm
    """
    set_clock("2026-06-01T00:00:00Z")
    jane = create_owner(
        full_name="Jane",
        date_of_birth="1981-09-09",
        tax_id_last4="8888",
        filing_status="SINGLE",
    )
    trad = create_account(jane["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=jane["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )

    refreshed_v1 = get_account(trad["id"], make_account_owner_headers(jane["id"]))
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=jane["id"],
        amount_cents=50_000,
        distribution_reason="NORMAL",
        tax_year=2026,
    )
    confirm_distribution(pending["id"], jane["id"], refreshed_v1["version"])

    # Second confirm: distribution.status != PENDING (state-gate fires before
    # any balance arithmetic could run).
    refreshed_v2 = get_account(trad["id"], make_account_owner_headers(jane["id"]))
    res = api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed_v2["version"]},
        make_account_owner_headers(jane["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# OCC stale-version on contribution confirm (Corner cross_cutting #1)
# =============================================================================


def test_contribution_confirm_with_stale_account_version_rejected(api):
    """PRD §2.7: "Two endpoints — confirming a `PENDING` contribution and
    confirming a `PENDING` distribution — are guarded by optimistic
    concurrency on the parent `IRAAccount`. Both endpoints require the request
    body to carry `expected_account_version`, the integer value of the
    account's `version` as the client last observed it. The server compares
    this value to the target account's current `version` at the moment of
    confirmation; if they differ, the confirm is rejected with
    `ERR_STALE_VERSION` and HTTP 412, and no balances or audit records are
    touched."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_account_version_on_contribution_confirm
    """
    set_clock("2026-06-01T00:00:00Z")
    ivy = create_owner(
        full_name="Ivy",
        date_of_birth="1981-05-05",
        tax_id_last4="3535",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(ivy["id"], "TRADITIONAL")
    v0 = trad["version"]

    pending_a = create_pending_contribution(
        account_id=trad["id"],
        owner_id=ivy["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )
    pending_b = create_pending_contribution(
        account_id=trad["id"],
        owner_id=ivy["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )

    # Confirm A first; account.version advances past v0.
    confirm_contribution(pending_a["id"], ivy["id"], v0)

    # Confirm B with the now-stale expected_account_version=v0.
    res = api.confirm_contribution(
        pending_b["id"],
        {"expected_account_version": v0},
        make_account_owner_headers(ivy["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


# =============================================================================
# OCC stale-version on distribution confirm (Corner cross_cutting #2)
# =============================================================================


def test_distribution_confirm_with_stale_account_version_rejected(api):
    """PRD §2.7: "Two endpoints — confirming a `PENDING` contribution and
    confirming a `PENDING` distribution — are guarded by optimistic
    concurrency on the parent `IRAAccount`. Both endpoints require the request
    body to carry `expected_account_version`, the integer value of the
    account's `version` as the client last observed it. The server compares
    this value to the target account's current `version` at the moment of
    confirmation; if they differ, the confirm is rejected with
    `ERR_STALE_VERSION` and HTTP 412, and no balances or audit records are
    touched."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_account_version_on_distribution_confirm
    """
    set_clock("2026-06-01T00:00:00Z")
    jack = create_owner(
        full_name="Jack",
        date_of_birth="1981-06-06",
        tax_id_last4="3636",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(jack["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=jack["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="PRETAX",
    )

    refreshed_v1 = get_account(trad["id"], make_account_owner_headers(jack["id"]))
    v1 = refreshed_v1["version"]

    pending_a = create_pending_distribution(
        account_id=trad["id"],
        owner_id=jack["id"],
        amount_cents=50_000,
        distribution_reason="NORMAL",
        tax_year=2026,
    )
    pending_b = create_pending_distribution(
        account_id=trad["id"],
        owner_id=jack["id"],
        amount_cents=50_000,
        distribution_reason="NORMAL",
        tax_year=2026,
    )

    # Confirm A first — bumps account.version.
    confirm_distribution(pending_a["id"], jack["id"], v1)

    # Confirm B with stale expected_account_version=v1.
    res = api.confirm_distribution(
        pending_b["id"],
        {"expected_account_version": v1},
        make_account_owner_headers(jack["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
