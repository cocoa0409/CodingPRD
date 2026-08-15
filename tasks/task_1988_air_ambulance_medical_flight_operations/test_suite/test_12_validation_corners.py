"""Validation corner claims: auth presence, filing windows, weather launch
gates, repatriation document checks, uniqueness, fiscal guards, and request
shape."""
from test_helpers import (
    ApiErrorId,
    advance_mission,
    advance_mission_through,
    api_client,
    create_insurance_authorization,
    create_membership,
    create_mission_request,
    create_patient,
    create_pcr,
    full_document_set,
    get_success_data,
    make_flight_crew_headers,
    post_go_weather,
    post_weather,
    qa_review,
    set_clock,
    setup_finalized_invoice,
    setup_planning_mission,
    setup_repatriation_mission,
    submit_pcr,
    update_membership_safe,
    validate_error,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MED = TEST_USERS["medical_director_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestMissingAuthHeadersReturns401:
    def test_request_without_auth_headers_rejected(self):
        """PRD §2.1: "Every request must carry `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity in which they
        act. A request missing either header, or carrying an unrecognized role,
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api_client.list_mission_requests(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestTimelyFilingWindow:
    def test_day_90_submit_succeeds(self):
        """PRD §3.8: "the submission date must fall no later than 90 days after
        the mission's completion date, counted inclusively so that exactly 90
        days still files, else `ERR_TIMELY_FILING_EXPIRED`."

        Design: Corner/validations/timely_filing_day_90_allowed
        """
        # Build the fixture but hold the claim at FINALIZED by NOT submitting;
        # then advance the clock to completion + 90 days and submit.
        ctx, invoice, pcr = self._setup_finalized_ready()
        set_clock("2026-10-30T00:00:00Z")
        submitted = get_success_data(api_client.submit_invoice(invoice["id"], BILL))
        assert submitted["claim_status"] == "SUBMITTED", (
            "Day 90 exactly is inside the inclusive timely-filing window"
        )

    def _setup_finalized_ready(self):
        """COMPLETED mission 2026-08-01; invoice FINALIZED; PCR QA_APPROVED."""
        ctx, invoice = setup_finalized_invoice(actual_loaded_miles=0.5)
        pilot = ctx["roster"]["PILOT"]
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        submit_pcr(pcr["id"], pilot)
        qa_review(pcr["id"], "APPROVED", 0, reviewer_id="qa-officer-2")
        return ctx, invoice, pcr

    def test_day_91_submit_rejected(self):
        """PRD §3.8: "the submission date must fall no later than 90 days after
        the mission's completion date, counted inclusively so that exactly 90
        days still files, else `ERR_TIMELY_FILING_EXPIRED`."

        Design: Corner/validations/timely_filing_day_91_rejected
        """
        ctx, invoice, pcr = self._setup_finalized_ready()
        set_clock("2026-10-31T00:00:00Z")
        resp = api_client.submit_invoice(invoice["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXPIRED)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "FINALIZED"


class TestPcrSubmissionWindow:
    def _setup_completed_at_1000_with_draft_pcr(self):
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_planning_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            tier="BLS", medical_config="BLS_CAPABLE",
            transport_class="EMERGENCY_SCENE", origin_facility="Scene",
            estimated_loaded_miles=1, planned_duration_min=60,
        )
        pilot = ctx["roster"]["PILOT"]
        post_go_weather(ctx["mission"]["id"], pilot)
        from test_helpers import advance_mission_through
        advance_mission_through(
            ctx["mission"]["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION"]
        )
        set_clock("2026-08-01T10:00:00Z")
        advance_mission(ctx["mission"]["id"], "COMPLETED", headers=make_flight_crew_headers(pilot["id"]))
        pcr = create_pcr(ctx["mission"]["id"], pilot)
        return ctx, pilot, pcr

    def test_submit_exactly_24h_after_completion_succeeds(self):
        """PRD §3.9: "the logical now must fall no later than 24 hours after the
        mission's `completed_at`, counted inclusively so that exactly 24 hours
        still submits, else `ERR_PCR_WINDOW_EXPIRED`."

        Design: Corner/validations/pcr_window_exactly_24h_allowed
        """
        ctx, pilot, pcr = self._setup_completed_at_1000_with_draft_pcr()
        set_clock("2026-08-02T10:00:00Z")
        submitted = submit_pcr(pcr["id"], pilot)
        assert submitted["status"] == "SUBMITTED", (
            "Exactly 24h after completion is inside the inclusive PCR window"
        )

    def test_submit_one_minute_past_24h_rejected(self):
        """PRD §3.9: "the logical now must fall no later than 24 hours after the
        mission's `completed_at`, counted inclusively so that exactly 24 hours
        still submits, else `ERR_PCR_WINDOW_EXPIRED`."

        Design: Corner/validations/pcr_window_24h01m_rejected
        """
        ctx, pilot, pcr = self._setup_completed_at_1000_with_draft_pcr()
        set_clock("2026-08-02T10:01:00Z")
        resp = api_client.submit_patient_care_report(
            pcr["id"], make_flight_crew_headers(pilot["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PCR_WINDOW_EXPIRED)
        after = get_success_data(api_client.get_patient_care_report(pcr["id"], DISP))
        assert after["status"] == "DRAFT"


class TestMembershipReinstateWindow:
    def _setup_lapsed_at(self, lapse_clock="2026-08-01T12:00:00Z"):
        set_clock(lapse_clock)
        patient = create_patient(full_name="Re Instate", date_of_birth="1988-08-08", weight_kg=70)
        membership = create_membership(patient["id"])
        update_membership_safe(membership["id"], "LAPSED")
        return membership

    def test_reinstate_exactly_30_days_allowed(self):
        """PRD §3.2: "Reinstatement — `LAPSED` back to `ACTIVE` — is permitted
        only within 30 days of the lapse, counted inclusively so that exactly 30
        days after `lapsed_at` still passes; a later attempt is rejected with
        `ERR_REINSTATE_WINDOW_EXPIRED`, and a successful reinstatement clears
        `lapsed_at` back to null."

        Design: Corner/validations/membership_reinstate_day_30_allowed
        """
        membership = self._setup_lapsed_at()
        set_clock("2026-08-31T12:00:00Z")
        reinstated = update_membership_safe(membership["id"], "ACTIVE")
        assert reinstated["status"] == "ACTIVE"
        assert reinstated.get("lapsed_at") is None, "Reinstatement clears lapsed_at"

    def test_reinstate_day_31_rejected(self):
        """PRD §3.2: "Reinstatement — `LAPSED` back to `ACTIVE` — is permitted
        only within 30 days of the lapse, counted inclusively so that exactly 30
        days after `lapsed_at` still passes; a later attempt is rejected with
        `ERR_REINSTATE_WINDOW_EXPIRED`."

        Design: Corner/validations/membership_reinstate_day_31_rejected
        """
        membership = self._setup_lapsed_at()
        set_clock("2026-09-01T12:00:00Z")
        resp = api_client.update_membership(membership["id"], {"status": "ACTIVE"}, BILL)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_WINDOW_EXPIRED)
        after = get_success_data(api_client.get_membership(membership["id"], BILL))
        assert after["status"] == "LAPSED"


class TestMarginalLaunchWithoutAlternateRejected:
    def test_marginal_decision_without_alternate_fails_with_alternate_required(self):
        """PRD §3.4: "a `MARGINAL` decision is flyable only when an
        `alternate_destination` has been filed on the mission (otherwise
        `ERR_ALTERNATE_REQUIRED`)"

        Design: Corner/validations/marginal_launch_without_alternate_rejected
        """
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        # MARGINAL: ceiling 590 < 500*1.2=600 (ROTOR_WING DAY FLAT).
        wa = post_weather(mission["id"], mission["version"], pilot,
                          ceiling_ft=590, visibility_sm=5.0, wind_kt=10)
        assert wa["decision"] == "MARGINAL"
        resp = api_client.advance_mission(
            mission["id"], {"to_state": "LAUNCHED"}, make_flight_crew_headers(pilot["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ALTERNATE_REQUIRED)
        after = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert after["status"] == "PLANNING"


class TestStaleWeatherAssessmentRejected:
    def test_assessment_older_than_60_minutes_is_stale(self):
        """PRD §3.4: "At launch and at resume-from-hold, the newest assessment
        must be fresh — the logical now must be no later than `assessed_at` plus
        60 minutes, so an assessment exactly one hour old is still fresh — and
        an older newest-assessment is rejected with
        `ERR_WEATHER_ASSESSMENT_STALE`."

        Design: Corner/validations/stale_weather_assessment_over_60min_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        post_weather(mission["id"], mission["version"], pilot)
        # 61 minutes later the newest assessment is stale even though GO.
        set_clock("2026-08-01T01:01:00Z")
        resp = api_client.advance_mission(
            mission["id"], {"to_state": "LAUNCHED"}, make_flight_crew_headers(pilot["id"])
        )
        validate_error(resp, ApiErrorId.ERR_WEATHER_ASSESSMENT_STALE)
        after = get_success_data(api_client.get_mission(mission["id"], DISP))
        assert after["status"] == "PLANNING"


class TestFitToFlyExactly72hAllowed:
    def test_fit_to_fly_72h_old_passes_verification(self):
        """PRD §3.7: "Validity requires every `PASSPORT` and `VISA` entry to
        have an `expires_iso` strictly later than the logical now, and the
        `FIT_TO_FLY` entry to have been issued no more than 72 hours before the
        logical now — exactly 72 hours old still passes; any breach is
        `ERR_DOC_EXPIRED`."

        Design: Corner/validations/fit_to_fly_exactly_72h_allowed
        """
        docs = full_document_set(fit_to_fly_issued="2026-07-29T12:00:00Z")
        ctx, case = setup_repatriation_mission(with_documents=docs)
        set_clock("2026-08-01T12:00:00Z")
        verified = get_success_data(api_client.verify_repatriation_case(case["id"], MED))
        assert verified["status"] == "READY_TO_FLY", (
            "72h inclusive boundary passes verification"
        )


class TestRepatriationDemotionWhenFitToFlyAgesOut:
    def test_launch_gate_revalidation_demotes_case_and_fails(self):
        """PRD §3.7: "The launch gate of §3.4 re-validates the case's documents
        at wheels-up time, and if the fit-to-fly statement has aged past 72
        hours or a passport or visa has expired since verification, the case is
        lazily demoted back to `COLLECTING` and the launch fails with
        `ERR_DOC_EXPIRED`."

        Design: Corner/validations/repatriation_demotion_when_fit_to_fly_ages_out
        """
        # FIT_TO_FLY issued 2026-07-29T13:00 -> 71h old at verify (passes),
        # 73h old at the 14:00 launch attempt (fails).
        docs = full_document_set(fit_to_fly_issued="2026-07-29T13:00:00Z")
        ctx, case = setup_repatriation_mission(with_documents=docs)
        set_clock("2026-08-01T12:00:00Z")
        verified = get_success_data(api_client.verify_repatriation_case(case["id"], MED))
        assert verified["status"] == "READY_TO_FLY"
        set_clock("2026-08-01T14:00:00Z")
        pilot = ctx["roster"]["PILOT"]
        post_go_weather(ctx["mission"]["id"], pilot)
        resp = api_client.advance_mission(ctx["mission"]["id"], {"to_state": "LAUNCHED"}, DISP)
        validate_error(resp, ApiErrorId.ERR_DOC_EXPIRED)
        case_after = get_success_data(api_client.get_repatriation_case(case["id"], DISP))
        assert case_after["status"] == "COLLECTING", (
            f"Lazy demotion cycle edge must fire, got {case_after['status']}"
        )


class TestRepatriationVerifyCompletenessAndValidity:
    def test_missing_document_type_rejected_as_incomplete(self):
        """PRD §3.7: "Completeness then requires all four document types to be
        present among the case's entries; a gap is `ERR_DOCS_INCOMPLETE`."

        Design: Corner/errors/repat_verify_missing_document_rejected
        """
        docs = [
            d for d in full_document_set(fit_to_fly_issued="2026-07-31T00:00:00Z")
            if d["doc_type"] != "CUSTOMS_PRECLEARANCE"
        ]
        ctx, case = setup_repatriation_mission(with_documents=docs)
        resp = api_client.verify_repatriation_case(case["id"], MED)
        validate_error(resp, ApiErrorId.ERR_DOCS_INCOMPLETE)
        after = get_success_data(api_client.get_repatriation_case(case["id"], DISP))
        assert after["status"] == "COLLECTING"


class TestSubscaleOutOfRangeRejected:
    def test_reported_cardio_11_fails_intake(self):
        """PRD §3.2: "four requester-reported clinical subscales —
        `reported_cardio`, `reported_resp`, `reported_neuro`, and
        `reported_interventions`, each an integer from 0 to 10"
        PRD §3.2: "as is any subscale outside the 0-to-10 range." (shape
        failure under `ERR_VALIDATION`)
        PRD §2.8: "then request shape — required fields present, types correct,
        enum members valid, ranges respected, which covers the clinical
        subscales within 0 to 10 ... reported as `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/errors/subscale_out_of_range_rejected
        """
        patient = create_patient(full_name="Range Test", date_of_birth="1993-03-03", weight_kg=70)
        resp = api_client.create_mission_request(
            {
                "patient_id": patient["id"],
                "transport_class": "EMERGENCY_SCENE",
                "origin_facility": "Scene",
                "destination_facility": "County General",
                "reported_cardio": 11,
                "reported_resp": 1,
                "reported_neuro": 1,
                "reported_interventions": 0,
                "onset_iso": "2026-07-31T10:00:00Z",
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestAuthRequiredGateAndApprovalBypass:
    def _setup_scheduled_planning_with_go(self):
        ctx = setup_planning_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            tier="BLS", medical_config="BLS_CAPABLE",
            transport_class="SCHEDULED_INTERFACILITY", origin_facility="Clinic West",
            estimated_loaded_miles=30, planned_duration_min=90,
        )
        pilot = ctx["roster"]["PILOT"]
        post_go_weather(ctx["mission"]["id"], pilot)
        return ctx

    def test_launch_without_authorization_fails_then_succeeds_after_approval(self):
        """PRD §3.4: "and finally the fiscal gate — for
        `SCHEDULED_INTERFACILITY` and `INTERNATIONAL_REPATRIATION` missions
        where the request's `emergency_override` is false, an insurance
        authorization on this mission in `APPROVED` or `PARTIAL` status must
        exist, else `ERR_AUTH_REQUIRED`."
        PRD §3.8: "Recall from §3.4 that `APPROVED` and `PARTIAL` are the two
        states that satisfy the launch gate."

        Design: Corner/errors/auth_required_gate_and_approval_bypass
        """
        ctx = self._setup_scheduled_planning_with_go()
        mission_id = ctx["mission"]["id"]
        resp = api_client.advance_mission(mission_id, {"to_state": "LAUNCHED"}, DISP)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)
        auth = create_insurance_authorization(mission_id, payer_name="Acme Health", policy_number="POL-9")
        get_success_data(
            api_client.update_insurance_authorization(auth["id"], {"status": "APPROVED"}, BILL)
        )
        launched = advance_mission(mission_id, "LAUNCHED", headers=DISP)
        assert launched["status"] == "LAUNCHED", (
            "With the APPROVED authorization on file (and the GO assessment still fresh) "
            "the identical launch succeeds"
        )


