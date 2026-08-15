"""Dispatch ordering, the assignment gate chain, and the fill-band aggregate."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_order,
    add_aircraft,
    add_carded_pilot,
    assert_filled_count_invariant,
    card_aircraft,
    create_active_contract,
    create_assignment,
    create_incident,
    demobilize_assignment,
    get_assignment,
    get_order,
    launch_assignment,
    arrive_assignment,
    log_sortie,
    place_order,
    release_assignment,
    set_clock,
    setup_accepted_order,
    setup_carded_pair,
    setup_on_incident,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]
DISPATCH = TEST_USERS["agency_dispatcher_headers"]


def _parse_instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestAcceptanceWindow:
    def test_acceptance_deadline_inclusive_boundary(self, api):
        """PRD §3.4: "The order records `placed_at` from the logical clock,
        computes `accept_deadline` as `placed_at` plus the contract's
        `acceptance_window_minutes`, and is born `PLACED`".
        PRD §3.4: "exactly at the deadline is allowed, while a later acceptance
        is `ERR_ACCEPTANCE_WINDOW_EXPIRED`."

        Design: Corner/validations/acceptance_window_deadline_boundary
        """
        contract = create_active_contract()  # acceptance_window_minutes 30
        incident = create_incident()

        # Placed at the default clock 2026-08-01T00:00:00Z.
        order1 = place_order(contract["id"], incident["id"],
                             order_number="O-1001")
        assert _parse_instant(order1["accept_deadline"]) == datetime(
            2026, 8, 1, 0, 30, tzinfo=timezone.utc), \
            "accept_deadline is placed_at plus the acceptance window"

        set_clock("2026-08-01T00:30:00Z")
        order2 = place_order(contract["id"], incident["id"],
                             order_number="O-1002")
        assert _parse_instant(order2["accept_deadline"]) == datetime(
            2026, 8, 1, 1, 0, tzinfo=timezone.utc)

        accepted = validate_success(api.accept_dispatch_order(order1["id"], OPS), 200)
        assert accepted["status"] == "ACCEPTED", \
            "acceptance exactly at the deadline is allowed"

        set_clock("2026-08-01T01:01:00Z")
        resp = api.accept_dispatch_order(order2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_WINDOW_EXPIRED,
                       expected_status=422)


class TestAcceptRequiresActiveContract:
    def test_accept_rejected_when_contract_suspended(self, api):
        """PRD §3.4: "Acceptance — `PLACED` → `ACCEPTED` by `CarrierOps` —
        requires the contract still `ACTIVE` and the clock at or before
        `accept_deadline`".
        PRD §2.9: "a contract must be `ACTIVE` to accept new business
        (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/dispatch_accept_requires_active_contract
        """
        contract = create_active_contract()
        incident = create_incident()
        order = place_order(contract["id"], incident["id"])
        assert order["status"] == "PLACED"

        validate_success(api.suspend_contract(contract["id"], OPS), 200)

        resp = api.accept_dispatch_order(order["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                       expected_status=409)

        after = get_order(order["id"])
        assert after["status"] == "PLACED", "rejected accept leaves the order PLACED"

    def test_accept_succeeds_within_window_on_active_contract(self, api):
        """PRD §3.4: "Acceptance — `PLACED` → `ACCEPTED` by `CarrierOps` —
        requires the contract still `ACTIVE` and the clock at or before
        `accept_deadline`; exactly at the deadline is allowed".
        PRD §2.7: "Before any explicit set, the clock starts at exactly
        2026-08-01T00:00:00Z".

        Design: Difficulty/cross_entity_state_dependency/dispatch_accept_requires_active_contract
        """
        contract = create_active_contract()
        incident = create_incident()
        order = place_order(contract["id"], incident["id"])
        v0 = order["version"]

        # Same setup as the suspended-contract case, minus the suspension:
        # the order is well inside its window, so acceptance succeeds.
        accepted = validate_success(api.accept_dispatch_order(order["id"], OPS), 200)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["version"] == v0 + 1


class TestAssignmentCapacityAndOcc:
    def test_dispatch_already_filled_rejected(self, api):
        """PRD §3.5: "The order must be non-terminal and not yet full: when
        `filled_count` already equals `aircraft_quantity`, creation is refused
        with `ERR_DISPATCH_ALREADY_FILLED`."

        Design: Corner/validations/dispatch_already_filled_rejected
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=1)
        create_assignment(order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")

        order = get_order(order["id"])
        assert order["filled_count"] == 1
        assert order["status"] == "FILLED"

        # Fresh OCC version: the refusal is the capacity state check.
        resp = api.create_assignment(order["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": pilot2["id"],
            "planned_start": "2026-08-04T12:00:00Z",
            "planned_end": "2026-08-04T14:00:00Z",
            "expected_dispatch_order_version": order["version"],
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_ALREADY_FILLED,
                       expected_status=409)

    def test_occ_assignment_create_stale_version(self, api):
        """PRD §2.8: "Creating an assignment under a dispatch order requires
        `expected_dispatch_order_version`, the order `version` the client last
        observed. Because accepted assignment creations and release cascades
        advance the order's version, a create carrying a previously observed
        version is stale and is likewise refused with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_assignment_create_stale_version
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=2)
        stale_version = order["version"]

        create_assignment(order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")

        # Stale: the pre-first-assignment version, though capacity remains.
        resp = api.create_assignment(order["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": pilot2["id"],
            "planned_start": "2026-08-04T10:00:00Z",
            "planned_end": "2026-08-04T12:00:00Z",
            "expected_dispatch_order_version": stale_version,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        fresh_version = get_order(order["id"])["version"]
        assert fresh_version == stale_version + 1, \
            "the accepted assignment creation advanced the order version by 1"
        created = validate_success(api.create_assignment(order["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": pilot2["id"],
            "planned_start": "2026-08-04T10:00:00Z",
            "planned_end": "2026-08-04T12:00:00Z",
            "expected_dispatch_order_version": fresh_version,
        }, OPS), 201)
        assert created["status"] == "ASSIGNED"
        order = get_order(order["id"])
        assert order["filled_count"] == 2
        assert order["status"] == "FILLED"


class TestModelGates:
    def test_assignment_model_gates(self, api):
        """PRD §3.5: "The aircraft and the pilot must both belong to the
        order's contract (`ERR_AIRCRAFT_NOT_ON_CONTRACT`,
        `ERR_PILOT_NOT_ON_CONTRACT`); when the order names a `required_model`,
        the aircraft's `model` must equal it (`ERR_MODEL_MISMATCH`); and the
        aircraft's model must appear in the pilot's
        `qualified_aircraft_models` (`ERR_MODEL_NOT_QUALIFIED`)."

        Design: Corner/validations/assignment_model_gates
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"], models=["S-70I"])
        order1 = setup_accepted_order(ws, quantity=1, required_model="S-70I",
                                      order_number="O-1001")
        order2 = setup_accepted_order(ws, quantity=1, order_number="O-1002")

        v1 = get_order(order1["id"])["version"]
        resp1 = api.create_assignment(order1["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": ws["pilot"]["id"],
            "planned_start": "2026-08-04T08:00:00Z",
            "planned_end": "2026-08-04T09:00:00Z",
            "expected_dispatch_order_version": v1,
        }, OPS)
        validate_error(resp1, ApiErrorId.ERR_MODEL_MISMATCH, expected_status=422)

        v2 = get_order(order2["id"])["version"]
        resp2 = api.create_assignment(order2["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": pilot2["id"],
            "planned_start": "2026-08-04T08:00:00Z",
            "planned_end": "2026-08-04T09:00:00Z",
            "expected_dispatch_order_version": v2,
        }, OPS)
        validate_error(resp2, ApiErrorId.ERR_MODEL_NOT_QUALIFIED,
                       expected_status=422)


class TestAircraftWindowOverlap:
    def test_adjacent_windows_allowed_same_aircraft(self, api):
        """PRD §3.5: "The aircraft's planned window is compared half-openly
        against every non-terminal assignment of the same aircraft — any
        assignment that has not reached `DEMOBILIZED`."
        PRD §3.5: "Overlapping windows are `ERR_ASSIGNMENT_OVERLAP`;
        back-to-back windows that merely touch are allowed."
        PRD §3.4: "reaching exactly the requested quantity moves it to
        `FILLED`".

        Design: Difficulty/resource_temporal_overlap/aircraft_window_half_open_adjacency
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=2)

        create_assignment(order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")
        adjacent = create_assignment(
            order["id"], ws["aircraft"]["id"], pilot2["id"],
            "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z")
        assert adjacent["status"] == "ASSIGNED", \
            "a window starting at the exact instant another ends is allowed"

        order = get_order(order["id"])
        assert order["filled_count"] == 2
        assert order["status"] == "FILLED"

    def test_intersecting_window_rejected_same_aircraft(self, api):
        """PRD §3.5: "Overlapping windows are `ERR_ASSIGNMENT_OVERLAP`;
        back-to-back windows that merely touch are allowed."

        Design: Difficulty/resource_temporal_overlap/aircraft_window_half_open_adjacency
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=2)
        create_assignment(order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")
        create_assignment(order["id"], ws["aircraft"]["id"], pilot2["id"],
                          "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z")

        # 09:00-11:00 genuinely intersects both existing windows.
        order2 = setup_accepted_order(ws, quantity=1, order_number="O-1002")
        v = get_order(order2["id"])["version"]
        resp = api.create_assignment(order2["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": pilot2["id"],
            "planned_start": "2026-08-04T09:00:00Z",
            "planned_end": "2026-08-04T11:00:00Z",
            "expected_dispatch_order_version": v,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP,
                       expected_status=409)


class TestPilotRestGap:
    def test_thirty_minute_gap_rejected_as_rest_violation(self, api):
        """PRD §3.5: "The pilot must carry a sixty-minute buffer around the
        new window in both directions: every non-terminal assignment window of
        the pilot must end at least sixty minutes before the candidate's
        `planned_start`, or begin at least sixty minutes after its
        `planned_end`. Mere adjacency is not rest, and a violation is
        `ERR_DUTY_REST_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/pilot_window_minimum_rest_gap
        """
        ws = setup_carded_pair()
        aircraft2 = carded_second_aircraft(ws)
        order1 = setup_accepted_order(ws, quantity=1, order_number="O-1001")
        create_assignment(order1["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z")

        order2 = setup_accepted_order(ws, quantity=1, order_number="O-1002")
        v = get_order(order2["id"])["version"]
        resp = api.create_assignment(order2["id"], {
            "aircraft_id": aircraft2["id"], "pilot_id": ws["pilot"]["id"],
            "planned_start": "2026-08-05T10:30:00Z",
            "planned_end": "2026-08-05T12:00:00Z",
            "expected_dispatch_order_version": v,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_DUTY_REST_VIOLATION,
                       expected_status=422)

        data, meta = validate_paginated(
            api.list_assignments(OPS, params={"pilot_id": ws["pilot"]["id"]}))
        assert meta["total_count"] == 1, "the rejected attempt leaves no residue"

    def test_exactly_sixty_minute_gap_allowed(self, api):
        """PRD §3.5: "every non-terminal assignment window of the pilot must
        end at least sixty minutes before the candidate's `planned_start`, or
        begin at least sixty minutes after its `planned_end`."

        Design: Difficulty/resource_temporal_overlap/pilot_window_minimum_rest_gap
        """
        ws = setup_carded_pair()
        aircraft2 = carded_second_aircraft(ws)
        order1 = setup_accepted_order(ws, quantity=1, order_number="O-1001")
        create_assignment(order1["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z")

        order2 = setup_accepted_order(ws, quantity=1, order_number="O-1002")
        created = create_assignment(
            order2["id"], aircraft2["id"], ws["pilot"]["id"],
            "2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z")
        assert created["status"] == "ASSIGNED", \
            "a gap of exactly sixty minutes satisfies the rest buffer"

        data, meta = validate_paginated(
            api.list_assignments(OPS, params={"pilot_id": ws["pilot"]["id"]}))
        assert meta["total_count"] == 2


class TestCrewDayLimit:
    def test_crew_day_limit_840_boundary(self, api):
        """PRD §3.5: "Independently, the duty-day span — the candidate's
        `planned_end` minus the duty day's `duty_start` — must not exceed 840
        minutes, fourteen hours; exactly 840 is allowed and anything beyond is
        `ERR_CREW_DAY_LIMIT_EXCEEDED`."

        Design: Corner/validations/crew_day_limit_840_boundary
        """
        ws = setup_carded_pair()
        order1 = setup_accepted_order(ws, quantity=2, order_number="O-1001")
        # 06:00 -> 20:00 spans exactly 840 minutes across two sparse windows.
        create_assignment(order1["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
                          "2026-08-06T06:00:00Z", "2026-08-06T07:00:00Z")
        late = create_assignment(order1["id"], ws["aircraft"]["id"],
                                 ws["pilot"]["id"],
                                 "2026-08-06T19:00:00Z", "2026-08-06T20:00:00Z")
        assert late["status"] == "ASSIGNED", "a span of exactly 840 minutes is allowed"

        order2 = setup_accepted_order(ws, quantity=1, order_number="O-1002")
        v = get_order(order2["id"])["version"]
        resp = api.create_assignment(order2["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": ws["pilot"]["id"],
            "planned_start": "2026-08-06T20:30:00Z",
            "planned_end": "2026-08-06T20:31:00Z",
            "expected_dispatch_order_version": v,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_CREW_DAY_LIMIT_EXCEEDED,
                       expected_status=422)


class TestAssignmentLifecycle:
    def test_assignment_happy_path_walk_and_order_autoclose(self, api):
        """PRD §3.6: "Launch moves an assignment `ASSIGNED` → `EN_ROUTE`";
        "Arrival then moves the assignment `EN_ROUTE` → `ON_INCIDENT`";
        "Finally, `CarrierOps` demobilizes a `RELEASED` assignment, stamping
        `demobilized_at`".
        PRD §3.4: "When a demobilization leaves every assignment of an order
        in `DEMOBILIZED` — and at least one assignment exists — the order
        closes itself from whichever of `ACCEPTED`, `PARTIALLY_FILLED`, or
        `FILLED` it occupies."
        PRD §2.7: "Every system-stamped instant — `placed_at`, `assigned_at`,
        `launched_at`, `arrived_at`, `released_at`, `demobilized_at`,
        `submitted_at` — reads this clock".

        Design: Corner/state_machines/assignment_happy_path_walk_and_order_autoclose
        """
        ws = setup_carded_pair()
        order = setup_accepted_order(ws, quantity=1)
        assignment = create_assignment(
            order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")
        clock_default = datetime(2026, 8, 1, tzinfo=timezone.utc)

        launched = launch_assignment(assignment["id"], ws["pilot"]["id"])
        assert launched["status"] == "EN_ROUTE"
        assert _parse_instant(launched["launched_at"]) == clock_default

        arrived = arrive_assignment(assignment["id"], ws["pilot"]["id"])
        assert arrived["status"] == "ON_INCIDENT"
        assert _parse_instant(arrived["arrived_at"]) == clock_default

        released = release_assignment(assignment["id"], reason="AGENCY")
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "AGENCY"
        assert _parse_instant(released["released_at"]) == clock_default

        demobilized = demobilize_assignment(assignment["id"])
        assert demobilized["status"] == "DEMOBILIZED"
        assert _parse_instant(demobilized["demobilized_at"]) == clock_default

        order = get_order(order["id"])
        assert order["status"] == "CLOSED", \
            "demobilizing the order's last assignment closes the order"


class TestFillBandConservation:
    def test_fill_band_walks_up_on_assignment_creation(self, api):
        """PRD §3.4: "`filled_count` always equals the number of the order's
        assignments currently in `ASSIGNED`, `EN_ROUTE`, or `ON_INCIDENT`.
        Creating an assignment that leaves the count short of
        `aircraft_quantity` moves the band to `PARTIALLY_FILLED`; reaching
        exactly the requested quantity moves it to `FILLED`".

        Design: Difficulty/compensating_invariant/assignment_create_release_conserve_filled_count
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=2)
        assert order["filled_count"] == 0
        assert order["status"] == "ACCEPTED"

        a1 = create_assignment(order["id"], ws["aircraft"]["id"],
                               ws["pilot"]["id"],
                               "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")
        order = get_order(order["id"])
        assert (order["filled_count"], order["status"]) == (1, "PARTIALLY_FILLED")
        assert_filled_count_invariant(order, [a1])

        a2 = create_assignment(order["id"], ws["aircraft"]["id"], pilot2["id"],
                               "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z")
        order = get_order(order["id"])
        assert (order["filled_count"], order["status"]) == (2, "FILLED")
        assert_filled_count_invariant(order, [a1, a2])

    def test_fill_band_walks_down_on_release_to_accepted(self, api):
        """PRD §3.4: "a release that drops a `FILLED` order back below
        quantity returns it to `PARTIALLY_FILLED`; and a release that empties
        a partially filled order returns it to `ACCEPTED`. The band therefore
        behaves like a compensating pair around any create-then-release
        sequence: count and derived status end exactly where they began."

        Design: Difficulty/compensating_invariant/assignment_create_release_conserve_filled_count
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=2)
        a1 = create_assignment(order["id"], ws["aircraft"]["id"],
                               ws["pilot"]["id"],
                               "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")
        a2 = create_assignment(order["id"], ws["aircraft"]["id"], pilot2["id"],
                               "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z")
        assert get_order(order["id"])["status"] == "FILLED"

        release_assignment(a1["id"], reason="AGENCY")
        order = get_order(order["id"])
        assert (order["filled_count"], order["status"]) == (1, "PARTIALLY_FILLED")
        assert_filled_count_invariant(
            order, [get_assignment(a1["id"]), get_assignment(a2["id"])])

        release_assignment(a2["id"], reason="AGENCY")
        order = get_order(order["id"])
        assert (order["filled_count"], order["status"]) == (0, "ACCEPTED"), \
            "the create+release pair conserves count and derived status"
        assert_filled_count_invariant(
            order, [get_assignment(a1["id"]), get_assignment(a2["id"])])


class TestDispatchPriorityPairs:
    def test_dispatch_create_state_beats_fiscal(self, api):
        """PRD §2.9: "checks run in a fixed priority order, and the earliest
        failing check produces the response" — state-machine legality (step 7,
        `ERR_CONTRACT_NOT_ACTIVE`) precedes the season flight-hour cap
        (step 13, `ERR_SEASON_FLIGHT_CAP_EXCEEDED`).
        PRD §3.4: "Placement is gated by the season flight-hour cap — the
        contract's `season_flight_hours_tenths` must still be below
        `season_flight_hour_cap_tenths`, otherwise the order is refused with
        `ERR_SEASON_FLIGHT_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_create_state_beats_fiscal
        """
        # Cap 10 tenths; one 1.0 h sortie brings the season to exactly 10.
        ws = setup_on_incident(
            contract_overrides={"season_flight_hour_cap_tenths": 10},
            planned_start="2026-08-02T08:00:00Z",
            planned_end="2026-08-02T09:00:00Z")
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 0.0, 1.0)

        validate_success(api.suspend_contract(ws["contract"]["id"], OPS), 200)

        # Both rules fail: the state check must answer first.
        resp = api.create_dispatch_order(
            {"order_number": "O-1002", "contract_id": ws["contract"]["id"],
             "incident_id": ws["incident"]["id"], "aircraft_quantity": 1},
            DISPATCH)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                       expected_status=409)

    def test_dispatch_create_fiscal_gate_in_isolation(self, api):
        """PRD §3.4: "Placement is gated by the season flight-hour cap — the
        contract's `season_flight_hours_tenths` must still be below
        `season_flight_hour_cap_tenths`, otherwise the order is refused with
        `ERR_SEASON_FLIGHT_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_create_state_beats_fiscal
        """
        ws = setup_on_incident(
            contract_overrides={"season_flight_hour_cap_tenths": 10},
            planned_start="2026-08-02T08:00:00Z",
            planned_end="2026-08-02T09:00:00Z")
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 0.0, 1.0)

        from test_helpers import get_contract
        contract = get_contract(ws["contract"]["id"])
        assert contract["season_flight_hours_tenths"] == 10, \
            "cap reached (not exceeded): the fiscal condition genuinely holds"

        # Without the suspension, the same placement fails on the fiscal gate.
        resp = api.create_dispatch_order(
            {"order_number": "O-1002", "contract_id": ws["contract"]["id"],
             "incident_id": ws["incident"]["id"], "aircraft_quantity": 1},
            DISPATCH)
        validate_error(resp, ApiErrorId.ERR_SEASON_FLIGHT_CAP_EXCEEDED,
                       expected_status=422)

    def test_fatigue_hold_beats_wrong_contract_on_assignment(self, api):
        """PRD §2.9: "checks run in a fixed priority order, and the earliest
        failing check produces the response" — flight safety (step 8,
        `ERR_CREW_ON_FATIGUE_HOLD`) precedes linkage and qualification
        (step 11, `ERR_PILOT_NOT_ON_CONTRACT`).
        PRD §3.5: "A pilot on `FATIGUE_HOLD` may not be assigned at all
        (`ERR_CREW_ON_FATIGUE_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/assignment_create_safety_beats_referential
        """
        ws1, p1 = _fatigued_pilot_workspace()
        # Second ACTIVE contract with its own carded aircraft; p1 is NOT
        # registered on it, so the referential gate also fails.
        contract2 = create_active_contract(contract_number="EU-2026-002")
        aircraft2 = add_aircraft(contract2["id"], tail_number="N200AF")
        card_aircraft(aircraft2["id"])
        incident = ws1["incident"]
        order2 = accept_order(place_order(
            contract2["id"], incident["id"], order_number="O-1002")["id"])

        v = get_order(order2["id"])["version"]
        resp = api.create_assignment(order2["id"], {
            "aircraft_id": aircraft2["id"], "pilot_id": p1["id"],
            "planned_start": "2026-08-10T08:00:00Z",
            "planned_end": "2026-08-10T09:00:00Z",
            "expected_dispatch_order_version": v,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_CREW_ON_FATIGUE_HOLD,
                       expected_status=422)

    def test_eight_hours_exactly_triggers_fatigue_hold(self, api):
        """PRD §3.6: "refuses the log with `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED`
        when the day total including the new sortie would exceed 80 tenths;
        exactly 80 is accepted."
        PRD §3.6: "the moment a log raises a duty day's `flown_tenths` to 80
        or more, a four-link cascade fires. The duty day absorbs the new
        tenths; the crew member's `duty_status` flips to `FATIGUE_HOLD`".

        Design: Difficulty/priority_pair_validation_conflict/assignment_create_safety_beats_referential
        """
        ws, p1 = _fatigued_pilot_workspace()
        assert p1["duty_status"] == "FATIGUE_HOLD", \
            "the 8.0 h sortie was accepted and pushed the pilot onto hold"


def carded_second_aircraft(ws):
    """Register and card a second aircraft on the workspace contract."""
    from test_helpers import add_aircraft, card_aircraft
    aircraft2 = add_aircraft(ws["contract"]["id"], tail_number="N200AF")
    return card_aircraft(aircraft2["id"])


def _fatigued_pilot_workspace():
    """Carded pair whose pilot has logged exactly 8.0 h (80 tenths) on
    2026-08-02 — the accepted sortie puts the pilot on FATIGUE_HOLD."""
    from test_helpers import get_crew_member
    ws = setup_on_incident(
        planned_start="2026-08-02T08:00:00Z",
        planned_end="2026-08-02T10:00:00Z")
    log = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                     "2026-08-02", 0.0, 8.0)
    assert log["flight_hours_tenths"] == 80
    p1 = get_crew_member(ws["pilot"]["id"])
    return ws, p1
