"""Seating chart, rain-plan cascades, accessible-seat pool, withdrawal seat
eviction, and seat inventory conservation."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, api_client,
    setup_ceremony, setup_ceremony_with_graduates, import_graduate,
    assign_seat, get_ceremony, get_graduate, list_ceremony_seats,
    get_graduate_allocation, run_waterfall,
    create_accommodation_request_payload, create_seat_assignment_payload,
    make_graduate_headers, make_coordinator_headers, TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COORDINATOR = TEST_USERS["venue_coordinator_headers"]
COORD_A = "coord-a"


def _setup_rain_eviction():
    """Main venue cap 6 (accessible 2), rain venue cap 4 (accessible 1);
    six eligible graduates (SUMMA, MAGNA, CUM, NONE x3); AUDIT_LOCKED; seating
    sweep assigns all six (A/1/1..A/1/4, A/2/1..A/2/2)."""
    ctx = setup_ceremony_with_graduates(
        [
            {"full_name": "G1 Summa", "email": "g1@x.edu", "tier": "SUMMA"},
            {"full_name": "G2 Magna", "email": "g2@x.edu", "tier": "MAGNA"},
            {"full_name": "G3 Cum", "email": "g3@x.edu", "tier": "CUM"},
            {"full_name": "G4 None", "email": "g4@x.edu", "tier": "NONE"},
            {"full_name": "G5 None", "email": "g5@x.edu", "tier": "NONE"},
            {"full_name": "G6 None", "email": "g6@x.edu", "tier": "NONE"},
        ],
        posture="AUDIT_LOCKED", ticket_ratio=1.0, venue_capacity=6,
        venue_accessible=2, venue_indoor=False, rain_capacity=4, rain_accessible=1)
    seating = validate_success(
        api_client.run_seating(ctx["ceremony"]["id"], COORDINATOR), 200)
    return ctx, seating


class TestRainActivationEvictionCascade:
    def test_rain_activation_evicts_overflow_per_selector(self, api):
        """PRD §3.5: "while the count of `ASSIGNED` seats exceeds the new
        `effective_capacity`, seats are evicted in a fixed selector order —
        non-accessible seats before accessible ones, then higher `row_label`
        values first, then higher `seat_number` values first, then most
        recently created first — each eviction moving the seat to `EVICTED`
        with `evicted_reason` `RAIN_SHRINK` and raising `open_seat_count` by
        one."

        Design: Difficulty/transitive_cascade/rain_activation_capacity_eviction_cascade
        """
        ctx, seating = _setup_rain_eviction()
        assert seating["assigned_count"] == 6
        assert seating["open_seat_count"] == 0

        ceremony = validate_success(
            api.activate_rain_plan(ctx["ceremony"]["id"], COORDINATOR), 200)
        assert ceremony["weather_mode"] == "RAIN_PLAN_ACTIVE"
        assert ceremony["effective_capacity"] == 4
        assert ceremony["open_seat_count"] == 0  # 4 capacity - 4 remaining ASSIGNED
        assert ceremony["ticket_pool_total"] == 4  # floor(4 * 1.0)

        evicted = list_ceremony_seats(ctx["ceremony"]["id"], status="EVICTED")
        assert len(evicted) == 2
        assert all(s["evicted_reason"] == "RAIN_SHRINK" for s in evicted)
        # selector: non-accessible first, row_label DESC, seat_number DESC
        positions = sorted((s["row_label"], s["seat_number"]) for s in evicted)
        assert positions == [("2", 1), ("2", 2)]

    def test_rain_activation_leaves_exactly_capacity_assigned(self, api):
        """PRD §2.9: "The `open_seat_count` is the `effective_capacity` minus
        the number of seat assignments in `ASSIGNED` status for the ceremony."
        PRD §3.5: "Activation then recomputes the pools with the rain venue's
        `total_capacity` as the new `effective_capacity`, and if the rain venue
        is smaller, the chart shrinks by force".

        Design: Difficulty/transitive_cascade/rain_activation_capacity_eviction_cascade
        """
        ctx, seating = _setup_rain_eviction()
        validate_success(api.activate_rain_plan(ctx["ceremony"]["id"], COORDINATOR), 200)
        assigned = list_ceremony_seats(ctx["ceremony"]["id"], status="ASSIGNED")
        assert len(assigned) == 4
        assert all(s["section"] == "A" and s["row_label"] == "1" for s in assigned)
        assert sorted(s["seat_number"] for s in assigned) == [1, 2, 3, 4]
        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["effective_capacity"] == len(assigned) + ceremony["open_seat_count"]


class TestCeremonyParallelDimensions:
    def _setup_audited_locked_with_rain(self):
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Pat Parallel", "email": "pat@x.edu", "tier": "SUMMA"}],
            posture="AUDIT_LOCKED", ticket_ratio=1.0, venue_capacity=10,
            venue_accessible=2, venue_indoor=False, rain_capacity=6, rain_accessible=1)
        return ctx

    def test_activate_rain_toggles_weather_not_posture(self, api):
        """PRD §2.5: "The `weather_mode` dimension toggles between `FAIR` and
        `RAIN_PLAN_ACTIVE` and is entirely parallel: it may be flipped only
        while the posture is `AUDIT_LOCKED` or `READY`, and it never changes
        the posture itself."
        PRD §2.9: "The **effective venue** is the ceremony's primary venue
        while `weather_mode` is `FAIR`, and the rain venue while `weather_mode`
        is `RAIN_PLAN_ACTIVE`. The `effective_capacity` is the effective
        venue's `total_capacity`."

        Design: Difficulty/non_linear_state_machine/ceremony_posture_weather_parallel_dimensions
        """
        ctx = self._setup_audited_locked_with_rain()
        ceremony = validate_success(
            api.activate_rain_plan(ctx["ceremony"]["id"], COORDINATOR), 200)
        assert ceremony["weather_mode"] == "RAIN_PLAN_ACTIVE"
        assert ceremony["readiness_posture"] == "AUDIT_LOCKED"
        assert ceremony["effective_capacity"] == 6
        assert ceremony["ticket_pool_total"] == 6  # floor(6 * 1.0)

    def test_deactivate_rain_restores_capacity_not_posture(self, api):
        """PRD §3.5: "Flipping `RAIN_PLAN_ACTIVE` back to `FAIR` — again only
        in `AUDIT_LOCKED` or `READY` — restores the primary venue's
        `total_capacity` as `effective_capacity` and grows `open_seat_count`,
        but evicted seats are **not** restored".
        PRD §2.5: "The `weather_mode` dimension toggles between `FAIR` and
        `RAIN_PLAN_ACTIVE` and is entirely parallel: it may be flipped only
        while the posture is `AUDIT_LOCKED` or `READY`, and it never changes
        the posture itself."

        Design: Difficulty/non_linear_state_machine/ceremony_posture_weather_parallel_dimensions
        """
        ctx = self._setup_audited_locked_with_rain()
        validate_success(api.activate_rain_plan(ctx["ceremony"]["id"], COORDINATOR), 200)
        ceremony = validate_success(
            api.deactivate_rain_plan(ctx["ceremony"]["id"], COORDINATOR), 200)
        assert ceremony["weather_mode"] == "FAIR"
        assert ceremony["readiness_posture"] == "AUDIT_LOCKED"
        assert ceremony["effective_capacity"] == 10
        assert ceremony["ticket_pool_total"] == 10


class TestSeatInventoryConservation:
    def _setup_two_seated(self):
        ctx = setup_ceremony_with_graduates(
            [
                {"full_name": "Seat A", "email": "sa@x.edu", "tier": "SUMMA"},
                {"full_name": "Seat B", "email": "sb@x.edu", "tier": "NONE"},
            ],
            posture="AUDIT_LOCKED", venue_capacity=5, venue_accessible=1)
        ga, gb = ctx["graduates"]
        s1 = assign_seat(ctx["ceremony"]["id"], ga["id"], seat_number=1)
        s2 = assign_seat(ctx["ceremony"]["id"], gb["id"], seat_number=2)
        return ctx, ga, gb, s1, s2

    def test_manual_evict_releases_seat(self, api):
        """PRD §3.5: "Each new assignment stands `ASSIGNED` with a null
        `evicted_reason` and decrements `open_seat_count` by one; each eviction
        — manual or cascading — increments it by one."
        PRD §3.5: "A coordinator may also evict any `ASSIGNED` seat by hand,
        which moves it to the terminal `EVICTED` with `evicted_reason`
        `MANUAL`."

        Design: Difficulty/compensating_invariant/seat_inventory_assign_evict_conservation
        """
        ctx, ga, gb, s1, s2 = self._setup_two_seated()
        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["open_seat_count"] == 3  # 5 - 2 assigned

        evicted = validate_success(api.evict_seat(s2["id"], COORDINATOR), 200)
        assert evicted["status"] == "EVICTED"
        assert evicted["evicted_reason"] == "MANUAL"

        ceremony = get_ceremony(ctx["ceremony"]["id"])
        assert ceremony["open_seat_count"] == 4  # 5 - 1 remaining ASSIGNED

    def test_assign_evict_conserves_seat_inventory(self, api):
        """PRD §2.9: "The `open_seat_count` is the `effective_capacity` minus
        the number of seat assignments in `ASSIGNED` status for the ceremony."

        Design: Difficulty/compensating_invariant/seat_inventory_assign_evict_conservation
        """
        ctx, ga, gb, s1, s2 = self._setup_two_seated()
        validate_success(api.evict_seat(s2["id"], COORDINATOR), 200)
        assigned = list_ceremony_seats(ctx["ceremony"]["id"], status="ASSIGNED")
        ceremony = get_ceremony(ctx["ceremony"]["id"])
        # invariant: effective_capacity (5) == ASSIGNED (1) + open_seat_count (4)
        assert ceremony["effective_capacity"] == 5
        assert len(assigned) == 1
        assert ceremony["open_seat_count"] == 4
        assert ceremony["effective_capacity"] == len(assigned) + ceremony["open_seat_count"]


class TestSeatConstraints:
    def test_seat_duplicate_position_returns_seat_conflict(self, api):
        """PRD §3.5: "the seat position must be unique among the ceremony's
        `ASSIGNED` seats and the graduate must not already hold an `ASSIGNED`
        seat (either violation is `ERR_SEAT_CONFLICT`)".

        Design: Corner/validations/seat_duplicate_position_returns_seat_conflict
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Seat A", "email": "sa@x.edu"},
             {"full_name": "Seat B", "email": "sb@x.edu"}],
            posture="AUDIT_LOCKED")
        ga, gb = ctx["graduates"]
        assign_seat(ctx["ceremony"]["id"], ga["id"], section="A", row_label="1",
                    seat_number=1)
        res = api.create_seat_assignment(
            create_seat_assignment_payload(ctx["ceremony"]["id"], gb["id"],
                                           section="A", row_label="1", seat_number=1),
            COORDINATOR)
        validate_error(res, ApiErrorId.ERR_SEAT_CONFLICT)
        assert res.status_code == 409
        seats_b = validate_success(
            api.list_graduate_seat_assignments(gb["id"], REGISTRAR), 200)
        assert seats_b == []

    def test_seat_assignment_beyond_capacity_returns_error(self, api):
        """PRD §3.5: "the count of `ASSIGNED` seats must be below the
        ceremony's `effective_capacity` before placing (else
        `ERR_SEAT_CAPACITY_EXCEEDED`)".

        Design: Corner/validations/seat_assignment_beyond_capacity_returns_error
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Cap A", "email": "ca@x.edu"},
             {"full_name": "Cap B", "email": "cb@x.edu"},
             {"full_name": "Cap C", "email": "cc@x.edu"}],
            posture="AUDIT_LOCKED", venue_capacity=2, venue_accessible=0)
        ga, gb, gc = ctx["graduates"]
        assign_seat(ctx["ceremony"]["id"], ga["id"], seat_number=1)
        assign_seat(ctx["ceremony"]["id"], gb["id"], seat_number=2)
        res = api.create_seat_assignment(
            create_seat_assignment_payload(ctx["ceremony"]["id"], gc["id"],
                                           section="A", row_label="1", seat_number=3),
            COORDINATOR)
        validate_error(res, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED)
        assert res.status_code == 422


class TestAccessiblePoolBoundaries:
    def test_accessible_capacity_exact_boundary(self, api):
        """PRD §3.5: "Approval of a `WHEELCHAIR_SEAT` request consumes the
        accessible pool: it is permitted only while the count of that
        ceremony's `WHEELCHAIR_SEAT` requests already in `APPROVED` or
        `FULFILLED` remains below the effective venue's `accessible_capacity`,
        else it is rejected with `ERR_ACCESSIBLE_CAPACITY_EXCEEDED`".

        Design: Corner/validations/accessible_capacity_exact_boundary
        """
        ctx = setup_ceremony(venue_capacity=10, venue_accessible=1)
        ceremony_id = ctx["ceremony"]["id"]
        ga = import_graduate(ceremony_id, full_name="Wheel A", email="wa@x.edu")
        gb = import_graduate(ceremony_id, full_name="Wheel B", email="wb@x.edu")
        req_a = validate_success(
            api.create_accommodation_request(
                ga["id"], create_accommodation_request_payload(ceremony_id, "WHEELCHAIR_SEAT"),
                make_graduate_headers(ga["id"])), 201)
        req_b = validate_success(
            api.create_accommodation_request(
                gb["id"], create_accommodation_request_payload(ceremony_id, "WHEELCHAIR_SEAT"),
                make_graduate_headers(gb["id"])), 201)

        first = validate_success(
            api.approve_accommodation(req_a["id"], make_coordinator_headers(COORD_A)), 200)
        assert first["status"] == "APPROVED"  # 1 reserved == accessible_capacity 1, inclusive

        res = api.approve_accommodation(req_b["id"], make_coordinator_headers(COORD_A))
        validate_error(res, ApiErrorId.ERR_ACCESSIBLE_CAPACITY_EXCEEDED)
        assert res.status_code == 422

    def test_rain_activation_blocked_by_accessible_overflow(self, api):
        """PRD §3.5: "Activation requires a designated rain venue (a null
        `rain_venue_id` is `ERR_RAIN_VENUE_MISSING`) and requires the
        ceremony's reserved accessible inventory — the count of `APPROVED` or
        `FULFILLED` `WHEELCHAIR_SEAT` requests — to fit within the rain venue's
        `accessible_capacity` (else `ERR_ACCESSIBLE_CAPACITY_EXCEEDED`)".

        Design: Corner/validations/rain_activation_blocked_by_accessible_overflow
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Wheel Wanda", "email": "wanda@x.edu"}],
            posture="AUDIT_LOCKED", venue_capacity=10, venue_accessible=1,
            venue_indoor=False, rain_capacity=6, rain_accessible=0)
        graduate = ctx["graduates"][0]
        req = validate_success(
            api.create_accommodation_request(
                graduate["id"],
                create_accommodation_request_payload(ctx["ceremony"]["id"], "WHEELCHAIR_SEAT"),
                make_graduate_headers(graduate["id"])), 201)
        validate_success(
            api.approve_accommodation(req["id"], make_coordinator_headers(COORD_A)), 200)

        res = api.activate_rain_plan(ctx["ceremony"]["id"], COORDINATOR)
        validate_error(res, ApiErrorId.ERR_ACCESSIBLE_CAPACITY_EXCEEDED)
        assert res.status_code == 422  # 1 reserved > rain accessible_capacity 0
        assert get_ceremony(ctx["ceremony"]["id"])["weather_mode"] == "FAIR"

    def test_rain_activate_without_rain_venue_returns_error(self, api):
        """PRD §3.5: "Activation requires a designated rain venue (a null
        `rain_venue_id` is `ERR_RAIN_VENUE_MISSING`)".

        Design: Corner/validations/rain_activate_without_rain_venue_returns_error
        """
        ctx = setup_ceremony(lock_audit=True, venue_indoor=False)
        res = api.activate_rain_plan(ctx["ceremony"]["id"], COORDINATOR)
        validate_error(res, ApiErrorId.ERR_RAIN_VENUE_MISSING)
        assert res.status_code == 409
        assert get_ceremony(ctx["ceremony"]["id"])["weather_mode"] == "FAIR"


