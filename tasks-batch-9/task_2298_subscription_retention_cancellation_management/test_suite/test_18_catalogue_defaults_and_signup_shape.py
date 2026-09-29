"""Declared defaults, the signup body, side-effect-free reads and the list envelope.

A plan created with only its required fields must carry every documented default; a
signup must settle both axes and the shipment triple in one 201; reading changes nothing
while the subscriber's derived fields track the clock; and lists page in creation order.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_common_fields,
    assert_instant,
    assert_plan,
    assert_shipment_units_conserved,
    assert_subscription,
    new_core_plan,
    new_plan,
    new_lite_plan,
    read_subscriber,
    read_subscription,
    set_clock,
    setup_active_subscription,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


class TestPlanDefaults:

    def test_a_plan_created_with_only_required_fields_carries_every_declared_default(self):
        """Cadence [2, 4, 8], twelve shipments, negative option, ten-day lead, three pauses.

        PRD §3.1: "`allowed_frequency_weeks` is a non-empty array of positive integers
        enumerating the cadences a subscription on this plan may choose; omitted, it
        defaults to the three values 2, 4 and 8. `max_pause_cycles` bounds how many
        cycles any single pause may span, at least 1, defaulting to 3. `addon_catalog` is
        the array of purchasable extras, each entry a `code`, a `unit_price_cents` and a
        `unit_cogs_cents`, and it defaults to empty."

        Design: Corner/entities/plan_create_applies_every_declared_field_default
        """
        set_clock("2026-01-10")
        response = api_client.create_plan(
            {"code": "MIN", "name": "Minimal Box", "monthly_price_cents": 1000,
             "unit_cogs_cents": 400, "margin_floor_pct": 0.3000}, ADMIN)
        plan = validate_success(response, 201)

        assert_plan(plan)
        assert plan["shipments_per_cycle"] == 1
        assert plan["shipments_per_term"] == 12
        assert plan["allowed_frequency_weeks"] == [2, 4, 8]
        assert plan["is_negative_option"] is True
        assert plan["renewal_reminder_days_before"] == 10
        assert plan["max_pause_cycles"] == 3
        assert plan["addon_catalog"] == []
        assert plan["downgrade_target_plan_id"] is None
        assert plan["status"] == "ACTIVE"
        assert plan["active_subscription_count"] == 0
        assert plan["version"] == 1


class TestSignupResponseShape:

    def test_one_signup_call_settles_both_axes_and_the_shipment_ledger(self):
        """4999 plus a 1299 addon commits 6298 and schedules the first renewal 28 days out.

        PRD §3.2: "The shipment ledger is initialised with `term_shipments_delivered` at
        1, `term_shipments_skipped` at 0 and `term_shipments_remaining` at the plan's
        `shipments_per_term` minus one. `committed_price_cents` is computed and copied
        into `baseline_price_cents`. `paused_until`, `cancel_effective_at`,
        `first_failed_at` and `grace_end_at` are all null, and
        `consecutive_failed_attempts` is 0. The plan's `active_subscription_count`
        increments."

        Design: Corner/entities/subscription_create_returns_201_with_every_declared_output_field
        """
        world = setup_active_subscription(
            clock="2026-01-10",
            subscriber_overrides={"acquisition_channel": "SEARCH"},
            addons=[{"code": "MUG", "qty": 1}])
        subscription = world["subscription"]

        assert_subscription(subscription)
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert subscription["billing_state"] == "CURRENT"
        assert subscription["committed_price_cents"] == 6298
        assert subscription["baseline_price_cents"] == 6298
        assert_instant(subscription["next_renewal_at"], "2026-02-07T00:00:00Z", "next_renewal_at")
        assert_instant(subscription["next_ship_at"], "2026-02-07T00:00:00Z", "next_ship_at")
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["term_shipments_skipped"] == 0
        assert subscription["term_shipments_remaining"] == 11
        assert_shipment_units_conserved(subscription, 12)
        assert subscription["active_discount_pct"] == pytest.approx(0.0000, abs=5e-5)
        assert subscription["discount_remaining_cycles"] == 0
        assert subscription["paused_until"] is None
        assert subscription["cancel_effective_at"] is None
        assert subscription["first_failed_at"] is None
        assert subscription["grace_end_at"] is None
        assert subscription["consecutive_failed_attempts"] == 0
        assert subscription["version"] == 1

        plan = validate_success(api_client.get_plan(world["plan"]["id"], ADMIN), 200)
        assert plan["active_subscription_count"] == 1


class TestReadsAreSideEffectFree:

    def test_a_read_ten_days_later_bumps_no_version_but_moves_derived_tenure(self):
        """The subscription still reads version 1 while the subscriber reads tenure 10.

        PRD §2.4: "Computed fields on `Subscriber` deserve a specific note: they are
        derived at read time against the logical clock. Reading a subscriber therefore
        always reflects the current `tenure_days`, the current `tenure_bucket`, the
        current `realized_ltv_cents` and `projected_ltv_cents` pair and the current
        trailing-window counts, without any intervening write being required."

        Design: Corner/entities/subscription_read_reflects_stored_state_without_bumping_version
        """
        world = setup_active_subscription(
            clock="2026-01-10",
            subscriber_overrides={"acquisition_channel": "SEARCH"},
            addons=[{"code": "MUG", "qty": 1}])

        set_clock("2026-01-20")

        subscription = read_subscription(world["subscription"]["id"])
        assert_common_fields(subscription)
        assert subscription["version"] == 1
        assert subscription["committed_price_cents"] == 6298
        assert subscription["plan_id"] == world["plan"]["id"]
        assert subscription["payment_method_id"] == world["payment_method"]["id"]

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert subscriber["tenure_days"] == 10
        assert subscriber["tenure_bucket"] == "M0_1"
        assert subscriber["cohort_month"] == "2026-01"

        # A second read still finds the same version: nothing was mutated by reading.
        assert read_subscription(world["subscription"]["id"])["version"] == 1


class TestListEnvelope:

    def test_plans_page_in_created_at_order_with_total_count_and_has_more(self):
        """Three plans, limit 2: the two oldest first, then the newest with has_more false.

        PRD §2.3: "List endpoints accept two query parameters. `limit` caps the number of
        items returned; it defaults to 10, may not be below 1, and may not exceed 100.
        `offset` is the number of items to skip and defaults to 0." and "List responses
        carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of
        the envelope described in §2.2."

        Design: Corner/entities/plan_list_paginates_by_created_at_ascending_with_envelope_metadata
        """
        # Distinct creation instants, so "ordered by created_at ascending" is unambiguous.
        set_clock("2026-01-10")
        lite = new_lite_plan()
        set_clock("2026-01-11")
        core = new_core_plan()
        set_clock("2026-01-12")
        bound = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                         margin_floor_pct=0.4048)

        first_page, first_meta = validate_paginated(
            api_client.list_plans(ADMIN, params={"limit": 2, "offset": 0}))
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert [plan["id"] for plan in first_page] == [lite["id"], core["id"]]

        second_page, second_meta = validate_paginated(
            api_client.list_plans(ADMIN, params={"limit": 2, "offset": 2}))
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False
        assert [plan["id"] for plan in second_page] == [bound["id"]]
