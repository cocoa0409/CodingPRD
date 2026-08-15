"""Role-based access control and entity-backed ownership claims (PRD §2.1, §3.2, §3.3, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    coordinator_headers,
    create_report_payload,
    get_assignment,
    get_event,
    get_incident,
    invite,
    make_crew_leader_headers,
    make_volunteer_headers,
    new_crew_leader,
    new_event,
    new_farm,
    new_offer,
    new_vehicle,
    new_volunteer,
    open_incident,
    publish_event,
    reviewer_headers,
    set_clock,
    setup_in_progress_event,
    sign_waiver,
    validate_error,
    get_success_data,
)


class TestRoleDenial:
    def test_volunteer_cannot_verify_lots(self, api):
        """PRD §2.1: "an authenticated caller whose role is not permitted for the
        endpoint — including a `Volunteer` acting on another volunteer's assignment, or
        a `CrewLeader` who is not the event's designated leader — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: the lot verify endpoint is listed for ProgramCoordinator only.

        Design: Corner/rbac/volunteer_cannot_verify_lots
        """
        ctx = setup_in_progress_event(
            lot_specs=[{"gross": 60.0, "cull": 0.0}],
        )
        lot = ctx["lots"][0]
        resp = api.verify_lot(
            lot["id"],
            {"verified_by_coordinator_id": ctx["lead"]["id"]},
            make_volunteer_headers(ctx["lead"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_grant_reviewer_cannot_submit_reports(self, api):
        """PRD §4: the report submit endpoint is listed for ProgramCoordinator only.
        PRD §2.1: "Access to each operation is restricted by role per the endpoint
        catalogue in §4; an authenticated caller whose role is not permitted for the
        endpoint — including a `Volunteer` acting on another volunteer's assignment, or
        a `CrewLeader` who is not the event's designated leader — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/grant_reviewer_cannot_submit_reports
        """
        report = get_success_data(
            api.create_report(
                create_report_payload(county_code="RB2"), coordinator_headers()
            )
        )
        resp = api.submit_report(report["id"], reviewer_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_coordinator_cannot_resolve_incidents(self, api):
        """PRD §3.4: "Only a `FoodSafetyOfficer` may resolve an incident, supplying a
        `disposition`"

        Design: Corner/rbac/coordinator_cannot_resolve_incidents
        """
        farm = new_farm(farm_name="RS", county_code="RS1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"])
        incident = open_incident(event["id"], lead["id"], condemned_lbs=5.0)

        resp = api.resolve_incident(
            incident["id"], {"disposition": "COMPOST"}, coordinator_headers()
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_incident(incident["id"])["disposition"] == "OPEN"


class TestEntityBackedOwnership:
    def test_volunteer_identity_ownership_check(self, api):
        """PRD §3.2: "Only the invited volunteer may answer — confirming or declining
        another volunteer's assignment is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/volunteer_identity_ownership_check
        """
        farm = new_farm(farm_name="OW", county_code="OW1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        owner = new_volunteer(full_name="Owner V")
        other = new_volunteer(full_name="Other V")
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead["id"], vehicle["id"], crew_capacity=3)
        publish_event(event["id"])
        asg = invite(event["id"], owner["id"])
        # The other volunteer even holds a waiver for this event; ownership still gates.
        sign_waiver(event["id"], other["id"], lead["id"])

        resp = api.confirm_assignment(asg["id"], make_volunteer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_assignment(asg["id"])["status"] == "PENDING"

    def test_crew_leader_event_start_ownership(self, api):
        """PRD §3.3: "Starting the work is the crew leader's call, and only the
        designated one: the acting crew leader must be the volunteer referenced by the
        event's `crew_leader_volunteer_id`, anyone else drawing `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/crew_leader_event_start_ownership
        """
        farm = new_farm(farm_name="CL", county_code="CL1")
        vehicle = new_vehicle()
        lead_a = new_crew_leader(full_name="Leader A")
        lead_b = new_crew_leader(full_name="Leader B")
        offer = new_offer(farm["id"])
        event = new_event(offer["id"], lead_a["id"], vehicle["id"], crew_capacity=1)
        publish_event(event["id"])
        set_clock("2026-08-10T09:00:00Z")

        resp = api.start_event(event["id"], make_crew_leader_headers(lead_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_event(event["id"])["status"] == "OPEN"
