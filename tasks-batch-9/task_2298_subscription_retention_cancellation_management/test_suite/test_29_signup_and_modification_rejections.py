"""Catalogue and modification guards that refuse a write without leaving a trace.

A retired plan takes no new subscriptions, an unlisted cadence and an unlisted addon are
both refused against the plan's own declarations, the downgrade lattice belongs to the plan
rather than to the caller, and a subscription on its way out can no longer be modified.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    complete_session,
    create_modification_payload,
    create_subscription_payload,
    modifications_for,
    new_core_plan,
    new_payment_method,
    new_plan,
    new_subscriber,
    read_subscriber,
    read_subscription,
    set_clock,
    setup_active_subscription,
    setup_reason_captured_session,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


def _plan(plan_id):
    return validate_success(api_client.get_plan(plan_id, ADMIN), 200)


class TestRetiredPlanSignup:

    def test_a_retired_plan_keeps_its_counters_and_takes_no_new_subscription(self):
        """The signup is refused, no invoice is minted and the subscriber never starts.

        PRD §3.1: "`status` is either `ACTIVE` or `RETIRED` and defaults to `ACTIVE`; a
        retired plan may not take new subscriptions."

        Design: Corner/errors/subscribing_to_a_retired_plan_is_rejected
        """
        set_clock("2026-01-10")
        retired_plan = new_plan(code="OLDBOX", name="Retired Box", monthly_price_cents=4000,
                                unit_cogs_cents=2000, margin_floor_pct=0.4000,
                                status="RETIRED")
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        card = new_payment_method(subscriber["id"])

        validate_error(api_client.create_subscription(
            create_subscription_payload(subscriber["id"], retired_plan["id"], card["id"]),
            ADMIN), ApiErrorId.ERR_PLAN_RETIRED, 422)

        stored_plan = _plan(retired_plan["id"])
        assert stored_plan["status"] == "RETIRED"
        assert stored_plan["active_subscription_count"] == 0

        _, invoice_meta = validate_paginated(api_client.list_invoices(ADMIN))
        assert invoice_meta["total_count"] == 0
        assert read_subscriber(subscriber["id"])["first_subscribed_at"] is None


class TestUnlistedCadenceSignup:

    def test_a_three_week_cadence_is_refused_against_the_plans_own_list(self):
        """The plan allows two, four and eight weeks, so three creates nothing.

        PRD §3.2: "`frequency_weeks` must be a member of the plan's
        `allowed_frequency_weeks` or the request is rejected with
        `ERR_FREQUENCY_NOT_ALLOWED` (422)".

        Design: Corner/errors/signup_at_a_cadence_outside_the_plan_list_is_rejected
        """
        set_clock("2026-01-10")
        plan = new_core_plan()
        assert plan["allowed_frequency_weeks"] == [2, 4, 8]
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        card = new_payment_method(subscriber["id"])

        validate_error(api_client.create_subscription(
            create_subscription_payload(subscriber["id"], plan["id"], card["id"],
                                        frequency_weeks=3, disclosure_acknowledged=True),
            ADMIN), ApiErrorId.ERR_FREQUENCY_NOT_ALLOWED, 422)

        _, subscription_meta = validate_paginated(api_client.list_subscriptions(
            ADMIN, params={"subscriber_id": subscriber["id"]}))
        assert subscription_meta["total_count"] == 0
        _, invoice_meta = validate_paginated(api_client.list_invoices(ADMIN))
        assert invoice_meta["total_count"] == 0
        assert _plan(plan["id"])["active_subscription_count"] == 0


class TestUnlistedAddon:

    def test_an_addon_the_plan_does_not_sell_cannot_be_attached(self):
        """SOCKS is not in the catalogue, so the price stays at the bare plan price.

        PRD §3.3: "then `addon_code` membership in the current plan's `addon_catalog`
        (`ERR_ADDON_NOT_AVAILABLE`, 422)".

        Design: Corner/errors/adding_an_addon_absent_from_the_catalog_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        assert [entry["code"] for entry in world["plan"]["addon_catalog"]] == ["MUG", "TUMBLER"]

        payload = create_modification_payload(
            "ADDON_ADD", world["subscription"]["version"], addon_code="SOCKS", addon_qty=1)
        validate_error(
            api_client.create_modification(world["subscription"]["id"], payload,
                                           world["subscriber_headers"]),
            ApiErrorId.ERR_ADDON_NOT_AVAILABLE, 422)

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["addons"] == []
        assert subscription["committed_price_cents"] == 4999
        assert subscription["version"] == 1
        assert modifications_for(subscription["id"]) == []


class TestDowngradeLattice:

    def test_a_real_plan_that_is_not_the_declared_target_is_still_refused(self):
        """The foreign key resolves, so the refusal is about the lattice, not existence.

        PRD §3.3: "A **plan downgrade** requires that `target_plan_id` equal the current
        plan's `downgrade_target_plan_id` and that the latter not be null; anything else is
        rejected with `ERR_DOWNGRADE_TARGET_MISSING` (422)."

        Design: Corner/errors/downgrade_to_a_plan_that_is_not_the_declared_target_is_rejected
        """
        set_clock("2026-01-10")
        world = setup_active_subscription(
            subscriber_overrides={"acquisition_channel": "SEARCH"})
        other_plan = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                              margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                              is_negative_option=False)
        assert world["plan"]["downgrade_target_plan_id"] is None

        payload = create_modification_payload(
            "PLAN_DOWNGRADE", world["subscription"]["version"],
            target_plan_id=other_plan["id"])
        validate_error(
            api_client.create_modification(world["subscription"]["id"], payload, RETENTION),
            ApiErrorId.ERR_DOWNGRADE_TARGET_MISSING, 422)

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["plan_id"] == world["plan"]["id"]
        assert subscription["committed_price_cents"] == 4999
        assert subscription["version"] == 1


class TestModificationAfterCancellationRequest:

    def test_a_pending_cancel_subscription_refuses_a_correctly_versioned_change(self):
        """The version quoted is current, so the only thing left to refuse is the state.

        PRD §3.3: "The guards on a modification request run in this order once the version
        check of §2.7 has passed: the subscription's `lifecycle_state` must be `ACTIVE` or
        `PAUSED`, and a subscription in `PENDING_CANCEL` or `CANCELLED` is rejected with
        `ERR_SUBSCRIPTION_NOT_MODIFIABLE` (409)".

        Design: Corner/errors/modifying_a_pending_cancel_subscription_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="PRICE")
        complete_session(session["id"], world["subscriber_headers"])

        pending = read_subscription(world["subscription"]["id"])
        assert pending["lifecycle_state"] == "PENDING_CANCEL"
        assert pending["version"] == 2

        payload = create_modification_payload("FREQUENCY_CHANGE", pending["version"],
                                              frequency_weeks=8)
        validate_error(
            api_client.create_modification(pending["id"], payload,
                                           world["subscriber_headers"]),
            ApiErrorId.ERR_SUBSCRIPTION_NOT_MODIFIABLE, 409)

        held = read_subscription(pending["id"])
        assert held["lifecycle_state"] == "PENDING_CANCEL"
        assert held["frequency_weeks"] == 4
        assert held["version"] == 2
        assert modifications_for(held["id"]) == []
