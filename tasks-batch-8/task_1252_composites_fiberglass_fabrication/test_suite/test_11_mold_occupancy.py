"""Mold occupancy: closed-interval semantics across demold instants."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_work_order_payload,
    demold,
    set_clock,
    setup_work_order_cured,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

LAM = TEST_USERS["laminator_headers"]
SM = TEST_USERS["shop_manager_headers"]


class TestMoldOccupancyClosedInterval:
    def _setup_demolded_at(self, api):
        """WO-O1 processed through demold with the clock held at exactly
        2026-06-02T10:00:00Z; WO-O2 released against the same mold."""
        ctx = setup_work_order_cured(
            mold_overrides={"mold_code": "MOLD-O1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-O1"},
            batch_overrides={"batch_code": "BATCH-O1"},
        )
        set_clock("2026-06-02T10:00:00Z")
        demold(ctx, 2000.0)
        wo2 = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    ctx["mold"]["id"],
                    ctx["ply_book"]["id"],
                    work_order_no="WO-O2",
                ),
                SM,
            ),
            201,
        )
        return ctx, wo2

    def test_start_exactly_at_demold_instant_conflicts(self, api):
        """PRD §2.9: "The interval from `layup_started_at` to `demolded_at` on a
        work order is a closed interval: the tool is occupied from the instant
        layup starts through the instant the part leaves the tool, inclusive of
        both endpoints. A new layup may begin only when no other work order on the
        same mold has `layup_started_at` set with `demolded_at` still null, and
        when the current logical time is strictly later than every prior occupant's
        `demolded_at` — a start exactly coincident with a previous demold is a
        conflict, reported as `ERR_MOLD_OCCUPANCY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/mold_occupancy_closed_interval_touching_demold_instant
        """
        _, wo2 = self._setup_demolded_at(api)
        # Clock is still at exactly WO-O1's demold instant.
        res = api.start_layup(wo2["id"], LAM)
        validate_error(res, ApiErrorId.ERR_MOLD_OCCUPANCY_CONFLICT, expected_status=409)

    def test_start_one_second_after_demold_admitted(self, api):
        """PRD §2.9: "when the current logical time is strictly later than every
        prior occupant's `demolded_at` — a start exactly coincident with a previous
        demold is a conflict". One second past the demold instant is strictly
        later, so the same transition succeeds and stamps `layup_started_at`.
        PRD §3.4: "A successful start stamps `layup_started_at` from the logical
        clock — occupancy of the tool begins at that instant — and moves the work
        order from `RELEASED` to `LAYUP_IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/mold_occupancy_closed_interval_touching_demold_instant
        """
        _, wo2 = self._setup_demolded_at(api)
        set_clock("2026-06-02T10:00:01Z")
        started = validate_success(api.start_layup(wo2["id"], LAM), 200)
        assert started["status"] == "LAYUP_IN_PROGRESS"
        assert started["layup_started_at"] is not None
