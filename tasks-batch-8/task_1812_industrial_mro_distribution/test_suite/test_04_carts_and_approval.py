"""Punch-out requisition carts: approval threshold fork, revision cycle, conversion."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_cart,
    create_branch,
    create_cart,
    create_customer,
    create_item,
    get_success_data,
    make_approver_headers,
    make_buyer_headers,
    place_order,
    reject_cart,
    restock,
    revise_cart,
    submit_cart,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _cart_cycle_setup(api, admin_headers):
    """Customer with approval_threshold_cents 5,000; item A list 10,000; item B
    list 3,000; cart with one line of item A."""
    customer = create_customer(
        account_number="PO-1", credit_limit_cents=1000000,
        approval_threshold_cents=5000, primary_ship_to_state="OH",
    )
    item_a = create_item(sku="CT-10K", list_price_cents=10000)
    item_b = create_item(sku="CT-3K", list_price_cents=3000)
    cart = create_cart(customer["id"], [{"item_id": item_a["id"], "qty": 1}])
    return customer, item_a, item_b, cart


class TestCartRejectionRevisionCycle:
    def test_submit_over_threshold_pends_then_reject_stores_reason(
        self, api, admin_headers
    ):
        """PRD §3.4: "An estimate strictly greater than the threshold routes the
        cart to `PENDING_APPROVAL`; an estimate less than or equal to the threshold
        — exact equality included — auto-approves, landing the cart directly in
        `APPROVED`."
        PRD §3.4: "rejection moves it to `REJECTED` and stores the supplied
        `reason` on the cart's `rejection_reason`."

        Design: Difficulty/non_linear_state_machine/cart_rejection_revision_cycle
        """
        customer, _item_a, _item_b, cart = _cart_cycle_setup(api, admin_headers)

        submitted = submit_cart(cart["id"], customer["id"])
        assert submitted["status"] == "PENDING_APPROVAL"
        assert submitted["estimated_total_cents"] == 10000

        rejected = reject_cart(cart["id"], customer["id"], reason="over budget")
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "over budget"

    def test_revision_reopens_rejected_cart_and_auto_approves_under_threshold(
        self, api, admin_headers
    ):
        """PRD §3.4: "when the buyer revises a rejected cart's lines, the cart
        reopens to `OPEN` and its `rejection_reason` clears, and the cycle of
        submit, decide, and revise may repeat without bound."
        PRD §3.4: "an estimate less than or equal to the threshold — exact equality
        included — auto-approves, landing the cart directly in `APPROVED`."

        Design: Difficulty/non_linear_state_machine/cart_rejection_revision_cycle
        """
        customer, _item_a, item_b, cart = _cart_cycle_setup(api, admin_headers)
        submit_cart(cart["id"], customer["id"])
        reject_cart(cart["id"], customer["id"], reason="over budget")

        reopened = revise_cart(
            cart["id"], customer["id"], [{"item_id": item_b["id"], "qty": 1}]
        )
        assert reopened["status"] == "OPEN"
        assert reopened.get("rejection_reason") is None

        resubmitted = submit_cart(cart["id"], customer["id"])
        assert resubmitted["status"] == "APPROVED"
        assert resubmitted["estimated_total_cents"] == 3000


class TestCartStateGates:
    def test_cart_submit_twice_returns_invalid_state(self, api, admin_headers):
        """PRD §3.4: "Carts are born `OPEN`."
        PRD §2.10: "Sixth, the state preconditions of the targeted transition are
        enforced, which is where stale-version rejections (`ERR_STALE_VERSION`) and
        invalid-transition rejections (`ERR_INVALID_STATE_TRANSITION`) surface
        alongside the state gates named in §3."

        Design: Corner/state_machines/cart_submit_twice_returns_invalid_state
        """
        customer = create_customer(
            account_number="IDM-1", credit_limit_cents=100000,
            approval_threshold_cents=0, primary_ship_to_state="OH",
        )
        item = create_item(sku="IDM-1", list_price_cents=500)
        cart = create_cart(customer["id"], [{"item_id": item["id"], "qty": 1}])
        submitted = submit_cart(cart["id"], customer["id"])
        assert submitted["status"] == "PENDING_APPROVAL"  # 500 > 0 threshold

        res = api.submit_cart(cart["id"], make_buyer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_cart_approve_from_open_returns_invalid_state(self, api, admin_headers):
        """PRD §3.4: "Either decision attempted on a cart that is not pending is
        rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/cart_approve_from_open_returns_invalid_state
        """
        customer = create_customer(
            account_number="IV-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="IV-1", list_price_cents=100)
        cart = create_cart(customer["id"], [{"item_id": item["id"], "qty": 1}])
        res = api.approve_cart(cart["id"], make_approver_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestCartConversion:
    def _approved_cart_scenario(self, api, admin_headers):
        customer = create_customer(
            account_number="CV-1", credit_limit_cents=100000,
            approval_threshold_cents=1000000, primary_ship_to_state="OH",
        )
        item = create_item(sku="CV-1", list_price_cents=700)
        branch = create_branch(location_code="BR-CV")
        restock(branch["id"], item["id"], 5)
        cart = create_approved_cart(
            customer["id"], [{"item_id": item["id"], "qty": 2}]
        )
        assert cart["status"] == "APPROVED"  # 700*2 = 1,400 <= 1,000,000
        return customer, item, branch, cart

    def test_cart_convert_creates_order_and_closes_cart(self, api, admin_headers):
        """PRD §3.4: "A successful conversion copies the cart's lines onto the new
        order, stamps the order's `source_cart_id`, and moves the cart to
        `CONVERTED`, its terminal state."
        PRD §3.5: "New orders start with `status` `SUBMITTED` and
        `fulfillment_status` `UNALLOCATED`"

        Design: Corner/state_machines/cart_convert_creates_order_and_closes_cart
        """
        customer, _item, branch, cart = self._approved_cart_scenario(
            api, admin_headers
        )
        buyer = make_buyer_headers(customer["id"])
        order = validate_success(
            api.create_order(
                {
                    "customer_id": customer["id"],
                    "fulfillment_branch_id": branch["id"],
                    "fulfillment_method": "WILL_CALL",
                    "source_cart_id": cart["id"],
                },
                buyer,
            ),
            201,
        )
        assert order["status"] == "SUBMITTED"
        assert order["total_cents"] == 1400
        assert order["source_cart_id"] == cart["id"]

        cart_after = validate_success(api.get_cart(cart["id"], admin_headers), 200)
        assert cart_after["status"] == "CONVERTED"

        res = api.create_order(
            {
                "customer_id": customer["id"],
                "fulfillment_branch_id": branch["id"],
                "fulfillment_method": "WILL_CALL",
                "source_cart_id": cart["id"],
            },
            buyer,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_cart_customer_mismatch_on_convert(self, api, admin_headers):
        """PRD §3.4: "the request's `customer_id` must equal the cart's owning
        `customer_id`, or the create is rejected with
        `ERR_CART_CUSTOMER_MISMATCH`."

        Design: Corner/errors/cart_customer_mismatch_on_convert
        """
        customer_a = create_customer(
            account_number="CM-A", credit_limit_cents=100000,
            approval_threshold_cents=1000000, primary_ship_to_state="OH",
        )
        customer_b = create_customer(
            account_number="CM-B", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="CM-1", list_price_cents=100)
        branch = create_branch(location_code="BR-CM")
        cart = create_approved_cart(
            customer_a["id"], [{"item_id": item["id"], "qty": 1}]
        )

        res = api.create_order(
            {
                "customer_id": customer_b["id"],
                "fulfillment_branch_id": branch["id"],
                "fulfillment_method": "WILL_CALL",
                "source_cart_id": cart["id"],
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_CART_CUSTOMER_MISMATCH)


class TestCartRbacAndOwnership:
    def test_approver_cannot_create_cart_returns_forbidden(self, api, admin_headers):
        """PRD §2.1: "Each endpoint admits a specific set of roles (§4); a caller
        whose role is not permitted on the targeted endpoint is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST `/mro/carts` | Create a requisition cart (punch-out return);
        buyer must belong to the customer | CustomerBuyer"

        Design: Corner/roles/approver_cannot_create_cart_returns_forbidden
        """
        customer = create_customer(account_number="RB-2", credit_limit_cents=100000)
        item = create_item(sku="RB-2", list_price_cents=100)
        res = api.create_cart(
            {"customer_id": customer["id"], "lines": [{"item_id": item["id"], "qty": 1}]},
            make_approver_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_buyer_manages_own_cart_positive(self, api, admin_headers):
        """PRD §3.4: "A `CustomerBuyer` assembles a `RequisitionCart` for their own
        account, naming the owning account via `customer_id`"
        PRD §3.4: "A buyer may revise an open cart's lines at any time; revision
        replaces the `lines` wholesale and leaves the cart `OPEN`."

        Design: Corner/roles/buyer_manages_own_cart_positive
        """
        customer = create_customer(
            account_number="POS-1", credit_limit_cents=100000,
            approval_threshold_cents=1000000, primary_ship_to_state="OH",
        )
        item = create_item(sku="POS-1", list_price_cents=100)
        buyer = make_buyer_headers(customer["id"])

        cart = validate_success(
            api.create_cart(
                {"customer_id": customer["id"],
                 "lines": [{"item_id": item["id"], "qty": 1}]},
                buyer,
            ),
            201,
        )
        assert cart["status"] == "OPEN"

        revised = validate_success(
            api.update_cart(
                cart["id"], {"lines": [{"item_id": item["id"], "qty": 2}]}, buyer
            ),
            200,
        )
        assert revised["status"] == "OPEN"

        submitted = validate_success(api.submit_cart(cart["id"], buyer), 200)
        assert submitted["status"] == "APPROVED"
        assert submitted["estimated_total_cents"] == 200
