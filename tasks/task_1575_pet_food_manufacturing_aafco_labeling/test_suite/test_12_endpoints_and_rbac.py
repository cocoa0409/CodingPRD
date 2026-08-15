"""Nested-resource retrieval, computed read counters, override completion, and
endpoint RBAC denials (PRD §2.1, §2.8, §2.9, §3.5, §3.6, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    brand_owner_payload,
    create_brand_owner,
    create_complaint,
    create_formula,
    create_ingredient,
    create_pairing,
    create_production_batch,
    create_supplier,
    get_formula,
    get_supplier,
    ingredient_payload,
    make_regulatory_affairs_headers,
    setup_batch_in_state,
    setup_nutrient_review_formula,
    setup_registration,
    setup_substantiated_formula,
    setup_trial_protocol,
    state_registration_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNestedRetrievalAndCounters:
    def test_fk_reverse_reachability_lists(
        self, api, formulation_scientist_headers, quality_analyst_headers
    ):
        """PRD §2.9: "Requests that target nested resources are validated strictly
        left to right along the path."
        PRD §4 declares the nested list endpoints for a formula's ingredient
        lines, a batch's lots, a brand's complaint cases, and a formula's state
        registrations.

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        ctx = setup_batch_in_state("COMPLETED", planned_kg=200.0, line_id="LINE-R1",
                                   with_lot=True)
        ra = make_regulatory_affairs_headers(ctx["brand"]["id"])
        # Registration submission is permitted while the formula is SUBSTANTIATED
        # or LOCKED (PRD §3.7); this context is LOCKED.
        registration = validate_success(
            api.create_state_registration(
                ctx["formula"]["id"],
                state_registration_payload(state_code="CA", tonnage_tier=3.0),
                ra,
            ),
            expected_status=201,
        )
        complaint = create_complaint(
            ctx["brand"]["id"], ctx["formula"]["id"],
            severity="MINOR", category="PACKAGING",
        )

        lines, _ = validate_paginated(
            api.list_formula_ingredients(ctx["formula"]["id"], formulation_scientist_headers)
        )
        assert len(lines) == 1 and lines[0]["id"] == ctx["line"]["id"]

        lots, _ = validate_paginated(
            api.list_lots(ctx["batch"]["id"], quality_analyst_headers)
        )
        assert len(lots) == 1 and lots[0]["id"] == ctx["lot"]["id"]

        cases, _ = validate_paginated(
            api.list_brand_owner_complaint_cases(ctx["brand"]["id"], quality_analyst_headers)
        )
        assert len(cases) == 1 and cases[0]["id"] == complaint["id"]

        registrations, _ = validate_paginated(
            api.list_state_registrations(ctx["formula"]["id"], ra)
        )
        assert len(registrations) == 1 and registrations[0]["id"] == registration["id"]

    def test_computed_read_counters_after_mutations(
        self, api, qa_approver_headers, line_operator_headers,
        formulation_scientist_headers, production_planner_headers
    ):
        """PRD §2.8: "Completing a batch increments the parent formula's
        `total_batch_count`. Approving or revoking a pairing recomputes the
        supplier's `approved_ingredient_count`."
        PRD §2.8: "These rollups are part of the mutation that triggered them,
        never deferred."

        Design: Corner/endpoints/computed_read_counters_after_mutations
        """
        from test_helpers import add_ingredient_line, post_nutrient_profile

        supplier = create_supplier()
        assert get_supplier(supplier["id"], qa_approver_headers)["approved_ingredient_count"] == 0
        ingredient = create_ingredient()
        brand = create_brand_owner()
        formula = create_formula(brand["id"])

        validate_success(api.approve_supplier(supplier["id"], qa_approver_headers))
        create_pairing(supplier["id"], ingredient["id"], approve=True)
        assert get_supplier(supplier["id"], qa_approver_headers)["approved_ingredient_count"] == 1

        assert get_formula(formula["id"])["total_batch_count"] == 0
        # Drive the formula to LOCKED and complete one batch.
        add_ingredient_line(formula["id"], ingredient["id"])
        post_nutrient_profile(formula["id"])
        validate_success(api.submit_nutrient_review(formula["id"], formulation_scientist_headers))
        validate_success(api.substantiate_formula(formula["id"], qa_approver_headers))
        validate_success(api.lock_formula(formula["id"], qa_approver_headers))
        batch = create_production_batch(formula["id"], planned_kg=150.0, line_id="LINE-C2")
        validate_success(api.release_batch(batch["id"], production_planner_headers))
        validate_success(api.start_run(batch["id"], line_operator_headers))
        validate_success(api.complete_batch(batch["id"], {"actual_kg": 150.0}, line_operator_headers))
        assert get_formula(formula["id"])["total_batch_count"] == 1

    def test_batch_complete_with_override_allows_excess_variance(
        self, api, quality_analyst_headers
    ):
        """PRD §3.6: "When its absolute value is strictly greater than 5.00
        percent, the completion request must carry the `override` flag and be
        acted on by a `QualityAnalyst`; a completion breaching the threshold
        without the override is rejected with `ERR_YIELD_VARIANCE_HOLD`
        (HTTP 422)."
        PRD §3.6: "A batch's `yield_variance_pct` is the difference between
        `actual_kg` and `planned_kg`, divided by `planned_kg`, expressed as a
        percentage and rounded half up to 2 decimal places."

        Design: Corner/endpoints/batch_complete_with_override_allows_excess_variance
        """
        ctx = setup_batch_in_state("IN_PROCESS", planned_kg=1000.0, line_id="LINE-O1")
        completed = validate_success(
            api.complete_batch(
                ctx["batch"]["id"], {"actual_kg": 1100.0, "override": True},
                quality_analyst_headers,
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["yield_variance_pct"] == pytest.approx(10.0, abs=0.005)


class TestEndpointRbacDenials:
    def test_rbac_denied_formulation_scientist_create_brand(
        self, api, formulation_scientist_headers
    ):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: brand-owner registration is authorized for `PlatformAdmin`.

        Design: Corner/rbac/rbac_denied_formulation_scientist_create_brand
        """
        resp = api.create_brand_owner(brand_owner_payload(), formulation_scientist_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_rbac_denied_qa_approver_create_ingredient(self, api, qa_approver_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: ingredient creation is authorized for `FormulationScientist`.

        Design: Corner/rbac/rbac_denied_qa_approver_create_ingredient
        """
        resp = api.create_ingredient(ingredient_payload(), qa_approver_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_rbac_denied_platform_admin_substantiate_formula(
        self, api, platform_admin_headers
    ):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: substantiation is authorized for `QAApprover`.

        Design: Corner/rbac/rbac_denied_platform_admin_substantiate_formula
        """
        ctx = setup_nutrient_review_formula()
        resp = api.substantiate_formula(ctx["formula"]["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
        assert get_formula(ctx["formula"]["id"])["status"] == "NUTRIENT_REVIEW"

    def test_rbac_denied_trial_coordinator_record_verdict(
        self, api, trial_coordinator_headers
    ):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: verdict recording is authorized for `QAApprover`.

        Design: Corner/rbac/rbac_denied_trial_coordinator_record_verdict
        """
        ctx = setup_trial_protocol(target_state="ANALYSIS", completed_count=8)
        resp = api.record_verdict(ctx["protocol"]["id"], trial_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_rbac_denied_production_planner_start_run(
        self, api, production_planner_headers, quality_analyst_headers
    ):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: starting a run is authorized for `LineOperator`.

        Design: Corner/rbac/rbac_denied_production_planner_start_run
        """
        ctx = setup_batch_in_state("RELEASED_FOR_PRODUCTION", line_id="LINE-S1")
        resp = api.start_run(ctx["batch"]["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
        current = validate_success(api.get_batch(ctx["batch"]["id"], quality_analyst_headers))
        assert current["status"] == "RELEASED_FOR_PRODUCTION"

    def test_rbac_denied_line_operator_release_batch(self, api, line_operator_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: releasing a batch is authorized for `ProductionPlanner`.

        Design: Corner/rbac/rbac_denied_line_operator_release_batch
        """
        ctx = setup_batch_in_state("SCHEDULED", line_id="LINE-S2")
        resp = api.release_batch(ctx["batch"]["id"], line_operator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_rbac_denied_state_regulator_create_registration(
        self, api, state_regulator_headers
    ):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: registration submission is authorized for `RegulatoryAffairs`.

        Design: Corner/rbac/rbac_denied_state_regulator_create_registration
        """
        ctx = setup_substantiated_formula()
        resp = api.create_state_registration(
            ctx["formula"]["id"], state_registration_payload(state_code="CO"),
            state_regulator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_rbac_denied_regulatory_affairs_approve_registration(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: registration approval is authorized for `StateRegulator`.

        Design: Corner/rbac/rbac_denied_regulatory_affairs_approve_registration
        """
        ctx = setup_registration(target_state="UNDER_REVIEW", state_code="OR")
        ra = make_regulatory_affairs_headers(ctx["brand"]["id"])
        version = get_formula(ctx["formula"]["id"])["version"]
        resp = api.approve_registration(
            ctx["registration"]["id"], {"expected_formula_version": version}, ra
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
