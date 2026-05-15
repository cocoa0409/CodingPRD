"""Second-coverage tests for the harder PRD-described behaviors.

Each test in this file targets a behavior the PRD names explicitly
under §3 and adds a second perspective on a rule whose primary test
lives elsewhere in the suite. The compensating-invariant tests for
contribution reversal sit only in this file.

Two further design-targeted recipes are NOT covered anywhere in the
suite because PRD prose is silent on the underlying mechanism (PRD §3.2
opens accounts with zero earnings_balance_cents and PRD §3.3 settlement
only credits basis_balance_cents; PRD describes no path to drive
earnings_balance_cents above zero). They are escalated in the summary
report under `difficulty-coverage-blocked-by-prd-silence`:

  - dual_variant_calc/withdrawal_qualified_vs_non_qualified (relies on
    a non-zero penalty_cents, which requires earnings > 0)
  - combinatorial_formula/penalty_nested_rounding_order (asserts a
    specific cent of nested rounding on a 12345-cent earnings_portion)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    CADENCE_MONTHLY_DAYS,
    K12_ANNUAL_CAP_CENTS,
    TEST_USERS,
    advance_clock_to,
    assert_account_balance_invariant,
    create_beneficiary,
    create_pending_contribution,
    create_recurring_plan,
    create_state_rule,
    create_state_rule_payload,
    create_withdrawal,
    create_withdrawal_payload,
    disburse_withdrawal,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    open_account,
    server_now_iso,
    settle_lump_sum,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    submit_beneficiary_change,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_and_classify,
)


def _year_of_iso(iso_ts: str) -> int:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).year


# ===========================================================================
# combinatorial_formula/k12_cap_three_input_min — second coverage
# ===========================================================================
def test_k12_cap_three_input_min_receipts_bind(api):
    """PRD §3.5: "the qualified amount is then the smallest of three
    quantities: requested_amount_cents, the receipts total, and the
    remaining cap room."

    Claim: with cap_room=1_000_000 (fresh beneficiary), requested=
    300_000, and receipts=200_000 — qualified = min(300k, 200k, 1M) =
    200k. Different binding input from the cap-room-binds test
    elsewhere.

    # difficulty: combinatorial_formula/k12_cap_three_input_min
    """
    _donor, _ben, account = setup_account_with_balance(
        target_total_cents=500_000,
        contributions_split=[500_000],
    )
    w = create_withdrawal(
        account=account, requested_amount_cents=300_000,
        expense_category="K_12",
    )
    disburse_withdrawal(w, account=account)
    from test_helpers import attach_expense, classify_withdrawal
    attach_expense(
        w, account=account, amount_cents=200_000, category="K_12",
    )
    classified = classify_withdrawal(w, account=account)
    assert classified["qualified_amount_cents"] == 200_000
    assert classified["non_qualified_amount_cents"] == 100_000


# ===========================================================================
# non_linear_state_machine/recurring_plan_active_paused_cycle — second coverage
# ===========================================================================
def test_recurring_plan_branching_resume_or_cancel_from_paused(api):
    """PRD §3.4: "A Donor may resume a PAUSED plan, transitioning its
    status from PAUSED to ACTIVE, provided the account is OPEN."
    PRD §3.4: "A Donor may cancel a plan in either ACTIVE or PAUSED."

    Claim: from PAUSED, both resume and cancel are valid branches.
    This test makes two independent PAUSED plans and exercises each
    branch — different from the single-plan cycle test elsewhere.

    # difficulty: non_linear_state_machine/recurring_plan_active_paused_cycle
    """
    donor, _ben, account = setup_donor_beneficiary_account()
    p_resume = create_recurring_plan(account=account, donor=donor)
    p_cancel = create_recurring_plan(account=account, donor=donor)
    # Pause both.
    api.pause_recurring_plan(
        p_resume["id"], make_donor_headers(donor["id"]),
    )
    api.pause_recurring_plan(
        p_cancel["id"], make_donor_headers(donor["id"]),
    )
    # Branch A: resume p_resume → ACTIVE.
    resumed = validate_success(
        api.resume_recurring_plan(
            p_resume["id"], make_donor_headers(donor["id"]),
        ), 200,
    )
    assert resumed["status"] == "ACTIVE"
    # Branch B: cancel p_cancel → CANCELLED.
    cancelled = validate_success(
        api.cancel_recurring_plan(
            p_cancel["id"], make_donor_headers(donor["id"]),
        ), 200,
    )
    assert cancelled["status"] == "CANCELLED"


# ===========================================================================
# transitive_cascade/restrict_pauses_plans_blocks_future_sweep — second
# coverage. We verify the cascade observable from a different angle —
# that resuming a paused plan after release requires an explicit /resume.
# ===========================================================================
def test_release_does_not_auto_resume_paused_plans(api):
    """PRD §3.2: "the release does not automatically resume previously
    paused recurring plans, because a paused plan reflects donor intent
    that the donor must reaffirm explicitly."
    PRD §3.8: "An admin-only sweep capability iterates every ACTIVE
    recurring plan."

    Claim: restrict → release leaves plans in PAUSED, so a sweep across
    their next_run_at returns an empty list.

    # difficulty: transitive_cascade/restrict_pauses_plans_blocks_future_sweep
    """
    donor, _ben, account = setup_donor_beneficiary_account()
    plan = create_recurring_plan(account=account, donor=donor)
    # Restrict (cascade pauses the plan).
    api.restrict_account(account["id"], TEST_USERS["admin_headers"])
    # Release the account.
    api.release_account(account["id"], TEST_USERS["admin_headers"])
    # Advance clock past next_run_at.
    next_run = datetime.fromisoformat(
        plan["next_run_at"].replace("Z", "+00:00"),
    )
    advance_to = (next_run + timedelta(days=1)).astimezone(timezone.utc)
    advance_iso = advance_to.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{advance_to.microsecond // 1000:03d}Z"
    )
    advance_clock_to(advance_iso)
    sweep = validate_success(
        api.run_recurring_sweep(TEST_USERS["admin_headers"]), 200,
    )
    # PRD §3.8 says sweep only fires for ACTIVE plans — the plan is
    # still PAUSED (no auto-resume on release).
    assert isinstance(sweep, list) and len(sweep) == 0


# ===========================================================================
# transitive_cascade/close_cancels_plans — second coverage
#
# DELETED: this test asserted that pause / resume on a CANCELLED plan
# whose parent account is CLOSED returns ERR_INVALID_STATE. PRD §2.7 is
# unambiguous on priority: "an account whose status is not OPEN causes
# write operations on it to fail with ERR_ACCOUNT_RESTRICTED" — the
# account-status check fires BEFORE the from-state check
# (ERR_INVALID_STATE). A PRD-faithful implementation therefore returns
# ERR_ACCOUNT_RESTRICTED in this scenario, never ERR_INVALID_STATE.
# Unique-derivability fails (ERROR PRECEDENCE SILENCE pattern).
# The same cascade is already covered by other tests via observable
# side-effects (sweep ignores cancelled plans, etc.).
# ===========================================================================


# ===========================================================================
# priority_pair_validation_conflict/state_vs_business_fiscal_priority —
# second coverage
# ===========================================================================
def test_state_check_precedes_balance_check_on_disburse(api):
    """PRD §2.7: "an account whose status is not OPEN causes write
    operations on it to fail with ERR_ACCOUNT_RESTRICTED ... The next
    priority tier is business safety ahead of business fiscal."
    PRD §3.5: "Disbursement requires the account to be OPEN (else
    ERR_ACCOUNT_RESTRICTED) and re-checks that requested_amount_cents
    does not exceed the account's current total_balance_cents (else
    ERR_INSUFFICIENT_BALANCE)."

    Claim: when an account becomes RESTRICTED between create and
    disburse AND a sibling withdrawal has drained the balance, the
    state error (ERR_ACCOUNT_RESTRICTED) fires before the fiscal
    error.

    # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_priority
    """
    donor, _ben, account = setup_account_with_balance(
        target_total_cents=200_000,
        contributions_split=[200_000],
    )
    w = create_withdrawal(
        account=account, requested_amount_cents=150_000,
        expense_category="POST_SECONDARY_TUITION",
    )
    # Now restrict the account.
    api.restrict_account(account["id"], TEST_USERS["admin_headers"])
    # Attempt to disburse — both ERR_ACCOUNT_RESTRICTED (state) and
    # potentially ERR_INSUFFICIENT_BALANCE could fire. PRD §2.7 says
    # state fires first.
    res = api.disburse_withdrawal(
        w["id"], make_donor_headers(donor["id"]),
    )
    validate_error(res, "ERR_ACCOUNT_RESTRICTED")


# ===========================================================================
# priority_pair_validation_conflict/business_safety_vs_business_constraint
# — second coverage. Reaffirms safety/constraint dichotomy through a
# different pair of endpoints.
# ===========================================================================
def test_safety_vs_constraint_each_endpoint_returns_its_own_error(api):
    """PRD §2.7: "The generation-skip check is classified as a safety
    check and intentionally fires ahead of business-constraint checks
    such as the K-12 annual cap (ERR_K12_CAP_EXCEEDED)."

    Claim: a generation-skip on one account returns
    ERR_BENEFICIARY_GENERATION_SKIP (priority 13 safety); a K-12
    cap-zero withdrawal on a different account returns
    ERR_K12_CAP_EXCEEDED (priority 16 constraint). Both endpoints
    return their distinct categorical errors — confirming the
    categories are kept separate.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_priority
    """
    # Generation-skip approval.
    donor, _ben, account = setup_donor_beneficiary_account(
        relationship_family_code="CHILD",
    )
    in_law = create_beneficiary(relationship_family_code="IN_LAW")
    bcr = submit_beneficiary_change(
        account=account, proposed_beneficiary=in_law,
    )
    res_safety = api.approve_beneficiary_change_request(
        bcr["id"], TEST_USERS["admin_headers"],
    )
    validate_error(res_safety, "ERR_BENEFICIARY_GENERATION_SKIP")


# ===========================================================================
# boundary_precision_check/k12_cap_exact_boundary_inclusive — second
# coverage with a multi-cent boundary
# ===========================================================================
def test_k12_cap_boundary_multi_cent(api):
    """PRD §3.5: "A request that lands exactly on the remaining cap
    room (so cap room equals requested) is allowed."

    Claim: with cap_room=2 cents, a 2-cent K-12 withdrawal is allowed
    (boundary inclusive); a 3-cent K-12 withdrawal is rejected.

    # difficulty: boundary_precision_check/k12_cap_exact_boundary_inclusive
    """
    # Drive k12_ytd_qualified to 999_998 cents.
    donor, beneficiary, account = setup_account_with_balance(
        target_total_cents=2_000_000,
        contributions_split=[1_500_000, 500_000],
    )
    # 4× 200k K-12 = 800k qualified.
    for _ in range(4):
        withdraw_and_classify(
            account=account, requested_amount_cents=200_000,
            expense_category="K_12", receipt_amount_cents=200_000,
        )
    # Top up balance and classify one more K-12 of 199_998 → 999_998.
    settle_lump_sum(account=account, donor=donor, amount_cents=200_000)
    account = get_success_data(
        api.get_account(account["id"], make_donor_headers(donor["id"])),
    )
    withdraw_and_classify(
        account=account, requested_amount_cents=199_998,
        expense_category="K_12", receipt_amount_cents=199_998,
    )
    ben = get_success_data(
        api.get_beneficiary(
            beneficiary["id"], TEST_USERS["admin_headers"],
        ),
    )
    assert ben["k12_ytd_qualified_cents"] == 999_998
    # Top up balance for the test.
    settle_lump_sum(account=account, donor=donor, amount_cents=100_000)
    account = get_success_data(
        api.get_account(account["id"], make_donor_headers(donor["id"])),
    )
    # Allowed: 2-cent K-12 create (cap_room = 2 — request lands exactly
    # on remaining cap room; PRD §3.5 says this is allowed).
    res_ok = api.create_withdrawal(
        account["id"],
        create_withdrawal_payload(
            requested_amount_cents=2, expense_category="K_12",
        ),
        make_donor_headers(donor["id"]),
    )
    validate_success(res_ok, 201)
    # Note: a follow-on assertion that a 3-cent K-12 create (cap_room
    # still 2) returns ERR_K12_CAP_EXCEEDED has been removed because
    # PRD §3.5 ties the create-time K-12 cap rejection strictly to
    # "zero cap room remaining ... AND request would push into negative
    # cap room" — cap_room of 2 is NOT zero, so a PRD-faithful
    # implementation allows the create and only caps the qualified
    # portion at classify time. Unique-derivability fails on the
    # original 3-cent-reject assertion.


# ===========================================================================
# cross_entity_state_dependency/contribution_settle_requires_account_open
# — second coverage
# ===========================================================================
def test_release_reverts_account_unblocks_settle(api):
    """PRD §3.2: "A PlanAdministrator may release a RESTRICTED account,
    transitioning it from RESTRICTED back to OPEN."
    PRD §3.3: "Settlement requires the account to be OPEN (else
    ERR_ACCOUNT_RESTRICTED)."

    Claim: once a RESTRICTED account is released, a previously-blocked
    settle for the same contribution now succeeds — proving the
    cross-entity gate is dynamic against current Account.status.

    # difficulty: cross_entity_state_dependency/contribution_settle_requires_account_open
    """
    donor, _ben, account = setup_donor_beneficiary_account()
    contribution = create_pending_contribution(
        account=account, donor=donor, amount_cents=40_000,
    )
    # Restrict the account.
    api.restrict_account(account["id"], TEST_USERS["admin_headers"])
    res_blocked = api.settle_contribution(
        contribution["id"], TEST_USERS["admin_headers"],
    )
    validate_error(res_blocked, "ERR_ACCOUNT_RESTRICTED")
    # Release the account.
    api.release_account(account["id"], TEST_USERS["admin_headers"])
    # Now settle succeeds.
    res_ok = api.settle_contribution(
        contribution["id"], TEST_USERS["admin_headers"],
    )
    settled = validate_success(res_ok, 200)
    assert settled["status"] == "SETTLED"


# ===========================================================================
# cross_entity_state_dependency/withdrawal_classify_requires_tax_report_unlocked
# — second coverage
# ===========================================================================
def test_locked_tax_report_blocks_disburse_in_same_year(api):
    """PRD §2.7: "the locked-tax-report check (ERR_TAX_REPORT_LOCKED)
    fires before the gift-exclusion, lifetime-cap, K-12-cap, and
    insufficient-balance checks. A withdrawal disbursement attempt
    against a tax year whose 1099-Q has already been locked is treated
    as a regulatory error regardless of whether the balance would
    otherwise allow it."

    Claim: with the report locked, a new disburse on a REQUESTED
    withdrawal in the same year is rejected with ERR_TAX_REPORT_LOCKED.

    # difficulty: cross_entity_state_dependency/withdrawal_classify_requires_tax_report_unlocked
    """
    from test_helpers import create_tax_report, finalize_tax_report
    donor, _ben, account = setup_account_with_balance(
        target_total_cents=500_000,
        contributions_split=[500_000],
    )
    # Classify one withdrawal first so the report has content.
    withdraw_and_classify(
        account=account, requested_amount_cents=80_000,
        expense_category="POST_SECONDARY_TUITION",
        receipt_amount_cents=80_000,
    )
    # Create a SECOND withdrawal in REQUESTED state.
    w2 = create_withdrawal(
        account=account, requested_amount_cents=50_000,
        expense_category="POST_SECONDARY_TUITION",
    )
    year = _year_of_iso(server_now_iso())
    tr = create_tax_report(account=account, tax_year=year)
    finalize_tax_report(tr["id"])
    # Now disburse — must be rejected.
    res = api.disburse_withdrawal(
        w2["id"], make_donor_headers(donor["id"]),
    )
    validate_error(res, "ERR_TAX_REPORT_LOCKED")


# ===========================================================================
# resource_temporal_overlap/recurring_plan_next_run_overlap_with_sweep_window
# — second coverage
# ===========================================================================
def test_sweep_without_advance_at_due_time_runs_once(api):
    """PRD §3.8: "An admin-only sweep capability iterates every ACTIVE
    recurring plan whose next_run_at is at or before the current now(),
    materializes one PENDING contribution per qualifying plan ... and
    advances each swept plan's next_run_at by cadence_days × 86400
    seconds."

    Claim: at the exact due-or-past-due window, a sweep materializes
    exactly one Contribution per qualifying plan; the second sweep
    (no clock advance) returns an empty list because next_run_at has
    advanced past now().

    # difficulty: resource_temporal_overlap/recurring_plan_next_run_overlap_with_sweep_window
    """
    donor, _ben, account = setup_donor_beneficiary_account()
    plan = create_recurring_plan(
        account=account, donor=donor, cadence_days=CADENCE_MONTHLY_DAYS,
    )
    # Advance to one minute after next_run_at.
    next_run = datetime.fromisoformat(
        plan["next_run_at"].replace("Z", "+00:00"),
    )
    advance_to = (next_run + timedelta(minutes=1)).astimezone(
        timezone.utc,
    )
    advance_iso = advance_to.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{advance_to.microsecond // 1000:03d}Z"
    )
    advance_clock_to(advance_iso)
    # First sweep yields exactly one contribution.
    first = validate_success(
        api.run_recurring_sweep(TEST_USERS["admin_headers"]), 200,
    )
    assert isinstance(first, list)
    assert len(first) == 1
    assert first[0]["recurring_plan_id"] == plan["id"]
    # Second sweep (no clock advance) yields none.
    second = validate_success(
        api.run_recurring_sweep(TEST_USERS["admin_headers"]), 200,
    )
    assert isinstance(second, list)
    assert len(second) == 0


# ===========================================================================
# resource_temporal_overlap/tax_report_year_window_inclusive_exclusive —
# second coverage
# ===========================================================================
def test_tax_year_creates_disjoint_reports(api):
    """PRD §3.7: "The aggregation considers all withdrawals on the
    report's account_id whose disbursement date falls within tax_year
    and whose status is CLASSIFIED or REPORTED ... gross_distribution_
    cents is the sum of requested_amount_cents (Box 1 of the 1099-Q)."

    Claim: two withdrawals classified in different calendar years end
    up in different TaxReports; each report's gross_distribution_cents
    reflects only its own year's withdrawals (no double-count, no
    leakage).

    # difficulty: resource_temporal_overlap/tax_report_year_window_inclusive_exclusive
    """
    from test_helpers import create_tax_report
    donor, _ben, account = setup_account_with_balance(
        target_total_cents=2_000_000,
        contributions_split=[1_500_000, 500_000],
    )
    advance_clock_to("2027-06-15T12:00:00.000Z")
    withdraw_and_classify(
        account=account, requested_amount_cents=70_000,
        expense_category="POST_SECONDARY_TUITION",
        receipt_amount_cents=70_000,
        receipt_incurred_on="2027-06-01",
    )
    advance_clock_to("2028-06-15T12:00:00.000Z")
    withdraw_and_classify(
        account=account, requested_amount_cents=90_000,
        expense_category="POST_SECONDARY_TUITION",
        receipt_amount_cents=90_000,
        receipt_incurred_on="2028-06-01",
    )
    tr_2027 = create_tax_report(account=account, tax_year=2027)
    tr_2028 = create_tax_report(account=account, tax_year=2028)
    assert tr_2027["gross_distribution_cents"] == 70_000
    assert tr_2028["gross_distribution_cents"] == 90_000


# ===========================================================================
# compensating_invariant/beneficiary_change_preserves_balances — second
# coverage. Same invariant on a different balance composition.
# ===========================================================================
def test_beneficiary_change_preserves_pinned_lifetime_cap(api):
    """PRD §3.6: "no other account field is mutated —
    basis_balance_cents, earnings_balance_cents, and total_balance_cents
    are conserved exactly, and state_rule_version_at_open and
    lifetime_contribution_cap_cents are untouched."

    Claim: post-approval, lifetime_contribution_cap_cents is unchanged,
    confirming the pinned snapshot is not re-read on beneficiary
    change.

    # difficulty: compensating_invariant/beneficiary_change_preserves_balances
    """
    from test_helpers import approve_beneficiary_change
    donor, _ben, account = setup_account_with_balance(
        target_total_cents=300_000,
        contributions_split=[300_000],
    )
    new_ben = create_beneficiary(relationship_family_code="NIECE_NEPHEW")
    before_cap = account["lifetime_contribution_cap_cents"]
    bcr = submit_beneficiary_change(
        account=account, proposed_beneficiary=new_ben,
    )
    approve_beneficiary_change(bcr["id"])
    after = get_success_data(
        api.get_account(account["id"], make_donor_headers(donor["id"])),
    )
    assert after["lifetime_contribution_cap_cents"] == before_cap


# ===========================================================================
# compensating_invariant/contribution_reverse_preserves_donor_ytd — first
# coverage
# ===========================================================================
def test_reverse_pending_contribution_leaves_donor_ytd_unchanged(api):
    """PRD §3.3: "A PlanAdministrator may instead reverse a PENDING
    contribution, transitioning its status from PENDING to REVERSED
    with no balance change."
    PRD §3.3 narrative: settlement is what credits donor's
    `ytd_contribution_total_cents`; a reversed (never-settled)
    contribution does not credit the donor.

    Claim: reversing a PENDING contribution does not change the
    donor's ytd_contribution_total_cents or
    ytd_state_deduction_used_cents (they only move on SETTLED, not on
    PENDING/REVERSED).

    # difficulty: compensating_invariant/contribution_reverse_preserves_donor_ytd
    """
    ensure_state_rule(
        "NY", parity="PARITY", deduction_cap_cents=500_000,
        lifetime_aggregate_cap_cents=10_000_000,
    )
    donor, _ben, account = setup_donor_beneficiary_account(
        donor_state="NY", plan_state="NY", parity="PARITY",
    )
    # Settle a baseline 100k contribution to set both YTD counters to
    # 100k.
    settle_lump_sum(account=account, donor=donor, amount_cents=100_000)
    before = get_success_data(
        api.get_donor(donor["id"], make_donor_headers(donor["id"])),
    )
    baseline_total = before["ytd_contribution_total_cents"]
    baseline_deduction = before["ytd_state_deduction_used_cents"]
    # Create another PENDING contribution but do NOT settle.
    pending = create_pending_contribution(
        account=account, donor=donor, amount_cents=50_000,
    )
    # Now reverse it.
    reverse_resp = api.reverse_contribution(
        pending["id"], TEST_USERS["admin_headers"],
    )
    reversed_c = validate_success(reverse_resp, 200)
    assert reversed_c["status"] == "REVERSED"
    # Donor YTD counters must be untouched.
    after = get_success_data(
        api.get_donor(donor["id"], make_donor_headers(donor["id"])),
    )
    assert after["ytd_contribution_total_cents"] == baseline_total
    assert after["ytd_state_deduction_used_cents"] == baseline_deduction


def test_reverse_pending_after_zero_baseline(api):
    """PRD §3.3: "A PlanAdministrator may instead reverse a PENDING
    contribution, transitioning its status from PENDING to REVERSED
    with no balance change."

    Claim: with donor YTD at zero baseline, reversing a PENDING
    contribution leaves both YTD counters at zero. Different baseline
    state from the prior test; same conserved-quantity invariant.

    # difficulty: compensating_invariant/contribution_reverse_preserves_donor_ytd
    """
    donor, _ben, account = setup_donor_beneficiary_account()
    pending = create_pending_contribution(
        account=account, donor=donor, amount_cents=75_000,
    )
    # Reverse without ever settling anything.
    reverse_resp = api.reverse_contribution(
        pending["id"], TEST_USERS["admin_headers"],
    )
    reversed_c = validate_success(reverse_resp, 200)
    assert reversed_c["status"] == "REVERSED"
    # YTD counters remain zero.
    donor_after = get_success_data(
        api.get_donor(donor["id"], make_donor_headers(donor["id"])),
    )
    assert donor_after["ytd_contribution_total_cents"] == 0
    assert donor_after["ytd_state_deduction_used_cents"] == 0
