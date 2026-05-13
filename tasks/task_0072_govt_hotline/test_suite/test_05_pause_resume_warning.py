"""Pause/resume lifecycle, pause_accumulated_seconds invariant, and
read-time warning_state recomputation.

PRD §3.6, §3.8, §3.13.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA, DISP,
    advance_clock,
    classify,
    dispatch,
    find_lead_assignment,
    get_work_order,
    make_department_handler_headers,
    pause,
    pause_work_order_payload,
    register_work_order,
    resume,
    setup_in_progress,
    setup_paused_with_seconds,
    setup_routing_world,
    validate_error,
    validate_success,
)


# ===========================================================================
# Pause/resume lifecycle (PRD §3.6)
# ===========================================================================
class TestPauseResume:
    """PRD §3.6: 'The pause endpoint expects a reason (between 1 and
    500 characters) and is permitted only when the work order's
    pause_started_at is null (the case is not already paused) and the
    acting handler is the lead assignment's current handler_id.'"""

    def test_pause_sets_pause_started_at(self, api):
        """PRD §3.6: 'they set the work order's pause_started_at to the
        same instant.'"""
        world = setup_in_progress()
        before = world["work_order"]
        assert before["pause_started_at"] in (None, "")
        pause(world["work_order"]["id"], handler=world["lead_handler"])
        after = get_work_order(world["work_order"]["id"])
        assert after["pause_started_at"] not in (None, "")

    def test_pause_when_already_paused_rejected(self, api):
        """PRD §3.6: 'A pause attempted while the work order is already
        paused fails priority-11 with ERR_ALREADY_PAUSED.'"""
        world = setup_in_progress()
        pause(world["work_order"]["id"], handler=world["lead_handler"])
        resp = api.pause_work_order(
            world["work_order"]["id"],
            pause_work_order_payload(reason="again"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_PAUSED.value)

    def test_resume_when_not_paused_rejected(self, api):
        """PRD §3.6: 'If the work order is not currently paused, resume
        fails priority-10 with ERR_NOT_PAUSED.'"""
        world = setup_in_progress()
        resp = api.resume_work_order(
            world["work_order"]["id"],
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_PAUSED.value)

    def test_pause_resume_pauses_pause_accumulated_seconds(self, api):
        """PRD §3.6: 'The work order's pause_accumulated_seconds is
        increased by that same duration.'

        After pause(1800s)+resume, pause_accumulated_seconds is 1800.
        """
        world = setup_paused_with_seconds(pause_seconds=1800)
        wo = world["work_order"]
        assert wo["pause_accumulated_seconds"] == 1800

    def test_pause_resume_pause_again_accumulates(self, api):
        """PRD §3.13: 'pause_accumulated_seconds is exactly equal to
        the sum of duration_seconds across its ClarificationPause rows
        whose resumed_at is not null'."""
        world = setup_in_progress()
        wo_id = world["work_order"]["id"]
        handler = world["lead_handler"]
        pause(wo_id, handler=handler)
        advance_clock(1800)
        resume(wo_id, handler=handler)
        pause(wo_id, handler=handler)
        advance_clock(1800)
        resume(wo_id, handler=handler)
        wo = get_work_order(wo_id)
        assert wo["pause_accumulated_seconds"] == 3600


# ===========================================================================
# Warning state (PRD §3.8)
# ===========================================================================
class TestWarningState:
    """PRD §3.8: 'A work order's warning_state is the single field that
    summarises how close the case is to breaching its deadline; it is
    recomputed on read by the retrieval endpoint and again on every
    sweep.'"""

    def test_fresh_workorder_warning_state_is_none(self, api):
        """PRD §3.8: 'Otherwise the state is NONE.' A freshly classified
        WO with full deadline ahead is NONE."""
        world = setup_routing_world(committed_hours=4, statutory_hours=8)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        wo_after = get_work_order(wo["id"])
        assert wo_after["warning_state"] == "NONE"

    def test_yellow_at_exact_25_percent_remaining(self, api):
        """PRD §3.8: 'when pct is less than or equal to 0.25 — meaning
        25% or less of the committed window remains — the state is
        YELLOW... a case with pct exactly equal to 0.25 is YELLOW (not
        NONE).'

        With committed_hours=4 and the clock advanced by 3 business
        hours (so remaining = 1 business hour, total = 4), pct = 0.25.
        """
        world = setup_routing_world(committed_hours=4, statutory_hours=8)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        advance_clock(3 * 3600)
        wo_after = get_work_order(wo["id"])
        assert wo_after["warning_state"] == "YELLOW", (
            f"Expected YELLOW at pct=0.25; got {wo_after['warning_state']}"
        )

    def test_red_when_pct_zero_at_committed_deadline(self, api):
        """PRD §3.8: 'a case where the server time is exactly equal to
        the committed deadline has pct equal to 0 and lands in RED (not
        BREACHED — BREACHED requires the strict greater-than past the
        statutory deadline).'"""
        world = setup_routing_world(committed_hours=4, statutory_hours=8)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        advance_clock(4 * 3600)
        wo_after = get_work_order(wo["id"])
        assert wo_after["warning_state"] == "RED"

    def test_breached_when_clock_past_statutory_deadline(self, api):
        """PRD §3.8: 'When the current server time is strictly greater
        than the statutory deadline, the state is BREACHED.'"""
        world = setup_routing_world(committed_hours=4, statutory_hours=8)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        # Advance past 8 business hours (= one full business day plus a bit).
        advance_clock(9 * 3600 + 60 * 60 * 24)
        wo_after = get_work_order(wo["id"])
        assert wo_after["warning_state"] == "BREACHED"
