"""Validation gates on enforcement cases and on recovery-fund claims.

The first group covers investigation origin, the appeal window on both sides of
its deadline, the classification match on a citation, exact penalty remittance
and the statutory penalty ceiling a hearing officer cannot exceed. The second
group covers the claimability of the complaint behind a claim, the judgment-field
pairing, the pleaded-loss ceiling and the judgment ripening period. Every test
drives the API from an empty database.
"""

from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    assert_fields,
    factories as F,
    fixtures as X,
    make_consumer_headers,
    make_hearing_officer_headers,
    make_investigator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEnforcementValidationGates:
    """Origin, appeal-window, classification, payment and penalty gates."""

    def test_sting_investigation_without_a_subject_name_is_refused(self, api):
        """A proactive case naming neither a licence nor a business is refused.

        PRD: "An `origin` of `COMPLAINT` without a `complaint_id`, an `origin` of
        `STING` with one, or a nameless unlicensed target all draw
        `ERR_INVESTIGATION_ORIGIN_MISMATCH`."

        Design: Corner/validations/corner_sting_investigation_without_a_subject_name_is_rejected
        """
        X.set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_investigation(
            {"origin": "STING"}, make_investigator_headers("inv-61")
        )

        validate_error(response, "ERR_INVESTIGATION_ORIGIN_MISMATCH")
        _, meta = validate_paginated(
            api.list_investigations(LICENSING_ANALYST_HEADERS, {"origin": "STING"})
        )
        assert meta["total_count"] == 0

    def test_finalizing_inside_the_appeal_window_is_refused(self, api):
        """Defaulting a citation on its deadline date is still too early.

        PRD: "This requires the clock date to be strictly past the
        `appeal_deadline`; attempting it while the window is still open —
        including on the deadline date itself — draws `ERR_APPEAL_WINDOW_OPEN`."

        Design: Corner/validations/corner_finalizing_inside_the_appeal_window_is_rejected
        """
        X.set_clock(api, "2026-09-01T00:00:00Z")
        classification = X.create_c10_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Window Open Electric LLC",
            contact_email="wopen@x.test",
            full_name="Willa Window",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        investigation = X.open_investigation(
            api,
            subject_license_id=ctx.license_id,
            origin="STING",
            investigator_user_id="inv-70",
        )
        X.substantiate(
            api,
            investigation["id"],
            severity="MINOR",
            evidence_summary="Unpermitted service change observed on site.",
            investigator_user_id="inv-70",
        )
        citation = X.issue_citation(
            api,
            investigation["id"],
            ctx.classification_id,
            investigator_user_id="inv-70",
            violation_code="B-7109",
            correction_due_date="2026-10-15",
        )

        response = api.finalize_citation(citation["id"], LICENSING_ANALYST_HEADERS)

        validate_error(response, "ERR_APPEAL_WINDOW_OPEN")
        assert_fields(
            validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
            {
                "status": "ISSUED",
                "issued_on": "2026-09-01",
                "appeal_deadline": "2026-09-16",
            },
        )

    def test_appealing_one_day_after_the_deadline_is_refused(self, api):
        """An appeal lodged the day after the deadline is out of time.

        PRD: "The appeal must be filed while the clock date is on or before the
        `appeal_deadline`; filing later draws `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/validations/corner_appealing_one_day_after_the_deadline_is_rejected
        """
        X.set_clock(api, "2026-09-01T00:00:00Z")
        classification = X.create_c10_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Late Appeal Electric LLC",
            contact_email="lateappeal@x.test",
            full_name="Lane Lateman",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        investigation = X.open_investigation(
            api,
            subject_license_id=ctx.license_id,
            origin="STING",
            investigator_user_id="inv-71",
        )
        X.substantiate(
            api,
            investigation["id"],
            severity="MINOR",
            evidence_summary="Advertising without the licence number.",
            investigator_user_id="inv-71",
        )
        citation = X.issue_citation(
            api,
            investigation["id"],
            ctx.classification_id,
            investigator_user_id="inv-71",
            violation_code="B-7027",
            correction_due_date="2026-10-15",
        )
        X.set_clock(api, "2026-09-17T09:00:00Z")

        response = api.appeal_citation(
            citation["id"], F.appeal_payload(), ctx.licensee_headers
        )

        validate_error(response, "ERR_APPEAL_WINDOW_CLOSED")
        assert_fields(
            validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
            {"status": "ISSUED", "appeal_deadline": "2026-09-16"},
        )

    def test_citation_classification_must_match_the_subject_license(self, api):
        """A citation cannot be written under another trade's classification.

        PRD: "And when the case names a licensed subject, the supplied
        `classification_id` must equal that licence's own `classification_id`, or
        the issuance draws `ERR_CLASSIFICATION_MISMATCH` — the board cannot cite
        an electrician under a plumbing classification to reach a harsher hazard
        tier."

        Design: Corner/validations/corner_citation_classification_must_match_the_subject_license
        """
        X.set_clock(api, "2026-08-01T00:00:00Z")
        electrical = X.create_c10_classification(api)
        mechanical = X.create_c20_classification(api)
        ctx = X.mint_active_license(
            api,
            mechanical,
            legal_name="Wrong Class Mechanical LLC",
            contact_email="wrongclass@x.test",
            full_name="Wanda Wrongclass",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        investigation = X.open_investigation(
            api,
            subject_license_id=ctx.license_id,
            origin="STING",
            investigator_user_id="inv-80",
        )
        X.substantiate(
            api,
            investigation["id"],
            severity="SERIOUS",
            evidence_summary="Refrigerant handling without certification.",
            investigator_user_id="inv-80",
        )

        response = api.create_citation(
            F.citation_payload(
                investigation["id"],
                electrical["id"],
                violation_code="B-7109",
                correction_due_date="2026-09-15",
            ),
            make_investigator_headers("inv-80"),
        )

        validate_error(response, "ERR_CLASSIFICATION_MISMATCH")
        _, meta = validate_paginated(
            api.list_citations(
                LICENSING_ANALYST_HEADERS, {"investigation_id": investigation["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert_fields(
            validate_success(
                api.get_investigation(investigation["id"], LICENSING_ANALYST_HEADERS)
            ),
            {"status": "SUBSTANTIATED"},
        )
        accepted = validate_success(
            api.create_citation(
                F.citation_payload(
                    investigation["id"],
                    mechanical["id"],
                    violation_code="B-7109",
                    correction_due_date="2026-09-15",
                ),
                make_investigator_headers("inv-80"),
            ),
            201,
        )
        assert_fields(accepted, {"status": "ISSUED"})

    def test_partial_penalty_payment_is_refused(self, api):
        """Remitting less than the balance owed is refused, and changes nothing.

        PRD: "The payment must be exact: `penalty_payment_cents` must equal
        `civil_penalty_cents` less `penalty_paid_cents` to the cent, and both
        partial payment and overpayment are refused with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/validations/corner_partial_penalty_payment_is_rejected
        """
        X.set_clock(api, "2026-09-01T00:00:00Z")
        classification = X.create_c10_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Partial Pay Electric LLC",
            contact_email="partialpay@x.test",
            full_name="Pam Partial",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        investigation = X.open_investigation(
            api,
            subject_license_id=ctx.license_id,
            origin="STING",
            investigator_user_id="inv-90",
        )
        X.substantiate(
            api,
            investigation["id"],
            severity="MINOR",
            evidence_summary="Permit closed without a final inspection.",
            investigator_user_id="inv-90",
        )
        citation = X.issue_citation(
            api,
            investigation["id"],
            ctx.classification_id,
            investigator_user_id="inv-90",
            violation_code="B-7110",
            correction_due_date="2026-10-15",
        )
        X.set_clock(api, "2026-09-17T09:00:00Z")
        finalized = validate_success(
            api.finalize_citation(citation["id"], LICENSING_ANALYST_HEADERS)
        )
        penalty_owed = finalized["civil_penalty_cents"]

        response = api.comply_with_citation(
            citation["id"], F.comply_payload(10000, "2026-09-16"), ctx.licensee_headers
        )

        validate_error(response, "ERR_PAYMENT_AMOUNT_MISMATCH")
        assert_fields(
            validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
            {
                "status": "FINAL",
                "penalty_paid_cents": 0,
                "correction_completed_on": None,
            },
        )
        satisfied = validate_success(
            api.comply_with_citation(
                citation["id"],
                F.comply_payload(penalty_owed, "2026-09-16"),
                ctx.licensee_headers,
            )
        )
        assert_fields(
            satisfied, {"status": "SATISFIED", "penalty_paid_cents": penalty_owed}
        )

    def test_modified_penalty_above_the_statutory_maximum_is_refused(self, api):
        """A hearing officer cannot substitute a penalty past the statutory cap.

        PRD: "The gates fire in order: the hearing must be `SCHEDULED` (otherwise
        `ERR_HEARING_STATE_INVALID`) and its citation must be
        `HEARING_SCHEDULED`; the actor's `X-User-ID` must equal
        `presiding_officer_user_id` (otherwise `ERR_NOT_PRESIDING_OFFICER`); the
        clock timestamp must be at or after `scheduled_start_utc`, since a
        hearing cannot be decided before it convenes (otherwise
        `ERR_HEARING_NOT_CONVENED`); and the penalty-substitution rules must hold
        — `modified_penalty_cents` must be supplied for a `MODIFY` decision, must
        be omitted for `AFFIRM` and `VACATE`, and must never exceed the statutory
        ceiling of 1,500,000 cents, with any violation reporting
        `ERR_PENALTY_EXCEEDS_STATUTORY_MAX`."

        Design: Corner/validations/corner_modified_penalty_above_the_statutory_maximum_is_rejected
        """
        X.set_clock(api, "2026-09-01T00:00:00Z")
        classification = X.create_c10_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Ceiling Electric LLC",
            contact_email="ceiling@x.test",
            full_name="Cara Ceiling",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        investigation = X.open_investigation(
            api,
            subject_license_id=ctx.license_id,
            origin="STING",
            investigator_user_id="inv-91",
        )
        X.substantiate(
            api,
            investigation["id"],
            severity="SERIOUS",
            evidence_summary="Live service energized without inspection.",
            investigator_user_id="inv-91",
        )
        citation = X.issue_citation(
            api,
            investigation["id"],
            ctx.classification_id,
            investigator_user_id="inv-91",
            violation_code="B-7113",
            correction_due_date="2026-10-15",
        )
        hearing = X.appealed_citation_with_hearing(
            api,
            citation["id"],
            ctx.licensee_id,
            "2026-09-20T10:00:00Z",
            "2026-09-20T12:00:00Z",
            presiding_officer_user_id="ho-9",
        )
        X.set_clock(api, "2026-09-20T10:30:00Z")

        response = api.decide_hearing(
            hearing["id"],
            F.hearing_decision_payload(
                "MODIFY",
                findings_summary="Violation proven; a higher penalty is substituted.",
                modified_penalty_cents=1600000,
            ),
            make_hearing_officer_headers("ho-9"),
        )

        validate_error(response, "ERR_PENALTY_EXCEEDS_STATUTORY_MAX")
        assert_fields(
            validate_success(api.get_hearing(hearing["id"], LICENSING_ANALYST_HEADERS)),
            {"status": "SCHEDULED", "decision": None},
        )
        assert_fields(
            validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
            {"status": "HEARING_SCHEDULED", "penalty_variant": "INITIAL_ASSESSMENT"},
        )


class TestRecoveryFundClaimGates:
    """Claimability, judgment-field coupling, pleaded-loss ceiling and ripening."""

    def test_claim_against_an_unlicensed_subject_is_refused(self, api):
        """The fund cannot be reached over an unlicensed operator.

        PRD: "First, **the fund does not reach unlicensed operators**: a claim may
        only be filed on a complaint whose `license_id` is non-null, and a claim
        on an unlicensed-practice complaint is refused with
        `ERR_UNLICENSED_SUBJECT_NOT_CLAIMABLE`."

        Design: Corner/validations/corner_claim_against_an_unlicensed_subject_is_rejected
        """
        X.set_clock(api, "2026-08-01T00:00:00Z")
        fund = X.open_fund_account(
            api,
            fiscal_year=2027,
            initial_balance_cents=5000000,
            per_claim_cap_cents=1500000,
            per_license_aggregate_cap_cents=3000000,
        )
        consumer = X.register_consumer(
            api, full_name="Una Unlicensed", contact_email="una@home.test"
        )
        complaint = X.file_unlicensed_complaint(
            api,
            consumer["id"],
            "Cash Only Construction",
            alleged_loss_cents=900000,
            contract_date="2026-07-01",
            work_completed_on="2026-07-20",
            description="Took the deposit and abandoned the job.",
        )
        X.screen_accepted(api, complaint["id"])

        response = api.create_claim(
            F.judgment_claim_payload(
                fund["id"], complaint["id"], 900000, 900000, "CV-2026-771", "2026-07-25"
            ),
            make_consumer_headers(consumer["id"]),
        )

        validate_error(response, "ERR_UNLICENSED_SUBJECT_NOT_CLAIMABLE")
        _, meta = validate_paginated(
            api.list_claims(FUND_ADJUDICATOR_HEADERS, {"complaint_id": complaint["id"]})
        )
        assert meta["total_count"] == 0
        assert_fields(
            X.read_fund_account(api, fund["id"]), {"balance_cents": 5000000}
        )

    def test_judgment_fields_on_a_citation_claim_are_refused(self, api):
        """Judgment particulars have no place on a citation-basis claim.

        PRD: "Supplying an incomplete judgment set on a judgment claim, or
        supplying any judgment field on a citation claim, draws
        `ERR_JUDGMENT_FIELDS_MISMATCH`."

        Design: Corner/validations/corner_judgment_fields_supplied_on_a_final_citation_claim_are_rejected
        """
        X.set_clock(api, "2026-08-01T00:00:00Z")
        fund = X.open_fund_account(
            api,
            fiscal_year=2027,
            initial_balance_cents=5000000,
            per_claim_cap_cents=1500000,
            per_license_aggregate_cap_cents=3000000,
        )
        classification = X.create_c20_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Docket Mixup Mechanical LLC",
            contact_email="docket@x.test",
            full_name="Dana Docket",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        consumer = X.register_consumer(
            api, full_name="Dot Docketless", contact_email="dot@home.test"
        )
        complaint = X.file_complaint(
            api,
            consumer["id"],
            ctx.license_id,
            alleged_loss_cents=900000,
            contract_date="2026-08-05",
            work_completed_on="2026-08-20",
            description="Condenser paid for and never installed.",
        )
        X.screen_accepted(api, complaint["id"])

        response = api.create_claim(
            F.claim_payload(
                fund["id"],
                complaint["id"],
                900000,
                judgment_amount_cents=900000,
                judgment_docket_number="CV-2026-802",
                judgment_entered_on="2026-08-25",
            ),
            make_consumer_headers(consumer["id"]),
        )

        validate_error(response, "ERR_JUDGMENT_FIELDS_MISMATCH")
        _, meta = validate_paginated(
            api.list_claims(FUND_ADJUDICATOR_HEADERS, {"complaint_id": complaint["id"]})
        )
        assert meta["total_count"] == 0
        assert_fields(
            validate_success(
                api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)
            ),
            {"status": "INVESTIGATION"},
        )

    def test_claim_above_the_pleaded_loss_is_refused(self, api):
        """The fund cannot be asked for more than the loss the consumer pleaded.

        PRD: "Fourth, **the pleaded-loss ceiling**: `claimed_amount_cents` must be
        at least one cent and no greater than the complaint's
        `alleged_loss_cents`, because the fund cannot be asked for more than the
        loss the consumer pleaded; a violation draws
        `ERR_CLAIM_EXCEEDS_ALLEGED_LOSS`."

        Design: Corner/validations/corner_claim_above_the_pleaded_loss_is_rejected
        """
        X.set_clock(api, "2026-08-01T00:00:00Z")
        fund = X.open_fund_account(
            api,
            fiscal_year=2027,
            initial_balance_cents=5000000,
            per_claim_cap_cents=1500000,
            per_license_aggregate_cap_cents=3000000,
        )
        classification = X.create_c20_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Overclaim Mechanical LLC",
            contact_email="overclaim@x.test",
            full_name="Ollie Overclaim",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        consumer = X.register_consumer(
            api, full_name="Ora Overpleader", contact_email="ora@home.test"
        )
        complaint = X.file_complaint(
            api,
            consumer["id"],
            ctx.license_id,
            alleged_loss_cents=400000,
            contract_date="2026-08-05",
            work_completed_on="2026-08-20",
            description="Ductwork left unsealed throughout the house.",
        )
        X.screen_accepted(api, complaint["id"])

        response = api.create_claim(
            F.judgment_claim_payload(
                fund["id"], complaint["id"], 600000, 600000, "CV-2026-811", "2026-08-25"
            ),
            make_consumer_headers(consumer["id"]),
        )

        validate_error(response, "ERR_CLAIM_EXCEEDS_ALLEGED_LOSS")
        _, meta = validate_paginated(
            api.list_claims(FUND_ADJUDICATOR_HEADERS, {"complaint_id": complaint["id"]})
        )
        assert meta["total_count"] == 0
        accepted = validate_success(
            api.create_claim(
                F.judgment_claim_payload(
                    fund["id"],
                    complaint["id"],
                    400000,
                    600000,
                    "CV-2026-811",
                    "2026-08-25",
                ),
                make_consumer_headers(consumer["id"]),
            ),
            201,
        )
        assert_fields(accepted, {"status": "FILED"})

    def test_approving_an_unripe_judgment_claim_is_refused_one_day_early(self, api):
        """Day eighty-nine after judgment is one day short of reachable.

        PRD: "Then, for a `COURT_JUDGMENT` claim, the **ripening period**: the
        clock date must be on or after `judgment_entered_on` advanced by ninety
        days, because the judgment must have gone ninety days unsatisfied before
        the fund is reachable. Day ninety itself is ripe; day eighty-nine is not,
        and draws `ERR_JUDGMENT_NOT_RIPE`."

        Design: Corner/validations/corner_approving_an_unripe_judgment_claim_is_rejected_one_day_early
        """
        X.set_clock(api, "2026-08-01T00:00:00Z")
        fund = X.open_fund_account(
            api,
            fiscal_year=2027,
            initial_balance_cents=5000000,
            per_claim_cap_cents=1500000,
            per_license_aggregate_cap_cents=3000000,
        )
        classification = X.create_c20_classification(api)
        ctx = X.mint_active_license(
            api,
            classification,
            legal_name="Unripe Mechanical LLC",
            contact_email="unripe@x.test",
            full_name="Rip Unready",
            verified_experience_months=60,
            education_credential="NONE",
            declared_net_worth_cents=400000,
        )
        consumer = X.register_consumer(
            api, full_name="Ruth Ripener", contact_email="ruth@home.test"
        )
        complaint = X.file_complaint(
            api,
            consumer["id"],
            ctx.license_id,
            alleged_loss_cents=900000,
            contract_date="2026-08-05",
            work_completed_on="2026-08-20",
            description="Heat pump replacement billed and never delivered.",
        )
        X.screen_accepted(api, complaint["id"])
        claim = X.file_judgment_claim(
            api,
            fund["id"],
            complaint["id"],
            consumer["id"],
            900000,
            900000,
            "CV-2026-900",
            "2026-09-01",
        )
        X.set_clock(api, "2026-11-29T12:00:00Z")

        response = api.adjudicate_claim(
            claim["id"], F.adjudication_payload("APPROVE"), FUND_ADJUDICATOR_HEADERS
        )

        validate_error(response, "ERR_JUDGMENT_NOT_RIPE")
        assert_fields(
            validate_success(api.get_claim(claim["id"], FUND_ADJUDICATOR_HEADERS)),
            {"status": "FILED", "awarded_amount_cents": None, "adjudicated_on": None},
        )
        X.set_clock(api, "2026-11-30T12:00:00Z")
        approved = validate_success(
            api.adjudicate_claim(
                claim["id"], F.adjudication_payload("APPROVE"), FUND_ADJUDICATOR_HEADERS
            )
        )
        assert_fields(
            approved, {"status": "APPROVED", "awarded_amount_cents": 900000}
        )
