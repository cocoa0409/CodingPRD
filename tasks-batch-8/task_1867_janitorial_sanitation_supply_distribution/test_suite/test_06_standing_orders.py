"""Standing orders: activation preview, the pause/resume cycle, item
uniqueness, the suspension conditional cascade, award repricing, and the
auto-replenishment engine inside the daily sweep."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_standing_order,
    award_bid,
    bid_to_under_review,
    create_contract_bid,
    create_product,
    create_standing_order,
    get_standing_order,
    make_facility_manager_headers,
    order_line,
    pause_standing_order,
    resume_standing_order,
    run_daily,
    setup_active_standing_order,
    setup_facility_with_product,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


class TestActivationPreview:
    def test_activate_computes_merchandise_preview(self, api):
        """PRD: "it produces the first commercial preview:
        `next_delivery_total_cents` is recomputed as a merchandise-only
        preview, the sum over items of each quantity times the product's
        current effective unit price (contract pricing included, per §3.8)"

        Design: Difficulty/non_linear_state_machine/standing_order_pause_resume_cycle
        """
        _facility, _product, so = setup_active_standing_order(
            qty=2, base_price_cents=1000, next_run_date="2026-08-03T00:00:00Z")
        assert so["status"] == "ACTIVE"
        assert so["next_delivery_total_cents"] == 2000, (
            "2 x 1000 at base price with no awarded bid")
        assert so["price_protected"] is False

    def test_pause_resume_cycle_repeatable(self, api):
        """PRD: "From `ACTIVE`, a pause moves the standing order to `PAUSED`
        with `pause_reason` `MANUAL`; a resume requires the facility to be
        `ACTIVE`, returns it to `ACTIVE` with `pause_reason` cleared to
        `NONE`, and refreshes the `next_delivery_total_cents` preview."

        Design: Difficulty/non_linear_state_machine/standing_order_pause_resume_cycle
        """
        facility, _product, so = setup_active_standing_order(
            qty=2, base_price_cents=1000, next_run_date="2026-08-03T00:00:00Z")
        paused = pause_standing_order(so["id"], facility)
        assert paused["status"] == "PAUSED"
        assert paused["pause_reason"] == "MANUAL"

        resumed = resume_standing_order(so["id"], facility)
        assert resumed["status"] == "ACTIVE"
        assert resumed["pause_reason"] == "NONE"

        paused_again = pause_standing_order(so["id"], facility)
        assert paused_again["status"] == "PAUSED", "The cycle is repeatable"
        assert paused_again["pause_reason"] == "MANUAL"


class TestStandingOrderItemUniqueness:
    def test_duplicate_standing_order_returns_error(self, api):
        """PRD: "A facility may not hold two standing orders in `DRAFT`,
        `ACTIVE`, or `PAUSED` status that share any item product; such a
        create is rejected with `ERR_DUPLICATE_STANDING_ORDER`."

        Design: Corner/validations/duplicate_standing_order_returns_error
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AK", qty_on_hand=500)
        create_standing_order(
            facility, [order_line(product["id"], 1)], frequency="WEEKLY",
            next_run_date="2026-08-03T00:00:00Z")
        payload = {
            "facility_id": facility["id"],
            "items": [{"product_id": product["id"], "qty": 2}],
            "frequency": "MONTHLY",
            "next_run_date": "2026-09-01T00:00:00Z",
        }
        resp = api.create_standing_order(
            payload, make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STANDING_ORDER)


class TestFacilitySuspensionCascade:
    def test_facility_suspend_resume_conditional_cascade(self, api):
        """PRD: "Suspending a facility — an `ACTIVE` → `SUSPENDED` transition
        available to a `DistributorAdmin` — ripples into its replenishment
        program: every standing order of the facility currently `ACTIVE` is
        moved to `PAUSED` with `pause_reason` set to `SUSPENSION`, while
        standing orders paused manually and those still in `DRAFT` are left
        untouched. Reinstatement performs the mirror-image conditional
        cascade: a `SUSPENDED` → `ACTIVE` transition flips only the
        suspension-paused standing orders back to `ACTIVE` and clears their
        `pause_reason` to `NONE`, while manually paused standing orders stay
        `PAUSED`."

        Design: Corner/state_machines/facility_suspend_resume_conditional_cascade
        """
        facility, product_one = setup_facility_with_product(
            facility_name="Fac Y", qty_on_hand=500)
        product_two = create_product(sku="SKU-Y2", name="Y2",
                                     category="EQUIPMENT",
                                     base_price_cents=2000,
                                     unit_of_measure="EACH", qty_on_hand=500)
        so_a = create_standing_order(
            facility, [order_line(product_one["id"], 1)],
            frequency="WEEKLY", next_run_date="2026-08-03T00:00:00Z")
        so_b = create_standing_order(
            facility, [order_line(product_two["id"], 1)],
            frequency="MONTHLY", next_run_date="2026-09-01T00:00:00Z")
        activate_standing_order(so_a["id"], facility)
        activate_standing_order(so_b["id"], facility)
        pause_standing_order(so_b["id"], facility)

        validate_success(api.suspend_facility(facility["id"], ADMIN))
        after_suspend_a = get_standing_order(so_a["id"])
        after_suspend_b = get_standing_order(so_b["id"])
        assert after_suspend_a["status"] == "PAUSED"
        assert after_suspend_a["pause_reason"] == "SUSPENSION"
        assert after_suspend_b["status"] == "PAUSED", (
            "The manually paused standing order is untouched by suspension")
        assert after_suspend_b["pause_reason"] == "MANUAL"

        validate_success(api.reinstate_facility(facility["id"], ADMIN))
        after_reinstate_a = get_standing_order(so_a["id"])
        after_reinstate_b = get_standing_order(so_b["id"])
        assert after_reinstate_a["status"] == "ACTIVE"
        assert after_reinstate_a["pause_reason"] == "NONE"
        assert after_reinstate_b["status"] == "PAUSED", (
            "The manually paused standing order stays PAUSED across the "
            "suspend-and-reinstate round trip")
        assert after_reinstate_b["pause_reason"] == "MANUAL"


