"""State-machine corner claims: initial states, terminal lockdowns, invalid
transitions, valid cycles, completion side effects, and idempotency."""
from test_helpers import (
    ApiErrorId,
    advance_ground_leg,
    advance_mission,
    advance_mission_through,
    api_client,
    create_bed_reservation,
    create_ground_leg,
    create_insurance_authorization,
    create_membership,
    create_patient,
    create_pcr,
    get_success_data,
    make_flight_crew_headers,
    post_go_weather,
    set_clock,
    setup_completed_mission,
    setup_planning_mission,
    submit_pcr,
    update_membership_safe,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestMembershipInitialStateActive:
    def test_new_membership_is_active_with_null_lapsed_at(self):
        """PRD §3.2: "the subscription is born `ACTIVE`, and it covers
        transports completed on or after `effective_from`."
        PRD §3.2: "Reinstatement — `LAPSED` back to `ACTIVE` — is permitted only
        within 30 days of the lapse ... and a successful reinstatement clears
        `lapsed_at` back to null."

        Design: Corner/state_machines/membership_initial_state_active
        """
        patient = create_patient(full_name="Mem Ber", date_of_birth="1988-08-08", weight_kg=70)
        membership = create_membership(patient["id"])
        assert membership["status"] == "ACTIVE"
        assert membership.get("lapsed_at") is None


class TestMembershipTerminatedLockdown:
    def test_terminated_membership_cannot_return_to_active(self):
        """PRD §3.2: "Termination is final: from either `ACTIVE` or `LAPSED` the
        subscription moves to `TERMINATED`, its terminal state; any other
        from-state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/membership_terminated_lockdown_rejected
        """
        patient = create_patient(full_name="Mem Ber", date_of_birth="1988-08-08", weight_kg=70)
        membership = create_membership(patient["id"])
        update_membership_safe(membership["id"], "TERMINATED")
        resp = api_client.update_membership(membership["id"], {"status": "ACTIVE"}, BILL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_membership(membership["id"], BILL))
        assert after["status"] == "TERMINATED"


class TestGroundLegSkipStateRejected:
    def test_scheduled_to_completed_skips_intermediate_states(self):
        """PRD §3.6: "Each leg walks a simple chain, advanced by a `Dispatcher`:
        `SCHEDULED` to `ENROUTE` ... `ENROUTE` to `AT_BEDSIDE`, and `AT_BEDSIDE`
        to `COMPLETED`; every step requires its from-state, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ground_leg_skip_state_rejected
        """
        ctx = setup_planning_mission()
        leg = create_ground_leg(
            ctx["mission"]["id"], leg_type="ORIGIN",
            scheduled_pickup_iso="2026-08-01T05:30:00Z",
        )
        resp = api_client.update_ground_leg(leg["id"], {"status": "COMPLETED"}, DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_ground_leg(leg["id"], DISP))
        assert after["status"] == "SCHEDULED"


class TestMissionAdvanceSkippingStatesRejected:
    def test_planning_to_in_transit_is_not_a_declared_transition(self):
        """PRD §3.5: "Once airborne, a `FlightCrew` caller walks the mission
        through its flight states by naming each `to_state`: `LAUNCHED` to
        `AT_PATIENT` when the crew reaches the patient, `AT_PATIENT` to
        `IN_TRANSIT` once loaded, and `IN_TRANSIT` to `AT_DESTINATION` on
        arrival; each step requires exactly its from-state, else
        `ERR_INVALID_STATE`."
        PRD §2.8: "a transition requested from a state that does not support it
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/mission_advance_skipping_states_rejected
        """
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        resp = api_client.advance_mission(
            ctx["mission"]["id"], {"to_state": "IN_TRANSIT"},
            make_flight_crew_headers(pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_mission(ctx["mission"]["id"], DISP))
        assert after["status"] == "PLANNING"


class TestInsuranceAuthorizationDenyAppealCycle:
    def test_requested_denied_appealed_approved_cycle(self):
        """PRD §3.8: "The specialist then records the payer's decision:
        `REQUESTED` to `APPROVED`; `REQUESTED` to `PARTIAL` ...; or `REQUESTED`
        to `DENIED`. A `DENIED` authorization may be pushed to `APPEALED`, and
        an `APPEALED` one may settle to `APPROVED` or back to `DENIED`. Every
        decision other than appeal itself requires the authorization to be in
        `REQUESTED` or `APPEALED`, and appeal requires `DENIED`; any other
        from-state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/insurance_authorization_deny_appeal_cycle
        """
        ctx = setup_planning_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            tier="BLS", medical_config="BLS_CAPABLE",
            transport_class="SCHEDULED_INTERFACILITY", origin_facility="Clinic West",
            estimated_loaded_miles=30, planned_duration_min=90,
        )
        auth = create_insurance_authorization(ctx["mission"]["id"])
        assert auth["status"] == "REQUESTED"
        s1 = get_success_data(
            api_client.update_insurance_authorization(auth["id"], {"status": "DENIED"}, BILL)
        )
        assert s1["status"] == "DENIED"
        s2 = get_success_data(
            api_client.update_insurance_authorization(auth["id"], {"status": "APPEALED"}, BILL)
        )
        assert s2["status"] == "APPEALED"
        s3 = get_success_data(
            api_client.update_insurance_authorization(auth["id"], {"status": "APPROVED"}, BILL)
        )
        assert s3["status"] == "APPROVED"


class TestBedReleaseAfterConsumedRejected:
    def test_consumed_bed_is_terminal(self):
        """PRD §3.6: "The dispatcher confirms a hold — `HELD` to `CONFIRMED` —
        or releases one from either `HELD` or `CONFIRMED` to `RELEASED`; any
        other from-state is `ERR_INVALID_STATE`, and each of these writes bumps
        the reservation's `version`."
        PRD §3.6: "mission completion consumes the surviving `HELD` or
        `CONFIRMED` ones into `CONSUMED`. `RELEASED` and `CONSUMED` are
        terminal."

        Design: Corner/state_machines/bed_release_after_consumed_rejected
        """
        ctx = setup_planning_mission()
        bed = create_bed_reservation(ctx["mission"]["id"], bed_type="ICU")
        pilot = ctx["roster"]["PILOT"]
        post_go_weather(ctx["mission"]["id"], pilot)
        advance_mission_through(
            ctx["mission"]["id"], pilot,
            ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION", "COMPLETED"],
        )
        bed_mid = get_success_data(api_client.get_bed_reservation(bed["id"], DISP))
        assert bed_mid["status"] == "CONSUMED"
        resp = api_client.update_bed_reservation(bed["id"], {"status": "RELEASED"}, DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        bed_after = get_success_data(api_client.get_bed_reservation(bed["id"], DISP))
        assert bed_after["status"] == "CONSUMED"


class TestMissionCompletionSideEffectsReleaseEverything:
    def test_completion_releases_tail_crew_and_consumes_bed(self):
        """PRD §3.5: "Completion stamps `completed_at` with the logical now,
        releases the aircraft per the rule above, moves all `ASSIGNED` crew
        assignments to `COMPLETED`, and moves every bed reservation on the
        mission still in `HELD` or `CONFIRMED` to `CONSUMED`."

        Design: Corner/state_machines/mission_completion_side_effects_release_everything
        """
        ctx = setup_planning_mission()
        mission = ctx["mission"]
        pilot = ctx["roster"]["PILOT"]
        nurse = ctx["roster"]["NURSE"]
        bed = create_bed_reservation(mission["id"], bed_type="MED_SURGE")
        post_go_weather(mission["id"], pilot)
        advance_mission_through(
            mission["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION"]
        )
        completed = advance_mission(mission["id"], "COMPLETED", headers=make_flight_crew_headers(pilot["id"]))
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"].startswith("2026-08-01T00:00:00"), (
            f"completed_at must be stamped with the logical now, got {completed['completed_at']}"
        )
        aircraft_after = get_success_data(api_client.get_aircraft(ctx["aircraft"]["id"], DISP))
        assert aircraft_after["status"] == "AVAILABLE"
        for member in (pilot, nurse):
            data, _ = validate_paginated(
                api_client.list_crew_assignments(
                    DISP, params={"mission_id": mission["id"], "crew_member_id": member["id"]}
                )
            )
            assert data[0]["status"] == "COMPLETED", (
                f"{member['crew_role']} assignment must close out, got {data[0]['status']}"
            )
        bed_after = get_success_data(api_client.get_bed_reservation(bed["id"], DISP))
        assert bed_after["status"] == "CONSUMED"


class TestPcrDoubleSubmitRejected:
    def test_second_submit_from_submitted_is_off_transition(self):
        """PRD §3.9: "The author — and only the author, again by the `X-User-ID`
        ownership comparison — submits from `DRAFT` or `AMENDED`; any other
        state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/pcr_double_submit_rejected
        """
        ctx = setup_completed_mission(transport_class="EMERGENCY_SCENE", origin_facility="Scene")
        pilot = ctx["roster"]["PILOT"]
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        first = submit_pcr(pcr["id"], pilot)
        assert first["status"] == "SUBMITTED"
        submitted_at = first["submitted_at"]
        resp = api_client.submit_patient_care_report(
            pcr["id"], make_flight_crew_headers(pilot["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_patient_care_report(pcr["id"], DISP))
        assert after["status"] == "SUBMITTED"
        assert after["submitted_at"] == submitted_at, "submitted_at must not move on the rejected resubmit"


class TestCrewShiftDoubleCloseRejected:
    def test_closed_shift_is_terminal(self):
        """PRD §3.1: "Closing a shift moves it from `OPEN` to `CLOSED`, stamps
        `actual_end_iso` with the logical now, and bumps the shift's `version`;
        any other from-state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/crew_shift_double_close_rejected
        """
        from test_helpers import create_base, create_crew_member, create_crew_shift
        set_clock("2026-08-01T00:00:00Z")
        base = create_base(name="Base A")
        medic = create_crew_member(base["id"], "Shift Ty", "PARAMEDIC")
        shift = create_crew_shift(medic["id"], "2026-08-01T00:00:00Z", "2026-08-01T10:00:00Z")
        set_clock("2026-08-01T10:00:00Z")
        closed = get_success_data(
            api_client.update_crew_shift(shift["id"], {"status": "CLOSED"}, OPS)
        )
        end1 = closed["actual_end_iso"]
        resp = api_client.update_crew_shift(shift["id"], {"status": "CLOSED"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_crew_shift(shift["id"], OPS))
        assert after["status"] == "CLOSED"
        assert after["actual_end_iso"] == end1, "actual_end_iso keeps its first value"


class TestDivertedMissionCanCompleteAtAlternate:
    def test_diverted_to_at_destination_to_completed(self):
        """PRD §3.5: "from `DIVERTED`, the normal advance to `AT_DESTINATION`
        resumes the chain."
        PRD §3.5: "Moving from `AT_DESTINATION` to `COMPLETED` requires every
        non-`CANCELLED` ground leg on the mission to be `COMPLETED`; a straggler
        rejects the completion with `ERR_GROUND_LEGS_PENDING`."

        Design: Corner/state_machines/diverted_mission_can_complete_at_alternate
        """
        ctx = setup_planning_mission(estimated_loaded_miles=60)
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        bed = create_bed_reservation(mission["id"], facility_name="County General", bed_type="ICU")
        create_ground_leg(
            mission["id"], leg_type="DESTINATION", bed_reservation_id=bed["id"],
            scheduled_pickup_iso="2026-08-01T09:30:00Z",
        )
        post_go_weather(mission["id"], pilot)
        advance_mission_through(mission["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT"])
        get_success_data(
            api_client.divert_mission(
                mission["id"],
                {"new_destination_facility": "Regional North", "reason": "Fog at primary"},
                make_flight_crew_headers(pilot["id"]),
            )
        )
        s1 = advance_mission(mission["id"], "AT_DESTINATION", headers=make_flight_crew_headers(pilot["id"]))
        assert s1["status"] == "AT_DESTINATION", "DIVERTED -> AT_DESTINATION is a declared hop"
        # The divert-cancelled DESTINATION leg does not block the completion gate.
        s2 = advance_mission(mission["id"], "COMPLETED", headers=make_flight_crew_headers(pilot["id"]))
        assert s2["status"] == "COMPLETED"
        aircraft_after = get_success_data(api_client.get_aircraft(ctx["aircraft"]["id"], DISP))
        assert aircraft_after["status"] == "AVAILABLE"
