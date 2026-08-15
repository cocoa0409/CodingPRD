"""Derived-value calculation tests: exposure variants, penalty variants,
required sample count tiers, traceability rounding, and threshold boundaries."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_brand_rep_headers, build_user_headers,
    create_standard, create_brand, create_product, add_ingredient,
    add_accepted_affidavit, create_product_under_evaluation, create_plan,
    collect_sample, confirm_sample, create_passed_audit, create_verified_product,
    open_case, substantiate_case, set_clock, get_product,
    create_facility_audit_payload, create_audit_report_payload,
)

ADMIN = TEST_USERS["verifier_admin_headers"]
LAB_1 = TEST_USERS["lab_analyst_1_headers"]
LAB_2 = TEST_USERS["lab_analyst_2_headers"]


def _auditor_headers(auditor_id):
    return build_user_headers(auditor_id, "Auditor")


# ─── Product exposure: provisional vs confirmed dual variant ────────────────

def _setup_exposure_product(api):
    """Product with A HIGH_RISK 40%, B LOW_RISK 30%, C NON_CROP 30%;
    affidavits for A and B accepted; product UNDER_EVALUATION with a
    FINISHED_PRODUCT plan (required 3). Returns (product, plan, ingA)."""
    ctx = create_product_under_evaluation(
        name="P1", gtin="G-P1", annual_volume_units=5000,
        ingredient_specs=(
            {"name": "A", "crop_type": "HIGH_RISK", "declared_weight_pct": 40.00},
            {"name": "B", "crop_type": "LOW_RISK", "declared_weight_pct": 30.00},
            {"name": "C", "crop_type": "NON_CROP", "declared_weight_pct": 30.00},
        ),
    )
    plan = create_plan(ctx["product"]["id"], risk_point="FINISHED_PRODUCT")
    return ctx, plan


class TestProductExposureVariants:
    def test_untested_pcr_ingredient_diverges_variants(self, api):
        """PRD section 3.5: "Under the evidence-only `confirmed_exposure_pct`, an
        ingredient with no confirmed result contributes zero."
        PRD section 3.5: "Under the conservative `provisional_exposure_pct`, an
        untested ingredient that requires PCR is assumed to sit exactly at the
        standard's threshold, while one that requires no testing still contributes
        zero."

        Design: Difficulty/dual_variant_calc/product_exposure_provisional_vs_confirmed
        """
        ctx, plan = _setup_exposure_product(api)
        product = get_product(ctx["product"]["id"])
        # A (40.00, requires PCR, untested) assumed at 0.9 -> 36.00 provisional;
        # confirmed variant counts it as 0.
        assert product["provisional_exposure_pct"] == pytest.approx(36.00, abs=0.01)
        assert product["confirmed_exposure_pct"] == pytest.approx(0.00, abs=0.01)

    def test_variants_converge_after_confirmation(self, api):
        """PRD section 3.5: "For each ingredient, take the maximum
        `result_gmo_pct` among its `CONFIRMED` samples — invalidated results are
        excluded — and weight it by `declared_weight_pct`."
        PRD section 3.5: "Both fields are recomputed on product submission, on
        sample confirmation, and on sample invalidation."

        Design: Difficulty/dual_variant_calc/product_exposure_provisional_vs_confirmed
        """
        ctx, plan = _setup_exposure_product(api)
        ing_a = ctx["ingredients"][0]
        confirm_sample(plan["id"], ing_a["id"], result_gmo_pct=0.30)
        product = get_product(ctx["product"]["id"])
        # 40.00 x 0.30 = 12.00 for both variants once evidence exists.
        assert product["provisional_exposure_pct"] == pytest.approx(12.00, abs=0.01)
        assert product["confirmed_exposure_pct"] == pytest.approx(12.00, abs=0.01)


# ─── Brand penalty points: lifetime vs rolling dual variant ─────────────────

def _setup_brand_with_two_draft_products():
    std = create_standard()
    brand = create_brand(name="B1", contact_email="b1@x.com")
    p1 = create_product(brand, std, name="P1", gtin="G-P1")
    p2 = create_product(brand, std, name="P2", gtin="G-P2")
    return std, brand, p1, p2


class TestBrandPenaltyVariants:
    def test_exactly_365_days_old_substantiation_excluded_from_rolling(self, api):
        """PRD section 3.8: "`rolling_penalty_points` is recomputed as the same sum
        restricted to cases whose `substantiated_at` is strictly more recent than
        365 days before now — a substantiation exactly 365 days old is excluded"
        PRD section 3.8: "the case's points add into the brand's
        `lifetime_penalty_points`, an all-time sum over `SUBSTANTIATED` cases on
        the brand's products"

        Design: Difficulty/dual_variant_calc/brand_penalty_lifetime_vs_rolling_window
        """
        _, brand, p1, _ = _setup_brand_with_two_draft_products()
        case = open_case(p1["id"], description="unlicensed seal use")
        substantiate_case(case["id"], sanction="WARNING")

        set_clock("2027-08-01T00:00:00Z")  # exactly 365 days after 2026-08-01
        brand_after = validate_success(api.get_brand(brand["id"], ADMIN), 200)
        assert brand_after["lifetime_penalty_points"] == 5
        assert brand_after["rolling_penalty_points"] == 0
        assert brand_after["standing_status"] == "GOOD_STANDING"

    def test_variants_diverge_on_identical_case_history(self, api):
        """PRD section 3.8: "and `standing_status` flips to `PROBATION` exactly
        when the lifetime total reaches 20 or more, otherwise `GOOD_STANDING`."
        PRD section 3.8: "`rolling_penalty_points` is recomputed as the same sum
        restricted to cases whose `substantiated_at` is strictly more recent than
        365 days before now — a substantiation exactly 365 days old is excluded"

        Design: Difficulty/dual_variant_calc/brand_penalty_lifetime_vs_rolling_window
        """
        _, brand, p1, p2 = _setup_brand_with_two_draft_products()
        case1 = open_case(p1["id"], description="unlicensed seal use")
        substantiate_case(case1["id"], sanction="WARNING")

        set_clock("2027-08-01T00:00:00Z")
        case2 = open_case(p2["id"], source="MARKETPLACE_MONITOR",
                          description="second violation")
        substantiate_case(case2["id"], sanction="WARNING")

        set_clock("2027-08-02T00:00:00Z")
        brand_after = validate_success(api.get_brand(brand["id"], ADMIN), 200)
        assert brand_after["lifetime_penalty_points"] == 10
        assert brand_after["rolling_penalty_points"] == 5
        assert brand_after["standing_status"] == "GOOD_STANDING"


# ─── required_sample_count combinatorial tiers ──────────────────────────────

class TestRequiredSampleCount:
    def test_full_stack_inputs_land_on_nine(self, api):
        """PRD section 3.5: "The plan's `required_sample_count` is computed at
        creation from the product's risk profile: start with a base of 0 for
        `INGREDIENT_INTAKE`, 1 for `IN_PROCESS`, or 2 for `FINISHED_PRODUCT`; add
        one for each of the product's ingredients with `requires_pcr` true; add a
        volume tier of 2 when `annual_volume_units` reaches 100,000, 1 when it
        reaches 10,000, and 0 below that; and add 2 when the brand's history shows
        at least one `SUBSTANTIATED` enforcement case or at least one `FAILED`
        facility audit, 0 otherwise. The total is capped at 10."

        Design: Difficulty/combinatorial_formula/required_sample_count_multi_input_tiers
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        # Brand history: one FAILED facility audit (history_extra = 2).
        audit = validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"], facility_name="F1",
                                              auditor_id="aud-1"),
                ADMIN,
            ), 201)
        validate_success(
            api.submit_audit_report(audit["id"], create_audit_report_payload(),
                                    _auditor_headers("aud-1")), 200)
        validate_success(api.decide_audit(audit["id"], {"decision": "FAILED"}, ADMIN), 200)

        ctx = create_product_under_evaluation(
            name="P1", gtin="G-P1", annual_volume_units=150000,
            ingredient_specs=(
                {"name": "A", "crop_type": "HIGH_RISK", "declared_weight_pct": 20.00},
                {"name": "B", "crop_type": "HIGH_RISK", "declared_weight_pct": 20.00},
                {"name": "C", "crop_type": "HIGH_RISK", "declared_weight_pct": 20.00},
            ),
            brand=brand, standard=std,
        )
        plan = create_plan(ctx["product"]["id"], risk_point="FINISHED_PRODUCT")
        # min(10, 2 base + 3 pcr + 2 volume + 2 history) = 9
        assert plan["required_sample_count"] == 9

    def test_minimal_inputs_land_on_one(self, api):
        """PRD section 3.5: "The plan's `required_sample_count` is computed at
        creation from the product's risk profile: start with a base of 0 for
        `INGREDIENT_INTAKE`, 1 for `IN_PROCESS`, or 2 for `FINISHED_PRODUCT`; add
        one for each of the product's ingredients with `requires_pcr` true; add a
        volume tier of 2 when `annual_volume_units` reaches 100,000, 1 when it
        reaches 10,000, and 0 below that; and add 2 when the brand's history shows
        at least one `SUBSTANTIATED` enforcement case or at least one `FAILED`
        facility audit, 0 otherwise. The total is capped at 10."

        Design: Difficulty/combinatorial_formula/required_sample_count_multi_input_tiers
        """
        ctx = create_product_under_evaluation(
            name="P2", gtin="G-P2", annual_volume_units=5000,
            ingredient_specs=(
                {"name": "A", "crop_type": "HIGH_RISK", "declared_weight_pct": 50.00},
            ),
        )
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        # min(10, 0 base + 1 pcr + 0 volume + 0 history) = 1
        assert plan["required_sample_count"] == 1


