"""Validation precedence between competing guards, and cross-entity state
dependencies (order pay depends on seller status; shift book depends on
campaign posture).

Covers difficulty queue A rules: priority_pair_validation_conflict,
cross_entity_state_dependency.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_active_catalog, setup_active_event,
    place_simple_order, add_volunteer, add_shift,
    MISSING_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]


# ─── priority_pair_validation_conflict / posture_gate_beats_seller_blocked_on_pay

class TestPostureGateBeatsSellerBlocked:
    def _setup_frozen_with_blocked_seller_order(self):
        # PRD §3.3: blocking a seller cancels their still-PENDING+PLACED orders,
        # so an order placed BEFORE the block would be CANCELLED and pay would
        # trip state-legality (ERR_INVALID_STATE) before reaching the posture /
        # seller-block guards. To exercise the posture-vs-seller-block
        # precedence faithfully, block first, then place the order (order
        # create carries no seller-block guard — PRD §2.9 lists the guard for
        # exactly pay/record/collect), then freeze. The order is thus PENDING +
        # PLACED (not cancelled) while the campaign is FROZEN and the seller is
        # BLOCKED, so both the posture gate and the seller-block guard apply.
        camp, seller, product = setup_active_catalog()
        api_client.block_seller(seller["id"], ADMIN)
        order = place_simple_order(camp["id"], seller["id"], product["id"], 5)
        api_client.freeze_campaign(camp["id"], ADMIN)
        return order

    def test_pay_on_frozen_with_blocked_seller_reports_posture_gate(self, api, admin_headers):
        """PRD §2.9: "When multiple guards could fire on one request, the
        precedence is: authentication, authorization, path existence,
        reference existence, body shape, optimistic concurrency, state
        legality, posture gate, seller-block guard, and then the remaining
        domain guards."

        PRD §3.1: "all forward-progress child transitions — paying,
        confirming, or delivering orders; recording or collecting pledges;
        booking shifts — are blocked with `ERR_CAMPAIGN_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/posture_gate_beats_seller_blocked_on_pay
        """
        order = self._setup_frozen_with_blocked_seller_order()
        res = api.pay_order(order["id"], admin_headers)
        validate_error(res, "ERR_CAMPAIGN_NOT_ACTIVE", expected_status=409)

    def test_blocked_seller_alone_does_not_preempt_posture(self, api, admin_headers):
        """PRD §2.9: "Second comes the **campaign-posture gate**: a campaign in
        `DRAFT` posture blocks the creation and transition of all of its
        children, and a campaign in `FROZEN` posture blocks every
        forward-progress child transition."
        PRD §2.9: "Third comes the **seller-block guard**: a revenue-affecting
        transition whose crediting seller is `BLOCKED` is rejected with
        `ERR_SELLER_BLOCKED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/posture_gate_beats_seller_blocked_on_pay
        """
        order = self._setup_frozen_with_blocked_seller_order()
        res = api.pay_order(order["id"], admin_headers)
        # The reported error must be the posture gate, not the seller-block guard.
        body = res.json()
        assert body["data"]["error_id"] == "ERR_CAMPAIGN_NOT_ACTIVE", \
            f"posture gate must win over seller-block guard, got {body['data']['error_id']}"


# ─── priority_pair_validation_conflict / reference_not_found_beats_insufficient_stock_on_order_create

class TestReferenceNotFoundBeatsInsufficientStock:
    def test_bad_seller_fk_with_overstock_reports_reference_not_found(self, api, admin_headers):
        """PRD §2.6: "Referential existence of body foreign keys is checked
        fourth: when a `campaign_id`, `seller_id`, `product_id`, or
        `volunteer_id` supplied in the body either does not exist or does not
        belong to the named campaign, the request is rejected with
        `ERR_REFERENCE_NOT_FOUND`."

        Design: Difficulty/priority_pair_validation_conflict/reference_not_found_beats_insufficient_stock_on_order_create
        """
        camp, seller, product = setup_active_catalog(stock_qty=2)
        res = api.create_order({
            "campaign_id": camp["id"],
            "seller_id": MISSING_UUID,
            "buyer_name": "B",
            "buyer_email": "b@x.com",
            "lines": [{"product_id": product["id"], "quantity": 99}],
        }, admin_headers)
        validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=404)

    def test_reference_check_precedes_stock_check(self, api, admin_headers):
        """PRD §2.9: "When multiple guards could fire on one request, the
        precedence is: authentication, authorization, path existence,
        reference existence, body shape, optimistic concurrency, state
        legality, posture gate, seller-block guard, and then the remaining
        domain guards."

        Design: Difficulty/priority_pair_validation_conflict/reference_not_found_beats_insufficient_stock_on_order_create
        """
        camp, seller, product = setup_active_catalog(stock_qty=2)
        res = api.create_order({
            "campaign_id": camp["id"],
            "seller_id": MISSING_UUID,
            "buyer_name": "B",
            "buyer_email": "b@x.com",
            "lines": [{"product_id": product["id"], "quantity": 99}],
        }, admin_headers)
        body = res.json()
        assert body["data"]["error_id"] == "ERR_REFERENCE_NOT_FOUND", \
            f"reference existence must win over stock guard, got {body['data']['error_id']}"


# ─── cross_entity_state_dependency / order_pay_blocked_when_seller_blocked ─

class TestOrderPayDependsOnSellerStatus:
    def test_pay_rejected_when_seller_blocked(self, api, admin_headers):
        """PRD §3.3: "while a seller is `BLOCKED`, three revenue-affecting
        transitions naming that seller are refused with `ERR_SELLER_BLOCKED`:
        paying one of their orders, recording one of their pledges, and
        collecting one of their pledges."

        Design: Difficulty/cross_entity_state_dependency/order_pay_blocked_when_seller_blocked
        """
        # PRD §3.3: blocking a seller cancels their PENDING+PLACED orders, so an
        # order placed before the block would be CANCELLED and pay would trip
        # state-legality. Order create carries no seller-block guard (PRD §2.9
        # scopes that guard to pay/record/collect), so block first, then place
        # the order: it stays PENDING+PLACED with a BLOCKED crediting seller, and
        # paying it reaches the seller-block guard -> ERR_SELLER_BLOCKED.
        camp, seller, product = setup_active_catalog()
        api_client.block_seller(seller["id"], ADMIN)
        order = place_simple_order(camp["id"], seller["id"], product["id"], 3)
        res = api.pay_order(order["id"], admin_headers)
        validate_error(res, "ERR_SELLER_BLOCKED", expected_status=409)

    def test_pay_rejected_leaves_order_pending(self, api, admin_headers):
        """PRD §3.4: "Paying an order moves `payment_status` from `PENDING` to
        `PAID`. Payment is permitted only when the campaign posture is
        `ACTIVE`, the order's `fulfillment_status` is not `CANCELLED`, and the
        crediting seller is `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/order_pay_blocked_when_seller_blocked
        """
        # Block first, then place the order, so the seller-block guard (not the
        # PRD §3.3 block cascade that would cancel a pre-existing order) is the
        # reason pay is rejected; the order must stay PENDING on the payment axis.
        camp, seller, product = setup_active_catalog()
        api_client.block_seller(seller["id"], ADMIN)
        order = place_simple_order(camp["id"], seller["id"], product["id"], 3)
        api.pay_order(order["id"], admin_headers)
        after = validate_success(api.get_order(order["id"], admin_headers), 200)
        assert after["payment_status"] == "PENDING", \
            "a rejected pay must leave payment_status unchanged at PENDING"


# ─── cross_entity_state_dependency / shift_book_blocked_when_campaign_frozen

class TestShiftBookDependsOnCampaignPosture:
    def test_book_rejected_when_campaign_frozen(self, api, admin_headers):
        """PRD §3.1: "While `FROZEN`, all forward-progress child transitions —
        paying, confirming, or delivering orders; recording or collecting
        pledges; booking shifts — are blocked with `ERR_CAMPAIGN_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/shift_book_blocked_when_campaign_frozen
        """
        camp, _ = setup_active_event()
        volunteer = add_volunteer(camp["id"])
        shift = add_shift(camp["id"], "2026-04-10T09:00:00Z", "2026-04-10T12:00:00Z",
                          role_label="GRILL")
        api_client.freeze_campaign(camp["id"], ADMIN)
        res = api.book_shift(shift["id"], {"volunteer_id": volunteer["id"]}, admin_headers)
        validate_error(res, "ERR_CAMPAIGN_NOT_ACTIVE", expected_status=409)

    def test_book_rejected_leaves_shift_open(self, api, admin_headers):
        """PRD §3.9: "Booking a shift moves it from `OPEN` to `BOOKED` and
        assigns a `volunteer_id`. Booking is permitted only when the campaign
        is `ACTIVE` and the named volunteer belongs to the same campaign."

        Design: Difficulty/cross_entity_state_dependency/shift_book_blocked_when_campaign_frozen
        """
        camp, _ = setup_active_event()
        volunteer = add_volunteer(camp["id"])
        shift = add_shift(camp["id"], "2026-04-10T09:00:00Z", "2026-04-10T12:00:00Z",
                          role_label="GRILL")
        api_client.freeze_campaign(camp["id"], ADMIN)
        api.book_shift(shift["id"], {"volunteer_id": volunteer["id"]}, admin_headers)
        after = validate_success(api.get_shift(shift["id"], admin_headers), 200)
        assert after["status"] == "OPEN", "a rejected book must leave the shift OPEN"
