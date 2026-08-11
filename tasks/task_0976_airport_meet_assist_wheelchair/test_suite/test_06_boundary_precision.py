"""Difficulty queue A — boundary_precision_check instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, walk_assignment_to_handed_off,
    complete_assignment, make_agent_headers, make_confirmer_headers,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/meet_buffer_minutes_boundary_15_accepted_14_rejected
# ---------------------------------------------------------------------------

class TestMeetBufferBoundary:
    def test_meet_buffer_15_accepted(self, api):
        """PRD §3.1: "the `meet_buffer_minutes` — the required buffer in minutes
        between an agent's landing-time and the pick-up, which must be at least 15."

        Design: Difficulty/boundary_precision_check/meet_buffer_minutes_boundary_15_accepted_14_rejected
        """
        resp = api_client.create_airport(
            {"iata_code": "ATX", "tz_offset_minutes": 0, "meet_buffer_minutes": 15},
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["meet_buffer_minutes"] == 15

    def test_meet_buffer_14_rejected(self, api):
        """PRD §3.1: "must be at least 15."

        Design: Difficulty/boundary_precision_check/meet_buffer_minutes_boundary_15_accepted_14_rejected
        """
        resp = api_client.create_airport(
            {"iata_code": "BTY", "tz_offset_minutes": 0, "meet_buffer_minutes": 14},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/usage_count_threshold_49_vs_50_maintenance_flip
# ---------------------------------------------------------------------------

class TestUsageCountMaintenanceBoundary:
    def _run_full_cycle(self, airport_id, wheelchair_id, agent_id, cycle_idx):
        """One dispatch + complete cycle against `wheelchair_id`.
        Builds a fresh passenger+request+leg each time so the same chair is reused."""
        # Fresh segment for each cycle to avoid time-collision issues
        seg = create_segment(
            airport_id,
            create_terminal(airport_id, code=f"T{cycle_idx}")["id"],
            flight_no=f"CYC{cycle_idx}", direction="ARRIVAL",
            scheduled_utc="2026-06-16T10:00:00Z",
        )
        pax = create_passenger(
            # WCHS so each leg sets requires_wheelchair (PRD §3.2) and the
            # dispatch actually checks out the shared test chair.
            full_name=f"P {cycle_idx}", dob="1980-01-01",
            mobility_code="WCHS", airline_pnr=f"P{cycle_idx}",
        )
        req = create_assist_request(
            pax["id"], bill_to="AIRLINE", service_tier="STANDARD", companion_count=0,
        )
        leg = create_leg(req["id"], seg["id"], leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        req = submit_request(req["id"])
        asg = dispatch_leg(leg["id"], req["id"], DISP)
        # Walk to completion as a distinct confirmer
        walk_assignment_to_handed_off(asg["id"], agent_id)
        get_success_data(api_client.post_segment_event(
            seg["id"], {"event_type": "LANDED", "actual_utc": "2026-06-16T10:00:00Z"}, OPS,
        ))
        complete_assignment(asg["id"], confirmer_user_id=f"conf_{cycle_idx}")

    def test_usage_count_50th_checkin_enters_maintenance(self, api):
        """PRD §3.5: "The checked-out chair returns from `CHECKED_OUT` to
        `AVAILABLE`, unless its `usage_count` has reached 50, in which case it
        transitions instead into `MAINTENANCE`."

        Design: Difficulty/boundary_precision_check/usage_count_threshold_49_vs_50_maintenance_flip
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="AUS", meet_buffer_minutes=15)
        # Create the test chair + a backup chair. We want the test chair to be
        # selected on every dispatch. The wheelchair selector ranks by usage_count
        # ASC, so we keep the backup chair's usage_count higher than the test
        # chair's by pre-running it once, OR just rely on created_at tiebreak.
        # Simpler: only create one wheelchair so it MUST be selected.
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-AUS-1")
        agent = create_agent(
            airport["id"], display_name="AUS Ag",
            # PRD §3.1 caps shift length at twelve hours; this window covers
            # the 09:00 dispatch clock used by every cycle below.
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        # Run 49 cycles to bring usage_count to 49, status returns to AVAILABLE.
        for i in range(49):
            self._run_full_cycle(airport["id"], wheelchair["id"], agent["id"], i)
            chair_now = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
            # After each of the first 49 cycles the chair returns to AVAILABLE
            assert chair_now["status"] == "AVAILABLE", (
                f"cycle {i}: expected AVAILABLE, got {chair_now['status']}"
            )
            assert chair_now["usage_count"] == i + 1
        # 50th checkout + checkin → MAINTENANCE
        self._run_full_cycle(airport["id"], wheelchair["id"], agent["id"], 49)
        chair_after_50 = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert chair_after_50["usage_count"] == 50
        assert chair_after_50["status"] == "MAINTENANCE"

    def test_usage_count_49_returns_to_available_not_maintenance(self, api):
        """PRD §3.5: "unless its `usage_count` has reached 50, in which case it
        transitions instead into `MAINTENANCE`." Boundary: 49 → AVAILABLE.

        Design: Difficulty/boundary_precision_check/usage_count_threshold_49_vs_50_maintenance_flip
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="AUS", meet_buffer_minutes=15)
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-AUS-2")
        agent = create_agent(
            airport["id"], display_name="AUS Ag2",
            # PRD §3.1 caps shift length at twelve hours; this window covers
            # the 09:00 dispatch clock used by every cycle below.
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        # Run 49 cycles — the 49th check-in returns the chair to AVAILABLE (count 49 < 50).
        for i in range(49):
            self._run_full_cycle(airport["id"], wheelchair["id"], agent["id"], i)
        chair_now = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert chair_now["usage_count"] == 49
        assert chair_now["status"] == "AVAILABLE"
