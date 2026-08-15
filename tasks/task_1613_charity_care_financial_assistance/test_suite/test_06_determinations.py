"""Determinations: dual-basis tier math, evidence gates, coverage checks,
finalize/reverse guards, segregation of duties, OCC, and notification letter."""
from test_helpers import (
    REVIEWER,
    ApiErrorId,
    assert_decimal_eq,
    assert_discount_determination,
    create_account,
    create_active_policy,
    create_determination,
    create_patient,
    get_application,
    get_determination,
    list_application_notices,
    make_assistance_reviewer_headers,
    make_financial_counselor_headers,
    set_clock,
    setup_final_determination,
    setup_presumptive_application,
    setup_verified_application,
    build_under_review_application,
    upload_and_verify,
    upload_document,
    validate_error,
    validate_success,
    verify_document,
)


class TestBasisDivergence:
    def test_verified_basis_sliding_scale_discount(self, api):
        """PRD §3.8: "Otherwise, if the FPL percentage is at or below
        `partial_discount_max_fpl_pct`, the tier is `TIER_PARTIAL` and the
        discount percentage is the sliding-scale interpolation: the policy's
        `partial_discount_floor_pct` plus the product of (the partial ceiling
        minus the actual FPL percentage) and (100 minus the floor), divided by
        (the partial ceiling minus the full ceiling), the whole rounded half-up
        to 2 decimal places."

        Design: Difficulty/dual_variant_calc/determination_basis_verified_sliding_vs_presumptive_flat
        """
        ctx = setup_verified_application(
            patient_name="Vera Verified", mrn="MRN-VER-1", ssn_last4="3333",
            date_of_birth="1975-05-05", reported_income=3750000,
            accounts=((1000000, 0),), tax_return_amount=3750000,
            members=(("SELF", 50),),
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        assert_discount_determination(det)
        assert det["status"] == "PRELIMINARY"
        # 3750000 * 100 / 1500000 = 250.0000 -> 50 + (300-250)*(100-50)/(300-200)
        assert_decimal_eq(det["fpl_pct_snapshot"], 250.0000, "fpl_pct_snapshot")
        assert det["tier"] == "TIER_PARTIAL"
        assert_decimal_eq(det["discount_pct"], 75.00, "discount_pct")

    def test_presumptive_basis_flat_discount_and_null_snapshot(self, api):
        """PRD §3.8: "On the presumptive path the determination consults only
        the screening outcome: `ELIGIBLE_FULL` yields `TIER_FULL` at a flat
        100.00, `ELIGIBLE_PARTIAL` yields `TIER_PARTIAL` at a flat 50.00, and
        `NOT_ELIGIBLE` yields `INELIGIBLE` — income, assets, and household size
        are not consulted, so identical accounts can receive a different
        discount under the two bases. For the presumptive basis
        `fpl_pct_snapshot` is null."

        Design: Difficulty/dual_variant_calc/determination_basis_verified_sliding_vs_presumptive_flat
        """
        ctx = setup_presumptive_application(
            patient_name="Paul Presumptive", mrn="MRN-PRE-1", ssn_last4="4444",
            date_of_birth="1982-02-02", reported_income=3750000,
            accounts=((1000000, 0),),
            members=(("SELF", 44),),
            screening_scores={
                "income_band_score": 95,
                "payment_history_score": 90,
                "utilization_score": 30,
                "public_benefit_score": 95,
                "housing_stability_score": 20,
            },
        )
        assert ctx["screening"]["outcome"] == "ELIGIBLE_PARTIAL"
        det = create_determination(
            ctx["application"]["id"], "PRESUMPTIVE_SCORE",
            [ctx["accounts"][0]["id"]],
        )
        assert det["tier"] == "TIER_PARTIAL"
        # flat 50.00 — the verified path on the same income would give 75.00
        assert_decimal_eq(det["discount_pct"], 50.00, "discount_pct")
        assert det.get("fpl_pct_snapshot") is None, (
            "presumptive basis freezes no FPL snapshot"
        )


class TestVerifiedEvidenceGate:
    def test_determination_without_any_verified_docs_rejected(self, api):
        """PRD §3.8: "Two basis-specific evidence gates apply: a
        `VERIFIED_APPLICATION` basis requires at least one `VERIFIED` income
        document (`PAY_STUB`, `TAX_RETURN`, or `BENEFIT_LETTER`) and at least
        one `VERIFIED` `IDENTITY` document on the application
        (`ERR_VERIFIED_DOCS_REQUIRED`, HTTP 422); a `PRESUMPTIVE_SCORE` basis
        requires a presumptive screening whose `outcome` is not `NOT_ELIGIBLE`
        (`ERR_PRESCREEN_BELOW_THRESHOLD`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/determination_create_gated_by_verified_documents
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Gate Gina", mrn="MRN-GATE-1", ssn_last4="1414",
            date_of_birth="1983-03-03", reported_income=2000000,
            members=(("SELF", 43),), accounts=((100000, 0),),
        )
        upload_document(
            ctx["application"]["id"], doc_type="TAX_RETURN",
            period_start="2025-01-01", period_end="2025-12-31",
            amount_cents=2000000, household_member_id=ctx["members"][0]["id"],
        )  # SUBMITTED, never verified
        app = get_application(ctx["application"]["id"])
        resp = api.create_determination(
            {
                "application_id": app["id"],
                "basis": "VERIFIED_APPLICATION",
                "covered_account_ids": [ctx["accounts"][0]["id"]],
                "expected_application_version": app["version"],
            },
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_VERIFIED_DOCS_REQUIRED)

    def test_income_verified_without_identity_still_rejected_then_succeeds(self, api):
        """PRD §3.8: "Two basis-specific evidence gates apply: a
        `VERIFIED_APPLICATION` basis requires at least one `VERIFIED` income
        document (`PAY_STUB`, `TAX_RETURN`, or `BENEFIT_LETTER`) and at least
        one `VERIFIED` `IDENTITY` document on the application
        (`ERR_VERIFIED_DOCS_REQUIRED`, HTTP 422); a `PRESUMPTIVE_SCORE` basis
        requires a presumptive screening whose `outcome` is not `NOT_ELIGIBLE`
        (`ERR_PRESCREEN_BELOW_THRESHOLD`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/determination_create_gated_by_verified_documents
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Gate Gina", mrn="MRN-GATE-1", ssn_last4="1414",
            date_of_birth="1983-03-03", reported_income=2000000,
            members=(("SELF", 43),), accounts=((100000, 0),),
        )
        app_id = ctx["application"]["id"]
        member_id = ctx["members"][0]["id"]
        account_id = ctx["accounts"][0]["id"]
        upload_and_verify(
            app_id, member_id, doc_type="TAX_RETURN", amount_cents=2000000
        )
        app = get_application(app_id)
        resp = api.create_determination(
            {
                "application_id": app_id,
                "basis": "VERIFIED_APPLICATION",
                "covered_account_ids": [account_id],
                "expected_application_version": app["version"],
            },
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_VERIFIED_DOCS_REQUIRED)
        upload_and_verify(
            app_id, member_id, doc_type="IDENTITY", amount_cents=0,
            period_start="2026-01-01", period_end="2026-01-01",
        )
        det = create_determination(app_id, "VERIFIED_APPLICATION", [account_id])
        assert det["status"] == "PRELIMINARY"
        # income 2000000 = 133.3333% <= 200 full ceiling
        assert det["tier"] == "TIER_FULL"


class TestCoverageAndLifecycleGuards:
    def test_covered_account_of_other_patient_rejected(self, api):
        """PRD §3.8: "The application must be in `UNDER_REVIEW`
        (`ERR_APPLICATION_NOT_UNDER_REVIEW`), and every entry of
        `covered_account_ids` must belong to the application's patient
        (`ERR_ACCOUNT_PATIENT_MISMATCH`, HTTP 422)."

        Design: Corner/validations/determination_account_patient_mismatch_rejected
        """
        ctx = setup_verified_application(
            patient_name="Mismatch A", mrn="MRN-MIS-A", ssn_last4="0032",
            reported_income=2000000, tax_return_amount=2000000,
        )
        patient_b = create_patient(
            full_name="Mismatch B", date_of_birth="1990-01-01",
            ssn_last4="0033", mrn="MRN-MIS-B",
        )
        account_b = create_account(
            patient_b["id"], total_charges_cents=100000, insurance_paid_cents=0
        )
        app = get_application(ctx["application"]["id"])
        resp = api.create_determination(
            {
                "application_id": app["id"],
                "basis": "VERIFIED_APPLICATION",
                "covered_account_ids": [account_b["id"]],
                "expected_application_version": app["version"],
            },
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_PATIENT_MISMATCH)

    def test_finalize_twice_rejected(self, api):
        """PRD §3.8: "Finalization by an `AssistanceReviewer` requires the
        determination to be `PRELIMINARY` (`ERR_DETERMINATION_NOT_PRELIMINARY`,
        HTTP 409), the application to still be `UNDER_REVIEW`
        (`ERR_APPLICATION_NOT_UNDER_REVIEW`), and the segregation-of-duties
        check of §2.8 (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/finalize_preliminary_twice_rejected
        """
        ctx = setup_final_determination(
            patient_name="Final Fred", mrn="MRN-FIN-1", ssn_last4="0011",
            date_of_birth="1988-01-01", reported_income=2000000,
            accounts=((100000, 0),), tax_return_amount=2000000,
            members=(("SELF", 38),),
        )
        assert ctx["determination"]["status"] == "FINAL"
        resp = api.finalize_determination(ctx["determination"]["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_PRELIMINARY)

    def test_reverse_preliminary_rejected(self, api):
        """PRD §3.8: "Reversal of a `FINAL` determination — available to an
        `AssistanceReviewer` or a `ComplianceOfficer`, optionally carrying a
        `reason` — requires `FINAL` status (`ERR_DETERMINATION_NOT_FINAL`,
        HTTP 409), moves the determination `FINAL → REVERSED`, and triggers a
        three-link cascade."

        Design: Corner/state_machines/reverse_preliminary_rejected
        """
        ctx = setup_verified_application(
            patient_name="Prelim Paula", mrn="MRN-PREL-1", ssn_last4="0012",
            date_of_birth="1989-01-01", reported_income=2000000,
            accounts=((100000, 0),), tax_return_amount=2000000,
            members=(("SELF", 37),),
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        assert det["status"] == "PRELIMINARY"
        resp = api.reverse_determination(det["id"], REVIEWER, {"reason": "too early"})
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_FINAL)


class TestSegregationOfDuties:
    def _sod_setup(self):
        """Docs verified by counselor-7; PRELIMINARY determination created by
        reviewer-1."""
        counselor7 = make_financial_counselor_headers("counselor-7")
        reviewer1 = make_assistance_reviewer_headers("reviewer-1")
        ctx = setup_verified_application(
            patient_name="Segregated Sam", mrn="MRN-SOD-1", ssn_last4="0042",
            reported_income=2000000, accounts=((100000, 0),),
            tax_return_amount=2000000, counselor_headers=counselor7,
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]], headers=reviewer1,
        )
        return ctx, det, counselor7, reviewer1

    def test_finalize_by_document_verifier_rejected(self, api):
        """PRD §2.8: "When an `AssistanceReviewer` finalizes a determination,
        the reviewer's `X-User-ID` must differ from the `verified_by_user_id`
        of every `VERIFIED` verification document on the application and from
        the `screened_by_user_id` of the application's presumptive screening. A
        finalize attempt by anyone who touched the evidence is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_finalize_by_document_verifier
        """
        ctx, det, counselor7, _reviewer1 = self._sod_setup()
        finalize_as_verifier = dict(counselor7)
        finalize_as_verifier["X-User-Role"] = "AssistanceReviewer"
        resp = api.finalize_determination(det["id"], finalize_as_verifier)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = get_determination(det["id"])
        assert current["status"] == "PRELIMINARY", "rejected finalize mutates nothing"

    def test_finalize_by_uninvolved_reviewer_succeeds(self, api):
        """PRD §2.8: "When an `AssistanceReviewer` finalizes a determination,
        the reviewer's `X-User-ID` must differ from the `verified_by_user_id`
        of every `VERIFIED` verification document on the application and from
        the `screened_by_user_id` of the application's presumptive screening. A
        finalize attempt by anyone who touched the evidence is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "On success the determination moves `PRELIMINARY → FINAL`, it
        stamps `decided_by_user_id` and `finalized_at`, creates a
        `DETERMINATION_LETTER` `NotificationRecord` against the application
        with `is_plain_language` true, and resolves the application: with any
        tier other than `INELIGIBLE` the application moves `UNDER_REVIEW →
        APPROVED`, while an `INELIGIBLE` tier moves it `UNDER_REVIEW → DENIED`
        and releases every account of the patient from `ASSISTANCE_HOLD` back
        to `NOTICE_PERIOD`."

        Design: Corner/validations/segregation_of_duties_finalize_by_document_verifier
        """
        ctx, det, _counselor7, reviewer1 = self._sod_setup()
        finalized = validate_success(api.finalize_determination(det["id"], reviewer1))
        assert finalized["status"] == "FINAL"
        assert finalized["decided_by_user_id"] == "reviewer-1"


class TestFinalizeLetterAndOcc:
    def test_determination_letter_created_on_finalize(self, api):
        """PRD §3.8: "On success the determination moves `PRELIMINARY → FINAL`,
        it stamps `decided_by_user_id` and `finalized_at`, creates a
        `DETERMINATION_LETTER` `NotificationRecord` against the application
        with `is_plain_language` true, and resolves the application: with any
        tier other than `INELIGIBLE` the application moves `UNDER_REVIEW →
        APPROVED`, while an `INELIGIBLE` tier moves it `UNDER_REVIEW → DENIED`
        and releases every account of the patient from `ASSISTANCE_HOLD` back
        to `NOTICE_PERIOD`."

        Design: Corner/endpoints/determination_letter_created_on_finalize
        """
        ctx = setup_final_determination(
            patient_name="Letter Liz", mrn="MRN-LET-1", ssn_last4="0046",
            reported_income=2000000, accounts=((100000, 0),),
            tax_return_amount=2000000,
        )
        app = get_application(ctx["application"]["id"])
        assert app["status"] == "APPROVED", "TIER_FULL finalize approves the application"
        notices = list_application_notices(app["id"])
        letters = [
            n for n in notices
            if n["notice_type"] == "DETERMINATION_LETTER"
            and n["application_id"] == app["id"]
        ]
        assert len(letters) >= 1, "finalize creates the 501(r) determination letter"
        assert all(n["is_plain_language"] is True for n in letters)

    def test_stale_application_version_rejected(self, api):
        """PRD §2.11: "Creating a determination requires the request to carry
        `expected_application_version`, the client-observed `version` of the
        target application. If the application's current `version` has advanced
        since the client last read it — for instance because a document was
        verified, a determination was created or finalized, or any other
        mutation bumped it — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing a second determination from silently stacking
        onto an application the client has not observed."

        Design: Corner/errors/occ_stale_application_version_on_determination_create
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Stale Stan", mrn="MRN-STALE-1", ssn_last4="0047",
            reported_income=2000000, members=(("SELF", 40),),
            accounts=((100000, 0),),
        )
        app_id = ctx["application"]["id"]
        member_id = ctx["members"][0]["id"]
        upload_and_verify(
            app_id, member_id, doc_type="TAX_RETURN", amount_cents=2000000
        )
        identity = upload_document(
            app_id, doc_type="IDENTITY", period_start="2026-01-01",
            period_end="2026-01-01", amount_cents=0, household_member_id=member_id,
        )
        stale_version = get_application(app_id)["version"]
        verify_document(identity["id"])  # bumps the application's version
        resp = api.create_determination(
            {
                "application_id": app_id,
                "basis": "VERIFIED_APPLICATION",
                "covered_account_ids": [ctx["accounts"][0]["id"]],
                "expected_application_version": stale_version,
            },
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh_version = get_application(app_id)["version"]
        created = validate_success(
            api.create_determination(
                {
                    "application_id": app_id,
                    "basis": "VERIFIED_APPLICATION",
                    "covered_account_ids": [ctx["accounts"][0]["id"]],
                    "expected_application_version": fresh_version,
                },
                REVIEWER,
            ),
            201,
        )
        assert created["status"] == "PRELIMINARY"
