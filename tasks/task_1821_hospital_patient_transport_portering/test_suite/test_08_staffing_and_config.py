"""Staffing adequacy (FORECAST/REPLAY), demand-curve and travel-edge config."""
from test_helpers import (
    SUP,
    ApiErrorId,
    add_covering_shift,
    add_demand_curve,
    add_transporter,
    cancel_shift,
    create_demand_curve_payload,
    create_location,
    create_travel_edge,
    create_travel_edge_payload,
    get_adequacy,
    setup_staffing_adequacy_scenario,
    setup_staffing_demand_rows,
    validate_error,
    validate_success,
)


class TestStaffingDualVariant:
    def test_forecast_required_transporters(self, api):
        """PRD §3.8: "Under `FORECAST`, the system derives the day type from
        the date — Monday through Friday map to `WEEKDAY`, Saturday and Sunday
        to `WEEKEND` — and for each block in the window multiplies each
        priority's `expected_requests` by its `mean_service_minutes`, sums the
        three products into total expected service minutes for the block,
        divides by 60, and rounds up to a whole headcount."
        PRD §3.8: "The response reports `required_transporters`,
        `scheduled_transporters`, and their difference as `gap`, so a negative
        gap names exactly how thin coverage runs."

        Design: Difficulty/dual_variant_calc/staffing_required_forecast_vs_replay
        """
        setup_staffing_adequacy_scenario()

        # 2026-08-03 is a Monday (WEEKDAY): block 9 ceil(510/60) = 9, block 10
        # ceil(204/60) = 4, summed to 13.
        forecast = get_adequacy("2026-08-03", 9, 2, "FORECAST")
        assert forecast["required_transporters"] == 13
        assert forecast["scheduled_transporters"] == 3
        assert forecast["gap"] == -10

    def test_replay_required_transporters_empty_history(self, api):
        """PRD §3.8: "Under `REPLAY`, each block instead looks at requests
        completed within the trailing 24 hours whose `created_at` hour matches
        the block, sums their actual service minutes — `completed_at` minus
        `at_pickup_at` — divides by 60, and rounds up; a block with no matching
        completions requires zero transporters."

        Design: Difficulty/dual_variant_calc/staffing_required_forecast_vs_replay
        """
        setup_staffing_adequacy_scenario()

        # Same window, but nothing has ever completed in the trailing 24h.
        replay = get_adequacy("2026-08-03", 9, 2, "REPLAY")
        assert replay["required_transporters"] == 0
        assert replay["scheduled_transporters"] == 3
        assert replay["gap"] == 3


class TestPerBlockCeiling:
    def test_perblock_ceil_then_sum(self, api):
        """PRD §3.8: "In both variants the rounding order is pinned: the
        ceiling is taken per block first, and only then are the per-block
        integers summed — summing first and rounding once is a different,
        incorrect algorithm."

        Design: Difficulty/combinatorial_formula/staffing_perblock_ceil_then_sum
        """
        setup_staffing_demand_rows()

        one_block = get_adequacy("2026-08-03", 9, 1, "FORECAST")
        assert one_block["required_transporters"] == 9, "ceil(510 / 60)"

        two_blocks = get_adequacy("2026-08-03", 9, 2, "FORECAST")
        assert two_blocks["required_transporters"] == 13, (
            "9 + ceil(204 / 60) = 9 + 4, per-block ceilings summed; "
            "sum-then-round would give ceil(714 / 60) = 12")

    def test_weekend_date_uses_weekend_rows(self, api):
        """PRD §3.8: "Under `FORECAST`, the system derives the day type from
        the date — Monday through Friday map to `WEEKDAY`, Saturday and Sunday
        to `WEEKEND`"

        Design: Difficulty/combinatorial_formula/staffing_perblock_ceil_then_sum
        """
        setup_staffing_demand_rows()

        # 2026-08-02 is a Sunday: only WEEKDAY rows exist, so both blocks
        # require zero.
        weekend = get_adequacy("2026-08-02", 9, 2, "FORECAST")
        assert weekend["required_transporters"] == 0
        assert weekend["scheduled_transporters"] == 0
        assert weekend["gap"] == 0


