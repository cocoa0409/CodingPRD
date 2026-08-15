"""Preorder campaign lifecycle: projections, lock fork, selector, bubble-ups."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_purchase_order,
    create_approved_vendor_with_quote,
    create_campaign,
    create_open_campaign,
    create_variant,
    create_vendor,
    get_campaign,
    get_program,
    get_variant,
    list_campaign_pos,
    lock_campaign,
    pay_preorder,
    place_paid_preorder,
    place_preorder,
    receive_po,
    set_clock,
    setup_campaign_fulfilling,
    setup_campaign_in_production,
    setup_open_campaign_shop,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestCampaignUnitsProvisionalVsFinal:
    def _setup_mixed_population(self, api):
        """OPEN campaign goal 10 price 2500 deposit 0.4; P1 M qty 6 PAID,
        P2 S qty 4 PAID, P3 M qty 2 left PLACED."""
        shop = setup_open_campaign_shop(
            goal_units=10,
            with_vendor=True,
            vendor_min_order_qty=2,
            vendor_unit_cost_cents=500,
        )
        program_id = shop["program"]["id"]
        campaign_id = shop["campaign"]["id"]
        design_id = shop["design"]["id"]
        variant_s = create_variant(
            program_id, design_id, size="S", unit_price_cents=2500
        )
        p1 = place_paid_preorder(
            program_id, campaign_id, shop["variant"]["id"], "cust-01", 6
        )
        p2 = place_paid_preorder(program_id, campaign_id, variant_s["id"], "cust-02", 4)
        p3 = place_preorder(
            program_id, campaign_id, shop["variant"]["id"], "cust-03", 2
        )
        assert p1["status"] == "PAID" and p2["status"] == "PAID"
        assert p3["status"] == "PLACED"
        return shop

    def test_provisional_placed_units_diverges_from_final_paid_units(self, api):
        """PRD §3.4: "`placed_units` is the provisional, forward-looking
        figure: the sum of `qty` over preorders in `PLACED`, `PAID`, or
        `FULFILLED`. `paid_units` is the final, lock-authoritative figure: the
        sum over preorders in `PAID` or `FULFILLED` only."

        Design: Difficulty/dual_variant_calc/campaign_units_provisional_vs_final
        """
        shop = self._setup_mixed_population(api)
        campaign = get_campaign(shop["campaign"]["id"])
        assert campaign["placed_units"] == 12, (
            f"provisional variant counts PLACED+PAID (6+4+2), got "
            f"{campaign['placed_units']}"
        )
        assert campaign["paid_units"] == 10, (
            f"final variant counts PAID only (6+4), got {campaign['paid_units']}"
        )

    def test_lock_consults_paid_units_alone(self, api):
        """PRD §3.4: "a campaign can display `placed_units` at or beyond its
        goal and still cancel at lock, because the lock consults `paid_units`
        alone."
        PRD §3.4: "If `paid_units` is at least `goal_units` — exact equality
        passes — the campaign advances to `IN_PRODUCTION` and the vendor quote
        selector runs"

        Design: Difficulty/dual_variant_calc/campaign_units_provisional_vs_final
        """
        shop = self._setup_mixed_population(api)
        locked = lock_campaign(shop["campaign"]["id"], "2026-09-01T00:00:00Z")
        assert locked["status"] == "IN_PRODUCTION", (
            "paid_units 10 >= goal 10 governs; the 2 unpaid PLACED units "
            "counted only by the provisional variant are ignored"
        )
        assert locked["selected_vendor_id"] == shop["vendor"]["id"]


class TestCampaignGoalBoundary:
    def test_paid_units_exactly_equal_goal_locks_into_production(self, api):
        """PRD §3.4: "If `paid_units` is at least `goal_units` — exact
        equality passes — the campaign advances to `IN_PRODUCTION` and the
        vendor quote selector runs"

        Design: Difficulty/boundary_precision_check/campaign_goal_exact_units_locks_into_production
        """
        shop = setup_campaign_in_production(
            goal_units=2, preorder_qty=2, vendor_min_order_qty=2
        )
        campaign = shop["campaign"]
        assert campaign["paid_units"] == 2
        assert campaign["goal_units"] == 2
        assert campaign["status"] == "IN_PRODUCTION", (
            "paid_units exactly equal to goal_units satisfies >= (not >)"
        )

    def test_paid_units_one_below_goal_cancels_at_lock(self, api):
        """PRD §3.4: "If `paid_units` falls short of `goal_units`, the lock
        instead drops the campaign to `CANCELLED`."

        Design: Difficulty/boundary_precision_check/campaign_goal_exact_units_locks_into_production
        """
        shop = setup_open_campaign_shop(
            goal_units=2, with_vendor=True, vendor_min_order_qty=2
        )
        place_paid_preorder(
            shop["program"]["id"],
            shop["campaign"]["id"],
            shop["variant"]["id"],
            "cust-01",
            1,
        )
        locked = lock_campaign(shop["campaign"]["id"], "2026-09-01T00:00:00Z")
        assert locked["status"] == "CANCELLED", (
            "paid_units 1 < goal 2 takes the goal-unmet branch"
        )


class TestCampaignBubbleUps:
    def test_campaign_auto_closes_when_last_preorder_fulfilled(self, api):
        """PRD §3.4: "When the last `PAID` preorder of a campaign is
        fulfilled, the campaign bubble-closes itself from `FULFILLING` to
        `CLOSED`."
        PRD §3.4: "`undistributed_profit_cents` grows by the line revenue
        (`unit_price_cents` times `qty`) minus the cost of goods (`qty` times
        the variant's `landed_unit_cost_cents`), minus the licensor's
        royalty"

        Design: Corner/state_machines/campaign_auto_closes_when_last_preorder_fulfilled
        """
        shop = setup_campaign_fulfilling(
            goal_units=1, preorder_qty=1, vendor_min_order_qty=1,
            vendor_unit_cost_cents=500,
        )
        assert shop["campaign"]["status"] == "FULFILLING"
        preorder = shop["preorders"][0]

        pay_preorder(
            preorder["id"], "BALANCE", preorder["balance_due_cents"], "cust-01"
        )
        fulfilled = validate_success(api.fulfill_preorder(preorder["id"], MANAGER), 200)
        assert fulfilled["status"] == "FULFILLED"

        assert get_campaign(shop["campaign"]["id"])["status"] == "CLOSED", (
            "bubble-up: the last PAID preorder fulfilled auto-closes the "
            "campaign with no explicit close call"
        )
        assert get_variant(shop["variant"]["id"])["on_hand_qty"] == 0, (
            "the auto PO delivered 1 unit; fulfillment consumed it"
        )
        assert get_program(shop["program"]["id"])["undistributed_profit_cents"] == 2000, (
            "2500 line revenue - 500 landed cost - 0 royalty"
        )

    def test_preorder_fulfill_before_fulfilling_rejected(self, api):
        """PRD §3.4: "A `StoreManager` then fulfills each `PAID` preorder (any
        other preorder state is `ERR_INVALID_STATE_TRANSITION`; a campaign not
        yet `FULFILLING` yields `ERR_CAMPAIGN_NOT_OPEN`)"

        Design: Corner/state_machines/preorder_fulfill_before_fulfilling_rejected
        """
        shop = setup_campaign_in_production(
            goal_units=1, preorder_qty=1, vendor_min_order_qty=1
        )
        assert shop["campaign"]["status"] == "IN_PRODUCTION"
        res = api.fulfill_preorder(shop["preorders"][0]["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN, 409)


class TestCampaignOpenAndLockGates:
    def test_duplicate_active_campaign_rejected(self, api):
        """PRD §3.4: "no other campaign of the same design is currently
        `OPEN`, `IN_PRODUCTION`, or `FULFILLING` (a clash is
        `ERR_DUPLICATE_ACTIVE_CAMPAIGN`)."
        PRD §3.4: "If `paid_units` falls short of `goal_units`, the lock
        instead drops the campaign to `CANCELLED`."

        Design: Corner/validations/duplicate_active_campaign_rejected
        """
        shop = setup_open_campaign_shop(goal_units=5, closes_at="2026-09-01T00:00:00Z")
        program_id = shop["program"]["id"]
        design_id = shop["design"]["id"]
        c1 = shop["campaign"]
        c2 = create_campaign(
            program_id,
            design_id,
            unit_price_cents=2000,
            deposit_pct=0.5,
            goal_units=3,
            closes_at="2026-09-15T00:00:00Z",
        )
        res = api.open_preorder_campaign(c2["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_CAMPAIGN, 409)

        cancelled = lock_campaign(c1["id"], "2026-09-01T00:00:00Z")
        assert cancelled["status"] == "CANCELLED", (
            "goal 5 unmet with 0 paid units at lock"
        )
        opened = validate_success(api.open_preorder_campaign(c2["id"], MANAGER), 200)
        assert opened["status"] == "OPEN", (
            "once no active sibling campaign remains, the second campaign "
            "opens"
        )

    def test_campaign_lock_before_window_close_rejected(self, api):
        """PRD §3.4: "Locking requires the campaign still `OPEN` (else
        `ERR_CAMPAIGN_NOT_OPEN`) and the logical clock at or past `closes_at`
        (else `ERR_CAMPAIGN_WINDOW_STILL_OPEN`)"

        Design: Corner/errors/campaign_lock_before_window_close_rejected
        """
        shop = setup_open_campaign_shop(
            goal_units=1, with_vendor=True, vendor_min_order_qty=1
        )
        place_paid_preorder(
            shop["program"]["id"],
            shop["campaign"]["id"],
            shop["variant"]["id"],
            "cust-89",
            1,
        )
        set_clock("2026-08-15T00:00:00Z")
        res = api.lock_preorder_campaign(shop["campaign"]["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_WINDOW_STILL_OPEN, 409)

    def test_lock_without_eligible_vendor_returns_no_vendor(self, api):
        """PRD §3.4: "If no vendor is eligible, the lock is refused with
        `ERR_NO_ELIGIBLE_VENDOR` and the campaign stays `OPEN`."

        Design: Corner/errors/lock_without_eligible_vendor_returns_no_vendor
        """
        shop = setup_open_campaign_shop(goal_units=1, with_vendor=False)
        place_paid_preorder(
            shop["program"]["id"],
            shop["campaign"]["id"],
            shop["variant"]["id"],
            "cust-81",
            1,
        )
        set_clock("2026-09-01T00:00:00Z")
        res = api.lock_preorder_campaign(shop["campaign"]["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_VENDOR, 422)
        assert get_campaign(shop["campaign"]["id"])["status"] == "OPEN", (
            "the failed selector leaves the campaign unchanged"
        )

    def test_selector_tiebreak_prefers_faster_vendor(self, api):
        """PRD §3.4: "eligible vendors are `APPROVED` vendors holding a quote
        on the campaign's design whose quote status is `ACTIVE`; eligible
        quotes rank by `unit_cost_cents` ascending, ties break by
        `production_days` ascending, remaining ties by the vendor's
        `created_at` ascending; the winner lands in `selected_vendor_id`."

        Design: Corner/calculations/selector_tiebreak_prefers_faster_vendor
        """
        shop = setup_open_campaign_shop(goal_units=1)
        program_id = shop["program"]["id"]
        design_id = shop["design"]["id"]
        vendor_a = create_approved_vendor_with_quote(
            program_id, design_id, unit_cost_cents=500, min_order_qty=1,
            production_days=10, name="SlowA",
        )
        vendor_b = create_approved_vendor_with_quote(
            program_id, design_id, unit_cost_cents=500, min_order_qty=1,
            production_days=5, name="FastB",
        )
        create_vendor(  # never approved: ineligible regardless of lower cost
            program_id,
            quotes=[],
            name="CheapC",
            contact_email="c@co.com",
        )
        place_paid_preorder(
            program_id, shop["campaign"]["id"], shop["variant"]["id"], "cust-01", 1
        )
        locked = lock_campaign(shop["campaign"]["id"], "2026-09-01T00:00:00Z")
        assert locked["status"] == "IN_PRODUCTION"
        assert locked["selected_vendor_id"] == vendor_b["id"], (
            "cost tie 500 == 500 is broken by production_days 5 < 10, NOT by "
            "creation order (SlowA was created first)"
        )
        pos = list_campaign_pos(shop["campaign"]["id"])
        assert len(pos) == 1
        assert pos[0]["vendor_id"] == vendor_b["id"]
        assert pos[0]["unit_cost_cents"] == 500


class TestPoReceiptTriggersCampaignFulfillment:
    def test_lock_auto_creates_submitted_purchase_orders(self, api):
        """PRD §3.4: "For every variant of the design whose paid demand is
        greater than zero, the lock auto-creates a purchase order:
        `campaign_id` set, `vendor_id` set to the selected vendor,
        `qty_ordered` equal to the larger of the variant's paid demand and the
        winning quote's `min_order_qty`, `unit_cost_cents` captured from that
        quote, status `SUBMITTED`, and `auto_created` true."

        Design: Difficulty/transitive_cascade/po_receipt_triggers_campaign_fulfillment
        """
        shop = setup_campaign_in_production(
            goal_units=2, preorder_qty=2, vendor_min_order_qty=2,
            vendor_unit_cost_cents=500,
        )
        pos = shop["pos"]
        assert len(pos) == 1, f"exactly one variant had paid demand, got {len(pos)} POs"
        po = pos[0]
        assert_purchase_order(po)
        assert po["auto_created"] is True
        assert po["qty_ordered"] == 2, "max(paid demand 2, min_order_qty 2)"
        assert po["unit_cost_cents"] == 500
        assert po["status"] == "SUBMITTED"
        assert po["vendor_id"] == shop["vendor"]["id"]
        assert po["campaign_id"] == shop["campaign"]["id"]

    def test_final_receipt_advances_campaign_to_fulfilling(self, api):
        """PRD §3.5: "a receipt bringing the total exactly equal to
        `qty_ordered` completes the order as `RECEIVED`. Completion fires one
        more effect: when the finished order carries a `campaign_id` and every
        purchase order of that campaign has reached `RECEIVED`, the campaign
        auto-advances from `IN_PRODUCTION` to `FULFILLING`."
        PRD §3.5: "Every receipt adds `qty` to `qty_received` and to the
        variant's `on_hand_qty`, and recomputes the variant's landed cost"

        Design: Difficulty/transitive_cascade/po_receipt_triggers_campaign_fulfillment
        """
        shop = setup_campaign_in_production(
            goal_units=2, preorder_qty=2, vendor_min_order_qty=2,
            vendor_unit_cost_cents=500,
        )
        po = shop["pos"][0]
        received = receive_po(po["id"], 2)
        assert received["status"] == "RECEIVED", (
            "qty_received 2 == qty_ordered 2 completes the order"
        )

        variant = get_variant(shop["variant"]["id"])
        assert variant["on_hand_qty"] == 2
        assert variant["landed_unit_cost_cents"] == 500, (
            "licensing fee 0 amortizes to nothing: 500 + round_half_up(0/2)"
        )
        assert get_campaign(shop["campaign"]["id"])["status"] == "FULFILLING", (
            "all campaign POs RECEIVED auto-advances the campaign"
        )
