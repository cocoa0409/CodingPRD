"""Investment commitment guards, the diversification cap boundary, disbursement
preconditions and side effects, OCC, and derived-field reconciliation.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_funding_loan, create_investor, file_prospectus,
    commit_investment, fund_loan_fully, disburse_loan, get_loan, get_loan_version,
    create_application,
    make_investor_headers,
    ADMIN, BIG_DEPOSIT_CENTS,
)


# =====================================================================
# Rule 6b — boundary precision: diversification cap exact equality allowed
# =====================================================================

def test_diversification_cap_exact_equality_allowed(api):
    """PRD §3.4: "the investor's total exposure to this single loan — the sum of
    this investor's `COMMITTED` `amount_cents` on this loan including the commitment
    now being made — may not exceed `max_single_loan_pct` multiplied by
    `capital_base_cents`, and a breach is rejected with `ERR_DIVERSIFICATION_BREACH`."

    Design: Difficulty/boundary_precision_check/diversification_cap_exact_equality_allowed_inclusive
    """
    borrower, app, loan = create_funding_loan()  # principal 1,200,000, FUNDING
    inv = create_investor(deposit_cents=1_600_000, max_single_loan_pct=0.25)
    # exposure 400000 == 0.25 * 1,600,000 -> exactly the cap, allowed (<=).
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 400_000,
         "expected_loan_version": v},
        make_investor_headers(inv["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "COMMITTED"
    assert data["amount_cents"] == 400_000


def test_diversification_cap_one_cent_over_breaches(api):
    """PRD §3.4: "may not exceed `max_single_loan_pct` multiplied by
    `capital_base_cents`, and a breach is rejected with `ERR_DIVERSIFICATION_BREACH`."

    Design: Difficulty/boundary_precision_check/diversification_cap_exact_equality_allowed_inclusive
    """
    borrower, app, loan = create_funding_loan()
    inv = create_investor(deposit_cents=1_600_000, max_single_loan_pct=0.25)
    # exposure 400001 > 0.25 * 1,600,000 == 400000 -> breach (X+1 boundary).
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 400_001,
         "expected_loan_version": v},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DIVERSIFICATION_BREACH.value, 422)


# =====================================================================
# Rule 5b — priority pair: over-subscribe (priority 10) vs diversification (priority 12)
# =====================================================================

def test_funding_exceeded_wins_over_diversification(api):
    """PRD §3.4: "Third, the commitment may not over-subscribe the loan — the loan's
    `committed_cents` after adding this `amount_cents` may not exceed the loan's
    `principal_cents` — and a breach is rejected with `ERR_FUNDING_EXCEEDED`."
    PRD §3.4: "Fifth, the diversification cap is enforced ... a breach is rejected
    with `ERR_DIVERSIFICATION_BREACH`."

    Design: Difficulty/priority_pair_validation_conflict/investment_funding_constraint_vs_diversification_fiscal_pair
    """
    borrower, app, loan = create_funding_loan()  # principal 1,200,000
    invz = create_investor(deposit_cents=BIG_DEPOSIT_CENTS, max_single_loan_pct=1)
    # Z funds 1,000,000 of 1,200,000 first.
    commit_investment(loan["id"], invz, 1_000_000, expected_loan_version=get_loan_version(loan["id"]))
    invw = create_investor(deposit_cents=1_000_000, max_single_loan_pct=0.25)
    # W commits 300000: over-funds (1,000,000+300,000 > 1,200,000 -> FUNDING_EXCEEDED at
    # priority 10) AND breaches cap (300000 > 0.25*1,000,000 == 250000, priority 12).
    # Uncommitted capital 1,000,000 >= 300000, so insufficient-capital does not fire.
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": invw["id"], "loan_id": loan["id"], "amount_cents": 300_000,
         "expected_loan_version": v},
        make_investor_headers(invw["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FUNDING_EXCEEDED.value, 422)


def test_diversification_breach_when_not_oversubscribing(api):
    """PRD §3.4: "Fifth, the diversification cap is enforced: the investor's total
    exposure to this single loan ... may not exceed `max_single_loan_pct` multiplied
    by `capital_base_cents`, and a breach is rejected with
    `ERR_DIVERSIFICATION_BREACH`."

    Design: Difficulty/priority_pair_validation_conflict/investment_funding_constraint_vs_diversification_fiscal_pair
    """
    # Loan principal 2,000,000: a 300000 commit does NOT over-subscribe (priority 10
    # passes) and uncommitted capital 1,000,000 covers it (priority 11 passes), so the
    # diversification cap (priority 12) is the only guard that can fire:
    # 300000 > 0.25 * 1,000,000 == 250000.
    borrower, app, loan = create_funding_loan(requested_principal_cents=2_000_000)
    inv = create_investor(deposit_cents=1_000_000, max_single_loan_pct=0.25)
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 300_000,
         "expected_loan_version": v},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DIVERSIFICATION_BREACH.value, 422)


# =====================================================================
# Rule 7a — cross-entity state dependency: disburse requires filed prospectus
# =====================================================================

def test_disburse_without_prospectus_rejected(api):
    """PRD §3.5: "a `ComplianceDisclosure` of type `SERIES_NOTE_PROSPECTUS` in
    `FILED` status must exist for this loan; if no such disclosure exists,
    disbursement is rejected with `ERR_DISCLOSURE_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/disburse_requires_filed_prospectus_disclosure_loan_to_disclosure
    """
    borrower, app, loan = create_funding_loan()  # principal 1,200,000, no disclosure
    inv = create_investor()
    # Fully fund WITHOUT filing a prospectus.
    fund_loan_fully(loan, [(inv, 1_200_000)])
    resp = api.disburse_loan(loan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_MISSING.value, 422)
    after = get_loan(loan["id"])
    assert after["status"] == "FUNDING", "loan must stay FUNDING after a failed disburse"


def test_disburse_with_filed_prospectus_succeeds(api):
    """PRD §3.5: "a `ComplianceDisclosure` of type `SERIES_NOTE_PROSPECTUS` in
    `FILED` status must exist for this loan"
    PRD §3.5: "The loan is then auto-transitioned to `REPAYMENT` within the same
    request"

    Design: Difficulty/cross_entity_state_dependency/disburse_requires_filed_prospectus_disclosure_loan_to_disclosure
    """
    from test_helpers import set_clock
    set_clock("2026-06-01T00:00:00.000Z")
    borrower, app, loan = create_funding_loan()
    file_prospectus(loan["id"])  # the cross-entity dependency is now satisfied
    inv = create_investor()
    fund_loan_fully(loan, [(inv, 1_200_000)])
    resp = api.disburse_loan(loan["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "REPAYMENT", "a filed prospectus permits disbursement"


# =====================================================================
# Rule 7b — cross-entity state dependency: investment requires borrower ACTIVE
# =====================================================================

def test_investment_on_suspended_borrower_loan_rejected(api):
    """PRD §3.4: "First, the loan must be in `FUNDING` status and both the
    committing investor and the loan's borrower must be `ACTIVE`; otherwise the
    commit is rejected with `ERR_LOAN_NOT_FUNDING`."

    Design: Difficulty/cross_entity_state_dependency/investment_requires_borrower_active_investment_to_borrower
    """
    borrower, app, loan = create_funding_loan()
    # Suspend the borrower (PlatformAdmin operation).
    validate_success(api.suspend_borrower(borrower["id"], ADMIN), 200)
    inv = create_investor()
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 400_000,
         "expected_loan_version": v},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FUNDING.value, 409)


def test_investment_by_suspended_investor_rejected(api):
    """PRD §3.4: "First, the loan must be in `FUNDING` status and both the
    committing investor and the loan's borrower must be `ACTIVE`; otherwise the
    commit is rejected with `ERR_LOAN_NOT_FUNDING`."

    Design: Difficulty/cross_entity_state_dependency/investment_requires_borrower_active_investment_to_borrower
    """
    borrower, app, loan = create_funding_loan()
    inv = create_investor()
    # Suspend the investor (PlatformAdmin operation, blocks new commitments).
    validate_success(api.suspend_investor(inv["id"], ADMIN), 200)
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 400_000,
         "expected_loan_version": v},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FUNDING.value, 409)


# =====================================================================
# Corner — state_machines: initial state, side effects, underfunded disburse
# =====================================================================

def test_new_loan_initial_state_funding(api):
    """PRD §3.3: "The new loan begins in `FUNDING` status with
    `outstanding_principal_cents` at 0, `current_period_index` at 0,
    `committed_cents` at 0"

    Design: Corner/state_machines/new_loan_starts_in_funding_initial_state
    """
    borrower, app, loan = create_funding_loan()
    assert loan["status"] == "FUNDING"
    assert loan["committed_cents"] == 0
    assert loan["outstanding_principal_cents"] == 0
    assert loan["apr"] == 0.0599


def test_disburse_underfunded_loan_invalid_state(api):
    """PRD §3.5: "The loan must be exactly fully funded — its `committed_cents` must
    equal its `principal_cents`, neither under nor over."
    PRD §3.5: "Attempting to disburse a loan that is not in `FUNDING` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/disburse_underfunded_loan_returns_invalid_state
    """
    borrower, app, loan = create_funding_loan()  # principal 1,200,000
    file_prospectus(loan["id"])
    inv = create_investor()
    fund_loan_fully(loan, [(inv, 400_000)])  # only 400000 of 1,200,000
    resp = api.disburse_loan(loan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert get_loan(loan["id"])["status"] == "FUNDING"


def test_disburse_sets_investment_outstanding_and_repayment_state(api):
    """PRD §3.5: "On disbursement, the platform sets the loan's
    `outstanding_principal_cents` equal to its `principal_cents`, sets
    `current_period_index` to 1"
    PRD §3.5: "For every `COMMITTED` investment on the loan, the investment's
    `outstanding_principal_cents` is set to its `amount_cents`"
    PRD §3.5: "The loan is then auto-transitioned to `REPAYMENT` within the same
    request"

    Design: Corner/state_machines/disburse_bubble_up_sets_investment_outstanding_and_repayment_state
    """
    from test_helpers import set_clock
    set_clock("2026-06-01T00:00:00.000Z")
    borrower, app, loan = create_funding_loan()
    file_prospectus(loan["id"])
    inv = create_investor()
    investments = fund_loan_fully(loan, [(inv, 1_200_000)])
    resp = api.disburse_loan(loan["id"], ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "REPAYMENT"
    assert data["current_period_index"] == 1
    assert data["outstanding_principal_cents"] == 1_200_000
    inv_after = validate_success(api.get_investment(investments[0]["id"], ADMIN), 200)
    assert inv_after["outstanding_principal_cents"] == 1_200_000


def test_charge_off_from_repayment_without_default_invalid_state(api):
    """PRD §3.7: "an attempt to charge off a loan in any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/charge_off_from_repayment_without_default_returns_invalid_state
    """
    from test_helpers import setup_single_investor_repayment_loan
    ctx = setup_single_investor_repayment_loan()
    resp = api.charge_off_loan(ctx["loan"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# =====================================================================
# Corner — validations / errors: capital and OCC guards
# =====================================================================

def test_insufficient_capital_blocks_oversized_investment(api):
    """PRD §3.4: "Fourth, the commitment may not exceed the investor's uncommitted
    capital (its `capital_base_cents` minus its `committed_capital_cents`), failing
    otherwise with `ERR_INSUFFICIENT_CAPITAL`."

    Design: Corner/validations/insufficient_capital_blocks_oversized_investment
    """
    borrower, app, loan = create_funding_loan()
    inv = create_investor(deposit_cents=300_000, max_single_loan_pct=1)
    v = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 400_000,
         "expected_loan_version": v},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CAPITAL.value, 422)


def test_stale_loan_version_on_investment_rejected(api):
    """PRD §2.6: "If another writer has advanced the loan's `version` since the
    investor read it ... the commit is rejected with `ERR_STALE_LOAN_VERSION`
    (HTTP 412)."

    Design: Corner/errors/stale_loan_version_on_investment_returns_412
    """
    borrower, app, loan = create_funding_loan()
    inv1 = create_investor()
    inv2 = create_investor()
    v0 = get_loan_version(loan["id"])
    # First commit bumps loan.version, making v0 stale for the second commit.
    commit_investment(loan["id"], inv1, 400_000, expected_loan_version=v0)
    resp = api.create_investment(
        {"investor_id": inv2["id"], "loan_id": loan["id"], "amount_cents": 400_000,
         "expected_loan_version": v0},
        make_investor_headers(inv2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOAN_VERSION.value, 412)


def test_occ_correct_version_succeeds_and_increments(api):
    """PRD §3.4: "the loan's `committed_cents` is raised by `amount_cents`, the
    investor's `committed_capital_cents` is raised by the same `amount_cents`, and
    the loan's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    borrower, app, loan = create_funding_loan()
    inv = create_investor()
    v0 = get_loan_version(loan["id"])
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": loan["id"], "amount_cents": 400_000,
         "expected_loan_version": v0},
        make_investor_headers(inv["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "COMMITTED"
    after = get_loan(loan["id"])
    assert after["version"] == v0 + 1, f"loan version must increment by 1, got {after['version']}"
    assert after["committed_cents"] == 400_000


def test_committed_cents_reconciled_across_two_investments(api):
    """PRD §2.8: "A loan's `committed_cents` is the running sum of the `amount_cents`
    of every `COMMITTED` investment on that loan and is reconciled on every
    investment commit."

    Design: Corner/cross_cutting_complexity_layers/derived_committed_cents_reconciled_across_two_investments
    """
    borrower, app, loan = create_funding_loan()
    i1 = create_investor()
    i2 = create_investor()
    fund_loan_fully(loan, [(i1, 800_000), (i2, 400_000)])
    after = get_loan(loan["id"])
    assert after["committed_cents"] == 1_200_000
    inv1 = validate_success(api.get_investor(i1["id"], ADMIN), 200)
    inv2 = validate_success(api.get_investor(i2["id"], ADMIN), 200)
    assert inv1["committed_capital_cents"] == 800_000
    assert inv2["committed_capital_cents"] == 400_000


def test_investor_default_diversification_cap_applied(api):
    """PRD §3.4: "it must be greater than 0 and at most 1; when omitted at
    registration it defaults to `0.25`."
    PRD §3.4: "A new investor starts in `ACTIVE` status with both
    `capital_base_cents` and `committed_capital_cents` at 0"

    Design: Corner/entities/investor_max_single_loan_pct_default_applied_when_omitted
    """
    resp = api.create_investor({"display_name": "Default Inv"}, ADMIN)
    data = validate_success(resp, 201)
    assert data["max_single_loan_pct"] == 0.25
    assert data["capital_base_cents"] == 0
    assert data["committed_capital_cents"] == 0