class TestWithdrawalCascades:
    def test_withdraw_releases_allocation_and_evicts_seat(self, api):
        """PRD §3.9: "The graduate's ticket allocation, unless already
        `RELEASED` or `EXPIRED`, moves to `RELEASED`: its `granted_count` is
        credited back to `ticket_pool_remaining` and zeroed".
        PRD §3.9: "Any `ASSIGNED` seat the graduate holds moves to `EVICTED`
        with `evicted_reason` `WITHDRAWN`, raising `open_seat_count` by one per
        eviction."

        Design: Corner/state_machines/withdraw_releases_allocation_and_evicts_seat
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Cascade Cass", "email": "cass@x.edu", "request": 4}],
            posture="AUDIT_LOCKED", ticket_ratio=1.0, venue_capacity=5,
            venue_accessible=1)
        ceremony_id = ctx["ceremony"]["id"]
        graduate = ctx["graduates"][0]
        run_waterfall(ceremony_id)
        seat = assign_seat(ceremony_id, graduate["id"], seat_number=1)

        validate_success(api.withdraw_graduate(graduate["id"], REGISTRAR), 200)

        allocation = get_graduate_allocation(graduate["id"])
        assert allocation["status"] == "RELEASED"
        assert allocation["granted_count"] == 0
        ceremony = get_ceremony(ceremony_id)
        assert ceremony["ticket_pool_remaining"] == 5  # pool fully restored
        assert ceremony["open_seat_count"] == 5
        seat_after = validate_success(api.get_seat_assignment(seat["id"], COORDINATOR), 200)
        assert seat_after["status"] == "EVICTED"
        assert seat_after["evicted_reason"] == "WITHDRAWN"
        assert get_graduate(graduate["id"])["status"] == "WITHDRAWN"

    def test_graduate_withdraw_twice_returns_invalid_state(self, api):
        """PRD §3.9: "Withdrawal is the system's widest cascade, available to a
        `RegistrarOfficer` or to the graduate themselves from any status except
        `WITHDRAWN`, and only while the ceremony has not reached `COMPLETED`."
        PRD §2.11: "The target entity's own state machine permits the
        transition from its current state, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/graduate_withdraw_twice_returns_invalid_state
        """
        ctx = setup_ceremony()
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Walt Twice",
                                   email="walt@x.edu")
        withdrawn = validate_success(api.withdraw_graduate(graduate["id"], REGISTRAR), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        res = api.withdraw_graduate(graduate["id"], REGISTRAR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409
        assert get_graduate(graduate["id"])["status"] == "WITHDRAWN"
