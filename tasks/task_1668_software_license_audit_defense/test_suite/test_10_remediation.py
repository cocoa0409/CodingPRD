"""Remediation of over-deployment: the PURCHASE_TRUE_UP cascade, UNINSTALL
conservation under fail-verification, and creation-time gates (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_remediation,
    complete_remediation,
    create_deployment,
    create_confirmed_deployment,
    create_remediation,
    fail_verification,
    get_case,
    get_license_position,
    list_product_alerts,
    list_product_deployments,
    list_product_entitlements,
    setup_case_with_confirmed_item,
    setup_product_with_gap,
    start_remediation,
    validate_error,
    validate_success,
)


class TestTrueUpCascade:
    def _setup_true_up_scenario(self):
        """Product entitled 100, deployed 130 CONFIRMED (gap 30, CRITICAL, with the
        OVER_DEPLOYMENT alert OPEN); a case in SCOPE_NEGOTIATION holding the
        product's CONFIRMED scope item (provisional rollup 300000); a
        PURCHASE_TRUE_UP remediation of 30 units created and started."""
        product_ctx = setup_product_with_gap(entitled=100, deployed=130)
        ctx = setup_case_with_confirmed_item(product_ctx)
        case = get_case(ctx["case"]["id"])
        assert case["provisional_case_exposure_cents"] == 300000

        alerts = list_product_alerts(ctx["product"]["id"])
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "OVER_DEPLOYMENT"
        assert alerts[0]["status"] == "OPEN"

        action = create_remediation(ctx["product"]["id"], "PURCHASE_TRUE_UP",
                                    quantity=30)
        start_remediation(action["id"])
        ctx["remediation"] = action
        ctx["alert"] = alerts[0]
        return ctx

    def test_true_up_completion_creates_auto_trueup_entitlement(
            self, api, sam_manager_headers):
        """PRD §3.8: "For `PURCHASE_TRUE_UP`, completion creates a new entitlement
        record with `source` `AUTO_TRUE_UP`, `quantity` equal to the action's
        `quantity`, `coverage_class` `PRODUCTION`, `effective_from` set to the
        current logical clock, `effective_to` null (perpetual), and a
        `purchase_order_number` formed as 'TRUEUP-' followed by the action's
        identifier; the action's `generated_entitlement_id` points at the new
        record and remains null for `UNINSTALL` actions."
        PRD §3.8: "Either way, the position is then recomputed — the new
        entitlement's activation lifts `entitled_quantity`, or the exclusions lower
        `deployed_quantity`"

        Design: Difficulty/transitive_cascade/true_up_remediation_cascade
        """
        ctx = self._setup_true_up_scenario()

        completed = complete_remediation(ctx["remediation"]["id"])
        assert_remediation(completed)
        assert completed["status"] == "COMPLETED"
        generated_id = completed["generated_entitlement_id"]
        assert generated_id is not None, "an AUTO_TRUE_UP entitlement was created"

        records = list_product_entitlements(ctx["product"]["id"])
        generated = next(r for r in records if r["id"] == generated_id)
        assert generated["source"] == "AUTO_TRUE_UP"
        assert generated["quantity"] == 30
        assert generated["coverage_class"] == "PRODUCTION"
        assert generated["status"] == "ACTIVE"
        assert generated["effective_to"] is None
        assert generated["purchase_order_number"] == \
            f"TRUEUP-{ctx['remediation']['id']}"

        position = get_license_position(ctx["product"]["id"])
        assert position["entitled_quantity"] == 130
        assert position["gap_quantity"] == 0
        assert position["gap_severity"] == "COMPLIANT"

    def test_true_up_completion_resolves_case_rollup_and_alert(
            self, api, sam_manager_headers):
        """PRD §3.8: "Either way, the position is then recomputed — the new
        entitlement's activation lifts `entitled_quantity`, or the exclusions lower
        `deployed_quantity` — the rollups of every non-terminal audit case scoping
        the product are recomputed with each such case's `version` incremented by
        one, and the product's monitoring alerts are upserted, resolving the
        `OVER_DEPLOYMENT` alert when the gap returns to zero."
        PRD §3.9: "When the underlying condition later evaluates false, any `OPEN`
        or `SUPPRESSED` alert resolves automatically to the terminal `RESOLVED`
        status"

        Design: Difficulty/transitive_cascade/true_up_remediation_cascade
        """
        ctx = self._setup_true_up_scenario()
        complete_remediation(ctx["remediation"]["id"])

        case = get_case(ctx["case"]["id"])
        assert case["provisional_case_exposure_cents"] == 0, \
            "the gap closure rezeroes the case's provisional rollup (was 300000)"

        alerts = list_product_alerts(ctx["product"]["id"])
        assert len(alerts) == 1, "alert rows are upserted, not duplicated"
        assert alerts[0]["id"] == ctx["alert"]["id"]
        assert alerts[0]["alert_type"] == "OVER_DEPLOYMENT"
        assert alerts[0]["status"] == "RESOLVED"


class TestUninstallConservation:
    def _setup_uninstall_scenario(self):
        """Product entitled 100; deployments D1=100 and D2=30 both CONFIRMED
        (deployed 130, gap 30); an UNINSTALL remediation targeting D2, started."""
        product_ctx = setup_product_with_gap(entitled=100, deployed=100)
        product = product_ctx["product"]
        d2 = create_confirmed_deployment(product["id"], 30)
        assert get_license_position(product["id"])["deployed_quantity"] == 130

        action = create_remediation(product["id"], "UNINSTALL",
                                    target_deployment_ids=[d2["id"]])
        start_remediation(action["id"])
        return product_ctx, d2, action

    def test_uninstall_completion_excludes_targets_and_drops_deployed(
            self, api, sam_manager_headers):
        """PRD §3.8: "An `UNINSTALL` requires a non-empty `target_deployment_ids`
        array naming the deployments to exclude — each target must exist
        (`ERR_DEPLOYMENT_NOT_FOUND`), must belong to the action's product, and must
        be `CONFIRMED`, otherwise creation is rejected with
        `ERR_REMEDIATION_TARGET_INVALID` — and any `quantity` input on an
        `UNINSTALL` is ignored: the server computes the action's `quantity` as the
        sum of the targeted deployments' `measured_quantity`."
        PRD §3.8: "For `UNINSTALL`, completion moves every targeted deployment from
        `CONFIRMED` to `EXCLUDED`, stamping each record's
        `excluded_by_remediation_id` with the completing action's identifier."

        Design: Difficulty/compensating_invariant/uninstall_complete_and_fail_verification_conserve_deployed
        """
        product_ctx, d2, action = self._setup_uninstall_scenario()
        assert action["quantity"] == 30, \
            "the quantity is computed from the targeted deployment, not from input"

        completed = complete_remediation(action["id"])
        assert completed["status"] == "COMPLETED"

        position = get_license_position(product_ctx["product"]["id"])
        assert position["deployed_quantity"] == 100, \
            "the 30 excluded units leave the CONFIRMED input set"

        rows = list_product_deployments(product_ctx["product"]["id"])
        target = next(r for r in rows if r["id"] == d2["id"])
        assert target["status"] == "EXCLUDED"
        assert target["excluded_by_remediation_id"] == action["id"]

    def test_uninstall_fail_verification_restores_deployed_exactly(
            self, api, sam_manager_headers):
        """PRD §3.8: "Verification can fail after completion, which moves the action
        from `COMPLETED` back to `PLANNED` as a compensating transaction that
        reverses every completion effect."
        PRD §3.8: "For `UNINSTALL`, every deployment whose
        `excluded_by_remediation_id` names this action returns from `EXCLUDED` to
        `CONFIRMED` with the reference cleared to null."
        PRD §3.8: "Position, case rollups, and alerts are then recomputed under a
        conservation rule: deployed and entitled quantities return exactly to their
        pre-completion values."

        Design: Difficulty/compensating_invariant/uninstall_complete_and_fail_verification_conserve_deployed
        """
        product_ctx, d2, action = self._setup_uninstall_scenario()
        deployed_pre = get_license_position(
            product_ctx["product"]["id"])["deployed_quantity"]
        complete_remediation(action["id"])
        assert get_license_position(
            product_ctx["product"]["id"])["deployed_quantity"] == 100

        reverted = fail_verification(action["id"])
        assert reverted["status"] == "PLANNED", \
            "failed verification moves the action back to PLANNED"

        position = get_license_position(product_ctx["product"]["id"])
        assert position["deployed_quantity"] == deployed_pre == 130, \
            "compensation restores the conserved quantity exactly"

        rows = list_product_deployments(product_ctx["product"]["id"])
        target = next(r for r in rows if r["id"] == d2["id"])
        assert target["status"] == "CONFIRMED"
        assert target["excluded_by_remediation_id"] is None


class TestRemediationCreateGates:
    def test_remediation_target_not_confirmed_rejected(self, api, sam_manager_headers):
        """PRD §3.8: "An `UNINSTALL` requires a non-empty `target_deployment_ids`
        array naming the deployments to exclude — each target must exist
        (`ERR_DEPLOYMENT_NOT_FOUND`), must belong to the action's product, and must
        be `CONFIRMED`, otherwise creation is rejected with
        `ERR_REMEDIATION_TARGET_INVALID`"

        Design: Corner/validations/remediation_target_not_confirmed_rejected
        """
        product_ctx = setup_product_with_gap(entitled=10)
        dep = create_deployment(product_ctx["product"]["id"], measured_quantity=12)
        assert dep["status"] == "REPORTED"

        resp = api.create_remediation_action(
            {"product_id": product_ctx["product"]["id"], "action_type": "UNINSTALL",
             "target_deployment_ids": [dep["id"]]},
            sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_TARGET_INVALID)

    def test_remediation_quantity_equals_gap_allowed_exceeds_rejected(
            self, api, sam_manager_headers):
        """PRD §3.8: "In both cases the action's quantity may not exceed the
        product's current `gap_quantity`; equality is allowed, and an excess is
        rejected with `ERR_REMEDIATION_EXCEEDS_GAP`."

        Design: Corner/validations/remediation_quantity_equals_gap_allowed_exceeds_rejected
        """
        product_ctx = setup_product_with_gap(entitled=10, deployed=12)
        assert get_license_position(product_ctx["product"]["id"])["gap_quantity"] == 2

        over = api.create_remediation_action(
            {"product_id": product_ctx["product"]["id"],
             "action_type": "PURCHASE_TRUE_UP", "quantity": 3},
            sam_manager_headers)
        validate_error(over, ApiErrorId.ERR_REMEDIATION_EXCEEDS_GAP)

        at_gap = validate_success(
            api.create_remediation_action(
                {"product_id": product_ctx["product"]["id"],
                 "action_type": "PURCHASE_TRUE_UP", "quantity": 2},
                sam_manager_headers), 201)
        assert_remediation(at_gap)
        assert at_gap["status"] == "PLANNED", "quantity == gap is allowed"


class TestRemediationLifecycleErrors:
    def test_remediation_cancel_after_complete_rejected(self, api,
                                                        sam_manager_headers):
        """PRD §3.8: "A `PLANNED` or `IN_PROGRESS` action may instead be cancelled
        outright, ending in the terminal `CANCELLED` state."
        PRD §3.8: "Attempting to start, complete, cancel, or fail-verify an action
        whose status does not permit that transition is rejected with
        `ERR_REMEDIATION_INVALID_STATE`."

        Design: Corner/state_machines/remediation_cancel_after_complete_rejected
        """
        product_ctx = setup_product_with_gap(entitled=10, deployed=12)
        action = create_remediation(product_ctx["product"]["id"], "PURCHASE_TRUE_UP",
                                    quantity=2)
        start_remediation(action["id"])
        completed = complete_remediation(action["id"])
        assert completed["status"] == "COMPLETED"

        resp = api.cancel_remediation(action["id"], sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_INVALID_STATE)

    def test_remediation_not_found_on_start(self, api, sam_manager_headers):
        """PRD §3.8: "Actions can be fetched individually
        (`ERR_REMEDIATION_NOT_FOUND`), listed per product with an optional `status`
        filter, and the deployments excluded by an action can be listed from the
        action itself."
        PRD §2.10: "the request is rejected with the 404 error corresponding to the
        first identifier that does not exist"

        Design: Corner/errors/remediation_not_found_on_start
        """
        resp = api.start_remediation(NON_EXISTENT_UUID, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_NOT_FOUND)
