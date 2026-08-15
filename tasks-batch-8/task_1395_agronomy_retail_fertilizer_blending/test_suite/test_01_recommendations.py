"""Recommendation rate calculations, review cycle, and formulation preview."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, create_grower, create_field, resulted_soil_test, create_recommendation,
    create_product, AGRON, COMPLIANCE)


class TestRecommendationRates:
    def test_build_vs_maintenance_rates_diverge(self, api):
        """PRD 3.2: "Under `BUILD_RATE`, the phosphate rate is the removal component
        plus nine pounds for every ppm by which the soil's `p_ppm` falls short of the
        critical level of 20 ppm (zero when at or above it), and the potash rate is
        the removal component plus four pounds for every ppm by which `k_ppm` falls
        short of the critical level of 130 ppm (zero at or above)."
        PRD 3.2: "Under `MAINTENANCE_RATE` there is no build component: the phosphate
        rate equals the removal component when `p_ppm` is below the drawdown threshold
        of 40 ppm and is zero otherwise, and the potash rate equals the removal
        component when `k_ppm` is below the drawdown threshold of 170 ppm and is zero
        otherwise."

        Design: Difficulty/dual_variant_calc/recommendation_build_vs_maintenance_rates
        """
        grower = create_grower(legal_name="Prairie View Farms", credit_limit_cents=10_000_000)
        field = create_field(grower, name="North 40", acres=50)
        st = resulted_soil_test(field["id"], grower, p_ppm=12, k_ppm=90, ph=6.1)

        rec_build = create_recommendation(
            st["id"], crop="CORN", yield_goal_bu_per_acre=220, rate_variant="BUILD_RATE")
        rec_maint = create_recommendation(
            st["id"], crop="CORN", yield_goal_bu_per_acre=220, rate_variant="MAINTENANCE_RATE")

        # BUILD: p2o5 = round(0.37*220 + (20-12)*9) = round(153.4) = 153
        assert rec_build["p2o5_lbs_per_acre"] == 153
        # BUILD: k2o = round(0.27*220 + (130-90)*4) = round(219.4) = 219
        assert rec_build["k2o_lbs_per_acre"] == 219
        # MAINTENANCE: no build component; p2o5 = round(81.4) = 81, k2o = round(59.4) = 59
        assert rec_maint["p2o5_lbs_per_acre"] == 81
        assert rec_maint["k2o_lbs_per_acre"] == 59
        # N identical in both variants: 1.0 * 220 - 0 - 0 = 220
        assert rec_build["n_lbs_per_acre"] == 220
        assert rec_maint["n_lbs_per_acre"] == 220
        # Same soil test, two valid variants, different results
        assert rec_build["p2o5_lbs_per_acre"] != rec_maint["p2o5_lbs_per_acre"]
        assert rec_build["k2o_lbs_per_acre"] != rec_maint["k2o_lbs_per_acre"]

    def test_build_rate_adds_build_component_above_maintenance(self, api):
        """PRD 3.2: "Under `BUILD_RATE`, the phosphate rate is the removal component
        plus nine pounds for every ppm by which the soil's `p_ppm` falls short of the
        critical level of 20 ppm (zero when at or above it), and the potash rate is
        the removal component plus four pounds for every ppm by which `k_ppm` falls
        short of the critical level of 130 ppm (zero at or above)."

        Design: Difficulty/dual_variant_calc/recommendation_build_vs_maintenance_rates
        """
        grower = create_grower(legal_name="Prairie View Farms 2", credit_limit_cents=10_000_000)
        field = create_field(grower, name="North 40", acres=50)
        st = resulted_soil_test(field["id"], grower, p_ppm=12, k_ppm=90, ph=6.1)

        rec_build = create_recommendation(
            st["id"], crop="CORN", yield_goal_bu_per_acre=220, rate_variant="BUILD_RATE")
        # build components: P (20-12)*9 = 72 above removal 81.4; K (130-90)*4 = 160 above 59.4
        assert rec_build["p2o5_lbs_per_acre"] - 81 == 72
        assert rec_build["k2o_lbs_per_acre"] - 59 == 160

    def test_maintenance_rate_drawdown_cutoff_zeroes_phosphate(self, api):
        """PRD 3.2: "Under `MAINTENANCE_RATE` there is no build component: the phosphate
        rate equals the removal component when `p_ppm` is below the drawdown threshold
        of 40 ppm and is zero otherwise, and the potash rate equals the removal
        component when `k_ppm` is below the drawdown threshold of 170 ppm and is zero
        otherwise."

        Design: Corner/calculations/maintenance_rate_drawdown_cutoff_zero
        """
        grower = create_grower(legal_name="Drawdown Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="DD Field", acres=50)
        st = resulted_soil_test(field["id"], grower, p_ppm=50, k_ppm=90, ph=6.4)

        rec = create_recommendation(
            st["id"], crop="CORN", yield_goal_bu_per_acre=220, rate_variant="MAINTENANCE_RATE")
        assert rec["p2o5_lbs_per_acre"] == 0, "p 50 >= drawdown 40 cuts P to zero"
        assert rec["k2o_lbs_per_acre"] == 59, "k 90 < 170 keeps removal rate"
        assert rec["n_lbs_per_acre"] == 220


class TestRecommendationCycle:
    def test_review_loop_cycles_and_bumps_version(self, api):
        """PRD 3.2: "A recommendation is born `DRAFT`. The agronomist submits it
        (`DRAFT → PENDING_REVIEW`); a `ComplianceOfficer` then either returns it to
        `DRAFT` — recording the supplied `reason` into `return_reason` — or approves
        it (`PENDING_REVIEW → APPROVED`)."
        PRD 2.4: "version, an integer that increments by exactly 1 on every mutation
        of that resource."

        Design: Difficulty/non_linear_state_machine/recommendation_draft_review_cycle
        """
        grower = create_grower(legal_name="Cycle Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="Plot 1", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = create_recommendation(st["id"])
        assert rec["version"] == 1

        r1 = get_success_data(api.submit_recommendation(rec["id"], AGRON))
        assert r1["status"] == "PENDING_REVIEW"

        r2 = get_success_data(api.return_recommendation(rec["id"], {"reason": "revise K rate"}, COMPLIANCE))
        assert r2["status"] == "DRAFT"
        assert r2["return_reason"] == "revise K rate"

        r3 = get_success_data(api.submit_recommendation(rec["id"], AGRON))
        assert r3["status"] == "PENDING_REVIEW", "second pass through the cycle"

        r4 = get_success_data(api.approve_recommendation(rec["id"], COMPLIANCE))
        assert r4["status"] == "APPROVED"
        assert r4["version"] == 5, "one version bump per transition"

    def test_return_reason_persisted_across_loop(self, api):
        """PRD 3.2: "a `ComplianceOfficer` then either returns it to `DRAFT` —
        recording the supplied `reason` into `return_reason` — or approves it
        (`PENDING_REVIEW → APPROVED`)."

        Design: Difficulty/non_linear_state_machine/recommendation_draft_review_cycle
        """
        grower = create_grower(legal_name="Cycle Farms 2", credit_limit_cents=1_000_000)
        field = create_field(grower, name="Plot 2", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = create_recommendation(st["id"])

        get_success_data(api.submit_recommendation(rec["id"], AGRON))
        returned = get_success_data(api.return_recommendation(rec["id"], {"reason": "revise K rate"}, COMPLIANCE))
        assert returned["status"] == "DRAFT"

        readback = get_success_data(api.get_recommendation(rec["id"], AGRON))
        assert readback["return_reason"] == "revise K rate", "return_reason persisted on read"


class TestRecommendationPreconditions:
    def test_approve_from_draft_rejected(self, api):
        """PRD 3.2: "The agronomist submits it (`DRAFT → PENDING_REVIEW`); a
        `ComplianceOfficer` then either returns it to `DRAFT` — recording the supplied
        `reason` into `return_reason` — or approves it (`PENDING_REVIEW → APPROVED`)."
        PRD 3.5: "Any transition fired from an ineligible state is
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/recommendation_approve_from_draft_rejected
        """
        grower = create_grower(legal_name="Precond Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="S2", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = create_recommendation(st["id"])

        resp = api.approve_recommendation(rec["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

        readback = get_success_data(api.get_recommendation(rec["id"], AGRON))
        assert readback["status"] == "DRAFT", "recommendation remains DRAFT"


class TestFormulationPreview:
    def test_solver_ordered_nutrient_assignment(self, api):
        """PRD 3.2: "First the phosphorus source: among the selected products it
        chooses the one with the highest `analysis_p2o5_pct` above zero... The chosen
        product's rate is the P2O5 need divided by its P2O5 analysis fraction, rounded
        half-up to one decimal of pounds per acre. Second, the nitrogen that source
        contributes — the P-source rate multiplied by its nitrogen analysis fraction,
        rounded half-up to three decimals — is credited against the N need... Fourth,
        any remaining nitrogen need — the N need minus both credited contributions,
        rounded half-up to three decimals — must be covered by a pure nitrogen source
        among the selected products: the one with the highest `analysis_n_pct` whose
        `analysis_p2o5_pct` and `analysis_k2o_pct` are both zero (same tie-break)..."

        Design: Difficulty/combinatorial_formula/formulation_solver_ordered_nutrient_assignment
        """
        grower = create_grower(legal_name="Solver Test Farms", credit_limit_cents=10_000_000)
        field = create_field(grower, name="West 80", acres=50)
        st = resulted_soil_test(field["id"], grower, p_ppm=12, k_ppm=90, ph=6.1)
        rec = create_recommendation(st["id"])  # N 220, P2O5 153, K2O 219
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        dap = create_product("DAP 18-46-0", 18, 46, 0)
        mop = create_product("MOP 0-0-60", 0, 0, 60)

        resp = api.formulation_preview(rec["id"], {"product_ids": [urea["id"], dap["id"], mop["id"]]}, AGRON)
        data = validate_success(resp, 200)
        assert data["feasible"] is True
        lines = {ln["product_id"]: ln for ln in data["lines"]}
        # DAP rate = round(153/0.46, 1) = 332.6
        assert lines[dap["id"]]["target_rate_lbs_per_acre"] == pytest.approx(332.6, abs=0.05)
        # MOP rate = round(219/0.60, 1) = 365.0
        assert lines[mop["id"]]["target_rate_lbs_per_acre"] == pytest.approx(365.0, abs=0.05)
        # UREA rate = round((220 - round(332.6*0.18,3)=59.868)/0.46, 1) = round(348.1130,1) = 348.1
        assert lines[urea["id"]]["target_rate_lbs_per_acre"] == pytest.approx(348.1, abs=0.05)
        # N-credit branch is load-bearing: without crediting, UREA would be 478.3
        assert lines[urea["id"]]["target_rate_lbs_per_acre"] < 400

    def test_solver_credits_p_source_nitrogen(self, api):
        """PRD 3.2: "Second, the nitrogen that source contributes — the P-source rate
        multiplied by its nitrogen analysis fraction, rounded half-up to three
        decimals — is credited against the N need; if that credit alone exceeds the N
        need, the formulation is infeasible with `ERR_FORMULATION_UNSOLVABLE`."

        Design: Difficulty/combinatorial_formula/formulation_solver_ordered_nutrient_assignment
        """
        grower = create_grower(legal_name="Solver Test Farms B", credit_limit_cents=10_000_000)
        field = create_field(grower, name="West 81", acres=50)
        st = resulted_soil_test(field["id"], grower, p_ppm=12, k_ppm=90, ph=6.1)
        rec = create_recommendation(st["id"])  # N 220
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        dap = create_product("DAP 18-46-0", 18, 46, 0)
        mop = create_product("MOP 0-0-60", 0, 0, 60)

        data = validate_success(api.formulation_preview(rec["id"], {"product_ids": [urea["id"], dap["id"], mop["id"]]}, AGRON))
        lines = {ln["product_id"]: ln for ln in data["lines"]}
        # DAP credits 59.868 N; residual N 160.132 -> UREA 348.1, not 478.3
        assert lines[urea["id"]]["target_rate_lbs_per_acre"] == pytest.approx(348.1, abs=0.05)

    def test_formulation_unsolvable_when_p_source_n_credit_exceeds_need(self, api):
        """PRD 3.2: "if that credit alone exceeds the N need, the formulation is
        infeasible with `ERR_FORMULATION_UNSOLVABLE`."

        Design: Corner/validations/formulation_preview_unsolvable_returns_422
        """
        grower = create_grower(legal_name="Unsolvable Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="UF Field", acres=50)
        st = resulted_soil_test(field["id"], grower, p_ppm=5, k_ppm=90, ph=6.0)
        rec = create_recommendation(st["id"], crop="WHEAT", yield_goal_bu_per_acre=30)
        # build: 0.37*30 + (20-5)*9 = 146.1 -> 146
        assert rec["p2o5_lbs_per_acre"] == 146
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        dap = create_product("DAP 18-46-0", 18, 46, 0)
        mop = create_product("MOP 0-0-60", 0, 0, 60)

        resp = api.formulation_preview(rec["id"], {"product_ids": [urea["id"], dap["id"], mop["id"]]}, AGRON)
        # DAP rate 317.4 credits 57.132 N > 30 needed -> infeasible
        validate_error(resp, ApiErrorId.ERR_FORMULATION_UNSOLVABLE)


class TestRecommendationValidation:
    def test_invalid_crop_enum_rejected(self, api):
        """PRD 3.2: "an `Agronomist` drafts a `Recommendation`, supplying `crop` (one
        of `CORN`, `SOYBEAN`, `WHEAT`)..."
        PRD 2.7: "then request-body shape — required fields present, enum members
        valid, numeric ranges respected, unknown fields rejected — as
        `ERR_VALIDATION_FAILED`."

        Design: Corner/entities/recommendation_invalid_crop_enum_returns_400
        """
        grower = create_grower(legal_name="Enum Farm", credit_limit_cents=1_000_000)
        field = create_field(grower, name="Enum Field", acres=50)
        st = resulted_soil_test(field["id"], grower)

        resp = api.create_recommendation(
            st["id"],
            {"crop": "DURUM", "yield_goal_bu_per_acre": 220, "rate_variant": "BUILD_RATE",
             "valid_until": "2027-06-01T00:00:00Z"},
            AGRON)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)
