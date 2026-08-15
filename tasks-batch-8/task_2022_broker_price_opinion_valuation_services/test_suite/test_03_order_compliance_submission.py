"""Order intake and compliance submission: state legality vs product-legality rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_state_regulation,
    dispatch_to_broker,
    get_order,
    make_client_admin_headers,
    new_order,
    setup_market,
    submit_order,
    validate_error,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestInteriorRequiresAppraisal:
    def test_error_interior_requires_appraisal(self, api):
        """PRD §3.4: "if the `inspection_level` is `INTERIOR` while the state's
        `appraisal_required_for_interior` is true, the `order_kind` must be
        `APPRAISAL`, else the submission fails with
        `ERR_INTERIOR_REQUIRES_APPRAISAL`."

        Design: Corner/errors/error_interior_requires_appraisal
        """
        env = setup_market("MS", client_code="CIR",
                           reg_overrides={"appraisal_required_for_interior": True})
        order = new_order(env, order_kind="BPO", inspection_level="INTERIOR")
        assert order["fulfillment_status"] == "INTAKE"

        resp = api.submit_order(order["id"], make_client_admin_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INTERIOR_REQUIRES_APPRAISAL)
        assert get_order(order["id"])["fulfillment_status"] == "INTAKE"


class TestSubmitDependsOnStateRegulation:
    def test_submit_rejected_when_bpo_not_permitted(self, api):
        """PRD §3.4: "if `order_kind` is `BPO`, the state's `bpo_permitted` must
        be true or the submission fails with `ERR_BPO_NOT_PERMITTED`"

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_state_regulation_active
        """
        env = setup_market("WY", client_code="CLN",
                           reg_overrides={"bpo_permitted": False})
        order = new_order(env, order_kind="BPO")

        resp = api.submit_order(order["id"], make_client_admin_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BPO_NOT_PERMITTED)
        assert get_order(order["id"])["fulfillment_status"] == "INTAKE"

    def test_submit_evaluates_regulation_at_submit_time(self, api):
        """PRD §3.4: "Submission re-verifies the property and state-regulation
        checks above, then applies the product-legality rules: if `order_kind` is
        `BPO`, the state's `bpo_permitted` must be true or the submission fails
        with `ERR_BPO_NOT_PERMITTED`"

        Design: Difficulty/cross_entity_state_dependency/order_submit_requires_state_regulation_active
        """
        env = setup_market("WY", client_code="CLN")
        order = new_order(env, order_kind="BPO")
        assert order["fulfillment_status"] == "INTAKE"

        # Regulation replaced between creation and submission: the submit-time
        # evaluation must read the current regulation row.
        create_state_regulation("WY", bpo_permitted=False)

        resp = api.submit_order(order["id"], make_client_admin_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BPO_NOT_PERMITTED)
        assert get_order(order["id"])["fulfillment_status"] == "INTAKE"


class TestSubmitStatePrecedence:
    def test_submit_on_dispatched_order_returns_invalid_state(self, api):
        """PRD §2.9: "5. State legality: the target resource is in a state from
        which this transition is permitted (`ERR_INVALID_STATE`)."
        PRD §3.4: "Moving from `INTAKE` to `READY_FOR_DISPATCH` is the compliance
        gateway, performed by a `ClientAdmin` submitting the order."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_submit
        """
        env = setup_market("FL", client_code="CLI", broker_code="BRKI")
        order = new_order(env)
        order = submit_order(env, order)
        dispatch_to_broker(env, order)

        resp = api.submit_order(order["id"], make_client_admin_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["fulfillment_status"] == "DISPATCHED"

    def test_state_error_wins_over_bpo_permissibility(self, api):
        """PRD §2.9: "5. State legality: the target resource is in a state from
        which this transition is permitted (`ERR_INVALID_STATE`)."
        PRD §2.9: "9. BPO product permissibility in the subject property's state
        (`ERR_BPO_NOT_PERMITTED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_submit
        """
        env = setup_market("FL", client_code="CLI", broker_code="BRKI")
        order = new_order(env)
        order = submit_order(env, order)
        dispatch_to_broker(env, order)

        # Now make the state BPO-hostile: the resubmission violates both state
        # legality (order is DISPATCHED) and BPO permissibility.
        create_state_regulation("FL", bpo_permitted=False)

        resp = api.submit_order(order["id"], make_client_admin_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