# ─── Traceability score nested rounding ─────────────────────────────────────

def _setup_scheduled_audit(api):
    brand = create_brand(name="B1", contact_email="b1@x.com")
    audit = validate_success(
        api.create_facility_audit(
            create_facility_audit_payload(brand["id"], facility_name="F1",
                                          auditor_id="aud-1"),
            ADMIN,
        ), 201)
    return brand, audit


_THREE_LOTS = [
    {"lot_code": "L1", "input_qty": 300, "recovered_qty": 287},
    {"lot_code": "L2", "input_qty": 400, "recovered_qty": 383},
    {"lot_code": "L3", "input_qty": 700, "recovered_qty": 665},
]


class TestTraceabilityScoreRounding:
    def test_per_lot_round_then_average_round(self, api):
        """PRD section 3.6: "Submission computes the `traceability_score_pct`: for
        each lot, the recovered quantity is divided by the input quantity and
        multiplied by 100, and that per-lot percentage is rounded half-up to 2
        decimal places first; the per-lot values are then averaged, and the
        average is itself rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/traceability_score_per_lot_then_average_rounding
        """
        _, audit = _setup_scheduled_audit(api)
        res = api.submit_audit_report(audit["id"], {"lots": _THREE_LOTS},
                                      _auditor_headers("aud-1"))
        submitted = validate_success(res, 200)
        # per-lot: 95.67, 95.75, 95.00 -> mean 95.4733... -> 95.47
        assert submitted["traceability_score_pct"] == pytest.approx(95.47, abs=0.001)

    def test_score_at_or_above_min_accepts_passed(self, api):
        """PRD section 3.6: "The `PASSED` decision is score-gated: the
        `traceability_score_pct` must be at least 95.00, with the boundary
        inclusive, else `ERR_TRACE_SCORE_BELOW_MIN`."

        Design: Difficulty/combinatorial_formula/traceability_score_per_lot_then_average_rounding
        """
        _, audit = _setup_scheduled_audit(api)
        validate_success(
            api.submit_audit_report(audit["id"], {"lots": _THREE_LOTS},
                                    _auditor_headers("aud-1")), 200)
        decided = validate_success(
            api.decide_audit(audit["id"], {"decision": "PASSED"}, ADMIN), 200)
        assert decided["status"] == "PASSED"


