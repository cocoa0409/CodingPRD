"""Dispatch gating, arrival cascade, selector ranking, and shift overlap
(PRD §3.1, §3.4)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage, dispatch,
    arrive, clear, get_incident, get_technician,
    create_technician_payload, create_shift_payload,
    set_clock, add_shift,
    TEST_USERS, make_technician_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestDispatchRequiresTriagedIncident:
    def test_dispatch_on_new_incident_rejected(self, api):
        """PRD §3.4: "A `Dispatcher` or `Supervisor` creates the assignment
        against an incident that must currently be `TRIAGED` — dispatching an
        incident in any other lifecycle state is rejected with
        `ERR_INCIDENT_NOT_TRIAGED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_triaged_incident
        """
        terr, tech = setup_territory_technician()
        call = intake_call(terr["id"], address_line="40 Fir St",
                           caller_name="Quinn", caller_phone="555-0116")

        resp = api_client.create_dispatch(
            call["incident_id"], {"technician_id": tech["id"]}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_TRIAGED)

        incident = get_incident(call["incident_id"])
        assert incident["lifecycle_status"] == "NEW"

    def test_dispatch_after_triage_succeeds_and_cascades(self, api):
        """PRD §3.4: "Creation cascades: the incident automatically
        transitions `TRIAGED → DISPATCHED`, its `awaiting_dispatch` flag
        clears to false, its `version` increments, and the technician's
        `active_assignment_count` increases by one with `weighted_load`
        recomputed." and "A created assignment starts in `EN_ROUTE` with
        `dispatched_at` stamped from the logical clock".

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_triaged_incident
        """
        terr, tech = setup_territory_technician()
        call = intake_call(terr["id"], address_line="40 Fir St",
                           caller_name="Quinn", caller_phone="555-0116")
        triage(call["incident_id"], "P2")

        resp = api_client.create_dispatch(
            call["incident_id"], {"technician_id": tech["id"]}, DISPATCHER)
        disp = validate_success(resp, expected_status=201)
        assert disp["status"] == "EN_ROUTE"
        assert disp["technician_id"] == tech["id"]
        assert disp["incident_id"] == call["incident_id"]

        incident = get_incident(call["incident_id"])
        assert incident["lifecycle_status"] == "DISPATCHED"
        assert incident["awaiting_dispatch"] is False

        t = get_technician(tech["id"])
        assert t["active_assignment_count"] == 1
        assert t["weighted_load"] == 3  # P2 weight (PRD §3.1)


class TestFirstArrivalStopsClock:
    def test_arrive_moves_assignment_and_incident_on_scene(self, api):
        """PRD §3.4: "When this arrival is the incident's first arrival in the
        current response segment, the incident cascade fires automatically:
        the incident moves `DISPATCHED → ON_SCENE`, `first_arrival_at` is set
        to the arrival's logical time and the response clock stops for the
        segment." It also "stamps `arrived_at` and increments the assignment
        `version`."

        Design: Corner/state_machines/first_arrival_stops_clock_and_transitions_on_scene
        """
        terr, tech = setup_territory_technician()
        call = intake_call(terr["id"], address_line="7 Scene St",
                           caller_name="Hal's caller", caller_phone="555-0208")
        triage(call["incident_id"], "P2")
        disp = dispatch(call["incident_id"], tech["id"])
        set_clock("2026-08-01T00:30:00Z")

        resp = api_client.arrive_dispatch(disp["id"],
                                          make_technician_headers(tech["id"]))
        updated = validate_success(resp)
        assert updated["status"] == "ON_SCENE"
        assert updated["arrived_at"].startswith("2026-08-01T00:30:00")

        incident = get_incident(call["incident_id"])
        assert incident["lifecycle_status"] == "ON_SCENE"
        assert incident["first_arrival_at"].startswith("2026-08-01T00:30:00")
        # 1800s elapsed against a 3600s P2 threshold: compliant (§2.7).
        assert incident["breach_class"] == "NONE"


class TestArriveOnPreemptedDispatch:
    def test_arrive_on_preempted_dispatch_returns_invalid_state(self, api):
        """PRD §3.4: "The arrival action requires the assignment to be
        `EN_ROUTE` (otherwise `ERR_INVALID_STATE`)" and "An assignment's
        lifecycle runs `EN_ROUTE → ON_SCENE → CLEARED`, with `PREEMPTED` and
        `CANCELLED` as additional terminal outcomes reachable only from
        `EN_ROUTE`."

        Design: Corner/state_machines/arrive_on_preempted_dispatch_returns_invalid_state
        """
        terr, tech = setup_territory_technician()
        call_a = intake_call(terr["id"], address_line="9 Low St",
                             caller_name="J", caller_phone="555-0209")
        triage(call_a["incident_id"], "P2")
        disp_a = dispatch(call_a["incident_id"], tech["id"])
        call_b = intake_call(terr["id"], address_line="11 High St",
                             caller_name="K", caller_phone="555-0210",
                             occupancy_type="HOSPITAL", symptoms_reported=True)
        triage(call_b["incident_id"], "P1")

        resp = api_client.preempt_dispatch(
            disp_a["id"],
            {"target_incident_id": call_b["incident_id"], "reason": "P1 preemption"},
            SUPERVISOR)
        validate_success(resp)

        resp = api_client.arrive_dispatch(disp_a["id"],
                                          make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = validate_success(api_client.get_dispatch(disp_a["id"], SUPERVISOR))
        assert current["status"] == "PREEMPTED"
        incident_a = get_incident(call_a["incident_id"])
        assert incident_a["first_arrival_at"] is None


class TestClearTwice:
    def test_clear_twice_returns_invalid_state_and_counts_once(self, api):
        """PRD §3.4: "The clear action likewise requires an `ON_SCENE`
        assignment owned by the caller; it stamps `cleared_at`, decrements the
        technician's `active_assignment_count`, sets `last_cleared_at` to the
        clearing time, and recomputes `weighted_load`." A clear from any other
        state fails with ERR_INVALID_STATE ("cancelling is illegal from any
        other state (`ERR_INVALID_STATE`)" analogously for transitions).

        Design: Corner/state_machines/clear_twice_returns_invalid_state
        """
        terr, tech = setup_territory_technician()
        call = intake_call(terr["id"], address_line="15 Clear St",
                           caller_name="Q", caller_phone="555-0214")
        triage(call["incident_id"], "P2")
        disp = dispatch(call["incident_id"], tech["id"])
        set_clock("2026-08-01T00:20:00Z")
        arrive(disp["id"], tech["id"])
        clear(disp["id"], tech["id"])

        resp = api_client.clear_dispatch(disp["id"],
                                         make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        t = get_technician(tech["id"])
        assert t["active_assignment_count"] == 0, "decremented exactly once"


class TestShiftOverlapRules:
    def test_adjacent_shift_allowed(self, api):
        """PRD §3.1: "Two shifts of the same technician may not overlap; an
        overlapping declaration is rejected with `ERR_SHIFT_OVERLAP`
        (HTTP 409), while adjacency — one shift's `shift_end` exactly equal to
        another's `shift_start` — is allowed."

        Design: Difficulty/resource_temporal_overlap/technician_shift_half_open_overlap_rules
        """
        terr, tech = setup_territory_technician(
            shift_start="2026-08-01T08:00:00Z", shift_end="2026-08-01T16:00:00Z")

        resp = api_client.create_shift(
            tech["id"],
            {"shift_start": "2026-08-01T16:00:00Z",
             "shift_end": "2026-08-01T23:00:00Z"},
            SUPERVISOR)
        validate_success(resp, expected_status=201)

        data, meta = validate_paginated(api_client.list_shifts(tech["id"], SUPERVISOR))
        assert meta["total_count"] == 2

    def test_overlapping_shifts_rejected(self, api):
        """PRD §3.1: "Two shifts of the same technician may not overlap; an
        overlapping declaration is rejected with `ERR_SHIFT_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/technician_shift_half_open_overlap_rules
        """
        terr, tech = setup_territory_technician(
            shift_start="2026-08-01T08:00:00Z", shift_end="2026-08-01T16:00:00Z")
        add_shift(tech["id"], "2026-08-01T16:00:00Z", "2026-08-01T23:00:00Z")

        resp = api_client.create_shift(
            tech["id"],
            {"shift_start": "2026-08-01T15:00:00Z",
             "shift_end": "2026-08-01T17:00:00Z"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)

        resp = api_client.create_shift(
            tech["id"],
            {"shift_start": "2026-08-01T22:00:00Z",
             "shift_end": "2026-08-01T23:30:00Z"},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)

        data, meta = validate_paginated(api_client.list_shifts(tech["id"], SUPERVISOR))
        assert meta["total_count"] == 2


class TestDispatchSelector:
    def test_auto_select_empty_pool_returns_no_available_technician(self, api):
        """PRD §3.4: "The eligible pool contains technicians who are active,
        on shift, homed in the incident's territory, and holding fewer than
        two active assignments." "An empty pool is rejected with
        `ERR_NO_AVAILABLE_TECHNICIAN` (HTTP 409)."

        Design: Corner/validations/auto_select_empty_pool_returns_no_available_technician
        """
        terr, tech = setup_territory_technician(
            shift_start="2026-08-02T00:00:00Z", shift_end="2026-08-02T12:00:00Z")
        call = intake_call(terr["id"], address_line="3 Pool St",
                           caller_name="Z3", caller_phone="555-0227")
        triage(call["incident_id"], "P2")

        resp = api_client.create_dispatch(call["incident_id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_TECHNICIAN)

        incident = get_incident(call["incident_id"])
        assert incident["lifecycle_status"] == "TRIAGED"

    def test_selector_picks_lowest_load_with_created_at_tiebreak(self, api):
        """PRD §3.4: "Ranking is by `weighted_load` ascending, then by
        `last_cleared_at` ascending with technicians who have never cleared
        (null) ordered first, then by technician `created_at` ascending; the
        first-ranked technician wins."

        Design: Corner/validations/selector_picks_lowest_load_with_created_at_tiebreak
        """
        terr = setup_territory()
        tech_a = validate_success(api_client.create_technician(
            create_technician_payload(full_name="Alpha", badge_number="B112",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        tech_b = validate_success(api_client.create_technician(
            create_technician_payload(full_name="Beta", badge_number="B113",
                                      home_territory_id=terr["id"]), ADMIN),
            expected_status=201)
        for t in (tech_a, tech_b):
            add_shift(t["id"])

        call = intake_call(terr["id"], address_line="4 Rank St",
                           caller_name="Z4", caller_phone="555-0228",
                           location_context="OUTSIDE_STRUCTURE")
        triage(call["incident_id"], "P3")

        resp = api_client.create_dispatch(call["incident_id"], {}, DISPATCHER)
        disp = validate_success(resp, expected_status=201)
        assert disp["technician_id"] == tech_a["id"], (
            "equal load 0, both never cleared -> created_at ASC tiebreak")

        a = get_technician(tech_a["id"])
        assert a["active_assignment_count"] == 1
        assert a["weighted_load"] == 2  # P3 weight (PRD §3.1)
