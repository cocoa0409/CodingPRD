"""Application intake, document review, eligibility screens, and amendments."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_documents,
    add_customer_account,
    create_draft_application,
    create_document_payload,
    decide_completeness,
    drive_to_capacity_reserved,
    drive_to_customer_decision_pending,
    drive_to_screen_passed,
    get_application,
    get_program,
    get_success_data,
    schedule_and_complete_exchange,
    schedule_and_pass_inspection,
    setup_program_with_grid,
    upload_required_documents,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


class TestDocumentReviewState:
    def test_review_from_accepted_rejected(self, api):
        """PRD §3.3: "each document starts with `review_status` `UPLOADED`. A
        coordinator then reviews each uploaded document to `ACCEPTED` or
        `REJECTED`, storing a `review_note` with the decision"
        PRD §2.10: "Eighth, the primary resource being in a state that permits
        the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline)."

        Design: Corner/state_machines/sm_document_review_from_uploaded_only
        """
        sc = setup_program_with_grid("SD", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        doc = get_success_data(api.create_document(
            create_document_payload(app["id"], doc_type="SITE_PLAN",
                                    title="site"), ctx["applicant"]))
        reviewed = validate_success(api.review_document(
            doc["id"], {"outcome": "ACCEPTED"}, COORDINATOR))
        assert reviewed["review_status"] == "ACCEPTED"

        resp = api.review_document(
            doc["id"], {"outcome": "REJECTED", "review_note": "second look"},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        doc_after = validate_success(api.get_document(doc["id"], ADMIN))
        assert doc_after["review_status"] == "ACCEPTED"


class TestCompletenessDecisionState:
    def test_decision_on_draft_rejected(self, api):
        """PRD §3.3: "Submission moves a `DRAFT` application to
        `PENDING_COMPLETENESS`; it requires the program to be `OPEN` or
        `CAP_REACHED` (otherwise `ERR_PROGRAM_NOT_ACCEPTING`), the account to
        be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`), and no other
        non-terminal application to exist for the same account (otherwise
        `ERR_DUPLICATE_ACTIVE_APPLICATION`)."
        PRD §2.10: "Eighth, the primary resource being in a state that permits
        the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline)."

        Design: Corner/state_machines/sm_completeness_decision_on_draft_rejected
        """
        sc = setup_program_with_grid("SC", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        resp = api.completeness_decision(app["id"], {"outcome": "COMPLETE"},
                                         COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestDuplicateActiveApplication:
    def test_second_submit_blocked_while_first_pending(self, api):
        """PRD §3.3: "Submission moves a `DRAFT` application to
        `PENDING_COMPLETENESS`; it requires the program to be `OPEN` or
        `CAP_REACHED` (otherwise `ERR_PROGRAM_NOT_ACCEPTING`), the account to
        be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`), and no other
        non-terminal application to exist for the same account (otherwise
        `ERR_DUPLICATE_ACTIVE_APPLICATION`)."

        Design: Corner/validations/v_duplicate_active_application_at_submit
        """
        sc = setup_program_with_grid("DA", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app1 = create_draft_application(sc, ctx, size=10_000,
                                        production=15_000_000)
        get_success_data(api.submit_application(app1["id"], ctx["applicant"]))
        app2 = create_draft_application(sc, ctx, size=5_000,
                                        production=8_000_000,
                                        technology="WIND")

        resp = api.submit_application(app2["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION, 422)
        assert get_application(app2["id"])["application_status"] == "DRAFT"


class TestRequiredDocumentSet:
    def test_missing_insurance_certificate_blocks_complete(self, api):
        """PRD §3.3: "Marking `COMPLETE` first requires the full required
        document set — one accepted document of each of the three types — to
        be entirely `ACCEPTED`; deciding `COMPLETE` against an incomplete set
        is rejected with `ERR_INCOMPLETE_DOCUMENTS`."

        Design: Corner/validations/v_insurance_certificate_required_over_1mw
        """
        sc = setup_program_with_grid(
            "IC",
            program_overrides={"aggregate_cap_watts": 5_000_000},
            feeder_overrides={"peak_load_watts": 100_000_000},
            transformer_overrides={"nameplate_watts": 100_000_000})
        ctx = add_customer_account(sc, "1", service_class="INDUSTRIAL",
                                   prior_annual_usage_wh=100_000_000)
        app = create_draft_application(sc, ctx, size=1_500_000,
                                       production=3_000_000)
        docs = {}
        for doc_type, title in (("SITE_PLAN", "site"),
                                ("SINGLE_LINE_DIAGRAM", "sld")):
            docs[doc_type] = get_success_data(api.create_document(
                create_document_payload(app["id"], doc_type=doc_type,
                                        title=title), ctx["applicant"]))
        accept_documents(docs)
        get_success_data(api.submit_application(app["id"], ctx["applicant"]))

        resp = api.completeness_decision(app["id"], {"outcome": "COMPLETE"},
                                         COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_DOCUMENTS, 422)

        cert = get_success_data(api.create_document(
            create_document_payload(app["id"], doc_type="INSURANCE_CERTIFICATE",
                                    title="coi"), ctx["applicant"]))
        accept_documents({"INSURANCE_CERTIFICATE": cert})
        app = validate_success(api.completeness_decision(
            app["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app["application_status"] == "CAPACITY_RESERVED"
        assert app["capacity_reserved_watts"] == 1_500_000

    def test_incomplete_decision_requires_a_rejected_document(self, api):
        """PRD §3.3: "Marking an application `INCOMPLETE` requires at least one
        of its documents to be in `REJECTED` status — otherwise the decision is
        rejected with `ERR_NO_REJECTED_DOCUMENTS` — and the payload must carry
        a `deficiency_note` explaining the gaps, with a missing note rejected
        as `ERR_INVALID_REQUEST`"

        Design: Corner/validations/v_incomplete_decision_requires_rejected_document
        """
        sc = setup_program_with_grid("NR", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        accept_documents(upload_required_documents(ctx, app["id"]))
        get_success_data(api.submit_application(app["id"], ctx["applicant"]))

        resp = api.completeness_decision(
            app["id"], {"outcome": "INCOMPLETE",
                        "deficiency_note": "arbitrary bounce"}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_NO_REJECTED_DOCUMENTS, 422)
        assert (get_application(app["id"])["application_status"]
                == "PENDING_COMPLETENESS")


class TestEligibilityScreen:
    def test_zero_usage_and_size_cap_checked_first(self, api):
        """PRD §3.3: "The size check comes first: if `system_size_watts_ac`
        exceeds the cap for the account's `service_class` — 25,000 watts
        (25 kW) for `RESIDENTIAL`, 1,000,000 watts (1 MW) for `COMMERCIAL`,
        5,000,000 watts (5 MW) for `INDUSTRIAL` — the application is denied
        with `denial_reason` `SIZE_EXCEEDS_CLASS_CAP`."
        PRD §3.3: "Estimated production exactly equal to the cap passes, and an
        account with zero prior usage fails any positive production estimate. A
        denial lands the application in terminal `DENIED` status."

        Design: Corner/calculations/c_eligibility_zero_usage_and_size_cap_order
        """
        sc = setup_program_with_grid("EL")
        ctx_z = add_customer_account(sc, "Z", prior_annual_usage_wh=0)
        app_z = create_draft_application(sc, ctx_z, size=10_000, production=1)
        accept_documents(upload_required_documents(ctx_z, app_z["id"]))
        get_success_data(api.submit_application(app_z["id"],
                                                ctx_z["applicant"]))

        ctx_r = add_customer_account(sc, "R", service_class="RESIDENTIAL",
                                     prior_annual_usage_wh=100_000_000)
        app_r = create_draft_application(sc, ctx_r, size=30_000,
                                         production=999_999_999)
        accept_documents(upload_required_documents(ctx_r, app_r["id"]))
        get_success_data(api.submit_application(app_r["id"],
                                                ctx_r["applicant"]))

        app_z = validate_success(api.completeness_decision(
            app_z["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app_z["application_status"] == "DENIED"
        assert app_z["denial_reason"] == "PRODUCTION_EXCEEDS_LOAD", (
            "usage 0 makes the production cap 0; production 1 Wh exceeds it")

        app_r = validate_success(api.completeness_decision(
            app_r["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app_r["application_status"] == "DENIED"
        assert app_r["denial_reason"] == "SIZE_EXCEEDS_CLASS_CAP", (
            "size is checked before the production ratio")

    def test_production_at_110_percent_boundary(self, api):
        """PRD §3.3: "Otherwise the production check runs: the production cap
        is the account's `prior_annual_usage_wh` multiplied by 110 percent with
        the product floored to whole watt-hours, and if
        `estimated_annual_production_wh` exceeds that cap the application is
        denied with `denial_reason` `PRODUCTION_EXCEEDS_LOAD`. Estimated
        production exactly equal to the cap passes, and an account with zero
        prior usage fails any positive production estimate."

        Design: Difficulty/boundary_precision_check/bpc_eligibility_production_110_boundary
        """
        sc = setup_program_with_grid("BND")
        ctx_p = add_customer_account(sc, "P",
                                     prior_annual_usage_wh=10_000_000)
        app_p = create_draft_application(sc, ctx_p, size=10_000,
                                         production=11_000_000)
        accept_documents(upload_required_documents(ctx_p, app_p["id"]))
        get_success_data(api.submit_application(app_p["id"],
                                                ctx_p["applicant"]))

        ctx_q = add_customer_account(sc, "Q",
                                     prior_annual_usage_wh=10_000_000)
        app_q = create_draft_application(sc, ctx_q, size=10_000,
                                         production=11_000_001)
        accept_documents(upload_required_documents(ctx_q, app_q["id"]))
        get_success_data(api.submit_application(app_q["id"],
                                                ctx_q["applicant"]))

        # floor(10,000,000 * 110 / 100) == 11,000,000: equality passes.
        app_p = validate_success(api.completeness_decision(
            app_p["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app_p["application_status"] == "CAPACITY_RESERVED"
        assert app_p["capacity_reserved_watts"] == 10_000

        # One watt-hour over the cap is denied.
        app_q = validate_success(api.completeness_decision(
            app_q["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app_q["application_status"] == "DENIED"
        assert app_q["denial_reason"] == "PRODUCTION_EXCEEDS_LOAD"

        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 10_000

    def test_production_cap_floors_the_percentage_product(self, api):
        """PRD §3.3: "the production cap is the account's
        `prior_annual_usage_wh` multiplied by 110 percent with the product
        floored to whole watt-hours, and if `estimated_annual_production_wh`
        exceeds that cap the application is denied with `denial_reason`
        `PRODUCTION_EXCEEDS_LOAD`."

        Design: Difficulty/boundary_precision_check/bpc_eligibility_production_110_boundary
        """
        # floor(9,999,999 * 110 / 100) == floor(10,999,998.9) == 10,999,998.
        sc = setup_program_with_grid("BND2")
        ctx_a = add_customer_account(sc, "A",
                                     prior_annual_usage_wh=9_999_999)
        app_a = create_draft_application(sc, ctx_a, size=10_000,
                                         production=10_999_998)
        accept_documents(upload_required_documents(ctx_a, app_a["id"]))
        get_success_data(api.submit_application(app_a["id"],
                                                ctx_a["applicant"]))

        ctx_b = add_customer_account(sc, "B",
                                     prior_annual_usage_wh=9_999_999)
        app_b = create_draft_application(sc, ctx_b, size=10_000,
                                         production=10_999_999)
        accept_documents(upload_required_documents(ctx_b, app_b["id"]))
        get_success_data(api.submit_application(app_b["id"],
                                                ctx_b["applicant"]))

        app_a = validate_success(api.completeness_decision(
            app_a["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app_a["application_status"] == "CAPACITY_RESERVED"

        app_b = validate_success(api.completeness_decision(
            app_b["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app_b["application_status"] == "DENIED"
        assert app_b["denial_reason"] == "PRODUCTION_EXCEEDS_LOAD"


class TestSubmitRequiresActiveAccount:
    def test_suspended_account_blocks_submit_until_reactivated(self, api):
        """PRD §3.3: "Submission moves a `DRAFT` application to
        `PENDING_COMPLETENESS`; it requires the program to be `OPEN` or
        `CAP_REACHED` (otherwise `ERR_PROGRAM_NOT_ACCEPTING`), the account to
        be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`), and no other
        non-terminal application to exist for the same account (otherwise
        `ERR_DUPLICATE_ACTIVE_APPLICATION`)."

        Design: Difficulty/cross_entity_state_dependency/cesd_submit_requires_active_account
        """
        sc = setup_program_with_grid("CES", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        get_success_data(
            api.suspend_service_account(ctx["account"]["id"], ADMIN))
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)

        resp = api.submit_application(app["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 422)
        assert get_application(app["id"])["application_status"] == "DRAFT"

        get_success_data(
            api.reactivate_service_account(ctx["account"]["id"], ADMIN))
        app = validate_success(
            api.submit_application(app["id"], ctx["applicant"]))
        assert app["application_status"] == "PENDING_COMPLETENESS"
        assert app["submission_round"] == 1

    def test_suspended_account_blocks_pto_until_reactivated(self, api):
        """PRD §3.8: "Four gates guard the grant, and the order between two of
        them is pinned: the account must be `ACTIVE`
        (`ERR_ACCOUNT_NOT_ACTIVE`); a completed meter exchange must exist for
        the application (`ERR_METER_EXCHANGE_NOT_COMPLETED`, checked before the
        inspection gate); the latest inspection — the one with the greatest
        `created_at` — must be `RESULT_RECORDED` with `outcome` `PASSED`
        (`ERR_INSPECTION_NOT_PASSED`); and a tariff schedule of the program
        must be effective at the current clock time
        (`ERR_NO_EFFECTIVE_TARIFF`)."

        Design: Difficulty/cross_entity_state_dependency/cesd_submit_requires_active_account
        """
        sc = setup_program_with_grid("CES2")
        ctx = add_customer_account(sc, "1")
        app = drive_to_screen_passed(sc, ctx, size=10_000,
                                     production=15_000_000)
        schedule_and_complete_exchange(app["id"])
        schedule_and_pass_inspection(ctx, app["id"])

        get_success_data(
            api.suspend_service_account(ctx["account"]["id"], ADMIN))
        resp = api.grant_pto(app["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 422)
        assert (get_application(app["id"])["application_status"]
                == "SCREEN_PASSED")

        get_success_data(
            api.reactivate_service_account(ctx["account"]["id"], ADMIN))
        app = validate_success(api.grant_pto(app["id"], COORDINATOR))
        assert app["application_status"] == "PTO_GRANTED"


class TestAmendmentRules:
    def test_empty_amend_payload_returns_400(self, api):
        """PRD §3.6: "an applicant may amend an application while it is in
        `DRAFT`, `CAPACITY_RESERVED`, or `SUPPLEMENTAL_REVIEW`, revising any of
        `system_size_watts_ac`, `estimated_annual_production_wh`, or
        `technology`; a payload touching none of these is rejected as
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/v_amend_empty_payload_returns_400
        """
        sc = setup_program_with_grid("AE", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        resp = api.amend_application(app["id"], {}, ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_amend_forbidden_in_customer_decision_pending(self, api):
        """PRD §3.6: "an applicant may amend an application while it is in
        `DRAFT`, `CAPACITY_RESERVED`, or `SUPPLEMENTAL_REVIEW`, revising any of
        `system_size_watts_ac`, `estimated_annual_production_wh`, or
        `technology`; a payload touching none of these is rejected as
        `ERR_INVALID_REQUEST`."
        PRD §2.10: "Eighth, the primary resource being in a state that permits
        the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline)."

        Design: Corner/validations/v_amend_forbidden_in_decision_pending
        """
        sc = setup_program_with_grid(
            "AF",
            feeder_overrides={"peak_load_watts": 1_000_000,
                              "pre_existing_der_watts": 140_000})
        ctx = add_customer_account(sc, "1",
                                   prior_annual_usage_wh=100_000_000)
        app, _review, _estimate = drive_to_customer_decision_pending(
            sc, ctx, size=20_000, production=30_000_000)

        resp = api.amend_application(
            app["id"], {"system_size_watts_ac": 9_000}, ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert (get_application(app["id"])["system_size_watts_ac"] == 20_000)

    def test_amend_eligibility_violations_rejected(self, api):
        """PRD §3.6: "an amended size above the class cap is rejected with
        `ERR_SIZE_EXCEEDS_CLASS_CAP`, and an amended production estimate above
        the 110-percent-of-usage cap is rejected with
        `ERR_PRODUCTION_EXCEEDS_LOAD` — the size check is always evaluated
        first, so an amendment violating both reports the size violation."

        Design: Corner/validations/v_amend_eligibility_violation_rejected
        """
        sc = setup_program_with_grid("AV")
        ctx_p = add_customer_account(sc, "P")
        app_p = drive_to_capacity_reserved(sc, ctx_p, size=10_000,
                                           production=15_000_000)
        ctx_r = add_customer_account(sc, "R", service_class="RESIDENTIAL")
        app_r = drive_to_capacity_reserved(sc, ctx_r, size=10_000,
                                           production=15_000_000)

        # 23,000,000 > floor(20,000,000 * 110 / 100) == 22,000,000.
        resp = api.amend_application(
            app_p["id"], {"estimated_annual_production_wh": 23_000_000},
            ctx_p["applicant"])
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_EXCEEDS_LOAD, 422)

        # 30,000 W exceeds the 25,000 W RESIDENTIAL class cap.
        resp = api.amend_application(
            app_r["id"], {"system_size_watts_ac": 30_000}, ctx_r["applicant"])
        validate_error(resp, ApiErrorId.ERR_SIZE_EXCEEDS_CLASS_CAP, 422)

        after_p = get_application(app_p["id"])
        assert after_p["estimated_annual_production_wh"] == 15_000_000
        assert after_p["application_status"] == "CAPACITY_RESERVED"
        after_r = get_application(app_r["id"])
        assert after_r["system_size_watts_ac"] == 10_000
        assert after_r["application_status"] == "CAPACITY_RESERVED"


class TestCompletenessCureAndAmendCycle:
    def test_cure_loop_then_design_revision_loop(self, api):
        """PRD §3.3: "An application sent back as `INCOMPLETE` may be
        resubmitted under the same program-and-account conditions;
        resubmission stamps `submitted_at` again and increments
        `submission_round` by one."
        PRD §3.6: "A successful amendment supersedes the application's
        `CURRENT` screening reports and closes its `OPEN` supplemental reviews,
        since the engineering record no longer describes the design on file."

        Design: Difficulty/non_linear_state_machine/nsm_application_completeness_cure_and_amend_cycle
        """
        sc = setup_program_with_grid(
            "CYC",
            feeder_overrides={"peak_load_watts": 1_000_000,
                              "pre_existing_der_watts": 140_000})
        ctx = add_customer_account(sc, "1",
                                   prior_annual_usage_wh=100_000_000)
        app = create_draft_application(sc, ctx, size=20_000,
                                       production=30_000_000)
        docs = upload_required_documents(ctx, app["id"])
        # The first site plan is rejected; the other two types pass.
        get_success_data(api.review_document(
            docs["SITE_PLAN"]["id"],
            {"outcome": "REJECTED", "review_note": "illegible"}, COORDINATOR))
        accept_documents({"SINGLE_LINE_DIAGRAM": docs["SINGLE_LINE_DIAGRAM"],
                          "INSURANCE_CERTIFICATE": docs["INSURANCE_CERTIFICATE"]})
        get_success_data(api.submit_application(app["id"], ctx["applicant"]))
        app = decide_completeness(app["id"], "INCOMPLETE",
                                  deficiency_note="site plan illegible")
        assert app["application_status"] == "INCOMPLETE"

        # Cure: a replacement SITE_PLAN is uploaded while INCOMPLETE.
        site_v2 = get_success_data(api.create_document(
            create_document_payload(app["id"], doc_type="SITE_PLAN",
                                    title="site v2"), ctx["applicant"]))
        accept_documents({"SITE_PLAN": site_v2})
        app = validate_success(
            api.submit_application(app["id"], ctx["applicant"]))
        assert app["submission_round"] == 2
        app = decide_completeness(app["id"], "COMPLETE")
        assert app["application_status"] == "CAPACITY_RESERVED"
        assert app["capacity_reserved_watts"] == 20_000

        # The 20 kW design fails the strict feeder screen (160,000 >= 150,000).
        rep1 = validate_success(api.create_screening_report(
            {"application_id": app["id"]}, TEST_USERS["engineer_headers"]),
            201)
        assert rep1["outcome"] == "FAILED"
        assert rep1["failing_screens"] == ["FEEDER_PENETRATION"]
        app = get_application(app["id"])
        assert app["application_status"] == "SUPPLEMENTAL_REVIEW"

        # Design revision: shrink to 9 kW, returning to CAPACITY_RESERVED.
        app = validate_success(api.amend_application(
            app["id"], {"system_size_watts_ac": 9_000}, ctx["applicant"]))
        assert app["application_status"] == "CAPACITY_RESERVED"
        assert app["capacity_reserved_watts"] == 9_000
        rep1_after = validate_success(
            api.get_screening_report(rep1["id"], ADMIN))
        assert rep1_after["report_status"] == "SUPERSEDED"

        # The 9 kW design passes: 140,000 + 9,000 = 149,000 < 150,000.
        rep2 = validate_success(api.create_screening_report(
            {"application_id": app["id"]}, TEST_USERS["engineer_headers"]),
            201)
        assert rep2["screening_round"] == 2
        assert rep2["outcome"] == "PASSED"
        assert rep2["feeder_aggregate_after_watts"] == 149_000
        assert rep2["feeder_limit_watts"] == 150_000
        app = get_application(app["id"])
        assert app["application_status"] == "SCREEN_PASSED"
        assert get_program(sc["program"]["id"])["reserved_watts"] == 9_000

    def test_amend_leaves_draft_and_keeps_reserved_state(self, api):
        """PRD §3.6: "Amendment leaves a `DRAFT` application in `DRAFT`; an
        amendment made from `SUPPLEMENTAL_REVIEW` returns the application to
        `CAPACITY_RESERVED` once the capacity rule below is satisfied; and an
        amendment made from `CAPACITY_RESERVED` keeps it there, unless the size
        increase triggers the release-and-requeue path, in which case the
        application lands in `WAITING_FOR_CAPACITY`."

        Design: Difficulty/non_linear_state_machine/nsm_application_completeness_cure_and_amend_cycle
        """
        sc = setup_program_with_grid("CYC2")
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        app = validate_success(api.amend_application(
            app["id"], {"technology": "WIND"}, ctx["applicant"]))
        assert app["application_status"] == "DRAFT"
        assert app["technology"] == "WIND"

        accept_documents(upload_required_documents(ctx, app["id"]))
        get_success_data(api.submit_application(app["id"], ctx["applicant"]))
        app = decide_completeness(app["id"], "COMPLETE")
        assert app["application_status"] == "CAPACITY_RESERVED"

        # A 2 kW increase fits the remaining headroom, so the reservation is
        # resized in place and the application stays CAPACITY_RESERVED.
        app = validate_success(api.amend_application(
            app["id"], {"system_size_watts_ac": 12_000}, ctx["applicant"]))
        assert app["application_status"] == "CAPACITY_RESERVED"
        assert app["capacity_reserved_watts"] == 12_000
        program = get_program(sc["program"]["id"])
        assert program["reserved_watts"] == 12_000
        assert program["available_capacity_watts"] == 988_000


class TestApplicationVersioning:
    def test_version_increments_once_per_application_mutation(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments with every modification to the resource."

        Design: Corner/cross_cutting_complexity_layers/cc_version_increments_on_each_mutation
        """
        sc = setup_program_with_grid("VER")
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        v_create = app["version"]
        accept_documents(upload_required_documents(ctx, app["id"]))

        app = validate_success(
            api.submit_application(app["id"], ctx["applicant"]))
        assert app["version"] == v_create + 1, (
            "submit modifies the application exactly once")

        app = validate_success(api.completeness_decision(
            app["id"], {"outcome": "COMPLETE"}, COORDINATOR))
        assert app["version"] == v_create + 2, (
            "the completeness decision modifies the application exactly once")
        assert app["application_status"] == "CAPACITY_RESERVED"

    def test_document_operations_do_not_touch_application_version(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments with every modification to the resource."

        Design: Corner/cross_cutting_complexity_layers/cc_version_increments_on_each_mutation
        """
        sc = setup_program_with_grid("VER2")
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        v_create = app["version"]
        # Uploading and reviewing documents modifies the documents, not the
        # application resource.
        accept_documents(upload_required_documents(ctx, app["id"]))
        after = get_application(app["id"])
        assert after["version"] == v_create, (
            "document upload and review leave the application unmodified")
