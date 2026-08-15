"""Cross-entity state dependencies: invoice submit gated on PCR QA_APPROVED,
international launch gated on READY_TO_FLY, accept gated on aircraft not in
MAINTENANCE."""
from test_helpers import (
    ApiErrorId,
    advance_mission,
    api_client,
    create_pcr,
    get_success_data,
    make_flight_crew_headers,
    post_go_weather,
    qa_review,
    setup_finalized_invoice,
    setup_repatriation_mission,
    setup_triaged_request,
    setup_base_with_crew,
    submit_pcr,
    validate_error,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]
OPS = TEST_USERS["ops_admin_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestInvoiceSubmitRequiresPcrQaApproved:
    def _setup_finalized_with_submitted_pcr(self):
        ctx, invoice = setup_finalized_invoice(actual_loaded_miles=0.5)
        pilot = ctx["roster"]["PILOT"]
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        submit_pcr(pcr["id"], pilot)
        return ctx, invoice, pcr, pilot

    def test_submit_blocked_while_pcr_only_submitted(self):
        """PRD §3.8: "Two gates guard submission, checked in this order so a
        clinical-record gap surfaces before a deadline one: the mission's
        patient care report must be `QA_APPROVED`, else `ERR_PCR_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/invoice_submit_requires_pcr_qa_approved
        """
        ctx, invoice, pcr, pilot = self._setup_finalized_with_submitted_pcr()
        resp = api_client.submit_invoice(invoice["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_PCR_NOT_APPROVED)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "FINALIZED"

    def test_submit_opens_once_pcr_reaches_qa_approved(self):
        """PRD §3.8: "the mission's patient care report must be `QA_APPROVED`,
        else `ERR_PCR_NOT_APPROVED`"
        PRD §3.8: "Submitting the claim moves `FINALIZED` to `SUBMITTED` — or,
        after an appeal, `APPEALED` to `RESUBMITTED`; from any other claim state
        it is `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/invoice_submit_requires_pcr_qa_approved
        """
        ctx, invoice, pcr, pilot = self._setup_finalized_with_submitted_pcr()
        validate_error(api_client.submit_invoice(invoice["id"], BILL), ApiErrorId.ERR_PCR_NOT_APPROVED)
        qa_review(pcr["id"], "APPROVED", 0, reviewer_id="qa-officer-9")
        submitted = get_success_data(api_client.submit_invoice(invoice["id"], BILL))
        assert submitted["claim_status"] == "SUBMITTED", (
            f"After QA_APPROVED the Invoice transition must open, got {submitted['claim_status']}"
        )


class TestInternationalLaunchRequiresReadyCase:
    def test_launch_blocked_while_case_collecting(self):
        """PRD §3.4: "then, for `INTERNATIONAL_REPATRIATION` missions,
        repatriation readiness — the case must be `READY_TO_FLY`, else
        `ERR_REPATRIATION_NOT_READY`"

        Design: Difficulty/cross_entity_state_dependency/international_launch_requires_ready_case
        """
        ctx, case = setup_repatriation_mission()
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        wa = post_go_weather(mission["id"], pilot)
        assert wa["decision"] == "GO", "Weather gate satisfied; failure must come from the case"
        resp = api_client.advance_mission(mission["id"], {"to_state": "LAUNCHED"}, DISP)
        validate_error(resp, ApiErrorId.ERR_REPATRIATION_NOT_READY)
        mission_after = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert mission_after["status"] == "PLANNING"
        case_after = get_success_data(api_client.get_repatriation_case(case["id"], DISP))
        assert case_after["status"] == "COLLECTING"

    def test_launch_blocked_even_with_emergency_override(self):
        """PRD §3.4: "then, for `INTERNATIONAL_REPATRIATION` missions,
        repatriation readiness — the case must be `READY_TO_FLY`, else
        `ERR_REPATRIATION_NOT_READY`"
        PRD §3.2: "may set `emergency_override`, a boolean defaulting to `false`
        that formally declares an emergency and, downstream, bypasses the
        payer-authorization launch gate (`ERR_AUTH_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/international_launch_requires_ready_case
        """
        # emergency_override bypasses only the fiscal gate; the repatriation gate stands.
        ctx, case = setup_repatriation_mission()
        request = get_success_data(
            api_client.get_mission_request(ctx["request"]["id"], DISP)
        )
        assert request["emergency_override"] is True
        pilot = ctx["roster"]["PILOT"]
        post_go_weather(ctx["mission"]["id"], pilot)
        resp = api_client.advance_mission(
            ctx["mission"]["id"], {"to_state": "LAUNCHED"},
            make_flight_crew_headers(pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPATRIATION_NOT_READY)


class TestAcceptRequiresAircraftNotInMaintenance:
    def test_accept_rejected_when_tail_in_maintenance(self):
        """PRD §3.3: "The aircraft itself must not be in `MAINTENANCE` —
        `AVAILABLE` or `ASSIGNED` both pass, because a tail may hold multiple
        non-overlapping future bookings — and a `MAINTENANCE` tail is rejected
        with `ERR_AIRCRAFT_NOT_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/accept_requires_aircraft_not_in_maintenance
        """
        set_clock_safe()
        base, aircraft, roster = setup_base_with_crew(medical_config="CCT_CAPABLE")
        get_success_data(api_client.update_aircraft(aircraft["id"], {"status": "MAINTENANCE"}, OPS))
        _, request = setup_triaged_request()
        resp = api_client.accept_mission_request(
            request["id"],
            {
                "aircraft_id": aircraft["id"],
                "crew": [
                    {"crew_member_id": roster["PILOT"]["id"], "role_in_mission": "PILOT"},
                    {"crew_member_id": roster["NURSE"]["id"], "role_in_mission": "NURSE"},
                ],
                "estimated_loaded_miles": 60,
                "planned_launch_iso": "2026-08-01T06:00:00Z",
                "planned_duration_min": 120,
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AVAILABLE)
        after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert after["status"] == "TRIAGED"
        missions, meta = _list_missions_for_request(request["id"])
        assert meta["total_count"] == 0, "No Mission may exist for the still-TRIAGED request"

    def test_accept_succeeds_after_tail_returns_to_available(self):
        """PRD §3.1: "an `OpsAdmin` may set an `AVAILABLE` tail to `MAINTENANCE`
        and return a `MAINTENANCE` tail to `AVAILABLE`"
        PRD §3.3: "The aircraft itself must not be in `MAINTENANCE` —
        `AVAILABLE` or `ASSIGNED` both pass."

        Design: Difficulty/cross_entity_state_dependency/accept_requires_aircraft_not_in_maintenance
        """
        set_clock_safe()
        base, aircraft, roster = setup_base_with_crew(medical_config="CCT_CAPABLE")
        get_success_data(api_client.update_aircraft(aircraft["id"], {"status": "MAINTENANCE"}, OPS))
        get_success_data(api_client.update_aircraft(aircraft["id"], {"status": "AVAILABLE"}, OPS))
        _, request = setup_triaged_request()
        from test_helpers import accept_request
        mission = accept_request(
            request["id"], aircraft["id"],
            [(roster["PILOT"]["id"], "PILOT"), (roster["NURSE"]["id"], "NURSE")],
            estimated_loaded_miles=60,
        )
        assert mission["status"] == "PLANNING"


def _list_missions_for_request(request_id):
    from test_helpers import validate_paginated
    return validate_paginated(
        api_client.list_missions(DISP, params={"mission_request_id": request_id})
    )


def set_clock_safe():
    from test_helpers import set_clock
    set_clock()
