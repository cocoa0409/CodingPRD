"""Return-order intake guards: enum shape, plan feature gates, oversize and
dimension safety, open-cycle requirement, overage hard cap, merchant gating,
and validation-order priority pairs."""
from test_helpers import (
    ApiErrorId,
    create_return_item_line,
    create_return_order_payload,
    fulfill_order_to_refund_posted,
    setup_commercial_spine,
    validate_error,
    validate_success,
)


class TestIntakeShape:

    def test_create_order_invalid_enum_method_rejected(self, api):
        """PRD §2.8: "path- and body-referenced identifiers exist, validated
        left to right, and enum fields carry a declared member, else
        `ERR_NOT_FOUND`, `ERR_ENUM_INVALID`, or `ERR_INVALID_REQUEST`."
        PRD §3.3: "choosing a fulfilment `method` of `LOCKER_QR`,
        `COUNTER_DROP`, or `HOME_PICKUP`".

        Design: Corner/validations/create_order_invalid_enum_method_rejected
        """
        from test_helpers import api_client
        spine = setup_commercial_spine(shopper_email="sen@x.com")
        payload = create_return_order_payload(
            spine["shopper"]["id"], spine["merchant"]["id"], method="PIGEON"
        )
        resp = api_client.create_return_order(payload, spine["shopper_headers"])
        validate_error(resp, ApiErrorId.ERR_ENUM_INVALID)


class TestPlanFeatureGates:

    def test_error_feature_not_included_pickup_gate(self, api):
        """PRD §3.3: "Method eligibility is plan-gated: `HOME_PICKUP` requires
        the plan's `pickup_enabled`, and boxless flows require
        `boxless_enabled`, with violations rejected as
        `ERR_FEATURE_NOT_INCLUDED`."

        Design: Corner/errors/error_feature_not_included_pickup_gate
        """
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": False}, shopper_email="sfn@x.com"
        )
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="HOME_PICKUP", boxless=True,
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FEATURE_NOT_INCLUDED)

    def test_error_oversize_not_supported_plan_gate(self, api):
        """PRD §3.3: "Regardless of method, any oversize item requires the
        plan's `oversize_enabled`, else `ERR_OVERSIZE_NOT_SUPPORTED`."
        PRD §3.1: "`oversize_enabled` permits items whose `longest_side_cm`
        exceeds 150 through non-locker methods."

        Design: Corner/errors/error_oversize_not_supported_plan_gate
        """
        spine = setup_commercial_spine(
            plan_overrides={"oversize_enabled": False}, shopper_email="son@x.com"
        )
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="COUNTER_DROP",
                items=[create_return_item_line(sku="ON", longest_side_cm=200,
                                               weight_grams=9000)],
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OVERSIZE_NOT_SUPPORTED)


class TestDimensionSafety:

    def test_locker_xl_dim_boundary_150_accepted_151_rejected(self, api):
        """PRD §3.3: "Choosing `LOCKER_QR` forces `boxless` to true and forbids
        any item whose `longest_side_cm` exceeds 150 — such an item presented
        for a locker flow is rejected with `ERR_DIM_EXCEEDS_XL`."
        PRD §3.5: "`XL` up to 150 cm".

        Design: Difficulty/boundary_precision_check/locker_xl_dim_boundary_150_accepted_151_rejected
        """
        from test_helpers import (
            create_location,
            create_slot,
            reserve_slot,
        )
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": False}, shopper_email="sx@x.com"
        )
        location = create_location(name="L-XL", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")

        # Exactly 150 cm: accepted at order creation AND fits the XL slot.
        ok_resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="LOCKER_QR",
                items=[create_return_item_line(sku="X150", longest_side_cm=150,
                                               weight_grams=5000,
                                               unit_price_cents=5000)],
            ),
            spine["shopper_headers"],
        )
        ok_order = validate_success(ok_resp, expected_status=201)
        assert ok_order["has_oversize_item"] is False
        reservation = reserve_slot(ok_order, slot, spine["shopper_headers"])
        assert reservation["status"] == "HELD"

        # 150.01 cm: rejected outright for a locker flow.
        bad_resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="LOCKER_QR",
                items=[create_return_item_line(sku="X151", longest_side_cm=150.01,
                                               weight_grams=5000,
                                               unit_price_cents=5000)],
            ),
            spine["shopper_headers"],
        )
        validate_error(bad_resp, ApiErrorId.ERR_DIM_EXCEEDS_XL)

    def test_locker_dim_rejection_also_when_plan_lacks_boxless(self, api):
        """PRD §2.8: "Because this order is fixed, an early failure always
        masks later ones". Priority 8 (dimension safety) precedes priority 9
        (feature gates), so a 200 cm item on a plan without boxless surfaces
        the dimension error.

        Design: Difficulty/priority_pair_validation_conflict/create_order_safety_beats_plan_constraint
        """
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": False, "boxless_enabled": False},
            shopper_email="sf@x.com",
        )
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="LOCKER_QR",
                items=[create_return_item_line(sku="BIG", longest_side_cm=200,
                                               weight_grams=9000,
                                               unit_price_cents=5000)],
            ),
            spine["shopper_headers"],
        )
        # P8 safety (ERR_DIM_EXCEEDS_XL) beats P9 feature gate
        # (ERR_FEATURE_NOT_INCLUDED) per the fixed order of PRD §2.8.
        validate_error(resp, ApiErrorId.ERR_DIM_EXCEEDS_XL)