# ─── Exemption weight boundary ──────────────────────────────────────────────

class TestExemptionWeightBoundary:
    def test_weight_exactly_at_ceiling_is_exempt(self, api):
        """PRD section 3.3: "An ingredient is exempt — `is_exempt` is true —
        exactly when its `declared_weight_pct` is at or below the standard's
        `exemption_max_weight_pct`; the boundary is inclusive, so an ingredient
        declared at precisely the ceiling is exempt."
        PRD section 3.3: "Otherwise, if the ingredient requires neither PCR nor an
        affidavit, it is `EXEMPTED`."

        Design: Difficulty/boundary_precision_check/exemption_weight_at_exact_threshold
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        res = api.create_ingredient(
            {"product_id": product["id"], "name": "AtBoundary",
             "crop_type": "LOW_RISK", "declared_weight_pct": 0.50},
            make_brand_rep_headers(brand["id"]),
        )
        ing = validate_success(res, 201)
        assert ing["is_exempt"] is True
        assert ing["requires_affidavit"] is False
        assert ing["compliance_status"] == "EXEMPTED"

    def test_weight_one_cent_above_ceiling_is_not_exempt(self, api):
        """PRD section 3.3: "Paperwork obligation is broader: `requires_affidavit`
        is true for every `HIGH_RISK` ingredient, exempt or not, and for a
        `LOW_RISK` ingredient that is not exempt; a `NON_CROP` ingredient never
        requires an affidavit."
        PRD section 3.3: "Anything else is `PENDING`."

        Design: Difficulty/boundary_precision_check/exemption_weight_at_exact_threshold
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        res = api.create_ingredient(
            {"product_id": product["id"], "name": "AboveBoundary",
             "crop_type": "LOW_RISK", "declared_weight_pct": 0.51},
            make_brand_rep_headers(brand["id"]),
        )
        ing = validate_success(res, 201)
        assert ing["is_exempt"] is False
        assert ing["requires_affidavit"] is True
        assert ing["compliance_status"] == "PENDING"


