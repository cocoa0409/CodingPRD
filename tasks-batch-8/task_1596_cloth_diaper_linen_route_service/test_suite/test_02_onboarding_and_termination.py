"""Onboarding chain (PRD 3.2): initial states, creation guards, kit sizing, and
the termination gates."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_kit,
    assert_subscription,
    create_customer,
    create_plan,
    create_subscription,
    create_subscription_payload,
    create_zone,
    find_kit,
    fund_pool,
    set_clock,
    setup_active_subscription,
    settle_kit,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN


class TestInitialStates:
    def test_subscription_initial_states_after_create(self, api):
        """PRD 3.2: "The new subscription's `service_status` is `PENDING_START`, its
        `billing_status` is `CURRENT`, and its `missed_stop_count` is zero."

        Design: Corner/state_machines/subscription_initial_states_after_create
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])

        subscription = validate_success(
            _client.create_subscription(
                create_subscription_payload(customer["id"], plan["id"], zone["id"]),
                ADMIN,
            ),
            201,
        )
        assert_subscription(subscription)
        assert subscription["service_status"] == "PENDING_START"
        assert subscription["billing_status"] == "CURRENT"
        assert subscription["missed_stop_count"] == 0


class TestCreationGuards:
    def test_duplicate_active_subscription_rejected(self, api):
        """PRD 3.2: "the customer must not already hold another subscription whose
        `service_status` is `PENDING_START`, `ACTIVE`, `PAUSED`, or `SUSPENDED`
        (`ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`)"

        Design: Corner/validations/duplicate_active_subscription_rejected
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])
        create_subscription(customer, plan, zone)  # PENDING_START

        response = _client.create_subscription(
            create_subscription_payload(customer["id"], plan["id"], zone["id"]), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_SUBSCRIPTION.value)

    def test_subscription_into_inactive_zone_rejected(self, api):
        """PRD 3.2: "the zone must be serviceable — `active` on the zone must be true
        and the subscription's `service_zone_id` must equal the customer's home zone
        (`ERR_ZONE_NOT_SERVICEABLE`)"

        Design: Corner/validations/subscription_into_inactive_zone_rejected
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone(zone_code="Z-DEAD", active=False)
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])

        response = _client.create_subscription(
            create_subscription_payload(customer["id"], plan["id"], zone["id"]), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_ZONE_NOT_SERVICEABLE.value)

    def test_subscription_with_bad_plan_reference_returns_404(self, api):
        """PRD 2.10: "Reference existence — every foreign-key identifier supplied in
        the body exists (`customer_id`, `subscription_plan_id`, `service_zone_id`,
        `subscription_id`, `route_id`, `wash_formula_id`, `inventory_pool_id`,
        `route_stop_id`, `makeup_route_id`, `soiled_intake_ids`), else
        `ERR_REFERENCE_NOT_FOUND` (404)."

        Design: Corner/validations/subscription_with_bad_plan_reference_returns_404
        """
        set_clock()
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])

        response = _client.create_subscription(
            create_subscription_payload(customer["id"], NON_EXISTENT_UUID, zone["id"]),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_subscription_create_without_pool_returns_shortfall(self, api):
        """PRD 3.2: "and the size pool must have enough available units to reserve
        the starter kit (`ERR_INVENTORY_SHORTFALL`)."

        Design: Corner/validations/subscription_create_without_pool_returns_shortfall
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        customer = create_customer(zone["id"])  # no inventory pools exist at all

        response = _client.create_subscription(
            create_subscription_payload(customer["id"], plan["id"], zone["id"]), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVENTORY_SHORTFALL.value)


class TestKitSizing:
    def test_kit_item_count_reserve_rounding(self, api):
        """PRD 3.1: "A plan with a quota of 80 items and the default 10 percent
        reserve therefore kits 88 items; a quota of 60 at the same reserve kits 66."

        Design: Corner/calculations/kit_item_count_reserve_rounding
        """
        set_clock()
        plan = create_plan(tier_code="ESSENTIAL", weekly_quota=60, weekly_fee_cents=3200)
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])
        subscription = create_subscription(customer, plan, zone)

        kit = find_kit(subscription["id"])
        assert_kit(kit)
        assert kit["item_count"] == 66, (
            f"quota 60 with the default 10 percent reserve kits 66, got "
            f"{kit['item_count']}"
        )
        assert kit["status"] == "RESERVED", "the kit is created with the subscription"


class TestTerminationGates:
    def test_terminate_with_kit_issued_returns_kit_not_returned(self, api):
        """PRD 3.2: "From `ACTIVE` or `PAUSED`, termination requires three
        preconditions, checked in order: the starter kit must be `SETTLED`
        (`ERR_KIT_NOT_RETURNED` first), no invoice of the subscription may be `ISSUED`
        or `PAST_DUE` (`ERR_INVOICE_UNPAID` second), and no stop of the subscription
        may still be `PLANNED` (`ERR_INVALID_STATE`)"

        Design: Corner/validations/terminate_with_kit_issued_returns_kit_not_returned
        """
        ctx = setup_active_subscription()  # kit ISSUED, no invoices
        sub_id = ctx["subscription"]["id"]

        response = _client.subscription_event(sub_id, {"event_type": "TERMINATE"}, ADMIN)
        validate_error(response, ApiErrorId.ERR_KIT_NOT_RETURNED.value)

        after = validate_success(_client.get_subscription(sub_id, ADMIN))
        assert after["service_status"] == "ACTIVE", "a rejected TERMINATE leaves the subscription ACTIVE"

    def test_terminated_subscription_event_returns_already_terminal(self, api):
        """PRD 2.10: "Terminal-state guard — an event or action attempted on a
        resource already in a terminal state is `ERR_ALREADY_TERMINAL` (409)."
        PRD 3.2: "In every case the deposit settlement runs: the refund equals
        whatever is in `deposit_held_cents`, the held balance is zeroed, and the
        refund is added to `deposit_refunded_cents` — preserving the ledger invariant
        of §2.8."

        Design: Corner/state_machines/terminated_subscription_event_returns_already_terminal
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscription"]["id"]
        kit_id = ctx["kit"]["id"]
        settle_kit(kit_id, 88)  # full return -> RETURNED -> SETTLED
        terminated = validate_success(
            _client.subscription_event(sub_id, {"event_type": "TERMINATE"}, ADMIN)
        )
        assert terminated["service_status"] == "TERMINATED"

        response = _client.subscription_event(sub_id, {"event_type": "ACTIVATE"}, ADMIN)
        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)
