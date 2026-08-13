"""State-machine cycle tests and logical-clock sweep tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_brand_rep_headers, NON_EXISTENT_UUID,
    create_standard, create_brand, create_product, add_ingredient,
    add_accepted_affidavit, create_product_under_evaluation, create_plan,
    collect_sample, confirm_sample, create_passed_audit, create_verified_product,
    open_case, substantiate_case, set_clock, get_product,
    create_affidavit_payload, create_facility_audit_payload,
    create_audit_report_payload, create_enforcement_case_payload,
)

ADMIN = TEST_USERS["verifier_admin_headers"]
LAB_1 = TEST_USERS["lab_analyst_1_headers"]
LAB_2 = TEST_USERS["lab_analyst_2_headers"]


# ─── Product reject/resubmit cycle ───────────────────────────────────────────

def _setup_non_crop_under_evaluation(api):
    """Product with one NON_CROP 100% ingredient (no affidavit needed),
    walked to UNDER_EVALUATION."""
    return create_product_under_evaluation(
        name="P1", gtin="G-P1",
        ingredient_specs=({"name": "Salt", "crop_type": "NON_CROP",
                           "declared_weight_pct": 100.00},),
        with_affidavits=False,
    )


class TestProductRejectResubmitCycle:
    def test_rejected_decision_stores_reason(self, api):
        """PRD section 3.2: "A `REJECTED` decision requires a non-empty
        `rejection_reason`, which is stored on the product; omitting it is a
        shape error."

        Design: Difficulty/non_linear_state_machine/product_reject_resubmit_cycle
        """
        ctx = _setup_non_crop_under_evaluation(api)
        res = api.decide_product(
            ctx["product"]["id"],
            {"decision": "REJECTED", "rejection_reason": "incomplete dossier"},
            ADMIN,
        )
        decided = validate_success(res, 200)
        assert decided["enrollment_status"] == "REJECTED"
        assert decided["rejection_reason"] == "incomplete dossier"

    def test_resubmit_clears_reason_and_closes_cycle(self, api):
        """PRD section 3.2: "Rejection is not terminal: the brand's representative
        may resubmit, moving the product from `REJECTED` back to `SUBMITTED`."
        PRD section 3.2: "Resubmission clears `rejection_reason` to null and
        re-checks affidavit currency under exactly the same rule as the original
        submission, so a lapsed affidavit surfaces as `ERR_AFFIDAVIT_MISSING`
        once again."

        Design: Difficulty/non_linear_state_machine/product_reject_resubmit_cycle
        """
        ctx = _setup_non_crop_under_evaluation(api)
        validate_success(
            api.decide_product(
                ctx["product"]["id"],
                {"decision": "REJECTED", "rejection_reason": "incomplete dossier"},
                ADMIN,
            ), 200)
        res = api.resubmit_product(
            ctx["product"]["id"], make_brand_rep_headers(ctx["brand"]["id"]))
        resubmitted = validate_success(res, 200)
        assert resubmitted["enrollment_status"] == "SUBMITTED"
        assert resubmitted["rejection_reason"] is None


# ─── SamplingPlan auto-complete / invalidate-reopen cycle ────────────────────

def _setup_plan_required_one(api):
    """UNDER_EVALUATION product, HIGH_RISK 100% ingredient with ACCEPTED
    affidavit, INGREDIENT_INTAKE plan with required_sample_count == 1."""
    ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
    plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
    assert plan["required_sample_count"] == 1
    return ctx, plan


class TestPlanCompletionCycle:
    def test_confirm_at_required_count_completes_plan(self, api):
        """PRD section 3.5: "A plan's `confirmed_sample_count` tracks how many of
        its samples currently sit in `CONFIRMED`; when that count reaches the
        required number — at or above, the boundary is inclusive — the plan moves
        from `ACTIVE` to `COMPLETED`, and if invalidation later drops the count
        below the requirement, a completed plan reopens to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/plan_auto_complete_and_invalidate_reopen_cycle
        """
        ctx, plan = _setup_plan_required_one(api)
        confirm_sample(plan["id"], ctx["ingredients"][0]["id"], result_gmo_pct=0.10)
        plan_after = validate_success(api.get_sampling_plan(plan["id"], ADMIN), 200)
        assert plan_after["status"] == "COMPLETED"
        assert plan_after["confirmed_sample_count"] == 1

    def test_invalidate_reopens_and_second_confirm_completes_again(self, api):
        """PRD section 3.5: "Invalidating a `CONFIRMED` sample resets its
        `outcome` to null, decrements the plan's `confirmed_sample_count` by one,
        reopens the plan from `COMPLETED` to `ACTIVE` if the count has fallen
        below the requirement, and recomputes both the ingredient's standing and
        the product's exposure"

        Design: Difficulty/non_linear_state_machine/plan_auto_complete_and_invalidate_reopen_cycle
        """
        ctx, plan = _setup_plan_required_one(api)
        ing_id = ctx["ingredients"][0]["id"]
        s1 = confirm_sample(plan["id"], ing_id, result_gmo_pct=0.10)
        validate_success(api.invalidate_sample(s1["id"], LAB_1), 200)
        plan_after = validate_success(api.get_sampling_plan(plan["id"], ADMIN), 200)
        assert plan_after["status"] == "ACTIVE"
        assert plan_after["confirmed_sample_count"] == 0

        confirm_sample(plan["id"], ing_id, result_gmo_pct=0.20)
        plan_final = validate_success(api.get_sampling_plan(plan["id"], ADMIN), 200)
        assert plan_final["status"] == "COMPLETED"
        assert plan_final["confirmed_sample_count"] == 1


# ─── Cross-entity gates: submit reads affidavit state ────────────────────────

class TestSubmitGatedByAffidavit:
    def test_submit_with_unreviewed_affidavit_rejected(self, api):
        """PRD section 3.2: "The product must have at least one ingredient, else
        `ERR_NO_INGREDIENTS`, and every ingredient that requires an affidavit must
        be covered by at least one `ACCEPTED` affidavit whose window currently
        covers the submission time, else `ERR_AFFIDAVIT_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_by_affidavit_state
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        ing = add_ingredient(product["id"], brand["id"])
        rep = make_brand_rep_headers(brand["id"])
        validate_success(
            api.create_affidavit(create_affidavit_payload(ing["id"]), rep), 201)
        res = api.submit_product(product["id"], rep)
        validate_error(res, ApiErrorId.ERR_AFFIDAVIT_MISSING.value)

    def test_submit_unblocked_after_affidavit_accepted(self, api):
        """PRD section 3.4: "Review belongs to the `VerifierAdmin`, who supplies a
        `decision` of `ACCEPTED` or `REJECTED`."
        PRD section 3.2: "Submitting a product moves it from `DRAFT` to
        `SUBMITTED` and is the first integrity gate."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_by_affidavit_state
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        ing = add_ingredient(product["id"], brand["id"])
        rep = make_brand_rep_headers(brand["id"])
        aff = validate_success(
            api.create_affidavit(create_affidavit_payload(ing["id"]), rep), 201)
        validate_success(
            api.review_affidavit(aff["id"], {"decision": "ACCEPTED"}, ADMIN), 200)
        res = api.submit_product(product["id"], rep)
        assert validate_success(res, 200)["enrollment_status"] == "SUBMITTED"


# ─── Cross-entity gates: plan creation reads product state ───────────────────

class TestPlanCreateGatedByProductState:
    def test_plan_create_on_submitted_product_rejected(self, api):
        """PRD section 3.5: "Plan creation names the `product_id` and a
        `risk_point` of `INGREDIENT_INTAKE`, `IN_PROCESS`, or `FINISHED_PRODUCT`,
        and requires the product to be `UNDER_EVALUATION`; products in any other
        state are rejected with `ERR_PRODUCT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/plan_create_gated_by_product_state
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        ing = add_ingredient(product["id"], brand["id"])
        add_accepted_affidavit(ing["id"], brand["id"])
        rep = make_brand_rep_headers(brand["id"])
        validate_success(api.submit_product(product["id"], rep), 200)
        version = get_product(product["id"])["version"]
        res = api.create_sampling_plan(
            {"product_id": product["id"], "risk_point": "INGREDIENT_INTAKE",
             "expected_product_version": version},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_PRODUCT_INVALID_STATE.value)

    def test_plan_create_after_begin_evaluation_succeeds(self, api):
        """PRD section 3.2: "Once `SUBMITTED`, the product is frozen for
        administrative triage — ingredient additions are refused — until a
        `VerifierAdmin` picks it up, moving it from `SUBMITTED` to
        `UNDER_EVALUATION`."
        PRD section 3.5: "A plan is created `ACTIVE`, or `COMPLETED` immediately
        when the required count computes to zero."

        Design: Difficulty/cross_entity_state_dependency/plan_create_gated_by_product_state
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        ing = add_ingredient(product["id"], brand["id"])
        add_accepted_affidavit(ing["id"], brand["id"])
        rep = make_brand_rep_headers(brand["id"])
        validate_success(api.submit_product(product["id"], rep), 200)
        validate_success(api.begin_evaluation(product["id"], ADMIN), 200)
        version = get_product(product["id"])["version"]
        res = api.create_sampling_plan(
            {"product_id": product["id"], "risk_point": "INGREDIENT_INTAKE",
             "expected_product_version": version},
            ADMIN,
        )
        plan = validate_success(res, 201)
        assert plan["status"] == "ACTIVE"


# ─── Corner: initial states on creation ──────────────────────────────────────

class TestInitialStates:
    def test_entities_are_born_in_declared_initial_states(self, api):
        """PRD section 3.2: "A new product begins with `enrollment_status` of
        `DRAFT` and both exposure estimates at zero."
        PRD section 3.4: "A submitted affidavit starts in `SUBMITTED` status and
        records the submitting representative in `submitted_by_user_id`."
        PRD section 3.6: "A `VerifierAdmin` schedules one by naming the
        `brand_id`, the `facility_name`, the `auditor_id` of the assigned field
        auditor, and the `scheduled_date`."
        PRD section 3.8: "A new case is `OPENED` and records `opened_by_user_id`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        assert product["enrollment_status"] == "DRAFT"

        ing = add_ingredient(product["id"], brand["id"])
        rep = make_brand_rep_headers(brand["id"])
        aff = validate_success(
            api.create_affidavit(create_affidavit_payload(ing["id"]), rep), 201)
        assert aff["status"] == "SUBMITTED"

        audit = validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"]), ADMIN), 201)
        assert audit["status"] == "SCHEDULED"

        case = open_case(product["id"], description="d")
        assert case["status"] == "OPENED"


