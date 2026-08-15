"""Applicant registration, application intake gates, and fee handling."""
from test_helpers import (
    ANON,
    EVALUATOR,
    INTAKE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_applicant,
    create_applicant_payload,
    create_application,
    create_application_payload,
    issue_action,
    make_applicant_headers,
    pay_application_fee,
    propose_action,
    register_applicant,
    setup_adjudicated_case,
    setup_licensed_applicant,
    setup_paid_application_in_intake,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_application,
)


class TestApplicantRegistration:

    def test_applicant_creation_lands_registered(self):
        """PRD section 3.1: "The new applicant record starts in `REGISTERED`
        status; its lifecycle thereafter runs `REGISTERED` →
        `APPLICATION_IN_PROGRESS` → `LICENSED`, with `BARRED` as the
        disciplinary terminal."
        PRD section 2.4: "Every resource carries an `id` minted by the server
        as a UUID with no type prefix, plus a `created_at` timestamp in
        ISO 8601 UTC format with three fractional digits."

        Design: Corner/entities/applicant_creation_defaults
        """
        resp = api_client.create_applicant(
            create_applicant_payload(
                full_name="Tia Ti", email="tia@x.com",
                date_of_birth="1997-01-01T00:00:00Z", ssn_last4="4321",
                moral_character_attestation=True),
            ANON,
        )
        data = validate_success(resp, expected_status=201)
        assert_applicant(data)
        assert data["status"] == "REGISTERED", (
            f"new applicant must start in REGISTERED, got {data['status']}")

    def test_applicant_missing_email_rejected(self):
        """PRD section 3.1: "Registration captures `full_name`, `email`,
        `date_of_birth`, `ssn_last4`, and `moral_character_attestation`."
        PRD section 2.5: "Required fields must be present, enum members must
        be valid, and numeric ranges must hold — `ssn_last4` is exactly four
        digits, `raw_score` is an integer from 0 to 100 inclusive, CE credit
        `hours` are greater than zero, and `suspension_end` is no earlier than
        `suspension_start` — else `ERR_VALIDATION`."

        Design: Corner/entities/applicant_missing_required_email_returns_invalid_request
        """
        payload = {
            "full_name": "Uma Um",
            "date_of_birth": "1997-02-02T00:00:00Z",
            "ssn_last4": "4322",
            "moral_character_attestation": True,
        }
        resp = api_client.create_applicant(payload, ANON)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestApplicationFeeComputation:

    def test_fee_recomputed_per_transcript_and_client_value_ignored(self):
        """PRD section 3.1: "The base fee depends on pathway: 10,000 cents for
        `TRADITIONAL`, 15,000 cents for `ALTERNATIVE`, 20,000 cents for
        `RECIPROCITY`, and 15,000 cents for `REINSTATEMENT`."
        PRD section 3.1: "To the base the system adds a transcript evaluation
        fee of 2,500 cents for each transcript currently attached to the
        application, counting every transcript regardless of its verification
        status; the sum of base and evaluation fees is the subtotal."
        PRD section 3.1: "When `expedite_requested` is true, a surcharge of 20
        percent of the subtotal, rounded half-up to a whole cent, is added on
        top; otherwise the surcharge is zero."
        PRD section 3.1: "This figure is recomputed at application creation,
        again every time a transcript is added, and again whenever the
        expedite flag changes."

        Design: Corner/entities/application_fee_computed_input_ignored
        """
        applicant = register_applicant(full_name="Val Va", email="val@x.com")
        app = create_application(
            applicant["id"], pathway="RECIPROCITY", subject_area="MATHEMATICS",
            grade_band="G7_12", expedite_requested=True, fee_cents=999)
        # 20000 base + 0 transcripts = 20000; expedite surcharge 4000.
        assert app["fee_cents"] == 24_000, (
            f"client-supplied fee_cents must be ignored; expected 24000, "
            f"got {app['fee_cents']}")
        for inst, deg, hours, code, grade in (
                ("A U", "BACHELORS", 120, "M1", "A"),
                ("B U", "MASTERS", 30, "M2", "B")):
            resp = api_client.create_transcript(
                app["id"],
                {"institution_name": inst, "degree_level": deg,
                 "total_semester_hours": hours,
                 "courses": [{"course_code": code, "credit_hours": 3,
                              "letter_grade": grade}]},
                make_applicant_headers(applicant["id"]))
            validate_success(resp, expected_status=201)
        data = validate_success(api_client.get_application(app["id"], EVALUATOR))
        # 20000 + 2 * 2500 = 25000 subtotal; 20% surcharge 5000; total 30000.
        assert data["fee_cents"] == 30_000, (
            f"expected fee_cents 30000 after two transcripts, got "
            f"{data['fee_cents']}")


