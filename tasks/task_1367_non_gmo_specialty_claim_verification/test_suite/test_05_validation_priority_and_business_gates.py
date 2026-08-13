"""Validation-priority pairs and isolated business-gate violations."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_brand_rep_headers, NON_EXISTENT_UUID,
    create_standard, create_brand, create_product, add_ingredient,
    add_accepted_affidavit, create_product_under_evaluation, create_plan,
    collect_sample, confirm_sample, create_passed_audit, create_verified_product,
    open_case, set_clock, get_product,
    create_ingredient_payload, create_sample_payload,
    create_sampling_plan_payload,
)

ADMIN = TEST_USERS["verifier_admin_headers"]
LAB_1 = TEST_USERS["lab_analyst_1_headers"]


# ─── Difficulty: priority pair — state beats business_referential ────────────

def _setup_superseded_plan(api):
    """Product PA UNDER_EVALUATION; plan1 created then superseded by plan2, so
    plan1 is CANCELLED. Returns (ctx, plan1, plan2)."""
    ctx = create_product_under_evaluation(name="PA", gtin="G-PA")
    plan1 = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
    plan2 = create_plan(ctx["product"]["id"], risk_point="IN_PROCESS")
    return ctx, plan1, plan2


class TestSampleCreatePriority:
    def test_cancelled_plan_and_foreign_ingredient_yields_plan_not_active(self, api):
        """PRD section 2.9: "then state-machine from-state preconditions
        (`ERR_PRODUCT_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`,
        `ERR_SAMPLE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_CASE_NOT_OPEN`,
        `ERR_AFFIDAVIT_NOT_REVIEWABLE`). Business referential integrity comes next
        (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_NO_INGREDIENTS`)"
        PRD section 3.5: "The plan must be `ACTIVE` — collecting against a
        completed or cancelled plan fails with `ERR_PLAN_NOT_ACTIVE` — the
        ingredient must belong to the plan's product, else
        `ERR_CROSS_REFERENCE_MISMATCH`"

        Design: Difficulty/priority_pair_validation_conflict/sample_create_state_beats_referential
        """
        ctx, plan1, _ = _setup_superseded_plan(api)
        # Second product with its own HIGH_RISK ingredient (foreign to the plan).
        pb = create_product(ctx["brand"], ctx["standard"], name="PB", gtin="G-PB")
        ing_b = add_ingredient(pb["id"], ctx["brand"]["id"], name="Corn",
                               declared_weight_pct=50.00)
        res = api.create_sample(
            create_sample_payload(plan1["id"], ing_b["id"]), LAB_1)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)

    def test_cancelled_plan_alone_yields_plan_not_active(self, api):
        """PRD section 3.5: "The plan must be `ACTIVE` — collecting against a
        completed or cancelled plan fails with `ERR_PLAN_NOT_ACTIVE`"

        Design: Difficulty/priority_pair_validation_conflict/sample_create_state_beats_referential
        """
        ctx, plan1, _ = _setup_superseded_plan(api)
        ing_own = ctx["ingredients"][0]
        res = api.create_sample(
            create_sample_payload(plan1["id"], ing_own["id"]), LAB_1)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


# ─── Difficulty: priority pair — business_safety beats business_temporal ─────

def _setup_noncompliant_with_passed_audit(api):
    """UNDER_EVALUATION product whose plan is COMPLETED via one sample confirmed
    NON_COMPLIANT (1.50); brand has a PASSED audit decided at the boot clock.
    Affidavit stays current (valid_until 2028-06-01)."""
    ctx = create_product_under_evaluation(
        name="P1", gtin="G-P1", affidavit_valid_until="2028-06-01T00:00:00Z")
    plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
    confirm_sample(plan["id"], ctx["ingredients"][0]["id"], result_gmo_pct=1.50)
    create_passed_audit(ctx["brand"]["id"])
    return ctx


class TestDecideVerifyPriority:
    def test_noncompliant_and_stale_audit_yields_noncompliant_error(self, api):
        """PRD section 3.7: "After the state check — the product must be
        `UNDER_EVALUATION` — the chain runs: no ingredient may be `NON_COMPLIANT`,
        else `ERR_NON_COMPLIANT_RESULTS_EXIST`; then no ingredient may be
        `PENDING`, else `ERR_INGREDIENTS_PENDING`; then every sampling plan of the
        product that is not `CANCELLED` must be `COMPLETED`, else
        `ERR_INCOMPLETE_SAMPLING`; then at least one passed facility audit must
        exist for the brand, else `ERR_AUDIT_NOT_PASSED`; then no enforcement case
        may be open against the product, else `ERR_OPEN_ENFORCEMENT_CASE`; then
        the brand's `rolling_penalty_points` must be below 10, else
        `ERR_BRAND_RECENT_PENALTIES`; and finally the most recent passed audit
        must still be fresh per §3.6, else `ERR_AUDIT_STALE`."

        Design: Difficulty/priority_pair_validation_conflict/decide_verify_safety_beats_temporal
        """
        ctx = _setup_noncompliant_with_passed_audit(api)
        # Audit decided 2026-08-01 + 12 months validity = 2027-08-01; at
        # 2027-09-05 the audit is stale while the NON_COMPLIANT ingredient stands.
        set_clock("2027-09-05T00:00:00Z")
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_NON_COMPLIANT_RESULTS_EXIST.value)

    def test_noncompliant_alone_yields_noncompliant_error(self, api):
        """PRD section 3.7: "no ingredient may be `NON_COMPLIANT`, else
        `ERR_NON_COMPLIANT_RESULTS_EXIST`"

        Design: Difficulty/priority_pair_validation_conflict/decide_verify_safety_beats_temporal
        """
        ctx = _setup_noncompliant_with_passed_audit(api)
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_NON_COMPLIANT_RESULTS_EXIST.value)


# ─── Corner: existence beats state ───────────────────────────────────────────

class TestExistencePriority:
    def test_submit_nonexistent_product_returns_not_found(self, api):
        """PRD section 2.9: "Next comes role authorization (`ERR_FORBIDDEN_ROLE`),
        then existence: path identifiers are validated left to right and
        body-supplied foreign keys — `brand_id`, `standard_id`, `product_id`,
        `ingredient_id`, `sampling_plan_id` — must resolve to existing resources,
        else `ERR_NOT_FOUND`."

        Design: Corner/validations/existence_beats_state_on_missing_product_submit
        """
        res = api.submit_product(
            NON_EXISTENT_UUID, make_brand_rep_headers(NON_EXISTENT_UUID))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Corner: isolated decide-VERIFIED gate violations ────────────────────────

def _setup_evidence_complete_no_audit(api):
    """Product evidence-complete (COMPLIANT ingredient, COMPLETED plan) but the
    brand has no PASSED audit."""
    ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
    plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
    confirm_sample(plan["id"], ctx["ingredients"][0]["id"], result_gmo_pct=0.10)
    return ctx


class TestDecideVerifyGates:
    def test_no_passed_audit_returns_audit_not_passed(self, api):
        """PRD section 3.7: "then at least one passed facility audit must exist
        for the brand, else `ERR_AUDIT_NOT_PASSED`"

        Design: Corner/validations/decide_verify_no_passed_audit_returns_audit_not_passed
        """
        ctx = _setup_evidence_complete_no_audit(api)
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_AUDIT_NOT_PASSED.value)

    def test_stale_audit_returns_audit_stale(self, api):
        """PRD section 3.7: "and finally the most recent passed audit must still
        be fresh per §3.6, else `ERR_AUDIT_STALE`."
        PRD section 3.6: "a passed audit stays fresh for the standard's
        `audit_validity_months` calendar months after its `decided_at`."

        Design: Corner/validations/decide_verify_stale_audit_returns_audit_stale
        """
        ctx = create_product_under_evaluation(
            name="P1", gtin="G-P1", affidavit_valid_until="2028-06-01T00:00:00Z")
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        confirm_sample(plan["id"], ctx["ingredients"][0]["id"], result_gmo_pct=0.10)
        create_passed_audit(ctx["brand"]["id"])
        # Audit decided 2026-08-01; 12-month validity ends 2027-08-01.
        set_clock("2027-09-05T00:00:00Z")
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_AUDIT_STALE.value)

    def test_incomplete_plan_returns_incomplete_sampling(self, api):
        """PRD section 3.7: "then every sampling plan of the product that is not
        `CANCELLED` must be `COMPLETED`, else `ERR_INCOMPLETE_SAMPLING`"

        Design: Corner/validations/decide_verify_incomplete_plan_returns_incomplete_sampling
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        # IN_PROCESS: base 1 + 1 pcr ingredient = required 2.
        plan = create_plan(ctx["product"]["id"], risk_point="IN_PROCESS")
        assert plan["required_sample_count"] == 2
        confirm_sample(plan["id"], ctx["ingredients"][0]["id"], result_gmo_pct=0.10)
        plan_after = validate_success(api.get_sampling_plan(plan["id"], ADMIN), 200)
        assert plan_after["confirmed_sample_count"] == 1
        assert plan_after["status"] == "ACTIVE"
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INCOMPLETE_SAMPLING.value)

    def test_pending_ingredient_returns_ingredients_pending(self, api):
        """PRD section 3.7: "then no ingredient may be `PENDING`, else
        `ERR_INGREDIENTS_PENDING`"
        PRD section 2.6: "Each `ACCEPTED` affidavit whose `valid_until` is at or
        before the new current time transitions to `EXPIRED`, and the owning
        ingredient's compliance standing is recomputed — an ingredient that loses
        its last current affidavit may drop from `COMPLIANT` to `PENDING`."

        Design: Corner/validations/decide_verify_pending_ingredients_returns_ingredients_pending
        """
        # Exempt HIGH_RISK (0.40 <= 0.5): affidavit-only requirement.
        ctx = create_product_under_evaluation(
            name="P1", gtin="G-P1",
            ingredient_specs=({"name": "SoyLecithin", "crop_type": "HIGH_RISK",
                               "declared_weight_pct": 0.40},),
            affidavit_valid_until="2026-09-01T00:00:00Z",
        )
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        assert plan["required_sample_count"] == 0
        assert plan["status"] == "COMPLETED"
        # Clock past the affidavit window: ingredient drops to PENDING.
        set_clock("2026-09-05T00:00:00Z")
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INGREDIENTS_PENDING.value)

    def test_open_case_returns_open_enforcement_case(self, api):
        """PRD section 3.7: "then no enforcement case may be open against the
        product, else `ERR_OPEN_ENFORCEMENT_CASE`"

        Design: Corner/validations/decide_verify_open_case_returns_open_enforcement_case
        """
        ctx = _setup_evidence_complete_no_audit(api)
        create_passed_audit(ctx["brand"]["id"])
        open_case(ctx["product"]["id"], source="MARKETPLACE_MONITOR", description="d")
        res = api.decide_product(ctx["product"]["id"], {"decision": "VERIFIED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_OPEN_ENFORCEMENT_CASE.value)


# ─── Corner: uniqueness and aggregate constraints ────────────────────────────

class TestUniquenessAndWeightConstraints:
    def test_duplicate_gtin_same_standard_rejected_other_standard_ok(self, api):
        """PRD section 3.2: "The `gtin` must be unique among all products enrolled
        under the same `standard_id`; a collision is rejected with
        `ERR_PRODUCT_GTIN_EXISTS`."

        Design: Corner/validations/duplicate_gtin_same_standard_rejected
        """
        std = create_standard()
        std2 = create_standard(claim_code="GF", name="Gluten-Free",
                               ingredient_threshold_pct=0.5)
        brand = create_brand(name="B1", contact_email="b1@x.com")
        rep = make_brand_rep_headers(brand["id"])
        create_product(brand, std, name="P1", gtin="G-DUP")

        res = api.create_product(
            {"brand_id": brand["id"], "standard_id": std["id"], "name": "P2",
             "gtin": "G-DUP", "annual_volume_units": 100},
            rep,
        )
        validate_error(res, ApiErrorId.ERR_PRODUCT_GTIN_EXISTS.value)

        res2 = api.create_product(
            {"brand_id": brand["id"], "standard_id": std2["id"], "name": "P3",
             "gtin": "G-DUP", "annual_volume_units": 100},
            rep,
        )
        validate_success(res2, 201)

    def test_weight_sum_over_one_hundred_rejected(self, api):
        """PRD section 3.3: "The share must be greater than 0 and at most 100, and
        the running total across the product's ingredients must never exceed 100;
        an addition that would push the sum over the top is rejected with
        `ERR_WEIGHT_SUM_EXCEEDED`, while an out-of-range share is
        `ERR_VALIDATION`."

        Design: Corner/validations/weight_sum_over_one_hundred_rejected
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        rep = make_brand_rep_headers(brand["id"])
        validate_success(
            api.create_ingredient(
                create_ingredient_payload(product["id"], name="A",
                                          crop_type="NON_CROP",
                                          declared_weight_pct=60.00), rep), 201)
        validate_success(
            api.create_ingredient(
                create_ingredient_payload(product["id"], name="B",
                                          crop_type="NON_CROP",
                                          declared_weight_pct=40.00), rep), 201)
        res = api.create_ingredient(
            create_ingredient_payload(product["id"], name="C",
                                      crop_type="NON_CROP",
                                      declared_weight_pct=0.01), rep)
        validate_error(res, ApiErrorId.ERR_WEIGHT_SUM_EXCEEDED.value)


# ─── Corner: sample referential and testability gates ────────────────────────

class TestSampleCreationGates:
    def test_foreign_ingredient_returns_cross_reference_mismatch(self, api):
        """PRD section 3.5: "The plan must be `ACTIVE` — collecting against a
        completed or cancelled plan fails with `ERR_PLAN_NOT_ACTIVE` — the
        ingredient must belong to the plan's product, else
        `ERR_CROSS_REFERENCE_MISMATCH`, and the ingredient must actually require
        PCR, else `ERR_INGREDIENT_NOT_TESTABLE`."

        Design: Corner/validations/sample_with_foreign_ingredient_returns_cross_reference
        """
        ctx = create_product_under_evaluation(name="PA", gtin="G-PA")
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        pb = create_product(ctx["brand"], ctx["standard"], name="PB", gtin="G-PB")
        ing_b = add_ingredient(pb["id"], ctx["brand"]["id"], name="Corn",
                               declared_weight_pct=50.00)
        res = api.create_sample(
            create_sample_payload(plan["id"], ing_b["id"]), LAB_1)
        validate_error(res, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH.value)

    def test_non_pcr_ingredient_returns_not_testable(self, api):
        """PRD section 3.5: "and the ingredient must actually require PCR, else
        `ERR_INGREDIENT_NOT_TESTABLE`."
        PRD section 3.3: "Testing obligation follows: `requires_pcr` is true only
        for a `HIGH_RISK` crop that is not exempt."

        Design: Corner/validations/sample_on_non_pcr_ingredient_rejected
        """
        ctx = create_product_under_evaluation(
            name="P1", gtin="G-P1",
            ingredient_specs=({"name": "Oats", "crop_type": "LOW_RISK",
                               "declared_weight_pct": 100.00},),
        )
        plan = create_plan(ctx["product"]["id"], risk_point="FINISHED_PRODUCT")
        assert plan["status"] == "ACTIVE"
        res = api.create_sample(
            create_sample_payload(plan["id"], ctx["ingredients"][0]["id"]), LAB_1)
        validate_error(res, ApiErrorId.ERR_INGREDIENT_NOT_TESTABLE.value)