# ─── Corner: invalid transitions ─────────────────────────────────────────────

class TestInvalidTransitions:
    def test_submit_on_verified_product_rejected(self, api):
        """PRD section 3.2: "Any product transition attempted from a state that
        does not support it is rejected with `ERR_PRODUCT_INVALID_STATE`."

        Design: Corner/state_machines/submit_verified_product_returns_invalid_state
        """
        ctx = create_verified_product()
        rep = make_brand_rep_headers(ctx["brand"]["id"])
        res = api.submit_product(ctx["product"]["id"], rep)
        validate_error(res, ApiErrorId.ERR_PRODUCT_INVALID_STATE.value)
        product = get_product(ctx["product"]["id"])
        assert product["enrollment_status"] == "VERIFIED"

    def test_confirm_collected_sample_rejected(self, api):
        """PRD section 3.5: "Confirmation moves it from `RESULT_RECORDED` to
        `CONFIRMED` and is the highest-leverage action in the laboratory."
        PRD section 2.9: "then state-machine from-state preconditions
        (`ERR_PRODUCT_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`,
        `ERR_SAMPLE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_CASE_NOT_OPEN`,
        `ERR_AFFIDAVIT_NOT_REVIEWABLE`)."

        Design: Corner/state_machines/confirm_collected_sample_returns_invalid_state
        """
        ctx = create_product_under_evaluation(name="P1", gtin="G-P1")
        plan = create_plan(ctx["product"]["id"])
        sample = collect_sample(plan["id"], ctx["ingredients"][0]["id"])
        res = api.confirm_sample(sample["id"], LAB_2)
        validate_error(res, ApiErrorId.ERR_SAMPLE_INVALID_STATE.value)

    def test_review_expired_affidavit_rejected(self, api):
        """PRD section 3.4: "Only a `SUBMITTED` affidavit is reviewable; accepted,
        rejected, and expired affidavits are settled, and re-reviewing one is
        rejected with `ERR_AFFIDAVIT_NOT_REVIEWABLE`."
        PRD section 2.6: "Each `ACCEPTED` affidavit whose `valid_until` is at or
        before the new current time transitions to `EXPIRED`"

        Design: Corner/state_machines/review_expired_affidavit_returns_invalid_state
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        ing = add_ingredient(product["id"], brand["id"])
        aff = add_accepted_affidavit(ing["id"], brand["id"],
                                     valid_until="2026-09-01T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        res = api.review_affidavit(aff["id"], {"decision": "ACCEPTED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_AFFIDAVIT_NOT_REVIEWABLE.value)

    def test_decide_scheduled_audit_rejected(self, api):
        """PRD section 3.6: "The assigned auditor — and only that auditor, per
        §2.8 — submits the traceability exercise report, which requires the
        audit still be `SCHEDULED`; the wrong state draws `ERR_AUDIT_INVALID_STATE`."
        PRD section 2.9: "then state-machine from-state preconditions
        (`ERR_PRODUCT_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`,
        `ERR_SAMPLE_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_CASE_NOT_OPEN`,
        `ERR_AFFIDAVIT_NOT_REVIEWABLE`)."

        Design: Corner/state_machines/decide_scheduled_audit_returns_invalid_state
        """
        brand = create_brand(name="B1", contact_email="b1@x.com")
        audit = validate_success(
            api.create_facility_audit(
                create_facility_audit_payload(brand["id"]), ADMIN), 201)
        res = api.decide_audit(audit["id"], {"decision": "PASSED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_AUDIT_INVALID_STATE.value)

    def test_resolve_closed_case_rejected_and_applies_no_penalty(self, api):
        """PRD section 3.8: "Resolution requires a second officer: the resolver's
        identity must differ from `opened_by_user_id`, per §2.8, and the
        case must still be `OPENED`, else `ERR_CASE_NOT_OPEN`."
        PRD section 3.8: "while open or once dismissed, a case's `penalty_points`
        remain zero."

        Design: Corner/state_machines/resolve_closed_case_returns_invalid_state
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        case = open_case(product["id"], description="d")
        substantiate_case(case["id"], sanction="WARNING")
        res = api.resolve_enforcement_case(
            case["id"], {"outcome": "DISMISSED"}, TEST_USERS["officer_2_headers"])
        validate_error(res, ApiErrorId.ERR_CASE_NOT_OPEN.value)
        brand_after = validate_success(api.get_brand(brand["id"], ADMIN), 200)
        assert brand_after["lifetime_penalty_points"] == 5