class TestApplicationRead:

    def test_get_unknown_application_not_found(self):
        """PRD section 2.9: "Path identifiers — `applicantId`, `programId`,
        `applicationId`, `id`, `transcriptId`, `testScoreId`, `checkId`,
        `evaluationId`, `planId`, `licenseId`, `endorsementId`, `permitId`,
        `creditId`, `auditId`, `caseId`, and `actionId` — are validated
        strictly left to right: each segment must exist before the next is
        examined, and the first missing identifier short-circuits the request
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_application_returns_not_found
        """
        resp = api_client.get_application(NON_EXISTENT_UUID, INTAKE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_transcript_invalid_degree_level_rejected(self):
        """PRD section 3.3: "Each transcript upload carries
        `institution_name`, a `degree_level` of `BACHELORS`, `MASTERS`, or
        `DOCTORATE`, `total_semester_hours`, and a `courses` array whose
        entries each name a `course_code`, `credit_hours`, and a
        `letter_grade` drawn from `A`, `A_MINUS`, `B`, `C`, `D`, or `F`."
        PRD section 2.5: "Required fields must be present, enum members must
        be valid, and numeric ranges must hold"

        Design: Corner/entities/transcript_invalid_enum_rejected
        """
        applicant = register_applicant(full_name="Wes We", email="wes@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY")
        resp = api_client.create_transcript(
            app["id"],
            {"institution_name": "A U", "degree_level": "PHD",
             "total_semester_hours": 120, "courses": []},
            make_applicant_headers(applicant["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestListEndpoints:

    def test_applicants_list_pagination_boundaries(self):
        """PRD section 2.3: "Every list endpoint accepts two query parameters,
        `limit` and `offset`. The `limit` parameter defaults to 10, must be at
        least 1, and may not exceed 100; the `offset` parameter defaults to 0."
        PRD section 2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more` so clients can page
        deterministically."

        Design: Corner/entities/applicants_list_pagination_boundaries
        """
        for i in (1, 2, 3):
            register_applicant(full_name=f"P{i}", email=f"p{i}@x.com",
                               ssn_last4=f"000{i}")
        page1, meta1 = validate_paginated(
            api_client.list_applicants(INTAKE, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2 and meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api_client.list_applicants(INTAKE, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1 and meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_applications_list_filter_by_applicant(self):
        """PRD section 2.3: "The application list accepts `applicant_id`,
        `program_id`, and `status`."
        PRD section 2.3: "All filters combine with pagination rather than
        replacing it."

        Design: Corner/endpoints/applications_list_filter_by_applicant
        """
        ap1 = register_applicant(full_name="Dee Da", email="deed@x.com")
        app1 = create_application(ap1["id"], pathway="RECIPROCITY",
                                  subject_area="MATHEMATICS")
        ap2 = register_applicant(full_name="Earl Ea", email="earl@x.com")
        create_application(ap2["id"], pathway="RECIPROCITY",
                           subject_area="SCIENCE", grade_band="G5_8")
        data, meta = validate_paginated(api_client.list_applications(
            EVALUATOR, params={"applicant_id": ap1["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1 and data[0]["id"] == app1["id"]


class TestFeePayment:

    def test_fee_payment_then_double_pay_rejected(self):
        """PRD section 3.1: "Paying moves `fee_status` from `UNPAID` to `PAID`
        and increments the application's `version` by 1; attempting to pay an
        application whose `fee_status` is already `PAID` is rejected with
        `ERR_FEE_ALREADY_PAID`."

        Design: Corner/endpoints/fee_payment_success_then_double_pay_rejected
        """
        applicant = register_applicant(full_name="Fox Fo", email="fox@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="ELEMENTARY", grade_band="PK_6")
        assert app["fee_status"] == "UNPAID"
        paid = validate_success(api_client.pay_application_fee(
            app["id"], {"payment_token": "tok_1"},
            make_applicant_headers(applicant["id"])))
        assert paid["fee_status"] == "PAID"
        assert paid["version"] == app["version"] + 1, (
            "payment must increment the application version by exactly 1")
        resp = api_client.pay_application_fee(
            app["id"], {"payment_token": "tok_2"},
            make_applicant_headers(applicant["id"]))
        validate_error(resp, ApiErrorId.ERR_FEE_ALREADY_PAID)

    def test_fee_payment_visible_immediately(self):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."
        PRD section 3.1: "Paying moves `fee_status` from `UNPAID` to `PAID`
        and increments the application's `version` by 1"

        Design: Corner/consistency_model/immediate_visibility_after_state_change
        """
        applicant = register_applicant(full_name="Ott Ot", email="ott@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="ELEMENTARY", grade_band="PK_6")
        assert app["status"] == "SUBMITTED"
        paid = validate_success(api_client.pay_application_fee(
            app["id"], {"payment_token": "tok_1"},
            make_applicant_headers(applicant["id"])))
        assert paid["fee_status"] == "PAID"
        fetched = validate_success(api_client.get_application(app["id"], INTAKE))
        assert fetched["fee_status"] == "PAID", (
            "a subsequent read must observe the paid fee with no delay")


class TestIntakeGates:

    def test_fee_unpaid_blocks_intake(self):
        """PRD section 3.1: "This first gate has three preconditions:
        `fee_status` must be `PAID` (else `ERR_FEE_UNPAID`, HTTP 402), the
        applicant's `moral_character_attestation` must be true (else
        `ERR_MORAL_ATTESTATION_REQUIRED`), and the applicant must not be
        `BARRED` (else `ERR_APPLICANT_BARRED`)."

        Design: Corner/validations/fee_unpaid_blocks_intake
        """
        applicant = register_applicant(full_name="Wyn Wy", email="wyn@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="ELEMENTARY", grade_band="PK_6")
        resp = api_client.transition_application(
            app["id"], {"to_status": "INTAKE_REVIEW"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_FEE_UNPAID)
        assert resp.status_code == 402

    def test_moral_attestation_false_blocks_intake(self):
        """PRD section 3.1: "This first gate has three preconditions:
        `fee_status` must be `PAID` (else `ERR_FEE_UNPAID`, HTTP 402), the
        applicant's `moral_character_attestation` must be true (else
        `ERR_MORAL_ATTESTATION_REQUIRED`), and the applicant must not be
        `BARRED` (else `ERR_APPLICANT_BARRED`)."

        Design: Corner/validations/moral_attestation_false_blocks_intake
        """
        applicant = register_applicant(
            full_name="Moe Mo", email="moe@x.com",
            moral_character_attestation=False)
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="ELEMENTARY", grade_band="PK_6")
        pay_application_fee(app["id"], applicant["id"])
        resp = api_client.transition_application(
            app["id"], {"to_status": "INTAKE_REVIEW"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_MORAL_ATTESTATION_REQUIRED)
        fetched = validate_success(api_client.get_application(app["id"], INTAKE))
        assert fetched["status"] == "SUBMITTED"

    def test_duplicate_open_application_same_subject_rejected(self):
        """PRD section 3.1: "an applicant may hold at most one non-terminal
        application per subject area: a second application for the same
        applicant and `subject_area` while the first is still in flight is
        rejected with `ERR_DUPLICATE_OPEN_APPLICATION`."

        Design: Corner/validations/duplicate_open_application_same_subject_rejected
        """
        applicant = register_applicant(full_name="Nia Ni", email="nia@x.com")
        create_application(applicant["id"], pathway="RECIPROCITY",
                           subject_area="MATHEMATICS", grade_band="G7_12")
        resp = api_client.create_application(
            create_application_payload(
                applicant["id"], pathway="RECIPROCITY",
                subject_area="MATHEMATICS", grade_band="PK_6"),
            make_applicant_headers(applicant["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_APPLICATION)

    def test_barred_applicant_cannot_apply(self):
        """PRD section 3.1: "An applicant who has been `BARRED` cannot open an
        application at all (`ERR_APPLICANT_BARRED`)"
        PRD section 3.9: "the applicant becomes `BARRED`"

        Design: Corner/validations/barred_applicant_cannot_apply
        """
        ctx = setup_licensed_applicant(
            full_name="Lou Lo", email="lou@x.com")
        applicant, license_ = ctx["applicant"], ctx["license"]
        case = setup_adjudicated_case(
            license_["id"], allegation_category="CRIMINAL_CONDUCT",
            investigator_id="inv-4", adjudicator_id="legal-4")
        action = propose_action(case["id"], sanction_type="REVOCATION")
        issue_action(action["id"])
        fetched = validate_success(api_client.get_applicant(applicant["id"], EVALUATOR))
        assert fetched["status"] == "BARRED"
        resp = api_client.create_application(
            create_application_payload(
                applicant["id"], pathway="ALTERNATIVE",
                subject_area="SCIENCE", grade_band="G5_8"),
            make_applicant_headers(applicant["id"]))
        validate_error(resp, ApiErrorId.ERR_APPLICANT_BARRED)


class TestWithdrawnApplicationLockdown:

    def test_withdrawn_application_rejects_further_advance(self):
        """PRD section 3.1: "Withdrawing from any of these states refunds the
        fee by setting `fee_status` to `REFUNDED` when it was `PAID` and
        increments `version` by 1."
        PRD section 2.5: "The target entity must be in a state from which the
        requested transition exists, and terminal states reject every
        transition, else `ERR_INVALID_STATE`."
        PRD section 2.5: "Incoming requests are validated against an ordered
        pipeline; a failure at an earlier stage masks all later checks, and
        the error returned is always the first one that fires."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_withdrawn_application
        """
        applicant = register_applicant(full_name="Jay Ja", email="jay@x.com")
        app = setup_paid_application_in_intake(
            applicant, pathway="ALTERNATIVE", subject_area="ELEMENTARY",
            grade_band="PK_6")
        withdrawn = withdraw_application(app["id"], applicant["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["fee_status"] == "REFUNDED"
        resp = api_client.transition_application(
            app["id"], {"to_status": "INTAKE_REVIEW"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api_client.get_application(app["id"], INTAKE))
        assert fetched["fee_status"] == "REFUNDED"

    def test_withdrawal_from_submitted_unpaid_keeps_fee_unpaid(self):
        """PRD section 3.1: "Withdrawing from any of these states refunds the
        fee by setting `fee_status` to `REFUNDED` when it was `PAID` and
        increments `version` by 1."
        PRD section 2.5: "The target entity must be in a state from which the
        requested transition exists, and terminal states reject every
        transition, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_withdrawn_application
        """
        applicant = register_applicant(full_name="Jay Jo", email="jayjo@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="ELEMENTARY", grade_band="PK_6")
        withdrawn = withdraw_application(app["id"], applicant["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["fee_status"] == "UNPAID", (
            "refund applies only when the fee was PAID")
        resp = api_client.transition_application(
            app["id"], {"to_status": "INTAKE_REVIEW"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
