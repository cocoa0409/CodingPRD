"""Conditional, aggregate and satisfied validations on signups and modifications.

The disclosure requirement fires only on negative-option plans; a cadence the plan allows
sails through the same rule that rejects one it does not; a pause spanning too many cycles
and a skip against an exhausted allotment are both refused without leaving a row behind.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant,
    assert_prior_snapshot_shape,
    assert_subscription_modification,
    create_modification_payload,
    create_subscription_payload,
    instant,
    modifications_for,
    new_core_plan,
    new_payment_method,
    new_plan,
    new_subscriber,
    notices_for,
    read_subscription,
    request_modification,
    set_clock,
    setup_active_subscription,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestConditionalDisclosureGate:

    def test_an_unacknowledged_disclosure_only_blocks_the_negative_option_plan(self):
        """The same body is a 201 on a plain plan and a 422 on an auto-renewing one.

        PRD §3.2: "when the plan is a negative-option plan, `disclosure_acknowledged` must
        be true or the request is rejected with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` (422)".

        Design: Corner/validations/disclosure_gate_applies_only_to_negative_option_plans
        """
        set_clock("2026-01-10")
        plain_plan = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                             margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                             is_negative_option=False)
        auto_renewing_plan = new_core_plan()
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        card = new_payment_method(subscriber["id"])

        accepted = validate_success(api_client.create_subscription(
            create_subscription_payload(subscriber["id"], plain_plan["id"], card["id"],
                                        disclosure_acknowledged=False), ADMIN), 201)
        assert accepted["disclosure_acknowledged"] is False
        # The paper trail is laid down only on a negative-option signup.
        assert notices_for(accepted["id"]) == []

        validate_error(api_client.create_subscription(
            create_subscription_payload(subscriber["id"], auto_renewing_plan["id"], card["id"],
                                        disclosure_acknowledged=False), ADMIN),
            ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED, 422)

        assert validate_success(api_client.get_plan(auto_renewing_plan["id"], ADMIN),
                                200)["active_subscription_count"] == 0


class TestSatisfiedCadenceRule:

    def test_a_cadence_the_plan_allows_applies_and_leaves_the_price_alone(self):
        """Eight weeks is on the list, so the change applies with a zero price delta.

        PRD §3.3: "A **frequency change** replaces `frequency_weeks`, which changes the
        cycle length and therefore every subsequent renewal interval."

        Design: Corner/validations/allowed_frequency_change_passes_and_leaves_price_untouched
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})

        modification = request_modification(
            world["subscription"]["id"], "FREQUENCY_CHANGE", world["subscriber_headers"],
            frequency_weeks=8)

        assert_subscription_modification(modification)
        assert modification["state"] == "APPLIED"
        assert_instant(modification["applied_at"], "2026-01-10T00:00:00Z", "applied_at")
        assert modification["delta_price_cents"] == 0
        assert modification["save_offer_grant_id"] is None
        assert_prior_snapshot_shape(modification["prior_snapshot"])
        assert modification["prior_snapshot"]["frequency_weeks"] == 4

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["frequency_weeks"] == 8
        assert subscription["committed_price_cents"] == 4999
        assert subscription["version"] == 2


class TestPauseSpanCeiling:

    def test_a_four_month_pause_on_a_four_week_cadence_is_refused(self):
        """Five rounded-up cycles against a ceiling of three, so nothing is paused.

        PRD §3.3: "The span of the pause in cycles is the window's duration divided by the
        cycle length in days, rounded **up** to a whole number, and that figure may not
        exceed the plan's `max_pause_cycles`; a longer pause is rejected with
        `ERR_PAUSE_EXCEEDS_MAX_CYCLES` (422)."

        Design: Corner/validations/pause_longer_than_max_pause_cycles_returns_constraint_error
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})

        payload = create_modification_payload(
            "PAUSE", world["subscription"]["version"],
            pause_start_at=instant("2026-01-10"), pause_end_at=instant("2026-05-10"))
        validate_error(
            api_client.create_modification(world["subscription"]["id"], payload,
                                           world["subscriber_headers"]),
            ApiErrorId.ERR_PAUSE_EXCEEDS_MAX_CYCLES, 422)

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert subscription["paused_until"] is None
        assert subscription["pause_cycles_used"] == 0
        assert subscription["version"] == 1
        assert modifications_for(subscription["id"]) == []


class TestSkipAllotment:

    def test_a_skip_on_a_single_shipment_term_is_refused_as_exhausted(self):
        """The signup already consumed the only unit, so remaining is 0 and the skip fails.

        PRD §3.3: "A **skip** consumes one unit of the shipment allotment. It requires
        `term_shipments_remaining` to be strictly greater than zero; a skip requested
        against an exhausted allotment is rejected with `ERR_SKIP_BUDGET_EXHAUSTED` (422)."

        Design: Corner/validations/skip_with_no_remaining_term_units_returns_skip_budget_exhausted
        """
        set_clock("2026-01-10")
        single_shipment_plan = new_plan(code="ONESHOT", monthly_price_cents=3000,
                                       unit_cogs_cents=1000, shipments_per_term=1)
        world = setup_active_subscription(
            plan=single_shipment_plan,
            subscriber_overrides={"acquisition_channel": "SEARCH"})
        assert world["subscription"]["term_shipments_remaining"] == 0

        payload = create_modification_payload(
            "SKIP_SHIPMENT", world["subscription"]["version"],
            skip_ship_at=instant("2026-02-07"))
        validate_error(
            api_client.create_modification(world["subscription"]["id"], payload,
                                           world["subscriber_headers"]),
            ApiErrorId.ERR_SKIP_BUDGET_EXHAUSTED, 422)

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["term_shipments_skipped"] == 0
        assert subscription["term_shipments_remaining"] == 0
        assert subscription["version"] == 1
        assert modifications_for(subscription["id"]) == []
