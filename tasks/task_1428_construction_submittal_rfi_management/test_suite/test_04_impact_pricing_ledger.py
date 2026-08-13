"""Pricing impacts against the contingency ledger (PRD §2.7, §2.10, §3.6)."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    add_reviewer,
    answer_rfi,
    assert_contingency_conserved,
    assert_impact_assessment,
    assessment_for_rfi,
    create_active_project,
    create_rfi,
    get_project,
    make_project_manager_headers,
    price_assessment,
    route_rfi,
    setup_estimated_assessment,
    waive_assessment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, PE_USER_ID, PM_USER_ID

PE = TEST_USERS["project_engineer_headers"]


class TestDualVariantDeltas:
    def test_provisional_delta_computed_at_answer_time(self, api):
        """PRD §3.6: "When the cost flag is true, the system immediately creates an
        ImpactAssessment in `ESTIMATED` status carrying the answer's
        `estimated_cost_cents` and a `provisional_delta_cents` computed by the
        provisional pricing variant of §3.6."
        PRD §3.6: "Because the provisional variant carries the allowance layer and the
        final variant does not, the two diverge even for numerically identical bases: a
        base of 100000 cents yields a provisional delta of 135482 cents but a final
        tier-1 delta of 117810 cents."

        Design: Difficulty/dual_variant_calc/impact_cost_provisional_vs_final
        """
        ctx = setup_estimated_assessment(estimated_cost_cents=100_000)
        assessment = ctx["assessment"]
        assert_impact_assessment(assessment)
        assert assessment["status"] == "ESTIMATED"
        assert assessment["estimated_cost_cents"] == 100_000
        assert assessment["provisional_delta_cents"] == 135_482, (
            "provisional: round(100000*1.10)=110000, round(110000*1.05)=115500, "
            "round(115500*1.15)=132825, round(132825*1.02)=135482"
        )
        assert assessment["final_delta_cents"] is None, (
            "the final delta stays null until pricing"
        )

    def test_final_delta_diverges_from_provisional_for_identical_base(self, api):
        """PRD §3.6: "The final variant prices off `sub_quote_cents` at a tier selected
        from the ledger: tier 2 when the project's `contingency_spent_cents`, observed
        before this pricing's reservation is applied, is at least
        `gc_tier_threshold_cents`, and tier 1 otherwise."
        PRD §3.6: "Because the provisional variant carries the allowance layer and the
        final variant does not, the two diverge even for numerically identical bases: a
        base of 100000 cents yields a provisional delta of 135482 cents but a final
        tier-1 delta of 117810 cents."

        Design: Difficulty/dual_variant_calc/impact_cost_provisional_vs_final
        """
        ctx = setup_estimated_assessment(estimated_cost_cents=100_000)
        assessment = ctx["assessment"]
        priced = price_assessment(assessment["id"], 100_000)
        assert priced["gc_markup_tier"] == 1, "nothing spent yet, below the threshold"
        assert priced["final_delta_cents"] == 117_810, (
            "final tier 1: 110000 -> 115500 -> round(115500*1.02)=117810"
        )
        assert priced["final_delta_cents"] != assessment["provisional_delta_cents"]


class TestLayeredRoundingOrder:
    def test_final_delta_uses_per_layer_rounding(self, api):
        """PRD §3.6: "Both delta variants share a layered markup in which every layer is
        rounded to whole cents, round-half-up, before the next layer applies. First the
        base grows by a subcontractor markup of ten percent and rounds; that result grows
        by the general-contractor markup — five percent in tier 1, seven percent in tier
        2 — and rounds; the provisional variant alone then grows by a contingency
        allowance of fifteen percent and rounds, while the final variant skips the
        allowance layer entirely; finally the result grows by a two percent bond and
        rounds to produce the delta."
        Base 33333 final: round(33333*1.10)=36666, round(36666*1.05)=38499,
        round(38499*1.02)=39269 — a sum-then-round ordering would yield 39267.

        Design: Difficulty/combinatorial_formula/impact_cost_layered_rounding_order
        """
        ctx = setup_estimated_assessment(estimated_cost_cents=33_333)
        priced = price_assessment(ctx["assessment"]["id"], 33_333)
        assert priced["final_delta_cents"] == 39_269
        assert priced["final_delta_cents"] != 39_267, (
            "39267 is the single-rounded value; per-layer rounding is pinned"
        )

    def test_provisional_delta_includes_allowance_layer_with_per_layer_rounding(self, api):
        """PRD §3.6: "the provisional variant alone then grows by a contingency allowance
        of fifteen percent and rounds, while the final variant skips the allowance layer
        entirely"
        PRD §3.6: "The provisional variant always prices at tier 1 off
        `estimated_cost_cents`."
        Base 33333 provisional: 36666 -> 38499 -> round(38499*1.15)=44274 ->
        round(44274*1.02)=45159.

        Design: Difficulty/combinatorial_formula/impact_cost_layered_rounding_order
        """
        ctx = setup_estimated_assessment(estimated_cost_cents=33_333)
        assert ctx["assessment"]["provisional_delta_cents"] == 45_159


class TestTierEvaluationOrder:
    def _two_assessment_world(self, api):
        """IA1 priced at 850000 and accepted (spent 1001385); IA2 ESTIMATED at 100000."""
        project = create_active_project("TierOrder", initial_contingency_cents=3_000_000)
        reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")

        rfi1 = create_rfi(project["id"], subject="Steel grade")
        route_rfi(rfi1["id"], reviewer["id"])
        answer_rfi(
            rfi1["id"],
            reviewer["id"],
            answer_text="Yes, premium",
            cost_impact_flag=True,
            estimated_cost_cents=850_000,
        )
        ia1 = assessment_for_rfi(project["id"], rfi1["id"])
        priced1 = price_assessment(ia1["id"], 850_000, user_id=PE_USER_ID)
        accept_assessment(ia1["id"], user_id=PM_USER_ID)

        rfi2 = create_rfi(project["id"], subject="Bolt spec")
        route_rfi(rfi2["id"], reviewer["id"])
        answer_rfi(
            rfi2["id"],
            reviewer["id"],
            answer_text="TC bolts",
            cost_impact_flag=True,
            estimated_cost_cents=100_000,
        )
        ia2 = assessment_for_rfi(project["id"], rfi2["id"])
        return project, priced1, ia2

    def test_accept_moves_reservation_to_spent_at_tier_one(self, api):
        """PRD §3.6: "Acceptance converts the reservation to spend —
        `contingency_reserved_cents` falls by `final_delta_cents` while
        `contingency_spent_cents` rises by the same amount, leaving the available balance
        unchanged"
        Quote 850000 at tier 1: 935000 -> 981750 -> round(981750*1.02)=1001385.

        Design: Difficulty/combinatorial_formula/contingency_tier_evaluation_order
        """
        project, priced1, _ia2 = self._two_assessment_world(api)
        assert priced1["gc_markup_tier"] == 1
        assert priced1["final_delta_cents"] == 1_001_385
        ledger = get_project(project["id"])
        assert ledger["contingency_spent_cents"] == 1_001_385
        assert ledger["contingency_reserved_cents"] == 0
        assert_contingency_conserved(ledger)

    def test_pricing_after_threshold_crossed_selects_tier_two(self, api):
        """PRD §3.6: "The final variant prices off `sub_quote_cents` at a tier selected
        from the ledger: tier 2 when the project's `contingency_spent_cents`, observed
        before this pricing's reservation is applied, is at least
        `gc_tier_threshold_cents`, and tier 1 otherwise."
        With spent 1001385 >= the default threshold 1000000 at pricing time, the second
        assessment prices at tier 2: 110000 -> round(110000*1.07)=117700 ->
        round(117700*1.02)=120054; a tier-1 read would produce 117810.

        Design: Difficulty/combinatorial_formula/contingency_tier_evaluation_order
        """
        _project, _priced1, ia2 = self._two_assessment_world(api)
        priced2 = price_assessment(ia2["id"], 100_000, user_id=PE_USER_ID)
        assert priced2["gc_markup_tier"] == 2
        assert priced2["final_delta_cents"] == 120_054
        assert priced2["final_delta_cents"] != 117_810


class TestPriceWaiveConservation:
    def test_price_moves_available_into_reserved(self, api):
        """PRD §3.6: "On success the selected `gc_markup_tier` is recorded,
        `contingency_reserved_cents` grows by `final_delta_cents` (with
        `contingency_available_cents` recomputed and the Project's `version` bumped)"
        PRD §2.7: "The ledger obeys a conservation invariant: at all times, the
        available, reserved, and spent balances sum exactly to the seed."

        Design: Difficulty/compensating_invariant/contingency_price_then_waive_conserves_funds
        """
        ctx = setup_estimated_assessment(
            initial_contingency_cents=2_000_000, estimated_cost_cents=100_000
        )
        price_assessment(ctx["assessment"]["id"], 100_000)
        ledger = get_project(ctx["project"]["id"])
        assert ledger["contingency_reserved_cents"] == 117_810
        assert ledger["contingency_spent_cents"] == 0
        assert ledger["contingency_available_cents"] == 1_882_190
        assert_contingency_conserved(ledger)

    def test_waive_restores_ledger_to_zero_drift(self, api):
        """PRD §3.6: "Waiver, also a `ProjectManager` action, is the compensating move:
        it releases the reservation entirely, so `contingency_reserved_cents` falls by
        `final_delta_cents` and the available balance grows, again recording
        `decided_by_user_id`."
        PRD §2.7: "The ledger obeys a conservation invariant: at all times, the
        available, reserved, and spent balances sum exactly to the seed."
        Price (forward) then waive (compensation) ends exactly at the seed.

        Design: Difficulty/compensating_invariant/contingency_price_then_waive_conserves_funds
        """
        ctx = setup_estimated_assessment(
            initial_contingency_cents=2_000_000, estimated_cost_cents=100_000
        )
        price_assessment(ctx["assessment"]["id"], 100_000)
        waived = waive_assessment(ctx["assessment"]["id"])
        assert waived["status"] == "WAIVED"
        ledger = get_project(ctx["project"]["id"])
        assert ledger["contingency_reserved_cents"] == 0
        assert ledger["contingency_spent_cents"] == 0
        assert ledger["contingency_available_cents"] == 2_000_000
        assert_contingency_conserved(ledger)


class TestStateVersusFiscalPriority:
    def test_accept_on_estimated_fails_state_before_fiscal(self, api):
        """PRD §3.6: "Three decisions resolve a `PRICED` assessment, and each requires
        `PRICED` (otherwise `ERR_ASSESSMENT_NOT_PRICED`)."
        PRD §2.10: "a pricing request on an assessment in the wrong state fails with its
        state error before the contingency balance is ever consulted."
        Accepting an ESTIMATED assessment on a project whose 1000-cent contingency could
        never cover the delta returns the state error, not the fiscal one.

        Design: Difficulty/priority_pair_validation_conflict/accept_state_vs_fiscal_priority
        """
        ctx = setup_estimated_assessment(
            initial_contingency_cents=1_000, estimated_cost_cents=100_000
        )
        resp = api.accept_impact_assessment(
            ctx["assessment"]["id"], make_project_manager_headers(PM_USER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_PRICED, 409)
        assert resp.status_code != 402, "the fiscal check is never reached"

    def test_price_with_state_valid_fires_fiscal_check(self, api):
        """PRD §3.6: "The state check comes first — pricing an assessment that is not
        `ESTIMATED` fails with `ERR_ASSESSMENT_NOT_ESTIMATED` — and only then does the
        fiscal check run: the computed `final_delta_cents` must fit within
        `contingency_available_cents`, otherwise the request fails with
        `ERR_CONTINGENCY_EXHAUSTED` (HTTP 402)."
        The same ESTIMATED assessment, acted on by the matching-state operation (price),
        reaches the fiscal check and fails there — confirming the state gate is what
        masked the fiscal failure in the companion test.

        Design: Difficulty/priority_pair_validation_conflict/accept_state_vs_fiscal_priority
        """
        ctx = setup_estimated_assessment(
            initial_contingency_cents=1_000, estimated_cost_cents=100_000
        )
        resp = api.price_impact_assessment(
            ctx["assessment"]["id"], {"sub_quote_cents": 100_000}, PE
        )
        validate_error(resp, ApiErrorId.ERR_CONTINGENCY_EXHAUSTED, 402)
        ledger = get_project(ctx["project"]["id"])
        assert ledger["contingency_reserved_cents"] == 0, "no partial reservation"


class TestFiscalAndSegregationRules:
    def test_price_beyond_available_contingency_returns_402(self, api):
        """PRD §3.6: "the computed `final_delta_cents` must fit within
        `contingency_available_cents`, otherwise the request fails with
        `ERR_CONTINGENCY_EXHAUSTED` (HTTP 402)."
        Final delta 117810 exceeds the 50000-cent available balance; the assessment
        stays ESTIMATED and nothing is reserved.

        Design: Corner/validations/price_beyond_available_contingency_returns_402
        """
        ctx = setup_estimated_assessment(
            initial_contingency_cents=50_000, estimated_cost_cents=100_000
        )
        resp = api.price_impact_assessment(
            ctx["assessment"]["id"], {"sub_quote_cents": 100_000}, PE
        )
        validate_error(resp, ApiErrorId.ERR_CONTINGENCY_EXHAUSTED, 402)

        ledger = get_project(ctx["project"]["id"])
        assert ledger["contingency_reserved_cents"] == 0
        assert_contingency_conserved(ledger)
        assessment = validate_success(
            api.get_impact_assessment(ctx["assessment"]["id"], PE), 200
        )
        assert assessment["status"] == "ESTIMATED"

    def test_segregation_of_duties_price_then_accept_same_user(self, api):
        """PRD §3.6: "Acceptance is a `ProjectManager` action guarded by segregation of
        duties: the acting `X-User-ID` must differ from the assessment's
        `priced_by_user_id`, or the request fails with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."
        The operator id that priced cannot accept even with the ProjectManager role; a
        different manager id accepts.

        Design: Corner/errors/segregation_of_duties_price_then_accept_same_user
        """
        ctx = setup_estimated_assessment(
            initial_contingency_cents=2_000_000, estimated_cost_cents=100_000
        )
        assessment_id = ctx["assessment"]["id"]
        price_assessment(assessment_id, 100_000, user_id=PE_USER_ID)

        resp = api.accept_impact_assessment(
            assessment_id, make_project_manager_headers(PE_USER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)

        accepted = accept_assessment(assessment_id, user_id=PM_USER_ID)
        assert accepted["status"] == "ACCEPTED"