class TestOpenCycleRequirement:

    def test_order_create_without_open_cycle_rejected(self, api):
        """PRD §3.3: "an `OPEN` billing cycle of the merchant must cover the
        current logical instant, else `ERR_BILLING_CYCLE_NOT_OPEN`."

        Design: Corner/state_machines/order_create_without_open_cycle_rejected
        """
        spine = setup_commercial_spine(shopper_email="snc@x.com", with_cycle=False)
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="COUNTER_DROP",
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_CYCLE_NOT_OPEN)


class TestOverageGuard:

    def test_overage_guard_projected_equals_cap_allowed(self, api):
        """PRD §3.3: "The system projects the merchant's load as the current
        `OPEN` cycle's `fulfilled_count` plus its `in_flight_count` plus one
        for the order being created. If that projection strictly exceeds twice
        the plan's `included_returns`, creation is rejected with
        `ERR_OVERAGE_LIMIT_EXCEEDED`; a projection exactly equal to twice the
        inclusion is allowed."

        Design: Corner/calculations/overage_guard_projected_equals_cap_allowed
        """
        spine = setup_commercial_spine(
            plan_overrides={"included_returns": 1, "pickup_enabled": False},
            shopper_email="sog@x.com",
        )
        first = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="COUNTER_DROP",
                items=[create_return_item_line(sku="O1")],
            ),
            spine["shopper_headers"],
        )
        validate_success(first, expected_status=201)

        # Second create: projected = 0 fulfilled + 1 in-flight + 1 = 2 == cap.
        second = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="COUNTER_DROP",
                items=[create_return_item_line(sku="O2")],
            ),
            spine["shopper_headers"],
        )
        validate_success(second, expected_status=201)

        # Third create: projected = 3 > 2 -> rejected.
        third = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="COUNTER_DROP",
                items=[create_return_item_line(sku="O3")],
            ),
            spine["shopper_headers"],
        )
        validate_error(third, ApiErrorId.ERR_OVERAGE_LIMIT_EXCEEDED)


class TestMerchantGate:

    def test_order_create_requires_merchant_active(self, api):
        """PRD §3.1: "From `ACTIVE`, a `PlatformAdmin` may suspend the account
        (`ACTIVE` → `SUSPENDED`), which immediately blocks new return order
        creation for the merchant with `ERR_MERCHANT_SUSPENDED`, and may
        reactivate it (`SUSPENDED` → `ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_merchant_active
        """
        from test_helpers import TEST_USERS, api_client
        spine = setup_commercial_spine(shopper_email="sg@x.com")
        merchant_id = spine["merchant"]["id"]

        resp_suspend = api_client.suspend_merchant(
            merchant_id, TEST_USERS["platform_admin_headers"]
        )
        validate_success(resp_suspend)

        blocked = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], merchant_id, method="HOME_PICKUP",
                boxless=True,
            ),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_MERCHANT_SUSPENDED)

        resp_reactivate = api_client.reactivate_merchant(
            merchant_id, TEST_USERS["platform_admin_headers"]
        )
        validate_success(resp_reactivate)

        ok = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], merchant_id, method="HOME_PICKUP",
                boxless=True,
            ),
            spine["shopper_headers"],
        )
        validate_success(ok, expected_status=201)

    def test_create_order_referential_beats_fiscal(self, api):
        """PRD §2.8: priority 7 (cross-entity referential integrity, surfacing
        `ERR_MERCHANT_SUSPENDED`) is evaluated before priority 12 (fiscal
        guards, surfacing `ERR_OVERAGE_LIMIT_EXCEEDED`); "an early failure
        always masks later ones".

        Design: Difficulty/priority_pair_validation_conflict/create_order_referential_beats_fiscal
        """
        from test_helpers import TEST_USERS, api_client
        spine = setup_commercial_spine(
            plan_overrides={"included_returns": 1, "pickup_enabled": True},
            shopper_email="sp@x.com", with_zone=True,
        )
        merchant_id = spine["merchant"]["id"]

        # Drive fulfilled+in_flight to the 2x cap with two fulfilled orders.
        fulfill_order_to_refund_posted(
            spine, items=[create_return_item_line(sku="P1")]
        )
        fulfill_order_to_refund_posted(
            spine, items=[create_return_item_line(sku="P2")]
        )

        api_client.suspend_merchant(merchant_id, TEST_USERS["platform_admin_headers"])

        # Both P7 (merchant suspended) and P12 (projected 3 > 2) hold; P7 wins.
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], merchant_id, method="HOME_PICKUP",
                boxless=True,
                items=[create_return_item_line(sku="P3")],
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED)


class TestMerchantLifecycleGuards:

    def test_merchant_close_with_open_cycle_rejected(self, api):
        """PRD §3.1: "Closing the account — from either `ACTIVE` or
        `SUSPENDED` into the terminal `CLOSED` — requires that no billing
        cycle of the merchant is in `OPEN` or `CLOSING` status, and is
        otherwise refused with `ERR_BILLING_CYCLE_OPEN`."

        Design: Corner/state_machines/merchant_close_with_open_cycle_rejected
        """
        from test_helpers import TEST_USERS, api_client
        spine = setup_commercial_spine(shopper_email="scl@x.com")
        resp = api_client.close_merchant(
            spine["merchant"]["id"], TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_CYCLE_OPEN)

    def test_plan_retire_in_use_rejected(self, api):
        """PRD §3.1: "Retirement is refused with `ERR_PLAN_IN_USE` while any
        merchant account in `ACTIVE` or `SUSPENDED` status still references
        the plan."

        Design: Corner/state_machines/plan_retire_in_use_rejected
        """
        from test_helpers import TEST_USERS, api_client, create_merchant, create_published_plan
        plan = create_published_plan()
        create_merchant(plan["id"], legal_name="M-PU")
        resp = api_client.retire_subscription_plan(
            plan["id"], TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_IN_USE)
