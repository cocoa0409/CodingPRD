"""Prior authorization lifecycle and its parallel billing dimension."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_pa,
    payer_decision_payload,
    set_clock,
    setup_qualified_order,
    setup_qualified_with_pa,
    validate_error,
    validate_success,
)


class TestParallelDimensions:
    def test_pa_creation_moves_only_billing_dimension(self, api, insurance_specialist_headers,
                                                      care_coordinator_headers):
        """PRD §3.3: "The new PA derives its `member_id` and `policy_id` from the order,
        snapshots the pump's tier into `requested_item_tier`, records
        `submitted_by_user_id`, opens in `SUBMITTED` with `submission_count` 1, and
        cascades the order's `billing_status` from `UNBILLED` to `AUTH_PENDING`."
        PRD §3.2: "two parallel dimensions that evolve independently".

        Design: Difficulty/non_linear_state_machine/pump_order_parallel_fulfillment_and_billing_dimensions
        """
        ctx = setup_qualified_order(policy_overrides={"requires_prior_auth": True})
        pa = validate_success(
            api.create_prior_authorization({"pump_order_id": ctx["order"]["id"]},
                                           insurance_specialist_headers), 201
        )
        assert pa["status"] == "SUBMITTED"
        assert pa["submission_count"] == 1

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "QUALIFIED"
        assert order["billing_status"] == "AUTH_PENDING"

    def test_pa_approval_then_shipment_move_dimensions_independently(
        self, api, insurance_specialist_headers, care_coordinator_headers,
        warehouse_operator_headers
    ):
        """PRD §3.3: "From `SUBMITTED`, a decision of `APPROVED` (which must carry
        `approved_until`) moves the PA to `APPROVED`, stamps `auth_number`,
        `approved_until`, and `decided_by_user_id`, and cascades the order's billing to
        `AUTH_APPROVED`."
        PRD §3.4: "A passing shipment cascades the pump order `QUALIFIED → SHIPPED`."

        Design: Difficulty/non_linear_state_machine/pump_order_parallel_fulfillment_and_billing_dimensions
        """
        ctx = setup_qualified_order(policy_overrides={"requires_prior_auth": True})
        pa = validate_success(
            api.create_prior_authorization({"pump_order_id": ctx["order"]["id"]},
                                           insurance_specialist_headers), 201
        )
        validate_success(
            api.payer_decision(
                pa["id"],
                payer_decision_payload("APPROVED", auth_number="AUTH-9",
                                       approved_until="2026-12-31"),
                TEST_USERS["platform_admin_headers"],
            ),
            200,
        )
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "QUALIFIED"
        assert order["billing_status"] == "AUTH_APPROVED"

        validate_success(
            api.create_shipment({"pump_order_id": ctx["order"]["id"], "carrier": "UPS",
                                 "tracking_number": "1Z-P"}, warehouse_operator_headers), 201
        )
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "SHIPPED"
        assert order["billing_status"] == "AUTH_APPROVED"


class TestPendResubmitAppealCycle:
    def test_pend_resubmit_increments_submission_count(self, api, insurance_specialist_headers,
                                                       platform_admin_headers):
        """PRD §3.3: "Pended cases loop: an `InsuranceSpecialist` resubmits, moving
        `PENDED → SUBMITTED` and incrementing `submission_count` — an unbounded cycle."

        Design: Difficulty/non_linear_state_machine/prior_authorization_pend_resubmit_appeal_cycle
        """
        ctx = setup_qualified_with_pa()
        pa = ctx["pa"]
        pended = validate_success(
            api.payer_decision(pa["id"],
                               payer_decision_payload("PENDED",
                                                      payer_notes="need physician notes"),
                               platform_admin_headers), 200
        )
        assert pended["status"] == "PENDED"

        resubmitted = validate_success(
            api.resubmit_prior_authorization(pa["id"], insurance_specialist_headers), 200
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submission_count"] == 2

    def test_denied_appeal_then_approved(self, api, insurance_specialist_headers,
                                         platform_admin_headers, care_coordinator_headers):
        """PRD §3.3: "A denied PA is likewise appealable: appealing moves
        `DENIED → APPEALED` and returns the order's billing to `AUTH_PENDING`."
        PRD §3.3: "From `APPEALED`, a payer decision of `APPROVED` lands in `APPROVED`
        (again requiring `approved_until` and setting `auth_number`; billing becomes
        `AUTH_APPROVED`)".

        Design: Difficulty/non_linear_state_machine/prior_authorization_pend_resubmit_appeal_cycle
        """
        ctx = setup_qualified_with_pa()
        pa = ctx["pa"]
        validate_success(
            api.payer_decision(pa["id"],
                               payer_decision_payload("DENIED",
                                                      payer_notes="not medically necessary"),
                               platform_admin_headers), 200
        )
        appealed = validate_success(
            api.appeal_prior_authorization(pa["id"], insurance_specialist_headers), 200
        )
        assert appealed["status"] == "APPEALED"

        approved = validate_success(
            api.payer_decision(pa["id"],
                               payer_decision_payload("APPROVED", auth_number="AUTH-77",
                                                      approved_until="2026-12-31"),
                               platform_admin_headers), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["auth_number"] == "AUTH-77"

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["billing_status"] == "AUTH_APPROVED"


class TestPriorAuthGates:
    def test_pa_create_when_not_required_rejected(self, api, insurance_specialist_headers,
                                                  care_coordinator_headers):
        """PRD §3.3: "attempting this for an order that is not `QUALIFIED` or does not
        require authorization is rejected with `ERR_PRIOR_AUTH_NOT_REQUIRED`."

        Design: Corner/state_machines/pa_create_when_not_required_rejected
        """
        ctx = setup_qualified_order()  # requires_prior_auth false, 30000 < 50000 threshold
        res = api.create_prior_authorization({"pump_order_id": ctx["order"]["id"]},
                                             insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PRIOR_AUTH_NOT_REQUIRED, expected_status=409)

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["billing_status"] == "UNBILLED"

    def test_shipment_after_approved_until_rejected_and_pa_expires(
        self, api, warehouse_operator_headers, care_coordinator_headers, platform_admin_headers
    ):
        """PRD §3.3: "If a shipment is attempted for the order after `approved_until` has
        passed and the order has not yet shipped or been delivered, the PA lazily
        transitions `APPROVED → EXPIRED`, the order's billing falls back to `AUTH_PENDING`,
        and the shipment is rejected with `ERR_PRIOR_AUTH_EXPIRED`."

        Design: Corner/validations/pa_expired_blocks_shipment_and_marks_expired
        """
        ctx = setup_qualified_with_pa()
        approve_pa(ctx["pa"]["id"], auth_number="AUTH-1", approved_until="2026-06-30")
        set_clock("2026-07-01T00:00:00Z")

        res = api.create_shipment(
            {"pump_order_id": ctx["order"]["id"], "carrier": "UPS",
             "tracking_number": "1Z-V2"},
            warehouse_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRIOR_AUTH_EXPIRED, expected_status=422)

    def test_expired_pa_leaves_order_qualified_and_auth_pending(
        self, api, warehouse_operator_headers, care_coordinator_headers, platform_admin_headers
    ):
        """PRD §3.3: "the PA lazily transitions `APPROVED → EXPIRED`, the order's billing
        falls back to `AUTH_PENDING`, and the shipment is rejected with
        `ERR_PRIOR_AUTH_EXPIRED`."

        Design: Corner/validations/pa_expired_blocks_shipment_and_marks_expired
        """
        ctx = setup_qualified_with_pa()
        approve_pa(ctx["pa"]["id"], auth_number="AUTH-1", approved_until="2026-06-30")
        set_clock("2026-07-01T00:00:00Z")
        api.create_shipment(
            {"pump_order_id": ctx["order"]["id"], "carrier": "UPS",
             "tracking_number": "1Z-V2"},
            warehouse_operator_headers,
        )

        pa = validate_success(
            api.get_prior_authorization(ctx["pa"]["id"], care_coordinator_headers), 200
        )
        assert pa["status"] == "EXPIRED"
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "QUALIFIED"
        assert order["billing_status"] == "AUTH_PENDING"
