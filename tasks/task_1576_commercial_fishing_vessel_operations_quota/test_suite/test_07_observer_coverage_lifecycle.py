"""Observer coverage: rest-buffer overlap, assignment lifecycle gates,
certification, debrief gating of landing verification, waiver, release
compensation, and observer-version OCC (PRD §3.5, §3.6, §2.6)."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    create_opening,
    declare_and_submit,
    get_assignment,
    get_observer,
    get_trip_assignment,
    list_trip_assignments,
    make_captain_headers,
    make_observer_headers,
    make_vessel_owner_headers,
    plan_trip,
    register_observer,
    setup_trip_with_confirmed_observer,
    setup_vessel_ready,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _setup_two_observer_trips():
    """Two PARTIAL vessels each with a 120h observer-required trip; returns ctx."""
    v1 = setup_vessel_ready()["vessel"]
    v2 = setup_vessel_ready(vessel_name="FV Bristol", home_port="KODIAK")["vessel"]
    opening = create_opening()
    trip_a = plan_trip(v1["id"], opening["id"],
                       departure="2026-08-10T00:00:00Z",
                       return_="2026-08-15T00:00:00Z")
    trip_b = plan_trip(v2["id"], opening["id"],
                       departure="2026-08-16T00:00:00Z",
                       return_="2026-08-21T00:00:00Z")
    observer = register_observer(certification_level="B")
    a_a = get_trip_assignment(trip_a["id"])
    a_b = get_trip_assignment(trip_b["id"])
    return v1, v2, opening, trip_a, trip_b, observer, a_a, a_b


class TestRestBuffer:
    def test_assign_within_24h_rest_buffer_rejected(self):
        """PRD §3.6: "Double-booking is checked against the observer's other
        assignments in `ASSIGNED`, `CONFIRMED`, or `DEPLOYED`, with a 24-hour rest
        buffer after each assignment: the new window must begin no earlier than 24
        hours after the end of an existing committed window, or end no later than 24
        hours before one begins; anything closer is `ERR_OBSERVER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/observer_assignment_rest_buffer_overlap
        """
        (_v1, _v2, _opening, _trip_a, _trip_b, observer,
         a_a, a_b) = _setup_two_observer_trips()
        validate_success(api_client.assign_observer(
            a_a["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-15T00:00:00Z",
             "expected_observer_version": observer["version"]},
            COORD), 200)
        current_observer = get_observer(observer["id"])
        resp = api_client.assign_observer(
            a_b["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-15T23:00:00Z",  # only 23h of rest
             "coverage_to": "2026-08-21T00:00:00Z",
             "expected_observer_version": current_observer["version"]},
            COORD)
        validate_error(resp, "ERR_OBSERVER_DOUBLE_BOOKED", 409)
        assert get_assignment(a_b["id"])["status"] == "REQUESTED"

    def test_assign_at_exactly_24h_rest_succeeds(self):
        """PRD §3.6: "the new window must begin no earlier than 24 hours after the
        end of an existing committed window" — a start exactly 24 hours later
        satisfies the buffer; and "A successful assignment moves the request to
        `ASSIGNED`, stamps the observer and window onto it, flips the observer to
        `ON_ASSIGNMENT`, and increments the observer's `version`."

        Design: Difficulty/resource_temporal_overlap/observer_assignment_rest_buffer_overlap
        """
        (_v1, _v2, _opening, _trip_a, _trip_b, observer,
         a_a, a_b) = _setup_two_observer_trips()
        assigned_a = validate_success(api_client.assign_observer(
            a_a["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-15T00:00:00Z",
             "expected_observer_version": observer["version"]},
            COORD), 200)
        assert assigned_a["status"] == "ASSIGNED"
        assert get_observer(observer["id"])["status"] == "ON_ASSIGNMENT"
        current_observer = get_observer(observer["id"])
        assigned_b = validate_success(api_client.assign_observer(
            a_b["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-16T00:00:00Z",  # exactly +24h
             "coverage_to": "2026-08-21T00:00:00Z",
             "expected_observer_version": current_observer["version"]},
            COORD), 200)
        assert assigned_b["status"] == "ASSIGNED"


class TestVerifyObserverGate:
    def test_verify_blocked_until_observer_debriefs(self):
        """PRD §3.5: "Second, the observer gate: the trip's observer requirement
        must be resolved — not required, waived, or an assignment of the trip in
        `DEBRIEFED` (`ERR_OBSERVER_NOT_DEBRIEFED`)."

        Design: Difficulty/cross_entity_state_dependency/verify_gated_by_observer_debrief
        """
        ctx = setup_trip_with_confirmed_observer(
            coverage_from="2026-08-10T00:00:00Z", coverage_to="2026-08-12T06:00:00Z")
        vessel_id = ctx["vessel"]["id"]
        captain = make_captain_headers(vessel_id)
        advance_clock("2026-08-10T06:00:00Z")
        validate_success(api_client.depart_trip(ctx["trip"]["id"], captain), 200)
        api_client.create_catch_report(
            ctx["trip"]["id"],
            {"fishery_code": "HALIBUT", "report_type": "HARVEST",
             "reported_lbs": 3000, "reported_at": "2026-08-11T06:00:00Z"},
            captain)
        advance_clock("2026-08-12T06:00:00Z")
        validate_success(api_client.return_trip(ctx["trip"]["id"], captain), 200)
        declaration = declare_and_submit(ctx["trip"]["id"], vessel_id,
                                         declared_lbs=3000)
        # Assignment is DEPLOYED (advanced at depart), not yet DEBRIEFED.
        assert get_assignment(ctx["assignment"]["id"])["status"] == "DEPLOYED"
        resp = api_client.verify_landing_declaration(declaration["id"], REG)
        validate_error(resp, "ERR_OBSERVER_NOT_DEBRIEFED", 409)
        validate_success(api_client.debrief_observer_assignment(
            ctx["assignment"]["id"], make_observer_headers(ctx["observer"]["id"])), 200)
        verified = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert verified["status"] == "VERIFIED"

    def test_waived_observer_requirement_allows_verify(self):
        """PRD §3.5: the observer gate is resolved when the requirement is "not
        required, waived, or an assignment of the trip in `DEBRIEFED`";
        PRD §3.6: "A regulator may instead waive a `REQUESTED` assignment
        (`ERR_ASSIGNMENT_NOT_REQUESTED` otherwise), moving it to `WAIVED` and
        setting the trip's `observer_waived` to true."

        Design: Difficulty/cross_entity_state_dependency/verify_gated_by_observer_debrief
        """
        ctx = setup_vessel_ready(holding_pounds=10000)
        opening = create_opening()
        # 100h trip on a PARTIAL vessel: observer-required.
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")
        assert trip["observer_required"] is True
        assignment = get_trip_assignment(trip["id"])
        waived = validate_success(
            api_client.waive_observer_assignment(assignment["id"], REG), 200)
        assert waived["status"] == "WAIVED"
        captain = make_captain_headers(ctx["vessel"]["id"])
        advance_clock("2026-08-10T06:00:00Z")
        validate_success(api_client.depart_trip(trip["id"], captain), 200)
        api_client.create_catch_report(
            trip["id"],
            {"fishery_code": "HALIBUT", "report_type": "HARVEST",
             "reported_lbs": 3000, "reported_at": "2026-08-11T06:00:00Z"},
            captain)
        advance_clock("2026-08-14T06:00:00Z")
        validate_success(api_client.return_trip(trip["id"], captain), 200)
        declaration = declare_and_submit(trip["id"], ctx["vessel"]["id"],
                                         declared_lbs=3000)
        verified = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert verified["status"] == "VERIFIED"


class TestAssignmentLifecycleGates:
    def test_observer_cert_insufficient_rejected(self):
        """PRD §3.6: "Certification must match the vessel's coverage class: a `FULL`
        vessel requires level `A`; a `PARTIAL` vessel requires `A` or `B`; an
        `EXEMPT` vessel accepts any level. Insufficient certification is rejected
        with `ERR_OBSERVER_CERT_INSUFFICIENT` (HTTP 422)."

        Design: Corner/state_machines/observer_cert_insufficient_rejected
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")  # 100h -> required
        observer = register_observer(observer_name="Obs Junior",
                                     certification_level="C")
        assignment = get_trip_assignment(trip["id"])
        resp = api_client.assign_observer(
            assignment["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-14T06:00:00Z",
             "expected_observer_version": observer["version"]},
            COORD)
        validate_error(resp, "ERR_OBSERVER_CERT_INSUFFICIENT", 422)
        assert get_assignment(assignment["id"])["status"] == "REQUESTED"

    def test_debrief_assigned_assignment_rejected(self):
        """PRD §3.6: the observer debriefs "moving from `DEPLOYED` to `DEBRIEFED`
        (`ERR_ASSIGNMENT_NOT_DEPLOYED` from elsewhere)".

        Design: Corner/state_machines/debrief_assigned_assignment_rejected
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")  # 100h -> required
        observer = register_observer(certification_level="B")
        assignment = get_trip_assignment(trip["id"])
        assigned = validate_success(api_client.assign_observer(
            assignment["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-14T06:00:00Z",
             "expected_observer_version": observer["version"]},
            COORD), 200)
        assert assigned["status"] == "ASSIGNED"
        resp = api_client.debrief_observer_assignment(
            assignment["id"], make_observer_headers(observer["id"]))
        validate_error(resp, "ERR_ASSIGNMENT_NOT_DEPLOYED", 409)

    def test_release_triggers_compensating_re_request(self):
        """PRD §3.6: "Release carries a compensating action: if the trip is still
        `PLANNED`, still observer-required, and not waived, a fresh assignment in
        `REQUESTED` is auto-created for the trip so coverage is re-sought rather
        than silently dropped." and "A coordinator may release a `CONFIRMED`
        assignment — `ERR_ASSIGNMENT_NOT_CONFIRMABLE` otherwise — moving it to
        `RELEASED` and recomputing the observer's availability."

        Design: Corner/state_machines/release_triggers_compensating_re_request
        """
        ctx = setup_trip_with_confirmed_observer(
            observer_coverage_class="PARTIAL", certification_level="B",
            departure="2026-08-10T06:00:00Z", return_="2026-08-14T06:00:00Z",
            coverage_from="2026-08-10T00:00:00Z", coverage_to="2026-08-14T06:00:00Z")
        assert ctx["trip"]["observer_required"] is True
        released = validate_success(api_client.release_observer_assignment(
            ctx["assignment"]["id"], COORD), 200)
        assert released["status"] == "RELEASED"
        assignments = list_trip_assignments(ctx["trip"]["id"])
        assert len(assignments) == 2, (
            f"expected the released row plus a fresh REQUESTED row, got {len(assignments)}")
        statuses = sorted(a["status"] for a in assignments)
        assert statuses == ["RELEASED", "REQUESTED"]
        fresh = [a for a in assignments if a["status"] == "REQUESTED"][0]
        assert fresh["id"] != ctx["assignment"]["id"]
        assert fresh["observer_id"] is None
        assert get_observer(ctx["observer"]["id"])["status"] == "AVAILABLE"


class TestObserverOcc:
    def test_occ_observer_assign_stale_version(self):
        """PRD §2.6: "Assigning an observer to an assignment requires
        `expected_observer_version`, matching the target `Observer`'s current
        `version`. The caller is selecting an observer from an availability
        picture; if that observer's version has advanced since the caller last
        read it (for example, the observer has since been assigned elsewhere),
        the write is refused rather than allowed to proceed on a stale picture."
        PRD §2.6: "In all four cases, a value that does not match the parent
        entity's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_observer_assign_stale_version
        """
        ctx = setup_vessel_ready()
        opening = create_opening(closes_at="2026-08-31T00:00:00Z")
        observer = register_observer(certification_level="A")
        trip_a = plan_trip(ctx["vessel"]["id"], opening["id"],
                           departure="2026-08-10T00:00:00Z",
                           return_="2026-08-15T00:00:00Z")
        trip_b = plan_trip(ctx["vessel"]["id"], opening["id"],
                           departure="2026-08-17T00:00:00Z",
                           return_="2026-08-22T00:00:00Z")
        a_a = get_trip_assignment(trip_a["id"])
        a_b = get_trip_assignment(trip_b["id"])
        stale_version = observer["version"]
        validate_success(api_client.assign_observer(
            a_a["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-15T00:00:00Z",
             "expected_observer_version": stale_version},
            COORD), 200)
        resp = api_client.assign_observer(
            a_b["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-17T00:00:00Z",
             "coverage_to": "2026-08-22T00:00:00Z",
             "expected_observer_version": stale_version},
            COORD)
        validate_error(resp, "ERR_STALE_VERSION", 412)
        assert get_assignment(a_b["id"])["status"] == "REQUESTED"

    def test_rbac_owner_cannot_assign_observer(self):
        """PRD §4: POST /observer-assignments/{id}/assign lists only
        ObserverCoordinator; PRD §2.1: "a role that is not listed for the endpoint
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

        Design: Corner/rbac/rbac_owner_cannot_assign_observer
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")
        observer = register_observer(certification_level="B")
        assignment = get_trip_assignment(trip["id"])
        resp = api_client.assign_observer(
            assignment["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-14T06:00:00Z",
             "expected_observer_version": observer["version"]},
            make_vessel_owner_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)
        assert get_assignment(assignment["id"])["status"] == "REQUESTED"