class TestAwardRepriceCascade:
    def test_award_reprices_protected_standing_order(self, api):
        """PRD: "Award, termination, and expiry all cascade to the
        standing-order base: every standing order in `ACTIVE` or `PAUSED`
        status whose facility's group matches the bid's
        `facility_group_code` recomputes `price_protected` and
        `next_delivery_total_cents`, with bid prices applying to covered items
        on award and ceasing to apply on termination or expiry."

        Design: Corner/state_machines/award_reprices_protected_standing_order
        """
        facility, product, so = setup_active_standing_order(
            qty=2, base_price_cents=1000, facility_group_code="GPO-6")
        assert so["next_delivery_total_cents"] == 2000
        bid = create_contract_bid(product, facility_group_code="GPO-6",
                                  bid_price_cents=800, bid_reference="BID-Z",
                                  protection_start="2026-07-01T00:00:00Z",
                                  protection_end="2026-12-31T00:00:00Z")
        bid_to_under_review(bid)
        award_bid(bid["id"])
        after = get_standing_order(so["id"])
        assert after["price_protected"] is True
        assert after["next_delivery_total_cents"] == 1600, (
            "2 x 800 at the awarded bid price")


class TestAutoReplenishment:
    def test_due_standing_order_generates_placed_order(self, api):
        """PRD: "Every `ACTIVE` standing order whose `next_run_date` is on or
        before the current clock time generates a real order — `source`
        `STANDING_ORDER`, its `standing_order_id` pointing back at the
        generator, priced with the standing order's `fuel_index` — and
        attempts to place it through the full placement pipeline of §3.6."
        PRD: "Fifth and last, the auto-replenishment engine of §3.5 generates
        orders from due `ACTIVE` standing orders and places them, recomputing
        each facility's `committed_cents` for every generated order."

        Design: Difficulty/transitive_cascade/ops_run_due_generates_order_depth2
        """
        facility, _product, so = setup_active_standing_order(
            qty=4, base_price_cents=1000, qty_on_hand=500,
            next_run_date="2026-08-01T00:00:00Z", fuel_index=3.00)
        summary = run_daily()
        assert summary["generated_count"] == 1
        orders, meta = validate_paginated(api.list_orders(
            ADMIN, params={"standing_order_id": so["id"]}))
        assert meta["total_count"] == 1
        generated = orders[0]
        assert generated["status"] == "PLACED"
        assert generated["source"] == "STANDING_ORDER"
        assert generated["standing_order_id"] == so["id"]
        assert generated["total_cents"] == 5300, (
            "subtotal 4000 + fee 1000 + surcharge round(5000 * 0.06 * 1.0) "
            "= 300 at fuel_index 3.00")

    def test_generated_order_commits_facility_and_advances_run_date(self, api):
        """PRD: "Either way, success or failure, the `next_run_date` advances
        by the frequency interval: 7 days for `WEEKLY`, 14 days for
        `BIWEEKLY`, 30 days for `MONTHLY`."
        PRD: "placement adds the new order's total to `committed_cents`"

        Design: Difficulty/transitive_cascade/ops_run_due_generates_order_depth2
        """
        facility, _product, so = setup_active_standing_order(
            qty=4, base_price_cents=1000, qty_on_hand=500,
            next_run_date="2026-08-01T00:00:00Z", fuel_index=3.00)
        run_daily()
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 5300
        after = get_standing_order(so["id"])
        assert after["next_run_date"].startswith("2026-08-08T00:00:00"), (
            "WEEKLY advances the due date by 7 days from 2026-08-01")

    def test_run_daily_second_run_generates_nothing(self, api):
        """PRD: "Either way, success or failure, the `next_run_date` advances
        by the frequency interval: 7 days for `WEEKLY`, 14 days for
        `BIWEEKLY`, 30 days for `MONTHLY`."
        PRD: "Every `ACTIVE` standing order whose `next_run_date` is on or
        before the current clock time generates a real order"

        Design: Corner/endpoints/run_daily_second_run_generates_nothing
        """
        _facility, _product, so = setup_active_standing_order(
            qty=1, base_price_cents=1000, qty_on_hand=500,
            next_run_date="2026-08-01T00:00:00Z", fuel_index=2.5)
        first = run_daily()
        assert first["generated_count"] == 1
        second = run_daily()
        assert second["generated_count"] == 0, (
            "The advanced next_run_date is no longer due, so the second "
            "sweep generates nothing")
        after = get_standing_order(so["id"])
        assert after["next_run_date"].startswith("2026-08-08T00:00:00"), (
            "The due date advanced exactly once across both sweeps")