class TestScheduledHeadcount:
    def test_staffing_scheduled_excludes_cancelled(self, api):
        """PRD §3.8: "The scheduled side of the ledger counts distinct
        `transporter_id` values across `PLANNED` shifts that cover any block in
        the window — a shift covers a block when it starts before the block's
        end and ends after the block's start, half-open semantics throughout —
        unioned across all blocks; cancelled shifts never count."

        Design: Corner/calculations/staffing_scheduled_excludes_cancelled
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        ta = add_transporter("T A", hub["id"])
        tb = add_transporter("T B", hub["id"])
        tc = add_transporter("T C", hub["id"])
        add_covering_shift(ta["id"], "2026-08-04T08:00:00Z",
                           "2026-08-04T12:00:00Z")
        add_covering_shift(tb["id"], "2026-08-04T08:00:00Z",
                           "2026-08-04T12:00:00Z")
        sc = add_covering_shift(tc["id"], "2026-08-04T08:00:00Z",
                                "2026-08-04T12:00:00Z")
        cancel_shift(sc["id"])

        # 2026-08-04 is a Tuesday; no demand rows exist, so required is 0.
        adequacy = get_adequacy("2026-08-04", 9, 1, "FORECAST")
        assert adequacy["required_transporters"] == 0
        assert adequacy["scheduled_transporters"] == 2, (
            "T C's cancelled shift is excluded from the count")
        assert adequacy["gap"] == 2


class TestConfigValidation:
    def test_adequacy_window_out_of_range_returns_400(self, api):
        """PRD §3.8: "the window must be sane — `window_hours` at least 1 and
        `hour_block` plus `window_hours` at most 24, else `ERR_VALIDATION`."

        Design: Corner/validations/adequacy_window_out_of_range_returns_400
        """
        resp = api.get_staffing_adequacy(
            SUP, params={"date": "2026-08-03", "hour_block": 22,
                         "window_hours": 3, "variant": "FORECAST"})
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_demand_curve_conflict_returns_409(self, api):
        """PRD §3.8: "The triple of `day_type`, `hour_block`, and `priority` is
        unique, and a colliding row is rejected with
        `ERR_DEMAND_CURVE_CONFLICT`."

        Design: Corner/validations/demand_curve_conflict_returns_409
        """
        add_demand_curve("WEEKDAY", 9, "STAT", 2, 30)
        resp = api.create_demand_curve(
            create_demand_curve_payload("WEEKDAY", 9, "STAT", 5, 25), SUP)
        validate_error(resp, ApiErrorId.ERR_DEMAND_CURVE_CONFLICT)

    def test_travel_edge_duplicate_returns_409(self, api):
        """PRD §3.1: "The directed pair is unique: a second edge with the same
        origin and destination is rejected with `ERR_TRAVEL_EDGE_DUPLICATE`."

        Design: Corner/validations/travel_edge_duplicate_returns_409
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        create_travel_edge(ward["id"], img["id"], 10, 16)

        resp = api.create_travel_edge(
            create_travel_edge_payload(ward["id"], img["id"], 12, 18), SUP)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_EDGE_DUPLICATE)


class TestDemandCurveCreation:
    def test_demand_curve_created_fields(self, api):
        """PRD §3.8: "Supervisors teach the system expected demand one
        **Demand Curve** row at a time: a `day_type` of `WEEKDAY` or `WEEKEND`,
        an `hour_block` from 0 to 23, a `priority`, an `expected_requests`
        volume of zero or more, and a positive `mean_service_minutes`."

        Design: Corner/validations/demand_curve_conflict_returns_409
        """
        resp = api.create_demand_curve(
            create_demand_curve_payload("WEEKEND", 14, "ROUTINE", 3, 45), SUP)
        data = validate_success(resp, 201)
        assert data["day_type"] == "WEEKEND"
        assert data["hour_block"] == 14
        assert data["priority"] == "ROUTINE"
        assert data["expected_requests"] == 3
        assert data["mean_service_minutes"] == 45
