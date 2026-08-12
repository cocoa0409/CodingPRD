"""Subscription lifecycle: parallel billing/service dimensions, activation
gates, plan-change proration arithmetic, and billing invariants."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_plan,
    create_senior,
    create_subscription,
    deliver_kit,
    factories,
    fixtures,
    get_success_data,
    order_kit,
    record_payment_payload,
    set_clock,
    setup_active_senior,
    setup_installed_senior,
    setup_senior_with_subscription,
    setup_two_active_seniors_one_installer,
    ship_kit,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _plus_plan():
    return create_plan(
        tier="PLUS",
        monthly_fee_cents=6000,
        included_motion_sensors=2,
        extra_sensor_fee_cents=199,
        max_contacts=5,
        checkin_interval_hours=48,
        medication_reminders_enabled=True,
        wellness_report_enabled=True,
        wellness_report_cadence="MONTHLY",
    )


def _premium_plan():
    return create_plan(
        tier="PREMIUM",
        monthly_fee_cents=9000,
        included_motion_sensors=2,
        extra_sensor_fee_cents=199,
        max_contacts=8,
        checkin_interval_hours=24,
        medication_reminders_enabled=True,
        wellness_report_enabled=True,
        wellness_report_cadence="WEEKLY",
    )


class TestSubscriptionCreation:
    def test_subscription_created_with_parallel_initial_states(self, api):
        """PRD 3.2: "A subscription ties a senior to a plan: creation supplies
        `senior_id` and `plan_id` and produces a subscription, thereafter
        addressed by its `subscription_id`, whose two parallel status
        dimensions evolve independently — `service_status` begins at
        `PROVISIONING` while `billing_status` begins at `CURRENT`."
        PRD 3.2: "The financial counters start at zero: `billing_credit_cents`,
        `lifetime_charged_cents`, `lifetime_credited_cents`, and
        `consecutive_failed_payments` all begin at 0, and the
        `last_change_plan_credit_cents`, `last_change_sensor_credit_cents`,
        `last_change_total_credit_cents`, `last_change_total_charge_cents`, and
        `last_change_net_cents` fields stay null until the first plan change."

        Design: Corner/state_machines/subscription_created_with_parallel_initial_states
        """
        plan = _plus_plan()
        senior = create_senior()
        data = validate_success(
            api.create_subscription(
                {"senior_id": senior["id"], "plan_id": plan["id"]}, ADMIN
            ),
            201,
        )
        assert data["service_status"] == "PROVISIONING"
        assert data["billing_status"] == "CURRENT"
        assert data["consecutive_failed_payments"] == 0
        assert data["billing_credit_cents"] == 0
        assert data["lifetime_charged_cents"] == 0
        assert data["lifetime_credited_cents"] == 0

    def test_body_fk_not_found_on_subscription_create(self, api):
        """PRD 2.9: "Only after the body parses does the system resolve
        identifiers: path-template identifiers are validated strictly left to
        right, so a request naming two resources fails with `ERR_NOT_FOUND` for
        the first unresolvable id in the path, and only once the path fully
        resolves are foreign keys inside the body checked, also under
        `ERR_NOT_FOUND`."

        Design: Corner/validations/body_fk_not_found_on_subscription_create
        """
        senior = create_senior(full_name="Fk Senior")
        resp = api.create_subscription(
            {
                "senior_id": senior["id"],
                "plan_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestActivationGates:
    def test_subscription_activate_without_installed_kit_rejected(self, api):
        """PRD 3.2: "Activation moves `service_status` from `PROVISIONING` to
        `ACTIVE`. It requires billing to be `CURRENT` (otherwise
        `ERR_BILLING_NOT_CURRENT`) and at least one of the senior's kits to be
        `INSTALLED` or `ACTIVE` (otherwise `ERR_KIT_NOT_DELIVERED`)."

        Design: Corner/state_machines/subscription_activate_without_installed_kit_rejected
        """
        ctx = setup_senior_with_subscription(
            plan_overrides={"tier": "ESSENTIAL", "included_motion_sensors": 1}
        )
        kit = order_kit(ctx["senior"]["id"])
        ship_kit(kit["id"])
        deliver_kit(kit["id"])  # DELIVERED, never INSTALLED
        resp = api.activate_subscription(ctx["subscription"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_KIT_NOT_DELIVERED)
        sub = get_success_data(
            api.get_subscription(ctx["subscription"]["id"], ADMIN)
        )
        assert sub["service_status"] == "PROVISIONING"

    def test_activate_with_past_due_billing_rejected(self, api):
        """PRD 3.2: "Activation moves `service_status` from `PROVISIONING` to
        `ACTIVE`. It requires billing to be `CURRENT` (otherwise
        `ERR_BILLING_NOT_CURRENT`) and at least one of the senior's kits to be
        `INSTALLED` or `ACTIVE` (otherwise `ERR_KIT_NOT_DELIVERED`)."

        Design: Corner/validations/activate_with_past_due_billing_rejected
        """
        ctx = setup_installed_senior(
            plan_overrides={"tier": "ESSENTIAL", "included_motion_sensors": 1}
        )
        get_success_data(
            api.record_payment(
                ctx["subscription"]["id"], {"outcome": "FAILED"}, ADMIN
            )
        )
        resp = api.activate_subscription(ctx["subscription"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BILLING_NOT_CURRENT)
        sub = get_success_data(
            api.get_subscription(ctx["subscription"]["id"], ADMIN)
        )
        assert sub["service_status"] == "PROVISIONING"
        assert sub["billing_status"] == "PAST_DUE"


class TestParallelDimensions:
    """Subscription's billing and service dimensions evolve independently."""

    def _setup(self):
        return setup_active_senior()

    def test_failed_then_succeeded_payment_moves_billing_only(self, api):
        """PRD 3.2: "A `FAILED` outcome first moves billing from `CURRENT` to
        `PAST_DUE`, incrementing `consecutive_failed_payments` by one."
        PRD 3.2: "A `SUCCEEDED` outcome returns billing to `CURRENT` from any
        billing status and resets `consecutive_failed_payments` to zero, but
        deliberately leaves `service_status` alone — a suspended service stays
        suspended until an explicit resume."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_and_service_dimensions
        """
        ctx = self._setup()
        sub_id = ctx["subscription"]["id"]
        first = get_success_data(
            api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN)
        )
        assert first["billing_status"] == "PAST_DUE"
        assert first["service_status"] == "ACTIVE", (
            "a single FAILED payment must not move the service dimension"
        )
        assert first["consecutive_failed_payments"] == 1

        second = get_success_data(
            api.record_payment(sub_id, {"outcome": "SUCCEEDED"}, ADMIN)
        )
        assert second["billing_status"] == "CURRENT"
        assert second["service_status"] == "ACTIVE"
        assert second["consecutive_failed_payments"] == 0

    def test_delinquency_suspends_and_billing_repair_keeps_suspension(self, api):
        """PRD 3.2: "A second failure — billing already `PAST_DUE` with
        `consecutive_failed_payments` at 1 or more — moves billing to
        `DELINQUENT` and, in the same mutation, cascades: an `ACTIVE` service
        becomes `SUSPENDED`, the senior's `monitoring_posture` becomes
        `DEGRADED`, and every open alert of the senior whose severity is `LOW`,
        `MEDIUM`, or `HIGH` is auto-resolved with `resolution_note` set to
        `AUTO_RESOLVED_POSTURE_DEGRADED`, decrementing `open_alert_count` once
        per alert and superseding their still-`SENT` notifications."
        PRD 3.2: "A `SUCCEEDED` outcome returns billing to `CURRENT` from any
        billing status and resets `consecutive_failed_payments` to zero, but
        deliberately leaves `service_status` alone — a suspended service stays
        suspended until an explicit resume."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_and_service_dimensions
        """
        ctx = self._setup()
        sub_id = ctx["subscription"]["id"]
        get_success_data(api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN))
        fourth = get_success_data(
            api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN)
        )
        assert fourth["billing_status"] == "DELINQUENT"
        assert fourth["service_status"] == "SUSPENDED", (
            "the second FAILED payment must cascade service to SUSPENDED"
        )

        fifth = get_success_data(
            api.record_payment(sub_id, {"outcome": "SUCCEEDED"}, ADMIN)
        )
        assert fifth["billing_status"] == "CURRENT"
        assert fifth["service_status"] == "SUSPENDED", (
            "billing repair must NOT resume the service dimension"
        )


