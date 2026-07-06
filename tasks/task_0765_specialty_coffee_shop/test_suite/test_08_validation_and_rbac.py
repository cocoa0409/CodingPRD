"""Validation errors, RBAC, ownership, and priority-conflict resolution."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
)


# --------------------------------------------------------------------------
# Priority conflict: suspended member (state) beats insufficient points (fiscal)
# --------------------------------------------------------------------------
class TestSuspendedBeatsInsufficientPoints:
    def _reject(self, api, headers):
        member = th.new_member(api, headers=headers, email="susp@example.com",
                               full_name="Susp", status="SUSPENDED")
        item = th.new_menu_item(api, name="Batch S", category="BEVERAGE", base_price_cents=400,
                                required_equipment_type="BATCH_BREW", size="MEDIUM",
                                origin_required=False, headers=headers)
        return api.create_order(
            {"member_id": member["id"],
             "lines": [{"menu_item_id": item["id"], "quantity": 1, "modifier_ids": []}],
             "points_redeemed": 50}, headers)

    def test_suspended_member_error_reported(self, api, manager_headers):
        """PRD 3.5: "If the order names a member whose `status` is `SUSPENDED`,
        placement is rejected with `ERR_MEMBER_SUSPENDED`."
        PRD 2.8: "State — the target resource is in a state that permits the
        requested transition (this includes a member being `ACTIVE` for order
        placement, and the OCC parent-state check), else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_member_beats_insufficient_points
        """
        resp = self._reject(api, manager_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value)

    def test_suspended_conflict_returns_http_409(self, api, manager_headers):
        """PRD 2.8: "Fiscal capacity — points redeemed within the member's balance,
        and a bean draw within the active lot's on-hand grams (HTTP 422)."
        PRD 5: the `ERR_MEMBER_SUSPENDED` error carries HTTP status 409.

        Design: Difficulty/priority_pair_validation_conflict/suspended_member_beats_insufficient_points
        """
        resp = self._reject(api, manager_headers)
        assert resp.status_code == 409, f"got {resp.status_code}"


# --------------------------------------------------------------------------
# Cross-entity: fulfill blocked by no ACTIVE bean lot
# --------------------------------------------------------------------------
class TestFulfillBlockedByNoActiveLot:
    def _order_no_active_lot(self, api, headers):
        th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=headers)
        # lot created but never activated -> stays RESERVE
        th.new_bean_lot(api, origin="ETHIOPIA", roast_level="MEDIUM", received_grams=1000,
                        par_grams=200, price_per_gram_cents=5, headers=headers)
        latte = th.new_menu_item(api, name="Latte LG", category="BEVERAGE", base_price_cents=450,
                                 required_equipment_type="ESPRESSO", size="LARGE", bean_grams=18,
                                 origin_required=True, bean_origin="ETHIOPIA", headers=headers)
        return th.new_order(api, headers=headers,
                            lines=[{"menu_item_id": latte["id"], "quantity": 1, "modifier_ids": []}])

    def test_fulfill_rejected_without_active_lot(self, api, manager_headers):
        """PRD 3.6: "Second, every origin-required line must have an `ACTIVE` bean
        lot for its `bean_origin`; if no such active lot exists the rejection is
        `ERR_BEAN_LOT_UNAVAILABLE`, and if an active lot exists but its
        `on_hand_grams` is less than the line's `line_bean_grams`, the rejection is
        `ERR_INSUFFICIENT_BEANS`."

        Design: Difficulty/cross_entity_state_dependency/fulfill_blocked_by_no_active_bean_lot
        """
        order = self._order_no_active_lot(api, manager_headers)
        resp = api.fulfill_order(order["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_BEAN_LOT_UNAVAILABLE.value)

    def test_fulfillment_stays_placed_without_active_lot(self, api, manager_headers):
        """PRD 3.6: "Fulfillment is performed by a `Barista` or `Manager` and drives
        `fulfillment_status` `PLACED -> FULFILLED`."
        PRD 3.6: "if no such active lot exists the rejection is
        `ERR_BEAN_LOT_UNAVAILABLE`"

        Design: Difficulty/cross_entity_state_dependency/fulfill_blocked_by_no_active_bean_lot
        """
        order = self._order_no_active_lot(api, manager_headers)
        api.fulfill_order(order["id"], manager_headers)
        fetched = validate_success(api.get_order(order["id"], manager_headers))
        assert fetched["fulfillment_status"] == "PLACED", f"got {fetched['fulfillment_status']}"


# --------------------------------------------------------------------------
# Existence / structural / fiscal validations
# --------------------------------------------------------------------------
def test_menu_item_not_found(api, manager_headers):
    """PRD 2.7: "The first reference that does not resolve causes the request to be
    rejected with `ERR_NOT_FOUND` before any later reference or business rule is
    evaluated."

    Design: Corner/entities/menu_item_not_found_returns_404
    """
    resp = api.get_menu_item(NON_EXISTENT_UUID, manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_empty_order_rejected(api, manager_headers):
    """PRD 3.5: "An order must have at least one line, or it is rejected with
    `ERR_EMPTY_ORDER`; each line's `quantity` must be a positive integer, or the
    order is rejected with `ERR_INVALID_QUANTITY`."

    Design: Corner/entities/order_empty_lines_returns_empty_order
    """
    resp = api.create_order({"lines": []}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


def test_duplicate_member_email_rejected(api, manager_headers):
    """PRD 3.4: "The `email` must be unique across members; a duplicate is rejected
    with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/validations/duplicate_member_email_rejected
    """
    th.new_member(api, headers=manager_headers, email="dup@example.com", full_name="One")
    resp = api.create_member({"email": "dup@example.com", "full_name": "Two"}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_insufficient_points_redemption_rejected(api, manager_headers):
    """PRD 3.5: "The `points_redeemed` value must be zero or a positive integer; a
    negative value is rejected with `ERR_INVALID_REDEMPTION`, and a value exceeding
    the member's `points_balance` is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/insufficient_points_redemption_rejected
    """
    member = th.new_member(api, headers=manager_headers, email="poor@example.com", full_name="Poor")
    th.set_member_points(api, member["id"], lifetime_delta=0, balance_delta=5, headers=manager_headers)
    item = th.new_menu_item(api, name="Batch", category="BEVERAGE", base_price_cents=400,
                            required_equipment_type="BATCH_BREW", size="MEDIUM",
                            origin_required=False, headers=manager_headers)
    resp = api.create_order(
        {"member_id": member["id"],
         "lines": [{"menu_item_id": item["id"], "quantity": 1, "modifier_ids": []}],
         "points_redeemed": 50}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


def test_log_waste_exceeding_on_hand_rejected(api, manager_headers):
    """PRD 3.1: "The `grams` value must be a positive integer that does not exceed
    the lot's current `on_hand_grams`; otherwise the request is rejected with
    `ERR_INVALID_WASTE`."

    Design: Corner/validations/log_waste_exceeds_on_hand_rejected
    """
    lot = th.new_bean_lot(api, origin="ETHIOPIA", roast_level="MEDIUM", received_grams=10,
                          par_grams=0, price_per_gram_cents=5, headers=manager_headers)
    resp = api.log_waste(lot["id"], {"grams": 50, "reason": "SPILL"}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_WASTE.value)


def test_orders_list_pagination_envelope(api, manager_headers):
    """PRD 2.3: "Each list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/orders_list_pagination_envelope
    """
    member = th.new_member(api, headers=manager_headers, email="list@example.com", full_name="List")
    item = th.new_menu_item(api, name="Batch", category="BEVERAGE", base_price_cents=400,
                            required_equipment_type="BATCH_BREW", size="MEDIUM",
                            origin_required=False, headers=manager_headers)
    th.new_order(api, headers=manager_headers, member_id=member["id"],
                 lines=[{"menu_item_id": item["id"], "quantity": 1, "modifier_ids": []}])
    th.new_order(api, headers=manager_headers, member_id=member["id"],
                 lines=[{"menu_item_id": item["id"], "quantity": 2, "modifier_ids": []}])
    resp = api.list_orders(manager_headers, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert len(data) == 2, f"got {len(data)}"


def test_cancel_subscription_twice_rejected(api, manager_headers):
    """PRD 3.8: "A `Customer` or `Manager` may cancel an `ACTIVE` subscription,
    transitioning it `ACTIVE -> CANCELLED`."
    PRD 2.8: "State — the target resource is in a state that permits the requested
    transition (this includes a member being `ACTIVE` for order placement, and the
    OCC parent-state check), else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_subscription_twice_invalid_state
    """
    member = th.new_member(api, headers=manager_headers, email="subcancel@example.com",
                           full_name="Sub")
    sub = th.create_subscription(api, member["id"], member["version"], headers=manager_headers,
                                 bean_origin="ETHIOPIA", frequency="MONTHLY", bags_per_cycle=2,
                                 next_ship_at="2026-04-01T00:00:00Z")
    validate_success(api.cancel_subscription(sub["id"], manager_headers))
    resp = api.cancel_subscription(sub["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# RBAC and ownership
# --------------------------------------------------------------------------
def test_customer_cannot_create_menu_item(api, manager_headers):
    """PRD 2.1: "When a request carries valid headers but the role is not permitted
    to perform the requested operation, the response is `ERR_UNAUTHORIZED`."

    Design: Corner/RBAC/customer_cannot_create_menu_item
    """
    member = th.new_member(api, headers=manager_headers, email="cust@example.com", full_name="Cust")
    cust = th.make_customer_headers(member["id"])
    resp = api.create_menu_item(
        {"name": "Hack", "category": "BEVERAGE", "base_price_cents": 100,
         "required_equipment_type": "NONE"}, cust)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_fulfill_order(api, manager_headers):
    """PRD 2.1: "When a request carries valid headers but the role is not permitted
    to perform the requested operation, the response is `ERR_UNAUTHORIZED`."
    PRD 3.6: "Fulfillment is performed by a `Barista` or `Manager` and drives
    `fulfillment_status` `PLACED -> FULFILLED`."

    Design: Corner/RBAC/customer_cannot_fulfill_order
    """
    member = th.new_member(api, headers=manager_headers, email="c2@example.com", full_name="C2")
    cust = th.make_customer_headers(member["id"])
    item = th.new_menu_item(api, name="Batch", category="BEVERAGE", base_price_cents=400,
                            required_equipment_type="BATCH_BREW", size="MEDIUM",
                            origin_required=False, headers=manager_headers)
    order = th.new_order(api, headers=cust, member_id=member["id"],
                         lines=[{"menu_item_id": item["id"], "quantity": 1, "modifier_ids": []}])
    resp = api.fulfill_order(order["id"], cust)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_pay_other_members_order(api, manager_headers):
    """PRD 2.1: "A Customer may only act on resources whose `member_id` is their
    own; when a Customer targets an order, subscription, or catering event
    belonging to another member, the request is rejected with `ERR_NOT_OWNER`."

    Design: Corner/RBAC/customer_cannot_pay_other_members_order
    """
    member_a = th.new_member(api, headers=manager_headers, email="a2@example.com", full_name="A2")
    member_b = th.new_member(api, headers=manager_headers, email="b2@example.com", full_name="B2")
    item = th.new_menu_item(api, name="Batch", category="BEVERAGE", base_price_cents=400,
                            required_equipment_type="BATCH_BREW", size="MEDIUM",
                            origin_required=False, headers=manager_headers)
    cust_a = th.make_customer_headers(member_a["id"])
    order = th.new_order(api, headers=cust_a, member_id=member_a["id"],
                         lines=[{"menu_item_id": item["id"], "quantity": 1, "modifier_ids": []}])
    cust_b = th.make_customer_headers(member_b["id"])
    resp = api.pay_order(order["id"], cust_b)
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)
