"""Order cancellation: tiered fees, the pre-PRESSING gate, slot freeing with
the backlog round-trip, and the waitlist promotion waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_order,
    create_customer,
    create_order,
    create_plating_bath,
    create_press_line,
    create_queued_order,
    create_release,
    get_order,
    press_run,
    quote_order,
    schedule_order,
    set_clock,
    setup_world,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CSR, OPERATOR


class TestCancellationFees:
    def test_cancellation_fee_tier_zero_and_ten_pct(self, api):
        """PRD §3.3: "The fee scales with sunk work, and the resulting
        `cancel_fee_cents` is recorded on the order: cancelling from `DRAFT` or
        `QUOTED` is free; from `CONFIRMED` the fee is ten percent of
        `quote_total_cents`, rounded half-up; from `TOOLING` or
        `AWAITING_TP_APPROVAL` it is twenty-five percent; from `QUEUED` or
        `SCHEDULED` it is fifty percent. Any positive fee automatically creates
        a `CANCELLATION_FEE` invoice in `ISSUED` status whose gross and net
        both equal the fee with zero discount, moving the order's billing
        dimension from `UNBILLED` to `INVOICED`."

        Design: Corner/calculations/cancellation_fee_tier_zero_and_ten_pct
        """
        world = setup_world(with_line=False, with_bath=False)
        rel = world["release"]

        # DRAFT cancel: free, no invoice.
        o1 = create_order(rel["id"], quantity_ordered=1000)
        r1 = api.cancel_press_order(o1["id"], {"reason": "early"}, CSR)
        c1 = validate_success(r1, 200)
        assert c1["production_status"] == "CANCELLED"
        assert c1["cancel_fee_cents"] == 0
        inv1, _m = validate_paginated(
            api.list_invoices(CSR, params={"press_order_id": o1["id"]})
        )
        assert inv1 == [], "a free DRAFT cancellation must create no invoice"

        # CONFIRMED cancel: 10% of quote_total 448420 -> 44842.
        o2 = create_order(rel["id"], quantity_ordered=1000)
        o2 = quote_order(o2)
        o2 = confirm_order(o2, world["customer"]["id"])
        r2 = api.cancel_press_order(o2["id"], {"reason": "post-confirm"}, CSR)
        c2 = validate_success(r2, 200)
        assert c2["cancel_fee_cents"] == 44842
        assert c2["billing_status"] == "INVOICED"
        inv2, _m = validate_paginated(
            api.list_invoices(CSR, params={"press_order_id": o2["id"]})
        )
        assert len(inv2) == 1
        assert inv2[0]["kind"] == "CANCELLATION_FEE"
        assert inv2[0]["net_cents"] == 44842
        assert inv2[0]["gross_cents"] == 44842
        assert inv2[0]["discount_cents"] == 0
        assert inv2[0]["status"] == "ISSUED"

    def test_cancel_at_pressing_rejected(self, api):
        """PRD §3.3: "Cancellation is a `CustomerServiceRep` action available
        from any pre-`PRESSING` state — attempting it once the order is
        `PRESSING`, `QC_REVIEW`, or beyond is rejected with
        `ERR_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/cancel_at_pressing_rejected
        """
        world = setup_world()
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], world["line"]["id"],
                               planned_units=1000)
        # Advance the clock to the slot date and start pressing.
        set_clock("2026-08-10T00:00:00Z")
        started = validate_success(
            api.post_production_event(order["id"], {"event": "START_PRESSING"},
                                      OPERATOR),
            200,
        )
        assert started["production_status"] == "PRESSING"

        resp = api.cancel_press_order(order["id"], {"reason": "too late"}, CSR)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

        current = get_order(order["id"])
        assert current["production_status"] == "PRESSING"
        invoices, _m = validate_paginated(
            api.list_invoices(CSR, params={"press_order_id": order["id"]})
        )
        assert invoices == [], "a rejected cancel must create no fee invoice"


class TestSlotFreeingRoundTrip:
    def _scheduled_order(self, world):
        staged = create_queued_order(world, quantity_ordered=1000)
        return schedule_order(staged["order"], world["line"]["id"],
                              planned_units=1000)

    def test_line_hours_book_free_roundtrip(self, api):
        """PRD §3.6: "Booked hours total the lengths of the line's unfreed
        `PRODUCTION` slots dated today or later, plus one changeover hour for
        every adjacent pair of different-family slots on the same date."
        PRD §3.3: "Cancelling a `SCHEDULED` order additionally releases its
        `PRODUCTION` slots — marked `freed` and excluded from all capacity
        math"

        Design: Difficulty/compensating_invariant/line_hours_book_free_roundtrip
        """
        world = setup_world(line_over={"line_code": "L9", "tonnage_class": "HEAVY"})
        line_id = world["line"]["id"]

        before = validate_success(api.get_line_backlog(line_id, CSR), 200)
        assert before["booked_hours"] == 0

        order = self._scheduled_order(world)
        committed = validate_success(api.get_line_backlog(line_id, CSR), 200)
        assert committed["booked_hours"] == 8

        validate_success(
            api.cancel_press_order(order["id"], {"reason": "label pulled"}, CSR), 200
        )
        after = validate_success(api.get_line_backlog(line_id, CSR), 200)
        assert after["booked_hours"] == 0, (
            "the cancel must restore booked hours exactly (compensating round-trip)"
        )

        slots = validate_success(api.list_order_slots(order["id"], CSR), 200)
        assert len(slots) == 1
        assert slots[0]["freed"] is True, (
            "the released slot must be retained as a freed audit row"
        )

    def test_cancel_fee_invoice_shadow(self, api):
        """PRD §3.3: "from `QUEUED` or `SCHEDULED` it is fifty percent. Any
        positive fee automatically creates a `CANCELLATION_FEE` invoice in
        `ISSUED` status whose gross and net both equal the fee with zero
        discount"

        Design: Difficulty/compensating_invariant/line_hours_book_free_roundtrip
        """
        world = setup_world(line_over={"line_code": "L9", "tonnage_class": "HEAVY"})
        order = self._scheduled_order(world)
        resp = api.cancel_press_order(order["id"], {"reason": "label pulled"}, CSR)
        cancelled = validate_success(resp, 200)
        # 50% of the 448420 quote total.
        assert cancelled["cancel_fee_cents"] == 224210
        invoices, _m = validate_paginated(
            api.list_invoices(CSR, params={"press_order_id": order["id"]})
        )
        assert len(invoices) == 1
        assert invoices[0]["kind"] == "CANCELLATION_FEE"
        assert invoices[0]["net_cents"] == 224210


class TestWaitlistPromotion:
    def _setup_gold_scheduled_plat_queued(self):
        set_clock()
        cust_gold = create_customer(name="TC3 Gold", contact_email="g@x.com",
                                    credit_limit_cents=100000000,
                                    discount_tier="GOLD")
        cust_plat = create_customer(name="TC3 Plat", contact_email="p@x.com",
                                    credit_limit_cents=100000000,
                                    discount_tier="PLATINUM")
        rel1 = create_release(cust_gold["id"], catalog_number="TC3-A",
                              title="TA", release_date="2026-12-01")
        rel2 = create_release(cust_plat["id"], catalog_number="TC3-B",
                              title="TB", release_date="2026-08-25")
        line = create_press_line()
        bath = create_plating_bath()
        w1 = {"customer": cust_gold, "release": rel1, "line": line, "bath": bath}
        w2 = {"customer": cust_plat, "release": rel2, "line": line, "bath": bath}
        o1 = create_queued_order(w1, quantity_ordered=800)["order"]
        o1 = schedule_order(o1, line["id"], start_hour=0, end_hour=8,
                            planned_units=800)
        o2 = create_queued_order(w2, quantity_ordered=1000)["order"]
        return w1, w2, o1, o2

    def test_cancel_scheduled_fee_and_slot_freed(self, api):
        """PRD §3.3: "from `QUEUED` or `SCHEDULED` it is fifty percent. Any
        positive fee automatically creates a `CANCELLATION_FEE` invoice in
        `ISSUED` status whose gross and net both equal the fee with zero
        discount"
        PRD §3.3: "Cancelling a `SCHEDULED` order additionally releases its
        `PRODUCTION` slots — marked `freed` and excluded from all capacity
        math — and triggers the waitlist promotion waterfall described in
        §3.6."

        Design: Difficulty/transitive_cascade/cancel_frees_slots_waitlist_promotion_cascade
        """
        _w1, _w2, o1, _o2 = self._setup_gold_scheduled_plat_queued()
        # GOLD quote for 800 BLACK 180g: subtotal 388455, 5% discount 19423,
        # total 369032; 50% cancel fee = 184516.
        resp = api.cancel_press_order(o1["id"], {"reason": "label pulled"}, CSR)
        cancelled = validate_success(resp, 200)
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 184516

        invoices, _m = validate_paginated(
            api.list_invoices(CSR, params={"press_order_id": o1["id"]})
        )
        assert len(invoices) == 1
        assert invoices[0]["kind"] == "CANCELLATION_FEE"
        assert invoices[0]["net_cents"] == 184516

        slots = validate_success(api.list_order_slots(o1["id"], CSR), 200)
        assert slots[0]["freed"] is True

    def test_waitlist_promotes_platinum_order(self, api):
        """PRD §3.6: "The candidate pool is every order in `QUEUED` —
        regardless of repress history — except the cancelled one. Candidates
        rank by customer tier weight descending (`PLATINUM` weighs 40, `GOLD`
        30, `SILVER` 20, `STANDARD` 10), ties broken by the order's
        `created_at` ascending and then by `intake_seq` ascending, never by
        identifier. Scanning in that rank order, a candidate is promoted
        exactly when its required hours — its `quantity_ordered` divided by the
        hourly rate of the freed window's line, rounded up — fit inside one
        single freed window on that line and date; a promoted order receives a
        new `PRODUCTION` slot covering exactly those required hours from the
        window's start, the freed remainder shrinks accordingly, the candidate
        moves `QUEUED` → `SCHEDULED`, its release risk is recomputed with cause
        `SCHEDULE`, and the scan continues against the remaining windows."

        Design: Difficulty/transitive_cascade/cancel_frees_slots_waitlist_promotion_cascade
        """
        _w1, w2, o1, o2 = self._setup_gold_scheduled_plat_queued()
        validate_success(
            api.cancel_press_order(o1["id"], {"reason": "label pulled"}, CSR), 200
        )

        promoted = get_order(o2["id"])
        assert promoted["production_status"] == "SCHEDULED", (
            "the PLATINUM queued order must absorb the freed 8h window"
        )
        slots = validate_success(api.list_order_slots(o2["id"], CSR), 200)
        assert len(slots) == 1
        slot = slots[0]
        assert slot["slot_kind"] == "PRODUCTION"
        assert slot["date"] == "2026-08-10"
        # ceil(1000 / ceil(5000/16)) = ceil(1000/313) = 4 required hours from
        # the freed window's start.
        assert slot["start_hour"] == 0
        assert slot["end_hour"] == 4
        assert slot["freed"] is False

        rel = validate_success(api.get_release(w2["release"]["id"], CSR), 200)
        # Projected completion is the day after the slot (2026-08-11) against
        # the 2026-08-25 street date: slack 14 days is ON_TRACK.
        assert rel["projected_completion_date"] == "2026-08-11"
        assert rel["slack_days"] == 14
        assert rel["risk_level"] == "ON_TRACK"
