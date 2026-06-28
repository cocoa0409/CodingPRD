"""Second-chance drawings & entries: empty-pool boundary, inclusive entry vs.
exclusive run window, cancel conservation, earliest-entered winner selection,
and OCC stale-drawing-version rejection.

Covers difficulty boundary_precision_check (empty pool), resource_temporal_overlap
(entry-deadline inclusive resource window), compensating_invariant (cancel conserves
eligible count), plus run/entry/OCC corner instances.
"""
from test_helpers import (
    api_client, validate_success, validate_error, officer_headers,
    create_game, setup_active_retailer_with_terminal, create_open_drawing,
    sell_and_validate_winner, sell_and_validate_nonwinner, enter_ticket,
    drawing_version, set_clock, setup_drawing_with_eligible_entry, ApiErrorId,
    TEST_USERS,
)

OFF = TEST_USERS["lottery_officer_headers"]
CLERK = TEST_USERS["claims_clerk_headers"]


class TestEmptyPoolBoundary:
    def test_run_empty_drawing_rejected(self, api):
        """PRD 3.9: "that the `entry_count` be at least 1 (an empty pool cannot be drawn,
        else `ERR_EMPTY_DRAWING_POOL`)."

        Design: Difficulty/boundary_precision_check/empty_second_chance_pool_run_rejected
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        drawing = create_open_drawing(game["id"], entry_deadline="2026-02-01T00:00:00Z")
        set_clock("2026-02-02T00:00:00Z")  # past deadline
        dv = drawing_version(drawing["id"])
        resp = api.run_drawing(drawing["id"], {"expected_drawing_version": dv}, OFF)
        validate_error(resp, ApiErrorId.ERR_EMPTY_DRAWING_POOL.value)
        assert validate_success(api.get_drawing(drawing["id"], OFF))["status"] == "OPEN"

    def test_run_nonempty_drawing_succeeds(self, api):
        """PRD 3.9: "A run is permitted only while the drawing is `OPEN`; it further
        requires that the logical clock be strictly past the `entry_deadline` (a drawing
        cannot be drawn before its entries close, else `ERR_DRAWING_NOT_CLOSED`) and that
        the `entry_count` be at least 1 (an empty pool cannot be drawn, else
        `ERR_EMPTY_DRAWING_POOL`)."

        Design: Difficulty/boundary_precision_check/empty_second_chance_pool_run_rejected
        """
        ctx = setup_drawing_with_eligible_entry(entry_deadline="2026-02-01T00:00:00Z",
                                                pre_entry_clock="2026-01-10T00:00:00Z")
        set_clock("2026-02-02T00:00:00Z")
        dv = drawing_version(ctx["drawing"]["id"])
        data = validate_success(
            api.run_drawing(ctx["drawing"]["id"], {"expected_drawing_version": dv}, OFF))
        assert data["status"] == "DRAWN", data["status"]


class TestEntryDeadlineWindow:
    def test_entry_at_deadline_succeeds_but_run_rejected(self, api):
        """PRD 3.9: "An entry is accepted only when the ticket's `second_chance_status` is
        `ELIGIBLE`, the drawing's `status` is `OPEN`, and the logical clock is at or before
        the drawing's `entry_deadline`"
        PRD 3.9: "it further requires that the logical clock be strictly past the
        `entry_deadline` (a drawing cannot be drawn before its entries close, else
        `ERR_DRAWING_NOT_CLOSED`)"

        Design: Difficulty/resource_temporal_overlap/second_chance_entry_deadline_inclusive_resource_window
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal()
        drawing = create_open_drawing(game["id"], entry_deadline="2026-02-01T00:00:00Z")
        set_clock("2026-01-10T00:00:00Z")
        ticket = sell_and_validate_nonwinner(game["id"], term["id"],
                                             draw_date="2026-01-10T00:00:00Z")
        set_clock("2026-02-01T00:00:00Z")  # exactly the entry_deadline
        entry = enter_ticket(drawing["id"], ticket["id"])  # inclusive: succeeds
        dv = drawing_version(drawing["id"])
        resp = api.run_drawing(drawing["id"], {"expected_drawing_version": dv}, OFF)
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_CLOSED.value)
        e = validate_success(api.get_entry(entry["id"], OFF))
        assert e["outcome"] == "PENDING", e["outcome"]
        d = validate_success(api.get_drawing(drawing["id"], OFF))
        assert d["entry_count"] == 1, d["entry_count"]

    def test_run_before_deadline_rejected_drawing_not_closed(self, api):
        """PRD 3.9: "it further requires that the logical clock be strictly past the
        `entry_deadline` (a drawing cannot be drawn before its entries close, else
        `ERR_DRAWING_NOT_CLOSED`)"

        Design: Difficulty/resource_temporal_overlap/second_chance_entry_deadline_inclusive_resource_window
        """
        ctx = setup_drawing_with_eligible_entry(entry_deadline="2026-02-01T00:00:00Z",
                                                pre_entry_clock="2026-01-10T00:00:00Z")
        # clock still before deadline (left at pre-entry clock)
        dv = drawing_version(ctx["drawing"]["id"])
        resp = api.run_drawing(ctx["drawing"]["id"], {"expected_drawing_version": dv}, OFF)
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_CLOSED.value)


