"""Approval workflow: cyclic state machines, the strict requires_approval
boundary, cross-entity gating on branding-approval and message-proof-lock, and
the CSV-import zero-accepted-rows boundary.

Translations of Difficulty/non_linear_state_machine (2), boundary_precision_check
(2), and cross_entity_state_dependency (2).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, factories, fixtures,
)
from test_helpers.test_users import TEST_USERS, make_account_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
FIN = TEST_USERS["finance_approver_headers"]
PROOF = TEST_USERS["proof_approver_headers"]


class TestApprovalCycleRejectResubmit:
    """CorporateOrder.approval_status forms a cycle:
    PENDING_APPROVAL → REJECTED → PENDING_APPROVAL. The same BudgetApproval row
    is reset on resubmit, not duplicated."""

    def test_order_reenters_pending_approval_after_reject_then_resubmit(self, api):
        """PRD §3.4: "the order's production_status stays DRAFT, and the
        AccountManager may resubmit later, closing the cycle PENDING_APPROVAL
        → REJECTED → PENDING_APPROVAL."

        Design: Difficulty/non_linear_state_machine/corporate_order_reject_then_resubmit_closes_the_approval_cycle
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Pen Basket", base_price_cents=4000))
        p = fixtures.setup_pending_approval_order(
            api, base=base,
            rows=[factories.recipient_row(quantity=5)],
            requested_by_user_id="emp-req-1")
        # Human REJECT.
        fixtures.budget_decision(
            api, order_id=p["order"]["id"], decision="REJECT",
            approver_user_id="fin-appr-6",
            decision_reason="Needs revised recipient count")
        # Resubmit closes the cycle back to PENDING_APPROVAL.
        fixtures.submit_for_approval(
            api, account_id=base["account"]["id"],
            order_id=p["order"]["id"], requested_by_user_id="emp-req-6")
        order = validate_success(api.get_order(p["order"]["id"], ADMIN))
        assert order["approval_status"] == "PENDING_APPROVAL"

    def test_same_budget_approval_row_is_reset_on_resubmit(self, api):
        """PRD §3.4: "If the same order is later resubmitted after having been
        REJECTED, the system resets that same BudgetApproval row (decision back
        to PENDING, requested_by_user_id overwritten, approver_user_id and
        decided_at cleared to null) instead of creating a second one,
        preserving a strict one-to-one relationship between an order and its
        budget-approval record."

        Design: Difficulty/non_linear_state_machine/corporate_order_reject_then_resubmit_closes_the_approval_cycle
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Pen Basket", base_price_cents=4000))
        p = fixtures.setup_pending_approval_order(
            api, base=base,
            rows=[factories.recipient_row(quantity=5)],
            requested_by_user_id="emp-req-1")
        fixtures.budget_decision(
            api, order_id=p["order"]["id"], decision="REJECT",
            approver_user_id="fin-appr-6",
            decision_reason="Needs revised recipient count")
        fixtures.submit_for_approval(
            api, account_id=base["account"]["id"],
            order_id=p["order"]["id"], requested_by_user_id="emp-req-6")
        data, _ = validate_paginated(
            api.list_budget_approvals(p["order"]["id"], ADMIN))
        assert len(data) == 1, "exactly one BudgetApproval row exists (1:1)"
        assert data[0]["decision"] == "PENDING"
        assert data[0]["requested_by_user_id"] == "emp-req-6"


class TestMessageProofRevisionLoop:
    """MessageProof cycle: SUBMITTED → REVISION_REQUESTED → DRAFT → SUBMITTED,
    with revision_count incremented each revision."""

    def test_proof_returns_to_submitted_after_revision_and_resubmit(self, api):
        """PRD §3.5: "The sibling REQUEST_REVISION branch is symmetric in
        structure: it sets proof_status to REVISION_REQUESTED, records the same
        decided_by_user_id, and increments revision_count by one; the system
        then immediately, as its own follow-up step, advances that proof from
        REVISION_REQUESTED back to DRAFT, at which point the AccountManager may
        resubmit — closing the cycle SUBMITTED → REVISION_REQUESTED → DRAFT →
        SUBMITTED."

        Design: Difficulty/non_linear_state_machine/message_proof_revision_loop_returns_to_submitted
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000)
        _, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="proof@example.com", quantity=1)],
            occasion="THANK_YOU")
        proof = fixtures.submit_message_proof(
            api, account_id=base["account"]["id"],
            recipient_id=rec[0]["id"], message_text="Congrats!",
            submitted_by_user_id="emp-msg-2")
        fixtures.decide_message_proof(
            api, proof_id=proof["id"], decision="REQUEST_REVISION",
            decided_by_user_id="proof-appr-2")
        # Resubmit — closes the cycle back to SUBMITTED.
        fixtures.submit_message_proof(
            api, account_id=base["account"]["id"],
            recipient_id=rec[0]["id"], message_text="Congrats again!",
            submitted_by_user_id="emp-msg-2")
        data, _ = validate_paginated(
            api.get_message_proof(rec[0]["id"], PROOF))
        p = data[0]
        assert p["proof_status"] == "SUBMITTED"
        assert p["message_text"] == "Congrats again!"

    def test_revision_count_incremented_after_request_revision(self, api):
        """PRD §3.5: "it sets proof_status to REVISION_REQUESTED, records the
        same decided_by_user_id, and increments revision_count by one"

        Design: Difficulty/non_linear_state_machine/message_proof_revision_loop_returns_to_submitted
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000)
        _, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="rev@example.com", quantity=1)],
            occasion="THANK_YOU")
        proof = fixtures.submit_message_proof(
            api, account_id=base["account"]["id"],
            recipient_id=rec[0]["id"], message_text="Congrats!",
            submitted_by_user_id="emp-msg-2")
        fixtures.decide_message_proof(
            api, proof_id=proof["id"], decision="REQUEST_REVISION",
            decided_by_user_id="proof-appr-2")
        fixtures.submit_message_proof(
            api, account_id=base["account"]["id"],
            recipient_id=rec[0]["id"], message_text="Congrats again!",
            submitted_by_user_id="emp-msg-2")
        data, _ = validate_paginated(
            api.get_message_proof(rec[0]["id"], PROOF))
        assert data[0]["revision_count"] == 1


class TestRequiresApprovalStrictGreaterThanBoundary:
    """requires_approval flips only when total_cost_cents STRICTLY exceeds the
    account's approval_threshold_cents. Equal to threshold auto-approves; one
    increment above requires human approval."""

    def test_total_equal_to_threshold_auto_approves(self, api):
        """PRD §3.4: "requires_approval is then set to true only when this
        total_cost_cents strictly exceeds the account's approval_threshold_cents
        — equal to the threshold still auto-approves."

        Design: Difficulty/boundary_precision_check/requires_approval_strict_greater_than_threshold_boundary
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=200_000,
            approval_threshold_cents=40_000,
            template_kwargs=dict(name="Bottle Basket", base_price_cents=4000))
        # 10 × 4000 = 40000 == threshold; TIER_0 0%; remaining_budget=200000
        # < SILVER_THRESHOLD (250000) so 0% loyalty; total = 40000.
        order, _ = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="at@example.com", quantity=10)],
            occasion="ONBOARDING")
        fixtures.submit_for_approval(
            api, account_id=base["account"]["id"], order_id=order["id"],
            requested_by_user_id="emp-req-11",
            station_id=base["station"]["id"],
            scheduled_date="2026-03-04T00:00:00Z")
        got = validate_success(api.get_order(order["id"], ADMIN))
        assert got["total_cost_cents"] == 40000
        assert got["requires_approval"] is False
        assert got["approval_status"] == "APPROVED"

    def test_total_one_notch_above_threshold_requires_approval(self, api):
        """PRD §3.4: "requires_approval is then set to true only when this
        total_cost_cents strictly exceeds the account's approval_threshold_cents"

        Design: Difficulty/boundary_precision_check/requires_approval_strict_greater_than_threshold_boundary
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=200_000,
            approval_threshold_cents=40_000,
            template_kwargs=dict(name="Bottle Basket", base_price_cents=4000))
        # 11 × 4000 = 44000 > 40000 threshold; TIER_0; total = 44000.
        order, _ = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="over@example.com", quantity=11)],
            occasion="ONBOARDING")
        fixtures.submit_for_approval(
            api, account_id=base["account"]["id"], order_id=order["id"],
            requested_by_user_id="emp-req-12",
            station_id=base["station"]["id"],
            scheduled_date="2026-03-04T00:00:00Z")
        got = validate_success(api.get_order(order["id"], ADMIN))
        assert got["total_cost_cents"] == 44000
        assert got["requires_approval"] is True
        assert got["approval_status"] == "PENDING_APPROVAL"


class TestImportBatchZeroAcceptedRowsBoundary:
    """A batch where every row is individually REJECTED for insufficient
    forward-looking inventory fails the whole call with
    ERR_IMPORT_BATCH_ALL_ROWS_REJECTED."""

    def test_all_rows_fail_forward_inventory_returns_batch_error(self, api):
        """PRD §3.4: "After every row in the batch has been evaluated this way,
        if not a single row was accepted, the entire batch call fails with
        ERR_IMPORT_BATCH_ALL_ROWS_REJECTED (422)."

        Design: Difficulty/boundary_precision_check/import_batch_zero_accepted_rows_boundary
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000)
        sku = fixtures.create_sku(api, name="Sold Out", unit_cost_cents=500,
                                  is_perishable=False, on_hand_qty=0)
        template = fixtures.create_template(
            api, name="Gadget Basket", base_price_cents=3000,
            category="CORPORATE_WELCOME", sku_id=sku["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"], occasion="CUSTOM")
        from test_helpers.test_users import make_account_manager_headers
        hdrs = make_account_manager_headers(account["id"])
        resp = api.import_recipients(
            order["id"],
            {"rows": [
                factories.recipient_row(email="rowone@example.com", quantity=1),
                factories.recipient_row(email="rowtwo@example.com", quantity=1),
            ]}, hdrs)
        validate_error(resp, ApiErrorId.ERR_IMPORT_BATCH_ALL_ROWS_REJECTED.value)

    def test_no_recipients_persisted_when_whole_batch_rejected(self, api):
        """PRD §3.4: "a rejected row never contributes to recipient counts, cost
        calculations, or any downstream cascade."

        Design: Difficulty/boundary_precision_check/import_batch_zero_accepted_rows_boundary
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000)
        sku = fixtures.create_sku(api, name="Sold Out", unit_cost_cents=500,
                                  is_perishable=False, on_hand_qty=0)
        template = fixtures.create_template(
            api, name="Gadget Basket", base_price_cents=3000,
            category="CORPORATE_WELCOME", sku_id=sku["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"], occasion="CUSTOM")
        from test_helpers.test_users import make_account_manager_headers
        hdrs = make_account_manager_headers(account["id"])
        api.import_recipients(
            order["id"],
            {"rows": [factories.recipient_row(email="a@example.com", quantity=1)]},
            hdrs)
        data, _ = validate_paginated(api.list_recipients(order["id"], hdrs))
        # No ACCEPTED rows must appear; the batch call failed atomically.
        assert not any(r.get("import_row_status") == "ACCEPTED" for r in data), \
            "no ACCEPTED recipients from a wholly rejected batch"


class TestOrderApprovalGatedByBrandingProfileApproval:
    """CorporateOrder cannot reach APPROVED while its branding_profile is not
    yet compliance-approved (approved=false). Flipping the profile to
    approved=true unblocks the same order's approval with no other change."""

    def test_approve_rejected_while_branding_profile_not_approved(self, api):
        """PRD §3.3: "the order cannot advance out of PENDING_APPROVAL into
        APPROVED while its branding_profile_id points at a profile whose
        approved is still false — that attempt is rejected with
        ERR_BRANDING_PROFILE_NOT_APPROVED (422)."

        Design: Difficulty/cross_entity_state_dependency/order_approval_gated_by_branding_profile_approval_state
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(api, name="Coaster Set", unit_cost_cents=300,
                                  is_perishable=False, on_hand_qty=100)
        template = fixtures.create_template(
            api, name="Coaster Basket", category="CLIENT_APPRECIATION",
            base_price_cents=4000, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station X", daily_capacity=1000)
        profile = fixtures.create_branding_profile(
            api, account=account, name="Xi Kit", accent_color="#667788",
            card_stock="RECYCLED")
        account = fixtures.get_account(api, account_id=account["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="CLIENT_APPRECIATION",
            branding_profile_id=profile["id"])
        from test_helpers.test_users import make_account_manager_headers
        fixtures.import_recipients(
            api, account_id=account["id"], order_id=order["id"],
            rows=[factories.recipient_row(email="dep@example.com", quantity=2)])
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order["id"],
            requested_by_user_id="emp-req-13")
        resp = api.budget_decision(
            order["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-13",
                station_id=station["id"],
                scheduled_date="2026-03-04T00:00:00Z"),
            FIN)
        validate_error(resp, ApiErrorId.ERR_BRANDING_PROFILE_NOT_APPROVED.value)

    def test_approve_succeeds_after_flipping_profile_to_approved(self, api):
        """PRD §3.3: "it is flipped to true only through a PlatformAdmin-exclusive
        compliance sign-off call, and there is no path for it to become false
        again once approved."

        Design: Difficulty/cross_entity_state_dependency/order_approval_gated_by_branding_profile_approval_state
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(api, name="Coaster Set", unit_cost_cents=300,
                                  is_perishable=False, on_hand_qty=100)
        template = fixtures.create_template(
            api, name="Coaster Basket", category="CLIENT_APPRECIATION",
            base_price_cents=4000, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station X", daily_capacity=1000)
        profile = fixtures.create_branding_profile(
            api, account=account, name="Xi Kit", accent_color="#667788",
            card_stock="RECYCLED")
        account = fixtures.get_account(api, account_id=account["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="CLIENT_APPRECIATION",
            branding_profile_id=profile["id"])
        fixtures.import_recipients(
            api, account_id=account["id"], order_id=order["id"],
            rows=[factories.recipient_row(email="dep2@example.com", quantity=2)])
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order["id"],
            requested_by_user_id="emp-req-13")
        # First APPROVE attempt is rejected.
        first = api.budget_decision(
            order["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-13",
                station_id=station["id"],
                scheduled_date="2026-03-04T00:00:00Z"),
            FIN)
        validate_error(first, ApiErrorId.ERR_BRANDING_PROFILE_NOT_APPROVED.value)
        # Flip the branding profile to approved=true.
        fixtures.approve_branding_profile(api, profile_id=profile["id"])
        # Second APPROVE succeeds.
        second = api.budget_decision(
            order["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-13",
                station_id=station["id"],
                scheduled_date="2026-03-04T00:00:00Z"),
            FIN)
        after = validate_success(second)
        assert after["approval_status"] == "APPROVED"


class TestShipmentCreationGatedByMessageProofLock:
    """Shipment creation requires the recipient's MessageProof to be LOCKED."""

    def test_shipment_creation_rejected_when_proof_not_locked(self, api):
        """PRD §3.8: "ShippingOps may only create a Shipment for a recipient
        whose MessageProof.proof_status is LOCKED — any earlier status is
        rejected with ERR_MESSAGE_PROOF_NOT_LOCKED (422)."

        Design: Difficulty/cross_entity_state_dependency/shipment_creation_gated_by_message_proof_lock_state
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Frame Basket",
                                 category="CLIENT_APPRECIATION",
                                 base_price_cents=3800))
        zone = fixtures.create_shipping_zone(
            api, zone_code="US-EAST", country_codes=["US"],
            carrier="SwiftShip", base_rate_cents=500, per_kg_rate_cents=100,
            transit_days_min=2, transit_days_max=5, blackout_dates=[])
        _, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="ungated@example.com", quantity=1)],
            occasion="THANK_YOU")
        resp = api.create_shipment(
            rec[0]["id"],
            factories.create_shipment_payload(
                zone_id=zone["id"], ship_date="2026-03-05T00:00:00Z"),
            TEST_USERS["shipping_ops_headers"])
        validate_error(resp, ApiErrorId.ERR_MESSAGE_PROOF_NOT_LOCKED.value)

    def test_shipment_creation_succeeds_after_proof_locks(self, api):
        """PRD §3.5: "The APPROVE branch sets proof_status to APPROVED and
        records decided_by_user_id; the system then immediately, as its own
        follow-up step, advances that same proof from APPROVED to LOCKED,
        permanently freezing the final card text and — as detailed in §3.8 —
        unblocking shipment creation for that recipient."

        Design: Difficulty/cross_entity_state_dependency/shipment_creation_gated_by_message_proof_lock_state
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Frame Basket",
                                 category="CLIENT_APPRECIATION",
                                 base_price_cents=3800))
        zone = fixtures.create_shipping_zone(
            api, zone_code="US-EAST", country_codes=["US"],
            carrier="SwiftShip", base_rate_cents=500, per_kg_rate_cents=100,
            transit_days_min=2, transit_days_max=5, blackout_dates=[])
        _, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="gated@example.com", quantity=1)],
            occasion="THANK_YOU")
        fixtures.lock_message_proof_for_recipient(
            api, account_id=base["account"]["id"], recipient_id=rec[0]["id"],
            message_text="Thank you!",
            submitted_by="emp-msg-3", decided_by="proof-appr-3")
        shipment = fixtures.create_shipment(
            api, recipient_id=rec[0]["id"], zone_id=zone["id"],
            ship_date="2026-03-05T00:00:00Z")
        assert shipment["status"] == "CREATED"
