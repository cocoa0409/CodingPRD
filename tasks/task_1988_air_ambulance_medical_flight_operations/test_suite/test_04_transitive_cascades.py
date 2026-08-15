"""Transitive cascades: divert bed/ground/flag chain, QA-flag remediation
cascade, and abort leg/bed release chain."""
from test_helpers import (
    accept_request,
    advance_ground_leg,
    advance_mission,
    advance_mission_through,
    api_client,
    create_bed_reservation,
    create_ground_leg,
    create_mission_request,
    create_pcr,
    get_success_data,
    make_flight_crew_headers,
    post_go_weather,
    qa_review,
    setup_completed_mission,
    setup_planning_mission,
    submit_pcr,
    triage_request,
    validate_paginated,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _list_assignments(mission_id, crew_member_id):
    resp = api_client.list_crew_assignments(
        DISP, params={"mission_id": mission_id, "crew_member_id": crew_member_id}
    )
    return validate_paginated(resp)


class TestDivertCascadeBedGroundFlag:
    def _setup_in_transit_with_linked_bed(self):
        ctx = setup_planning_mission(estimated_loaded_miles=60)
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        bed = create_bed_reservation(mission["id"], facility_name="County General", bed_type="ICU")
        leg = create_ground_leg(
            mission["id"], leg_type="DESTINATION", bed_reservation_id=bed["id"],
            scheduled_pickup_iso="2026-08-01T09:30:00Z",
        )
        post_go_weather(mission["id"], pilot)
        advance_mission_through(mission["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT"])
        return ctx, pilot, bed, leg

    def test_divert_releases_mismatched_bed_and_cancels_linked_leg(self):
        """PRD §3.5: "Divert fires a three-hop cascade: hop one releases every
        bed reservation on this mission whose `facility_name` does not match the
        `new_destination_facility` and whose status is `HELD` or `CONFIRMED`,
        moving each to `RELEASED`; hop two cancels every ground leg whose
        `bed_reservation_id` points at a bed released in hop one and whose
        status is `SCHEDULED` or `ENROUTE`, moving each to `CANCELLED`; hop
        three recomputes the mission's `ground_coordination_status`, which
        typically becomes `NEEDS_REPLAN` when a destination leg was cancelled
        without replacement. The mission's `destination_facility` field itself
        is rewritten to the divert target."

        Design: Difficulty/transitive_cascade/divert_cascade_bed_ground_flag
        """
        ctx, pilot, bed, leg = self._setup_in_transit_with_linked_bed()
        mission_id = ctx["mission"]["id"]
        diverted = get_success_data(
            api_client.divert_mission(
                mission_id,
                {"new_destination_facility": "Regional North", "reason": "Thunderstorm over primary"},
                make_flight_crew_headers(pilot["id"]),
            )
        )
        assert diverted["status"] == "DIVERTED"
        assert diverted["destination_facility"] == "Regional North"
        bed_after = get_success_data(api_client.get_bed_reservation(bed["id"], DISP))
        assert bed_after["status"] == "RELEASED", (
            f"Hop 1: mismatched HELD bed must be RELEASED, got {bed_after['status']}"
        )
        leg_after = get_success_data(api_client.get_ground_leg(leg["id"], DISP))
        assert leg_after["status"] == "CANCELLED", (
            f"Hop 2: leg linked to the released bed must be CANCELLED, got {leg_after['status']}"
        )

    def test_divert_recomputes_ground_coordination_status_to_needs_replan(self):
        """PRD §3.6: "It reads `NEEDS_REPLAN` when a `CANCELLED` `DESTINATION`
        leg exists for which no later-created `DESTINATION` leg remains
        non-`CANCELLED`."
        PRD §3.5: "hop three recomputes the mission's
        `ground_coordination_status`, which typically becomes `NEEDS_REPLAN`
        when a destination leg was cancelled without replacement."

        Design: Difficulty/transitive_cascade/divert_cascade_bed_ground_flag
        """
        ctx, pilot, bed, leg = self._setup_in_transit_with_linked_bed()
        mission_id = ctx["mission"]["id"]
        get_success_data(
            api_client.divert_mission(
                mission_id,
                {"new_destination_facility": "Regional North", "reason": "Thunderstorm over primary"},
                make_flight_crew_headers(pilot["id"]),
            )
        )
        mission_after = get_success_data(api_client.get_mission(mission_id, DISP))
        assert mission_after["ground_coordination_status"] == "NEEDS_REPLAN", (
            f"Hop 3: expected NEEDS_REPLAN after the DESTINATION leg was cancelled "
            f"without replacement, got {mission_after['ground_coordination_status']}"
        )


class TestQaFlagCascadeRemediationRelease:
    def _setup_nurse_at_10_points_with_pending_assignment(self):
        """One base/tail; nurse's first COMPLETED mission's PCR FLAGGED 10;
        second COMPLETED mission's nurse-authored PCR left SUBMITTED; third
        mission PLANNING holding the nurse's ASSIGNED assignment."""
        ctx1 = setup_completed_mission(estimated_loaded_miles=50)
        nurse = ctx1["roster"]["NURSE"]
        pilot = ctx1["roster"]["PILOT"]
        aircraft = ctx1["aircraft"]
        patient = ctx1["patient"]
        pcr1 = create_pcr(ctx1["mission"]["id"], nurse)
        submit_pcr(pcr1["id"], nurse)
        qa_review(pcr1["id"], "FLAGGED", 10, reviewer_id="qa-officer-1")
        # Mission 2 on the same tail in a non-overlapping window, completed.
        req2 = triage_request(create_mission_request(patient["id"])["id"])
        m2 = accept_request(
            req2["id"], aircraft["id"],
            [(pilot["id"], "PILOT"), (nurse["id"], "NURSE")],
            estimated_loaded_miles=50, planned_launch_iso="2026-08-01T12:00:00Z",
        )
        post_go_weather(m2["id"], pilot)
        advance_mission_through(
            m2["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION", "COMPLETED"]
        )
        pcr2 = create_pcr(m2["id"], nurse)
        submit_pcr(pcr2["id"], nurse)
        # Mission 3 stays PLANNING with the nurse ASSIGNED (2026-08-03 window).
        req3 = triage_request(create_mission_request(patient["id"])["id"])
        m3 = accept_request(
            req3["id"], aircraft["id"],
            [(pilot["id"], "PILOT"), (nurse["id"], "NURSE")],
            estimated_loaded_miles=50, planned_launch_iso="2026-08-03T06:00:00Z",
        )
        assignments, _meta = _list_assignments(m3["id"], nurse["id"])
        return nurse, pcr2, assignments[0]

    def test_flagged_review_accumulates_points_and_flips_member_at_threshold(self):
        """PRD §3.9: "Hop one adds the points to the author's rolling tally:
        `deficiency_points_90d` is the sum of `deficiency_points` across every
        flagged review of this author's records whose review instant falls
        inside the rolling 90-day window ending at the logical now, reviews
        processed in ascending creation order. Hop two flips the member from
        `ACTIVE` to `REMEDIATION_HOLD` the moment that tally reaches 15 points —
        exactly 15 triggers the hold."

        Design: Difficulty/transitive_cascade/qa_flag_cascade_remediation_release
        """
        nurse, pcr2, _asg3 = self._setup_nurse_at_10_points_with_pending_assignment()
        member_mid = get_success_data(api_client.get_crew_member(nurse["id"], DISP))
        assert member_mid["deficiency_points_90d"] == 10
        assert member_mid["status"] == "ACTIVE", "Below the 15 threshold: no hold yet"
        # Second flag of 5 points: 10 + 5 = 15, crossing the >= 15 threshold.
        flagged = qa_review(pcr2["id"], "FLAGGED", 5, reviewer_id="qa-officer-1")
        assert flagged["status"] == "QA_FLAGGED"
        member_after = get_success_data(api_client.get_crew_member(nurse["id"], DISP))
        assert member_after["deficiency_points_90d"] == 15, (
            f"Expected rolling tally 15, got {member_after['deficiency_points_90d']}"
        )
        assert member_after["status"] == "REMEDIATION_HOLD", (
            f"Hop 2: exactly 15 triggers the hold, got {member_after['status']}"
        )

    def test_remediation_hold_releases_members_assignments_on_planning_missions(self):
        """PRD §3.9: "Hop three, caused by the hold itself, releases every
        `ASSIGNED` crew assignment that member holds on missions still in
        `PLANNING`, moving each to `RELEASED`."

        Design: Difficulty/transitive_cascade/qa_flag_cascade_remediation_release
        """
        nurse, pcr2, asg3 = self._setup_nurse_at_10_points_with_pending_assignment()
        assert asg3["status"] == "ASSIGNED"
        qa_review(pcr2["id"], "FLAGGED", 5, reviewer_id="qa-officer-1")
        asg3_after = get_success_data(api_client.get_crew_assignment(asg3["id"], DISP))
        assert asg3_after["status"] == "RELEASED", (
            f"Hop 3: the hold must release the member's ASSIGNED assignment on the "
            f"PLANNING mission, got {asg3_after['status']}"
        )


class TestAbortCascadeLegBedRelease:
    def _setup_launched_with_confirmed_bed_and_enroute_leg(self):
        ctx = setup_planning_mission(estimated_loaded_miles=60)
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        bed = create_bed_reservation(mission["id"], facility_name="County General", bed_type="CCU")
        get_success_data(
            api_client.update_bed_reservation(bed["id"], {"status": "CONFIRMED"}, DISP)
        )
        leg = create_ground_leg(
            mission["id"], leg_type="DESTINATION", bed_reservation_id=bed["id"],
            scheduled_pickup_iso="2026-08-01T09:30:00Z",
        )
        advance_ground_leg(leg["id"], "ENROUTE")
        post_go_weather(mission["id"], pilot)
        advance_mission(mission["id"], "LAUNCHED", headers=make_flight_crew_headers(pilot["id"]))
        return ctx, pilot, bed, leg

    def test_abort_cancels_enroute_leg_and_releases_aircraft(self):
        """PRD §3.5: "Either way, the cascade releases the aircraft (subject to
        the last-booking rule below), moves every `ASSIGNED` crew assignment on
        the mission to `RELEASED`, cancels every ground leg in `SCHEDULED` or
        `ENROUTE`, and — as a second hop caused by each cancelled destination
        leg — releases that leg's linked bed reservation if it is `HELD` or
        `CONFIRMED`."

        Design: Difficulty/transitive_cascade/abort_cascade_leg_bed_release
        """
        ctx, pilot, bed, leg = self._setup_launched_with_confirmed_bed_and_enroute_leg()
        mission_id = ctx["mission"]["id"]
        aborted = get_success_data(
            api_client.abort_mission(
                mission_id, {"reason_code": "MECHANICAL"},
                make_flight_crew_headers(pilot["id"]),
            )
        )
        assert aborted["status"] == "ABORTED"
        aircraft_after = get_success_data(api_client.get_aircraft(ctx["aircraft"]["id"], DISP))
        assert aircraft_after["status"] == "AVAILABLE"
        leg_after = get_success_data(api_client.get_ground_leg(leg["id"], DISP))
        assert leg_after["status"] == "CANCELLED", (
            f"Hop 1: ENROUTE leg must be CANCELLED on abort, got {leg_after['status']}"
        )

    def test_abort_releases_bed_as_second_hop_of_leg_cancellation(self):
        """PRD §3.5: "and — as a second hop caused by each cancelled destination
        leg — releases that leg's linked bed reservation if it is `HELD` or
        `CONFIRMED`."
        PRD §3.6: "Cancelling a `DESTINATION` leg that carries a
        `bed_reservation_id` releases that bed if it is still `HELD` or
        `CONFIRMED`."

        Design: Difficulty/transitive_cascade/abort_cascade_leg_bed_release
        """
        ctx, pilot, bed, leg = self._setup_launched_with_confirmed_bed_and_enroute_leg()
        mission_id = ctx["mission"]["id"]
        get_success_data(
            api_client.abort_mission(
                mission_id, {"reason_code": "MECHANICAL"},
                make_flight_crew_headers(pilot["id"]),
            )
        )
        bed_after = get_success_data(api_client.get_bed_reservation(bed["id"], DISP))
        assert bed_after["status"] == "RELEASED", (
            f"Hop 2 (caused by the leg cancellation): CONFIRMED bed must be RELEASED, "
            f"got {bed_after['status']}"
        )