class TestCancelConservation:
    def test_cancel_releases_entry_back_to_eligible(self, api):
        """PRD 3.9: "Cancellation releases every entry back to eligibility: each entry's
        `outcome` stays `PENDING`, and each entered ticket's `second_chance_status` moves
        `ENTERED → ELIGIBLE` so it may be entered into another drawing."

        Design: Difficulty/compensating_invariant/cancel_drawing_conserves_eligible_ticket_count
        """
        ctx = setup_drawing_with_eligible_entry(entry_deadline="2026-03-01T00:00:00Z",
                                                pre_entry_clock="2026-01-10T00:00:00Z")
        data = validate_success(api.cancel_drawing(ctx["drawing"]["id"], OFF))
        assert data["status"] == "CANCELLED", data["status"]
        t = validate_success(api.get_ticket(ctx["ticket"]["id"], OFF))
        assert t["second_chance_status"] == "ELIGIBLE", t["second_chance_status"]
        e = validate_success(api.get_entry(ctx["entry"]["id"], OFF))
        assert e["outcome"] == "PENDING", e["outcome"]

    def test_entering_ticket_sets_status_entered(self, api):
        """PRD 3.9: "the ticket's `second_chance_status` moves `ELIGIBLE → ENTERED`, and
        the drawing's `entry_count` is incremented."

        Design: Difficulty/compensating_invariant/cancel_drawing_conserves_eligible_ticket_count
        """
        ctx = setup_drawing_with_eligible_entry(entry_deadline="2026-03-01T00:00:00Z",
                                                pre_entry_clock="2026-01-10T00:00:00Z")
        t = validate_success(api.get_ticket(ctx["ticket"]["id"], OFF))
        assert t["second_chance_status"] == "ENTERED", t["second_chance_status"]


class TestRunSelection:
    def test_run_selects_earliest_entered_winner(self, api):
        """PRD 3.9: "among the drawing's entries it picks the one with the earliest
        `entered_at`, breaking any tie by the entry's `created_at` ascending — never by
        `id`. The drawing moves `OPEN → DRAWN`, its `winning_entry_id` is set to the
        selected entry's `id`, and the cascade fires: the selected entry's `outcome`
        becomes `WON` and its ticket's `second_chance_status` moves
        `ENTERED → DRAWN_WINNER`, while every other entry's `outcome` becomes `LOST` and
        each of those tickets' `second_chance_status` moves `ENTERED → DRAWN_LOSER`."

        Design: Corner/endpoints/run_drawing_selects_earliest_entered_winner
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000,
                           claim_window_days=60)
        ret, term = setup_active_retailer_with_terminal()
        drawing = create_open_drawing(game["id"], entry_deadline="2026-02-01T00:00:00Z")
        set_clock("2026-01-10T00:00:00Z")
        tkA = sell_and_validate_nonwinner(game["id"], term["id"], draw_date="2026-01-10T00:00:00Z")
        enA = enter_ticket(drawing["id"], tkA["id"])
        set_clock("2026-01-11T00:00:00Z")
        tkB = sell_and_validate_nonwinner(game["id"], term["id"], draw_date="2026-01-11T00:00:00Z")
        enB = enter_ticket(drawing["id"], tkB["id"])
        set_clock("2026-02-02T00:00:00Z")
        dv = drawing_version(drawing["id"])
        data = validate_success(api.run_drawing(drawing["id"], {"expected_drawing_version": dv}, OFF))
        assert data["status"] == "DRAWN", data["status"]
        assert data["winning_entry_id"] == enA["id"], data["winning_entry_id"]
        assert validate_success(api.get_entry(enA["id"], OFF))["outcome"] == "WON"
        assert validate_success(api.get_entry(enB["id"], OFF))["outcome"] == "LOST"
        assert validate_success(api.get_ticket(tkA["id"], OFF))["second_chance_status"] == "DRAWN_WINNER"
        assert validate_success(api.get_ticket(tkB["id"], OFF))["second_chance_status"] == "DRAWN_LOSER"

    def test_entry_into_winner_ticket_not_eligible(self, api):
        """PRD 3.9: "An entry is accepted only when the ticket's `second_chance_status` is
        `ELIGIBLE`, the drawing's `status` is `OPEN`, and the logical clock is at or before
        the drawing's `entry_deadline`; if any of these fails, the entry is rejected with
        `ERR_ENTRY_NOT_ELIGIBLE`."

        Design: Corner/validations/entry_into_winner_ticket_not_eligible
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal()
        drawing = create_open_drawing(game["id"], entry_deadline="2026-03-01T00:00:00Z")
        set_clock("2026-01-05T00:00:00Z")
        winner = sell_and_validate_winner(game["id"], term["id"], gross_prize_cents=1000000,
                                          draw_date="2026-01-10T00:00:00Z")
        resp = api.create_entry({"drawing_id": drawing["id"], "ticket_id": winner["id"]}, CLERK)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_ELIGIBLE.value)


class TestDrawingOCC:
    def test_stale_drawing_version_run_rejected(self, api):
        """PRD 2.5: "if the drawing's `version` has advanced since then — because an entry
        was added or the drawing was already run — the client's view of the candidate pool
        is stale, `expected_drawing_version` no longer matches the drawing's current
        `version`, and the run is rejected with `ERR_STALE_VERSION` (HTTP 412) so it cannot
        select a winner over an outdated entry set."

        Design: Corner/errors/error_stale_version_on_drawing_run
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000,
                           claim_window_days=60)
        ret, term = setup_active_retailer_with_terminal()
        drawing = create_open_drawing(game["id"], entry_deadline="2026-02-01T00:00:00Z")
        stale_v = drawing["version"]  # observed before any entry bumps it
        set_clock("2026-01-10T00:00:00Z")
        tk = sell_and_validate_nonwinner(game["id"], term["id"], draw_date="2026-01-10T00:00:00Z")
        enter_ticket(drawing["id"], tk["id"])  # bumps drawing version
        set_clock("2026-02-02T00:00:00Z")
        resp = api.run_drawing(drawing["id"], {"expected_drawing_version": stale_v}, OFF)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        assert validate_success(api.get_drawing(drawing["id"], OFF))["status"] == "OPEN"
