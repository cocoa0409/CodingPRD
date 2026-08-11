"""Nesting station changeover-buffer window semantics (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_dealer,
    create_door_style,
    create_draft_order,
    create_finish,
    create_nesting_run_payload,
    create_sheet_component,
    create_station,
    add_door_line,
    get_success_data,
    make_dealer_headers,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]


class TestChangeoverBuffer:
    def _station_with_run_a(self, api):
        dealer = create_dealer(price_level="L3")
        style = create_door_style(construction="SLAB", base_list_price_cents=15000)
        finish = create_finish(upcharge_pct=0.0)
        component = create_sheet_component(on_hand_qty=100)
        station = create_station(changeover_minutes=30, station_code="ST-B")
        lines = []
        for _ in range(2):
            order = create_draft_order(dealer)
            line = add_door_line(order, style, finish, qty=2, unit_price=10000)
            get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
            lines.append(line)
        run_a = get_success_data(
            api.create_nesting_run(
                create_nesting_run_payload(
                    station["id"], component["id"], [lines[0]["id"]],
                    scheduled_date="2026-05-02", start_minute=60, end_minute=240,
                ),
                PLANNER,
            )
        )
        return station, component, lines, run_a

    def test_run_starting_exactly_at_end_plus_changeover_accepted(self, api):
        """PRD §3.5: "CNC cutting capacity is organized around nesting stations,
        each registered with a unique `station_code`, a non-negative
        `changeover_minutes` buffer that must separate consecutive runs on the
        station, and an `active` flag defaulting to true; an inactive station
        rejects new runs with `ERR_STATION_INACTIVE` (HTTP 422)."
        PRD §3.5: "Against every other `DRAFT` or `RELEASED` run on the same
        station and date, the new run must clear the other run by the station's
        changeover buffer: either the new run's start minute is no earlier than
        the other run's end minute plus the buffer, or the new run's end minute
        plus the buffer is no later than the other run's start minute."

        Design: Difficulty/resource_temporal_overlap/nesting_station_changeover_buffer_overlap
        """
        station, component, lines, _run_a = self._station_with_run_a(api)
        # Run A occupies [60, 240); buffer 30 -> B may start at 240 + 30 = 270.
        resp = api.create_nesting_run(
            create_nesting_run_payload(
                station["id"], component["id"], [lines[1]["id"]],
                scheduled_date="2026-05-02", start_minute=270, end_minute=400,
            ),
            PLANNER,
        )
        run_b = validate_success(resp, 201)
        assert run_b["status"] == "DRAFT"
        assert run_b["start_minute"] == 270

    def test_run_one_minute_inside_changeover_buffer_rejected(self, api):
        """PRD §3.5: "A window that fails to clear any such neighbor is rejected
        with `ERR_STATION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/nesting_station_changeover_buffer_overlap
        """
        station, component, lines, _run_a = self._station_with_run_a(api)
        # 269 < 240 + 30: the buffer is not cleared even though [269, 400) does
        # not geometrically intersect A's [60, 240).
        resp = api.create_nesting_run(
            create_nesting_run_payload(
                station["id"], component["id"], [lines[1]["id"]],
                scheduled_date="2026-05-02", start_minute=269, end_minute=400,
            ),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STATION_WINDOW_OVERLAP)
