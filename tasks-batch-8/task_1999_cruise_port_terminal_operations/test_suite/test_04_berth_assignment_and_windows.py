"""Berth assignment creation and confirmation: physical fit, window
containment, the buffered-overlap rule, posture gating, arrival containment,
berth service locks, and the OCC guard on create-with-supersede."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_berth_assignment,
    confirm_assignment,
    create_berth,
    create_port_call,
    create_terminal,
    create_vessel,
    create_weather_advisory,
    depart_port_call,
    get_berth_assignment,
    get_port_call,
    set_clock,
    setup_base,
    setup_confirmed_call,
    setup_scheduled_call,
    setup_turnaround_call,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]


class TestBufferedOverlapPairs:
    def _setup_incumbent(self):
        """Call A with a CONFIRMED assignment on B1 covering the default day."""
        ctx = setup_base(vessel_name="MV R")
        pc_a = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                                voyage_ref="VA")
        ba_a = add_berth_assignment(pc_a["id"], ctx["berth"]["id"],
                                    expected_port_call_version=pc_a["version"])
        confirm_assignment(ba_a["id"])
        ctx["pc_a"] = pc_a
        ctx["ba_a"] = get_berth_assignment(ba_a["id"])
        return ctx

    def test_window_ending_exactly_buffer_before_incumbent_allowed(self, api):
        """PRD §3.3: "Against every other assignment on the same berth in
        `CONFIRMED` or `ACTIVE`, the candidate conflicts unless its window ends
        at least 120 minutes before the other window starts, or its window
        starts no earlier than 120 minutes after the other window ends — a
        mandatory buffer of two full hours on both sides, with a gap of exactly
        120 minutes on either side allowed."

        Design: Difficulty/resource_temporal_overlap/berth_buffered_halfopen_pairwise
        """
        ctx = self._setup_incumbent()
        # Call D's window ends 04:00, exactly 120 minutes before A's 06:00 start.
        pc_d = create_port_call(
            ctx["terminal"]["id"], ctx["vessel"]["id"], voyage_ref="VD",
            scheduled_eta="2026-08-09T12:00:00Z",
            scheduled_etd="2026-08-10T02:00:00Z")
        ba_d = add_berth_assignment(pc_d["id"], ctx["berth"]["id"],
                                    window_start="2026-08-09T10:00:00Z",
                                    window_end="2026-08-10T04:00:00Z",
                                    expected_port_call_version=pc_d["version"])
        confirmed = confirm_assignment(ba_d["id"])
        assert confirmed["status"] == "CONFIRMED"

    def test_window_interior_overlap_rejected(self, api):
        """PRD §3.3: "A violation is rejected with `ERR_BERTH_WINDOW_CONFLICT`
        (HTTP 409)."
        PRD §3.3: "Assignments in `TENTATIVE`, `SUPERSEDED`, `EXPIRED`, or
        `RELEASED` never block anyone."

        Design: Difficulty/resource_temporal_overlap/berth_buffered_halfopen_pairwise
        """
        ctx = self._setup_incumbent()
        # Call B's window sits strictly inside A's confirmed window.
        pc_b = create_port_call(
            ctx["terminal"]["id"], ctx["vessel"]["id"], voyage_ref="VB",
            scheduled_eta="2026-08-10T10:30:00Z",
            scheduled_etd="2026-08-10T19:30:00Z")
        ba_b = add_berth_assignment(pc_b["id"], ctx["berth"]["id"],
                                    window_start="2026-08-10T10:00:00Z",
                                    window_end="2026-08-10T20:00:00Z",
                                    expected_port_call_version=pc_b["version"])

        resp = api.confirm_berth_assignment(ba_b["id"], HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_BERTH_WINDOW_CONFLICT)
        assert get_berth_assignment(ba_b["id"])["status"] == "TENTATIVE"


class TestBerthBufferBoundary:
    def _setup_incumbent(self):
        ctx = setup_base(vessel_name="MV N")
        pc_a = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                                voyage_ref="VA")
        ba_a = add_berth_assignment(pc_a["id"], ctx["berth"]["id"],
                                    expected_port_call_version=pc_a["version"])
        confirm_assignment(ba_a["id"])
        return ctx

    def test_119_minute_gap_rejected(self, api):
        """PRD §3.3: "Against every other assignment on the same berth in
        `CONFIRMED` or `ACTIVE`, the candidate conflicts unless its window ends
        at least 120 minutes before the other window starts, or its window
        starts no earlier than 120 minutes after the other window ends — a
        mandatory buffer of two full hours on both sides, with a gap of exactly
        120 minutes on either side allowed."
        PRD §3.3: "A violation is rejected with `ERR_BERTH_WINDOW_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/berth_buffer_120_vs_119_minutes
        """
        ctx = self._setup_incumbent()
        # 23:59 start is a 119-minute gap after the incumbent's 22:00 end.
        pc_c = create_port_call(
            ctx["terminal"]["id"], ctx["vessel"]["id"], voyage_ref="VC",
            scheduled_eta="2026-08-11T01:00:00Z",
            scheduled_etd="2026-08-11T09:00:00Z")
        ba_c = add_berth_assignment(pc_c["id"], ctx["berth"]["id"],
                                    window_start="2026-08-10T23:59:00Z",
                                    window_end="2026-08-11T11:59:00Z",
                                    expected_port_call_version=pc_c["version"])
        resp = api.confirm_berth_assignment(ba_c["id"], HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_BERTH_WINDOW_CONFLICT)
        assert get_berth_assignment(ba_c["id"])["status"] == "TENTATIVE"

    def test_120_minute_gap_allowed(self, api):
        """PRD §3.3: "Against every other assignment on the same berth in
        `CONFIRMED` or `ACTIVE`, the candidate conflicts unless its window ends
        at least 120 minutes before the other window starts, or its window
        starts no earlier than 120 minutes after the other window ends — a
        mandatory buffer of two full hours on both sides, with a gap of exactly
        120 minutes on either side allowed."

        Design: Difficulty/boundary_precision_check/berth_buffer_120_vs_119_minutes
        """
        ctx = self._setup_incumbent()
        # 00:00 start is exactly a 120-minute gap after the incumbent's 22:00 end.
        pc_b = create_port_call(
            ctx["terminal"]["id"], ctx["vessel"]["id"], voyage_ref="VB",
            scheduled_eta="2026-08-11T02:00:00Z",
            scheduled_etd="2026-08-11T10:00:00Z")
        ba_b = add_berth_assignment(pc_b["id"], ctx["berth"]["id"],
                                    window_start="2026-08-11T00:00:00Z",
                                    window_end="2026-08-11T12:00:00Z",
                                    expected_port_call_version=pc_b["version"])
        confirmed = confirm_assignment(ba_b["id"])
        assert confirmed["status"] == "CONFIRMED"


class TestPostureGatePrecedenceAtConfirm:
    def _setup_emergency_with_conflicting_candidate(self):
        """Confirmed incumbent on B1; a second TENTATIVE assignment whose
        60-minute gap violates the buffer; then an EMERGENCY advisory covering
        the logical now."""
        ctx = setup_base(vessel_name="MV K")
        term = ctx["terminal"]["id"]
        ves = ctx["vessel"]["id"]
        pc_a = create_port_call(term, ves, voyage_ref="VA")
        ba_a = add_berth_assignment(pc_a["id"], ctx["berth"]["id"],
                                    expected_port_call_version=pc_a["version"])
        confirm_assignment(ba_a["id"])

        pc_b = create_port_call(term, ves, voyage_ref="VB",
                                scheduled_eta="2026-08-11T01:00:00Z",
                                scheduled_etd="2026-08-11T09:00:00Z")
        ba_b = add_berth_assignment(pc_b["id"], ctx["berth"]["id"],
                                    window_start="2026-08-10T23:00:00Z",
                                    window_end="2026-08-11T11:00:00Z",
                                    expected_port_call_version=pc_b["version"])

        set_clock("2026-08-10T12:00:00Z")
        create_weather_advisory(term, severity="EMERGENCY",
                                window_start="2026-08-10T00:00:00Z",
                                window_end="2026-08-11T00:00:00Z")
        ctx["pc_b"] = pc_b
        ctx["ba_b"] = ba_b
        return ctx

    def test_posture_emergency_wins_over_window_conflict(self, api):
        """PRD §2.9: "Incoming requests are validated in a fixed priority
        order, so that when several checks could fail, the rejection is
        deterministic."
        PRD §2.9: "9. Posture gate: `EMERGENCY` blocks assignment create and
        confirm, service-order approve, transport dispatch, and port-call depart
        — otherwise `ERR_POSTURE_EMERGENCY` (409)."
        PRD §2.9: "14. Buffered berth overlap — otherwise
        `ERR_BERTH_WINDOW_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/emergency_posture_beats_window_conflict
        """
        ctx = self._setup_emergency_with_conflicting_candidate()
        resp = api.confirm_berth_assignment(ctx["ba_b"]["id"], HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_POSTURE_EMERGENCY)

    def test_posture_rejection_leaves_candidate_tentative(self, api):
        """PRD §3.3: "Confirmation re-validates the assignment against the live
        world in the pipeline order of §2.9: the assignment must still be
        `TENTATIVE` and the berth must be `ACTIVE` (a berth taken out of service
        since creation fails here with `ERR_INVALID_STATE`); the posture must
        not be `EMERGENCY`; fit and containment are re-checked; and finally the
        buffered-overlap rule runs."
        PRD §2.9: "9. Posture gate: `EMERGENCY` blocks assignment create and
        confirm, service-order approve, transport dispatch, and port-call depart
        — otherwise `ERR_POSTURE_EMERGENCY` (409)."

        Design: Difficulty/priority_pair_validation_conflict/emergency_posture_beats_window_conflict
        """
        ctx = self._setup_emergency_with_conflicting_candidate()
        api.confirm_berth_assignment(ctx["ba_b"]["id"], HARBORMASTER)
        assert get_berth_assignment(ctx["ba_b"]["id"])["status"] == "TENTATIVE"


class TestWindowContainmentAndFit:
    def test_assignment_window_must_contain_schedule(self, api):
        """PRD §3.3: "And the window must contain the call's schedule:
        `window_start` no later than `scheduled_eta` and `window_end` no earlier
        than `scheduled_etd`, otherwise `ERR_WINDOW_NOT_CONTAINED` (HTTP 422)."

        Design: Corner/validations/assignment_window_must_contain_schedule
        """
        ctx = setup_scheduled_call()
        resp = api.create_berth_assignment(
            ctx["port_call"]["id"],
            {"berth_id": ctx["berth"]["id"],
             "window_start": "2026-08-10T09:00:00Z",
             "window_end": "2026-08-10T22:00:00Z",
             "expected_port_call_version": ctx["port_call"]["version"]},
            HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CONTAINED)

        _, meta = validate_paginated(
            api.list_berth_assignments(HARBORMASTER,
                                       params={"port_call_id": ctx["port_call"]["id"]}))
        assert meta["total_count"] == 0

    def test_arrive_outside_assignment_window_rejected(self, api):
        """PRD §3.3: "The call must hold a `CONFIRMED` assignment, or the
        arrival is rejected with `ERR_INVALID_STATE`, and `actual_eta` must fall
        within that assignment's window — no earlier than its `window_start` and
        no later than its `window_end`, inclusive at both ends — or the
        rejection is `ERR_WINDOW_NOT_CONTAINED`."

        Design: Corner/validations/arrive_outside_assignment_window_rejected
        """
        ctx = setup_confirmed_call()
        resp = api.arrive_port_call(ctx["port_call"]["id"],
                                    {"actual_eta": "2026-08-10T23:00:00Z"},
                                    HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CONTAINED)
        assert get_port_call(ctx["port_call"]["id"])["status"] == "SCHEDULED"

    def test_berth_fit_equality_edges(self, api):
        """PRD §3.3: "The berth must physically fit the vessel: its `length_ft`
        must be at least the vessel's `loa_ft` plus a 30-foot safety margin —
        equality is allowed — and its `max_draft_ft` must be at least the
        vessel's `draft_ft`, again with equality allowed; a short apron face or
        a shallow berth is rejected with `ERR_BERTH_NOT_FIT` (HTTP 422)."

        Design: Corner/validations/berth_fit_equality_edges
        """
        terminal = create_terminal()
        berth = create_berth(terminal["id"], length_ft=1200, max_draft_ft=40.0)
        v_ok = create_vessel(terminal["id"], name="MV F1", loa_ft=1170,
                             draft_ft=40.0, pax_capacity=2000, crew_count=500)
        v_loa = create_vessel(terminal["id"], name="MV F2", loa_ft=1171,
                              draft_ft=30.0, pax_capacity=2000, crew_count=500)
        v_draft = create_vessel(terminal["id"], name="MV F3", loa_ft=950,
                                draft_ft=40.1, pax_capacity=2000, crew_count=500)

        pc_ok = create_port_call(terminal["id"], v_ok["id"], voyage_ref="V-OK")
        ok = api.create_berth_assignment(
            pc_ok["id"],
            {"berth_id": berth["id"],
             "window_start": "2026-08-10T06:00:00Z",
             "window_end": "2026-08-10T22:00:00Z",
             "expected_port_call_version": pc_ok["version"]},
            HARBORMASTER)
        validate_success(ok, 201)

        pc_loa = create_port_call(terminal["id"], v_loa["id"], voyage_ref="V-LOA")
        err1 = api.create_berth_assignment(
            pc_loa["id"],
            {"berth_id": berth["id"],
             "window_start": "2026-08-10T06:00:00Z",
             "window_end": "2026-08-10T22:00:00Z",
             "expected_port_call_version": pc_loa["version"]},
            HARBORMASTER)
        validate_error(err1, ApiErrorId.ERR_BERTH_NOT_FIT)

        pc_dr = create_port_call(terminal["id"], v_draft["id"], voyage_ref="V-DR")
        err2 = api.create_berth_assignment(
            pc_dr["id"],
            {"berth_id": berth["id"],
             "window_start": "2026-08-10T06:00:00Z",
             "window_end": "2026-08-10T22:00:00Z",
             "expected_port_call_version": pc_dr["version"]},
            HARBORMASTER)
        validate_error(err2, ApiErrorId.ERR_BERTH_NOT_FIT)

    def test_berth_out_of_service_blocked_while_assignment_active(self, api):
        """PRD §3.1: "Taking a berth out of service is refused while any
        assignment on that berth is `ACTIVE` — the rejection is
        `ERR_INVALID_STATE` — but assignments merely `TENTATIVE` on the berth
        are left in place and are only caught later, at confirmation time."
        PRD §3.3: "Departure releases the berth — the `ACTIVE` assignment
        becomes `RELEASED` and the terminal's occupancy and posture are
        recomputed — and then cascades through the manifests: ..."

        Design: Corner/state_machines/berth_out_of_service_blocked_while_assignment_active
        """
        ctx = setup_turnaround_call(customs="cleared")
        berth_id = ctx["berth"]["id"]
        assert ctx["assignment"]["status"] == "ACTIVE"

        blocked = api.out_of_service_berth(berth_id, ADMIN)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        depart_port_call(ctx["port_call"]["id"],
                         actual_etd="2026-08-10T20:00:00Z")
        assert get_berth_assignment(ctx["assignment"]["id"])["status"] == "RELEASED"

        released = validate_success(api.out_of_service_berth(berth_id, ADMIN))
        assert released["status"] == "OUT_OF_SERVICE"


class TestBerthAssignmentOcc:
    def test_stale_expected_version_rejected_current_accepted(self, api):
        """PRD §2.8: "Creating a berth assignment for a port call must carry
        `expected_port_call_version`, holding the caller's last observed
        `version` of that port call. Because creating an assignment supersedes
        the call's live assignment, a create whose `expected_port_call_version`
        trails the call's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412): the caller's view of which assignment is live is stale, and
        its supersede decision is void."

        Design: Corner/cross_cutting_layers/occ_berth_assignment_supersede_stale_version
        """
        ctx = setup_scheduled_call()
        pc = ctx["port_call"]
        berth_id = ctx["berth"]["id"]

        first = add_berth_assignment(pc["id"], berth_id,
                                     expected_port_call_version=pc["version"])
        assert first["status"] == "TENTATIVE"
        assert get_port_call(pc["id"])["version"] == pc["version"] + 1

        stale = api.create_berth_assignment(
            pc["id"],
            {"berth_id": berth_id,
             "window_start": "2026-08-10T05:00:00Z",
             "window_end": "2026-08-10T23:00:00Z",
             "expected_port_call_version": pc["version"]},
            HARBORMASTER)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        current_version = get_port_call(pc["id"])["version"]
        second = add_berth_assignment(
            pc["id"], berth_id, window_start="2026-08-10T05:00:00Z",
            window_end="2026-08-10T23:00:00Z",
            expected_port_call_version=current_version)
        assert second["status"] == "TENTATIVE"

        assert get_berth_assignment(first["id"])["status"] == "SUPERSEDED"
        assert get_port_call(pc["id"])["version"] == current_version + 1, (
            "each successful create bumps the call's version by exactly 1"
        )
