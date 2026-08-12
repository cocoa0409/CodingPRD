"""Box assembly: sub-lot scheduling, window overlap, capacity, completion."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_assembly_line,
    create_assembly_line_payload,
    create_sub_lot_payload,
    create_submitted_box_order,
    get_success_data,
    slot_and_complete_box_line,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


class TestSubLotWindowOverlap:
    def _line_with_sub_lot_a(self, api):
        env = create_submitted_box_order(price_level="L3", qty=30, unit_price=50000)
        assembly_line = create_assembly_line(
            line_code="AL-W", capacity_minutes_per_day=2000,
            standard_minutes_per_box=30, setup_minutes_per_sub_lot=20,
        )
        sub_a = get_success_data(
            api.create_sub_lot(
                create_sub_lot_payload(
                    env["line"]["id"], assembly_line["id"],
                    scheduled_date="2026-05-03", start_minute=60, qty=10,
                ),
                PLANNER,
            )
        )
        return env, assembly_line, sub_a

    def test_adjacent_sub_lot_accepted_under_half_open_semantics(self, api):
        """PRD §3.6: "The sub-lot's half-open window — start minute inclusive, end
        minute exclusive — must not overlap any non-cancelled sub-lot on the same
        assembly line and date; adjacency is explicitly allowed, so one sub-lot's
        start may equal another's end."
        PRD §3.6: "Work content is computed at scheduling: `work_minutes` is the
        sub-lot `qty` multiplied by the line's `standard_minutes_per_box`, plus one
        charge of `setup_minutes_per_sub_lot`."

        Design: Difficulty/resource_temporal_overlap/assembly_line_half_open_window_adjacency
        """
        env, assembly_line, sub_a = self._line_with_sub_lot_a(api)
        # work = 10 x 30 + 20 = 320 -> A occupies [60, 380).
        assert sub_a["work_minutes"] == 320
        assert sub_a["end_minute"] == 380
        sub_b = validate_success(
            api.create_sub_lot(
                create_sub_lot_payload(
                    env["line"]["id"], assembly_line["id"],
                    scheduled_date="2026-05-03", start_minute=380, qty=10,
                ),
                PLANNER,
            ),
            201,
        )
        assert sub_b["start_minute"] == 380
        assert sub_b["end_minute"] == 700, "adjacency at 380 must be allowed"
        line = validate_success(api.get_order_line(env["line"]["id"], PLANNER))
        assert line["slotted_qty"] == 20

    def test_overlapping_sub_lot_rejected_one_minute_early(self, api):
        """PRD §3.6: "An overlapping placement is rejected with
        `ERR_LINE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/assembly_line_half_open_window_adjacency
        """
        env, assembly_line, _sub_a = self._line_with_sub_lot_a(api)
        # [379, 549) intersects A's [60, 380) by one minute.
        resp = api.create_sub_lot(
            create_sub_lot_payload(
                env["line"]["id"], assembly_line["id"],
                scheduled_date="2026-05-03", start_minute=379, qty=5,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_OVERLAP)
        line = validate_success(api.get_order_line(env["line"]["id"], PLANNER))
        assert line["slotted_qty"] == 10, "a rejected sub-lot must not consume line capacity"


class TestLineDayCapacity:
    def test_line_day_capacity_exact_fit_then_overflow(self, api):
        """PRD §3.6: "And the aggregate line-day load — the sum of `work_minutes`
        over all non-cancelled sub-lots on the same assembly line and date,
        including the new sub-lot — must not exceed `capacity_minutes_per_day`; an
        exact tie at capacity is allowed, and a true excess is rejected with
        `ERR_LINE_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/calculations/line_day_capacity_exact_fit_then_overflow
        """
        env = create_submitted_box_order(price_level="L3", qty=20, unit_price=50000)
        assembly_line = create_assembly_line(
            line_code="AL-T", capacity_minutes_per_day=320,
            standard_minutes_per_box=30, setup_minutes_per_sub_lot=20,
        )
        first = validate_success(
            api.create_sub_lot(
                create_sub_lot_payload(
                    env["line"]["id"], assembly_line["id"],
                    scheduled_date="2026-05-03", start_minute=60, qty=10,
                ),
                PLANNER,
            ),
            201,
        )
        # work = 10 x 30 + 20 = 320 -> exactly at the 320-minute capacity.
        assert first["work_minutes"] == 320
        assert first["end_minute"] == 380
        # A further 1-box sub-lot would add 50 minutes -> 370 > 320.
        resp = api.create_sub_lot(
            create_sub_lot_payload(
                env["line"]["id"], assembly_line["id"],
                scheduled_date="2026-05-03", start_minute=380, qty=1,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED)


class TestSubLotGates:
    def test_sublot_qty_exceeds_remaining_line_qty(self, api):
        """PRD §3.6: "The sub-lot quantity must not exceed the line's `qty` minus
        the quantity already slotted by other non-cancelled sub-lots covering the
        line; exceeding that remainder is rejected with
        `ERR_SUB_LOT_QTY_EXCEEDS_LINE` (HTTP 402)."

        Design: Corner/validations/sublot_qty_exceeds_remaining_line_qty
        """
        env = create_submitted_box_order(price_level="L3", qty=5, unit_price=50000)
        assembly_line = create_assembly_line(line_code="AL-1")
        get_success_data(
            api.create_sub_lot(
                create_sub_lot_payload(
                    env["line"]["id"], assembly_line["id"],
                    scheduled_date="2026-05-03", start_minute=60, qty=4,
                ),
                PLANNER,
            )
        )
        # Only 5 - 4 = 1 box remains; 2 is too many.
        resp = api.create_sub_lot(
            create_sub_lot_payload(
                env["line"]["id"], assembly_line["id"],
                scheduled_date="2026-05-03", start_minute=300, qty=2,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_SUB_LOT_QTY_EXCEEDS_LINE)

    def test_schedule_date_in_past_rejected(self, api):
        """PRD §2.6: "Any `scheduled_date` on a nesting run or sub-lot, and any
        `route_date` on a delivery route, that falls before the logical clock's
        current date is rejected with `ERR_SCHEDULE_DATE_IN_PAST` (HTTP 422)."

        Design: Corner/validations/schedule_date_in_past_rejected
        """
        env = create_submitted_box_order(price_level="L3", qty=5, unit_price=50000)
        assembly_line = create_assembly_line(line_code="AL-1")
        # The logical clock starts at 2026-05-01; 2026-04-30 is in the past.
        resp = api.create_sub_lot(
            create_sub_lot_payload(
                env["line"]["id"], assembly_line["id"],
                scheduled_date="2026-04-30", start_minute=60, qty=5,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_DATE_IN_PAST)

    def test_assembly_line_inactive_rejected(self, api):
        """PRD §3.6: "an inactive line rejects new sub-lots with
        `ERR_ASSEMBLY_LINE_INACTIVE` (HTTP 422)."

        Design: Corner/validations/assembly_line_inactive_rejected
        """
        env = create_submitted_box_order(price_level="L3", qty=5, unit_price=50000)
        assembly_line = get_success_data(
            api.create_assembly_line(
                create_assembly_line_payload(line_code="AL-OFF", capacity_minutes_per_day=480,
                                             active=False),
                ADMIN,
            )
        )
        resp = api.create_sub_lot(
            create_sub_lot_payload(
                env["line"]["id"], assembly_line["id"],
                scheduled_date="2026-05-03", start_minute=60, qty=5,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_ASSEMBLY_LINE_INACTIVE)

    def test_sublot_on_draft_order_rejected(self, api):
        """PRD §3.6: "The covered line's order must be in `SUBMITTED` or
        `IN_PRODUCTION` (`ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION`)."

        Design: Corner/validations/sublot_on_draft_order_rejected
        """
        from test_helpers import (
            create_box_line_payload,
            create_dealer,
            create_draft_order,
            create_finish,
            make_dealer_headers,
        )

        dealer = create_dealer(price_level="L3")
        finish = create_finish(upcharge_pct=0.0)
        order = create_draft_order(dealer)  # deliberately never submitted
        line = get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=5),
                make_dealer_headers(dealer["id"]),
            )
        )
        assembly_line = create_assembly_line(line_code="AL-1")
        resp = api.create_sub_lot(
            create_sub_lot_payload(
                line["id"], assembly_line["id"],
                scheduled_date="2026-05-03", start_minute=60, qty=5,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION)


class TestSubLotCompletion:
    def test_complete_sublot_twice_rejected(self, api):
        """PRD §3.6: "Completing a sub-lot requires it to be `SCHEDULED`, else
        `ERR_SUB_LOT_NOT_COMPLETABLE` (HTTP 409), and moves it to `COMPLETE`."

        Design: Corner/state_machines/complete_sublot_twice_rejected
        """
        env = create_submitted_box_order(price_level="L3", qty=5, unit_price=50000)
        result = slot_and_complete_box_line(env["line"])
        resp = api.complete_sub_lot(result["sub_lot"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_SUB_LOT_NOT_COMPLETABLE)
