"""Guarantee claims: the approval refund cascade and the submission gates
(order-state, plan-offers-guarantee, and duplicate-claim)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_confirmed_order,
    setup_delivered_order,
    setup_delivered_satisfaction_with_session,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

SATISFACTION_PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
                     "included_revision_rounds": 1, "included_coaching_sessions": 0,
                     "guarantee_type": "SATISFACTION"}


class TestGuaranteeRefundCascade:
    def test_approve_refunds_full_net_and_moves_order_to_refunded(self, api):
        """PRD §3.7: "Approving it moves the claim from `SUBMITTED` to `APPROVED` and sets
        its `refund_amount_cents`: for a `SATISFACTION` claim this is the order's full
        `net_collected_cents`, and for an `INTERVIEW` claim it is the order's `base_price_cents`."
        PRD §3.7: "the system writes a `REFUND` payment for the claim's `refund_amount_cents`
        with reason `GUARANTEE_REFUND`, raising `amount_refunded_cents` by that amount".

        Design: Difficulty/transitive_cascade/guarantee_refund_cascade_depth2
        """
        ctx = setup_delivered_satisfaction_with_session()
        approved = validate_success(api.approve_guarantee_claim(ctx["claim_id"], ADMIN))
        assert approved["status"] == "APPROVED"
        assert approved["refund_amount_cents"] == 30000
        order = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert order["status"] == "REFUNDED"
        assert order["amount_refunded_cents"] == 30000

    def test_approve_cancels_scheduled_sessions_downstream(self, api):
        """PRD §3.7: as the order enters REFUNDED "it cancels every coaching session on the
        order still in SCHEDULED (the guarantee refund settles the order as a whole, so no
        separate per-session refund is issued for these)".

        Design: Difficulty/transitive_cascade/guarantee_refund_cascade_depth2
        """
        ctx = setup_delivered_satisfaction_with_session()
        validate_success(api.approve_guarantee_claim(ctx["claim_id"], ADMIN))
        session = validate_success(api.get_session(ctx["session"]["id"], ADMIN))
        assert session["status"] == "CANCELLED"


def test_claim_on_undelivered_order_returns_not_delivered(api):
    """PRD §3.7: "The order must be in DELIVERED or CLOSED; a claim against an order in any
    other state is rejected with ERR_ORDER_NOT_DELIVERED (HTTP 409)."

    Design: Corner/validations/claim_on_undelivered_order_returns_not_delivered
    """
    ctx = setup_confirmed_order(plan_overrides=SATISFACTION_PLAN, with_coach=False)
    resp = api.create_guarantee_claim(ctx["order_id"], {"claim_type": "SATISFACTION", "evidence": "too soon"},
                                      ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERED.value)


def test_claim_type_not_offered_returns_guarantee_not_offered(api):
    """PRD §3.7: "the order's `guarantee_type`, copied from the plan, must equal the
    `claim_type` and must not be `NONE` — otherwise the claim is rejected with
    `ERR_GUARANTEE_NOT_OFFERED` (HTTP 409)."

    Design: Corner/validations/claim_type_not_offered_returns_guarantee_not_offered
    """
    ctx = setup_delivered_order(plan_overrides=SATISFACTION_PLAN)
    resp = api.create_guarantee_claim(ctx["order_id"], {"claim_type": "INTERVIEW", "evidence": "no interviews"},
                                      ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_OFFERED.value)


def test_duplicate_claim_returns_already_exists(api):
    """PRD §3.7: "No claim may be filed when an open claim, meaning one that is SUBMITTED or
    already APPROVED, exists for the order; a duplicate is rejected with
    ERR_CLAIM_ALREADY_EXISTS (HTTP 409)."

    Design: Corner/errors/duplicate_claim_returns_already_exists
    """
    ctx = setup_delivered_order(plan_overrides=SATISFACTION_PLAN)
    validate_success(api.create_guarantee_claim(
        ctx["order_id"], {"claim_type": "SATISFACTION", "evidence": "first claim"}, ctx["client_headers"]), 201)
    resp = api.create_guarantee_claim(
        ctx["order_id"], {"claim_type": "SATISFACTION", "evidence": "second claim"}, ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS.value)
