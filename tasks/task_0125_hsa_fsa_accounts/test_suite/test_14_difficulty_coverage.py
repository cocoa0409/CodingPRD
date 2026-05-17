"""Difficulty-design coverage — at least two tests per declared
instance per the test-targeting index.

Each test docstring carries a `# difficulty: <rule_id>/<instance>`
tag so coverage can be audited. Each test pins to a verbatim PRD
sentence stating the underlying rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    approve_claim,
    available_balance,
    create_claim,
    create_account_holder,
    create_contribution_payload,
    create_plan_year_payload,
    get_claim,
    get_plan_year,
    iso_datetime_utc,
    make_account_holder_headers,
    make_adjudicator_headers,
    open_account,
    open_plan_year,
    pay_claim,
    post_contribution,
    post_ops_run,
    reverse_claim,
    seed_qualified_expense,
    setup_active_plan_year,
    setup_carryover_chain_with_successor,
    setup_dcfsa_with_inactive_dependent_at_submit_time,
    setup_funded_plan_year,
    setup_health_fsa_carryover_full_chain,
    setup_health_fsa_grace_one_day_past,
    setup_health_fsa_grace_predecessor_with_successor,
    setup_holder_and_account,
    setup_hsa_non_qualified_for_chronological_tax_form,
    setup_hsa_self_only_at_cap_boundary,
    setup_paid_claim,
    setup_submitted_claim,
    setup_two_health_fsa_policy_variants,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_forfeiture_grace_period_full(self, api):
        """# difficulty: dual_variant_calc/forfeiture_grace_vs_carryover_health_fsa

        PRD §3.6: "with GRACE_PERIOD, by the time the
        GRACE_PERIOD_EXPIRY sweep runs (after March 15), service-date
        claims through March 15 have already been paid and the
        remaining leftover is fully forfeited".
        PRD §3.6: "The dual-variant nature of the year-end
        calculation matters: a Health FSA with $3,000 of
        contributions and $2,200 of paid claims under GRACE_PERIOD
        forfeits the full $800 leftover at March-15 expiry".

        Claim: HEALTH_FSA GRACE_PERIOD with $3,000 contributions and
        $2,200 paid -> after YEAR_END_CLOSE then GRACE_PERIOD_EXPIRY,
        Y2025.status == CLOSED and forfeited_cents == 80_000.
        """
        holder, a_grace, y_grace, a_carry, y_carry = (
            setup_two_health_fsa_policy_variants(
                calendar_year=2025,
                contribution_cents=300_000,
                paid_claim_cents=220_000,
            )
        )
        # Year-end close: grace -> GRACE_PERIOD; carryover ->
        # CARRYOVER_PENDING.
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        # Grace-period expiry: 2026-03-16.
        advance_clock_to(iso_datetime_utc(2026, 3, 16))
        post_ops_run(
            kind="GRACE_PERIOD_EXPIRY",
            as_of_date=iso_datetime_utc(2026, 3, 16),
        )
        y_grace_final = get_plan_year(a_grace["id"], y_grace["id"])
        assert y_grace_final["status"] == "CLOSED"
        assert y_grace_final["forfeited_cents"] == 80_000

    def test_forfeiture_carryover_partial(self, api):
        """# difficulty: dual_variant_calc/forfeiture_grace_vs_carryover_health_fsa

        PRD §3.6: "with CARRYOVER, the amount carried forward is the
        lesser of the leftover and the carryover ceiling of 64,000
        cents ($640.00), and only the leftover in excess of that
        ceiling is forfeited".
        PRD §3.6: "the same numbers under CARRYOVER carry $640
        forward to the successor plan year's carryover_in_cents and
        forfeit only $160".

        Claim: HEALTH_FSA CARRYOVER with $3,000 contributions and
        $2,200 paid -> after YEAR_END_CLOSE the predecessor enters
        CARRYOVER_PENDING; if no successor is opened, the
        predecessor's eventual forfeiture honors the $640 ceiling.
        Here we open a successor for 2026 and observe successor
        carryover_in == 64_000 and predecessor forfeited == 16_000.
        """
        holder, a_grace, y_grace, a_carry, y_carry = (
            setup_two_health_fsa_policy_variants(
                calendar_year=2025,
                contribution_cents=300_000,
                paid_claim_cents=220_000,
            )
        )
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        # Open successor PlanYear for 2026 on the CARRYOVER account.
        y_succ = open_plan_year(a_carry["id"], calendar_year=2026)
        y_carry_final = get_plan_year(a_carry["id"], y_carry["id"])
        succ_final = get_plan_year(a_carry["id"], y_succ["id"])
        assert y_carry_final["status"] == "CLOSED"
        assert y_carry_final["forfeited_cents"] == 16_000
        assert succ_final["carryover_in_cents"] == 64_000

    def test_chronological_replay_pins_basis(self, api, auditor_headers):
        """# difficulty: dual_variant_calc/tax_basis_chronological_vs_forward_looking_hsa

        PRD §3.8: "The chronological variant replays the audit events
        for the plan year in (occurred_at, id) order, maintaining a
        running deductible accumulator. ... tax_basis_cents is
        deductible_cents minus recapture_cents."

        Claim: chronological variant with PRD-pinned inputs produces
        a deductible_cents and recapture_cents distinct from the
        forward_looking variant (covered also in test_10; here we
        anchor to the difficulty-design instance).
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=200_000,
            contribution_two_cents=200_000,
        )
        resp = api.get_tax_form(
            acct["id"], py["id"], auditor_headers,
            params={"basis": "chronological"},
        )
        data = validate_success(resp, expected_status=200)
        # PRD §3.8: chronological replay over
        #   contribute 200_000 -> deductible 200_000
        #   pay non-qual 200_000 -> recapture 200_000, deductible 0
        #   contribute 200_000 -> deductible 200_000
        # Final: deductible_cents=200_000, recapture_cents=200_000.
        assert data["recapture_cents"] == 200_000
        assert data["deductible_cents"] == 200_000

    def test_forward_looking_diverges_from_chronological(
        self, api, auditor_headers,
    ):
        """# difficulty: dual_variant_calc/tax_basis_chronological_vs_forward_looking_hsa

        PRD §3.8: "The two variants can disagree. When contributions
        arrive after non-qualified claims have already been paid, the
        chronological variant clamps each contribution's deductibility
        event-by-event, so later contributions that would have crossed
        the cap mid-year are dropped from the deductible; the
        forward-looking variant simply caps the final year-to-date
        total."

        Claim: forward_looking yields a tax_basis_cents distinct from
        chronological under the same inputs.
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=200_000,
            contribution_two_cents=200_000,
        )
        chrono = validate_success(
            api.get_tax_form(
                acct["id"], py["id"], auditor_headers,
                params={"basis": "chronological"},
            ),
            expected_status=200,
        )
        fl = validate_success(
            api.get_tax_form(
                acct["id"], py["id"], auditor_headers,
                params={"basis": "forward_looking"},
            ),
            expected_status=200,
        )
        assert chrono["tax_basis_cents"] != fl["tax_basis_cents"]


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_hsa_self_only_young_cap(self, api, plan_admin_headers):
        """# difficulty: combinatorial_formula/plan_year_cap_three_input_nonlinear

        PRD §3.2: "For an HSA with self-only coverage,
        contribution_cap_cents is set to 412,500 cents ($4,125.00)."

        Claim: HSA SELF_ONLY young (under 55) -> cap 412_500,
        catch_up 0.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1980-06-01")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            account_holder_birth_date="1980-06-01",
        )
        resp = api.create_plan_year(
            acct["id"], create_plan_year_payload(calendar_year=2025),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 412_500
        assert data["catch_up_cap_cents"] == 0

    def test_hsa_family_with_catch_up_cap(self, api, plan_admin_headers):
        """# difficulty: combinatorial_formula/plan_year_cap_three_input_nonlinear

        PRD §3.2: "For an HSA with family coverage, it is 830,000
        cents ($8,300.00). The HSA catch-up cap catch_up_cap_cents is
        100,000 cents ($1,000.00) if, on December 31 of the plan
        year's calendar_year ... the account holder's age ... is at
        least 55".

        Claim: HSA FAMILY + age 56 at Dec 31 -> cap 830_000,
        catch_up 100_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(birth_date="1969-06-01")
        acct = open_account(
            holder, account_type="HSA", coverage_tier="FAMILY",
            year_end_policy="NONE",
            account_holder_birth_date="1969-06-01",
        )
        resp = api.create_plan_year(
            acct["id"], create_plan_year_payload(calendar_year=2025),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 830_000
        assert data["catch_up_cap_cents"] == 100_000

    def test_dcfsa_married_separate_cap(self, api, plan_admin_headers):
        """# difficulty: combinatorial_formula/plan_year_cap_three_input_nonlinear

        PRD §3.2: "For a Dependent Care FSA,
        contribution_cap_cents is set to 250,000 cents ($2,500.00)
        when the linked account holder's tax_filing_status is
        MARRIED_SEPARATE".

        Claim: DCFSA + MARRIED_SEPARATE -> cap 250_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(
            birth_date="1980-01-01",
            tax_filing_status="MARRIED_SEPARATE",
        )
        acct = open_account(
            holder, account_type="DEPENDENT_CARE_FSA", coverage_tier=None,
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], create_plan_year_payload(calendar_year=2025),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 250_000

    def test_dcfsa_single_full_cap(self, api, plan_admin_headers):
        """# difficulty: combinatorial_formula/plan_year_cap_three_input_nonlinear

        PRD §3.2: "and 500,000 cents ($5,000.00) for every other
        filing status."

        Claim: DCFSA + SINGLE -> cap 500_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder = create_account_holder(
            birth_date="1980-01-01", tax_filing_status="SINGLE",
        )
        acct = open_account(
            holder, account_type="DEPENDENT_CARE_FSA", coverage_tier=None,
            year_end_policy="NONE",
            account_holder_birth_date="1980-01-01",
        )
        resp = api.create_plan_year(
            acct["id"], create_plan_year_payload(calendar_year=2025),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["contribution_cap_cents"] == 500_000

    def test_grace_period_resolution_after_mar_15_picks_successor(self, api):
        """# difficulty: combinatorial_formula/plan_year_resolution_circular_year_routing

        PRD §3.5: "The tie-break: prefer plan year Y (use older money
        first) when Y is in GRACE_PERIOD and the service date is on
        or before March 15 of Y+1; otherwise fall back to plan year
        Y+1."

        Claim: a service_date of 2026-04-01 (after Mar 15 of Y+1)
        routes to Y+1 (the new plan year) — NOT to the
        GRACE_PERIOD-status prior plan year.
        """
        holder, acct, y_pred, y_succ, qe = (
            setup_health_fsa_grace_predecessor_with_successor(
                predecessor_year=2025, successor_year=2026,
                predecessor_contribution_cents=100_000,
                successor_contribution_cents=50_000,
            )
        )
        advance_clock_to(iso_datetime_utc(2026, 4, 5))
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2026, 4, 1),
            expense_code=qe["code"], amount_cents=30_000,
        )
        submit_claim(claim["id"], account_holder=holder)
        final = get_claim(claim["id"])
        assert final["plan_year_id"] == y_succ["id"], (
            f"expected successor plan_year_id={y_succ['id']}, got "
            f"{final['plan_year_id']}"
        )

    def test_grace_period_resolution_picks_prior_year(self, api):
        """# difficulty: combinatorial_formula/plan_year_resolution_circular_year_routing

        PRD §3.5: "A service date falling in the January 1–through–
        March 15 window of year Y+1 may be eligible both for the
        prior plan year Y (if Y is in GRACE_PERIOD status) and for
        the new plan year Y+1 (if it exists in ACTIVE). The
        tie-break: prefer plan year Y (use older money first) when Y
        is in GRACE_PERIOD and the service date is on or before
        March 15 of Y+1; otherwise fall back to plan year Y+1."

        Claim: Mar 10 of Y+1, with Y in GRACE_PERIOD and Y+1 ACTIVE,
        -> claim.plan_year_id == Y2025.id.
        """
        holder, acct, y_pred, y_succ, qe = (
            setup_health_fsa_grace_predecessor_with_successor(
                predecessor_year=2025, successor_year=2026,
                predecessor_contribution_cents=100_000,
                successor_contribution_cents=50_000,
            )
        )
        # Advance clock past 03-10 so the service date is not future.
        advance_clock_to(iso_datetime_utc(2026, 3, 10))
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2026, 3, 10),
            expense_code=qe["code"], amount_cents=30_000,
        )
        submit_claim(claim["id"], account_holder=holder)
        final = get_claim(claim["id"])
        assert final["plan_year_id"] == y_pred["id"], (
            f"expected prior-year plan_year_id={y_pred['id']}, got "
            f"{final['plan_year_id']}"
        )

    def test_chronological_round_then_clamp_pinned(self, api, auditor_headers):
        """# difficulty: combinatorial_formula/chronological_tax_basis_rounding_then_clamp_order

        PRD §3.8: "On each CLAIM_PAID event whose linked
        QualifiedExpense.category is NON_QUALIFIED, a penalty cents
        value is computed as the absolute value of the event's
        cents_delta multiplied by the HSA penalty rate of 2,000 basis
        points (i.e., 20.00%) divided by 10,000, rounded half-up to a
        whole cent".

        Claim: with HSA contributions=200_000 and a NON_QUALIFIED
        claim of 50_000, the chronological replay applies penalty
        first: penalty = round_half_up(50_000 * 0.20) = 10_000;
        gross = 50_000 + 10_000 = 60_000. accumulator before claim =
        200_000. applied = min(60_000, 200_000) = 60_000. recapture =
        60_000, accumulator after = 140_000. After all events:
        deductible_cents == 140_000, recapture_cents == 60_000.
        """
        holder, acct, py = setup_hsa_non_qualified_for_chronological_tax_form(
            calendar_year=2025,
            contribution_one_cents=200_000,
            non_qual_claim_cents=50_000,
            contribution_two_cents=0,
        )
        resp = api.get_tax_form(
            acct["id"], py["id"], auditor_headers,
            params={"basis": "chronological"},
        )
        data = validate_success(resp, expected_status=200)
        assert data["recapture_cents"] == 60_000, (
            f"recapture_cents expected 60_000, "
            f"got {data['recapture_cents']}"
        )
        assert data["deductible_cents"] == 140_000, (
            f"deductible_cents expected 140_000, "
            f"got {data['deductible_cents']}"
        )

    # NOTE: test_chronological_round_then_clamp was DELETED.
    # The scenario it asserted (HSA contribute 3_000 then pay
    # NON_QUALIFIED 33_300) is unreachable under a PRD-faithful
    # implementation: PRD §3.5 requires that a claim's amount_cents
    # be no greater than the plan year's available balance, otherwise
    # /pay returns ERR_INSUFFICIENT_BALANCE. With only 3_000 cents
    # contributed and an HSA cap of 412_500 cents (no clamp possible
    # at this scale), no PRD-compliant sequence can put the
    # chronological deductible accumulator at 3_000 while the balance
    # is also >= 33_300 at the moment of /pay. Unique derivability
    # fails (STEP 1b).


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_claim_paid_to_reversed_path(self, api):
        """# difficulty: non_linear_state_machine/claim_branching_with_reversal

        PRD §3.5: "Reversal of a PAID claim is the only path to undo
        a payment and is performed by a ClaimAdjudicator."
        PRD §3.5: "On success, the original Claim row is mutated in
        place: status becomes REVERSED."

        Claim: a PAID claim transitions to REVERSED on /reverse and
        the plan year's claims_paid_ytd_cents drops back to zero.
        """
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000, claim_cents=20_000,
        )
        reverse_claim(claim["id"])
        final = get_claim(claim["id"])
        assert final["status"] == "REVERSED"
        py_final = get_plan_year(acct["id"], py["id"])
        assert py_final["claims_paid_ytd_cents"] == 0

    def test_claim_submitted_to_denied_path(self, api):
        """# difficulty: non_linear_state_machine/claim_branching_with_reversal

        PRD §3.5: "Denial of a claim is permitted from either
        SUBMITTED or APPROVED status. ... Denial from SUBMITTED is
        subject to segregation-of-duties (same rule as approval;
        ERR_SEGREGATION_OF_DUTIES on a same-user violation). ... On
        success, Claim.status becomes DENIED, denial_reason is
        persisted".

        Claim: a SUBMITTED claim denied by a non-submitter adjudicator
        transitions to DENIED.
        """
        holder, acct, py, qe, claim = setup_submitted_claim()
        # Use a different adjudicator id than the holder (the
        # submitter actor on CLAIM_SUBMITTED).
        non_submitter = make_adjudicator_headers("non-submitter-1")
        resp = api.deny_claim(
            claim["id"], {"denial_reason": "test"}, non_submitter,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DENIED"
        assert data["denial_reason"] == "test"

    def test_plan_year_active_to_grace_period_branch(self, api):
        """# difficulty: non_linear_state_machine/plan_year_branching_close_paths

        PRD §3.6: "For a Health FSA or Dependent Care FSA whose
        year_end_policy is GRACE_PERIOD, the plan year transitions to
        GRACE_PERIOD status".

        Claim: HEALTH_FSA GRACE_PERIOD -> after YEAR_END_CLOSE the
        plan year status is GRACE_PERIOD.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="GRACE_PERIOD",
            birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "GRACE_PERIOD"

    def test_plan_year_active_to_carryover_pending_branch(self, api):
        """# difficulty: non_linear_state_machine/plan_year_branching_close_paths

        PRD §3.6: "For a Health FSA whose year_end_policy is
        CARRYOVER, the plan year transitions to CARRYOVER_PENDING."

        Claim: HEALTH_FSA CARRYOVER -> after YEAR_END_CLOSE the plan
        year status is CARRYOVER_PENDING.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="CARRYOVER", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "CARRYOVER_PENDING"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_year_end_close_then_successor_then_drawdown(self, api):
        """# difficulty: transitive_cascade/year_end_close_to_carryover_to_successor

        PRD §3.6: "If no successor exists yet, the carryover is held
        on the predecessor (which stays in CARRYOVER_PENDING) until a
        successor plan year is opened via the standard plan-year
        creation flow, at which point the carryover is moved into the
        new plan year's carryover_in_cents and the predecessor is
        immediately closed".

        Claim: closing the predecessor's CARRYOVER_PENDING is itself
        a downstream cascade of the earlier YEAR_END_CLOSE OpsRun.
        Verified by: predecessor.status == CLOSED, predecessor
        forfeited == leftover - applied_carryover, successor
        carryover_in == 64_000.
        """
        holder, acct, pred, succ = setup_carryover_chain_with_successor(
            predecessor_year=2025, successor_year=2026,
            contribution_cents=100_000, pay_claim_cents=20_000,
        )
        assert pred["status"] == "CLOSED"
        assert succ["carryover_in_cents"] == 64_000
        assert pred["forfeited_cents"] == 16_000

    def test_year_end_close_creates_carryover_pending(self, api):
        """# difficulty: transitive_cascade/year_end_close_to_carryover_to_successor

        PRD §3.6: "For a Health FSA whose year_end_policy is
        CARRYOVER, the plan year transitions to CARRYOVER_PENDING. A
        CARRYOVER_APPLIED audit event is appended".

        Claim: the OpsRun trigger first moves the predecessor to
        CARRYOVER_PENDING (the chain's step 1).
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="CARRYOVER", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        # Step 1: ACTIVE -> CARRYOVER_PENDING.
        assert py_after["status"] == "CARRYOVER_PENDING"

    def test_contribution_reverse_to_balance(self, api):
        """# difficulty: transitive_cascade/contribution_reversal_to_balance_to_audit_invariant

        PRD §3.3: "The plan year's contributions_ytd_cents decreases
        by the original amount".

        Claim: after reversing the sole contribution,
        PlanYear.contributions_ytd_cents == 0 (step 1 propagation).
        """
        _, acct, py = setup_active_plan_year()
        contrib = post_contribution(
            py["id"], amount_cents=50_000, source="PAYROLL",
        )
        from test_helpers import reverse_contribution
        reverse_contribution(contrib["id"])
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["contributions_ytd_cents"] == 0

    def test_contribution_reverse_audit_invariant_holds(self, api):
        """# difficulty: transitive_cascade/contribution_reversal_to_balance_to_audit_invariant

        PRD §2.8: "for every PlanYear, the sum of
        AuditEvent.cents_delta taken over all events whose
        subject_entity is CONTRIBUTION or CLAIM and whose plan_year_id
        equals that plan year must equal contributions_ytd_cents
        minus claims_paid_ytd_cents."

        Claim: after a POST + REVERSE pair, the audit ledger sum is
        0 and matches the plan year's counters (step 2 invariant).
        """
        from test_helpers import list_audit_events, reverse_contribution
        _, acct, py = setup_active_plan_year()
        contrib = post_contribution(
            py["id"], amount_cents=50_000, source="PAYROLL",
        )
        reverse_contribution(contrib["id"])
        events = list_audit_events(acct["id"], plan_year_id=py["id"])
        ledger_sum = sum(
            e["cents_delta"] for e in events
            if e.get("subject_entity") in {"CONTRIBUTION", "CLAIM"}
        )
        py_after = get_plan_year(acct["id"], py["id"])
        expected = (
            py_after["contributions_ytd_cents"]
            - py_after["claims_paid_ytd_cents"]
        )
        assert ledger_sum == expected == 0


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_beats_fiscal_on_pay_closed_plan_year(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pay_on_closed_with_insufficient

        PRD §2.10: "the resolved PlanYear must be in a claimable
        status ... (ERR_PLAN_YEAR_NOT_CLAIMABLE); ... next, fiscal
        balance checks (ERR_INSUFFICIENT_BALANCE, then
        ERR_REVERSAL_WOULD_OVERDRAW)".

        Claim: /pay against a CLOSED plan year with a claim amount
        exceeding available balance returns
        ERR_PLAN_YEAR_NOT_CLAIMABLE (state wins).
        """
        advance_clock_to(iso_datetime_utc(2025, 12, 1))
        holder, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="NONE", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=10_000, source="PAYROLL")
        qe = seed_qualified_expense(
            category="MEDICAL",
            eligible_account_types=["HEALTH_FSA"],
            requires_dependent=False,
        )
        c = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 6, 15),
            expense_code=qe["code"], amount_cents=50_000,
        )
        submit_claim(c["id"], account_holder=holder)
        approve_claim(c["id"])
        # YEAR_END_CLOSE -> py to CLOSED (HEALTH_FSA NONE).
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        resp = api.pay_claim(
            c["id"], make_adjudicator_headers("pri-pair-pay-1"),
        )
        validate_error(
            resp, ApiErrorId.ERR_PLAN_YEAR_NOT_CLAIMABLE.value,
        )

    def test_state_beats_fiscal_using_grace_then_close_path(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pay_on_closed_with_insufficient

        PRD §2.10: "Resolved PlanYear must be in a claimable status
        (ACTIVE, GRACE_PERIOD, or CARRYOVER_PENDING) for ... /pay;
        CLOSED PlanYears reject" with ERR_PLAN_YEAR_NOT_CLAIMABLE.

        Claim: a HEALTH_FSA GRACE_PERIOD plan year that is closed by
        GRACE_PERIOD_EXPIRY rejects subsequent /pay with
        ERR_PLAN_YEAR_NOT_CLAIMABLE, regardless of balance.
        """
        holder, acct, pred, qe = setup_health_fsa_grace_one_day_past(
            predecessor_year=2025, successor_year=2026,
            contribution_cents=100_000,
        )
        # Build an APPROVED claim then run GRACE_PERIOD_EXPIRY to
        # close the plan year, then /pay.
        c = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 12, 15),
            expense_code=qe["code"], amount_cents=200_000,
        )
        submit_claim(c["id"], account_holder=holder)
        approve_claim(c["id"])
        # Now close via GRACE_PERIOD_EXPIRY (after the fixture has
        # already advanced the clock to 3/20).
        advance_clock_to(iso_datetime_utc(2026, 3, 21))
        post_ops_run(
            kind="GRACE_PERIOD_EXPIRY",
            as_of_date=iso_datetime_utc(2026, 3, 21),
        )
        resp = api.pay_claim(
            c["id"], make_adjudicator_headers("pri-pair-grace-1"),
        )
        validate_error(
            resp, ApiErrorId.ERR_PLAN_YEAR_NOT_CLAIMABLE.value,
        )

    def test_sod_beats_dependent_inactive_on_approve(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_segregation_on_inactive_dep

        PRD §2.10: "next, segregation-of-duties for adjudication
        (ERR_SEGREGATION_OF_DUTIES); next, business-referential checks
        against QualifiedExpense (ERR_EXPENSE_NOT_ELIGIBLE), then
        dependent-required (ERR_DEPENDENT_REQUIRED), then
        dependent-active (ERR_DEPENDENT_INACTIVE)".

        Claim: when a /approve request simultaneously violates SoD
        (X-User-ID == submitter id) AND cites an inactive Dependent,
        the response is ERR_SEGREGATION_OF_DUTIES.
        """
        from test_helpers import create_dependent, deactivate_dependent
        holder, acct, py = setup_funded_plan_year(
            account_type="DEPENDENT_CARE_FSA",
            coverage_tier=None, year_end_policy="NONE",
            calendar_year=2025, contribution_cents=100_000,
        )
        dep = create_dependent(account_holder=holder)
        qe = seed_qualified_expense(
            category="DEPENDENT_CARE",
            eligible_account_types=["DEPENDENT_CARE_FSA"],
            requires_dependent=True,
        )
        c = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 6, 15),
            expense_code=qe["code"], amount_cents=10_000,
            dependent_id=dep["id"],
        )
        submit_claim(c["id"], account_holder=holder)
        deactivate_dependent(dep["id"])
        same_id_headers = make_adjudicator_headers(holder["id"])
        resp = api.approve_claim(c["id"], same_id_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_sod_alone_without_dep_inactive(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_segregation_on_inactive_dep

        PRD §2.9: "if they match, the operation is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: SoD violation on /approve fires
        ERR_SEGREGATION_OF_DUTIES even when no other rule is
        breached (single-rule baseline that pairs with the
        SoD-vs-dep-inactive case above).
        """
        holder, acct, py, qe, claim = setup_submitted_claim()
        same_id_headers = make_adjudicator_headers(holder["id"])
        resp = api.approve_claim(claim["id"], same_id_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_contribution_cap_exact_limit_succeeds(
        self, api, plan_admin_headers,
    ):
        """# difficulty: boundary_precision_check/contribution_cap_at_exact_limit_endpoint

        PRD §3.3: "the sum of the prior contributions_ytd_cents and
        the new amount_cents must be at most contribution_cap_cents
        plus catch_up_cap_cents."

        Claim: a single contribution equal to the cap exactly
        succeeds.
        """
        _, _, py = setup_hsa_self_only_at_cap_boundary(calendar_year=2025)
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(amount_cents=412_500),
            plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "POSTED"

    def test_contribution_cap_one_cent_above_rejected(
        self, api, plan_admin_headers,
    ):
        """# difficulty: boundary_precision_check/contribution_cap_at_exact_limit_endpoint

        PRD §3.3: "If posting would push the total above that
        combined ceiling, the contribution is rejected with
        ERR_CONTRIBUTION_CAP_EXCEEDED."

        Claim: contributing 1 cent more than the cap is rejected.
        """
        _, _, py = setup_hsa_self_only_at_cap_boundary(calendar_year=2025)
        post_contribution(py["id"], amount_cents=412_500, source="PAYROLL")
        resp = api.create_contribution(
            py["id"],
            create_contribution_payload(amount_cents=1),
            plan_admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value,
        )

    def test_grace_period_service_date_inclusive_march_15(self, api):
        """# difficulty: boundary_precision_check/grace_period_service_date_inclusive_boundary

        PRD §3.5: "for HEALTH_FSA or DEPENDENT_CARE_FSA whose
        year_end_policy is GRACE_PERIOD, the coverage window for
        routing is January 1 of the calendar_year through March 15 of
        calendar_year + 1, both endpoints inclusive."

        Claim: service_date = 2026-03-15 routes to prior year Y2025
        in GRACE_PERIOD (boundary inclusive).
        """
        holder, acct, pred, qe = setup_health_fsa_grace_one_day_past(
            predecessor_year=2025, successor_year=2026,
            contribution_cents=100_000,
        )
        c = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2026, 3, 15),
            expense_code=qe["code"], amount_cents=5_000,
        )
        submit_claim(c["id"], account_holder=holder)
        final = get_claim(c["id"])
        assert final["plan_year_id"] == pred["id"]
        assert final["status"] == "SUBMITTED"

    def test_grace_period_service_date_one_day_past_rejected(self, api):
        """# difficulty: boundary_precision_check/grace_period_service_date_inclusive_boundary

        PRD §3.5: "If no plan year matches, the submission is
        rejected with ERR_NO_ELIGIBLE_PLAN_YEAR."

        Claim: service_date = 2026-03-16 (one day past) with no
        Y+1 ACTIVE -> ERR_NO_ELIGIBLE_PLAN_YEAR.
        """
        from test_helpers import create_claim_payload
        holder, acct, pred, qe = setup_health_fsa_grace_one_day_past(
            predecessor_year=2025, successor_year=2026,
            contribution_cents=100_000,
        )
        payload = create_claim_payload(
            service_date=iso_datetime_utc(2026, 3, 16),
            expense_code=qe["code"], amount_cents=5_000,
        )
        # The PRD §3.5 says ERR_NO_ELIGIBLE_PLAN_YEAR applies at
        # /submit. PRD says the same expense/dependent checks run
        # at create time but does NOT pin the plan-year resolution
        # check at create. So create may succeed; the submit must
        # reject.
        create_resp = api.create_claim(
            acct["id"], payload,
            make_account_holder_headers(holder["id"]),
        )
        if create_resp.status_code >= 400:
            # Some implementations may also validate at create.
            # Either way the rule is the same:
            validate_error(
                create_resp, ApiErrorId.ERR_NO_ELIGIBLE_PLAN_YEAR.value,
            )
            return
        draft = create_resp.json()["data"]
        submit_resp = api.submit_claim(
            draft["id"], make_account_holder_headers(holder["id"]),
        )
        validate_error(
            submit_resp, ApiErrorId.ERR_NO_ELIGIBLE_PLAN_YEAR.value,
        )


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_claim_submit_blocked_when_dependent_inactive(self, api):
        """# difficulty: cross_entity_state_dependency/claim_submit_blocked_when_dependent_inactive

        PRD §3.5: "that this Dependent.status is ACTIVE
        (ERR_DEPENDENT_INACTIVE if it is inactive)."

        Claim: a DCFSA /submit with an inactive Dependent ->
        ERR_DEPENDENT_INACTIVE; claim stays in DRAFT.
        """
        holder, acct, py, dep, claim = (
            setup_dcfsa_with_inactive_dependent_at_submit_time()
        )
        resp = api.submit_claim(
            claim["id"], make_account_holder_headers(holder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_INACTIVE.value)
        final = get_claim(claim["id"])
        assert final["status"] == "DRAFT"

    def test_claim_submit_blocked_dependent_inactive_after_create(self, api):
        """# difficulty: cross_entity_state_dependency/claim_submit_blocked_when_dependent_inactive

        PRD §3.1: "deactivation does not retroactively affect claims
        already in flight that cite the dependent, but blocks new
        claim submissions from citing the inactive dependent."
        PRD §3.5: "that this Dependent.status is ACTIVE
        (ERR_DEPENDENT_INACTIVE if it is inactive)."

        Claim: dependent ACTIVE at create-time; deactivated before
        /submit -> ERR_DEPENDENT_INACTIVE at /submit; claim remains
        DRAFT.
        """
        from test_helpers import (
            create_dependent,
            deactivate_dependent,
        )
        holder, acct, py = setup_funded_plan_year(
            account_type="DEPENDENT_CARE_FSA",
            coverage_tier=None, year_end_policy="NONE",
            calendar_year=2025, contribution_cents=100_000,
        )
        dep = create_dependent(account_holder=holder)
        qe = seed_qualified_expense(
            category="DEPENDENT_CARE",
            eligible_account_types=["DEPENDENT_CARE_FSA"],
            requires_dependent=True,
        )
        claim = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 6, 15),
            expense_code=qe["code"], amount_cents=10_000,
            dependent_id=dep["id"],
        )
        deactivate_dependent(dep["id"])
        resp = api.submit_claim(
            claim["id"], make_account_holder_headers(holder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_INACTIVE.value)
        final = get_claim(claim["id"])
        assert final["status"] == "DRAFT"

    def test_account_close_blocked_when_plan_year_active(self, api):
        """# difficulty: cross_entity_state_dependency/account_close_blocked_when_plan_year_active

        PRD §3.1: "Closing an account is permitted only if no
        PlanYear is in ACTIVE, GRACE_PERIOD, or CARRYOVER_PENDING
        status (otherwise rejected with
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR)".

        Claim: closing an account with an ACTIVE PlanYear ->
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR; the account stays OPEN.
        """
        from test_helpers import TEST_USERS
        _, acct, _py = setup_active_plan_year()
        resp = api.close_account(
            acct["id"], TEST_USERS["plan_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.value,
        )
        from test_helpers import get_account
        acct_after = get_account(acct["id"])
        assert acct_after["status"] == "OPEN"

    def test_account_close_blocked_when_plan_year_carryover_pending(
        self, api,
    ):
        """# difficulty: cross_entity_state_dependency/account_close_blocked_when_plan_year_active

        PRD §3.1: "Closing an account is permitted only if no
        PlanYear is in ACTIVE, GRACE_PERIOD, or CARRYOVER_PENDING
        status (otherwise rejected with
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR)".

        Claim: close with a PlanYear in CARRYOVER_PENDING ->
        ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.
        """
        from test_helpers import TEST_USERS
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="CARRYOVER", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "CARRYOVER_PENDING"
        resp = api.close_account(
            acct["id"], TEST_USERS["plan_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR.value,
        )


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_duplicate_calendar_year_rejected(
        self, api, plan_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/plan_year_calendar_year_uniqueness_per_account

        PRD §3.2: "The pair (account_id, calendar_year) is unique
        per account; an attempt to open a duplicate plan year returns
        ERR_DUPLICATE_PLAN_YEAR."

        Claim: opening the same calendar_year twice ->
        ERR_DUPLICATE_PLAN_YEAR.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account()
        open_plan_year(acct["id"], calendar_year=2025)
        resp = api.create_plan_year(
            acct["id"], create_plan_year_payload(calendar_year=2025),
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLAN_YEAR.value)

    def test_adjacent_calendar_years_both_succeed(
        self, api, plan_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/plan_year_calendar_year_uniqueness_per_account

        PRD §3.2: "The pair (account_id, calendar_year) is unique
        per account".

        Claim: adjacent calendar_year values 2025 + 2026 both succeed
        (discrete equality, not adjacency, is the conflict).
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct = setup_holder_and_account()
        py1 = open_plan_year(acct["id"], calendar_year=2025)
        py2 = open_plan_year(acct["id"], calendar_year=2026)
        assert py1["id"] != py2["id"]

    def test_ops_run_exact_duplicate_rejected(
        self, api, plan_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/ops_run_monotonic_as_of_date_on_clock_resource

        PRD §3.7: "The pair (kind, as_of_date) is unique; submitting
        a duplicate returns ERR_DUPLICATE_OPS_RUN."

        Claim: an exact-duplicate (kind, as_of_date) ->
        ERR_DUPLICATE_OPS_RUN.
        """
        advance_clock_to(iso_datetime_utc(2026, 6, 1))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        resp = api.create_ops_run(
            {
                "kind": "YEAR_END_CLOSE",
                "as_of_date": iso_datetime_utc(2026, 1, 2),
            },
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPS_RUN.value)

    def test_ops_run_earlier_than_prior_rejected(
        self, api, plan_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/ops_run_monotonic_as_of_date_on_clock_resource

        PRD §3.7: "The as_of_date must be strictly later than the
        most recent prior OpsRun.as_of_date — that is, ops runs are
        strictly monotonic; non-monotonic dates are rejected with
        ERR_OPS_RUN_NOT_MONOTONIC."

        Claim: a strictly earlier as_of_date ->
        ERR_OPS_RUN_NOT_MONOTONIC.
        """
        advance_clock_to(iso_datetime_utc(2026, 6, 1))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        resp = api.create_ops_run(
            {
                "kind": "YEAR_END_CLOSE",
                "as_of_date": iso_datetime_utc(2025, 12, 31),
            },
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OPS_RUN_NOT_MONOTONIC.value)


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_contribution_post_then_reverse_returns_to_zero(self, api):
        """# difficulty: compensating_invariant/contribution_post_then_reverse_balances_to_zero

        PRD §3.3: "The plan year's contributions_ytd_cents decreases
        by the original amount".
        PRD §2.8: "for every PlanYear, the sum of
        AuditEvent.cents_delta taken over all events whose
        subject_entity is CONTRIBUTION or CLAIM and whose plan_year_id
        equals that plan year must equal contributions_ytd_cents
        minus claims_paid_ytd_cents."

        Claim: post two contributions, reverse both -> both the
        ledger sum and contributions_ytd_cents return to 0.
        """
        from test_helpers import list_audit_events, reverse_contribution
        _, acct, py = setup_active_plan_year()
        c1 = post_contribution(py["id"], amount_cents=20_000,
                               source="PAYROLL")
        c2 = post_contribution(py["id"], amount_cents=50_000,
                               source="DIRECT")
        reverse_contribution(c1["id"])
        reverse_contribution(c2["id"])
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["contributions_ytd_cents"] == 0
        events = list_audit_events(acct["id"], plan_year_id=py["id"])
        ledger = sum(
            e["cents_delta"] for e in events
            if e.get("subject_entity") in {"CONTRIBUTION", "CLAIM"}
        )
        assert ledger == 0

    def test_contribution_reverse_ledger_invariant_with_one_outstanding(
        self, api,
    ):
        """# difficulty: compensating_invariant/contribution_post_then_reverse_balances_to_zero

        PRD §2.8: "for every PlanYear, the sum of
        AuditEvent.cents_delta ... must equal contributions_ytd_cents
        minus claims_paid_ytd_cents."

        Claim: after one reversal among two contributions, the
        ledger sum equals the remaining POSTED amount.
        """
        from test_helpers import list_audit_events, reverse_contribution
        _, acct, py = setup_active_plan_year()
        c1 = post_contribution(py["id"], amount_cents=20_000,
                               source="PAYROLL")
        post_contribution(py["id"], amount_cents=50_000,
                          source="DIRECT")
        reverse_contribution(c1["id"])
        py_after = get_plan_year(acct["id"], py["id"])
        events = list_audit_events(acct["id"], plan_year_id=py["id"])
        ledger = sum(
            e["cents_delta"] for e in events
            if e.get("subject_entity") in {"CONTRIBUTION", "CLAIM"}
        )
        expected = (
            py_after["contributions_ytd_cents"]
            - py_after["claims_paid_ytd_cents"]
        )
        assert ledger == expected
        assert py_after["contributions_ytd_cents"] == 50_000

    def test_claim_pay_reverse_preserves_drawdown_invariant(self, api):
        """# difficulty: compensating_invariant/claim_pay_then_reverse_preserves_carryover_consumed_invariant

        PRD §3.5: "claims_paid_ytd_cents decreases by the original
        paid_amount_cents, carryover_consumed_cents is adjusted
        symmetrically per the drawdown rule (undo is LIFO with
        respect to drawdown — current-year credit is restored before
        carryover credit)".

        Claim: with HEALTH_FSA CARRYOVER successor PY (carryover_in
        64_000 from predecessor) + $1_000 current-year, pay a $1_200
        claim, then reverse -> claims_paid_ytd_cents and
        carryover_consumed_cents return to 0.
        """
        holder, acct, _pred, succ, qe = setup_health_fsa_carryover_full_chain(
            predecessor_year=2025, successor_year=2026,
            pred_contribution_cents=100_000,
            pred_pay_claim_cents=20_000,
        )
        post_contribution(succ["id"], amount_cents=100_000,
                          source="PAYROLL")
        c = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2026, 6, 15),
            expense_code=qe["code"], amount_cents=120_000,
        )
        submit_claim(c["id"], account_holder=holder)
        approve_claim(c["id"])
        pay_claim(c["id"])
        reverse_claim(c["id"])
        succ_final = get_plan_year(acct["id"], succ["id"])
        assert succ_final["claims_paid_ytd_cents"] == 0
        assert succ_final["carryover_consumed_cents"] == 0
        assert succ_final["carryover_in_cents"] == 64_000

    def test_claim_pay_reverse_available_balance_restored(self, api):
        """# difficulty: compensating_invariant/claim_pay_then_reverse_preserves_carryover_consumed_invariant

        PRD §3.5: "The available balance is defined as the sum of
        contributions_ytd_cents and carryover_in_cents, less
        claims_paid_ytd_cents."

        Claim: after pay + reverse, available_balance equals
        contributions_ytd_cents + carryover_in_cents (the same as
        before the claim was paid).
        """
        holder, acct, _pred, succ, qe = setup_health_fsa_carryover_full_chain(
            predecessor_year=2025, successor_year=2026,
            pred_contribution_cents=100_000,
            pred_pay_claim_cents=20_000,
        )
        post_contribution(succ["id"], amount_cents=100_000,
                          source="PAYROLL")
        before = get_plan_year(acct["id"], succ["id"])
        ab_before = available_balance(before)
        c = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2026, 6, 15),
            expense_code=qe["code"], amount_cents=120_000,
        )
        submit_claim(c["id"], account_holder=holder)
        approve_claim(c["id"])
        pay_claim(c["id"])
        reverse_claim(c["id"])
        after = get_plan_year(acct["id"], succ["id"])
        assert available_balance(after) == ab_before
