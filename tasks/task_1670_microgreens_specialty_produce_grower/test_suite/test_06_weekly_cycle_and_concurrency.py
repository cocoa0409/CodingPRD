"""The weekly order cycle (CONFIRMED -> LOCKED at cutoff, LOCKED -> CONFIRMED
on rollover), the change window, and optimistic concurrency on the two guarded
writes (line add, crop-plan sow)."""
from test_helpers import (
    ApiErrorId,
    add_order_line,
    add_order_line_payload,
    confirm_standing_order,
    create_approved_food_safety_plan,
    create_crop_plan,
    create_customer,
    create_listed_variety,
    create_released_seed_lot,
    create_standing_order,
    get_standing_order,
    make_chef_headers,
    setup_confirmed_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import GROWER, OPS


class TestWeeklyLockCycle:
    def test_confirmed_order_locks_after_cutoff_weekday(self, api):
        """PRD §3.5: "From `CONFIRMED`, the calendar takes over: once the
        logical clock's weekday passes the order's `change_cutoff_day` relative
        to its `effective_week_start`, the system moves the order to `LOCKED`
        and no further line changes are accepted for that week."
        PRD §2.5: "a `CONFIRMED` standing order flips to `LOCKED` once the
        clock's weekday passes the order's cutoff"

        Design: Difficulty/non_linear_state_machine/standing_order_confirm_lock_rollover_cycle
        """
        ws = setup_confirmed_order(name="Arugula", crop_category="PETITE_GREEN",
                                   qty_kg=1.0, listed_price_cents_per_kg=900,
                                   days_to_harvest=12,
                                   effective_week_start="2026-08-03",
                                   change_cutoff_day=2)
        order = ws["standing_order"]
        customer = ws["customer"]
        assert order["status"] == "CONFIRMED"

        # 2026-08-06 is the Thursday of the effective week; weekday 3 > cutoff 2.
        validate_success(api.set_clock("2026-08-06T00:00:00Z", OPS))
        after = get_standing_order(order["id"], customer)
        assert after["status"] == "LOCKED", (
            "Once the clock's weekday passes change_cutoff_day the order is LOCKED")

    def test_locked_order_returns_to_confirmed_on_weekly_rollover(self, api):
        """PRD §2.5: "a `LOCKED` order returns to `CONFIRMED` on the weekly
        rollover into its next effective week."
        PRD §3.5: "When the week rolls over into the next effective week, a
        `LOCKED` order returns to `CONFIRMED` and may be edited again."

        Design: Difficulty/non_linear_state_machine/standing_order_confirm_lock_rollover_cycle
        """
        ws = setup_confirmed_order(name="Arugula", crop_category="PETITE_GREEN",
                                   qty_kg=1.0, listed_price_cents_per_kg=900,
                                   days_to_harvest=12,
                                   effective_week_start="2026-08-03",
                                   change_cutoff_day=2)
        order = ws["standing_order"]
        customer = ws["customer"]

        validate_success(api.set_clock("2026-08-06T00:00:00Z", OPS))
        locked = get_standing_order(order["id"], customer)
        assert locked["status"] == "LOCKED"

        # 2026-08-10 is the Monday of the next effective week.
        validate_success(api.set_clock("2026-08-10T00:00:00Z", OPS))
        rolled = get_standing_order(order["id"], customer)
        assert rolled["status"] == "CONFIRMED", (
            "The weekly rollover returns the LOCKED order to CONFIRMED")


class TestWeeklyChangeWindow:
    def test_line_change_after_cutoff_rejected_weekly_change_locked(self, api):
        """PRD §3.5: "then the temporal checks — if the logical clock has moved
        the order into `LOCKED` the add is rejected with
        `ERR_WEEKLY_CHANGE_LOCKED`"
        PRD §3.5: "From `CONFIRMED`, the calendar takes over: once the logical
        clock's weekday passes the order's `change_cutoff_day` relative to its
        `effective_week_start`, the system moves the order to `LOCKED` and no
        further line changes are accepted for that week."

        Design: Difficulty/resource_temporal_overlap/weekly_change_cutoff_window_lock
        """
        ws = setup_confirmed_order(name="Endive", crop_category="PETITE_GREEN",
                                   qty_kg=1.0, listed_price_cents_per_kg=950,
                                   days_to_harvest=14,
                                   effective_week_start="2026-08-03",
                                   change_cutoff_day=2)
        order = ws["standing_order"]
        customer = ws["customer"]

        # Friday of the effective week: weekday 4 > cutoff 2 -> LOCKED.
        validate_success(api.set_clock("2026-08-07T00:00:00Z", OPS))
        current = get_standing_order(order["id"], customer)
        assert current["status"] == "LOCKED"

        payload = add_order_line_payload(ws["variety"]["id"], 2.0, current["version"])
        resp = api.add_order_line(order["id"], payload,
                                  make_chef_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_WEEKLY_CHANGE_LOCKED)

    def test_line_change_on_cutoff_day_still_accepted(self, api):
        """PRD §3.5: "a `change_cutoff_day`, a day-of-week index running from 0
        for Monday to 6 for Sunday, after which weekly changes lock for the
        coming week."
        PRD §3.5: "once the logical clock's weekday passes the order's
        `change_cutoff_day` relative to its `effective_week_start`, the system
        moves the order to `LOCKED` and no further line changes are accepted
        for that week."

        Design: Difficulty/resource_temporal_overlap/weekly_change_cutoff_window_lock
        """
        ws = setup_confirmed_order(name="Endive", crop_category="PETITE_GREEN",
                                   qty_kg=1.0, listed_price_cents_per_kg=950,
                                   days_to_harvest=14,
                                   effective_week_start="2026-08-03",
                                   change_cutoff_day=2)
        order = ws["standing_order"]
        customer = ws["customer"]

        # Wednesday of the effective week IS the cutoff day (index 2); the
        # window closes only once the weekday passes the cutoff.
        validate_success(api.set_clock("2026-08-05T00:00:00Z", OPS))
        item = add_order_line(order["id"], customer, ws["variety"]["id"], 2.0)
        assert item["fulfillment"] == "PLANNED", (
            "On the cutoff day itself the change window is still open")
        assert item["line_extension_cents"] == 1900  # 2.0 kg * 950 c/kg


class TestOptimisticConcurrency:
    def test_stale_standing_order_version_rejected_on_line_add(self, api):
        """PRD §2.8: "Adding a weekly-change line to a standing order requires
        the request to carry `expected_standing_order_version`, holding the
        order's `version` as the client last observed it. If the order's
        current `version` has advanced past that value — because another write
        (a line add, a confirm) has landed since the client last read the order
        — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the
        client cannot overwrite an order state it never observed."

        Design: Corner/cross_cutting/stale_standing_order_version_rejected_on_line_add
        """
        variety = create_listed_variety(name="Thyme", crop_category="SPECIALTY_HERB",
                                        listed_price_cents_per_kg=2800,
                                        days_to_harvest=22,
                                        expected_yield_grams_per_tray=3000,
                                        min_order_grams=100)
        customer = create_customer(business_name="R9")
        order = create_standing_order(customer)
        stale_version = order["version"]  # observed at creation (1)

        add_order_line(order["id"], customer, variety["id"], 1.0)
        confirm_standing_order(order["id"], customer)
        # Two writes have landed since the client last observed the order.

        payload = add_order_line_payload(variety["id"], 2.0, stale_version)
        resp = api.add_order_line(order["id"], payload,
                                  make_chef_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_crop_plan_version_rejected_on_sow(self, api):
        """PRD §2.8: "Sowing a crop plan follows the same pattern: the sow
        request must carry `expected_crop_plan_version` matching the plan's
        current `version`. If the plan's version has advanced since the client
        last read it — for example because `planned_tray_count` or
        `seed_grams_required` was edited — the sow is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/stale_crop_plan_version_rejected_on_sow
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Oregano", crop_category="SPECIALTY_HERB",
                                        listed_price_cents_per_kg=2700,
                                        days_to_harvest=23,
                                        expected_yield_grams_per_tray=3000,
                                        min_order_grams=100)
        lot = create_released_seed_lot(variety["id"])
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        # The plan's current version is 1; a client presenting any other value
        # has not observed the current plan.
        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"] + 5},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
