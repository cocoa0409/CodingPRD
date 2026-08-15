"""Optimistic concurrency on the three version-guarded writes (PRD 2.9), the
per-mutation version counter (PRD 2.4), and the derived availability ledger
(PRD 2.7)."""
from test_helpers import (
    ApiErrorId,
    add_active_subscription,
    complete_stop,
    create_pause,
    create_pause_payload,
    create_swap,
    drive_route_to_in_progress,
    find_kit,
    find_stop,
    kit_event,
    make_customer_headers,
    read_pool,
    read_route_version,
    read_subscription_version,
    setup_active_subscription,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, DRIVER, create_route


class TestPauseOcc:
    def test_occ_pause_create_stale_version(self, api):
        """PRD 2.9: "Creating a service pause requires
        `expected_subscription_version`, carrying the caller's last observed `version`
        of the target subscription; a mismatch with the subscription's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_pause_create_stale_version
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscription"]["id"]
        stale_v = ctx["subscription_version"]

        pause = create_pause(
            sub_id, "2026-08-05", "2026-08-10", stale_v, ctx["customer_headers"]
        )
        assert pause["status"] == "SCHEDULED"
        assert read_subscription_version(sub_id) == stale_v + 1, (
            "pause creation is a subscription mutation and advances its version"
        )

        response = _client.create_pause(
            create_pause_payload(sub_id, "2026-08-12", "2026-08-15", stale_v),
            ctx["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)


class TestSwapApproveOcc:
    def test_occ_swap_approve_stale_version(self, api):
        """PRD 2.9: "Approving an inventory swap requires
        `expected_inventory_pool_version`, carrying the caller's last observed
        `version` of the target-size inventory pool; a mismatch with that pool's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_swap_approve_stale_version
        """
        from test_helpers.fixtures import fund_pool

        ctx = setup_active_subscription()
        pool_l = fund_pool("LARGE", 200)
        pool_v = pool_l["version"]
        swap1 = create_swap(ctx["subscription"]["id"], "LARGE", ctx["customer_headers"])
        swap2 = create_swap(ctx["subscription"]["id"], "LARGE", ctx["customer_headers"])

        approved = validate_success(
            _client.approve_swap(
                swap1["id"], {"expected_inventory_pool_version": pool_v}, ADMIN
            )
        )
        assert approved["status"] == "APPROVED"

        response = _client.approve_swap(
            swap2["id"], {"expected_inventory_pool_version": pool_v}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)


class TestStopCompleteOcc:
    def test_occ_stop_complete_stale_route(self, api):
        """PRD 2.9: "Completing a route stop requires `expected_route_version`,
        carrying the caller's last observed `version` of the route; a mismatch with
        the route's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_stop_complete_stale_route
        """
        ctx = setup_active_subscription()
        member_b = add_active_subscription(ctx, customer_overrides={"full_name": "Occ B"})
        route = create_route(ctx["zone"], "2026-08-03")
        stop_a = find_stop(route["id"], ctx["subscription"]["id"])
        stop_b = find_stop(route["id"], member_b["subscription"]["id"])
        route_v = drive_route_to_in_progress(route["id"], "2026-08-03")

        complete_stop(stop_a["id"], route_v, clean_items=80)

        stale = _client.complete_stop(
            stop_b["id"],
            {
                "soiled_bags_collected": 1,
                "clean_items_delivered": 80,
                "expected_route_version": route_v,
            },
            DRIVER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        fresh_v = read_route_version(route["id"])
        retried = complete_stop(stop_b["id"], fresh_v, clean_items=80)
        assert retried["status"] == "COMPLETED", (
            "re-reading the route and retrying with the fresh version succeeds"
        )


class TestVersionCounter:
    def test_version_increments_on_each_mutation(self, api):
        """PRD 2.4: "`version` (integer): starts at its initial value on creation and
        increments by one on every mutation of the resource, including mutations
        caused by cascades originating elsewhere."
        PRD 3.7: "Pause creation is also a subscription mutation and increments the
        subscription's `version` by one."

        Design: Corner/complexity_layers/version_increments_on_each_mutation
        """
        from test_helpers.fixtures import (
            create_customer,
            create_plan,
            create_subscription,
            create_zone,
            customer_event,
            find_kit,
            fund_pool,
            kit_event,
            set_clock,
        )

        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])
        created = create_subscription(customer, plan, zone)
        v_at_create = created["version"]

        kit = find_kit(created["id"])
        kit_event(kit["id"], "ISSUE")
        customer_event(customer["id"], "ACTIVATE")
        activated = validate_success(
            _client.subscription_event(created["id"], {"event_type": "ACTIVATE"}, ADMIN)
        )
        assert activated["version"] == v_at_create + 1, (
            f"ACTIVATE must advance the version by exactly one: "
            f"{v_at_create} -> {activated['version']}"
        )

        paused = create_pause(
            created["id"], "2026-08-05", "2026-08-10",
            activated["version"], make_customer_headers(customer["id"]),
        )
        assert paused["status"] == "SCHEDULED"
        v_after_pause = read_subscription_version(created["id"])
        assert v_after_pause == activated["version"] + 1, (
            f"pause creation must advance the version by exactly one: "
            f"{activated['version']} -> {v_after_pause}"
        )


class TestDerivedAvailability:
    def test_derived_available_units_reconciled_across_kit_lifecycle(self, api):
        """PRD 2.7: "The derived `available_units` is what remains for new
        commitments: on-hand minus reserved."
        PRD 3.2: "Creation has three side effects. A starter kit is created in
        `RESERVED` status whose `size_code` equals the subscription's
        `current_size_code` and whose `item_count` is the kit size from §3.1; the size
        pool moves `item_count` units from `on_hand_units` into `reserved_units`"

        Design: Corner/complexity_layers/derived_available_units_reconciled_across_kit_lifecycle
        """
        from test_helpers.fixtures import (
            create_customer,
            create_plan,
            create_subscription,
            create_zone,
            fund_pool,
            set_clock,
        )

        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        pool = fund_pool("MEDIUM", 500)
        assert pool["available_units"] == 500

        customer = create_customer(zone["id"])
        subscription = create_subscription(customer, plan, zone)

        after_reserve = read_pool(pool["id"])
        assert after_reserve["on_hand_units"] == 412
        assert after_reserve["reserved_units"] == 88
        assert after_reserve["available_units"] == 324, (
            "available = on_hand 412 - reserved 88 after the kit reservation"
        )

        kit = find_kit(subscription["id"])
        kit_event(kit["id"], "ISSUE")

        after_issue = read_pool(pool["id"])
        assert after_issue["reserved_units"] == 0
        assert after_issue["checked_out_units"] == 88
        assert after_issue["available_units"] == 412, (
            "ISSUE converts the reservation to checked-out, freeing availability"
        )
