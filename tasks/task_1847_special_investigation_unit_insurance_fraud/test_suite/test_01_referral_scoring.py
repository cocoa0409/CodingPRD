"""Referral intake, weighted suspicion scoring, and band thresholds."""
from test_helpers import (
    validate_success, get_success_data,
    make_manager_headers, make_adjuster_headers,
    create_adjuster, create_claim, create_referral, triage_referral,
)
from test_helpers.api_client import api_client


class TestRedFlagScoreDualVariant:
    """Difficulty/dual_variant_calc/red_flag_score_provisional_vs_triage_adjusted"""

    def test_provisional_score_at_intake_uses_raw_weights(self, api):
        """PRD §3.2: "The referral is born in `SUBMITTED`, and the server immediately
        computes a provisional `suspicion_score` and `score_band`."
        PRD §3.2: "Each code in `red_flag_codes` contributes a fixed weight:
        `PRIOR_FRAUD_CONVICTION` adds 35, `DUPLICATE_CLAIM_CROSS_INSURER` adds 30,
        `PROVIDER_ON_WATCHLIST` adds 28, `STAGED_ACCIDENT_PATTERN` adds 25,
        `PHANTOM_TREATMENT` adds 22, `INFLATED_BILLING` adds 20, `IDENTITY_MISMATCH`
        adds 18, `POST_POLICY_BIND_CLAIM` adds 15, `EXCESSIVE_TREATMENT_FREQUENCY`
        adds 14, and `UNWITNESSED_LOSS` adds 12."

        Design: Difficulty/dual_variant_calc/red_flag_score_provisional_vs_triage_adjusted
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=10_000_000)
        ref = create_referral(
            claim, red_flag_codes=["STAGED_ACCIDENT_PATTERN", "UNWITNESSED_LOSS"],
            headers=ah)
        assert ref["suspicion_score"] == 37, \
            f"25+12=37 expected, got {ref['suspicion_score']}"
        assert ref["score_band"] == "MEDIUM"

    def test_triage_adjusted_variant_replaces_weights_via_overrides(self, api):
        """PRD §3.2: "During triage the manager may pass `modifier_overrides`, a map
        from red-flag code to replacement weight; for that recompute only, any code
        named in the map contributes the supplied weight instead of its standard
        weight, so the triage-adjusted score can differ from the provisional intake
        score even for an identical list of codes."

        Design: Difficulty/dual_variant_calc/red_flag_score_provisional_vs_triage_adjusted
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=10_000_000)
        ref = create_referral(
            claim, red_flag_codes=["STAGED_ACCIDENT_PATTERN", "UNWITNESSED_LOSS"],
            headers=ah)
        assert ref["suspicion_score"] == 37
        after = triage_referral(ref, modifier_overrides={"UNWITNESSED_LOSS": 25},
                                manager_headers=mh)
        assert after["suspicion_score"] == 50, \
            f"25 (STAGED) + 25 (UNWITNESSED overridden) = 50, got {after['suspicion_score']}"
        assert after["score_band"] == "HIGH"
        assert after["suspicion_score"] != ref["suspicion_score"]


class TestRedFlagScoreEvaluationOrder:
    """Difficulty/combinatorial_formula/red_flag_score_mode_c_evaluation_order_pinned"""

    def test_combination_bonus_applied_before_high_value_multiplier(self, api):
        """PRD §3.2: "When three or more codes are present, a combination bonus of
        15 points is added on top of the summed weights. Finally, when the flagged
        claim's `claimed_amount_cents` is at least 25,000,000 cents — a quarter of
        a million dollars — the running score is multiplied by 1.25 and rounded
        half-up to a whole number."
        (PRIOR 35 + STAGED 25 + INFLATED 20 = 80; +15 bonus = 95; *1.25 = 118.75
        -> round half up -> 119. If multiplier applied first: 80*1.25+15 = 115.)

        Design: Difficulty/combinatorial_formula/red_flag_score_mode_c_evaluation_order_pinned
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=50_000_000)
        ref = create_referral(
            claim,
            red_flag_codes=["PRIOR_FRAUD_CONVICTION", "STAGED_ACCIDENT_PATTERN",
                            "INFLATED_BILLING"],
            headers=ah)
        assert ref["suspicion_score"] == 119, \
            f"(80+15)*1.25=118.75 -> 119 expected, got {ref['suspicion_score']}"

    def test_evaluation_order_pins_critical_band(self, api):
        """PRD §3.2: "The `score_band` is then read from the final score: below 20
        is `LOW`, 20 up to but not including 40 is `MEDIUM`, 40 up to but not
        including 70 is `HIGH`, and 70 or more is `CRITICAL`."

        Design: Difficulty/combinatorial_formula/red_flag_score_mode_c_evaluation_order_pinned
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=50_000_000)
        ref = create_referral(
            claim,
            red_flag_codes=["PRIOR_FRAUD_CONVICTION", "STAGED_ACCIDENT_PATTERN",
                            "INFLATED_BILLING"],
            headers=ah)
        assert ref["score_band"] == "CRITICAL"


class TestScoreBandBoundaries:
    def test_score_exactly_20_is_medium_not_low(self, api):
        """PRD §3.2: "The `score_band` is then read from the final score: below 20
        is `LOW`, 20 up to but not including 40 is `MEDIUM`, 40 up to but not
        including 70 is `HIGH`, and 70 or more is `CRITICAL`."
        Single INFLATED_BILLING = 20; 20 is NOT < 20, so band is MEDIUM.

        Design: Corner/calculations/red_flag_score_band_boundary_20_is_medium
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=1_000_000)
        ref = create_referral(claim, red_flag_codes=["INFLATED_BILLING"], headers=ah)
        assert ref["suspicion_score"] == 20
        assert ref["score_band"] == "MEDIUM"

    def test_combination_bonus_at_exactly_3_codes(self, api):
        """PRD §3.2: "When three or more codes are present, a combination bonus of
        15 points is added on top of the summed weights."
        UNWITNESSED_LOSS(12) + POST_POLICY_BIND_CLAIM(15) +
        EXCESSIVE_TREATMENT_FREQUENCY(14) = 41; +15 bonus = 56.

        Design: Corner/calculations/red_flag_score_combination_bonus_at_exactly_3_codes
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=1_000_000)
        ref = create_referral(
            claim,
            red_flag_codes=["UNWITNESSED_LOSS", "POST_POLICY_BIND_CLAIM",
                            "EXCESSIVE_TREATMENT_FREQUENCY"],
            headers=ah)
        assert ref["suspicion_score"] == 56, \
            f"12+15+14+15=56 expected, got {ref['suspicion_score']}"
        assert ref["score_band"] == "HIGH"


class TestComputedScoreNotClientInjectable:
    def test_referral_create_ignores_client_supplied_suspicion_score(self, api):
        """PRD §3.2: "The referral is born in `SUBMITTED`, and the server immediately
        computes a provisional `suspicion_score` and `score_band`."
        The server-computed value reflects the formula (UNWITNESSED_LOSS=12), not a
        client-supplied value.

        Design: Corner/entities/referral_computed_score_input_ignored
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=1_000_000)
        resp = api_client.create_referral(
            {"claim_id": claim["id"], "submitted_by_role": "ADJUSTER",
             "red_flag_codes": ["UNWITNESSED_LOSS"], "narrative": "x",
             "suspicion_score": 999},
            ah)
        data = validate_success(resp, expected_status=201)
        assert data["suspicion_score"] == 12, \
            f"server must compute 12, not client-supplied 999; got {data['suspicion_score']}"
