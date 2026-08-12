"""Transitive cascade tests: the depth-3 safety suspension cascade and the
depth-2 demobilization/return cascade (PRD §2.10, §3.4, §3.5, §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_host_safety_officer_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, conduct_and_acknowledge_briefing,
    arrive_crew, create_submitted_timesheet, create_lodging_block,
    create_lodging_assignment, setup_cleared_arrived_crew,
    create_per_diem_claim_payload,
)


def _setup_fulfilled_request_with_held_candidates():
    """Request FULFILLED (required_minimum_crews 1, one ARRIVED+CLEARED crew),
    one SUBMITTED timesheet and one SUBMITTED per-diem claim."""
    ctx = setup_cleared_arrived_crew(clock_after_arrival="2026-05-05T09:00:00Z")
    ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                    day_classification="WORK", reported_work_minutes=480)
    resp = api_client.create_per_diem_claim(
        create_per_diem_claim_payload(crew_id=ctx["crew"]["id"], claim_date="2026-05-03"),
        make_responding_coordinator_headers(ctx["rsp"]["id"]))
    assert resp.status_code == 201, f"Setup failed creating claim: {resp.text}"
    pd = get_success_data(resp)
    resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
    request = validate_success(resp)
    assert request["status"] == "FULFILLED", (
        f"Precondition: request must be FULFILLED, got {request['status']}"
    )
    ctx.update({"ts": ts, "pd": pd, "request": request})
    return ctx


class TestSafetySuspendDepth3Cascade:
    def test_link1_crew_readiness_drops_to_safety_hold(self):
        """PRD §3.5: "When a `HostSafetyOfficer` suspends a crew — an optional
        `reason` may be recorded — the crew's readiness drops from
        `CLEARED_TO_WORK` to `SAFETY_HOLD`, `last_suspended_at` is stamped, and
        a depth-three cascade follows."

        Design: Difficulty/transitive_cascade/safety_suspend_depth3_cascade
        """
        ctx = _setup_fulfilled_request_with_held_candidates()
        resp = api_client.suspend_crew(
            ctx["crew"]["id"], {"reason": "PPE violation"},
            make_host_safety_officer_headers(ctx["host"]["id"]))
        crew = validate_success(resp)
        assert crew["readiness_status"] == "SAFETY_HOLD"
        assert crew["last_suspended_at"] is not None

    def test_link2_and_link3_rows_held_and_request_demoted(self):
        """PRD §3.5: "First the crew itself leaves the deployable population;
        second, every one of the crew's `SUBMITTED` timesheets and `SUBMITTED`
        per-diem claims is parked in `HELD`; third, the request's
        `deployable_crew_count` is recomputed and a `FULFILLED` request whose
        deployability has fallen below `required_minimum_crews` is demoted to
        `IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/safety_suspend_depth3_cascade
        """
        ctx = _setup_fulfilled_request_with_held_candidates()
        api_client.suspend_crew(
            ctx["crew"]["id"], {"reason": "PPE violation"},
            make_host_safety_officer_headers(ctx["host"]["id"]))
        resp = api_client.get_timesheet(ctx["ts"]["id"], make_program_admin_headers())
        assert validate_success(resp)["status"] == "HELD"
        resp = api_client.get_per_diem_claim(ctx["pd"]["id"], make_program_admin_headers())
        assert validate_success(resp)["status"] == "HELD"
        resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
        request = validate_success(resp)
        assert request["deployable_crew_count"] == 0
        assert request["status"] == "IN_PROGRESS"


class TestCompleteReturnDepth2ReleasesRequest:
    def _setup_arrived_with_lodging(self):
        set_clock("2026-05-01T08:00:00Z")
        host = create_company(name="Host Power", company_code="HST",
                              role_capability="BOTH", home_region="Coastal")
        rsp = create_company(name="Responder Electric", company_code="RSP",
                             role_capability="RESPONDING", home_region="Inland")
        event = create_event(host["id"], activate=True)
        create_and_publish_schedule(event["id"], rsp["id"])
        request = create_accepted_request(event["id"], host["id"], rsp["id"],
                                          required_minimum_crews=2)
        crew = commit_crew(request["id"], rsp["id"])
        block = create_lodging_block(event["id"], host["id"], total_rooms=2)
        asg = create_lodging_assignment(block["id"], crew["id"], host["id"],
                                        check_in_date="2026-05-03",
                                        check_out_date="2026-05-08")
        crew = arrive_crew(crew["id"], host["id"])
        return {"host": host, "rsp": rsp, "event": event, "request": request,
                "crew": crew, "block": block, "asg": asg}

    def test_release_checks_out_lodging_and_frees_rooms(self):
        """PRD §3.7: "Its first link checks the crew out of lodging: every
        `OCCUPIED` assignment moves to `CHECKED_OUT` with
        `actual_check_out_date` set to the current date, and the block's
        `assigned_rooms` drops accordingly."

        Design: Difficulty/transitive_cascade/complete_return_depth2_releases_request
        """
        ctx = self._setup_arrived_with_lodging()
        resp = api_client.release_crew(ctx["crew"]["id"],
                                       make_host_coordinator_headers(ctx["host"]["id"]))
        assert resp.status_code == 200
        resp = api_client.get_lodging_assignment(ctx["asg"]["id"], make_program_admin_headers())
        asg = validate_success(resp)
        assert asg["status"] == "CHECKED_OUT"
        assert asg["actual_check_out_date"] == "2026-05-01"  # current clock date
        resp = api_client.get_lodging_block(ctx["block"]["id"], make_program_admin_headers())
        assert validate_success(resp)["assigned_rooms"] == 0

    def test_last_crew_return_releases_the_request(self):
        """PRD §3.7: "When the last of a request's crews reaches a terminal
        mobility — `RETURNED` or `WITHDRAWN` — the request itself is released,
        moving from `IN_PROGRESS` or `FULFILLED` to `RELEASED`"

        Design: Difficulty/transitive_cascade/complete_return_depth2_releases_request
        """
        ctx = self._setup_arrived_with_lodging()
        api_client.release_crew(ctx["crew"]["id"],
                                make_host_coordinator_headers(ctx["host"]["id"]))
        resp = api_client.complete_return(ctx["crew"]["id"],
                                          make_responding_coordinator_headers(ctx["rsp"]["id"]))
        crew = validate_success(resp)
        assert crew["mobility_status"] == "RETURNED"
        assert crew["returned_at"] is not None
        resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
        assert validate_success(resp)["status"] == "RELEASED"
