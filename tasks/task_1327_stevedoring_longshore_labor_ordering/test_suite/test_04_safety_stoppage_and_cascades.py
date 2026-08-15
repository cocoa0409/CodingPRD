"""Safety incidents, work-stoppage gates, and the cascades they trigger."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    berth_vessel,
    book_equipment,
    check_in,
    clear_incident,
    complete_gang,
    create_shift,
    create_vessel,
    dispatch_batch,
    get_assignment,
    get_equipment_assignment,
    get_gang,
    get_shift,
    get_unit,
    get_vessel,
    list_assignments,
    open_shift,
    place_gang,
    register_unit,
    register_worker,
    report_incident,
    run_dispatch,
    set_worker_status,
    setup_dispatched_gang,
    setup_placed_gang,
    setup_working_gang,
    start_gang_work,
    start_shift,
    validate_error,
    validate_success,
)

SUPT = TEST_USERS["superintendent_headers"]
DISP = TEST_USERS["dispatcher_headers"]

CRANE_SPEC = {"full_name": "Crane Op", "registration_number": "R010",
              "classification": "CRANE_OPERATOR", "registered_on": "2010-01-01",
              "base_hourly_rate_cents": 5000}
CRANE_GANG = {"gang_type": "CRANE_GANG", "required_classification": "CRANE_OPERATOR",
              "required_headcount": 1, "required_equipment_type": "RTG",
              "required_equipment_count": 1}


def _setup_working_crane_gang(vessel_name, voyage_number):
    """WORKING crane gang: W1 WORKING, one RTG assignment ACTIVE."""
    return setup_working_gang(
        vessel_overrides={"vessel_name": vessel_name, "voyage_number": voyage_number,
                          "planned_moves": 200, "planned_tons": 100,
                          "contracted_mph_target": 25.0,
                          "credit_limit_cents": 500_000_000},
        gang_overrides=dict(CRANE_GANG),
        worker_specs=[dict(CRANE_SPEC)],
        equipment_specs=[{"unit_code": "RTG-1", "equipment_type": "RTG"}])


class TestSuspendResumeCycle:

    def test_full_stoppage_suspends_gang_and_releases_equipment(self, api):
        """PRD §3.5: "The moment a vessel's posture becomes `FULL_STOPPAGE`, every gang order of that vessel's shifts that is in `WORKING` drops to `SUSPENDED`: the order's `suspension_count` increments by one, its equipment assignments in `RESERVED` or `ACTIVE` are released and their units return from `ASSIGNED` to `AVAILABLE`, and `assigned_equipment_ok` recomputes — false unless surplus coverage somehow remains."

        Design: Difficulty/non_linear_state_machine/gang_order_suspend_resume_cycle_requires_equipment_reacquisition
        """
        ns = _setup_working_crane_gang("MV Cycle", "CY-601")
        assert ns.gang["status"] == "WORKING"

        report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                        description="Container stack collapse")

        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "SUSPENDED"
        assert gang["suspension_count"] == 1
        assert gang["assigned_equipment_ok"] is False

    def test_resume_requires_fresh_equipment_booking(self, api):
        """PRD §3.5: "Resuming is deliberate, never automatic: the foreman starts work again on the `SUSPENDED` order, the posture must once more be `NORMAL`, and because suspension released the equipment, `assigned_equipment_ok` must be rebuilt through fresh bookings before the gate passes — on resume, the order's new `RESERVED` assignments become `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/gang_order_suspend_resume_cycle_requires_equipment_reacquisition
        """
        ns = _setup_working_crane_gang("MV Cycle", "CY-601")
        inc = report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                              description="Container stack collapse")
        clear_incident(inc["id"])
        assert get_vessel(ns.vessel["id"])["work_posture"] == "NORMAL"

        # Equipment was released by the suspension: the posture gate passes but
        # the equipment gate rejects the first resume attempt.
        blocked = start_gang_work(ns.gang["id"], ns.foreman_id)
        validate_error(blocked, ApiErrorId.ERR_NO_EQUIPMENT_ASSIGNED)
        assert get_gang(ns.gang["id"])["status"] == "SUSPENDED"

        # Re-book the freed unit (its old assignment is terminal RELEASED).
        new_booking = book_equipment(ns.gang["id"], ns.equipment[0]["id"])
        assert new_booking["status"] == "RESERVED"

        resumed = start_gang_work(ns.gang["id"], ns.foreman_id)
        assert validate_success(resumed)["status"] == "WORKING", (
            "WORKING -> SUSPENDED -> WORKING cycle completed")
        assert get_equipment_assignment(new_booking["id"])["status"] == "ACTIVE"


class TestFullStoppageCascade:

    def test_incident_flips_posture_and_suspends_working_gang(self, api):
        """PRD §3.6: "The posture is `FULL_STOPPAGE` when any open incident is `CRITICAL` at any scope, or `MAJOR` at `VESSEL` or `TERMINAL` scope."
        PRD §3.6: "The derivation re-runs on every incident creation and every clearance, and entering `FULL_STOPPAGE` fires the suspension cascade of §3.5 in the same moment."

        Design: Difficulty/transitive_cascade/safety_incident_full_stoppage_depth4_cascade
        """
        ns = _setup_working_crane_gang("MV Cascade", "CA-801")
        report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                        description="Crane wire snap")

        assert get_vessel(ns.vessel["id"])["work_posture"] == "FULL_STOPPAGE"
        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "SUSPENDED"
        assert gang["suspension_count"] == 1

    def test_stoppage_cascade_releases_equipment_down_to_unit(self, api):
        """PRD §3.5: "its equipment assignments in `RESERVED` or `ACTIVE` are released and their units return from `ASSIGNED` to `AVAILABLE`"
        PRD §3.4: "from either `RESERVED` or `ACTIVE` the assignment becomes `RELEASED`, the unit returns to `AVAILABLE` when no other non-terminal assignment holds it"

        Design: Difficulty/transitive_cascade/safety_incident_full_stoppage_depth4_cascade
        """
        ns = _setup_working_crane_gang("MV Cascade", "CA-801")
        ea = ns.equipment_assignments[0]
        assert get_equipment_assignment(ea["id"])["status"] == "ACTIVE"

        report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                        description="Crane wire snap")

        assert get_equipment_assignment(ea["id"])["status"] == "RELEASED"
        assert get_unit(ns.equipment[0]["id"])["status"] == "AVAILABLE", (
            "the unit is freed by the release its own assignment underwent")


class TestWorkerSuspensionCascade:

    def _setup_offered_worker(self):
        """OPEN shift, headcount-1 gang, W1 (rank 1) OFFERED, W2 (rank 2) next."""
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV Suspend", "voyage_number": "SU-901"},
            gang_overrides={"required_headcount": 1})
        assert ns.assignments[0]["worker_id"] == ns.workers[0]["id"]
        return ns

    def test_suspension_bumps_outstanding_offer(self, api):
        """PRD §3.3: "Moving a worker to `SUSPENDED` cascades: every `OFFERED` assignment of that worker becomes `BUMPED`, each bump triggers the single-slot auto-offer to the next eligible candidate with the suspended worker excluded, and manning recomputes on every affected gang order."

        Design: Difficulty/transitive_cascade/worker_suspension_bump_redispatch_depth3_cascade
        """
        ns = self._setup_offered_worker()
        w1 = ns.workers[0]
        a1 = ns.assignments[0]

        resp = set_worker_status(w1["id"], "SUSPENDED", w1["version"])
        assert validate_success(resp)["status"] == "SUSPENDED"

        assert get_assignment(a1["id"])["status"] == "BUMPED", (
            "the suspended worker's OFFERED assignment flips to BUMPED")

    def test_suspension_auto_offers_next_eligible_worker(self, api):
        """PRD §3.3: "Moving a worker to `SUSPENDED` cascades: every `OFFERED` assignment of that worker becomes `BUMPED`, each bump triggers the single-slot auto-offer to the next eligible candidate with the suspended worker excluded, and manning recomputes on every affected gang order."
        PRD §2.9: "On a gang order, `filled_headcount` recounts the assignments in `CHECKED_IN` or `WORKING` status and `offered_count` recounts those in `OFFERED` on every assignment status change"

        Design: Difficulty/transitive_cascade/worker_suspension_bump_redispatch_depth3_cascade
        """
        ns = self._setup_offered_worker()
        w1, w2 = ns.workers

        set_worker_status(w1["id"], "SUSPENDED", w1["version"])

        rows = list_assignments(gang_order_id=ns.gang["id"])
        assert len(rows) == 2, "a replacement offer is created by the cascade"
        replacement = rows[1]
        assert replacement["worker_id"] == w2["id"]
        assert replacement["status"] == "OFFERED"

        gang = get_gang(ns.gang["id"])
        assert gang["filled_headcount"] == 0
        assert gang["offered_count"] == 1


class TestPartialStoppageGate:

    def _setup_manned_gang_with_foreign_incident(self):
        """G_m MANNED (checked-in crane op + RTG booked) on an IN_PROGRESS
        shift; G_x PLACED; a MAJOR incident scoped to G_x."""
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV XDep2", "voyage_number": "X-302"},
            gang_overrides=dict(CRANE_GANG))
        gm = ns.gang
        gx = place_gang(ns.shift["id"], gang_type="LASHING_GANG",
                        required_classification="LASHER", required_headcount=1,
                        required_equipment_type="FORKLIFT",
                        required_equipment_count=0)
        w1 = register_worker(**CRANE_SPEC)
        unit = register_unit(unit_code="RTG-1", equipment_type="RTG")
        book_equipment(gm["id"], unit["id"])
        run_dispatch(gm["id"])
        start_shift(ns.shift["id"])
        a1 = list_assignments(gang_order_id=gm["id"])[0]
        check_in(a1["id"])
        assert get_gang(gm["id"])["status"] == "MANNED"
        inc = report_incident(ns.vessel["id"], scope="GANG", severity="MAJOR",
                              description="Lashing bar injury",
                              gang_order_id=gx["id"])
        return ns, gm, gx, w1, inc

    def test_start_work_blocked_by_partial_stoppage_posture(self, api):
        """PRD §2.10: "Under `PARTIAL_STOPPAGE`, starting or resuming gang work is blocked with the same error, while dispatch and check-in remain permitted."
        PRD §3.6: "Otherwise it is `PARTIAL_STOPPAGE` when any open incident is `MAJOR` at `GANG` scope."

        Design: Difficulty/cross_entity_state_dependency/start_work_blocked_by_partial_stoppage_posture
        """
        ns, gm, _gx, w1, _inc = self._setup_manned_gang_with_foreign_incident()
        assert get_vessel(ns.vessel["id"])["work_posture"] == "PARTIAL_STOPPAGE"

        resp = start_gang_work(gm["id"], w1["id"])
        validate_error(resp, ApiErrorId.ERR_WORK_STOPPAGE_ACTIVE)
        assert get_gang(gm["id"])["status"] == "MANNED", (
            "the gate blocks the transition without disturbing manning")

    def test_start_work_succeeds_after_incident_cleared(self, api):
        """PRD §3.6: "Clearing an incident, a superintendent action that moves it `REPORTED` → `CLEARED`, recomputes the posture immediately, and the posture may relax through `PARTIAL_STOPPAGE` back to `NORMAL`."
        PRD §3.5: "On a successful start the order moves to `WORKING`, every `CHECKED_IN` assignment on it becomes `WORKING`, and every `RESERVED` equipment assignment becomes `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/start_work_blocked_by_partial_stoppage_posture
        """
        ns, gm, _gx, w1, inc = self._setup_manned_gang_with_foreign_incident()
        blocked = start_gang_work(gm["id"], w1["id"])
        validate_error(blocked, ApiErrorId.ERR_WORK_STOPPAGE_ACTIVE)

        clear_incident(inc["id"])
        assert get_vessel(ns.vessel["id"])["work_posture"] == "NORMAL"

        resumed = start_gang_work(gm["id"], w1["id"])
        assert validate_success(resumed)["status"] == "WORKING"


class TestValidationPriorityPairs:

    def test_state_error_beats_safety_error_on_start_work(self, api):
        """PRD §2.5: "When several checks would fail on the same request, the failure that surfaces is determined by a fixed priority order — the first failing check wins and later checks are never evaluated for that request."
        PRD §2.10: "These gates sit at priority tier 7 in the validation order of §2.5 — after concurrency and state checks, before referential and temporal rules."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_start_work
        """
        # Gang CANCELLED (state check, tier 6) + vessel FULL_STOPPAGE (tier 7).
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Prio1", "voyage_number": "P-111"},
            gang_overrides={"required_headcount": 1})
        w1 = register_worker(full_name="W One", registration_number="R001",
                             classification="HOLDMAN", registered_on="2010-01-01",
                             base_hourly_rate_cents=4000)
        api.cancel_gang_order(ns.gang["id"], SUPT)
        report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                        description="Fire on deck")
        assert get_vessel(ns.vessel["id"])["work_posture"] == "FULL_STOPPAGE"

        resp = start_gang_work(ns.gang["id"], w1["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_priority_leaves_states_untouched(self, api):
        """PRD §2.5: "6. **State.** The target entity's current state permits the requested operation. The generic failure is `ERR_INVALID_STATE` (409); two state conditions carry their own identifiers — `ERR_SHIFT_NOT_OPEN_FOR_ORDERS` and `ERR_INVOICE_NOT_FINALIZABLE`."
        PRD §2.5: "7. **Work-stoppage gates.** The vessel's safety posture blocks the operation; failures produce `ERR_WORK_STOPPAGE_ACTIVE` (409), per §2.10."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_start_work
        """
        ns = setup_placed_gang(
            vessel_overrides={"vessel_name": "MV Prio1", "voyage_number": "P-111"},
            gang_overrides={"required_headcount": 1})
        w1 = register_worker(full_name="W One", registration_number="R001",
                             classification="HOLDMAN", registered_on="2010-01-01",
                             base_hourly_rate_cents=4000)
        api.cancel_gang_order(ns.gang["id"], SUPT)
        report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                        description="Fire on deck")

        resp = start_gang_work(ns.gang["id"], w1["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        assert get_gang(ns.gang["id"])["status"] == "CANCELLED"
        assert get_vessel(ns.vessel["id"])["work_posture"] == "FULL_STOPPAGE"

    def _setup_stoppage_with_double_booked_forced_dispatch(self):
        """Two overlapping OPEN shifts; W1 OFFERED on G1 (S1 08:00-16:00);
        G2 PLACED on S2 (12:00-20:00); vessel driven to FULL_STOPPAGE."""
        vessel = create_vessel(vessel_name="MV Prio2", voyage_number="P-112")
        berth_vessel(vessel["id"])
        s1 = create_shift(vessel["id"], period="DAY",
                          start_utc="2026-08-10T08:00:00Z",
                          end_utc="2026-08-10T16:00:00Z")
        s2 = create_shift(vessel["id"], period="NIGHT",
                          start_utc="2026-08-10T12:00:00Z",
                          end_utc="2026-08-10T20:00:00Z")
        open_shift(s1["id"])
        open_shift(s2["id"])
        g1 = place_gang(s1["id"], required_headcount=1)
        g2 = place_gang(s2["id"], required_headcount=1)
        w1 = register_worker(full_name="W One", registration_number="R001",
                             classification="HOLDMAN", registered_on="2010-01-01",
                             base_hourly_rate_cents=4000)
        run_dispatch(g1["id"])
        report_incident(vessel["id"], scope="VESSEL", severity="CRITICAL",
                        description="Fuel spill")
        return g2, w1

    def test_safety_error_beats_temporal_error_on_dispatch(self, api):
        """PRD §2.10: "These gates sit at priority tier 7 in the validation order of §2.5 — after concurrency and state checks, before referential and temporal rules."
        PRD §2.10: "Under `FULL_STOPPAGE`, dispatch batches, assignment check-ins, and starting or resuming gang work are all blocked and rejected with `ERR_WORK_STOPPAGE_ACTIVE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_dispatch
        """
        g2, w1 = self._setup_stoppage_with_double_booked_forced_dispatch()
        # W1 also fails the overlap clause (tier 9); the stoppage gate (tier 7) wins.
        resp = dispatch_batch(g2["id"], worker_ids=[w1["id"]])
        validate_error(resp, ApiErrorId.ERR_WORK_STOPPAGE_ACTIVE)

    def test_safety_priority_leaves_gang_untouched(self, api):
        """PRD §2.5: "9. **Temporal interval rules.** Worker double-booking across overlapping shift windows (`ERR_WORKER_DOUBLE_BOOKED`, 409), the equipment buffered-window rule (`ERR_EQUIPMENT_WINDOW_CONFLICT`, 409), move-record period overlap (`ERR_MOVE_PERIOD_OVERLAP`, 409), and the timesheet length cap (`ERR_TIMESHEET_EXCEEDS_SHIFT`, 422)."
        PRD §2.10: "These gates sit at priority tier 7 in the validation order of §2.5 — after concurrency and state checks, before referential and temporal rules."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_dispatch
        """
        g2, w1 = self._setup_stoppage_with_double_booked_forced_dispatch()
        resp = dispatch_batch(g2["id"], worker_ids=[w1["id"]])
        validate_error(resp, ApiErrorId.ERR_WORK_STOPPAGE_ACTIVE)

        g2_after = get_gang(g2["id"])
        assert g2_after["status"] == "PLACED"
        assert g2_after["offered_count"] == 0


class TestClearDoesNotAutoResume:

    def test_clearing_incident_does_not_auto_resume_suspended_gangs(self, api):
        """PRD §3.6: "What clearance never does is resume work by itself: gang orders that fell to `SUSPENDED` remain suspended until a foreman explicitly starts work again under the resume rules — and that explicit resume is the only path back to `WORKING`."

        Design: Corner/state_machines/clearing_incident_does_not_auto_resume_suspended_gangs
        """
        ns = setup_working_gang(
            vessel_overrides={"vessel_name": "MV NoAuto", "voyage_number": "S-105"},
            gang_overrides={"required_headcount": 1})
        inc = report_incident(ns.vessel["id"], scope="VESSEL", severity="CRITICAL",
                              description="Fire")
        assert get_gang(ns.gang["id"])["status"] == "SUSPENDED"

        clear_incident(inc["id"])
        assert get_vessel(ns.vessel["id"])["work_posture"] == "NORMAL"
        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "SUSPENDED", "no automatic resume on clearance"
        assert gang["suspension_count"] == 1


class TestGangCancelCascade:

    def test_gang_cancel_cascades_to_assignments_and_equipment(self, api):
        """PRD §3.2: "From `PLACED`, `DISPATCHING`, `MANNED`, or `SHORT_MANNED`, cancelling the order moves its assignments in `OFFERED` or `CHECKED_IN` to `CANCELLED` and releases its equipment assignments in `RESERVED`, freeing their units."
        PRD §3.2: "Every freed unit returns to `AVAILABLE` once no other non-terminal booking holds it, per §3.4."

        Design: Corner/state_machines/gang_cancel_cascades_to_assignments_and_equipment
        """
        crane_specs = [
            {"full_name": "C One", "registration_number": "R010",
             "classification": "CRANE_OPERATOR", "registered_on": "2010-01-01",
             "base_hourly_rate_cents": 5000},
            {"full_name": "C Two", "registration_number": "R011",
             "classification": "CRANE_OPERATOR", "registered_on": "2015-01-01",
             "base_hourly_rate_cents": 5000},
        ]
        ns = setup_dispatched_gang(
            vessel_overrides={"vessel_name": "MV Cancel", "voyage_number": "S-103"},
            gang_overrides={"gang_type": "CRANE_GANG",
                            "required_classification": "CRANE_OPERATOR",
                            "required_headcount": 2,
                            "required_equipment_type": "RTG",
                            "required_equipment_count": 1},
            worker_specs=crane_specs,
            equipment_specs=[{"unit_code": "RTG-1", "equipment_type": "RTG"}])
        start_shift(ns.shift["id"])
        a1, a2 = ns.assignments[0], ns.assignments[1]
        check_in(a1["id"])
        gang = get_gang(ns.gang["id"])
        assert gang["status"] == "DISPATCHING"  # filled 1 + offered 1 covers 2

        resp = api.cancel_gang_order(gang["id"], SUPT)
        assert validate_success(resp)["status"] == "CANCELLED"

        assert get_assignment(a1["id"])["status"] == "CANCELLED", (
            "CHECKED_IN assignment cancelled")
        assert get_assignment(a2["id"])["status"] == "CANCELLED", (
            "OFFERED assignment cancelled")
        ea = ns.equipment_assignments[0]
        assert get_equipment_assignment(ea["id"])["status"] == "RELEASED"
        assert get_unit(ns.equipment[0]["id"])["status"] == "AVAILABLE"
        assert get_gang(gang["id"])["filled_headcount"] == 0


class TestShiftBubbleUp:

    def test_shift_closes_automatically_when_last_gang_completes(self, api):
        """PRD §3.1: "A shift never closes by hand: it moves `IN_PROGRESS` → `CLOSED` on its own once every gang order placed on it has reached a terminal state (`COMPLETED` or `CANCELLED`), provided at least one gang order exists."
        PRD §3.5: "The completion cascade moves assignments in `CHECKED_IN` or `WORKING` to `COMPLETED` and cancels any still outstanding in `OFFERED`"

        Design: Corner/state_machines/shift_closes_automatically_when_last_gang_completes
        """
        ns = setup_working_gang(
            vessel_overrides={"vessel_name": "MV Bubble", "voyage_number": "S-104"},
            gang_overrides={"required_headcount": 1})
        assert ns.shift["status"] == "IN_PROGRESS"

        gang = complete_gang(ns.gang["id"], ns.foreman_id)
        assert gang["status"] == "COMPLETED"

        assert get_shift(ns.shift["id"])["status"] == "CLOSED", (
            "bubble-up: no explicit close call was made")
        a1 = [a for a in ns.assignments if a["status"] == "WORKING"][0]
        assert get_assignment(a1["id"])["status"] == "COMPLETED"