class TestPlanChangeProrationModes:
    """DAILY_PRORATE vs FULL_CYCLE_SWAP on identical inputs (PRD 3.2)."""

    def _setup_pair(self):
        """Two seniors ACTIVE on the same PLUS plan; clock 2026-05-21T00:00Z
        (period_end 2026-05-31T11:00:00Z, days_remaining 10)."""
        ctx_a, ctx_b = setup_two_active_seniors_one_installer(
            plan_overrides={
                "tier": "PLUS",
                "monthly_fee_cents": 6000,
                "included_motion_sensors": 2,
                "extra_sensor_fee_cents": 199,
                "max_contacts": 5,
                "checkin_interval_hours": 48,
                "medication_reminders_enabled": True,
                "wellness_report_enabled": True,
                "wellness_report_cadence": "MONTHLY",
            }
        )
        plan_prem = _premium_plan()
        set_clock("2026-05-21T00:00:00Z")
        return ctx_a, ctx_b, plan_prem

    def test_daily_prorate_amounts_and_period_unchanged(self, api):
        """PRD 3.2: "Under `DAILY_PRORATE`, two credit lines refund the old
        plan: the plan-fee credit is the old plan's `monthly_fee_cents`
        multiplied by `days_remaining` and divided by 30, rounded half up to a
        whole cent, and the sensor credit is the old plan's
        `extra_sensor_fee_cents` multiplied by the number of extra sensors —
        the kit's motion sensor count minus the old plan's
        `included_motion_sensors`, floored at zero — then by `days_remaining`
        and divided by 30, again rounded half up."
        PRD 3.2: "Under `FULL_CYCLE_SWAP` there is no proration: the credit is
        the old plan's full monthly fee plus its full extra-sensor fees, the
        charge is the new plan's full monthly fee plus its full extra-sensor
        fees, and `current_period_end` is reset to thirty days from the current
        clock; under the default mode `current_period_end` is left unchanged."

        Design: Difficulty/dual_variant_calc/proration_daily_vs_full_cycle_swap
        """
        ctx_a, _ctx_b, plan_prem = self._setup_pair()
        data = get_success_data(
            api.change_plan(
                ctx_a["subscription"]["id"],
                {"plan_id": plan_prem["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        assert data["last_change_total_credit_cents"] == 2000
        assert data["last_change_total_charge_cents"] == 3000
        assert data["last_change_net_cents"] == 1000
        assert _parse_ts(data["current_period_end"]) == _parse_ts(
            "2026-05-31T11:00:00Z"
        ), "DAILY_PRORATE must leave current_period_end unchanged"

    def test_full_cycle_swap_amounts_and_period_reset(self, api):
        """PRD 3.2: "Under `FULL_CYCLE_SWAP` there is no proration: the credit
        is the old plan's full monthly fee plus its full extra-sensor fees, the
        charge is the new plan's full monthly fee plus its full extra-sensor
        fees, and `current_period_end` is reset to thirty days from the current
        clock; under the default mode `current_period_end` is left unchanged."
        PRD 3.2: "The request names the new `plan_id` and may name a
        `proration_mode`; when omitted, the mode defaults to `DAILY_PRORATE`."

        Design: Difficulty/dual_variant_calc/proration_daily_vs_full_cycle_swap
        """
        ctx_a, ctx_b, plan_prem = self._setup_pair()
        daily = get_success_data(
            api.change_plan(
                ctx_a["subscription"]["id"],
                {"plan_id": plan_prem["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        swap = get_success_data(
            api.change_plan(
                ctx_b["subscription"]["id"],
                {"plan_id": plan_prem["id"], "proration_mode": "FULL_CYCLE_SWAP"},
                ADMIN,
            )
        )
        assert swap["last_change_total_credit_cents"] == 6000
        assert swap["last_change_total_charge_cents"] == 9000
        assert swap["last_change_net_cents"] == 3000
        assert _parse_ts(swap["current_period_end"]) == _parse_ts(
            "2026-06-20T00:00:00Z"
        ), "FULL_CYCLE_SWAP must reset current_period_end to now + 30 days"
        assert daily["last_change_net_cents"] != swap["last_change_net_cents"], (
            "identical inputs under the two modes must produce different nets"
        )


class TestPerLineRoundingOrder:
    """Per-line rounding then sum is pinned (PRD 2.7, 3.2)."""

    def _setup(self, api):
        plan_old = create_plan(
            tier="ESSENTIAL",
            monthly_fee_cents=5999,
            included_motion_sensors=1,
            extra_sensor_fee_cents=199,
            max_contacts=3,
            checkin_interval_hours=72,
            medication_reminders_enabled=False,
            wellness_report_enabled=False,
            wellness_report_cadence="NONE",
        )
        plan_new = _premium_plan()
        senior = create_senior(full_name="Round Senior")
        subscription = create_subscription(senior["id"], plan_old["id"])
        kit = order_kit(senior["id"], motion_sensor_count=2)
        ship_kit(kit["id"])
        deliver_kit(kit["id"])
        installer, appointment = fixtures.install_kit(
            senior["id"],
            kit["id"],
            window_start="2026-05-01T10:00:00Z",
            window_end="2026-05-01T11:00:00Z",
            complete_at="2026-05-01T11:00:00Z",
        )
        get_success_data(api.activate_subscription(subscription["id"], ADMIN))
        set_clock("2026-05-17T11:00:00Z")
        return subscription, plan_new

    def test_proration_per_line_credit_rounding(self, api):
        """PRD 2.7: "Plan-change proration (§3.2) rounds each credit or charge
        line independently — rounding half up to the nearest whole cent — and
        only then sums the rounded lines. This per-line-then-sum order is
        pinned: summing unrounded lines and rounding once can differ from the
        pinned result by a cent, and implementations must reproduce the pinned
        behavior."

        Design: Difficulty/combinatorial_formula/proration_per_line_rounding_order
        """
        subscription, plan_new = self._setup(api)
        data = get_success_data(
            api.change_plan(
                subscription["id"],
                {"plan_id": plan_new["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        # days_remaining = 14; old fee 5999, one extra sensor at 199.
        assert data["last_change_plan_credit_cents"] == 2800, (
            "plan-fee credit must be round_half_up(5999*14/30) = 2800"
        )
        assert data["last_change_sensor_credit_cents"] == 93, (
            "sensor credit must be round_half_up(199*1*14/30) = 93"
        )

    def test_proration_per_line_total_and_net(self, api):
        """PRD 2.7: "Plan-change proration (§3.2) rounds each credit or charge
        line independently — rounding half up to the nearest whole cent — and
        only then sums the rounded lines. This per-line-then-sum order is
        pinned: summing unrounded lines and rounding once can differ from the
        pinned result by a cent, and implementations must reproduce the pinned
        behavior."
        PRD 3.2: "The net of a change is the total charge minus the total
        credit. A non-negative net is added to `lifetime_charged_cents`; a
        negative net has its absolute value added to both
        `lifetime_credited_cents` and the spendable `billing_credit_cents`."

        Design: Difficulty/combinatorial_formula/proration_per_line_rounding_order
        """
        subscription, plan_new = self._setup(api)
        data = get_success_data(
            api.change_plan(
                subscription["id"],
                {"plan_id": plan_new["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        # Per-line: 2800 + 93 = 2893. Sum-then-round would yield 2892.
        assert data["last_change_total_credit_cents"] == 2893
        assert data["last_change_total_charge_cents"] == 4200
        assert data["last_change_net_cents"] == 1307
        assert data["lifetime_charged_cents"] == 1307


class TestBillingNetPositionInvariant:
    """Round-tripping a plan change conserves the lifetime net position."""

    def _setup(self):
        plan_plus = _plus_plan()
        plan_prem = _premium_plan()
        ctx_a, _ctx_b = setup_two_active_seniors_one_installer(
            plan_overrides={
                "tier": "PLUS",
                "monthly_fee_cents": 6000,
                "included_motion_sensors": 2,
                "extra_sensor_fee_cents": 199,
                "max_contacts": 5,
                "checkin_interval_hours": 48,
                "medication_reminders_enabled": True,
                "wellness_report_enabled": True,
                "wellness_report_cadence": "MONTHLY",
            }
        )
        # ctx_a activated at clock 2026-05-01T11:00:00Z; move to day-10 mark.
        set_clock("2026-05-21T11:00:00Z")
        return ctx_a, plan_plus, plan_prem

    def test_plan_change_round_trip_nets_zero_lifetime_position(self, api):
        """PRD 3.2: "The net of a change is the total charge minus the total
        credit. A non-negative net is added to `lifetime_charged_cents`; a
        negative net has its absolute value added to both
        `lifetime_credited_cents` and the spendable `billing_credit_cents`."

        Design: Difficulty/compensating_invariant/inv_billing_net_position_round_trip
        """
        ctx_a, plan_plus, plan_prem = self._setup()
        sub_id = ctx_a["subscription"]["id"]
        upgrade = get_success_data(
            api.change_plan(
                sub_id,
                {"plan_id": plan_prem["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        assert upgrade["last_change_net_cents"] == 1000

        downgrade = get_success_data(
            api.change_plan(
                sub_id,
                {"plan_id": plan_plus["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        assert downgrade["last_change_net_cents"] == -1000
        net_position = (
            downgrade["lifetime_charged_cents"]
            - downgrade["lifetime_credited_cents"]
        )
        assert downgrade["lifetime_charged_cents"] == 1000
        assert downgrade["lifetime_credited_cents"] == 1000
        assert net_position == 0, (
            "an upgrade followed by its compensating downgrade at an unchanged "
            "clock must leave the net lifetime position unchanged"
        )

    def test_plan_change_round_trip_banks_credit(self, api):
        """PRD 3.2: "The net of a change is the total charge minus the total
        credit. A non-negative net is added to `lifetime_charged_cents`; a
        negative net has its absolute value added to both
        `lifetime_credited_cents` and the spendable `billing_credit_cents`."

        Design: Difficulty/compensating_invariant/inv_billing_net_position_round_trip
        """
        ctx_a, plan_plus, plan_prem = self._setup()
        sub_id = ctx_a["subscription"]["id"]
        get_success_data(
            api.change_plan(
                sub_id,
                {"plan_id": plan_prem["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        downgrade = get_success_data(
            api.change_plan(
                sub_id,
                {"plan_id": plan_plus["id"], "proration_mode": "DAILY_PRORATE"},
                ADMIN,
            )
        )
        assert downgrade["billing_credit_cents"] == 1000, (
            "the negative net must be banked as spendable billing credit"
        )


class TestPaymentFailureCascade:
    """Depth-3 cascade: payment -> subscription -> posture -> alerts."""

    def _setup(self):
        """ACTIVE senior; gateway ONLINE with an open LOW_BATTERY MEDIUM alert
        (battery reading 15) and no contact tree (alert sits RAISED)."""
        ctx = setup_active_senior()
        gateway = ctx["devices"]["gateway"]
        # Advance the clock so the battery reading is not a future event.
        set_clock("2026-05-01T10:30:00Z")
        fixtures.ingest_event(
            gateway["id"], "HEARTBEAT", "2026-05-01T10:30:00Z", battery_percent=15
        )
        alerts = fixtures.list_alerts(
            senior_id=ctx["senior"]["id"], alert_type="LOW_BATTERY"
        )
        assert len(alerts) == 1, "setup: one LOW_BATTERY alert must be open"
        ctx["low_battery_alert"] = alerts[0]
        return ctx

    def test_second_failed_payment_suspends_and_degrades(self, api):
        """PRD 3.2: "A second failure — billing already `PAST_DUE` with
        `consecutive_failed_payments` at 1 or more — moves billing to
        `DELINQUENT` and, in the same mutation, cascades: an `ACTIVE` service
        becomes `SUSPENDED`, the senior's `monitoring_posture` becomes
        `DEGRADED`, and every open alert of the senior whose severity is `LOW`,
        `MEDIUM`, or `HIGH` is auto-resolved with `resolution_note` set to
        `AUTO_RESOLVED_POSTURE_DEGRADED`, decrementing `open_alert_count` once
        per alert and superseding their still-`SENT` notifications."

        Design: Difficulty/transitive_cascade/payment_failure_posture_auto_resolve_chain
        """
        ctx = self._setup()
        sub_id = ctx["subscription"]["id"]
        first = get_success_data(
            api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN)
        )
        assert first["billing_status"] == "PAST_DUE"
        second = get_success_data(
            api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN)
        )
        assert second["billing_status"] == "DELINQUENT"
        assert second["service_status"] == "SUSPENDED"
        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["monitoring_posture"] == "DEGRADED"
        assert senior["open_alert_count"] == 0

    def test_delinquency_auto_resolves_non_critical_alerts(self, api):
        """PRD 3.2: "A second failure — billing already `PAST_DUE` with
        `consecutive_failed_payments` at 1 or more — moves billing to
        `DELINQUENT` and, in the same mutation, cascades: an `ACTIVE` service
        becomes `SUSPENDED`, the senior's `monitoring_posture` becomes
        `DEGRADED`, and every open alert of the senior whose severity is `LOW`,
        `MEDIUM`, or `HIGH` is auto-resolved with `resolution_note` set to
        `AUTO_RESOLVED_POSTURE_DEGRADED`, decrementing `open_alert_count` once
        per alert and superseding their still-`SENT` notifications."

        Design: Difficulty/transitive_cascade/payment_failure_posture_auto_resolve_chain
        """
        ctx = self._setup()
        alert = ctx["low_battery_alert"]
        assert alert["status"] == "RAISED", "alert must be open before cascade"
        sub_id = ctx["subscription"]["id"]
        get_success_data(api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN))
        get_success_data(api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN))
        alert_after = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert alert_after["status"] == "RESOLVED"
        assert alert_after["resolution_note"] == "AUTO_RESOLVED_POSTURE_DEGRADED"
