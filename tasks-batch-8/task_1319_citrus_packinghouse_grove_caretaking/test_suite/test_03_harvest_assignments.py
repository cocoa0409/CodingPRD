"""Harvest crews and assignments: window gates, capacity and overlap rules,
terminal lockdown, crew/grove state gates, quarantine gating, and the
state-vs-safety validation ordering."""
from test_helpers import (
    ApiErrorId,
    assert_assignment,
    create_assignment_payload,
    create_quarantine,
    get_assignment,
    get_grove,
    release_quarantine,
    set_clock,
    setup_assignment_in_progress,
    setup_grove_with_maturity,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import create_crew
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestAssignmentWindowGate:
    def test_assignment_start_happy_path_and_window_gate(self, api):
        """PRD §3.2: "the logical clock reads within the assignment's window —
        at or after `window_start` and strictly before `window_end`, with an
        attempt outside that half-open window rejected as
        `ERR_ASSIGNMENT_WINDOW_NOT_OPEN`."

        Design: Corner/state_machines/assignment_start_happy_path_and_window_gate
        """
        scenario = setup_grove_with_maturity("SM1")
        crew = create_crew("CR-SM1", 400)
        assignment = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T06:00:00Z",
                                      "2026-08-03T18:00:00Z", 100),
            SUPERVISOR), expected_status=201)
        assert_assignment(assignment)
        assert assignment["status"] == "SCHEDULED"
        # Clock parked at 2026-08-01, before the window: start is refused.
        resp = api_client.start_assignment(assignment["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_NOT_OPEN)
        # At window_start exactly (inclusive lower bound) the start succeeds.
        set_clock("2026-08-03T06:00:00Z")
        started = validate_success(api_client.start_assignment(
            assignment["id"], SUPERVISOR))
        assert started["status"] == "IN_PROGRESS"


class TestAssignmentCompletionBounds:
    def test_assignment_complete_actual_boxes_bounds(self, api):
        """PRD §3.2: "Completing an assignment moves `IN_PROGRESS` →
        `COMPLETED` and records `actual_boxes`, which must be at least 1 and
        at most the planned boxes multiplied by 1.25 and rounded up to a whole
        box; a count outside that band is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/assignment_complete_actual_boxes_bounds
        """
        scenario = setup_assignment_in_progress("SM2", planned_boxes=100)
        assignment_id = scenario["assignment"]["id"]
        resp = api_client.complete_assignment(assignment_id, {"actual_boxes": 0},
                                              SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        resp = api_client.complete_assignment(assignment_id, {"actual_boxes": 126},
                                              SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # ceil(100 * 1.25) = 125 is the inclusive upper bound.
        completed = validate_success(api_client.complete_assignment(
            assignment_id, {"actual_boxes": 125}, SUPERVISOR))
        assert completed["status"] == "COMPLETED"
        assert completed["actual_boxes"] == 125


class TestAssignmentTerminalLockdown:
    def test_assignment_terminal_lockdown(self, api):
        """PRD §3.2: "Completing an assignment moves `IN_PROGRESS` →
        `COMPLETED`" and "Cancellation moves an assignment to the terminal
        `CANCELLED`". PRD §2.6 tier 6: "the target resource's current state
        permits the requested transition, including terminal-state lockdown"
        and "other state violations surface as `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409)".

        Design: Corner/state_machines/assignment_terminal_lockdown
        """
        scenario = setup_assignment_in_progress(
            "SM3", window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-01T06:00:00Z", planned_boxes=50)
        validate_success(api_client.complete_assignment(
            scenario["assignment"]["id"], {"actual_boxes": 10}, SUPERVISOR))
        second = validate_success(api_client.create_assignment(
            create_assignment_payload(scenario["crew"]["id"],
                                      scenario["grove"]["id"],
                                      "2026-08-01T06:00:00Z",
                                      "2026-08-01T12:00:00Z", 50),
            SUPERVISOR), expected_status=201)
        validate_success(api_client.cancel_assignment(second["id"], SUPERVISOR))

        resp = api_client.complete_assignment(
            scenario["assignment"]["id"], {"actual_boxes": 10}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp = api_client.cancel_assignment(second["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestCrewOverlap:
    def test_crew_exclusive_half_open_overlap_adjacent_accepted(self, api):
        """PRD §3.2: "a conflict exists exactly when the new window's start
        falls before an existing window's end and that existing window's start
        falls before the new window's end; windows that merely touch — the new
        one starting at the instant an existing one ends — do not conflict."

        Design: Difficulty/resource_temporal_overlap/crew_exclusive_half_open_overlap
        """
        scenario = setup_grove_with_maturity("OV1", with_maturity=False)
        crew = create_crew("CR-OV1", 400)
        first = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T06:00:00Z",
                                      "2026-08-03T18:00:00Z", 300),
            SUPERVISOR), expected_status=201)
        second = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T18:00:00Z",
                                      "2026-08-04T06:00:00Z", 300),
            SUPERVISOR), expected_status=201)
        assert first["status"] == "SCHEDULED" and second["status"] == "SCHEDULED", \
            "adjacent half-open windows [06:00,18:00) and [18:00,06:00) do not conflict"

    def test_crew_exclusive_half_open_overlap_intersection_rejected(self, api):
        """PRD §3.2: "A conflicting request fails with
        `ERR_CREW_WINDOW_OVERLAP`." — a window intersecting an existing
        SCHEDULED assignment's interior (one hour into each neighbor)
        conflicts.

        Design: Difficulty/resource_temporal_overlap/crew_exclusive_half_open_overlap
        """
        scenario = setup_grove_with_maturity("OV1B", with_maturity=False)
        crew = create_crew("CR-OV1B", 400)
        validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T06:00:00Z",
                                      "2026-08-03T18:00:00Z", 300),
            SUPERVISOR), expected_status=201)
        validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T18:00:00Z",
                                      "2026-08-04T06:00:00Z", 300),
            SUPERVISOR), expected_status=201)
        resp = api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T17:00:00Z",
                                      "2026-08-03T20:00:00Z", 50),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_OVERLAP)