# ─── Corner: zero-requirement plan born COMPLETED ────────────────────────────

class TestZeroRequiredPlan:
    def test_plan_with_zero_required_samples_auto_completes(self, api):
        """PRD section 3.5: "A plan is created `ACTIVE`, or `COMPLETED`
        immediately when the required count computes to zero."
        PRD section 3.5: "The plan's `required_sample_count` is computed at
        creation from the product's risk profile: start with a base of 0 for
        `INGREDIENT_INTAKE`, 1 for `IN_PROCESS`, or 2 for `FINISHED_PRODUCT`"

        Design: Corner/state_machines/plan_zero_required_samples_auto_completes
        """
        ctx = _setup_non_crop_under_evaluation(api)
        plan = create_plan(ctx["product"]["id"], risk_point="INGREDIENT_INTAKE")
        assert plan["required_sample_count"] == 0
        assert plan["status"] == "COMPLETED"


# ─── Corner: clock sweeps ────────────────────────────────────────────────────

class TestClockSweeps:
    def test_sweep_expires_affidavit_and_flips_ingredient_to_pending(self, api):
        """PRD section 2.6: "Each `ACCEPTED` affidavit whose `valid_until` is at
        or before the new current time transitions to `EXPIRED`, and the owning
        ingredient's compliance standing is recomputed — an ingredient that loses
        its last current affidavit may drop from `COMPLIANT` to `PENDING`."
        PRD section 3.4: "Windows are half-open: coverage includes the
        `valid_from` instant and runs up to but excludes `valid_until`"

        Design: Corner/state_machines/clock_sweep_expires_affidavit_and_flips_ingredient
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        ing = add_ingredient(product["id"], brand["id"], name="Oats",
                             crop_type="LOW_RISK", declared_weight_pct=30.00)
        aff = add_accepted_affidavit(ing["id"], brand["id"],
                                     valid_until="2026-09-01T00:00:00Z")
        ing_before = validate_success(api.get_ingredient(ing["id"], ADMIN), 200)
        assert ing_before["compliance_status"] == "COMPLIANT"

        set_clock("2026-09-01T00:00:00Z")
        aff_after = validate_success(api.get_affidavit(aff["id"], ADMIN), 200)
        assert aff_after["status"] == "EXPIRED"
        ing_after = validate_success(api.get_ingredient(ing["id"], ADMIN), 200)
        assert ing_after["compliance_status"] == "PENDING"

    def test_sweep_moves_product_to_renewal_due_then_lapsed(self, api):
        """PRD section 3.7: "when the logical clock enters that window — at or
        after `valid_until` minus the window, and still before `valid_until` —
        while the license is `ACTIVE`, the sweep moves a `VERIFIED` product to
        `RENEWAL_DUE`."
        PRD section 2.6: "Each `ACTIVE` label license whose `valid_until` is at or
        before the new current time transitions to `EXPIRED`, and its product — if
        `VERIFIED` or `RENEWAL_DUE` — transitions to `LAPSED`."
        PRD section 3.2: "Any product transition attempted from a state that does
        not support it is rejected with `ERR_PRODUCT_INVALID_STATE`."

        Design: Corner/state_machines/clock_sweep_moves_product_to_renewal_due_then_lapsed
        """
        ctx = create_verified_product()
        product_id = ctx["product"]["id"]

        set_clock("2027-06-15T00:00:00Z")
        product = get_product(product_id)
        assert product["enrollment_status"] == "RENEWAL_DUE"

        set_clock("2027-08-02T00:00:00Z")
        product = get_product(product_id)
        assert product["enrollment_status"] == "LAPSED"
        licenses = validate_success(
            api.list_licenses(ADMIN, params={"product_id": product_id}), 200)
        assert licenses[0]["status"] == "EXPIRED"

        rep = make_brand_rep_headers(ctx["brand"]["id"])
        res = api.submit_product(product_id, rep)
        validate_error(res, ApiErrorId.ERR_PRODUCT_INVALID_STATE.value)


# ─── Corner: submit requires at least one ingredient ─────────────────────────

class TestSubmitPreconditions:
    def test_submit_without_ingredients_rejected(self, api):
        """PRD section 3.2: "The product must have at least one ingredient, else
        `ERR_NO_INGREDIENTS`, and every ingredient that requires an affidavit must
        be covered by at least one `ACCEPTED` affidavit whose window currently
        covers the submission time, else `ERR_AFFIDAVIT_MISSING`."

        Design: Corner/state_machines/submit_without_ingredients_returns_no_ingredients
        """
        std = create_standard()
        brand = create_brand(name="B1", contact_email="b1@x.com")
        product = create_product(brand, std, name="P1", gtin="G-P1")
        res = api.submit_product(product["id"], make_brand_rep_headers(brand["id"]))
        validate_error(res, ApiErrorId.ERR_NO_INGREDIENTS.value)
