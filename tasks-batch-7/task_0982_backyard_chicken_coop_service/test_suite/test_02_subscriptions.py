"""Subscriptions: coverage boundary, period computation, plan changes, renewal, OCC."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, assert_same_instant,
    create_household, create_plan, create_subscription, create_coop,
    create_visit, install_coop, setup_household_with_installed_coop,
    set_logical_clock, make_customer_headers, plan_change_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _setup_subscription_with_installed_coop(zone_code="URBAN", **plan_overrides):
    """Household + plan + ACTIVE subscription (period 2026-05-01) + INSTALLED coop."""
    household = create_household(zone_code=zone_code)
    plan = create_plan(**plan_overrides)
    subscription = create_subscription(household, plan["id"], "2026-05-01T00:00:00Z")
    coop = create_coop(household, 6)
    install_coop(household, coop, date="2026-05-02")
    return household, plan, subscription, coop


class TestCoverageBoundary:
    def test_first_two_cleanings_covered(self, api):
        """PRD §3.3: "When a household has an `ACTIVE` subscription — at most
        one can exist, per the uniqueness rule — a visit of type `COOP_CLEANING`
        or `FLOCK_HEALTH_CHECK` is `SUBSCRIPTION_COVERED` if the visit's
        scheduled date falls inside the half-open period from
        `current_period_start` inclusive to `current_period_end` exclusive
        **and** the matching used counter is strictly below the plan's included
        count: `used_cleanings` strictly less than
        `included_cleanings_per_period` for cleanings, `used_health_checks`
        strictly less than `included_health_checks_per_period` for health
        checks."
        PRD §3.3: "When coverage resolves to `SUBSCRIPTION_COVERED`, the visit's
        `subscription_id` is set and the corresponding used counter is
        incremented immediately — this is a reservation, released (decremented)
        only if the visit is cancelled or marked no-show before completing."

        Design: Difficulty/boundary_precision_check/subscription_coverage_boundary_third_visit_billable
        """
        household, plan, subscription, coop = _setup_subscription_with_installed_coop(
            included_cleanings_per_period=2)

        v1 = create_visit(household, coop, "COOP_CLEANING",
                          "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
        v2 = create_visit(household, coop, "COOP_CLEANING",
                          "2026-05-12T09:00:00Z", "2026-05-12T10:00:00Z")

        assert v1["coverage"] == "SUBSCRIPTION_COVERED", "used 0 < 2 at creation"
        assert v1["subscription_id"] == subscription["id"]
        assert v2["coverage"] == "SUBSCRIPTION_COVERED", "used 1 < 2 at creation"

        sub_after = validate_success(api.get_subscription(subscription["id"], BILLING), 200)
        assert sub_after["used_cleanings"] == 2

    def test_third_cleaning_at_included_count_is_billable(self, api):
        """PRD §3.3: "The boundary is a strict less-than: a counter equal to the
        included count means the visit is `BILLABLE`."

        Design: Difficulty/boundary_precision_check/subscription_coverage_boundary_third_visit_billable
        """
        household, plan, subscription, coop = _setup_subscription_with_installed_coop(
            included_cleanings_per_period=2)

        for day in ("10", "12"):
            create_visit(household, coop, "COOP_CLEANING",
                         f"2026-05-{day}T09:00:00Z", f"2026-05-{day}T10:00:00Z")
        v3 = create_visit(household, coop, "COOP_CLEANING",
                          "2026-05-14T09:00:00Z", "2026-05-14T10:00:00Z")

        assert v3["coverage"] == "BILLABLE", (
            "used 2 == included 2: strict less-than fails at equality")
        sub_after = validate_success(api.get_subscription(subscription["id"], BILLING), 200)
        assert sub_after["used_cleanings"] == 2, (
            "A BILLABLE visit must not consume covered reservations")


class TestPeriodComputation:
    def test_period_end_is_start_plus_one_calendar_month(self, api):
        """PRD §3.3: "On creation the subscription's `status` is `ACTIVE`,
        `used_cleanings` and `used_health_checks` start at 0, `pending_plan_id`
        is null, and `current_period_end` is computed as `current_period_start`
        plus one calendar month, exclusive."

        Design: Corner/entities/subscription_period_end_computed
        """
        household = create_household(name="H PE", address="25 Hen Ln")
        plan = create_plan(plan_code="PE1", monthly_fee_cents=1000,
                           included_cleanings_per_period=1, included_health_checks_per_period=1)
        subscription = create_subscription(household, plan["id"], "2026-05-01T00:00:00Z")

        assert_same_instant(subscription["current_period_end"], "2026-06-01T00:00:00Z",
                            "current_period_end")
        assert subscription["used_cleanings"] == 0
        assert subscription["used_health_checks"] == 0
        assert subscription["status"] == "ACTIVE"
        assert subscription["pending_plan_id"] is None


class TestRenewal:
    def test_renew_before_period_end_rejected(self, api):
        """PRD §3.3: "Renewal requires the subscription to be `ACTIVE` and the
        logical clock's date to have reached or passed `current_period_end` —
        earlier attempts are rejected with `ERR_PERIOD_NOT_ENDED`."

        Design: Corner/validations/renew_period_before_end_rejected
        """
        household = create_household(name="H RE", address="39 Hen Ln")
        plan = create_plan(plan_code="RE1", monthly_fee_cents=1000,
                           included_cleanings_per_period=1)
        subscription = create_subscription(household, plan["id"], "2026-05-01T00:00:00Z")

        res = api.renew_subscription_period(subscription["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_ENDED)

        after = validate_success(api.get_subscription(subscription["id"], BILLING), 200)
        assert_same_instant(after["current_period_start"], "2026-05-01T00:00:00Z",
                            "current_period_start")

    def test_renew_lands_pending_plan_and_resets_counters(self, api):
        """PRD §3.3: "Renewal lands any scheduled plan change (`plan_id` becomes
        `pending_plan_id`, then `pending_plan_id` returns to null), resets both
        used counters to 0, advances `current_period_start` to the old
        `current_period_end`, recomputes `current_period_end` as the new start
        plus one calendar month, and increments `version` by 1."

        Design: Corner/calculations/subscription_renew_applies_pending_plan
        """
        household, plan_a, subscription, coop = _setup_subscription_with_installed_coop(
            plan_code="RENA", monthly_fee_cents=2900, included_cleanings_per_period=1)
        plan_b = create_plan(plan_code="RENB", monthly_fee_cents=4900,
                             included_cleanings_per_period=4, included_health_checks_per_period=2,
                             supply_discount_pct=0.10)

        covered = create_visit(household, coop, "COOP_CLEANING",
                               "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
        assert covered["coverage"] == "SUBSCRIPTION_COVERED"
        sub_now = validate_success(api.get_subscription(subscription["id"], BILLING), 200)
        assert sub_now["used_cleanings"] == 1

        change = validate_success(api.create_plan_change(
            subscription["id"],
            plan_change_payload(plan_b["id"], sub_now["version"]),
            make_customer_headers(household["id"])), 200)
        assert change["pending_plan_id"] == plan_b["id"]

        set_logical_clock("2026-06-01T00:00:00Z")
        renewed = validate_success(
            api.renew_subscription_period(subscription["id"], BILLING), 200)

        assert renewed["plan_id"] == plan_b["id"], "pending change lands at renew"
        assert renewed["pending_plan_id"] is None
        assert renewed["used_cleanings"] == 0, "counter reset"
        assert renewed["used_health_checks"] == 0
        assert_same_instant(renewed["current_period_start"], "2026-06-01T00:00:00Z",
                            "current_period_start")
        assert_same_instant(renewed["current_period_end"], "2026-07-01T00:00:00Z",
                            "current_period_end")


class TestPlanChanges:
    def test_plan_change_is_pending_until_renew(self, api):
        """PRD §3.3: "Plan changes are scheduled, not immediate."
        PRD §3.3: "A successful change records `pending_plan_id` as the new plan
        and increments the subscription's `version`; a new pending change
        legitimately supersedes any prior pending change, which is exactly why
        the stale-version guard exists."

        Design: Corner/cross_cutting_complexity_layers/plan_change_pending_until_renew
        """
        household = create_household(name="H PC", address="58 Hen Ln")
        plan_a = create_plan(plan_code="PCA", monthly_fee_cents=2900,
                             included_cleanings_per_period=1)
        plan_b = create_plan(plan_code="PCB", monthly_fee_cents=4900,
                             included_cleanings_per_period=4, supply_discount_pct=0.10)
        subscription = create_subscription(household, plan_a["id"], "2026-05-01T00:00:00Z")

        updated = validate_success(api.create_plan_change(
            subscription["id"],
            plan_change_payload(plan_b["id"], subscription["version"]),
            make_customer_headers(household["id"])), 200)

        assert updated["plan_id"] == plan_a["id"], "active plan unchanged until renew-period"
        assert updated["pending_plan_id"] == plan_b["id"]
        assert updated["status"] == "ACTIVE"

    def test_stale_plan_change_rejected_after_superseding_write(self, api):
        """PRD §2.7: "The request must carry `expected_subscription_version`
        equal to the target subscription's current `version`. If another writer
        has advanced the subscription's version since the client last read it —
        for example by posting a plan change of their own, which legitimately
        supersedes the prior pending change — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting
        state it has not observed."
        PRD §2.7: "Every successful plan change, period renewal, route
        publication, stop addition, stop removal, and wallet adjustment
        increments the owning entity's `version` by 1, so a client that reads a
        resource, then writes, always knows whether its view was current."

        Design: Corner/cross_cutting_complexity_layers/occ_plan_change_stale_version_rejected
        """
        household = create_household(name="H OCC1", address="55 Hen Ln")
        plan_a = create_plan(plan_code="OCCA", monthly_fee_cents=2900,
                             included_cleanings_per_period=1)
        plan_b = create_plan(plan_code="OCCB", monthly_fee_cents=4900,
                             included_cleanings_per_period=4, supply_discount_pct=0.10)
        subscription = create_subscription(household, plan_a["id"], "2026-05-01T00:00:00Z")
        observed_version = subscription["version"]
        customer = make_customer_headers(household["id"])

        first = validate_success(api.create_plan_change(
            subscription["id"], plan_change_payload(plan_b["id"], observed_version),
            customer), 200)
        assert first["version"] == observed_version + 1, "plan change increments version by 1"
        assert first["pending_plan_id"] == plan_b["id"]

        res = api.create_plan_change(
            subscription["id"], plan_change_payload(plan_a["id"], observed_version),
            customer)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_subscription(subscription["id"], BILLING), 200)
        assert after["pending_plan_id"] == plan_b["id"], "the losing write changed nothing"
