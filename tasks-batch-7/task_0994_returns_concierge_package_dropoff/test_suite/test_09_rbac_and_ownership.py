"""Role-based access control and entity-backed ownership: exclusive-operation
denials, cross-entity ownership mismatches, and shared-read positive paths."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_billing_cycle,
    create_location,
    create_order,
    create_return_item_line,
    create_shopper,
    create_slot,
    create_subscription_plan_payload,
    make_location_operator_headers,
    make_merchant_admin_headers,
    make_shopper_headers,
    reserve_slot,
    setup_commercial_spine,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


class TestRoleExclusiveDenied:

    def test_shopper_cannot_create_subscription_plan(self, api):
        """PRD §4: POST /v1/subscription-plans lists PlatformAdmin as the only
        authorized role.
        PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/roles/shopper_cannot_create_subscription_plan
        """
        resp = api.create_subscription_plan(
            create_subscription_plan_payload(),
            TEST_USERS["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestOwnership:

    def test_shopper_cannot_touch_other_shoppers_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Shopper`, `X-User-ID` is the `id`
        of the acting `Shopper`; ownership checks on any resource that
        references a `Shopper` compare the resource's `shopper_id` to
        `X-User-ID`." "An entity-backed caller acting on a resource it does
        not own is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/roles/shopper_cannot_touch_other_shoppers_order
        """
        spine = setup_commercial_spine(shopper_email="sa-own@x.com")
        shopper_b = create_shopper("sb-own@x.com", full_name="S B")
        order = create_order(spine, method="COUNTER_DROP")

        resp = api.get_return_order(
            order["id"], make_shopper_headers(shopper_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_operator_cannot_consume_at_other_location(self, api):
        """PRD §3.5: "the caller must own the slot's location, else
        `ERR_OWNERSHIP_MISMATCH`."
        PRD §2.1: "When `X-User-Role` is `LocationOperator`, `X-User-ID` is
        the `id` of the `DropoffLocation` the operator runs".

        Design: Corner/roles/operator_cannot_consume_at_other_location
        """
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": False}, shopper_email="soo@x.com"
        )
        location_a = create_location(name="L-OA", kind="LOCKER")
        slot = create_slot(location_a["id"], size_class="XL")
        location_b = create_location(name="L-OB", kind="LOCKER")

        order = create_order(spine, method="LOCKER_QR",
                             items=[create_return_item_line(sku="OO",
                                                            longest_side_cm=20)])
        reservation = reserve_slot(order, slot, spine["shopper_headers"])

        # Operator of location B attempts to consume a reservation at A.
        resp = api.consume_slot_reservation(
            reservation["id"], make_location_operator_headers(location_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_merchant_admin_cannot_dispute_other_merchants_cycle(self, api):
        """PRD §3.2: "The merchant's own `MerchantAdmin` may then dispute the
        settled charge, moving `SETTLED` → `DISPUTED`; the caller must be the
        merchant itself, so a caller whose identity differs from the cycle's
        `merchant_id` is refused with `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/roles/merchant_admin_cannot_dispute_other_merchants_cycle
        """
        from test_helpers import (
            create_merchant,
            create_published_plan,
            make_platform_admin_headers,
        )
        plan = create_published_plan()
        merchant_a = create_merchant(plan["id"], legal_name="M-DA")
        merchant_b = create_merchant(plan["id"], legal_name="M-DB")
        cycle = create_billing_cycle(merchant_a["id"])

        admin_1 = make_platform_admin_headers("admin-1")
        admin_2 = make_platform_admin_headers("admin-2")
        validate_success(api.close_billing_cycle(cycle["id"], admin_1))
        validate_success(api.settle_billing_cycle(cycle["id"], admin_2))

        # MerchantAdmin of merchant B disputes merchant A's SETTLED cycle.
        resp = api.dispute_billing_cycle(
            cycle["id"], make_merchant_admin_headers(merchant_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


class TestSharedRead:

    def test_support_agent_shared_read_allowed(self, api):
        """PRD §2.1: "When `X-User-Role` is `SupportAgent`,
        `CarrierDispatcher`, or `PlatformAdmin`, `X-User-ID` is an opaque
        operator identifier not tied to any persisted entity."
        PRD §4: GET /v1/return-orders/{id} lists SupportAgent among its
        authorized roles.

        Design: Corner/roles/support_agent_shared_read_allowed
        """
        spine = setup_commercial_spine(shopper_email="ssr@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        data = validate_success(api.get_return_order(order["id"], AGENT))
        assert data["id"] == order["id"]
