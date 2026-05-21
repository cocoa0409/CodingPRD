"""Restaurant lifecycle: approve / suspend / reinstate / settle (PRD §3.1, §3.8).

Covers:
- PENDING_APPROVAL → ACTIVE via /approve
- ACTIVE → SUSPENDED via /suspend; fans out cancellation to PLACED orders
- SUSPENDED → ACTIVE via /reinstate
- /settle zeroes pending_settlement_cents
- Invalid-state transitions → ERR_INVALID_STATE
"""

import pytest

from test_helpers import (
    api_client,
    create_active_restaurant,
    create_customer,
    create_restaurant_payload,
    get_success_data,
    make_customer_headers,
    make_restaurant_headers,
    place_order,
    setup_customer_restaurant_menu,
    validate_error,
    validate_success,
)


class TestRestaurantApproval:
    def test_approve_pending_goes_active(self, api, admin_headers):
        """PRD §3.1: "A separate approval step transitions the restaurant from
        PENDING_APPROVAL to ACTIVE."

        Claim: POST /approve on PENDING_APPROVAL → status ACTIVE.
        """
        created = get_success_data(
            api.create_restaurant(create_restaurant_payload(), admin_headers)
        )
        assert created["status"] == "PENDING_APPROVAL"
        res = api.approve_restaurant(created["id"], admin_headers)
        data = validate_success(res, 200)
        assert data["status"] == "ACTIVE"

    def test_approve_on_active_rejected(self, api, admin_headers):
        """PRD §2.6 priority 6: "Target resource is in a state from which the requested
        transition is allowed (ERR_INVALID_STATE)."

        Claim: /approve on an ACTIVE restaurant → ERR_INVALID_STATE.
        """
        r = create_active_restaurant()
        res = api.approve_restaurant(r["id"], admin_headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestRestaurantSuspendReinstate:
    def test_suspend_active_goes_suspended(self, api, admin_headers):
        """PRD §3.1: "A PlatformAdmin can later suspend an ACTIVE restaurant — moving it
        to SUSPENDED — or reinstate a SUSPENDED restaurant back to ACTIVE."

        Claim: /suspend on ACTIVE → status SUSPENDED.
        """
        r = create_active_restaurant()
        res = api.suspend_restaurant(r["id"], admin_headers)
        data = validate_success(res, 200)
        assert data["status"] == "SUSPENDED"

    def test_reinstate_suspended_goes_active(self, api, admin_headers):
        """PRD §3.1: "reinstate a SUSPENDED restaurant back to ACTIVE."

        Claim: /reinstate on SUSPENDED → status ACTIVE.
        """
        r = create_active_restaurant()
        api.suspend_restaurant(r["id"], admin_headers)
        res = api.reinstate_restaurant(r["id"], admin_headers)
        data = validate_success(res, 200)
        assert data["status"] == "ACTIVE"

    def test_suspend_fans_out_to_placed_orders(self, api, admin_headers):
        """PRD §3.1: "Suspending an active restaurant additionally fans out a cancellation
        to every one of its orders that is currently in PLACED, transitioning each such
        order to CANCELLED."

        Claim: PLACED order becomes CANCELLED when its restaurant is suspended.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        assert order["status"] == "PLACED"

        api.suspend_restaurant(restaurant["id"], admin_headers)
        updated = get_success_data(api.get_order(order["id"], admin_headers))
        assert updated["status"] == "CANCELLED"


class TestRestaurantSettle:
    def test_settle_zeroes_pending_settlement(self, api, admin_headers):
        """PRD §3.8: "A PlatformAdmin invokes the restaurant's settle capability; the
        restaurant's pending_settlement_cents is reset to 0."

        Claim: /settle zeroes pending_settlement_cents.
        """
        # Drive a full delivery to accumulate a non-zero pending balance,
        # then settle.
        from test_helpers import run_order_to_delivered
        ctx = run_order_to_delivered(distance_km=2.0, menu_price_cents=5000)
        restaurant = ctx["restaurant"]
        assert restaurant["pending_settlement_cents"] > 0

        res = api.settle_restaurant(restaurant["id"], admin_headers)
        data = validate_success(res, 200)
        assert data["pending_settlement_cents"] == 0


class TestRestaurantPatch:
    def test_patch_address(self, api, admin_headers):
        """PRD §3.1: "Mutable restaurant fields — address, lat, lng, and
        commission_rate_override — can be edited by the owning Restaurant or by a
        PlatformAdmin."

        Claim: PATCH updates address and increments version.
        """
        r = create_active_restaurant()
        old_version = r["version"]
        res = api.patch_restaurant(r["id"], {"address": "99 New Street"}, admin_headers)
        data = validate_success(res, 200)
        assert data["address"] == "99 New Street"
        assert data["version"] > old_version

    def test_patch_with_stale_version_rejected(self, api, admin_headers):
        """PRD §2.5: "When the client supplies version, the server compares it to the
        resource's current version; a mismatch aborts the operation with
        ERR_VERSION_CONFLICT."

        Claim: stale version on PATCH → ERR_VERSION_CONFLICT.
        """
        r = create_active_restaurant()
        stale = r["version"]
        # First PATCH bumps version from stale to stale+1.
        api.patch_restaurant(r["id"], {"address": "step-1"}, admin_headers)
        # Second PATCH with stale version should conflict.
        res = api.patch_restaurant(
            r["id"], {"address": "step-2", "version": stale}, admin_headers
        )
        validate_error(res, "ERR_VERSION_CONFLICT")
