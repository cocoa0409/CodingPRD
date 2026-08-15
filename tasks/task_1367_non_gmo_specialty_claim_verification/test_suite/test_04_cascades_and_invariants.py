"""Cross-entity cascade tests and compensating-invariant tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_brand_rep_headers,
    create_standard, create_brand, create_product, add_ingredient,
    add_accepted_affidavit, create_product_under_evaluation, create_plan,
    collect_sample, confirm_sample, create_verified_product,
    open_case, substantiate_case, set_clock, get_product,
)

ADMIN = TEST_USERS["verifier_admin_headers"]
LAB_1 = TEST_USERS["lab_analyst_1_headers"]
LAB_2 = TEST_USERS["lab_analyst_2_headers"]


def _get_license(api, product_id):
    licenses = validate_success(
        api.list_licenses(ADMIN, params={"product_id": product_id}), 200)
    assert len(licenses) == 1, f"expected exactly one license, got {len(licenses)}"
    return licenses[0]


# ─── Enforcement suspension cascade (license -> product -> brand) ────────────

class TestEnforcementSuspensionCascade:
    def test_suspension_suspends_license_and_product(self, api):
        """PRD section 3.8: "A `LICENSE_SUSPENSION` pushes the product's `ACTIVE`
        license to `SUSPENDED` with `suspend_reason` of `ENFORCEMENT` and
        `suspended_at` stamped to now — and if the license was already `SUSPENDED`
        for a scope change, `suspended_at` resets to now and the reason becomes
        `ENFORCEMENT` — then moves a `VERIFIED` or `RENEWAL_DUE` product to
        `SUSPENDED`, and finally recomputes the brand's `verified_product_count`."

        Design: Difficulty/transitive_cascade/enforcement_suspension_license_product_brand_cascade
        """
        ctx = create_verified_product()
        case = open_case(ctx["product"]["id"], source="RETEST_FAILURE",
                         description="market retest above threshold")
        substantiate_case(case["id"], sanction="LICENSE_SUSPENSION")

        lic = _get_license(api, ctx["product"]["id"])
        assert lic["status"] == "SUSPENDED"
        assert lic["suspend_reason"] == "ENFORCEMENT"
        # suspended_at stamped to the logical now (2026-08-01T00:00:00Z at boot)
        assert str(lic["suspended_at"]).startswith("2026-08-01T00:00:00")

        product = get_product(ctx["product"]["id"])
        assert product["enrollment_status"] == "SUSPENDED"

    def test_suspension_recomputes_brand_counters(self, api):
        """PRD section 2.10: "A brand's `verified_product_count` is always the
        count of its products whose `enrollment_status` is `VERIFIED` or
        `RENEWAL_DUE`; any transition into or out of those states recomputes it."
        PRD section 3.8: "fixes the case's `penalty_points` at 5 for a warning, 15
        for a suspension, and 25 for a revocation; while open or once dismissed, a
        case's `penalty_points` remain zero."
        PRD section 3.8: "the case's points add into the brand's
        `lifetime_penalty_points`, an all-time sum over `SUBSTANTIATED` cases on
        the brand's products"

        Design: Difficulty/transitive_cascade/enforcement_suspension_license_product_brand_cascade
        """
        ctx = create_verified_product()
        brand_before = validate_success(api.get_brand(ctx["brand"]["id"], ADMIN), 200)
        assert brand_before["verified_product_count"] == 1

        case = open_case(ctx["product"]["id"], source="RETEST_FAILURE",
                         description="market retest above threshold")
        resolved = substantiate_case(case["id"], sanction="LICENSE_SUSPENSION")
        assert resolved["penalty_points"] == 15

        brand_after = validate_success(api.get_brand(ctx["brand"]["id"], ADMIN), 200)
        assert brand_after["verified_product_count"] == 0
        assert brand_after["lifetime_penalty_points"] == 15
        assert brand_after["standing_status"] == "GOOD_STANDING"


# ─── NON_COMPLIANT confirm cascade (sample -> ingredient -> product) ─────────

def _setup_two_ingredient_product(api):
    """UNDER_EVALUATION product with A HIGH_RISK 40% (affidavit accepted) and
    B NON_CROP 60%; INGREDIENT_INTAKE plan (required 1)."""
    ctx = create_product_under_evaluation(
        name="P1", gtin="G-P1",
        ingredient_specs=(
            {"name": "A", "crop_type": "HIGH_RISK", "declared_weight_pct": 40.00},
            {"name": "B", "crop_type": "NON_CROP", "declared_weight_pct": 60.00},
        ),
    )
    plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
    return ctx, plan


class TestNoncompliantConfirmCascade:
    def test_noncompliant_outcome_forces_ingredient_noncompliant(self, api):
        """PRD section 3.5: "Confirmation computes the `outcome`: `COMPLIANT` when
        the result is at or below the standard's `ingredient_threshold_pct` — the
        boundary is inclusive — and `NON_COMPLIANT` otherwise"
        PRD section 3.5: "The owning ingredient's `compliance_status` is
        recomputed, and a `NON_COMPLIANT` outcome forces the ingredient to
        `NON_COMPLIANT` regardless of everything else."

        Design: Difficulty/transitive_cascade/noncompliant_confirm_ingredient_product_cascade
        """
        ctx, plan = _setup_two_ingredient_product(api)
        ing_a = ctx["ingredients"][0]
        sample = collect_sample(plan["id"], ing_a["id"])
        validate_success(
            api.record_sample_result(sample["id"], {"result_gmo_pct": 1.50}, LAB_1), 200)
        confirmed = validate_success(api.confirm_sample(sample["id"], LAB_2), 200)
        assert confirmed["outcome"] == "NON_COMPLIANT"

        ing_after = validate_success(api.get_ingredient(ing_a["id"], ADMIN), 200)
        assert ing_after["compliance_status"] == "NON_COMPLIANT"

    def test_noncompliant_confirm_recomputes_product_exposure(self, api):
        """PRD section 3.5: "For each ingredient, take the maximum
        `result_gmo_pct` among its `CONFIRMED` samples — invalidated results are
        excluded — and weight it by `declared_weight_pct`."
        PRD section 3.5: "The product's two exposure estimates are recomputed in
        turn."

        Design: Difficulty/transitive_cascade/noncompliant_confirm_ingredient_product_cascade
        """
        ctx, plan = _setup_two_ingredient_product(api)
        ing_a = ctx["ingredients"][0]
        confirm_sample(plan["id"], ing_a["id"], result_gmo_pct=1.50)
        product = get_product(ctx["product"]["id"])
        # 40.00 x 1.50 = 60.00; NON_CROP contributes 0 in both variants.
        assert product["confirmed_exposure_pct"] == pytest.approx(60.00, abs=0.01)
        assert product["provisional_exposure_pct"] == pytest.approx(60.00, abs=0.01)


# ─── License suspension + reinstate: remaining-validity conservation ─────────

def _setup_suspended_via_enforcement(api):
    """VERIFIED product suspended by a LICENSE_SUSPENSION substantiated at
    2026-08-31 (clock set before the resolve). Returns the context."""
    ctx = create_verified_product()
    case = open_case(ctx["product"]["id"], source="RETEST_FAILURE",
                     description="retest above threshold")
    set_clock("2026-08-31T00:00:00Z")
    substantiate_case(case["id"], sanction="LICENSE_SUSPENSION")
    return ctx


class TestLicenseValidityConservation:
    def test_reinstate_restores_product_and_clears_suspension(self, api):
        """PRD section 3.7: "Reinstating a product — a `VerifierAdmin` action
        requiring the product be `SUSPENDED` with no open enforcement case —
        moves it from `SUSPENDED` back to `VERIFIED` and reactivates its license."
        PRD section 3.7: "Reinstatement clears `suspended_at` and `suspend_reason`
        to null and raises the brand's `verified_product_count` by one."

        Design: Difficulty/compensating_invariant/license_suspension_reinstate_validity_conserved
        """
        ctx = _setup_suspended_via_enforcement(api)
        set_clock("2026-10-10T00:00:00Z")
        res = api.reinstate_product(ctx["product"]["id"], ADMIN)
        product = validate_success(res, 200)
        assert product["enrollment_status"] == "VERIFIED"

        lic = _get_license(api, ctx["product"]["id"])
        assert lic["status"] == "ACTIVE"
        assert lic["suspended_at"] is None
        assert lic["suspend_reason"] is None

        brand = validate_success(api.get_brand(ctx["brand"]["id"], ADMIN), 200)
        assert brand["verified_product_count"] == 1

    def test_reinstate_extends_valid_until_by_suspension_duration(self, api):
        """PRD section 3.7: "When the `suspend_reason` is `ENFORCEMENT`, the
        license's `valid_until` is extended by the exact suspension duration — the
        elapsed time from `suspended_at` to the reinstatement instant — so the
        remaining validity is conserved across the suspend-and-reinstate pair; a
        `SCOPE_CHANGE` suspension earns no such extension."

        Design: Difficulty/compensating_invariant/license_suspension_reinstate_validity_conserved
        """
        ctx = _setup_suspended_via_enforcement(api)
        set_clock("2026-10-10T00:00:00Z")
        validate_success(api.reinstate_product(ctx["product"]["id"], ADMIN), 200)
        lic = _get_license(api, ctx["product"]["id"])
        # issued 2026-08-01 + 365 days = 2027-08-01; suspension 2026-08-31 ->
        # 2026-10-10 is exactly 40 days, so valid_until becomes 2027-09-10.
        assert str(lic["valid_until"]).startswith("2027-09-10T00:00:00")


# ─── Plan confirmed_sample_count conservation across confirm+invalidate ──────

class TestPlanCountConservation:
    def test_confirm_raises_count_and_completes_plan(self, api):
        """PRD section 3.5: "A plan's `confirmed_sample_count` tracks how many of
        its samples currently sit in `CONFIRMED`; when that count reaches the
        required number — at or above, the boundary is inclusive — the plan moves
        from `ACTIVE` to `COMPLETED`"

        Design: Difficulty/compensating_invariant/plan_confirm_invalidate_count_conserved
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        assert plan["required_sample_count"] == 1
        confirm_sample(plan["id"], ctx["ingredients"][0]["id"], result_gmo_pct=0.10)
        plan_after = validate_success(api.get_sampling_plan(plan["id"], ADMIN), 200)
        assert plan_after["confirmed_sample_count"] == 1
        assert plan_after["status"] == "COMPLETED"

    def test_confirm_then_invalidate_restores_pre_confirm_state(self, api):
        """PRD section 3.5: "A confirm followed by an invalidate of the same
        sample therefore leaves the count exactly where it was before the confirm,
        and `INVALIDATED` samples never count toward anything."
        PRD section 3.5: "Under the evidence-only `confirmed_exposure_pct`, an
        ingredient with no confirmed result contributes zero."

        Design: Difficulty/compensating_invariant/plan_confirm_invalidate_count_conserved
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        ing_id = ctx["ingredients"][0]["id"]
        sample = confirm_sample(plan["id"], ing_id, result_gmo_pct=0.10)
        validate_success(api.invalidate_sample(sample["id"], LAB_1), 200)

        plan_after = validate_success(api.get_sampling_plan(plan["id"], ADMIN), 200)
        assert plan_after["confirmed_sample_count"] == 0
        assert plan_after["status"] == "ACTIVE"

        product = get_product(ctx["product"]["id"])
        assert product["confirmed_exposure_pct"] == pytest.approx(0.00, abs=0.01)


# ─── Corner: decide VERIFIED cascade-creates the label license ───────────────

class TestLicenseIssuance:
    def test_decide_verified_creates_discoverable_license(self, api):
        """PRD section 3.7: "If the product has no license yet, one is created
        `ACTIVE` with `valid_from` set to the current time and `valid_until` set
        `license_term_days` days later; its `license_code` is `LIC-` followed by a
        six-digit zero-padded issuance sequence beginning at `LIC-000001`, a
        deterministic counter not derived from the license `id`."
        PRD section 2.10: "A brand's `verified_product_count` is always the count
        of its products whose `enrollment_status` is `VERIFIED` or `RENEWAL_DUE`"

        Design: Corner/endpoints/decide_verified_creates_license_discoverable
        """
        ctx = create_verified_product()
        assert ctx["product"]["enrollment_status"] == "VERIFIED"

        lic = _get_license(api, ctx["product"]["id"])
        assert lic["status"] == "ACTIVE"
        assert lic["license_code"] == "LIC-000001"
        assert str(lic["valid_from"]).startswith("2026-08-01T00:00:00")
        assert str(lic["valid_until"]).startswith("2027-08-01T00:00:00")

        brand = validate_success(api.get_brand(ctx["brand"]["id"], ADMIN), 200)
        assert brand["verified_product_count"] == 1
