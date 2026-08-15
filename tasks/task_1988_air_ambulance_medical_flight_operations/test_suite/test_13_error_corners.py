"""Error-catalog corner claims: uniqueness guards, fiscal guards, safety
rejections, and launch/completion gating errors."""
from test_helpers import (
    ApiErrorId,
    advance_ground_leg,
    advance_mission,
    advance_mission_through,
    api_client,
    create_bed_reservation,
    create_crew_member,
    create_ground_leg,
    create_invoice,
    create_mission_request,
    create_patient,
    create_pcr,
    full_document_set,
    get_success_data,
    make_flight_crew_headers,
    post_go_weather,
    qa_review,
    set_clock,
    setup_base_with_crew,
    setup_completed_mission,
    setup_planning_mission,
    setup_repatriation_mission,
    setup_submitted_invoice,
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


class TestDuplicateInvoiceRejected:
    def test_second_invoice_for_same_mission_rejected(self):
        """PRD §3.8: "A `BillingSpecialist` creates it with nothing but the
        `mission_id`; exactly one invoice may exist per mission, and a second
        attempt is rejected with `ERR_DUPLICATE_INVOICE`."

        Design: Corner/errors/duplicate_invoice_rejected
        """
        ctx = setup_planning_mission()
        create_invoice(ctx["mission"]["id"])
        resp = api_client.create_invoice({"mission_id": ctx["mission"]["id"]}, BILL)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE, 409)


