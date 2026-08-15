"""Validation-order conflicts: when one request violates two rules, the PRD's
fixed check order decides which error is reported."""
from test_helpers import (
    ApiErrorId,
    accept_request,
    api_client,
    create_aircraft,
    create_base,
    create_crew_member,
    create_invoice,
    create_pcr,
    get_success_data,
    make_flight_crew_headers,
    post_weather,
    set_clock,
    setup_base_with_crew,
    setup_finalized_invoice,
    setup_planning_mission,
    setup_triaged_request,
    submit_pcr,
    triage_request,
    validate_error,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MED = TEST_USERS["medical_director_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestStateBeatsSafetyOnAccept:
    def test_declined_request_accept_reports_request_not_triaged(self):
        """PRD §3.3: "Acceptance enforces its checks in a fixed order, and an
        early failure masks later ones. The request must currently be `TRIAGED`
        — anything else is rejected with `ERR_REQUEST_NOT_TRIAGED`. Then the
        tail's `medical_config` rank must meet or exceed the request's
        `acuity_tier` rank: a `CCT` request needs a `CCT_CAPABLE` aircraft, an
        `ALS` request needs `ALS_CAPABLE` or better; a shortfall is
        `ERR_ACUITY_EXCEEDS_CONFIG`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_accept
        """
        set_clock("2026-08-01T00:00:00Z")
        base, aircraft, roster = setup_base_with_crew(medical_config="BLS_CAPABLE")
        medic = create_crew_member(base["id"], "Pam Medic", "PARAMEDIC")
        # CCT-tier request (fresh onset 60 min before now -> 7.8 acceptance).
        patient, request = setup_triaged_request(
            subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3},
            onset_iso="2026-07-31T23:00:00Z",
            transport_class="EMERGENCY_SCENE",
            origin_facility="Mile 42 I-10",
        )
        assert request["acuity_tier"] == "CCT"
        declined = get_success_data(
            api_client.decline_mission_request(
                request["id"], {"reason": "No receiving bed available"}, MED
            )
        )
        assert declined["status"] == "DECLINED"
        # Both rules are violated: the request is not TRIAGED, and the BLS tail
        # fails the CCT config gate. The earlier accept check wins.
        resp = api_client.accept_mission_request(
            request["id"],
            {
                "aircraft_id": aircraft["id"],
                "crew": [
                    {"crew_member_id": roster["PILOT"]["id"], "role_in_mission": "PILOT"},
                    {"crew_member_id": roster["NURSE"]["id"], "role_in_mission": "NURSE"},
                    {"crew_member_id": medic["id"], "role_in_mission": "PARAMEDIC"},
                ],
                "estimated_loaded_miles": 40,
                "planned_launch_iso": "2026-08-01T06:00:00Z",
                "planned_duration_min": 120,
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_TRIAGED)
        after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert after["status"] == "DECLINED"

    def test_received_request_accept_reports_request_not_triaged_not_config(self):
        """PRD §3.3: "Acceptance enforces its checks in a fixed order, and an
        early failure masks later ones. The request must currently be `TRIAGED`
        — anything else is rejected with `ERR_REQUEST_NOT_TRIAGED`."
        PRD §3.3: "a `CCT` request needs a `CCT_CAPABLE` aircraft, an `ALS`
        request needs `ALS_CAPABLE` or better; a shortfall is
        `ERR_ACUITY_EXCEEDS_CONFIG`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_accept
        """
        from test_helpers import create_mission_request, create_patient
        set_clock("2026-08-01T00:00:00Z")
        base, aircraft, roster = setup_base_with_crew(medical_config="BLS_CAPABLE")
        patient = create_patient()
        # RECEIVED request (never triaged) + BLS tail: state check runs first.
        request = create_mission_request(patient["id"])
        assert request["status"] == "RECEIVED"
        resp = api_client.accept_mission_request(
            request["id"],
            {
                "aircraft_id": aircraft["id"],
                "crew": [
                    {"crew_member_id": roster["PILOT"]["id"], "role_in_mission": "PILOT"},
                    {"crew_member_id": roster["NURSE"]["id"], "role_in_mission": "NURSE"},
                ],
                "estimated_loaded_miles": 40,
                "planned_launch_iso": "2026-08-01T06:00:00Z",
                "planned_duration_min": 120,
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_TRIAGED)


class TestSafetyBeatsFiscalOnLaunch:
    def _setup_scheduled_mission_with_no_go(self):
        ctx = setup_planning_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            tier="BLS",
            medical_config="BLS_CAPABLE",
            transport_class="SCHEDULED_INTERFACILITY",
            origin_facility="Clinic West",
            estimated_loaded_miles=30,
            planned_duration_min=90,
        )
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        # NO_GO: ceiling 100 < 500 required (ROTOR_WING DAY FLAT).
        wa = post_weather(mission["id"], mission["version"], pilot,
                          ceiling_ft=100, visibility_sm=0.5)
        assert wa["decision"] == "NO_GO"
        return ctx

    def test_no_go_launch_reports_weather_not_auth(self):
        """PRD §3.4: "Its gate evaluates in a fixed order: first the roster
        check ... then the weather block — the newest assessment must exist and
        carry decision `GO` (a `NO_GO` decision, or no assessment at all, is
        `ERR_BELOW_WEATHER_MINIMUMS`) ... and finally the fiscal gate — for
        `SCHEDULED_INTERFACILITY` and `INTERNATIONAL_REPATRIATION` missions
        where the request's `emergency_override` is false, an insurance
        authorization on this mission in `APPROVED` or `PARTIAL` status must
        exist, else `ERR_AUTH_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_launch
        """
        ctx = self._setup_scheduled_mission_with_no_go()
        mission_id = ctx["mission"]["id"]
        # No InsuranceAuthorization on file, so the fiscal gate would also fail —
        # but the weather block runs earlier in the stated order.
        resp = api_client.advance_mission(mission_id, {"to_state": "LAUNCHED"}, DISP)
        validate_error(resp, ApiErrorId.ERR_BELOW_WEATHER_MINIMUMS)
        after = get_success_data(api_client.get_mission(mission_id, DISP))
        assert after["status"] == "PLANNING"

    def test_no_go_launch_with_auth_absent_never_surfaces_auth_error(self):
        """PRD §3.4: "then the weather block — the newest assessment must exist
        and carry decision `GO` (a `NO_GO` decision, or no assessment at all, is
        `ERR_BELOW_WEATHER_MINIMUMS`)"
        PRD §3.4: "and finally the fiscal gate — for `SCHEDULED_INTERFACILITY`
        and `INTERNATIONAL_REPATRIATION` missions where the request's
        `emergency_override` is false, an insurance authorization on this
        mission in `APPROVED` or `PARTIAL` status must exist, else
        `ERR_AUTH_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_launch
        """
        ctx = self._setup_scheduled_mission_with_no_go()
        mission_id = ctx["mission"]["id"]
        pilot = ctx["roster"]["PILOT"]
        # Same double-violation via the FlightCrew caller path.
        resp = api_client.advance_mission(
            mission_id, {"to_state": "LAUNCHED"}, make_flight_crew_headers(pilot["id"])
        )
        err = resp.json()["data"]["error_id"]
        assert err == ApiErrorId.ERR_BELOW_WEATHER_MINIMUMS, (
            f"Weather block must mask the fiscal gate; got {err}"
        )


class TestReferentialBeatsTemporalOnSubmit:
    def _setup_finalized_invoice_with_unapproved_pcr(self):
        ctx, invoice = setup_finalized_invoice(actual_loaded_miles=0.5)
        pilot = ctx["roster"]["PILOT"]
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        submit_pcr(pcr["id"], pilot)  # SUBMITTED, never QA-reviewed
        return ctx, invoice

    def test_submit_reports_pcr_not_approved_over_timely_filing(self):
        """PRD §3.8: "Two gates guard submission, checked in this order so a
        clinical-record gap surfaces before a deadline one: the mission's
        patient care report must be `QA_APPROVED`, else `ERR_PCR_NOT_APPROVED`;
        and the submission date must fall no later than 90 days after the
        mission's completion date, counted inclusively so that exactly 90 days
        still files, else `ERR_TIMELY_FILING_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_submit
        """
        ctx, invoice = self._setup_finalized_invoice_with_unapproved_pcr()
        # 91 days after the 2026-08-01 completion: both gates would fail; the
        # PCR gate is listed first in the workflow's stated order.
        set_clock("2026-10-31T00:00:00Z")
        resp = api_client.submit_invoice(invoice["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_PCR_NOT_APPROVED)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "FINALIZED"

    def test_submit_reports_pcr_not_approved_inside_the_window_too(self):
        """PRD §3.8: "the mission's patient care report must be `QA_APPROVED`,
        else `ERR_PCR_NOT_APPROVED`"
        PRD §3.8: "Two gates guard submission, checked in this order so a
        clinical-record gap surfaces before a deadline one."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_submit
        """
        ctx, invoice = self._setup_finalized_invoice_with_unapproved_pcr()
        # Same referential failure but comfortably inside the 90-day window:
        # confirms the error is the PCR gate itself, not the deadline.
        resp = api_client.submit_invoice(invoice["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_PCR_NOT_APPROVED)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "FINALIZED"
