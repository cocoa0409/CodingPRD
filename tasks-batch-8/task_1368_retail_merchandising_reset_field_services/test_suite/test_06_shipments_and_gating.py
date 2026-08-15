"""Fixture/POG shipment lifecycle, penalty accrual on scan events, and the
FIXTURE_INSTALL delivery gate on depart/check-in."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_shipment,
    get_project,
    make_field_rep_headers,
    make_scenario,
    scan_shipment,
    schedule_assignment,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["pm_headers"]


def _fixture_scenario(promised_date="2026-08-15", due_date="2026-08-25"):
    scn = make_scenario(scope_type="FIXTURE_INSTALL", due_date=due_date)
    ship = create_shipment(
        scn["project"]["id"], scn["ps_rows"][0]["id"], promised_date=promised_date
    )
    return scn, ship


class TestScanStateMachine:
    def test_fixture_scan_advances_state(self, api):
        """PRD 3.6: "A scan marking the shipment in transit moves it from
        `LABEL_CREATED`, `IN_TRANSIT`, or `DELIVERY_EXCEPTION` to `IN_TRANSIT`.
        ... A scan recording delivery moves it from `IN_TRANSIT` or
        `DELIVERY_EXCEPTION` to `DELIVERED`; when the delivery date falls after
        the `promised_date`, the late delivery adds 5 to the project's
        `rework_penalty_score`."

        Design: Corner/endpoints/fixture_scan_advances_state
        """
        scn, ship = _fixture_scenario()
        assert ship["status"] == "LABEL_CREATED"
        in_transit = scan_shipment(ship["id"], "IN_TRANSIT")
        assert in_transit["status"] == "IN_TRANSIT"
        set_clock("2026-08-08T12:00:00Z")  # on or before promised date: no late fee
        delivered = scan_shipment(ship["id"], "DELIVERED")
        assert delivered["status"] == "DELIVERED"
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 0, (
            "on-time delivery must not add a late-delivery penalty"
        )


class TestDeliveryExceptionLoop:
    def test_shipment_delivery_exception_loop_penalties_accumulate(self, api):
        """PRD 3.6: "A scan recording a delivery exception moves it from
        `LABEL_CREATED` or `IN_TRANSIT` to `DELIVERY_EXCEPTION` and adds 3 to
        the project's `rework_penalty_score`. A scan recording delivery moves
        it from `IN_TRANSIT` or `DELIVERY_EXCEPTION` to `DELIVERED`; when the
        delivery date falls after the `promised_date`, the late delivery adds
        5 to the project's `rework_penalty_score`."
        PRD 2.9: "From the score the system derives the project's `posture`:
        `NORMAL` while the score is below 20, `WATCH` once the score reaches at
        least 20 but remains below 40, and `ESCALATED` once the score reaches
        at least 40."

        Design: Difficulty/non_linear_state_machine/fixture_shipment_delivery_exception_loop
        """
        scn, ship = _fixture_scenario(promised_date="2026-08-10")
        set_clock("2026-08-08T12:00:00Z")
        scan_shipment(ship["id"], "IN_TRANSIT")
        exc1 = scan_shipment(ship["id"], "EXCEPTION")
        assert exc1["status"] == "DELIVERY_EXCEPTION"
        back = scan_shipment(ship["id"], "IN_TRANSIT")
        assert back["status"] == "IN_TRANSIT", (
            "the carrier re-attempt loop DELIVERY_EXCEPTION -> IN_TRANSIT must work"
        )
        scan_shipment(ship["id"], "EXCEPTION")
        scan_shipment(ship["id"], "IN_TRANSIT")
        set_clock("2026-08-12T12:00:00Z")  # past promised_date 2026-08-10
        delivered = scan_shipment(ship["id"], "DELIVERED")
        assert delivered["status"] == "DELIVERED"
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 11, (
            f"3 + 3 (two exceptions) + 5 (late delivery) = 11, "
            f"got {project['rework_penalty_score']}"
        )
        assert project["posture"] == "NORMAL"

    def test_shipment_lost_is_terminal_and_adds_penalty(self, api):
        """PRD 3.6: "A scan declaring the shipment lost moves it from
        `IN_TRANSIT` to `LOST` and adds 8 to the project's
        `rework_penalty_score`." and "`DELIVERED` and `LOST` are terminal."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/non_linear_state_machine/fixture_shipment_delivery_exception_loop
        """
        scn, ship = _fixture_scenario()
        scan_shipment(ship["id"], "IN_TRANSIT")
        lost = scan_shipment(ship["id"], "LOST")
        assert lost["status"] == "LOST"
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 8, (
            f"lost shipment adds 8, got {project['rework_penalty_score']}"
        )
        resp = api.scan_fixture_shipment(ship["id"], {"scan_result": "IN_TRANSIT"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFixtureDeliveryGate:
    def test_checkin_blocked_until_fixtures_delivered(self, api):
        """PRD 3.3: "Checking in is blocked while any fixture shipment for the
        store sits in `LABEL_CREATED`, `IN_TRANSIT`, or `DELIVERY_EXCEPTION` —
        a delivered shipment lifts the gate, and no gate applies to other scope
        types. Either blocked attempt is rejected with
        `ERR_FIXTURES_NOT_DELIVERED` (HTTP 409)."

        Design: Corner/endpoints/fixture_checkin_blocked_until_delivered
        """
        scn, ship = _fixture_scenario()
        scan_shipment(ship["id"], "IN_TRANSIT")
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        set_clock("2026-08-05T09:30:00Z")
        resp = api.check_in_assignment(asg["id"], make_field_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_FIXTURES_NOT_DELIVERED)
        # a delivered shipment lifts the gate
        scan_shipment(ship["id"], "DELIVERED")
        ok = api.check_in_assignment(asg["id"], make_field_rep_headers(rep["id"]))
        visit = validate_success(ok, 201)
        assert visit["verification_status"] == "PENDING_REVIEW"