class TestCrewWindowCapacity:
    def test_crew_window_capacity_day_rounding(self, api):
        """PRD §3.2: "the window's length in hours divided by 24 and rounded
        up to whole days — so a 25-hour window counts as two days — multiplied
        by the crew's `daily_capacity_boxes` gives the window capacity, and
        `planned_boxes` may not exceed it, though an exact fit is allowed; a
        violation fails with `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Corner/calculations/crew_window_capacity_day_rounding
        """
        scenario = setup_grove_with_maturity("CA7", with_maturity=False)
        crew = create_crew("CR-CA7", 400)
        # 25-hour window -> ceil(25/24) = 2 days -> capacity 800; exact fit OK.
        exact = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T06:00:00Z",
                                      "2026-08-04T07:00:00Z", 800),
            SUPERVISOR), expected_status=201)
        assert exact["planned_boxes"] == 800
        # One box over capacity on a disjoint 25-hour window is refused.
        resp = api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-05T06:00:00Z",
                                      "2026-08-06T07:00:00Z", 801),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)


class TestCrewAndGroveStateGates:
    def test_crew_not_active_blocks_assignment_create(self, api):
        """PRD §3.2: "Any attempt to engage an `INACTIVE` crew — at scheduling
        or at start — is refused with `ERR_CREW_NOT_ACTIVE`."

        Design: Corner/errors/crew_not_active_blocks_assignment_create
        """
        scenario = setup_grove_with_maturity("ER2", with_maturity=False)
        crew = create_crew("CR-ER2", 400)
        validate_success(api_client.deactivate_crew(crew["id"], ADMIN))
        resp = api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T00:00:00Z",
                                      "2026-08-03T12:00:00Z", 50),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_ACTIVE)

    def test_grove_retired_blocks_new_assignment(self, api):
        """PRD §3.1: "Retirement is refused with `ERR_INVALID_STATE_TRANSITION`
        while the grove has any harvest assignment in `SCHEDULED` or
        `IN_PROGRESS`". PRD §3.1: "From then on the grove accepts no new
        harvest assignments, deliveries, or caretaking orders: attempts
        against a `RETIRED` grove fail with `ERR_GROVE_RETIRED` (HTTP 409)."

        Design: Corner/errors/grove_retired_blocks_new_assignment
        """
        scenario = setup_grove_with_maturity("ER1", with_maturity=False)
        crew = create_crew("CR-ER1", 400)
        assignment = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 50),
            SUPERVISOR), expected_status=201)
        # Retire is blocked while the assignment is SCHEDULED.
        resp = api_client.retire_grove(scenario["grove"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        validate_success(api_client.cancel_assignment(assignment["id"], SUPERVISOR))
        retired = validate_success(api_client.retire_grove(scenario["grove"]["id"],
                                                           ADMIN))
        assert retired["lifecycle_status"] == "RETIRED"
        # New work on a retired grove is refused.
        resp = api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-03T00:00:00Z",
                                      "2026-08-03T12:00:00Z", 50),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_GROVE_RETIRED)


