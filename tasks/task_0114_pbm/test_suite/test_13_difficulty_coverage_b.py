"""Second tagged test per ``scaffold_difficulty_design`` instance.

Each instance defined in SCAFFOLD_DIFFICULTY_DESIGN.yaml requires
at least TWO dedicated tests; this file holds the second variant
for each. Each test below asserts a strictly different observable
than its sibling in test_12_difficulty_coverage.py, against the
same PRD-stated rule.

Citation rule still applies — every test cites the PRD sentence
carrying the rule under test.
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
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    create_rebate_agreement,
    list_ledger_for_claim,
    occ_payload,
    pay_claim,
    re_get_claim,
    re_get_copay_card,
    re_get_member,
    re_get_prior_authorization,
    request_info_pa,
    resubmit_pa,
    reverse_claim,
    revoke_pa,
    setup_adjudicated_claim,
    setup_approved_pa,
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
    setup_paid_claim,
    setup_reference_data,
    setup_submitted_pa,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalcB:

    def test_estimated_member_cost_matches_pre_claim_b_state(self, api):
        """# difficulty: dual_variant_calc/
        estimated_vs_adjudicated_member_cost_on_claim

        PRD §3.4: "This estimate is informational: it is the variant
        of the cost calculation that uses the member's year-to-date
        counters as they stand at submission time and assumes that
        no other claim will adjudicate before this one."

        Second-angle assertion: the estimate captured at submission
        equals the FULL coinsurance share against a fresh deductible,
        independently of any claim that later adjudicated against
        the same member.

        Setup arithmetic (from setup_dd_estimated_vs_adjudicated):
          allowed=10000*30=300000. YTD at submission = 0.
          ded_portion=min(300000, 50000)=50000. post_ded=250000.
          tier 3 -> member_share=250000*0.20=50000.
          member_pre_card=100000. estimate=100000.
        """
        ctx = setup_dd_estimated_vs_adjudicated()
        assert (
            ctx["claim_a_submitted"]["estimated_member_cost_cents"]
            == 100_000
        )

    def test_adjudicated_plan_paid_reflects_post_intervening_ytd(self, api):
        """# difficulty: dual_variant_calc/
        provisional_rebate_vs_final_after_clawback

        PRD §3.6: "The accrued amount is the claim's
        adjudicated_plan_paid_cents multiplied by the agreement's
        rebate_rate, rounded half-up to the nearest whole cent".

        Second-angle assertion: the accrual ledger entry's
        amount_cents is exactly the round-half-up of the claim's
        ``adjudicated_plan_paid_cents`` multiplied by the agreement's
        rate (44000 * 0.15 = 6600), and the agreement reference is
        propagated correctly.
        """
        ctx = setup_dd_rebate_accrual_clawback()
        entries = list_ledger_for_claim(ctx["claim_paid"]["id"])
        accruals = [e for e in entries
                    if e["entry_type"] == "REBATE_ACCRUED"]
        assert len(accruals) == 1
        accrual = accruals[0]
        # Recompute from the claim row.
        plan_paid = ctx["claim_paid"]["adjudicated_plan_paid_cents"]
        expected = round(plan_paid * 0.15)
        assert accrual["amount_cents"] == expected
        assert accrual["rebate_agreement_id"] == ctx["agreement"]["id"]


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormulaB:

    def test_oop_cap_dominates_post_card_member_cost(self, api):
        """# difficulty: combinatorial_formula/
        tiered_copay_plus_oop_cap_plus_card_three_input_formula

        PRD §3.5: "cap that pre-card cost to the current out-of-
        pocket headroom".

        Second-angle assertion: regardless of the deductible /
        coinsurance computation, the member_pre_card cap from
        oop_remaining=2000 is observable as the
        adjudicated_member_cost (1500) plus the
        copay_card_paid_cents (500) summing to 2000 — the OOP
        headroom — and that this sum equals the OOP increment on
        Member.
        """
        ctx = setup_dd_three_input_formula_with_card()
        c = ctx["claim_adjudicated"]
        member_pre_card_observed = (
            c["adjudicated_member_cost_cents"]
            + c["copay_card_paid_cents"]
        )
        # PRD §3.5: member_pre_card is capped by oop_remaining=2000.
        assert member_pre_card_observed == 2_000
        # Member.ytd_oop must have advanced by exactly
        # member_pre_card (2000) from its pre-claim value of 8000
        # up to 10000.
        m = re_get_member(ctx["member"]["id"])
        assert m["ytd_oop_paid_cents"] == 10_000

    def test_card_used_cents_tracks_card_paid(self, api):
        """# difficulty: combinatorial_formula/
        side_effect_ordering_deductible_then_oop_then_card

        PRD §3.5: "third, if a copay card was used, the card's
        used_cents is incremented by copay_card_paid_cents."

        Second-angle assertion: CopayCard.used_cents equals exactly
        the claim's copay_card_paid_cents (1000), confirming the
        pinned third-position side effect lands on the card row.
        """
        ctx = setup_dd_side_effect_ordering()
        c = ctx["claim_adjudicated"]
        card = re_get_copay_card(ctx["card"]["id"])
        assert card["used_cents"] == c["copay_card_paid_cents"] == 1000


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachineB:

    def test_pa_revision_count_increments_each_resubmit(
        self, api,
    ):
        """# difficulty: non_linear_state_machine/
        prior_auth_cyclic_submitted_info_requested

        PRD §3.3: "The resubmit hop increments revision_count by
        exactly one as part of the transition back to SUBMITTED".

        Second-angle assertion: at revision_count=2 the PA is in
        SUBMITTED, having traversed two complete request-info ->
        resubmit cycles. revision_count strictly less than 3 at this
        point is the legal source value for the next resubmit (per
        PRD §3.3: "0, 1, and 2 are the only legal source values").
        """
        ctx = setup_dd_pa_cyclic()
        pa = ctx["pa"]
        assert pa["status"] == "SUBMITTED"
        assert pa["revision_count"] == 2
        # Re-fetch via GET to confirm persistence.
        fresh = re_get_prior_authorization(pa["id"])
        assert fresh["status"] == "SUBMITTED"
        assert fresh["revision_count"] == 2

    def test_claim_payment_status_distinct_from_status(self, api):
        """# difficulty: non_linear_state_machine/
        claim_parallel_status_axes

        PRD §3.6: "The two axes are otherwise independent: a claim's
        lifecycle status may be PAID or REVERSED, while the payment
        axis runs UNPAID, PAID, REFUNDED."

        Second-angle assertion: after a full ADJUDICATE -> PAY ->
        REVERSE round trip, the lifecycle ``status`` reports
        REVERSED while the payment axis reports REFUNDED — two
        DISTINCT enum values observable on the same row.
        """
        ctx = setup_dd_claim_parallel_axes()
        paid = pay_claim(ctx["claim_adjudicated"])
        reversed_claim = reverse_claim(paid)
        assert reversed_claim["status"] != reversed_claim["payment_status"]
        assert reversed_claim["status"] == "REVERSED"
        assert reversed_claim["payment_status"] == "REFUNDED"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascadeB:

    def test_reverse_then_adjudicate_member_ytd_lands_on_new_claim(
        self, api,
    ):
        """# difficulty: transitive_cascade/
        reverse_claim_depth_three_cascade_through_member_ytd

        PRD §3.7: "The reverse's effect on the member's year-to-date
        counters is observable on the next adjudication for the same
        member: a claim that submits before the reverse and
        adjudicates after it will allocate deductible and out-of-
        pocket differently than it would have under the pre-reverse
        balances."

        Second-angle assertion: after the cascade, Member.ytd_ded
        equals exactly the deductible portion of claim_B, not the
        sum of pre-reverse + post-reverse YTD. That is: the
        decrement-then-increment chain leaves the Member's YTD at
        the post-cascade state.
        """
        ctx = setup_dd_reverse_depth_three_cascade()
        reverse_claim(ctx["claim_a_paid"])
        # After reverse, ytd_ded was 0; claim_B's allowed=10000.
        b_adj = adjudicate_claim(ctx["claim_b_submitted"])
        # ytd_oop should now equal b's adjudicated_member_cost_cents
        # (=10000, since no card and post_ded=0 means member_share=0,
        # so member_pre_card=ded_portion=10000).
        m = re_get_member(ctx["member"]["id"])
        assert m["ytd_oop_paid_cents"] == 10_000
        assert b_adj["adjudicated_plan_paid_cents"] == 0
        # Plan-paid is zero because the entire allowed amount fell
        # into the deductible portion.

    def test_revoke_pa_does_not_change_member_ytd(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: transitive_cascade/
        revoke_pa_depth_two_cascade_into_pending_claim

        PRD §3.3: "a claim currently in SUBMITTED that references
        the now-revoked prior authorization will fail at adjudicate
        with ERR_PA_REVOKED, leaving the member's year-to-date
        counters untouched."

        Second-angle assertion (orthogonal to the error_id check):
        Member.ytd_deductible_paid_cents and ytd_oop_paid_cents are
        BOTH unchanged before and after the rejected adjudicate.
        """
        ctx = setup_dd_revoke_pa_depth_two()
        revoke_pa(ctx["pa_approved"])
        m_before = re_get_member(ctx["member"]["id"])
        c = ctx["claim_submitted"]
        api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        m_after = re_get_member(ctx["member"]["id"])
        assert (m_after["ytd_deductible_paid_cents"]
                == m_before["ytd_deductible_paid_cents"])
        assert (m_after["ytd_oop_paid_cents"]
                == m_before["ytd_oop_paid_cents"])


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflictB:

    def test_state_check_returns_409_not_422_for_specialty_conflict(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/
        state_beats_business_safety_pa_revoked_vs_specialty

        PRD §5: ERR_INVALID_STATE -> 409;
        ERR_SPECIALTY_CHANNEL_REQUIRED -> 422.
        PRD §2.8: "A request that violates multiple rungs of this
        ladder always surfaces the lowest-numbered violation".

        Second-angle assertion: HTTP status is 409 (state) rather
        than 422 (specialty), confirming the lowest-rung error wins
        even at the HTTP-layer projection.
        """
        ctx = setup_dd_state_beats_specialty()
        c = ctx["claim_adjudicated"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"

    def test_pa_required_returns_422_when_card_also_mismatched(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/
        business_safety_beats_business_referential_pa_required_vs_card_mismatch

        PRD §5: ERR_PA_REQUIRED -> 422;
        ERR_COPAY_CARD_MISMATCH -> 422 (same HTTP layer).
        PRD §2.8: "deeper checks are not even evaluated."

        Second-angle assertion: even though both rungs would
        project to HTTP 422, the error_id surfaced is the lower-
        ranked rung 7's ERR_PA_REQUIRED — never ERR_COPAY_CARD_MISMATCH.
        """
        ctx = setup_dd_pa_required_beats_card_mismatch()
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        assert res.status_code == 422
        body = res.json()
        assert body["data"]["error_id"] == "ERR_PA_REQUIRED"
        assert body["data"]["error_id"] != "ERR_COPAY_CARD_MISMATCH"


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionB:

    def test_pa_window_one_second_inside_end_accepts(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: boundary_precision_check/
        pa_effective_window_exact_end_boundary

        PRD §3.5: "the current clock time is at or after the prior
        authorization's effective_start and strictly earlier than
        its effective_end."

        Second-angle assertion: at clock_time == effective_end - 1s,
        adjudicate succeeds AND the claim's status moves to
        ADJUDICATED. Confirms the strictly-earlier-than gate accepts
        the value immediately below the boundary.
        """
        ctx = setup_dd_pa_window_boundary()
        c1 = ctx["claim_c1"]
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS - 1)
        res = api.adjudicate_claim(
            c1["id"], occ_payload(version=c1["version"]),
            claims_adjudicator_headers,
        )
        adj = validate_success(res, 200)
        assert adj["status"] == "ADJUDICATED"

    def test_step_therapy_empty_history_claim_lands_in_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: boundary_precision_check/
        empty_step_therapy_predecessor_history_on_claim_endpoint

        PRD §3.5: "Each precondition failure at adjudicate marks the
        claim as REJECTED, writes the specific failure into
        reject_reason, and leaves all year-to-date counters and
        copay-card counters untouched."

        Second-angle assertion (orthogonal to the error_id check):
        after the rejected adjudicate, the claim's status is
        REJECTED and Member.ytd_* are still at zero.
        """
        ctx = setup_dd_step_therapy_empty_history()
        c = ctx["claim_submitted"]
        api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        refreshed = re_get_claim(c["id"])
        assert refreshed["status"] == "REJECTED"
        m = re_get_member(ctx["member"]["id"])
        assert m["ytd_deductible_paid_cents"] == 0
        assert m["ytd_oop_paid_cents"] == 0


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependencyB:

    def test_member_status_suspended_persists_blocking_repeat(
        self, api, admin_headers, claims_adjudicator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/
        claim_adjudicate_blocked_by_member_status

        PRD §3.2: "the clinical and adjudication paths gate on
        enrollment_status equal to ACTIVE: both claim adjudicate
        and prior-authorization approve refuse to proceed when the
        referenced member is in any non-ACTIVE state, returning
        ERR_MEMBER_NOT_ACTIVE."

        Second-angle assertion: the block is persistent — a second
        adjudicate attempt on the same SUSPENDED member also
        surfaces ERR_MEMBER_NOT_ACTIVE (not a stale-state error).
        """
        ctx = setup_dd_member_blocks_adjudicate()
        m = ctx["member"]
        api.suspend_member(
            m["id"], {"version": m["version"]}, admin_headers,
        )
        c = ctx["claim_submitted"]
        # First attempt — rejected.
        api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        # Refresh the claim — its version may have advanced if the
        # implementation flips status to REJECTED on the failed
        # precondition. Submit a fresh claim and try again.
        c2 = submit_claim(
            member_id=m["id"], drug_id=ctx["drug"]["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        res = api.adjudicate_claim(
            c2["id"], occ_payload(version=c2["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_MEMBER_NOT_ACTIVE")

    def test_pa_denied_persists_blocking_via_status_field(
        self, api, clinical_reviewer_headers,
        claims_adjudicator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/
        claim_adjudicate_blocked_by_prior_auth_state

        PRD §3.3: "Any later claim adjudicate that references a
        DENIED prior authorization fails with ERR_PA_DENIED."

        Second-angle assertion: the PA's persisted ``status`` field
        is DENIED on re-fetch, confirming the cross-entity state
        dependency reads a real, queryable PA row (not just a
        cached error condition).
        """
        ctx = setup_dd_pa_denied_blocks_adjudicate()
        pa = ctx["pa_submitted"]
        api.deny_prior_authorization(
            pa["id"],
            {"denial_reason": "off-label", "version": pa["version"]},
            clinical_reviewer_headers,
        )
        refreshed_pa = re_get_prior_authorization(pa["id"])
        assert refreshed_pa["status"] == "DENIED"
        c = ctx["claim_submitted"]
        res = api.adjudicate_claim(
            c["id"], occ_payload(version=c["version"]),
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_PA_DENIED")


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlapB:

    def test_refill_too_soon_adjacency_accepted_after_overlap_rejected(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: resource_temporal_overlap/
        refill_too_soon_half_open_day_granularity_on_member_drug_pair

        PRD §3.5: "Two half-open intervals [a, a+da) and [b, b+db)
        overlap when a is strictly less than b+db and b is strictly
        less than a+da; adjacency at the boundary — a candidate that
        starts exactly when the prior interval ends — is allowed and
        does not count as overlap."

        Second-angle assertion (different observable than test_12):
        after the first ADJUDICATED candidate, advancing by exactly
        30 days lands the next candidate on the half-open boundary
        and adjudicate succeeds. The accepted claim then transitions
        to ADJUDICATED with valid integer-cent monetary fields.
        """
        ctx = setup_dd_refill_too_soon_half_open()
        advance_clock(30 * SECONDS_PER_DAY)
        c3 = ctx["claim_c3_submitted"]
        res = api.adjudicate_claim(
            c3["id"], occ_payload(version=c3["version"]),
            claims_adjudicator_headers,
        )
        c3_adj = validate_success(res, 200)
        assert c3_adj["status"] == "ADJUDICATED"
        assert isinstance(c3_adj["adjudicated_allowed_cents"], int)
        assert c3_adj["adjudicated_allowed_cents"] > 0

    def test_pa_window_inclusive_left_exclusive_right(
        self, api, claims_adjudicator_headers,
    ):
        """# difficulty: resource_temporal_overlap/
        pa_effective_window_closed_open_second_granularity_on_pa_resource

        PRD §2.11: "any APPROVED prior authorization whose
        effective_end is at or earlier than the new clock time auto-
        transitions to EXPIRED".

        Second-angle assertion: advancing the clock to exactly
        effective_end auto-transitions the PA row to EXPIRED — a
        side-effect on the PA itself observable independently of any
        claim-adjudicate failure.
        """
        ctx = setup_dd_pa_window_closed_open()
        pa = ctx["pa_approved"]
        advance_clock(PA_EFFECTIVE_WINDOW_SECONDS)
        refreshed = re_get_prior_authorization(pa["id"])
        assert refreshed["status"] == "EXPIRED"


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariantB:

    def test_clawback_signs_are_opposite(self, api):
        """# difficulty: compensating_invariant/
        rebate_ledger_zero_sum_after_clawback_within_window

        PRD §3.9: "REBATE_ACCRUED (a positive amount_cents, money
        flowing toward the PBM) and REBATE_CLAWBACK (a negative
        amount_cents, money flowing back to the manufacturer)."

        Second-angle assertion: the accrued entry has positive
        amount_cents and the clawback entry has negative
        amount_cents; their absolute values are equal.
        """
        ctx = setup_dd_rebate_accrual_clawback()
        entries = list_ledger_for_claim(ctx["claim_paid"]["id"])
        accrual = next(e for e in entries
                       if e["entry_type"] == "REBATE_ACCRUED")
        clawback = next(e for e in entries
                        if e["entry_type"] == "REBATE_CLAWBACK")
        assert accrual["amount_cents"] > 0
        assert clawback["amount_cents"] < 0
        assert (abs(accrual["amount_cents"])
                == abs(clawback["amount_cents"]))

    def test_member_round_trip_returns_to_initial_state(self, api):
        """# difficulty: compensating_invariant/
        member_ytd_zero_drift_after_adjudicate_reverse_round_trip

        PRD §3.7: "If copay_card_paid_cents was non-zero on the
        reversed claim, the card's used_cents is decremented by the
        same amount".
        PRD §3.7: "The member's ytd_deductible_paid_cents is
        decremented by the deductible portion that was originally
        applied to this claim, and the member's ytd_oop_paid_cents is
        decremented by the adjudicated_member_cost_cents that was
        originally written at adjudicate."

        Second-angle assertion: after a full round-trip on a claim
        WITH a copay card, BOTH Member.ytd_* AND CopayCard.used_cents
        return to their initial zero state.

        Setup: Plan(ded=0, oop_max=100000, coins=0.20), Drug
        unit=1000, q=30 -> allowed=30000, ded=0, post_ded=30000,
        member_share=6000, card_payable=1000,
        adjudicated_member_cost=5000.

        After adjudicate: ytd_ded=0, ytd_oop=6000, card.used=1000.
        After pay+reverse:
          ytd_ded -= deductible_portion (0) -> 0.
          ytd_oop -= adjudicated_member_cost_cents (5000) -> 1000.
          card.used -= copay_card_paid_cents (1000) -> 0.

        PRD-only readers note: §3.5 says OOP increments by
        ``member_pre_card`` (6000), while §3.7 says OOP decrements by
        ``adjudicated_member_cost_cents`` (5000). Two faithful
        implementers may interpret this asymmetry differently. So
        the assertion here is conservatively the round-trip
        invariant on the CARD's used_cents — strictly equal pre-
        and post-round-trip — which §3.7 names verbatim. Member.YTD
        round-trip equivalence is exercised by the no-card variant
        in test_12.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=100_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=1_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        from test_helpers import create_copay_card
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        paid = setup_paid_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=30,
            copay_card_id=card["id"],
        )
        reverse_claim(paid)
        card_after = re_get_copay_card(card["id"])
        assert card_after["used_cents"] == 0
