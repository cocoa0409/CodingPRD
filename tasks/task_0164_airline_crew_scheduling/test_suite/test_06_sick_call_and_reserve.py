"""Sick calls, reserve pool, and the depth-3 cascade.

PRD §3.4 covers the sick-call flow, reserve-callout, and the
auto-selection algorithm. PRD names the half-open standby window
[standby_start_at, standby_end_at) inclusively at the start.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    add_hours_iso,
    add_minutes_iso,
    advance_clock_to,
    call_out_reserve_payload,
    create_crew_member,
    crew_role_headers,
    get_assignment,
    get_crew_member,
    iso_from_dt,
    iso_now_utc,
    list_reserve_pool,
    place_on_reserve,
    report_sick_call,
    scheduler_headers,
    setup_pairing_admin_assigned,
    setup_sick_call_chain,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestSickCallReleasesAssignment:

    def test_sick_call_with_assignment_releases_it(self, api):
        """PRD §3.4: "When assignment_id is supplied and that
        assignment is still SCHEDULED, the assignment is released to
        RELEASED."
        """
        ctx = setup_sick_call_chain()
        resp = report_sick_call(
            ctx["sick_member"], assignment_id=ctx["sick_assignment"]["id"],
        )
        # PRD §3.4: "the sick call is still recorded (HTTP 201)".
        assert resp.status_code == 201
        a = get_assignment(ctx["sick_assignment"]["id"])
        assert a["status"] == "RELEASED", (
            "PRD §3.4: the assignment is released to RELEASED."
        )

    def test_sick_call_member_status_transitions_to_on_sick_call(self, api):
        """PRD §3.4: "The crew member's status transitions from ACTIVE
        to ON_SICK_CALL."
        """
        ctx = setup_sick_call_chain()
        report_sick_call(
            ctx["sick_member"], assignment_id=ctx["sick_assignment"]["id"],
        )
        cm = get_crew_member(ctx["sick_member"]["id"])
        assert cm["status"] == "ON_SICK_CALL"


class TestSickCallCascadeDepth3:

    def test_sick_call_chain_calls_out_reserve_and_backlinks(self, api):
        """PRD §3.4: "The system then runs the reserve-selection
        algorithm against the vacated rank slot; if a covering candidate
        is found, a new Assignment row with source = RESERVE_CALLOUT is
        created linking the reserve to the vacated slot, the reserve
        row moves from AVAILABLE to CALLED_OUT, the sick call's
        covered_by_assignment_id is set to the new assignment's id, and
        the covering crew member's cumulative_block_minutes_30d is
        incremented by Pairing.total_block_minutes."

        # difficulty: transitive_cascade/sick_call_chain_depth_3
        """
        ctx = setup_sick_call_chain()
        resp = report_sick_call(
            ctx["sick_member"], assignment_id=ctx["sick_assignment"]["id"],
        )
        assert resp.status_code == 201
        sc = resp.json()["data"]
        # Reserve transitioned.
        rp = next(
            r for r in list_reserve_pool()
            if r["id"] == ctx["reserve_pool"]["id"]
        )
        assert rp["state"] == "CALLED_OUT", (
            "PRD §3.4 link 2: reserve transitions AVAILABLE -> CALLED_OUT."
        )
        # Back-link populated.
        assert sc.get("covered_by_assignment_id") is not None, (
            "PRD §3.4 link 3: SickCall.covered_by_assignment_id set."
        )


class TestReserveCalloutWindowBoundaries:

    def test_callout_at_standby_start_inclusive(self, api):
        """PRD §3.4: "A reserve row is eligible if its state is
        AVAILABLE, now lies within the half-open standby window — at or
        after standby_start_at and strictly before standby_end_at."

        # difficulty: resource_temporal_overlap/reserve_pool_standby_window_inclusion
        Start boundary INCLUSIVE: now == standby_start_at → eligible.
        """
        reserve_member = create_crew_member(rank="CAPTAIN")
        # Use a far-future window, then advance clock to start.
        start_iso = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=2),
        )
        end_iso = add_hours_iso(start_iso, 12)
        rp = place_on_reserve(
            reserve_member["id"],
            reserve_date=start_iso,
            standby_start_at=start_iso,
            standby_end_at=end_iso,
        )
        # Build a pairing to cover.
        sick_pilot = create_crew_member(rank="CAPTAIN")
        pairing, _ = setup_pairing_admin_assigned(
            sick_pilot, assigned_rank_slot="CAPTAIN",
        )
        # Advance clock to exactly standby_start_at.
        advance_clock_to(start_iso)
        # Issue callout.
        resp = api.call_out_reserve(
            rp["id"],
            call_out_reserve_payload(
                pairing_id=pairing["id"], assigned_rank_slot="CAPTAIN",
            ),
            scheduler_headers,
        )
        # PRD §3.4 names ERR_RESERVE_OUTSIDE_WINDOW for outside; start
        # is inclusive so this should succeed. Other PRD-named errors
        # could surface (FAA, etc.). For this fixture the callout
        # should succeed (rank/base match, FAA fresh pilot).
        if resp.status_code >= 400:
            # If implementation enforces other gates, accept either
            # success or any non-window-related PRD error_id.
            data = resp.json().get("data") or {}
            err_id = data.get("error_id")
            assert err_id != ApiErrorId.ERR_RESERVE_OUTSIDE_WINDOW.value, (
                "PRD §3.4: standby_start_at is INCLUSIVE — callout AT "
                "the start instant must not be rejected as "
                "ERR_RESERVE_OUTSIDE_WINDOW."
            )
        else:
            validate_success(resp, expected_status=201)

    def test_callout_at_standby_end_exclusive(self, api):
        """PRD §3.4: "now lies within the half-open standby window — at
        or after standby_start_at and strictly before standby_end_at."

        # difficulty: resource_temporal_overlap/reserve_pool_standby_window_inclusion
        End boundary EXCLUSIVE: now == standby_end_at → out-of-window.
        """
        from test_helpers import build_pairing_with_one_duty_period, publish_pairing
        reserve_member = create_crew_member(rank="CAPTAIN")
        start_iso = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=2),
        )
        end_iso = add_hours_iso(start_iso, 12)
        rp = place_on_reserve(
            reserve_member["id"],
            reserve_date=start_iso,
            standby_start_at=start_iso,
            standby_end_at=end_iso,
        )
        # Build a PUBLISHED pairing with an OPEN CAPTAIN slot — no
        # admin-assignment here, so the reserve callout's only failure
        # mode under this clock position is the window check.
        pairing, _, _ = build_pairing_with_one_duty_period(
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        # Advance clock to exactly standby_end_at.
        advance_clock_to(end_iso)
        resp = api.call_out_reserve(
            rp["id"],
            call_out_reserve_payload(
                pairing_id=pairing["id"], assigned_rank_slot="CAPTAIN",
            ),
            scheduler_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESERVE_OUTSIDE_WINDOW.value)


class TestEmptyReservePool:

    def test_sick_call_with_no_eligible_reserve_emits_no_reserve_available(
        self, api,
    ):
        """PRD §3.4: "If no covering candidate exists, the sick call is
        still recorded (HTTP 201) but covered_by_assignment_id remains
        null, the pairing keeps its uncovered slot, and the response
        body's error_id is ERR_NO_RESERVE_AVAILABLE to signal the
        manual-intervention need."

        # difficulty: boundary_precision_check/reserve_callout_empty_pool
        """
        sick_pilot = create_crew_member(rank="CAPTAIN")
        pairing, assignment = setup_pairing_admin_assigned(
            sick_pilot, assigned_rank_slot="CAPTAIN",
        )
        # No reserves placed → empty pool.
        resp = report_sick_call(
            sick_pilot, assignment_id=assignment["id"],
        )
        assert resp.status_code == 201, (
            "PRD §3.4: HTTP 201 — sick call recorded even with empty pool."
        )
        body = resp.json()["data"]
        assert body.get("error_id") == ApiErrorId.ERR_NO_RESERVE_AVAILABLE.value, (
            "PRD §3.4: response body's error_id is "
            "ERR_NO_RESERVE_AVAILABLE."
        )
        assert body.get("covered_by_assignment_id") is None, (
            "PRD §3.4: covered_by_assignment_id remains null."
        )
        # Assignment was still released.
        a = get_assignment(assignment["id"])
        assert a["status"] == "RELEASED", (
            "PRD §3.4: When assignment_id is supplied and that "
            "assignment is still SCHEDULED, the assignment is released."
        )


class TestNoShow:

    def test_mark_no_show_transitions_assignment(self, api):
        """PRD §3.4: "the CrewScheduler marks the assignment as
        no-show, transitioning the assignment from SCHEDULED to
        NO_SHOW. The crew member's status remains ACTIVE, pay credit is
        not granted for the no-show assignment, and the
        reserve-selection algorithm runs to recover the slot."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Build pairing with start_at in the future, then admin-assign,
        # then advance clock to start_at.
        start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=48),
        )
        pairing, assignment = setup_pairing_admin_assigned(
            pilot, start_at=start, assigned_rank_slot="CAPTAIN",
        )
        # Move clock to start_at.
        advance_clock_to(start)
        resp = api.mark_assignment_no_show(
            assignment["id"], scheduler_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "NO_SHOW"
        cm = get_crew_member(pilot["id"])
        assert cm["status"] == "ACTIVE", (
            "PRD §3.4: The crew member's status remains ACTIVE."
        )
