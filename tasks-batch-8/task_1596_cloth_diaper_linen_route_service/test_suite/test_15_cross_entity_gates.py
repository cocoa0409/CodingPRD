"""Cross-entity state gates: an action on one entity is gated on another
entity's live state (route for stops, kit for activation, pool for approvals,
invoices for termination)."""
from test_helpers import (
    ApiErrorId,
    adjust_pool,
    complete_stop,
    create_route,
    create_swap,
    customer_event,
    find_stop,
    generate_invoice,
    invoice_event,
    read_customer,
    read_pool_version,
    sequence_route,
    set_clock,
    setup_active_subscription,
    setup_route_in_progress,
    settle_kit,
    subscription_event,
    validate_error,
    validate_success,
    create_customer,
    create_plan,
    create_subscription,
    create_zone,
    fund_pool,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, DRIVER, create_pool


class TestStopCompleteRequiresRouteInProgress:
    def test_complete_on_locked_route_rejected(self, api):
        """PRD 3.3: "Four guards apply: the route must be `IN_PROGRESS`
        (`ERR_INVALID_STATE`); the subscription must be `ACTIVE`
        (`ERR_SUBSCRIPTION_NOT_ACTIVE`); the request's `expected_route_version` must
        match the route's current `version` per §2.9 (`ERR_STALE_VERSION`); and the
        completion must not push the route past its capacity"

        Design: Difficulty/cross_entity_state_dependency/stop_complete_requires_route_in_progress
        """
        ctx = setup_active_subscription()
        route = create_route(ctx["zone"], "2026-08-03")
        stop = find_stop(route["id"], ctx["subscription"]["id"])
        sequence_route(route["id"])
        locked = validate_success(
            _client.route_event(route["id"], {"event_type": "LOCK"}, ADMIN)
        )
        assert locked["status"] == "LOCKED"

        response = _client.complete_stop(
            stop["id"],
            {
                "soiled_bags_collected": 1,
                "clean_items_delivered": 80,
                "expected_route_version": locked["version"],
            },
            DRIVER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    def test_complete_after_route_start_succeeds(self, api):
        """PRD 3.3: "A successful completion moves the stop `PLANNED` → `COMPLETED`,
        adds its figures into the route's totals, moves one count from
        `planned_stop_count` to `completed_stop_count`, and increments the route's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/stop_complete_requires_route_in_progress
        """
        ctx = setup_active_subscription()
        setup_route_in_progress(ctx)
        completed = complete_stop(ctx["stop"]["id"], ctx["route_version"], clean_items=80)
        assert completed["status"] == "COMPLETED", (
            "the identical request succeeds once the route is IN_PROGRESS"
        )


class TestSubscriptionActivateRequiresKitIssued:
    def test_activate_with_reserved_kit_rejected(self, api):
        """PRD 3.2: "Only then can the subscription itself be activated — a
        `PlatformAdmin` fires the subscription event `ACTIVATE`, which requires the
        customer to be `ACTIVE` and the kit to be `ISSUED` (both `ERR_INVALID_STATE`
        otherwise), and requires `start_date` to be on or before the current logical
        date (otherwise `ERR_CUTOFF_PASSED`)."

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_requires_kit_issued
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])
        subscription = create_subscription(customer, plan, zone)
        customer_event(customer["id"], "ACTIVATE")  # owns a PENDING_START subscription

        response = _client.subscription_event(
            subscription["id"], {"event_type": "ACTIVATE"}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

        after = validate_success(_client.get_subscription(subscription["id"], ADMIN))
        assert after["service_status"] == "PENDING_START", (
            "the kit is still RESERVED, so the gate holds"
        )

    def test_activate_after_kit_issue_succeeds(self, api):
        """PRD 3.2: "The kit then ships: a `PlatformAdmin` or `PlantOperator` issues
        it, moving the kit `RESERVED` → `ISSUED` and shifting `item_count` units in
        the size pool from `reserved_units` to `checked_out_units`. Only then can the
        subscription itself be activated"

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_requires_kit_issued
        """
        ctx = setup_active_subscription()  # full chain, kit ISSUEd before ACTIVATE
        assert ctx["subscription"]["service_status"] == "ACTIVE", (
            "with the kit issued, ACTIVATE moves PENDING_START -> ACTIVE"
        )


class TestSwapApproveRequiresPoolAvailability:
    def _setup_swap_into_empty_pool(self):
        ctx = setup_active_subscription()
        pool_l = create_pool("LARGE")  # zero stock
        swap = create_swap(ctx["subscription"]["id"], "LARGE", ctx["customer_headers"])
        ctx.update({"pool_l": pool_l, "swap": swap})
        return ctx

    def test_approve_with_zero_available_returns_shortfall(self, api):
        """PRD 3.6: "Beyond the state and subscription checks, approval requires the
        target pool's `available_units` to be at least `quantity`
        (`ERR_INVENTORY_SHORTFALL`)."

        Design: Difficulty/cross_entity_state_dependency/swap_approve_requires_pool_availability
        """
        ctx = self._setup_swap_into_empty_pool()
        assert ctx["swap"]["quantity"] == 88, (
            f"quantity is the kit size for LARGE: 80 + ceil(80 x 10 / 100) = 88, "
            f"got {ctx['swap']['quantity']}"
        )
        response = _client.approve_swap(
            ctx["swap"]["id"],
            {"expected_inventory_pool_version": ctx["pool_l"]["version"]},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVENTORY_SHORTFALL.value)

    def test_approve_after_acquire_reserves_quantity(self, api):
        """PRD 3.6: "Approval moves `quantity` units in the target pool from
        `on_hand_units` into `reserved_units`, increments the pool's `version`, and
        moves the swap `REQUESTED` → `APPROVED`."
        PRD 2.7: "The derived `available_units` is what remains for new commitments:
        on-hand minus reserved."

        Design: Difficulty/cross_entity_state_dependency/swap_approve_requires_pool_availability
        """
        ctx = self._setup_swap_into_empty_pool()
        adjust_pool(ctx["pool_l"]["id"], "ACQUIRE", 200)
        fresh_v = read_pool_version(ctx["pool_l"]["id"])

        approved = validate_success(
            _client.approve_swap(
                ctx["swap"]["id"], {"expected_inventory_pool_version": fresh_v}, ADMIN
            )
        )
        assert approved["status"] == "APPROVED"

        pool = validate_success(_client.get_pool(ctx["pool_l"]["id"], ADMIN))
        assert pool["on_hand_units"] == 112
        assert pool["reserved_units"] == 88
        assert pool["available_units"] == 24, (
            "PRD 2.7: available_units = on_hand - reserved = 112 - 88 = 24, got "
            f"{pool['available_units']}"
        )


class TestSwapSizeStepGate:
    def test_swap_skip_size_rejected(self, api):
        """PRD 3.6: "The size ladder is `NEWBORN` < `SMALL` < `MEDIUM` < `LARGE` <
        `XL`, and the target must be exactly one step from the current size —
        skipping a rung is `ERR_SIZE_TRANSITION_INVALID`."

        Design: Corner/validations/swap_skip_size_rejected
        """
        ctx = setup_active_subscription()  # MEDIUM subscription
        response = _client.create_swap(
            {"subscription_id": ctx["subscription"]["id"], "to_size_code": "XL"},
            ctx["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SIZE_TRANSITION_INVALID.value)


class TestTerminateRequiresNoUnpaidInvoice:
    def test_terminate_with_issued_invoice_rejected(self, api):
        """PRD 3.2: "From `ACTIVE` or `PAUSED`, termination requires three
        preconditions, checked in order: the starter kit must be `SETTLED`
        (`ERR_KIT_NOT_RETURNED` first), no invoice of the subscription may be `ISSUED`
        or `PAST_DUE` (`ERR_INVOICE_UNPAID` second), and no stop of the subscription
        may still be `PLANNED` (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/terminate_requires_no_unpaid_invoice
        """
        ctx = setup_active_subscription()
        settle_kit(ctx["kit"]["id"], 88)  # kit SETTLED, so the invoice check is reached
        invoice = generate_invoice(ctx["subscription"]["id"])
        invoice_event(invoice["id"], "ISSUE")

        response = _client.subscription_event(
            ctx["subscription"]["id"], {"event_type": "TERMINATE"}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVOICE_UNPAID.value)

        after = read_customer(ctx["customer"]["id"])
        assert after["deposit_held_cents"] == 18000, (
            "a rejected TERMINATE runs no deposit settlement"
        )

    def test_terminate_after_pay_settles_deposit(self, api):
        """PRD 3.2: "In every case the deposit settlement runs: the refund equals
        whatever is in `deposit_held_cents`, the held balance is zeroed, and the
        refund is added to `deposit_refunded_cents` — preserving the ledger invariant
        of §2.8."

        Design: Difficulty/cross_entity_state_dependency/terminate_requires_no_unpaid_invoice
        """
        ctx = setup_active_subscription()
        settle_kit(ctx["kit"]["id"], 88)
        invoice = generate_invoice(ctx["subscription"]["id"])
        invoice_event(invoice["id"], "ISSUE")
        invoice_event(invoice["id"], "PAY")

        terminated = subscription_event(ctx["subscription"]["id"], "TERMINATE")
        assert terminated["service_status"] == "TERMINATED"

        customer = read_customer(ctx["customer"]["id"])
        assert customer["deposit_held_cents"] == 0
        assert customer["deposit_refunded_cents"] == 18000, (
            "a clean termination refunds exactly what was held"
        )
