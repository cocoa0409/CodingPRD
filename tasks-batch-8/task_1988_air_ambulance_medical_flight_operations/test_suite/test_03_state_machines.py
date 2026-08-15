"""Non-linear state machines: the MissionRequest info cycle, the Invoice's
parallel claim/member dimensions, and the Mission weather hold-resume loop."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_mission,
    api_client,
    create_mission_request,
    create_patient,
    get_success_data,
    make_flight_crew_headers as make_fc,
    post_weather,
    set_clock,
    setup_member_protected_submitted_invoice,
    setup_planning_mission,
    setup_triaged_request,
    triage_request,
    validate_error,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]
MED = TEST_USERS["medical_director_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestMissionRequestInfoCycle:
    def test_triaged_to_pending_info_and_back_recomputes_acceptance_score(self):
        """PRD §3.2: "When the clinical picture is incomplete, the director
        sends the request back: from `TRIAGED` to `PENDING_INFO`, carrying an
        `info_note` describing what is needed. A `Dispatcher` answers with
        updated clinicals — `updated_cardio`, `updated_resp`, `updated_neuro`,
        `updated_interventions` — plus an `info_note`, which returns the request
        from `PENDING_INFO` to `TRIAGED` and recomputes the acceptance score and
        tier from the updated values under the same acceptance variant,
        deterioration bonus included."

        Design: Difficulty/non_linear_state_machine/mission_request_info_cycle
        """
        set_clock("2026-08-01T00:00:00Z")
        patient = create_patient(full_name="Amy Acute", date_of_birth="1975-11-02", weight_kg=65)
        request = create_mission_request(
            patient["id"],
            subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3},
            onset_iso="2026-07-31T23:00:00Z",
            transport_class="EMERGENCY_SCENE",
            origin_facility="Mile 42 I-10",
        )
        request = triage_request(
            request["id"], subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3}
        )
        assert request["status"] == "TRIAGED"
        pending = get_success_data(
            api_client.request_info(request["id"], {"info_note": "Need updated vitals trend"}, MED)
        )
        assert pending["status"] == "PENDING_INFO", (
            f"Expected PENDING_INFO loop state, got {pending['status']}"
        )
        # Loop back with worsening clinicals; onset still 60 min before now -> bonus applies.
        # 9*.25+7*.35+5*.25+3*.15 = 2.25+2.45+1.25+0.45 = 6.40; +2.0 bonus = 8.40.
        reloop = get_success_data(
            api_client.provide_info(
                request["id"],
                {
                    "updated_cardio": 9,
                    "updated_resp": 7,
                    "updated_neuro": 5,
                    "updated_interventions": 3,
                    "info_note": "Worsening respiratory status",
                },
                DISP,
            )
        )
        assert reloop["status"] == "TRIAGED", (
            f"Expected cycle closed back to TRIAGED, got {reloop['status']}"
        )
        assert reloop["acceptance_acuity_score"] == pytest.approx(8.4, abs=1e-9), (
            f"Expected recomputed acceptance 8.4, got {reloop['acceptance_acuity_score']}"
        )
        assert reloop["acuity_tier"] == "CCT"

    def test_provide_info_from_triaged_is_off_transition(self):
        """PRD §3.2: "A `Dispatcher` answers with updated clinicals ... which
        returns the request from `PENDING_INFO` to `TRIAGED`."
        PRD §2.8: "a transition requested from a state that does not support it
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/mission_request_info_cycle
        """
        _, request = setup_triaged_request()
        resp = api_client.provide_info(
            request["id"],
            {
                "updated_cardio": 9,
                "updated_resp": 7,
                "updated_neuro": 5,
                "updated_interventions": 3,
                "info_note": "unsolicited update",
            },
            DISP,
        )
        # provide-info is only declared from PENDING_INFO; TRIAGED is off-transition.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert after["status"] == "TRIAGED"


class TestInvoiceParallelClaimAndMemberDimensions:
    def test_member_dimension_evaluated_at_finalize_independent_of_claim(self):
        """PRD §3.8: "Finalize recomputes every line and stores the settlement
        in `final_total_cents`, moves `claim_status` to `FINALIZED`, and
        evaluates the member dimension for the first and only time: if a
        membership subscription exists for the mission's patient with status
        `ACTIVE` and an `effective_from` on or before the date of the mission's
        `completed_at`, the invoice is `MEMBER_PROTECTED` and `membership_id` is
        bound to that subscription; otherwise it is `NON_MEMBER`."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_claim_and_member_dimensions
        """
        _, invoice, _, membership = setup_member_protected_submitted_invoice(
            membership_effective_from="2026-08-01", membership_tier="FAMILY"
        )
        # Re-read at FINALIZED point is not possible post-submit; instead verify the
        # evaluated outcome and binding now: the dimension was set at finalize and
        # the payer response below must not move it.
        assert invoice["claim_status"] == "SUBMITTED"
        assert invoice["member_adjustment_status"] == "MEMBER_PROTECTED"
        assert invoice["membership_id"] == membership["id"]

    def test_payer_response_moves_claim_dimension_only_then_writeoff_moves_member(self):
        """PRD §3.8: "The write-off moves the entire residual:
        `member_writeoff_cents` is set to the current
        `patient_responsibility_cents`, `patient_responsibility_cents` becomes
        zero, and the dimension advances to `WRITEOFF_POSTED`."
        PRD §3.8: "On a `PAID` or `PARTIALLY_PAID` response posted while the
        member dimension reads `NON_MEMBER`, the dimension moves to
        `BALANCE_BILLED`; a `DENIED` response applies the waterfall but leaves
        the member dimension unchanged."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_claim_and_member_dimensions
        """
        _, invoice, _, membership = setup_member_protected_submitted_invoice(
            membership_effective_from="2026-08-01", membership_tier="FAMILY"
        )
        # BLS rotor, actual 0.5 mi: final 1,800,000+8,000+560+0 = 1,808,560.
        assert invoice["final_total_cents"] == 1808560
        paid = get_success_data(
            api_client.payer_response(
                invoice["id"],
                {"outcome": "PAID", "paid_cents": 1808560, "contractual_adjustment_cents": 0},
                BILL,
            )
        )
        # Payer response moved the claim dimension only; member dimension stays pinned.
        assert paid["claim_status"] == "PAID"
        assert paid["member_adjustment_status"] == "MEMBER_PROTECTED", (
            "Payer response must not move the member dimension off MEMBER_PROTECTED"
        )
        written = get_success_data(api_client.member_writeoff(invoice["id"], BILL))
        assert written["member_adjustment_status"] == "WRITEOFF_POSTED"
        assert written["patient_responsibility_cents"] == 0
        assert written["member_writeoff_cents"] == 0
        assert written["membership_id"] == membership["id"]


class TestMissionWeatherHoldResumeLoop:
    def _setup_launched_then_held(self):
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Mile 9 US-60"
        )
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        post_weather(mission["id"], mission["version"], pilot)
        advance_mission(mission["id"], "LAUNCHED")
        held = advance_mission(mission["id"], "WEATHER_HOLD")
        return ctx, pilot, held

    def test_no_go_assessment_blocks_resume_from_hold(self):
        """PRD §3.4: "Resuming consumes a fresh `GO`: the newest assessment must
        be no more than 60 minutes old and must read `GO` — anything else,
        including a `MARGINAL` decision, is rejected with
        `ERR_BELOW_WEATHER_MINIMUMS`. No alternate-destination rescue exists on
        resume."

        Design: Difficulty/non_linear_state_machine/mission_weather_hold_resume_loop
        """
        ctx, pilot, held = self._setup_launched_then_held()
        mission_id = ctx["mission"]["id"]
        # NO_GO: ceiling 100 < 500 required (ROTOR_WING DAY FLAT).
        post_weather(mission_id, held["version"], pilot, ceiling_ft=100, visibility_sm=0.5)
        resp = api_client.advance_mission(mission_id, {"to_state": "LAUNCHED"}, make_fc(pilot["id"]))
        validate_error(resp, ApiErrorId.ERR_BELOW_WEATHER_MINIMUMS)
        after = get_success_data(api_client.get_mission(mission_id, DISP))
        assert after["status"] == "WEATHER_HOLD"

    def test_fresh_go_assessment_resumes_the_hold_resume_loop(self):
        """PRD §3.4: "From `LAUNCHED`, a `Dispatcher` or `FlightCrew` caller may
        move the mission to `WEATHER_HOLD`, and from `WEATHER_HOLD` back to
        `LAUNCHED`; the loop may repeat. Resuming consumes a fresh `GO`: the
        newest assessment must be no more than 60 minutes old and must read
        `GO`."

        Design: Difficulty/non_linear_state_machine/mission_weather_hold_resume_loop
        """
        ctx, pilot, held = self._setup_launched_then_held()
        mission_id = ctx["mission"]["id"]
        post_weather(mission_id, held["version"], pilot, ceiling_ft=100, visibility_sm=0.5)
        resp = api_client.advance_mission(mission_id, {"to_state": "LAUNCHED"}, make_fc(pilot["id"]))
        validate_error(resp, ApiErrorId.ERR_BELOW_WEATHER_MINIMUMS)
        mission_now = get_success_data(api_client.get_mission(mission_id, DISP))
        go = post_weather(
            mission_id, mission_now["version"], pilot,
            ceiling_ft=1200, visibility_sm=6.0, wind_kt=8,
        )
        assert go["decision"] == "GO"
        resumed = advance_mission(mission_id, "LAUNCHED", headers=make_fc(pilot["id"]))
        assert resumed["status"] == "LAUNCHED", (
            f"Expected hold-resume loop to close at LAUNCHED, got {resumed['status']}"
        )
