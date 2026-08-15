"""Queue A (difficulty design) translations — the deepest claims of the PRD.

Each instance from the difficulty design index gets at least two tests. Every
test docstring carries a verbatim PRD citation plus its `Design: Difficulty/...`
tag on the final line.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_index,
    activate_program,
    approve_claim,
    create_and_bind_treaty,
    create_bound_policy,
    create_index,
    create_policyholder,
    create_program,
    create_quoted_policy,
    create_station,
    create_verified_event_with_claim,
    find_event_for_window,
    get_success_data,
    ingest_observation,
    list_claims_for_event,
    list_claims_for_policy,
    make_treasury_officer_headers,
    setup_active_program,
    setup_approved_claim,
    setup_paid_claim,
    setup_program_with_bound_policy,
    validate_error,
    validate_success,
    verify_event,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["program_manager_headers"]
ACT = TEST_USERS["actuary_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
TRE = TEST_USERS["treasury_officer_headers"]
FRA = TEST_USERS["fraud_analyst_headers"]
DOPS = TEST_USERS["data_operations_headers"]
SVC = TEST_USERS["servicing_agent_headers"]

TIERS_3 = [
    {"tier": 1, "threshold_value": 50, "payout_fraction": 0.25},
    {"tier": 2, "threshold_value": 30, "payout_fraction": 0.5},
    {"tier": 3, "threshold_value": 20, "payout_fraction": 1.0},
]
TIERS_2 = [
    {"tier": 1, "threshold_value": 50, "payout_fraction": 0.25},
    {"tier": 2, "threshold_value": 30, "payout_fraction": 0.5},
]
TIERS_1 = [{"tier": 1, "threshold_value": 50, "payout_fraction": 0.25}]


# ===========================================================================
# Rule dual_variant_calc — payout_provisional_forward_vs_final_chronological_capped
# ===========================================================================

class TestDualVariantPayout:
    def _setup_two_claims(self, api):
        """si 2,000,000 policy; claim1 approved at tier 3 (final = 2,000,000,
        consuming the full per-coverage-year cap); claim2 generated at tier 2
        from a second window in the same coverage year."""
        stack = setup_program_with_bound_policy(
            sum_insured_cents=2_000_000, trigger_thresholds=TIERS_3
        )
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        st_id = stack["station"]["id"]

        # Claim 1: tier-3 event (15mm breaches all three tiers) -> final 2,000,000.
        ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 15)
        ev1 = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, ev1["id"])
        claim1 = list_claims_for_event(prog_id, ev1["id"])[0]
        claim1 = approve_claim(prog_id, claim1["id"], "adjuster-1")
        assert claim1["final_payout_cents"] == 2_000_000

        # Claim 2: second window at 30mm -> tier 2 -> provisional 1,000,000.
        ingest_observation(prog_id, idx_id, st_id, "2026-07-31", 30)
        ev2 = find_event_for_window(prog_id, idx_id, "2026-07-31")
        verify_event(prog_id, idx_id, ev2["id"])
        claim2 = list_claims_for_event(prog_id, ev2["id"])[0]
        return stack, claim2

    def test_provisional_is_forward_looking_uncapped(self, api):
        """PRD §3.6: "Each generated claim opens in `GENERATED` status, linked to
        its `policy_id` and the `trigger_event_id` that spawned it, with
        `tier_applied` defaulted to the event's `max_tier_breached`,
        `ceded_recovery_cents` at zero, and `provisional_payout_cents` computed
        forward-looking: the policy's `sum_insured_cents` multiplied by the
        `payout_fraction` of `tier_applied`, rounded half-up to a whole cent,
        with no regard to any other claim of the same policy in the same
        coverage year."

        Design: Difficulty/dual_variant_calc/payout_provisional_forward_vs_final_chronological_capped
        """
        stack, claim2 = self._setup_two_claims(api)
        assert claim2["tier_applied"] == 2
        assert claim2["provisional_payout_cents"] == 1_000_000, (
            "provisional must be si 2,000,000 x tier-2 fraction 0.50, uncapped, "
            f"even though a prior claim consumed the year's cap; got "
            f"{claim2['provisional_payout_cents']}"
        )

    def test_final_is_chronological_capped_at_zero(self, api):
        """PRD §3.7: "It then computes the uncapped amount — `sum_insured_cents`
        multiplied by the `payout_fraction` of `tier_applied`, rounded half-up to
        a whole cent — and sets `final_payout_cents` to the smaller of that
        uncapped amount and the remaining per-policy headroom, namely
        `sum_insured_cents` minus the prior sum, with the headroom floored at
        zero."

        Design: Difficulty/dual_variant_calc/payout_provisional_forward_vs_final_chronological_capped
        """
        stack, claim2 = self._setup_two_claims(api)
        prog_id = stack["program"]["id"]
        approved = approve_claim(prog_id, claim2["id"], "adjuster-1")
        assert approved["status"] == "APPROVED"
        assert approved["final_payout_cents"] == 0, (
            "final = min(1,000,000, max(0, 2,000,000 - 2,000,000)) = 0; got "
            f"{approved['final_payout_cents']}"
        )
        assert approved["final_payout_cents"] != approved["provisional_payout_cents"]


# ===========================================================================
# Rule dual_variant_calc — premium_loading_vs_cession_rounding_divergence
# ===========================================================================

class TestPremiumVsCessionRounding:
    def _setup(self, api):
        program = create_program(
            program_code="PRG-DV2", peril_type="WINDSPEED",
            regulatory_classification="SURPLUS_LINES",
        )
        station = create_station(program["id"])
        index = create_index(
            program["id"],
            index_code="IDX-WIND-2", measurement_unit="m/s",
            trigger_thresholds=[{"tier": 1, "threshold_value": 50, "payout_fraction": 1.0}],
            historical_breach_frequency=0.1, expected_loss_ratio=0.5,
        )
        activate_index(program["id"], index["id"])
        program = activate_program(program["id"])
        create_and_bind_treaty(
            program["id"], treaty_name="TR-33", ceded_percentage=33,
            attachment_point_cents=0, treaty_limit_cents=10_000_000,
        )
        holder = create_policyholder(program["id"])
        # Policy A: the premium trap case (tax on loaded, not pure).
        pol_a, inv_a = create_bound_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=1_000_000
        )
        # Policy B: si 333,333 claim to expose per-treaty rounding.
        pol_b, inv_b = create_bound_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=333_333
        )
        ingest_observation(program["id"], index["id"], station["id"], "2026-06-30", 40)
        event = find_event_for_window(program["id"], index["id"], "2026-06-30")
        verify_event(program["id"], index["id"], event["id"])
        claim_b = [c for c in list_claims_for_event(program["id"], event["id"])
                   if c["policy_id"] == pol_b["id"]][0]
        claim_b = approve_claim(program["id"], claim_b["id"], "adjuster-1")
        return program, pol_a, claim_b

    def test_premium_loading_then_tax_order(self, api):
        """PRD §3.5: "The program's `regulatory_classification` then selects an
        expense loading — 25% for `ADMITTED_INSURANCE`, 35% for `SURPLUS_LINES`,
        15% for `DERIVATIVE_CONTRACT` — and `premium_cents` is the pure premium
        multiplied by one plus that loading rate, rounded half-up to a whole
        cent. Finally, tax is levied on the loaded premium, never on the pure
        premium: `premium_tax_cents` is `premium_cents` multiplied by the
        classification's tax rate — 2% for `ADMITTED_INSURANCE`, 5% for
        `SURPLUS_LINES`, and 0% for `DERIVATIVE_CONTRACT` — rounded half-up to a
        whole cent."

        Design: Difficulty/dual_variant_calc/premium_loading_vs_cession_rounding_divergence
        """
        _, pol_a, _ = self._setup(api)
        assert pol_a["premium_cents"] == 67_500, (
            f"pure 1,000,000 x 0.10 x 0.50 = 50,000; x1.35 SURPLUS loading = 67,500; "
            f"got {pol_a['premium_cents']}"
        )
        assert pol_a["premium_tax_cents"] == 3_375, (
            f"5% of the loaded 67,500, not of the pure 50,000; got "
            f"{pol_a['premium_tax_cents']}"
        )

    def test_cession_rounds_per_treaty_then_sums(self, api):
        """PRD §2.7: "First, reinsurance cession rounds **per treaty** — each
        treaty's share is rounded half-up to whole cents before the per-treaty
        shares are summed into the claim's ceded total; the sum is never rounded
        after the fact."
        PRD §3.7: "its final status is `RECOVERY_CEDED` when any amount was
        ceded, `PAID` when none was."

        Design: Difficulty/dual_variant_calc/premium_loading_vs_cession_rounding_divergence
        """
        program, _, claim_b = self._setup(api)
        prog_id = program["id"]
        assert claim_b["final_payout_cents"] == 333_333
        released = validate_success(api.release_payment(
            prog_id, claim_b["id"], make_treasury_officer_headers("treasury-9")
        ))
        assert released["ceded_recovery_cents"] == 110_000, (
            f"round_half_up(333,333 x 33/100) per treaty = 110,000; got "
            f"{released['ceded_recovery_cents']}"
        )
        assert released["net_payment_cents"] == 223_333
        assert released["status"] == "RECOVERY_CEDED"


# ===========================================================================
# Rule combinatorial_formula — premium_pricing_mode_a_multibranch_formula
# ===========================================================================

class TestPremiumPricingBranches:
    def _quote(self, classification):
        program, station, index = setup_active_program(
            regulatory_classification=classification
        )
        holder = create_policyholder(program["id"])
        policy, _ = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        return policy

    def test_admitted_branch_loading_and_tax(self, api):
        """PRD §3.5: "The pure premium is `sum_insured_cents` multiplied by the
        index's `historical_breach_frequency` and then by its
        `expected_loss_ratio`. The program's `regulatory_classification` then
        selects an expense loading — 25% for `ADMITTED_INSURANCE`, 35% for
        `SURPLUS_LINES`, 15% for `DERIVATIVE_CONTRACT` — and `premium_cents` is
        the pure premium multiplied by one plus that loading rate, rounded
        half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/premium_pricing_mode_a_multibranch_formula
        """
        policy = self._quote("ADMITTED_INSURANCE")
        assert policy["premium_cents"] == 300_000, (
            f"pure 240,000 x 1.25 = 300,000; got {policy['premium_cents']}"
        )
        assert policy["premium_tax_cents"] == 6_000, (
            f"2% of the loaded 300,000; got {policy['premium_tax_cents']}"
        )

    def test_surplus_branch_diverges_on_classification_alone(self, api):
        """PRD §3.5: "Finally, tax is levied on the loaded premium, never on the
        pure premium: `premium_tax_cents` is `premium_cents` multiplied by the
        classification's tax rate — 2% for `ADMITTED_INSURANCE`, 5% for
        `SURPLUS_LINES`, and 0% for `DERIVATIVE_CONTRACT` — rounded half-up to a
        whole cent."

        Design: Difficulty/combinatorial_formula/premium_pricing_mode_a_multibranch_formula
        """
        admitted = self._quote("ADMITTED_INSURANCE")
        surplus = self._quote("SURPLUS_LINES")
        assert surplus["premium_cents"] == 324_000, (
            f"pure 240,000 x 1.35 = 324,000; got {surplus['premium_cents']}"
        )
        assert surplus["premium_tax_cents"] == 16_200, (
            f"5% of the loaded 324,000; got {surplus['premium_tax_cents']}"
        )
        assert admitted["premium_cents"] != surplus["premium_cents"], (
            "identical pure-premium inputs must price differently purely from the "
            "classification branch"
        )


# ===========================================================================
# Rule combinatorial_formula — cession_waterfall_mode_b_rounding_order
# ===========================================================================

class TestCessionWaterfallRoundingOrder:
    def _setup(self, api):
        program, station, index = setup_active_program(
            program_code="PRG-CF-B", peril_type="EARTHQUAKE_MAGNITUDE",
            regulatory_classification="DERIVATIVE_CONTRACT",
        )
        prog_id = program["id"]
        # Rebuild the index with payout_fraction=1.0 so final = sum_insured,
        # exposing the per-treaty rounding on the raw cession arithmetic.
        # (Default fixture uses payout_fraction 0.25 which would divide all
        # expected cessions by 4.)
        idx_resp = api.create_index_definition(
            prog_id,
            {"index_code": "IDX-CFB2", "measurement_unit": "mm",
             "aggregation_window_days": 30, "data_source_agreement_ref": "DSA-CFB2",
             "source_priority_mode": "STATION_PRIMARY",
             "trigger_thresholds": [{"tier": 1, "threshold_value": 50, "payout_fraction": 1.0}],
             "strike_direction": "BELOW",
             "historical_breach_frequency": 0.2, "expected_loss_ratio": 0.6},
            ACT,
        )
        index = get_success_data(idx_resp)
        activate_index(prog_id, index["id"])
        t1 = create_and_bind_treaty(
            prog_id, treaty_name="T1-33", ceded_percentage=33,
            attachment_point_cents=0, treaty_limit_cents=10_000_000,
        )
        t2 = create_and_bind_treaty(
            prog_id, treaty_name="T2-10", ceded_percentage=10,
            attachment_point_cents=100_000, treaty_limit_cents=10_000_000,
        )
        holder = create_policyholder(prog_id)
        policy, _ = create_bound_policy(
            prog_id, holder["id"], index["id"], sum_insured_cents=333_333
        )
        ingest_observation(prog_id, index["id"], station["id"], "2026-06-30", 40)
        event = find_event_for_window(prog_id, index["id"], "2026-06-30")
        verify_event(prog_id, index["id"], event["id"])
        claim = list_claims_for_policy(prog_id, policy["id"])[0]
        claim = approve_claim(prog_id, claim["id"], "adjuster-1")
        return prog_id, t1, t2, claim

    def test_per_treaty_recovered_amounts_individually_rounded(self, api):
        """PRD §3.7: "For each treaty, the excess over attachment is the claim's
        `final_payout_cents` minus the treaty's `attachment_point_cents`, floored
        at zero; the gross cession is that excess multiplied by the treaty's
        `ceded_percentage` and divided by 100, rounded half-up to a whole cent;
        the treaty's remaining room is its `treaty_limit_cents` minus its
        `recovered_to_date_cents`; and the amount actually ceded to that treaty
        is the smaller of the gross cession and the remaining room, floored at
        zero. Each treaty's `recovered_to_date_cents` grows by its ceded share"

        Design: Difficulty/combinatorial_formula/cession_waterfall_mode_b_rounding_order
        """
        prog_id, t1, t2, claim = self._setup(api)
        validate_success(api.release_payment(
            prog_id, claim["id"], make_treasury_officer_headers("treasury-1")
        ))
        t1_after = validate_success(api.get_treaty(prog_id, t1["id"], PM))
        t2_after = validate_success(api.get_treaty(prog_id, t2["id"], PM))
        assert t1_after["recovered_to_date_cents"] == 110_000, (
            f"rhu(333,333 x 0.33) = 110,000 per-treaty; got "
            f"{t1_after['recovered_to_date_cents']}"
        )
        assert t2_after["recovered_to_date_cents"] == 23_333, (
            f"rhu((333,333 - 100,000) x 0.10) = rhu(23,333.30) = 23,333; got "
            f"{t2_after['recovered_to_date_cents']}"
        )

    def test_claim_ceded_total_is_sum_of_per_treaty_rounded_shares(self, api):
        """PRD §3.7: "The claim's `ceded_recovery_cents` is the sum of the
        per-treaty cessions (rounded per treaty before summing, per §2.7), its
        `net_payment_cents` is `final_payout_cents` minus `ceded_recovery_cents`,
        and its final status is `RECOVERY_CEDED` when any amount was ceded,
        `PAID` when none was."

        Design: Difficulty/combinatorial_formula/cession_waterfall_mode_b_rounding_order
        """
        prog_id, _, _, claim = self._setup(api)
        released = validate_success(api.release_payment(
            prog_id, claim["id"], make_treasury_officer_headers("treasury-1")
        ))
        assert released["ceded_recovery_cents"] == 133_333, (
            f"110,000 + 23,333 per-treaty rounded shares; got "
            f"{released['ceded_recovery_cents']}"
        )
        assert released["net_payment_cents"] == 200_000
        assert released["status"] == "RECOVERY_CEDED"


# ===========================================================================
# Rule non_linear_state_machine — dispute_case_cyclic_open_awaiting_open
# ===========================================================================

class TestDisputeCycle:
    def test_open_awaiting_open_cycle_completes(self, api):
        """PRD §3.8: "A `ClaimsAdjuster` who needs more from the customer sends
        the dispute from `OPEN` to `AWAITING_CUSTOMER` (any other state draws
        `ERR_DISPUTE_NOT_OPEN`); the `ServicingAgent` returns it to `OPEN` by
        submitting the requested information (which requires `AWAITING_CUSTOMER`,
        else `ERR_DISPUTE_NOT_AWAITING`); and this cycle between `OPEN` and
        `AWAITING_CUSTOMER` may repeat as many times as the exchange requires."

        Design: Difficulty/non_linear_state_machine/dispute_case_cyclic_open_awaiting_open
        """
        stack, _, claim = setup_paid_claim(trigger_thresholds=TIERS_2)
        prog_id = stack["program"]["id"]
        dispute = validate_success(api.create_dispute(
            prog_id, claim["id"],
            {"dispute_reason": "BASIS_RISK_MISMATCH", "claimed_tier": 2}, SVC,
        ), expected_status=201)
        awaiting = validate_success(api.request_dispute_info(
            prog_id, claim["id"], dispute["id"], ADJ
        ))
        assert awaiting["status"] == "AWAITING_CUSTOMER"
        reopened = validate_success(api.submit_dispute_info(
            prog_id, claim["id"], dispute["id"], SVC
        ))
        assert reopened["status"] == "OPEN", (
            f"cycle must return to the origin state OPEN; got {reopened['status']}"
        )

    def test_cycle_repeats_without_limit(self, api):
        """PRD §3.8: "and this cycle between `OPEN` and `AWAITING_CUSTOMER` may
        repeat as many times as the exchange requires."

        Design: Difficulty/non_linear_state_machine/dispute_case_cyclic_open_awaiting_open
        """
        stack, _, claim = setup_paid_claim(trigger_thresholds=TIERS_2)
        prog_id = stack["program"]["id"]
        dispute = validate_success(api.create_dispute(
            prog_id, claim["id"],
            {"dispute_reason": "BASIS_RISK_MISMATCH", "claimed_tier": 2}, SVC,
        ), expected_status=201)
        for _ in range(2):
            validate_success(api.request_dispute_info(prog_id, claim["id"], dispute["id"], ADJ))
            back = validate_success(api.submit_dispute_info(prog_id, claim["id"], dispute["id"], SVC))
            assert back["status"] == "OPEN"
        # A third request-info after two full loops still succeeds.
        third = validate_success(api.request_dispute_info(
            prog_id, claim["id"], dispute["id"], ADJ
        ))
        assert third["status"] == "AWAITING_CUSTOMER"


# ===========================================================================
# Rule non_linear_state_machine — parametric_policy_parallel_dimensions_independent
# ===========================================================================

class TestPolicyParallelDimensions:
    def test_posture_independent_at_quote_and_moves_on_approve(self, api):
        """PRD §3.5: "The new policy opens with `lifecycle_status` `QUOTED` and
        `settlement_posture` `CLEAR`"
        PRD §3.5: "The settlement posture evolves in parallel with, and
        independently of, the lifecycle. A policy starts `CLEAR`; the moment any
        of its claims enters `APPROVED` or `FRAUD_HOLD`, the posture bubbles up
        to `PAYMENT_PENDING`"

        Design: Difficulty/non_linear_state_machine/parametric_policy_parallel_dimensions_independent
        """
        stack = setup_program_with_bound_policy(trigger_thresholds=TIERS_1)
        prog_id = stack["program"]["id"]
        # At quote time the two dims start independently.
        quoted, _ = create_quoted_policy(
            prog_id, stack["holder"]["id"], stack["index"]["id"]
        )
        assert quoted["lifecycle_status"] == "QUOTED"
        assert quoted["settlement_posture"] == "CLEAR"

        _, claims = create_verified_event_with_claim(stack)
        approve_claim(prog_id, claims[0]["id"], "adjuster-1")
        mid = validate_success(api.get_policy(
            prog_id, stack["holder"]["id"], stack["policy"]["id"], UW
        ))
        assert mid["lifecycle_status"] == "BOUND"
        assert mid["settlement_posture"] == "PAYMENT_PENDING", (
            f"approve must bubble the posture; got {mid['settlement_posture']}"
        )

    def test_cancel_guarded_by_posture_and_posture_settles_after_release(self, api):
        """PRD §3.5: "Cancellation is available to the `Underwriter` only while
        the commitment is still clean: the policy must be `BOUND`
        (`ERR_POLICY_NOT_BOUND`), its `settlement_posture` must not be
        `PAYMENT_PENDING` (`ERR_POLICY_PAYMENT_IN_FLIGHT`)"
        PRD §3.7: "if every claim of the policy has now reached a terminal state
        the policy's posture settles to `SETTLED_QUIET`."

        Design: Difficulty/non_linear_state_machine/parametric_policy_parallel_dimensions_independent
        """
        stack, _, claim = setup_approved_claim(trigger_thresholds=TIERS_1)
        prog_id = stack["program"]["id"]
        holder_id = stack["holder"]["id"]
        pol_id = stack["policy"]["id"]

        err = api.cancel_policy(prog_id, holder_id, pol_id, UW)
        validate_error(err, ApiErrorId.ERR_POLICY_PAYMENT_IN_FLIGHT)

        validate_success(api.release_payment(
            prog_id, claim["id"], make_treasury_officer_headers("treasury-1")
        ))
        after = validate_success(api.get_policy(prog_id, holder_id, pol_id, UW))
        assert after["settlement_posture"] == "SETTLED_QUIET"
        assert after["lifecycle_status"] == "BOUND", (
            "settlement of the claim does not move the lifecycle dimension"
        )


# ===========================================================================
# Rule transitive_cascade — observation_revision_annuls_event_cascades_claims_and_posture
# ===========================================================================

class TestAnnulmentCascade:
    def _setup_approved_then_revision(self, api):
        stack = setup_program_with_bound_policy(trigger_thresholds=TIERS_1)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        st_id = stack["station"]["id"]
        obs1 = ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 40)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, event["id"])
        claim = list_claims_for_policy(prog_id, stack["policy"]["id"])[0]
        claim = approve_claim(prog_id, claim["id"], "adjuster-1")
        revision = ingest_observation(
            prog_id, idx_id, st_id, "2026-06-30", 80,
            supersedes_observation_id=obs1["id"],
        )
        return stack, obs1, revision, event, claim

    def test_revision_flips_prior_row_effectiveness(self, api):
        """PRD §3.3: "Each row also carries a computed `is_effective` flag: true
        unless and until a later revision for the same station and window
        supersedes it, at which point the prior row's `is_effective` flips to
        false."

        Design: Difficulty/transitive_cascade/observation_revision_annuls_event_cascades_claims_and_posture
        """
        stack, obs1, revision, _, _ = self._setup_approved_then_revision(api)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        rows = get_success_data(api.list_observations(
            prog_id, idx_id, DOPS,
            params={"station_id": stack["station"]["id"], "window_end_date": "2026-06-30"},
        ))
        by_id = {r["id"]: r for r in rows}
        assert by_id[obs1["id"]]["is_effective"] is False
        assert by_id[revision["id"]]["is_effective"] is True

    def test_annulment_spares_approved_claim(self, api):
        """PRD §3.6: "When a late observation revision drops a `VERIFIED` event's
        recomputed `max_tier_breached` to 0, the system moves the event to
        `ANNULLED` without any client call. Compensation follows immediately:
        every claim generated from the event that still stands in `GENERATED` or
        `ADJUSTED` is declined, while claims already `APPROVED` are deliberately
        left standing — money that far committed must be clawed back through the
        dispute process of §3.8, not auto-voided."

        Design: Difficulty/transitive_cascade/observation_revision_annuls_event_cascades_claims_and_posture
        """
        stack, _, _, event, claim = self._setup_approved_then_revision(api)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        ev = validate_success(api.get_trigger_event(prog_id, idx_id, event["id"], ADJ))
        assert ev["status"] == "ANNULLED", (
            f"revised blend 80 breaches nothing under BELOW t1<=50; got {ev['status']}"
        )
        claim_after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert claim_after["status"] == "APPROVED", (
            "the compensation cascade touches only GENERATED/ADJUSTED claims"
        )

    def test_annulment_declines_unapproved_claim(self, api):
        """PRD §3.6: "Compensation follows immediately: every claim generated
        from the event that still stands in `GENERATED` or `ADJUSTED` is
        declined"

        Design: Difficulty/transitive_cascade/observation_revision_annuls_event_cascades_claims_and_posture
        """
        stack = setup_program_with_bound_policy(trigger_thresholds=TIERS_1)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        st_id = stack["station"]["id"]
        obs1 = ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 40)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, event["id"])
        claim = list_claims_for_policy(prog_id, stack["policy"]["id"])[0]
        assert claim["status"] == "GENERATED"
        ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 80,
                           supersedes_observation_id=obs1["id"])
        ev = validate_success(api.get_trigger_event(prog_id, idx_id, event["id"], ADJ))
        assert ev["status"] == "ANNULLED"
        claim_after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert claim_after["status"] == "DECLINED"


# ===========================================================================
# Rule transitive_cascade — blacklist_cascades_claims_voided
# ===========================================================================

class TestBlacklistCascade:
    def _setup_two_policies_one_approved(self, api):
        stack = setup_program_with_bound_policy(trigger_thresholds=TIERS_1)
        prog_id = stack["program"]["id"]
        holder_id = stack["holder"]["id"]
        idx_id = stack["index"]["id"]
        # Second policy on the same holder/index, also BOUND.
        pol2, _ = create_bound_policy(
            prog_id, holder_id, idx_id, sum_insured_cents=1_000_000
        )
        ingest_observation(prog_id, idx_id, stack["station"]["id"], "2026-06-30", 40)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, event["id"])
        claim1 = list_claims_for_policy(prog_id, stack["policy"]["id"])[0]
        claim2 = list_claims_for_policy(prog_id, pol2["id"])[0]
        claim1 = approve_claim(prog_id, claim1["id"], "adjuster-1")
        return stack, claim1, claim2

    def test_blacklist_voids_generated_claim(self, api):
        """PRD §3.4: "Blacklisting an `ACTIVE` policyholder cascades across the
        book: every claim of that policyholder standing in `GENERATED` or
        `ADJUSTED` is voided, while claims already `APPROVED` are unaffected —
        they are committed to treasury and must run their course."

        Design: Difficulty/transitive_cascade/blacklist_cascades_claims_voided
        """
        stack, _, claim2 = self._setup_two_policies_one_approved(api)
        prog_id = stack["program"]["id"]
        holder = validate_success(api.blacklist_policyholder(
            prog_id, stack["holder"]["id"], FRA
        ))
        assert holder["status"] == "BLACKLISTED"
        claim2_after = validate_success(api.get_claim(prog_id, claim2["id"], FRA))
        assert claim2_after["status"] == "VOIDED"

    def test_blacklist_spares_approved_claim(self, api):
        """PRD §3.4: "every claim of that policyholder standing in `GENERATED` or
        `ADJUSTED` is voided, while claims already `APPROVED` are unaffected —
        they are committed to treasury and must run their course."

        Design: Difficulty/transitive_cascade/blacklist_cascades_claims_voided
        """
        stack, claim1, _ = self._setup_two_policies_one_approved(api)
        prog_id = stack["program"]["id"]
        validate_success(api.blacklist_policyholder(prog_id, stack["holder"]["id"], FRA))
        claim1_after = validate_success(api.get_claim(prog_id, claim1["id"], FRA))
        assert claim1_after["status"] == "APPROVED"


# ===========================================================================
# Rule priority_pair_validation_conflict —
#   state_vs_business_fiscal_on_bind_unpaid_and_over_exposure
# ===========================================================================

class TestBindPriorityConflict:
    def _setup_unpaid_over_exposure(self, api):
        program, station, index = setup_active_program(exposure_limit_cents=1_000_000)
        holder = create_policyholder(program["id"])
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        return program, holder, policy


# ===========================================================================
# Rule priority_pair_validation_conflict —
#   business_safety_vs_business_referential_on_observation_and_sod
# ===========================================================================

class TestSodAndCrossReference:
    def test_release_by_approving_user_rejected_sod(self, api):
        """PRD §2.9: "At release time, the releasing officer's `X-User-ID` must
        differ from the recorded `approver_user_id`; if the same operator
        identifier attempts both steps, the release is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_observation_and_sod
        """
        stack, _, claim = setup_approved_claim(approver_user_id="adjuster-1")
        prog_id = stack["program"]["id"]
        resp = api.release_payment(
            prog_id, claim["id"], make_treasury_officer_headers("adjuster-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        after = validate_success(api.get_claim(prog_id, claim["id"], TRE))
        assert after["status"] == "APPROVED", (
            "an SoD rejection is side-effect-free; the claim stays APPROVED"
        )

    def test_observation_referencing_other_programs_station_rejected(self, api):
        """PRD §3.3: "the referenced station must actually belong to the program
        (`ERR_CROSS_REFERENCE_INVALID`)"
        PRD §2.6: "7. Cross-reference linkability — that a referenced index
        belongs to the program, a referenced station belongs to the program, or
        a claim belongs to a policy of a policyholder of the program
        (`ERR_CROSS_REFERENCE_INVALID`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_observation_and_sod
        """
        stack_a = setup_program_with_bound_policy(trigger_thresholds=TIERS_1)
        prog_b = create_program(program_code="PRG-PP2B", peril_type="WINDSPEED")
        station_b = create_station(prog_b["id"], station_code="ST-B")
        resp = api.create_observation(
            stack_a["program"]["id"], stack_a["index"]["id"],
            {"station_id": station_b["id"],
             "window_end_date": "2026-07-31", "measured_value": 10},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_INVALID, expected_status=422)


# ===========================================================================
# Rule boundary_precision_check — threshold_inclusive_boundary_at_exact_tier_value
# ===========================================================================

class TestTierBoundaryInclusive:
    def test_exact_threshold_breaches_tier_below(self, api):
        """PRD §3.3: "The blended value is tested against the index's tiers.
        Under `BELOW` direction, a tier breaches when the blend is less than or
        equal to its `threshold_value`; under `ABOVE`, when the blend is greater
        than or equal. The boundary is inclusive — a value exactly at the
        threshold breaches the tier."

        Design: Difficulty/boundary_precision_check/threshold_inclusive_boundary_at_exact_tier_value
        """
        stack = setup_program_with_bound_policy(trigger_thresholds=TIERS_2)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        ingest_observation(prog_id, idx_id, stack["station"]["id"], "2026-06-30", 30)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verified = verify_event(prog_id, idx_id, event["id"])
        assert verified["blended_index_value"] == 30
        assert verified["max_tier_breached"] == 2, (
            f"exactly 30 must breach the 30mm tier under inclusive <=; got tier "
            f"{verified['max_tier_breached']}"
        )

    def test_claim_at_boundary_uses_higher_tier_fraction(self, api):
        """PRD §3.6: "`provisional_payout_cents` computed forward-looking: the
        policy's `sum_insured_cents` multiplied by the `payout_fraction` of
        `tier_applied`, rounded half-up to a whole cent"
        PRD §3.3: "The boundary is inclusive — a value exactly at the threshold
        breaches the tier."

        Design: Difficulty/boundary_precision_check/threshold_inclusive_boundary_at_exact_tier_value
        """
        stack = setup_program_with_bound_policy(
            sum_insured_cents=2_000_000, trigger_thresholds=TIERS_2
        )
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        ingest_observation(prog_id, idx_id, stack["station"]["id"], "2026-06-30", 30)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, event["id"])
        claim = list_claims_for_policy(prog_id, stack["policy"]["id"])[0]
        assert claim["tier_applied"] == 2
        assert claim["provisional_payout_cents"] == 1_000_000, (
            f"tier-2 fraction 0.50 on si 2,000,000, not the tier-1 500,000; got "
            f"{claim['provisional_payout_cents']}"
        )


# ===========================================================================
# Rule boundary_precision_check — treaty_exhaustion_exact_limit_boundary
# ===========================================================================

class TestTreatyExhaustionBoundary:
    def _setup(self, api):
        program, station, _default_idx = setup_active_program(
            program_code="PRG-BP2",
        )
        prog_id = program["id"]
        # Rebuild an index with payout_fraction=0.5 so final per claim =
        # 2,000,000 x 0.5 = 1,000,000; cession rhu((1,000,000 - 100,000) x 0.30)
        # = 270,000 == treaty limit exactly.
        index = create_index(
            prog_id, index_code="IDX-BP2-X",
            trigger_thresholds=[{"tier": 1, "threshold_value": 50, "payout_fraction": 0.5}],
        )
        activate_index(prog_id, index["id"])
        treaty = create_and_bind_treaty(
            prog_id, treaty_name="T-EXH", ceded_percentage=30,
            attachment_point_cents=100_000, treaty_limit_cents=270_000,
        )
        holder = create_policyholder(prog_id)
        pol1, _ = create_bound_policy(prog_id, holder["id"], index["id"],
                                      sum_insured_cents=2_000_000)
        pol2, _ = create_bound_policy(prog_id, holder["id"], index["id"],
                                      sum_insured_cents=2_000_000)
        ingest_observation(prog_id, index["id"], station["id"], "2026-06-30", 40)
        event = find_event_for_window(prog_id, index["id"], "2026-06-30")
        verify_event(prog_id, index["id"], event["id"])
        claim1 = approve_claim(prog_id, list_claims_for_policy(prog_id, pol1["id"])[0]["id"], "adjuster-1")
        claim2 = approve_claim(prog_id, list_claims_for_policy(prog_id, pol2["id"])[0]["id"], "adjuster-1")
        return prog_id, treaty, claim1, claim2

    def test_treaty_exhausts_on_exact_limit_equality(self, api):
        """PRD §3.7: "Each treaty's `recovered_to_date_cents` grows by its ceded
        share, and a treaty whose cumulative recovery reaches its
        `treaty_limit_cents` exactly is exhausted on the spot — its status
        becomes `EXHAUSTED` and it takes no further cessions."

        Design: Difficulty/boundary_precision_check/treaty_exhaustion_exact_limit_boundary
        """
        prog_id, treaty, claim1, _ = self._setup(api)
        validate_success(api.release_payment(
            prog_id, claim1["id"], make_treasury_officer_headers("treasury-1")
        ))
        after = validate_success(api.get_treaty(prog_id, treaty["id"], PM))
        assert after["recovered_to_date_cents"] == 270_000
        assert after["status"] == "EXHAUSTED", (
            f"equality at the limit flips status; got {after['status']}"
        )

    def test_exhausted_treaty_cedes_zero_to_next_claim(self, api):
        """PRD §3.7: "its status becomes `EXHAUSTED` and it takes no further
        cessions."
        PRD §3.7: "its `net_payment_cents` is `final_payout_cents` minus
        `ceded_recovery_cents`, and its final status is `RECOVERY_CEDED` when any
        amount was ceded, `PAID` when none was."

        Design: Difficulty/boundary_precision_check/treaty_exhaustion_exact_limit_boundary
        """
        prog_id, _, claim1, claim2 = self._setup(api)
        validate_success(api.release_payment(
            prog_id, claim1["id"], make_treasury_officer_headers("treasury-1")
        ))
        released2 = validate_success(api.release_payment(
            prog_id, claim2["id"], make_treasury_officer_headers("treasury-1")
        ))
        assert released2["ceded_recovery_cents"] == 0
        assert released2["status"] == "PAID"
        assert released2["net_payment_cents"] == 1_000_000


# ===========================================================================
# Rule cross_entity_state_dependency — policy_bind_gated_on_invoice_paid_state
# ===========================================================================

class TestBindGatedOnInvoicePaid:
    def _setup_partially_paid(self, api):
        program, station, index = setup_active_program()
        holder = create_policyholder(program["id"])
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        # Partial payment: 200,000 of 306,000.
        validate_success(api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 200_000}, SVC
        ))
        return program, holder, policy, invoice

    def test_bind_rejected_while_invoice_partially_paid(self, api):
        """PRD §3.5: "the policy's invoice must be `PAID` (`ERR_PREMIUM_NOT_PAID`,
        HTTP 402)"
        PRD §3.5: "coverage binds only when the invoice is fully paid by that due
        date."

        Design: Difficulty/cross_entity_state_dependency/policy_bind_gated_on_invoice_paid_state
        """
        program, holder, policy, _ = self._setup_partially_paid(api)
        resp = api.bind_policy(program["id"], holder["id"], policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PREMIUM_NOT_PAID, expected_status=402)

    def test_bind_succeeds_after_final_installment(self, api):
        """PRD §3.5: "Each accepted payment adds to `amount_paid_cents`; the
        invoice stands `PARTIALLY_PAID` while a balance remains and turns `PAID`
        the moment payments equal the billed amount."
        PRD §3.5: "On a successful bind the policy's `lifecycle_status` becomes
        `BOUND`"

        Design: Difficulty/cross_entity_state_dependency/policy_bind_gated_on_invoice_paid_state
        """
        program, holder, policy, invoice = self._setup_partially_paid(api)
        resp = api.bind_policy(program["id"], holder["id"], policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PREMIUM_NOT_PAID, expected_status=402)
        paid_invoice = validate_success(api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 106_000}, SVC
        ))
        assert paid_invoice["status"] == "PAID"
        assert paid_invoice["amount_paid_cents"] == 306_000
        bound = validate_success(api.bind_policy(
            program["id"], holder["id"], policy["id"], UW
        ))
        assert bound["lifecycle_status"] == "BOUND"


# ===========================================================================
# Rule cross_entity_state_dependency — claim_approve_gated_on_trigger_event_verified
# ===========================================================================

class TestClaimGatedOnEventVerified:
    def _setup_under_review_then_revision(self, api):
        stack = setup_program_with_bound_policy(trigger_thresholds=TIERS_1)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        st_id = stack["station"]["id"]
        obs1 = ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 40)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        get_success_data(api.open_event_review(prog_id, idx_id, event["id"], ADJ))
        # Late revision moves the blend out of breach while UNDER_REVIEW.
        ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 80,
                           supersedes_observation_id=obs1["id"])
        return stack, event

    def test_verify_fails_when_blend_no_longer_breaches(self, api):
        """PRD §3.6: "If the recomputed blend no longer breaches at least tier 1
        — whether because a late revision moved the index or because the
        effective set has gone empty — verification fails with
        `ERR_EVENT_NO_LONGER_BREACHING` (HTTP 409) and the event stays under
        review."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_on_trigger_event_verified
        """
        stack, event = self._setup_under_review_then_revision(api)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        resp = api.verify_event(prog_id, idx_id, event["id"], ADJ)
        validate_error(resp, ApiErrorId.ERR_EVENT_NO_LONGER_BREACHING, expected_status=409)
        after = validate_success(api.get_trigger_event(prog_id, idx_id, event["id"], ADJ))
        assert after["status"] == "UNDER_REVIEW", (
            "a failed verify must leave the event under review"
        )

    def test_no_claim_exists_while_event_never_verified(self, api):
        """PRD §3.6: "A successful verification moves the event to `VERIFIED` and
        fans out across the book. For every policy `BOUND` on this index whose
        coverage window — `policy_start_date` through `policy_end_date`, both
        inclusive — contains the event's `window_end_date`, the system generates
        exactly one claim"

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_on_trigger_event_verified
        """
        stack, event = self._setup_under_review_then_revision(api)
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        resp = api.verify_event(prog_id, idx_id, event["id"], ADJ)
        validate_error(resp, ApiErrorId.ERR_EVENT_NO_LONGER_BREACHING, expected_status=409)
        claims = list_claims_for_policy(prog_id, stack["policy"]["id"])
        assert claims == [], (
            f"claim generation is unreachable while the event never verifies; got {claims}"
        )


# ===========================================================================
# Rule resource_temporal_overlap — trigger_event_uniqueness_per_index_window
# ===========================================================================

class TestTriggerEventWindowUniqueness:
    def _setup_two_stations(self, api):
        program = create_program(program_code="PRG-TO1")
        st1 = create_station(program["id"], station_code="ST-1", reliability_weight=1.0)
        st2 = create_station(program["id"], station_code="ST-2", reliability_weight=0.5)
        index = create_index(program["id"], index_code="IDX-TO1")
        activate_index(program["id"], index["id"])
        program = activate_program(program["id"])
        holder = create_policyholder(program["id"])
        policy, _ = create_bound_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        return program, st1, st2, index

    def test_second_station_observation_does_not_mint_second_event(self, api):
        """PRD §3.3: "When the recomputed blend breaches tier 1 or higher and no
        trigger event yet exists for that index and window, the system creates a
        trigger event in `DETECTED` status"

        Design: Difficulty/resource_temporal_overlap/trigger_event_uniqueness_per_index_window
        """
        program, st1, st2, index = self._setup_two_stations(api)
        prog_id, idx_id = program["id"], index["id"]
        ingest_observation(prog_id, idx_id, st1["id"], "2026-06-30", 40)
        ingest_observation(prog_id, idx_id, st2["id"], "2026-06-30", 45)
        events = get_success_data(api.list_trigger_events_in_program(
            prog_id, ADJ, params={"index_definition_id": idx_id}
        ))
        assert len(events) == 1, (
            f"at most one trigger event per (index, window); got {len(events)}"
        )

    def test_second_station_reading_folds_into_same_blend(self, api):
        """PRD §3.3: "The blended value is then the weighted mean of the
        surviving rows — each `measured_value` multiplied by its station's
        `reliability_weight`, summed, and divided by the sum of those weights —
        rounded half-up to 4 decimal places."

        Design: Difficulty/resource_temporal_overlap/trigger_event_uniqueness_per_index_window
        """
        program, st1, st2, index = self._setup_two_stations(api)
        prog_id, idx_id = program["id"], index["id"]
        ingest_observation(prog_id, idx_id, st1["id"], "2026-06-30", 40)
        ingest_observation(prog_id, idx_id, st2["id"], "2026-06-30", 45)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verified = verify_event(prog_id, idx_id, event["id"])
        assert verified["blended_index_value"] == pytest.approx(41.6667, abs=0.0001), (
            f"(40*1.0 + 45*0.5)/1.5 = 41.6667 at 4dp; got "
            f"{verified['blended_index_value']}"
        )


# ===========================================================================
# Rule resource_temporal_overlap — observation_duplicate_window_rejected_requires_supersede
# ===========================================================================

class TestObservationRevisionSemantics:
    def _setup_two_stations(self, api):
        program = create_program(program_code="PRG-TO2")
        st1 = create_station(program["id"], station_code="ST-1", reliability_weight=1.0)
        st2 = create_station(program["id"], station_code="ST-2", reliability_weight=0.5)
        index = create_index(program["id"], index_code="IDX-TO2")
        activate_index(program["id"], index["id"])
        program = activate_program(program["id"])
        return program, st1, st2, index

    def test_duplicate_station_window_without_supersede_rejected(self, api):
        """PRD §3.3: "Deduplication is strict: a second observation for the same
        (`station_id`, `window_end_date`) pair must name the prior effective row
        in `supersedes_observation_id`, otherwise it is rejected with
        `ERR_DUPLICATE_OBSERVATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/observation_duplicate_window_rejected_requires_supersede
        """
        program, st1, st2, index = self._setup_two_stations(api)
        prog_id, idx_id = program["id"], index["id"]
        ingest_observation(prog_id, idx_id, st1["id"], "2026-06-30", 40)
        resp = api.create_observation(
            prog_id, idx_id,
            {"station_id": st1["id"], "window_end_date": "2026-06-30", "measured_value": 55},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OBSERVATION, expected_status=409)

    def test_same_window_other_station_and_proper_revision_accepted(self, api):
        """PRD §3.3: "Deduplication is strict: a second observation for the same
        (`station_id`, `window_end_date`) pair must name the prior effective row
        in `supersedes_observation_id`"
        PRD §3.3: "Each row also carries a computed `is_effective` flag: true
        unless and until a later revision for the same station and window
        supersedes it, at which point the prior row's `is_effective` flips to
        false."

        Design: Difficulty/resource_temporal_overlap/observation_duplicate_window_rejected_requires_supersede
        """
        program, st1, st2, index = self._setup_two_stations(api)
        prog_id, idx_id = program["id"], index["id"]
        obs1 = ingest_observation(prog_id, idx_id, st1["id"], "2026-06-30", 40)
        # Same window on a DIFFERENT station: accepted (occupation is per-station).
        obs2 = validate_success(api.create_observation(
            prog_id, idx_id,
            {"station_id": st2["id"], "window_end_date": "2026-06-30", "measured_value": 55},
            DOPS,
        ), expected_status=201)
        assert obs2["id"]
        # Proper revision naming the effective row: accepted and supersedes.
        obs3 = validate_success(api.create_observation(
            prog_id, idx_id,
            {"station_id": st1["id"], "window_end_date": "2026-06-30",
             "measured_value": 60, "supersedes_observation_id": obs1["id"]},
            DOPS,
        ), expected_status=201)
        assert obs3["id"]
        rows = get_success_data(api.list_observations(
            prog_id, idx_id, DOPS,
            params={"station_id": st1["id"], "window_end_date": "2026-06-30"},
        ))
        by_id = {r["id"]: r for r in rows}
        assert by_id[obs1["id"]]["is_effective"] is False
        assert by_id[obs3["id"]]["is_effective"] is True


# ===========================================================================
# Rule compensating_invariant — invoice_payment_conservation_partial_plus_final_equals_total
# ===========================================================================

class TestInvoicePaymentConservation:
    def test_partial_plus_final_conserves_invoice_total(self, api):
        """PRD §3.5: "Each accepted payment adds to `amount_paid_cents`; the
        invoice stands `PARTIALLY_PAID` while a balance remains and turns `PAID`
        the moment payments equal the billed amount."
        PRD §3.5: "The invoice is created in `ISSUED` status with
        `invoice_amount_cents` equal to the sum of `premium_cents` and
        `premium_tax_cents` computed at issuance"

        Design: Difficulty/compensating_invariant/invoice_payment_conservation_partial_plus_final_equals_total
        """
        program, station, index = setup_active_program()
        holder = create_policyholder(program["id"])
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        assert invoice["invoice_amount_cents"] == 306_000, (
            f"premium 300,000 + tax 6,000; got {invoice['invoice_amount_cents']}"
        )
        p1 = validate_success(api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 200_000}, SVC
        ))
        assert p1["amount_paid_cents"] == 200_000
        assert p1["status"] == "PARTIALLY_PAID"
        p2 = validate_success(api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 106_000}, SVC
        ))
        assert p2["amount_paid_cents"] == 306_000, (
            "conservation: 200,000 + 106,000 == invoice_amount_cents exactly"
        )
        assert p2["status"] == "PAID"

    def test_overpayment_rejected_and_balance_undisturbed(self, api):
        """PRD §3.5: "the amount must be greater than zero, and the running
        `amount_paid_cents` plus the new amount must not exceed
        `invoice_amount_cents` — an overpaying submission is rejected with
        `ERR_OVERPAYMENT` (HTTP 422)."

        Design: Difficulty/compensating_invariant/invoice_payment_conservation_partial_plus_final_equals_total
        """
        program, station, index = setup_active_program()
        holder = create_policyholder(program["id"])
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        # Partial payment keeps the invoice payable; the next payment of
        # 106,001 would overrun the 306,000 total by one cent. Only the
        # overpayment guard can fire here (invoice is still PARTIALLY_PAID).
        validate_success(api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 200_000}, SVC
        ))
        resp = api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 106_001}, SVC
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)
        after = validate_success(api.get_invoice(program["id"], invoice["id"], SVC))
        assert after["amount_paid_cents"] == 200_000, (
            "the rejected payment must not disturb the running total"
        )
        # The exact remaining balance still settles the invoice at zero drift.
        final = validate_success(api.pay_invoice(
            program["id"], invoice["id"], {"amount_cents": 106_000}, SVC
        ))
        assert final["amount_paid_cents"] == 306_000
        assert final["status"] == "PAID"


# ===========================================================================
# Rule compensating_invariant — incurred_claims_conserved_under_upheld_dispute_adjustment
# ===========================================================================

class TestIncurredClaimsConservation:
    def _setup_paid_with_dispute(self, api):
        # measured_value=30 breaches both tiers (30<=50 and 30<=30, inclusive).
        # Claim is approved at the max tier (2), so we dispute DOWN to tier 1
        # (a downward adjustment) — claimed_tier=1 satisfies != tier_applied.
        stack, event, claim = setup_paid_claim(
            trigger_thresholds=TIERS_2, measured_value=30,
        )
        prog_id = stack["program"]["id"]
        dispute = validate_success(api.create_dispute(
            prog_id, claim["id"],
            {"dispute_reason": "BASIS_RISK_MISMATCH", "claimed_tier": 1}, SVC,
        ), expected_status=201)
        return stack, claim, dispute

    def test_upheld_dispute_applies_full_signed_delta(self, api):
        """PRD §3.8: "On `UPHELD`, `adjustment_delta_cents` is that benchmark
        minus the claim's `final_payout_cents`."
        PRD §3.8: "The signed delta applies to the claim's `final_payout_cents`
        and to the program's `incurred_claims_cents` alike — a downward
        adjustment reduces both"

        Design: Difficulty/compensating_invariant/incurred_claims_conserved_under_upheld_dispute_adjustment
        """
        stack, claim, dispute = self._setup_paid_with_dispute(api)
        prog_id = stack["program"]["id"]
        before = validate_success(api.get_program(prog_id, PM))
        # Approved at tier 2 (measured 30, both tiers breached): final = 1,000,000.
        assert before["incurred_claims_cents"] == 1_000_000
        resolved = validate_success(api.resolve_dispute(
            prog_id, claim["id"], dispute["id"], {"resolution": "UPHELD"}, ADJ
        ))
        # tier-1 benchmark 500,000 - final 1,000,000 = -500,000 (downward).
        assert resolved["adjustment_delta_cents"] == -500_000, (
            f"tier-1 benchmark 500,000 - final 1,000,000 = -500,000; got "
            f"{resolved['adjustment_delta_cents']}"
        )
        claim_after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert claim_after["final_payout_cents"] == 500_000

    def test_program_ledger_moves_identically_with_claim(self, api):
        """PRD §3.8: "The signed delta applies to the claim's `final_payout_cents`
        and to the program's `incurred_claims_cents` alike — a downward
        adjustment reduces both — while cession is deliberately not re-run on
        adjustment"

        Design: Difficulty/compensating_invariant/incurred_claims_conserved_under_upheld_dispute_adjustment
        """
        stack, claim, dispute = self._setup_paid_with_dispute(api)
        prog_id = stack["program"]["id"]
        before = validate_success(api.get_program(prog_id, PM))
        validate_success(api.resolve_dispute(
            prog_id, claim["id"], dispute["id"], {"resolution": "UPHELD"}, ADJ
        ))
        after = validate_success(api.get_program(prog_id, PM))
        # 1,000,000 at release + (-500,000) upheld delta = 500,000.
        assert after["incurred_claims_cents"] == 500_000, (
            f"1,000,000 at release + (-500,000) upheld delta; got "
            f"{after['incurred_claims_cents']}"
        )
        assert (after["incurred_claims_cents"] - before["incurred_claims_cents"]) == -500_000
