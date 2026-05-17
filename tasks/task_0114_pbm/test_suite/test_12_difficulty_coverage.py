"""Difficulty-coverage tests: TWO tests per
``scaffold_difficulty_design`` instance.

Each test is tagged in its docstring with
``# difficulty: <rule_id>/<instance.name>`` to make the coverage
audit mechanical.

PRD-First citation rule still applies — every test cites the PRD
sentence carrying the underlying behavioral rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_CLAWBACK_WINDOW_DAYS,
    PA_EFFECTIVE_WINDOW_SECONDS,
    SECONDS_PER_DAY,
    adjudicate_claim,
    advance_clock,
    assert_ledger_zero_sum_for_claim,
    list_ledger_for_claim,
    occ_payload,
    pay_claim,
    re_get_claim,
    re_get_copay_card,
    re_get_member,
    re_get_prior_authorization,
    resubmit_prior_authorization_payload,
    reverse_claim,
    revoke_pa,
    run_race,
    setup_dd_claim_parallel_axes,
    setup_dd_estimated_vs_adjudicated,
    setup_dd_member_blocks_adjudicate,
    setup_dd_member_ytd_round_trip,
    setup_dd_pa_cyclic,
    setup_dd_pa_denied_blocks_adjudicate,
    setup_dd_pa_required_beats_card_mismatch,
    setup_dd_pa_window_boundary,
    setup_dd_pa_window_closed_open,
    setup_dd_rebate_accrual_clawback,
    setup_dd_refill_too_soon_half_open,
    setup_dd_reverse_depth_three_cascade,
    setup_dd_revoke_pa_depth_two,
    setup_dd_side_effect_ordering,
    setup_dd_state_beats_specialty,
    setup_dd_step_therapy_empty_history,
    setup_dd_three_input_formula_with_card,
    submit_claim,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_estimate_vs_adjudicated_diverge(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: dual_variant_calc/
        estimated_vs_adjudicated_member_cost_on_claim

        PRD §3.4: "This estimate is informational: it is the variant
        of the cost calculation that uses the member's year-to-date
        counters as they stand at submission time".
        PRD §3.5: "the system re-runs the cost formula using the
        member's year-to-date counters at adjudication time, which
        may have moved since the claim was first submitted."

        Claim: claim_A's estimate (computed at submission, YTD=0)
        differs from its adjudicated_member_cost (computed after
        claim_B already moved YTD).
        """
        ctx = setup_dd_estimated_vs_adjudicated()
        # claim_A's estimate was captured at submission time. The
        # adjudicated row is the post-claim_B value.
        claim_a_submitted = ctx["claim_a_submitted"]
        claim_a_adj = ctx["claim_a_adjudicated"]
        assert claim_a_submitted["estimated_member_cost_cents"] == 100_000
        # PRD §3.5 chronological recalculation:
        # allowed=10000*30=300000.
        # YTD at adjudication: claim_B already adjudicated and
        # advanced ytd_deductible by min(40000, 50000) = 40000.
        # claim_A: ded_remaining=50000-40000=10000.
        # ded_portion=min(300000, 10000)=10000.
        # post_ded=290000. member_share=290000*0.20=58000.
        # member_pre_card=10000+58000=68000. oop_remaining is not
        # binding (cap >> 68000).
        assert claim_a_adj["adjudicated_member_cost_cents"] == 68_000
        assert (
            claim_a_submitted["estimated_member_cost_cents"]
            != claim_a_adj["adjudicated_member_cost_cents"]
        )

    def test_provisional_rebate_vs_final_after_clawback(self, api):
        """# difficulty: dual_variant_calc/
        provisional_rebate_vs_final_after_clawback

        PRD §3.6: "The accrued amount is the claim's
        adjudicated_plan_paid_cents multiplied by the agreement's
        rebate_rate, rounded half-up to the nearest whole cent, and
        stored as a positive integer on LedgerEntry.amount_cents."
        PRD §3.7: "a compensating REBATE_CLAWBACK LedgerEntry is
        appended whose amount_cents is the negation of the original
        accrual; the invariant after this second posting is that the
        sum of every ledger entry's amount_cents for the same
        claim_id is exactly zero."

        Claim: after PAY -> REVERSE within window, ledger holds
        +6600 REBATE_ACCRUED and -6600 REBATE_CLAWBACK; sum=0.
        """
        ctx = setup_dd_rebate_accrual_clawback()
        entries = list_ledger_for_claim(ctx["claim_paid"]["id"])
        accruals = [e for e in entries
                    if e["entry_type"] == "REBATE_ACCRUED"]
        clawbacks = [e for e in entries
                     if e["entry_type"] == "REBATE_CLAWBACK"]
        assert len(accruals) == 1
        assert len(clawbacks) == 1
        assert accruals[0]["amount_cents"] == 6_600
        assert clawbacks[0]["amount_cents"] == -6_600
        assert_ledger_zero_sum_for_claim(entries)


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_tier3_with_oop_cap_and_card_three_inputs(self, api):
        """# difficulty: combinatorial_formula/
        tiered_copay_plus_oop_cap_plus_card_three_input_formula

        PRD §3.5: "compute the allowed charge … carve the deductible
        portion as the smaller of allowed and current deductible-
        remaining; compute the post-deductible balance; pick the
        tier-driven member share (flat formulary copay_cents for
        tier 1 or 2, capped at the post-deductible balance;
        otherwise the post-deductible balance times coinsurance_rate
        rounded half-up); sum to obtain the member's pre-card cost;
        cap that pre-card cost to the current out-of-pocket headroom;
        and, if a card is in play, deduct the card's contribution".

        Setup: Plan(ded=5000, oop_max=10000, coins=0.20). Drug
        unit=2000, q=10 -> allowed=20000. Member ytd_ded=5000,
        ytd_oop=8000 -> ded_remaining=0, oop_remaining=2000. tier 3
        -> coinsurance branch. post_ded=20000, member_share=
        20000*0.20=4000. member_pre_card=0+4000=4000, capped to
        oop_remaining=2000. card cap = min(500, 500, 2000) = 500.
        Expected: adjudicated_allowed_cents=20000,
        adjudicated_member_cost_cents=1500, copay_card_paid_cents=500.
        """
        ctx = setup_dd_three_input_formula_with_card()
        c = ctx["claim_adjudicated"]
        assert c["adjudicated_allowed_cents"] == 20_000
        assert c["adjudicated_member_cost_cents"] == 1_500
        assert c["copay_card_paid_cents"] == 500

    def test_side_effect_order_oop_counts_pre_card_share(self, api):
        """# difficulty: combinatorial_formula/
        side_effect_ordering_deductible_then_oop_then_card

        PRD §3.5: "first, the member's ytd_deductible_paid_cents is
        incremented by the deductible portion of this claim; second,
        the member's ytd_oop_paid_cents is incremented by the
        member's pre-card cost (the out-of-pocket counter therefore
        tracks the pre-card member share, not the post-card residual);
        third, if a copay card was used, the card's used_cents is
        incremented by copay_card_paid_cents."

        Setup: Plan(ded=0, oop_max=100000, coins=0.20). Drug
        unit=1000, q=30 -> allowed=30000. Member ytd=0. tier 3 ->
        post_ded=30000, member_share=30000*0.20=6000. card max=1000,
        pcc=1000 -> card_payable=min(1000, 1000-0, 6000)=1000.
        adjudicated_member_cost_cents = 6000-1000 = 5000.
        Member.ytd_oop must be 6000 (NOT 5000); CopayCard.used must
        be 1000.
        """
        ctx = setup_dd_side_effect_ordering()
        c = ctx["claim_adjudicated"]
        assert c["adjudicated_member_cost_cents"] == 5_000
        assert c["copay_card_paid_cents"] == 1_000
        m = re_get_member(ctx["member"]["id"])
        assert m["ytd_oop_paid_cents"] == 6_000
        card = re_get_copay_card(ctx["card"]["id"])
        assert card["used_cents"] == 1_000


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_pa_cyclic_revision_count_reaches_limit(
        self, api, prescriber_headers, clinical_reviewer_headers,
    ):
        """# difficulty: non_linear_state_machine/
        prior_auth_cyclic_submitted_info_requested

        PRD §3.3: "a fresh revision is only legal while
        revision_count is strictly less than 3 at the moment of
        resubmit (so 0, 1, and 2 are the only legal source values,
        yielding 1, 2, and 3 respectively after the increment). An
        attempt to resubmit when revision_count is already 3 is
        rejected with ERR_PA_REVISION_LIMIT."

        Claim: with a PA cycled to SUBMITTED at revision_count=2,
        request-info + resubmit-attempt-after-third-increment is
        rejected with ERR_PA_REVISION_LIMIT.
        """
        ctx = setup_dd_pa_cyclic()
        pa = ctx["pa"]
        assert pa["status"] == "SUBMITTED"
        assert pa["revision_count"] == 2
        # request-info -> resubmit takes revision_count 2 -> 3, which
        # is the maximum LEGAL value (PRD source values 0/1/2 yield
        # 1/2/3). One more cycle must be rejected.
        info_res = api.request_info_prior_authorization(
            pa["id"], occ_payload(version=pa["version"]),
            clinical_reviewer_headers,
        )
        info = validate_success(info_res, 200)
        resub_res = api.resubmit_prior_authorization(
            info["id"],
            resubmit_prior_authorization_payload(
                clinical_rationale="more", version=info["version"],
            ),
            prescriber_headers,
        )
        # Now PA has revision_count==3 in SUBMITTED. One more cycle:
        resubmitted = validate_success(resub_res, 200)
        assert resubmitted["revision_count"] == 3
        info2 = validate_success(
            api.request_info_prior_authorization(
                resubmitted["id"],
                occ_payload(version=resubmitted["version"]),
                clinical_reviewer_headers,
            ),
            200,
        )
        # The third resubmit attempt — source value would be 3 → not
        # strictly less than 3. PRD: ERR_PA_REVISION_LIMIT.
        final_res = api.resubmit_prior_authorization(
            info2["id"],
            resubmit_prior_authorization_payload(
                clinical_rationale="and more", version=info2["version"],
            ),
            prescriber_headers,
        )
        validate_error(final_res, "ERR_PA_REVISION_LIMIT")

    def test_claim_parallel_axes_evolve_together(
        self, api,
    ):
        """# difficulty: non_linear_state_machine/
        claim_parallel_status_axes

        PRD §3.6: "the claim's payment_status parallel-axis field
        flips from UNPAID to PAID. The two axes are otherwise
        independent: a claim's lifecycle status may be PAID or
        REVERSED, while the payment axis runs UNPAID, PAID,
        REFUNDED."
        PRD §3.7: "The claim's status transitions to REVERSED and its
        payment_status flips from PAID to REFUNDED."

        Claim: after pay, (status, payment_status) = (PAID, PAID);
        after reverse, (status, payment_status) = (REVERSED,
        REFUNDED).
        """
        ctx = setup_dd_claim_parallel_axes()
        adj = ctx["claim_adjudicated"]
        paid = pay_claim(adj)
        assert paid["status"] == "PAID"
        assert paid["payment_status"] == "PAID"
        reversed_claim = reverse_claim(paid)
        assert reversed_claim["status"] == "REVERSED"
        assert reversed_claim["payment_status"] == "REFUNDED"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_reverse_claim_cascades_to_next_adjudicate(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: transitive_cascade/
        reverse_claim_depth_three_cascade_through_member_ytd

        PRD §3.7: "The reverse's effect on the member's year-to-date
        counters is observable on the next adjudication for the same
        member: a claim that submits before the reverse and
        adjudicates after it will allocate deductible and out-of-
        pocket differently than it would have under the pre-reverse
        balances. This three-step cascade — reverse on the claim,
        mutate the member's year-to-date, change the deductible-
        attribution outcome for the next claim — is the
        chronological-recalculation premise made concrete."

        Setup: claim_A PAID consumed 50000 deductible; claim_B is
        SUBMITTED for a different drug. Reverse claim_A, then
        adjudicate claim_B; claim_B sees ytd_ded=0 and allocates the
        full 10000 to its own deductible portion.
        """
        ctx = setup_dd_reverse_depth_three_cascade()
        claim_a = ctx["claim_a_paid"]
        claim_b = ctx["claim_b_submitted"]
        # before
        m_before = re_get_member(ctx["member"]["id"])
        assert m_before["ytd_deductible_paid_cents"] == 50_000
        # link 1+2: REVERSE claim_A -> Member.ytd_ded -> 0
        reverse_claim(claim_a)
        m_after_rev = re_get_member(ctx["member"]["id"])
        assert m_after_rev["ytd_deductible_paid_cents"] == 0
        # link 3: ADJUDICATE claim_B against fresh YTD.
        # claim_B: allowed=10000*1=10000. ded_portion=min(10000,
        # 50000)=10000. post_ded=0. member_pre_card=10000.
        b_adj = adjudicate_claim(claim_b)
        assert b_adj["adjudicated_member_cost_cents"] == 10_000
        m_final = re_get_member(ctx["member"]["id"])
        assert m_final["ytd_deductible_paid_cents"] == 10_000

    def test_revoke_pa_cascades_to_pending_claim_rejection(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: transitive_cascade/
        revoke_pa_depth_two_cascade_into_pending_claim

        PRD §2.9: "Revoking an APPROVED prior authorization marks
        the prior authorization as REVOKED and does not auto-reverse
        claims that were already PAID under it. Any claim currently
        in SUBMITTED that references the revoked prior authorization
        will fail at adjudicate with ERR_PA_REVOKED".
        PRD §3.3: "a claim currently in SUBMITTED that references
        the now-revoked prior authorization will fail at adjudicate
        with ERR_PA_REVOKED, leaving the member's year-to-date
        counters untouched."

        Claim: revoke PA, then adjudicate Claim referencing it ->
        ERR_PA_REVOKED; Member YTD unchanged.
        """
        ctx = setup_dd_revoke_pa_depth_two()
        m_before = re_get_member(ctx["member"]["id"])
        revoke_pa(ctx["pa_approved"])
        refreshed_pa = re_get_prior_authorization(
            ctx["pa_approved"]["id"],
        )
        assert refreshed_pa["status"] == "REVOKED"
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_REVOKED")
        m_after = re_get_member(ctx["member"]["id"])
        assert (m_after["ytd_deductible_paid_cents"]
                == m_before["ytd_deductible_paid_cents"])
        assert (m_after["ytd_oop_paid_cents"]
                == m_before["ytd_oop_paid_cents"])


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_beats_specialty(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/
        state_beats_business_safety_pa_revoked_vs_specialty

        PRD §2.8: "A request that violates multiple rungs of this
        ladder always surfaces the lowest-numbered violation; deeper
        checks are not even evaluated."
        PRD §2.8 rung 4 (state legality) and rung 6 (specialty
        channel match): state precedes specialty.

        Setup: an already-ADJUDICATED claim for a specialty drug
        (initial adjudicate used the correct SPECIALTY channel).
        Re-adjudicating it would simultaneously violate rung 4
        (already not in SUBMITTED) and — were the implementer to
        evaluate it — rung 6 only matters before claim is
        re-adjudicated. Per PRD §2.8 the lowest rung's error_id wins,
        so we expect ERR_INVALID_STATE.
        """
        ctx = setup_dd_state_beats_specialty()
        c = ctx["claim_adjudicated"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_pa_required_beats_copay_card_mismatch(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/
        business_safety_beats_business_referential_pa_required_vs_card_mismatch

        PRD §2.8: "A request that violates multiple rungs of this
        ladder always surfaces the lowest-numbered violation; deeper
        checks are not even evaluated."
        PRD §2.8 rung 7 (PA required) precedes rung 12 (copay-card
        matching).

        Setup: drug requires_prior_auth=true, no APPROVED PA, and
        copay card bound to a different drug. Both rungs would fire;
        PA_REQUIRED wins.
        """
        ctx = setup_dd_pa_required_beats_card_mismatch()
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_REQUIRED")


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    def test_pa_window_exact_end_boundary(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: boundary_precision_check/
        pa_effective_window_exact_end_boundary

        PRD §3.5: "the current clock time is at or after the prior
        authorization's effective_start and strictly earlier than its
        effective_end. The precise edge case is that a clock-time
        exactly equal to effective_end has already triggered the
        auto-expiry transition documented in §2.11 and is therefore
        outside the window, yielding ERR_PA_EXPIRED."

        Claim: at clock = effective_end - 1s, adjudicate is accepted;
        at clock = effective_end exactly, adjudicate is rejected with
        ERR_PA_EXPIRED.
        """
        ctx = setup_dd_pa_window_boundary()
        c1, c2 = ctx["claim_c1"], ctx["claim_c2"]
        # Advance to effective_end - 1s.
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS - 1)
        adj_res = api.adjudicate_claim(
            c1["id"], occ_payload(version=c1["version"]),
            claims_adjudicator_headers,
        )
        c1_adj = validate_success(adj_res, 200)
        assert c1_adj["status"] == "ADJUDICATED"
        # Advance 1 more second -> clock == effective_end.
        advance_clock(1)
        rej_res = api.adjudicate_claim(
            c2["id"], occ_payload(version=c2["version"]),
            claims_adjudicator_headers,
        )
        validate_error(rej_res, "ERR_PA_EXPIRED")

    def test_step_therapy_empty_history_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: boundary_precision_check/
        empty_step_therapy_predecessor_history_on_claim_endpoint

        PRD §3.5: "If the drug's step_therapy_predecessor_ndc is
        non-null and the claim is not riding on an APPROVED prior
        authorization, the system must locate at least one Claim for
        the same member_id, whose drug_id resolves to the
        predecessor's ndc, whose status is PAID, and whose
        adjudication occurred inside the member's current benefit
        year (that is, on or after benefit_year_start). Failure
        yields ERR_STEP_THERAPY_NOT_SATISFIED."

        Claim: empty-predecessor-history -> ERR_STEP_THERAPY_NOT_SATISFIED.
        """
        ctx = setup_dd_step_therapy_empty_history()
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_STEP_THERAPY_NOT_SATISFIED")


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_member_suspension_blocks_adjudicate(
        self, api, admin_headers, claims_adjudicator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/
        claim_adjudicate_blocked_by_member_status

        PRD §3.5: "The referenced member must be ACTIVE on penalty
        of ERR_MEMBER_NOT_ACTIVE."
        PRD §2.8 rung 5: "the referenced Member must satisfy
        enrollment_status equal to ACTIVE; otherwise the request
        yields ERR_MEMBER_NOT_ACTIVE (409)."

        Claim: suspend the member, then adjudicate ->
        ERR_MEMBER_NOT_ACTIVE.
        """
        ctx = setup_dd_member_blocks_adjudicate()
        member = ctx["member"]
        api.suspend_member(
            member["id"], {"version": member["version"]},
            admin_headers,
        )
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_MEMBER_NOT_ACTIVE")

    def test_pa_denied_blocks_adjudicate(
        self, api, clinical_reviewer_headers,
        claims_adjudicator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/
        claim_adjudicate_blocked_by_prior_auth_state

        PRD §3.5: "A referenced prior authorization in DENIED yields
        ERR_PA_DENIED".

        Claim: deny the referenced PA, then adjudicate the claim ->
        ERR_PA_DENIED.
        """
        ctx = setup_dd_pa_denied_blocks_adjudicate()
        pa = ctx["pa_submitted"]
        # Deny the PA.
        api.deny_prior_authorization(
            pa["id"],
            {"denial_reason": "off-label", "version": pa["version"]},
            clinical_reviewer_headers,
        )
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_DENIED")


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_refill_too_soon_half_open_day_granularity(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: resource_temporal_overlap/
        refill_too_soon_half_open_day_granularity_on_member_drug_pair

        PRD §3.5: "Two half-open intervals [a, a+da) and [b, b+db)
        overlap when a is strictly less than b+db and b is strictly
        less than a+da; adjacency at the boundary — a candidate that
        starts exactly when the prior interval ends — is allowed and
        does not count as overlap."

        Setup: C1 ADJUDICATED at T=0 with days_supply=30 (window
        [0,30)). C2 and C3 pre-submitted. At T=29 (overlap), C2 ->
        ERR_REFILL_TOO_SOON. At T=30 (adjacency), C3 -> ADJUDICATED.
        """
        ctx = setup_dd_refill_too_soon_half_open()
        # T=29 -> overlap.
        advance_clock(29 * SECONDS_PER_DAY)
        c2 = ctx["claim_c2_submitted"]
        res2 = api.adjudicate_claim(
            c2["id"], occ_payload(version=c2["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res2, "ERR_REFILL_TOO_SOON")
        # Advance to T=30 -> adjacency.
        advance_clock(SECONDS_PER_DAY)
        c3 = ctx["claim_c3_submitted"]
        res3 = api.adjudicate_claim(
            c3["id"], occ_payload(version=c3["version"]),
            claims_adjudicator_headers,
        )
        c3_adj = validate_success(res3, 200)
        assert c3_adj["status"] == "ADJUDICATED"

    def test_pa_window_closed_open_second_granularity(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: resource_temporal_overlap/
        pa_effective_window_closed_open_second_granularity_on_pa_resource

        PRD §3.5: "the current clock time is at or after the prior
        authorization's effective_start and strictly earlier than its
        effective_end. The precise edge case is that a clock-time
        exactly equal to effective_end has already triggered the
        auto-expiry transition documented in §2.11 and is therefore
        outside the window, yielding ERR_PA_EXPIRED."

        Setup: PA APPROVED at clock T=0 with effective_end=T+180d.
        At T=0 exactly (== effective_start, closed-left), adjudicate
        is accepted. At T = effective_end exactly (open-right),
        adjudicate is rejected with ERR_PA_EXPIRED.
        """
        ctx = setup_dd_pa_window_closed_open()
        c1, c2 = ctx["claim_c1"], ctx["claim_c2"]
        # Clock has not been advanced — we are at effective_start
        # exactly (closed-left).
        res1 = api.adjudicate_claim(
            c1["id"], occ_payload(version=c1["version"]),
            claims_adjudicator_headers,
        )
        c1_adj = validate_success(res1, 200)
        assert c1_adj["status"] == "ADJUDICATED"
        # Advance to effective_end exactly (open-right).
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS)
        res2 = api.adjudicate_claim(
            c2["id"], occ_payload(version=c2["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res2, "ERR_PA_EXPIRED")


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_rebate_ledger_zero_sum_within_window(self, api):
        """# difficulty: compensating_invariant/
        rebate_ledger_zero_sum_after_clawback_within_window

        PRD §3.7: "the invariant after this second posting is that
        the sum of every ledger entry's amount_cents for the same
        claim_id is exactly zero."

        Claim: after PAY+REVERSE within window, ledger entries for
        the claim_id sum to 0.
        """
        ctx = setup_dd_rebate_accrual_clawback()
        entries = list_ledger_for_claim(ctx["claim_paid"]["id"])
        # Exactly one accrual, exactly one clawback.
        accruals = [e for e in entries
                    if e["entry_type"] == "REBATE_ACCRUED"]
        clawbacks = [e for e in entries
                     if e["entry_type"] == "REBATE_CLAWBACK"]
        assert len(accruals) == 1 and len(clawbacks) == 1
        assert_ledger_zero_sum_for_claim(entries)

    def test_member_ytd_zero_drift_after_round_trip(
        self, api,
    ):
        """# difficulty: compensating_invariant/
        member_ytd_zero_drift_after_adjudicate_reverse_round_trip

        PRD §3.7: "The member's ytd_deductible_paid_cents is
        decremented by the deductible portion that was originally
        applied to this claim, and the member's ytd_oop_paid_cents is
        decremented by the adjudicated_member_cost_cents that was
        originally written at adjudicate."

        Setup: Plan(ded=50000, oop_max=200000, coins=0.20, tier 3
        copay=0). Drug unit=10000, q=30, RETAIL_30. Member fresh.
        After adjudicate: ytd_ded=50000, ytd_oop=100000.
        After pay-then-reverse (no card): ytd_ded=0, ytd_oop=0.

        Note: this scenario uses NO copay card so that
        adjudicated_member_cost_cents == member_pre_card; the §3.7
        sentence "decremented by adjudicated_member_cost_cents" then
        cleanly returns ytd_oop to 0 regardless of any pre-card-vs-
        post-card asymmetry. PRD-only readers will arrive at the
        same observable outcome on this fixture.
        """
        ctx = setup_dd_member_ytd_round_trip()
        c = ctx["claim_submitted"]
        # Adjudicate
        from test_helpers import adjudicate_claim as _adj
        c_adj = _adj(c)
        m_after_adj = re_get_member(ctx["member"]["id"])
        assert m_after_adj["ytd_deductible_paid_cents"] == 50_000
        assert m_after_adj["ytd_oop_paid_cents"] == 100_000
        # Pay
        c_paid = pay_claim(c_adj)
        # Reverse
        reverse_claim(c_paid)
        m_after_rev = re_get_member(ctx["member"]["id"])
        assert m_after_rev["ytd_deductible_paid_cents"] == 0
        assert m_after_rev["ytd_oop_paid_cents"] == 0
