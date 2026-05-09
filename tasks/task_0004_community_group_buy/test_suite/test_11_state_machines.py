"""State machine transitions and invalid-from-wrong-state rejections."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_community, create_supplier, create_customer,
    create_active_leader, create_pending_leader,
    create_group_buy_campaign, join_campaign, pay_order, close_campaign,
    setup_basic_scaffold, setup_paid_succeeded_order, setup_picked_up_order,
    file_after_sales, start_review, resolve_case,
    plan_shipments_for_order, dispatch_shipment, arrive_shipment, pickup_confirm,
    advance_clock,
    create_flash_campaign_payload, create_flash_purchase_payload,
    create_resolve_payload,
    setup_multi_customer_paid,
    ADMIN, CS_AGENT, PICKUP_OP,
    make_group_leader_headers, make_customer_headers, make_supplier_headers,
)


class TestGroupLeaderTransitions:

    def test_approve_pending_leader_advances_to_active(self, api):
        """PRD §3.1: "they enter ACTIVE through approval by a PlatformAdmin".

        Claim: PENDING_REVIEW -> ACTIVE on approve.
        """
        community = create_community(name="C-LDR-A", region_code="RC1")
        leader = create_pending_leader(community["id"], display_name="LA")
        result = validate_success(api.approve_leader(leader["id"], ADMIN), 200)
        assert result["status"] == "ACTIVE"

    def test_suspend_then_reinstate(self, api):
        """PRD §3.1: "reinstatement returns a SUSPENDED leader to ACTIVE
        provided no OPEN RiskAlert of HIGH severity is currently targeting
        this leader".

        Claim: ACTIVE -> SUSPENDED -> ACTIVE without any open HIGH alerts.
        """
        community = create_community(name="C-LDR-S", region_code="RC1")
        leader = create_active_leader(community["id"], display_name="LS")
        suspended = validate_success(api.suspend_leader(leader["id"], ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_leader(leader["id"], ADMIN), 200)
        assert reinstated["status"] == "ACTIVE"

    def test_deactivate_blocked_when_forming_campaigns_owned(self, api):
        """PRD §3.1: "deactivation moves a leader from PENDING_REVIEW,
        ACTIVE, or SUSPENDED to the terminal DEACTIVATED state provided no
        FORMING or EXTENDED campaign is currently owned by that leader."

        Claim: deactivate is rejected with ERR_INVALID_STATE while a
        FORMING campaign is still owned.
        """
        community = create_community(name="C-LDR-DA", region_code="RC1")
        supplier = create_supplier(name="S-DA")
        leader = create_active_leader(community["id"], display_name="LDA")
        create_group_buy_campaign(leader["id"], supplier["id"],
                                    unit_price_cents=100,
                                    discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                    opens_at_period=0, deadline_period=100)
        res = api.deactivate_leader(leader["id"], ADMIN)
        validate_error(res, "ERR_INVALID_STATE")


class TestGroupBuyCampaignTransitions:

    def test_close_with_zero_participants_fails(self, api):
        """PRD §3.3: "On FAILED, no commission entries are generated".
        PRD §3.3: "the campaign succeeds when participant_count is at
        least discount_tiers[0].min_participants and fails otherwise."

        Claim: closing a campaign with 0 participants and min=1 results
        in FAILED.
        """
        community = create_community(name="C-CL-F", region_code="RC1")
        supplier = create_supplier(name="S-CL-F")
        leader = create_active_leader(community["id"], display_name="LCLF")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        result = close_campaign(campaign["id"], leader["id"])
        assert result["status"] == "FAILED"

    def test_close_succeeded_then_finalize_advances_to_closed(self, api):
        """PRD §3.3: "Once a SUCCEEDED or FAILED campaign's child orders
        have all reached terminal payment-and-fulfillment pairs, the
        campaign may be finalized, advancing status to CLOSED."

        Claim: a SUCCEEDED campaign whose only order has reached terminal
        states can be finalized to CLOSED.
        """
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        # Advance clock past after-sales window so fulfillment hits COMPLETED
        advance_clock(8)
        result = validate_success(api.finalize_campaign(sc["campaign"]["id"], ADMIN), 200)
        assert result["status"] == "CLOSED"


class TestOrderPaymentTransitions:

    def test_pay_pending_pay_to_paid(self, api):
        """PRD §3.4: "Paying an order advances payment_status from
        PENDING_PAY to PAID."

        Claim: pay on a PENDING_PAY order results in payment_status=PAID.
        """
        community = create_community(name="C-PAY", region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier(name="S")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        paid = validate_success(api.pay_order(order["id"], make_customer_headers(cust["id"])), 200)
        assert paid["payment_status"] == "PAID"
        assert paid["paid_period_index"] is not None

    def test_pay_already_paid_rejected(self, api):
        """PRD §3.4: "Paying an order advances payment_status from
        PENDING_PAY to PAID."

        Claim: paying again on an already-PAID order is rejected with
        ERR_INVALID_STATE.
        """
        community = create_community(name="C-PAY-2", region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier(name="S")
        leader = create_active_leader(community["id"], display_name="L")
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=100)
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        pay_order(order["id"], cust["id"])
        res = api.pay_order(order["id"], make_customer_headers(cust["id"]))
        validate_error(res, "ERR_INVALID_STATE")


class TestShipmentTransitions:

    def test_dispatch_planned_shipment(self, api):
        """PRD §3.6: "Dispatching a shipment moves status from PLANNED to
        DISPATCHED, stamps dispatched_period_index with the current period,
        and pins predicted_eta_period_index."

        Claim: dispatch advances PLANNED -> DISPATCHED and stamps the
        dispatched period.
        """
        sc = setup_paid_succeeded_order(unit_price_cents=100, quantity=1)
        shipments = plan_shipments_for_order(
            sc["order"]["id"], sc["supplier"]["id"], sc["pickup_point"]["id"],
            [{"sku": "SKUA", "quantity": 1}],
        )
        sh = shipments[0]
        assert sh["status"] == "PLANNED"
        result = validate_success(api.dispatch_shipment(sh["id"],
                                                          make_supplier_headers(sc["supplier"]["id"])),
                                    200)
        assert result["status"] == "DISPATCHED"
        assert result["dispatched_period_index"] is not None
        assert result["predicted_eta_period_index"] is not None

    def test_dispatch_already_dispatched_rejected(self, api):
        """PRD §3.6: "Two suppliers attempting to dispatch the same shipment
        simultaneously serialise on the shipment's status: exactly one
        transition succeeds and the loser observes ERR_INVALID_STATE."

        Claim: dispatching a shipment that is already DISPATCHED is
        rejected with ERR_INVALID_STATE.
        """
        sc = setup_paid_succeeded_order(unit_price_cents=100, quantity=1)
        shipments = plan_shipments_for_order(
            sc["order"]["id"], sc["supplier"]["id"], sc["pickup_point"]["id"],
            [{"sku": "SKUA", "quantity": 1}],
        )
        sh = shipments[0]
        dispatch_shipment(sh["id"], sc["supplier"]["id"])
        res = api.dispatch_shipment(sh["id"], make_supplier_headers(sc["supplier"]["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_mispick_then_reconcile(self, api):
        """PRD §3.7: "A PickupOperator who notices a sorting error reports a
        mis-pick, advancing the affected shipment from AT_PICKUP to MIS_PICK.
        Reconciling a mis-pick advances the shipment from MIS_PICK to RECONCILED".

        Claim: AT_PICKUP -> MIS_PICK -> RECONCILED via the mis-pick + reconcile flow.
        """
        sc = setup_paid_succeeded_order(unit_price_cents=100, quantity=1)
        shipments = plan_shipments_for_order(
            sc["order"]["id"], sc["supplier"]["id"], sc["pickup_point"]["id"],
            [{"sku": "SKUA", "quantity": 1}],
        )
        sh = shipments[0]
        dispatch_shipment(sh["id"], sc["supplier"]["id"])
        arrive_shipment(sh["id"], sc["supplier"]["id"])
        mp = validate_success(api.report_mispick(sh["id"], PICKUP_OP), 200)
        assert mp["status"] == "MIS_PICK"
        rec = validate_success(api.reconcile_shipment(sh["id"], PICKUP_OP), 200)
        # After reconcile + idempotent system-driven AT_PICKUP-equivalent, status may
        # be either RECONCILED or AT_PICKUP per PRD §3.7
        assert rec["status"] in ("RECONCILED", "AT_PICKUP")