class TestDuplicateRepatriationCaseRejected:
    def test_second_case_for_same_mission_rejected(self):
        """PRD §3.7: "A `Dispatcher` opens exactly one documentation case per
        mission — a second case for the same mission is rejected with
        `ERR_DUPLICATE_REPATRIATION_CASE`."

        Design: Corner/errors/duplicate_repatriation_case_rejected
        """
        ctx, case = setup_repatriation_mission()
        resp = api_client.create_repatriation_case(
            {
                "mission_id": ctx["mission"]["id"],
                "destination_country": "MX",
                "receiving_facility": "County General",
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPATRIATION_CASE, 409)


class TestDuplicatePcrRejected:
    def test_second_record_for_same_mission_rejected(self):
        """PRD §3.9: "A second record for the same mission is rejected with
        `ERR_DUPLICATE_PCR`."

        Design: Corner/errors/duplicate_pcr_rejected
        """
        ctx = setup_completed_mission(transport_class="EMERGENCY_SCENE", origin_facility="Scene")
        pilot = ctx["roster"]["PILOT"]
        nurse = ctx["roster"]["NURSE"]
        create_pcr(ctx["mission"]["id"], pilot)
        # Even authored by the other crew member, the mission already has a record.
        resp = api_client.create_patient_care_report(
            {
                "mission_id": ctx["mission"]["id"],
                "author_crew_id": nurse["id"],
                "vitals_summary": "dup",
                "interventions_summary": "dup",
                "meds_summary": "dup",
            },
            make_flight_crew_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PCR, 409)


class TestWriteoffNonMemberRejected:
    def test_writeoff_rejected_when_dimension_balance_billed(self):
        """PRD §3.8: "If the dimension is anything other than
        `MEMBER_PROTECTED` — the patient was a non-member, the membership had
        lapsed, or its `effective_from` fell after the completion date — the
        attempt is `ERR_MEMBERSHIP_NOT_ELIGIBLE`."
        PRD §3.8: "On a `PAID` or `PARTIALLY_PAID` response posted while the
        member dimension reads `NON_MEMBER`, the dimension moves to
        `BALANCE_BILLED`."

        Design: Corner/errors/writeoff_non_member_rejected
        """
        # No membership for this patient: finalize evaluates NON_MEMBER.
        _, invoice, _ = setup_submitted_invoice(actual_loaded_miles=0.5, qa_reviewer_id="qa-officer-3")
        assert invoice["member_adjustment_status"] == "NON_MEMBER"
        paid = get_success_data(
            api_client.payer_response(
                invoice["id"],
                {"outcome": "PAID", "paid_cents": 400000, "contractual_adjustment_cents": 100000},
                BILL,
            )
        )
        # ALS rotor, actual 0.5 mi -> final 1,928,560; residual 1,428,560.
        assert paid["member_adjustment_status"] == "BALANCE_BILLED"
        assert paid["patient_responsibility_cents"] == 1428560
        resp = api_client.member_writeoff(invoice["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ELIGIBLE)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["member_writeoff_cents"] == 0


class TestPayerResponseOverpaymentRejected:
    def test_paid_plus_adjustment_over_total_rejected(self):
        """PRD §3.8: "the posting must respect the ledger guard: `paid_cents`
        plus `contractual_adjustment_cents` must not exceed `final_total_cents`,
        else `ERR_LEDGER_IMBALANCE`."

        Design: Corner/errors/payer_response_overpayment_rejected
        """
        _, invoice, _ = setup_submitted_invoice(actual_loaded_miles=0.5, qa_reviewer_id="qa-officer-4")
        # ALS rotor, actual 0.5 mi -> final 1,928,560.
        assert invoice["final_total_cents"] == 1928560
        resp = api_client.payer_response(
            invoice["id"],
            {"outcome": "PAID", "paid_cents": 1928560, "contractual_adjustment_cents": 1},
            BILL,
        )
        validate_error(resp, ApiErrorId.ERR_LEDGER_IMBALANCE)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "SUBMITTED"
        assert after["insurer_paid_cents"] == 0


class TestAppealThirdTimeRejected:
    def test_third_appeal_exceeds_cap(self):
        """PRD §3.8: "A denial can be appealed, at most twice. The appeal
        requires `claim_status` of `DENIED` (else `ERR_INVALID_STATE`) and an
        `appeal_count` below 2 — the cap means at most two appeals per invoice,
        and an attempt beyond the cap is `ERR_APPEAL_LIMIT`."

        Design: Corner/errors/appeal_third_time_rejected
        """
        _, invoice, _ = setup_submitted_invoice(actual_loaded_miles=0.5, qa_reviewer_id="qa-officer-5")
        for _ in range(2):
            get_success_data(
                api_client.payer_response(
                    invoice["id"],
                    {"outcome": "DENIED", "paid_cents": 0, "contractual_adjustment_cents": 0},
                    BILL,
                )
            )
            get_success_data(api_client.appeal_invoice(invoice["id"], BILL))
            get_success_data(api_client.submit_invoice(invoice["id"], BILL))
        denied3 = get_success_data(
            api_client.payer_response(
                invoice["id"],
                {"outcome": "DENIED", "paid_cents": 0, "contractual_adjustment_cents": 0},
                BILL,
            )
        )
        assert denied3["appeal_count"] == 2
        assert denied3["claim_status"] == "DENIED"
        resp = api_client.appeal_invoice(invoice["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "DENIED"
        assert after["appeal_count"] == 2


class TestAcceptAcuityExceedsConfigRejected:
    def test_cct_request_on_als_tail_rejected(self):
        """PRD §3.3: "Then the tail's `medical_config` rank must meet or exceed
        the request's `acuity_tier` rank: a `CCT` request needs a `CCT_CAPABLE`
        aircraft, an `ALS` request needs `ALS_CAPABLE` or better; a shortfall is
        `ERR_ACUITY_EXCEEDS_CONFIG`."

        Design: Corner/errors/accept_acuity_exceeds_config_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        base, aircraft, roster = setup_base_with_crew(medical_config="ALS_CAPABLE")
        medic = create_crew_member(base["id"], "Pam Medic", "PARAMEDIC")
        # CCT tier: fresh onset (60 min) with 8/6/5/3 -> 7.8 acceptance.
        _, request = setup_triaged_request(
            subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3},
            onset_iso="2026-07-31T23:00:00Z",
            transport_class="EMERGENCY_SCENE",
            origin_facility="Mile 42 I-10",
        )
        assert request["acuity_tier"] == "CCT"
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
        validate_error(resp, ApiErrorId.ERR_ACUITY_EXCEEDS_CONFIG)
        after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert after["status"] == "TRIAGED"
        aircraft_after = get_success_data(api_client.get_aircraft(aircraft["id"], DISP))
        assert aircraft_after["status"] == "AVAILABLE"


class TestAcceptCctWithoutParamedicRejected:
    def test_cct_roster_missing_paramedic_rejected(self):
        """PRD §3.3: "Next the roster must cover the tier's composition minimum
        — every tier requires exactly one `PILOT` and one `NURSE`, and `CCT`
        additionally requires exactly one `PARAMEDIC` — with each role filled by
        exactly one assignment and no role duplicated; a gap or a duplicate is
        `ERR_CREW_COMPOSITION_INCOMPLETE`."

        Design: Corner/errors/accept_cct_without_paramedic_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        base, aircraft, roster = setup_base_with_crew(medical_config="CCT_CAPABLE")
        _, request = setup_triaged_request(
            subscales={"cardio": 8, "resp": 6, "neuro": 5, "interv": 3},
            onset_iso="2026-07-31T23:00:00Z",
            transport_class="EMERGENCY_SCENE",
            origin_facility="Mile 42 I-10",
        )
        assert request["acuity_tier"] == "CCT"
        # Config passes (CCT_CAPABLE) but the roster lacks the PARAMEDIC.
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
        validate_error(resp, ApiErrorId.ERR_CREW_COMPOSITION_INCOMPLETE)
        after = get_success_data(api_client.get_mission_request(request["id"], DISP))
        assert after["status"] == "TRIAGED"
        aircraft_after = get_success_data(api_client.get_aircraft(aircraft["id"], DISP))
        assert aircraft_after["status"] == "AVAILABLE"


class TestAssignInactiveCrewRejected:
    def test_assignment_for_inactive_member_rejected(self):
        """PRD §3.3: "The mission must still be `PLANNING` (else
        `ERR_INVALID_STATE`), the member must be `ACTIVE` (else
        `ERR_CREW_UNAVAILABLE`), and the supplied `role_in_mission` must not
        duplicate a role already `ASSIGNED` on that mission (else
        `ERR_CREW_COMPOSITION_INCOMPLETE`)."

        Design: Corner/errors/assign_inactive_crew_rejected
        """
        ctx = setup_planning_mission()
        base = ctx["base"]
        medic = create_crew_member(base["id"], "Pam Medic", "PARAMEDIC")
        get_success_data(api_client.update_crew_member(medic["id"], {"status": "INACTIVE"}, OPS))
        resp = api_client.create_crew_assignment(
            {
                "mission_id": ctx["mission"]["id"],
                "crew_member_id": medic["id"],
                "role_in_mission": "PARAMEDIC",
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_UNAVAILABLE)
        data, meta = _list_assignments_for(ctx["mission"]["id"], medic["id"])
        assert meta["total_count"] == 0, "No CrewAssignment may be persisted for the INACTIVE member"


class TestShiftOverlapPositiveMinutesRejected:
    def test_candidate_overlapping_existing_shift_rejected(self):
        """PRD §3.1: "If any existing shift of the same member, `OPEN` or
        `CLOSED`, intersects the candidate window by at least one minute, the
        create is rejected with `ERR_SHIFT_OVERLAP`."

        Design: Corner/errors/shift_overlap_positive_minutes_rejected
        """
        from test_helpers import create_base, create_crew_shift
        set_clock("2026-08-01T00:00:00Z")
        base = create_base(name="Base A")
        medic = create_crew_member(base["id"], "Olivia Overlap", "PARAMEDIC")
        create_crew_shift(medic["id"], "2026-08-01T00:00:00Z", "2026-08-01T10:00:00Z")
        # 09:00-12:00 intersects the existing 00:00-10:00 shift by 60 minutes.
        resp = api_client.create_crew_shift(
            {
                "crew_member_id": medic["id"],
                "planned_start_iso": "2026-08-01T09:00:00Z",
                "planned_end_iso": "2026-08-01T12:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, 409)


class TestFinalizeBeforeMissionCompletedRejected:
    def test_finalize_mid_flight_rejected(self):
        """PRD §3.8: "The invoice must be `DRAFT` (else `ERR_INVALID_STATE`) and
        the owning mission must be `COMPLETED` (else `ERR_MISSION_NOT_COMPLETED`)."

        Design: Corner/errors/finalize_before_mission_completed_rejected
        """
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        invoice = create_invoice(ctx["mission"]["id"])
        post_go_weather(ctx["mission"]["id"], pilot)
        advance_mission_through(
            ctx["mission"]["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT"]
        )
        resp = api_client.finalize_invoice(invoice["id"], {"actual_loaded_miles": 41}, BILL)
        validate_error(resp, ApiErrorId.ERR_MISSION_NOT_COMPLETED)
        after = get_success_data(api_client.get_invoice(invoice["id"], BILL))
        assert after["claim_status"] == "DRAFT"


class TestCompleteWithPendingGroundLegRejected:
    def test_completion_blocked_while_leg_enroute_then_opens(self):
        """PRD §3.5: "Moving from `AT_DESTINATION` to `COMPLETED` requires every
        non-`CANCELLED` ground leg on the mission to be `COMPLETED`; a straggler
        rejects the completion with `ERR_GROUND_LEGS_PENDING`."

        Design: Corner/errors/complete_with_pending_ground_leg_rejected
        """
        ctx = setup_planning_mission()
        pilot = ctx["roster"]["PILOT"]
        mission = ctx["mission"]
        leg = create_ground_leg(mission["id"], leg_type="DESTINATION")
        advance_ground_leg(leg["id"], "ENROUTE")
        post_go_weather(mission["id"], pilot)
        advance_mission_through(
            mission["id"], pilot, ["LAUNCHED", "AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION"]
        )
        resp = api_client.advance_mission(
            mission["id"], {"to_state": "COMPLETED"}, make_flight_crew_headers(pilot["id"])
        )
        validate_error(resp, ApiErrorId.ERR_GROUND_LEGS_PENDING)
        advance_ground_leg(leg["id"], "AT_BEDSIDE")
        advance_ground_leg(leg["id"], "COMPLETED")
        completed = advance_mission(
            mission["id"], "COMPLETED", headers=make_flight_crew_headers(pilot["id"])
        )
        assert completed["status"] == "COMPLETED", "Gate opens once the straggler leg completes"


class TestRepatVerifyExpiredPassportRejected:
    def test_expired_passport_fails_validity_not_completeness(self):
        """PRD §3.7: "Validity requires every `PASSPORT` and `VISA` entry to
        have an `expires_iso` strictly later than the logical now, and the
        `FIT_TO_FLY` entry to have been issued no more than 72 hours before the
        logical now — exactly 72 hours old still passes; any breach is
        `ERR_DOC_EXPIRED`."

        Design: Corner/errors/repat_verify_expired_passport_rejected
        """
        # All four types present; PASSPORT expired 2026-07-01 (now 2026-08-01).
        docs = full_document_set(
            fit_to_fly_issued="2026-07-31T00:00:00Z",
            passport_expires="2026-07-01T00:00:00Z",
        )
        ctx, case = setup_repatriation_mission(with_documents=docs)
        resp = api_client.verify_repatriation_case(case["id"], MED)
        validate_error(resp, ApiErrorId.ERR_DOC_EXPIRED)
        after = get_success_data(api_client.get_repatriation_case(case["id"], DISP))
        assert after["status"] == "COLLECTING"


def _list_assignments_for(mission_id, crew_member_id):
    from test_helpers import validate_paginated
    return validate_paginated(
        api_client.list_crew_assignments(
            DISP, params={"mission_id": mission_id, "crew_member_id": crew_member_id}
        )
    )