class TestAssignmentStartGatedByQuarantine:
    def test_start_allowed_after_release_by_different_officer(self, api):
        """PRD §3.8: "Each covered grove's `SCHEDULED` harvest assignments are
        cancelled" by the activation cascade, so the pre-quarantine assignment
        is terminally `CANCELLED` and a later start attempt on it surfaces the
        tier-6 state error `ERR_INVALID_STATE_TRANSITION` — per PRD §2.6,
        "State legality" (tier 6) precedes "Regulatory and safety gates"
        (tier 7). PRD §3.8: "The release stamps `released_at` and
        `released_by`, then recomputes the posture of every affected grove: a
        grove returns to `CLEAR` only when no other `ACTIVE` order still
        covers it". PRD §2.9: "A quarantine order's releasing officer must
        differ from its issuing officer: `released_by` may not equal
        `issued_by`." Once the grove is `CLEAR` again, assignment creation
        and start proceed (PRD §3.2, §3.8).

        Design: Difficulty/cross_entity_state_dependency/assignment_start_gated_by_grove_quarantine
        """
        scenario = setup_grove_with_maturity("CE1B")
        crew = create_crew("CR-CE1B", 400)
        assignment = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 100),
            SUPERVISOR), expected_status=201)
        order = create_quarantine("GROVE", "HLB_GREENING",
                                  grove_id=scenario["grove"]["id"],
                                  officer_id="co-ce-a")
        assert order["status"] == "ACTIVE"
        # §3.8 cascade: the SCHEDULED assignment is cancelled, and §2.10: the
        # grove is QUARANTINED while at least one ACTIVE order covers it.
        assert get_assignment(assignment["id"])["status"] == "CANCELLED"
        assert get_grove(scenario["grove"]["id"])["quarantine_posture"] == "QUARANTINED"
        # §2.6: state legality (tier 6) precedes the regulatory gates
        # (tier 7), so starting the cascade-cancelled assignment surfaces the
        # state error.
        validate_error(api_client.start_assignment(assignment["id"], SUPERVISOR),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        released = validate_success(release_quarantine(
            order["id"], inspection_passed=True, officer_id="co-ce-b"))
        assert released["status"] == "RELEASED"
        assert released["released_by"] == "co-ce-b" != released["issued_by"]
        assert get_grove(scenario["grove"]["id"])["quarantine_posture"] == "CLEAR"
        # With the grove CLEAR again, the create + start path is legal.
        replacement = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 100),
            SUPERVISOR), expected_status=201)
        started = validate_success(api_client.start_assignment(
            replacement["id"], SUPERVISOR))
        assert started["status"] == "IN_PROGRESS"


class TestStateBeatsSafetyPriority:
    def test_state_vs_safety_assignment_start_error(self, api):
        """PRD §2.6: "a request that would fail checks in two different tiers
        is rejected with the error from the earlier tier, so a failure higher
        on the ladder is never masked by one lower down." Tier 6 (state
        legality, `ERR_INVALID_STATE_TRANSITION`) precedes tier 7 (regulatory
        gates, `ERR_GROVE_QUARANTINED`): starting a CANCELLED assignment whose
        grove is quarantined surfaces the state error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_assignment_start
        """
        scenario = setup_grove_with_maturity("PP1")
        crew = create_crew("CR-PP1", 400)
        assignment = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 100),
            SUPERVISOR), expected_status=201)
        validate_success(api_client.cancel_assignment(assignment["id"], SUPERVISOR))
        create_quarantine("GROVE", "CANKER", grove_id=scenario["grove"]["id"],
                          officer_id="co-pp-a")
        resp = api_client.start_assignment(assignment["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_state_vs_safety_assignment_start_leaves_state_untouched(self, api):
        """PRD §2.6: the rejected request surfaces "the error from the earlier
        tier" and no transition occurs: the assignment remains in its terminal
        `CANCELLED` state (PRD §3.2) and the grove's posture stays
        `QUARANTINED` while an `ACTIVE` order covers it (PRD §2.10).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_assignment_start
        """
        scenario = setup_grove_with_maturity("PP1B")
        crew = create_crew("CR-PP1B", 400)
        assignment = validate_success(api_client.create_assignment(
            create_assignment_payload(crew["id"], scenario["grove"]["id"],
                                      "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z", 100),
            SUPERVISOR), expected_status=201)
        validate_success(api_client.cancel_assignment(assignment["id"], SUPERVISOR))
        create_quarantine("GROVE", "CANKER", grove_id=scenario["grove"]["id"],
                          officer_id="co-pp-a")
        validate_error(api_client.start_assignment(assignment["id"], SUPERVISOR),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_assignment(assignment["id"])["status"] == "CANCELLED"
        assert get_grove(scenario["grove"]["id"])["quarantine_posture"] == "QUARANTINED"
