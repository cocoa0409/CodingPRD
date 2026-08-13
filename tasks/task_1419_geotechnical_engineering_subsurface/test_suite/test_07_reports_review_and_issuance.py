"""Report review cycle, issuance guards (OCC, segregation of duties, role
exclusivity), and the rejection-to-stale-to-blocked cascade."""
from test_helpers import (
    LM,
    PM,
    SEN,
    ApiErrorId,
    api_client,
    authorize_lab_order,
    create_lab_order,
    get_success_data,
    make_principal_engineer_headers,
    make_senior_engineer_headers,
    reject_lab_order,
    setup_accepted_uc_order,
    setup_pe_review_report,
    setup_project_in_report_review,
    start_lab_order,
    submit_lab_result,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

PREPARER_ID = "se-1"
ISSUER_ID = "pe-9"


# ---------------------------------------------------------------------------
# Report revision cycle (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestReportPeRejectRevisionCycle:
    """The PE may reject a PE_REVIEW report back to DRAFT, and the same
    report can re-traverse the loop; version increments on every hop."""

    def test_revision_loop_retraversable(self, api):
        """PRD section 3.6: "Review is cyclic: the preparer submits the draft
        to technical review (`DRAFT` → `TECH_REVIEW`); a `ProjectManager`
        either returns it for rework (`TECH_REVIEW` → `DRAFT`) or advances it
        to the PE (`TECH_REVIEW` → `PE_REVIEW`); a `PrincipalEngineer` may
        reject it back (`PE_REVIEW` → `DRAFT`)."

        Design: Difficulty/non_linear_state_machine/report_pe_reject_revision_cycle
        """
        ctx = setup_pe_review_report()
        report = ctx["report"]
        assert report["status"] == "PE_REVIEW"

        rejected = get_success_data(api.transition_report(
            report["id"], {"to": "DRAFT"},
            make_principal_engineer_headers(ISSUER_ID)))
        assert rejected["status"] == "DRAFT", "PE reject loops back to DRAFT"

        again = get_success_data(api.transition_report(
            report["id"], {"to": "TECH_REVIEW"}, SEN))
        assert again["status"] == "TECH_REVIEW"
        again = get_success_data(api.transition_report(
            report["id"], {"to": "PE_REVIEW"}, PM))
        assert again["status"] == "PE_REVIEW", (
            "The revision loop is re-traversable after a PE reject"
        )

    def test_version_increments_on_every_loop_hop(self, api):
        """PRD section 2.4: "`version` (integer): starts at its initial value
        on creation and increments by exactly 1 on every mutation of the
        resource, whether client-driven or system-driven." and "Every state
        transition described in §3 increments the transitioning resource's
        `version` by 1 and refreshes its `updated_at`".

        Design: Difficulty/non_linear_state_machine/report_pe_reject_revision_cycle
        """
        ctx = setup_pe_review_report()
        report = ctx["report"]
        v_pe = report["version"]

        rejected = get_success_data(api.transition_report(
            report["id"], {"to": "DRAFT"},
            make_principal_engineer_headers(ISSUER_ID)))
        assert rejected["version"] == v_pe + 1
        get_success_data(api.transition_report(
            report["id"], {"to": "TECH_REVIEW"}, SEN))
        back = get_success_data(api.transition_report(
            report["id"], {"to": "PE_REVIEW"}, PM))
        assert back["version"] == v_pe + 3, (
            "Three transitions after the captured version must yield +3"
        )


# ---------------------------------------------------------------------------
# Issuance guards (corner instances)
# ---------------------------------------------------------------------------

def test_occ_stale_report_version_on_issue_returns_412(api):
    """PRD section 2.7: "Issuing a report — `POST /geo/reports/{id}/issue` —
    requires `expected_report_version` matching the Report's current
    `version`; a mismatch is rejected with `ERR_STALE_REPORT_VERSION`
    (HTTP 412), covering the case where a reviewer has cycled the report back
    to `DRAFT` since the issuer last observed it."

    Design: Corner/validations/occ_stale_report_version_on_issue_returns_412
    """
    ctx = setup_pe_review_report()
    report = get_success_data(api.get_report(ctx["report"]["id"],
                                             make_principal_engineer_headers(ISSUER_ID)))

    resp = api.issue_report(
        report["id"], {"expected_report_version": report["version"] - 1},
        make_principal_engineer_headers(ISSUER_ID))
    validate_error(resp, ApiErrorId.ERR_STALE_REPORT_VERSION)
    assert resp.status_code == 412

    after = get_success_data(api.get_report(report["id"],
                                            make_principal_engineer_headers(ISSUER_ID)))
    assert after["status"] == "PE_REVIEW", "A stale issue has no side effects"
    assert after["sealed_by_pe_user_id"] is None


def test_report_issue_pe_is_preparer_rejected(api):
    """PRD section 3.6: "A `PrincipalEngineer` issues a report standing in
    `PE_REVIEW`, subject to five guards: the issuer's `X-User-ID` must differ
    from the report's `prepared_by_user_id` — segregation of duties, violated
    with `ERR_SOD_PE_IS_PREPARER` (HTTP 409)".

    Design: Corner/validations/report_issue_pe_is_preparer_rejected
    """
    ctx = setup_pe_review_report()
    report = ctx["report"]
    assert report["prepared_by_user_id"] == PREPARER_ID

    # The issuer presents as a PrincipalEngineer but with the preparer's id.
    resp = api.issue_report(
        report["id"], {"expected_report_version": report["version"]},
        make_principal_engineer_headers(PREPARER_ID))
    validate_error(resp, ApiErrorId.ERR_SOD_PE_IS_PREPARER)
    assert resp.status_code == 409


def test_project_manager_cannot_issue_report(api):
    """PRD section 2.1: "A request whose role is not on the endpoint's
    authorized list, or that fails an entity-backed ownership check, is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: "| POST | `/geo/reports/{id}/issue` | PE seals and issues
    a `PE_REVIEW` report (OCC plus segregation of duties) |
    PrincipalEngineer |".

    Design: Corner/rbac/project_manager_cannot_issue_report
    """
    ctx = setup_pe_review_report()
    report = ctx["report"]

    resp = api.issue_report(
        report["id"], {"expected_report_version": report["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Rejection -> stale analysis -> blocked issuance cascade (difficulty, x2)
# ---------------------------------------------------------------------------

class TestRejectionStalesAnalysisBlocksIssue:
    """Depth-3 cascade from a lab-order rejection: the sample's
    classification resets, the verified analysis goes stale, and issuance is
    consequently blocked."""

    def _setup_with_rejected_errata_order(self, api):
        """Project in REPORT_REVIEW with a report in PE_REVIEW, a VERIFIED
        CURRENT analysis, and a second sample whose SIEVE + ATTERBERG orders
        are ACCEPTED (so it classifies); then a DIRECT_SHEAR errata order is
        created during review, run to RESULT_SUBMITTED, and rejected.

        PRD section 3.4 restricts sample logging to borings in DRILLED or
        LOGGED, so the second sample (and its classification orders, which
        must be ACCEPTED before the project may enter REPORT_REVIEW per
        section 3.6) are built while the project still stands in FIELDWORK;
        only the errata order is created during review."""
        from test_helpers import (
            FG,
            SE,
            create_analysis,
            create_sample,
            run_order_to_accepted,
            ship_sample_to_lab,
            transition_analysis,
            transition_boring,
            transition_project,
        )

        # Project FIELDWORK, boring DRILLED, UC order ACCEPTED.
        ctx = setup_accepted_uc_order()
        project_id = ctx["project"]["id"]

        # A second sample logged while the boring still stands in DRILLED,
        # with both classification inputs accepted.
        sample2 = create_sample(ctx["boring"]["id"], depth_top_ft=12,
                                depth_bottom_ft=13.5, sampler_type="SPT",
                                recovery_pct=85)
        ship_sample_to_lab(sample2["id"])
        run_order_to_accepted(project_id, sample2["id"], "SIEVE_ANALYSIS",
                              {"percent_passing_200": 42})
        run_order_to_accepted(project_id, sample2["id"], "ATTERBERG",
                              {"liquid_limit": 38, "plasticity_index": 12})
        classified = get_success_data(api.get_sample(sample2["id"], LM))
        assert classified["uscs_class"] == "SC"

        # Verified analysis (project still in FIELDWORK).
        analysis = create_analysis(project_id)
        ctx["analysis"] = transition_analysis(analysis["id"], "VERIFIED")

        # Advance: boring LOGGED -> CLOSED, project LAB_ANALYSIS ->
        # REPORT_REVIEW, report DRAFT -> TECH_REVIEW -> PE_REVIEW.
        transition_boring(ctx["boring"]["id"], "LOGGED", FG)
        transition_boring(ctx["boring"]["id"], "CLOSED", SE)
        transition_project(project_id, "LAB_ANALYSIS")
        ctx["project"] = transition_project(project_id, "REPORT_REVIEW",
                                            headers=SEN)
        report = get_success_data(api.create_report(
            project_id, {}, make_senior_engineer_headers(PREPARER_ID)))
        report = get_success_data(api.transition_report(
            report["id"], {"to": "TECH_REVIEW"}, SEN))
        report = get_success_data(api.transition_report(
            report["id"], {"to": "PE_REVIEW"}, PM))
        ctx["report"] = report

        # Errata order during REPORT_REVIEW is expressly permitted.
        errata = create_lab_order(project_id, sample2["id"],
                                  test_type="DIRECT_SHEAR")
        authorize_lab_order(errata["id"])
        start_lab_order(errata["id"])
        submit_lab_result(errata["id"], qu_psf=2100)
        reject_lab_order(errata["id"])
        return ctx, sample2, errata

    def test_rejection_resets_classification_and_stales_analysis(self, api):
        """PRD section 3.4: "Rejection cascades as a three-link chain: the
        sample's `uscs_class` resets to null (link 1); every `VERIFIED`
        FoundationAnalysis of the project goes `STALE` (link 2, caused by the
        classification reset); and report issuance is consequently blocked,
        because sealing requires a verified analysis whose data is current
        (link 3, §3.6)."

        Design: Difficulty/transitive_cascade/rejection_stales_analysis_blocks_issue
        """
        ctx, sample2, _errata = self._setup_with_rejected_errata_order(api)

        sample_after = get_success_data(api.get_sample(sample2["id"], LM))
        assert sample_after["uscs_class"] is None, (
            "Link 1: rejection resets the sample's uscs_class to null"
        )
        analysis_after = get_success_data(
            api.get_foundation_analysis(ctx["analysis"]["id"], SEN))
        assert analysis_after["data_status"] == "STALE", (
            "Link 2: every VERIFIED analysis of the project goes STALE"
        )

    def test_issuance_blocked_after_rejection(self, api):
        """PRD section 3.4: "Rejection cascades as a three-link chain: the
        sample's `uscs_class` resets to null (link 1); every `VERIFIED`
        FoundationAnalysis of the project goes `STALE` (link 2, caused by the
        classification reset); and report issuance is consequently blocked,
        because sealing requires a verified analysis whose data is current
        (link 3, §3.6)."
        PRD section 3.6: "a FoundationAnalysis of the project must stand in
        `VERIFIED` (`ERR_ANALYSIS_NOT_VERIFIED`); that analysis must carry
        `data_status` equal to `CURRENT` (`ERR_ANALYSIS_DATA_STALE`); every
        laboratory order of the project must stand in `ACCEPTED`
        (`ERR_ORDER_STATE_FORBIDS`)".

        (After the rejection both the data_status guard and the
        all-orders-accepted guard fail; both are category-5 errors and the
        PRD does not rank them against each other, so either identifier
        evidences the block.)

        Design: Difficulty/transitive_cascade/rejection_stales_analysis_blocks_issue
        """
        ctx, _sample2, _errata = self._setup_with_rejected_errata_order(api)

        report = get_success_data(api.get_report(
            ctx["report"]["id"], make_principal_engineer_headers(ISSUER_ID)))
        resp = api.issue_report(
            report["id"], {"expected_report_version": report["version"]},
            make_principal_engineer_headers(ISSUER_ID))
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_ANALYSIS_DATA_STALE,
                   ApiErrorId.ERR_ORDER_STATE_FORBIDS])
        assert resp.status_code == 409, (
            f"Issuance must be blocked (409); surfaced {actual}"
        )
        after = get_success_data(api.get_report(
            report["id"], make_principal_engineer_headers(ISSUER_ID)))
        assert after["status"] == "PE_REVIEW"
        assert after["sealed_by_pe_user_id"] is None