# ─── PCR result boundary at the standard threshold ──────────────────────────

class TestPcrResultBoundary:
    def test_result_exactly_at_threshold_is_compliant(self, api):
        """PRD section 3.5: "Confirmation computes the `outcome`: `COMPLIANT` when
        the result is at or below the standard's `ingredient_threshold_pct` — the
        boundary is inclusive — and `NON_COMPLIANT` otherwise, stamps
        `confirmed_by_user_id`, and then fans out."

        Design: Difficulty/boundary_precision_check/pcr_result_at_exact_threshold
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"])
        ing = ctx["ingredients"][0]
        sample = confirm_sample(plan["id"], ing["id"], result_gmo_pct=0.90)
        assert sample["outcome"] == "COMPLIANT"

    def test_result_one_cent_above_threshold_is_noncompliant(self, api):
        """PRD section 3.5: "The owning ingredient's `compliance_status` is
        recomputed, and a `NON_COMPLIANT` outcome forces the ingredient to
        `NON_COMPLIANT` regardless of everything else."
        PRD section 3.5: "For each ingredient, take the maximum `result_gmo_pct`
        among its `CONFIRMED` samples — invalidated results are excluded — and
        weight it by `declared_weight_pct`."

        Design: Difficulty/boundary_precision_check/pcr_result_at_exact_threshold
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"])
        ing = ctx["ingredients"][0]
        s1 = collect_sample(plan["id"], ing["id"])
        s2 = collect_sample(plan["id"], ing["id"])
        validate_success(
            api.record_sample_result(s1["id"], {"result_gmo_pct": 0.90}, LAB_1), 200)
        validate_success(api.confirm_sample(s1["id"], LAB_2), 200)
        validate_success(
            api.record_sample_result(s2["id"], {"result_gmo_pct": 0.91}, LAB_1), 200)
        confirmed = validate_success(api.confirm_sample(s2["id"], LAB_2), 200)
        assert confirmed["outcome"] == "NON_COMPLIANT"

        ing_after = validate_success(api.get_ingredient(ing["id"], ADMIN), 200)
        assert ing_after["compliance_status"] == "NON_COMPLIANT"
        product = get_product(ctx["product"]["id"])
        # MAX over CONFIRMED = 0.91; 100.00 x 0.91 = 91.00
        assert product["confirmed_exposure_pct"] == pytest.approx(91.00, abs=0.01)


# ─── Corner: exposure MAX resolution and INVALIDATED exclusion ───────────────

class TestExposureMaxAndInvalidatedExclusion:
    def test_max_confirmed_and_invalidate_restores(self, api):
        """PRD section 3.5: "For each ingredient, take the maximum
        `result_gmo_pct` among its `CONFIRMED` samples — invalidated results are
        excluded — and weight it by `declared_weight_pct`."
        PRD section 3.5: "Invalidating a `CONFIRMED` sample resets its `outcome`
        to null, decrements the plan's `confirmed_sample_count` by one, reopens
        the plan from `COMPLETED` to `ACTIVE` if the count has fallen below the
        requirement, and recomputes both the ingredient's standing and the
        product's exposure"

        Design: Corner/calculations/exposure_uses_max_confirmed_result_and_excludes_invalidated
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"])
        ing = ctx["ingredients"][0]
        s1 = collect_sample(plan["id"], ing["id"])
        s2 = collect_sample(plan["id"], ing["id"])

        validate_success(api.record_sample_result(s1["id"], {"result_gmo_pct": 0.40}, LAB_1), 200)
        validate_success(api.confirm_sample(s1["id"], LAB_2), 200)
        product = get_product(ctx["product"]["id"])
        assert product["confirmed_exposure_pct"] == pytest.approx(40.00, abs=0.01)

        validate_success(api.record_sample_result(s2["id"], {"result_gmo_pct": 0.70}, LAB_1), 200)
        validate_success(api.confirm_sample(s2["id"], LAB_2), 200)
        product = get_product(ctx["product"]["id"])
        assert product["confirmed_exposure_pct"] == pytest.approx(70.00, abs=0.01)

        validate_success(api.invalidate_sample(s2["id"], LAB_1), 200)
        product = get_product(ctx["product"]["id"])
        assert product["confirmed_exposure_pct"] == pytest.approx(40.00, abs=0.01)


# ─── Corner: PROBATION boundary at exactly 20 lifetime points ────────────────

class TestBrandProbationBoundary:
    def test_probation_flips_at_exactly_twenty_points(self, api):
        """PRD section 3.8: "and `standing_status` flips to `PROBATION` exactly
        when the lifetime total reaches 20 or more, otherwise `GOOD_STANDING`."
        PRD section 3.8: "Products without a license — those still `DRAFT`,
        `SUBMITTED`, `UNDER_EVALUATION`, or `REJECTED` — keep their enrollment
        state through all of this; only the penalty points land."

        Design: Corner/calculations/brand_probation_at_twenty_points_boundary
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        p1 = create_product(brand, std, name="P1", gtin="G-P1")
        p2 = create_product(brand, std, name="P2", gtin="G-P2")

        case1 = open_case(p1["id"], source="RETEST_FAILURE", description="d")
        substantiate_case(case1["id"], sanction="LICENSE_SUSPENSION")
        brand_after = validate_success(api.get_brand(brand["id"], ADMIN), 200)
        assert brand_after["lifetime_penalty_points"] == 15
        assert brand_after["standing_status"] == "GOOD_STANDING"

        case2 = open_case(p2["id"], source="CONSUMER_COMPLAINT", description="d")
        substantiate_case(case2["id"], sanction="WARNING")
        brand_after = validate_success(api.get_brand(brand["id"], ADMIN), 200)
        assert brand_after["lifetime_penalty_points"] == 20
        assert brand_after["standing_status"] == "PROBATION"

        p1_after = validate_success(api.get_product(p1["id"], ADMIN), 200)
        assert p1_after["enrollment_status"] == "DRAFT"


# ─── Corner: traceability PASSED gate boundary ───────────────────────────────

class TestTraceScorePassedGate:
    def test_exactly_min_passes_and_below_blocks(self, api):
        """PRD section 3.6: "The `PASSED` decision is score-gated: the
        `traceability_score_pct` must be at least 95.00, with the boundary
        inclusive, else `ERR_TRACE_SCORE_BELOW_MIN`."
        PRD section 3.6: "The `FAILED` decision is always allowed regardless of
        score."

        Design: Corner/calculations/trace_score_exactly_min_passes_and_below_blocks
        """
        brand, a1 = _setup_scheduled_audit(api)
        res = api.submit_audit_report(
            a1["id"],
            {"lots": [{"lot_code": "L1", "input_qty": 200, "recovered_qty": 190}]},
            _auditor_headers("aud-1"),
        )
        assert validate_success(res, 200)["traceability_score_pct"] == pytest.approx(95.00, abs=0.001)
        decided = validate_success(
            api.decide_audit(a1["id"], {"decision": "PASSED"}, ADMIN), 200)
        assert decided["status"] == "PASSED"

        # A1 terminal, so the capacity gate frees the facility for A2.
        a2 = validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"], facility_name="F1",
                                              auditor_id="aud-1",
                                              scheduled_date="2026-09-01T00:00:00Z"),
                ADMIN,
            ), 201)
        res = api.submit_audit_report(
            a2["id"],
            {"lots": [{"lot_code": "L1", "input_qty": 200, "recovered_qty": 189.98}]},
            _auditor_headers("aud-1"),
        )
        assert validate_success(res, 200)["traceability_score_pct"] == pytest.approx(94.99, abs=0.001)
        err_res = api.decide_audit(a2["id"], {"decision": "PASSED"}, ADMIN)
        validate_error(err_res, ApiErrorId.ERR_TRACE_SCORE_BELOW_MIN.value)
        failed = validate_success(
            api.decide_audit(a2["id"], {"decision": "FAILED"}, ADMIN), 200)
        assert failed["status"] == "FAILED"
