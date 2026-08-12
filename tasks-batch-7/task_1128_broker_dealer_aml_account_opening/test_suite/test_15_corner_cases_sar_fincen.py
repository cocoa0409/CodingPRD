"""Corner queue: case workflow, SAR drafting/filing/continuing review, 314(a) responses."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_case_payload,
    create_sar_filing,
    get_account,
    get_account_version,
    get_case,
    get_sar_filing,
    list_alerts_for_account,
    post_wire,
    set_clock,
    setup_case_in_state,
    setup_filed_sar,
    setup_open_account,
    setup_scanned_314a_match,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_analyst_headers, make_sar_officer_headers


class TestCaseRecommendSarBeforeInvestigationRejected:
    def test_recommend_on_open_case_rejected_and_recommender_stays_null(self, api):
        """PRD §3.6: "Recommending from any state other than `INVESTIGATING` is
        rejected with `ERR_CASE_NOT_ACTIONABLE`."
        PRD §3.6: "the system stamps `recommending_analyst_id` from `X-User-ID`" — only
        on a successful recommendation; on the rejected attempt it stays null.

        Design: Corner/state_machines/case_recommend_sar_before_investigation_rejected
        """
        ctx = setup_case_in_state("OPEN")
        case_id = ctx["case"]["id"]
        resp = api_client.recommend_sar(
            case_id,
            {"recommendation_note": "too early", "initial_detection_date": "2026-05-01"},
            make_analyst_headers("analyst-s9"),
        )
        error = validate_error(resp, ApiErrorId.ERR_CASE_NOT_ACTIONABLE)
        assert error["error_id"] == "ERR_CASE_NOT_ACTIONABLE"
        case = get_case(case_id)
        assert case.get("recommending_analyst_id") is None


class TestSarFileTwiceRejected:
    def test_second_file_rejected_and_filed_at_unchanged(self, api):
        """PRD §3.6: "Filing a draft — only possible from `DRAFT`, else
        `ERR_SAR_NOT_FILABLE`" — an already-FILED filing cannot be filed again, and its
        `filed_at` does not move on the second attempt.

        Design: Corner/state_machines/sar_file_twice_rejected
        """
        ctx = setup_filed_sar(analyst_id="analyst-s11", sar_officer_id="saroff-s11")
        sar = ctx["sar"]
        first_filed_at = sar["filed_at"]
        assert sar["status"] == "FILED"

        resp = api_client.file_sar(sar["id"], make_sar_officer_headers("saroff-s11"))
        error = validate_error(resp, ApiErrorId.ERR_SAR_NOT_FILABLE)
        assert error["error_id"] == "ERR_SAR_NOT_FILABLE"
        reread = get_sar_filing(sar["id"])
        assert reread["filed_at"] == first_filed_at


class TestSarContinuingPriorFilingCaseMismatch:
    def test_prior_filing_from_another_case_rejected(self, api):
        """PRD §3.6: "A *continuing-activity* filing sets `prior_filing_id` to a filing
        of the same case currently in `FILED` status, with the case itself in
        `DECIDED_FILED`; a prior filing from another case, or one not `FILED`, is
        rejected with `ERR_PRIOR_FILING_CASE_MISMATCH`."

        Design: Corner/validations/sar_continuing_prior_filing_case_mismatch
        """
        ctx_a = setup_filed_sar(analyst_id="analyst-v4", sar_officer_id="saroff-v4")
        sar_a = ctx_a["sar"]
        ctx_b = setup_case_in_state(
            "SAR_RECOMMENDED", detection_date="2026-05-02", analyst_id="analyst-v4"
        )

        resp = api_client.create_sar_filing(
            {
                "case_id": ctx_b["case"]["id"],
                "narrative": "cross-linked",
                "activity_start": "2026-05-02",
                "activity_end": "2026-05-02",
                "prior_filing_id": sar_a["id"],
            },
            make_sar_officer_headers("saroff-v4"),
        )
        error = validate_error(resp, ApiErrorId.ERR_PRIOR_FILING_CASE_MISMATCH)
        assert error["error_id"] == "ERR_PRIOR_FILING_CASE_MISMATCH"
        assert resp.status_code == 400


class TestSarContinuingNoActivityReview:
    def test_no_continuing_activity_records_review_without_draft(self, api):
        """PRD §3.6: "Each review increments `continuing_review_count`, stamps
        `last_continuing_review_at`, clears `review_overdue`, and returns
        `new_draft_filing_id` and `next_review_due`. When the outcome is
        `CONTINUING_ACTIVITY`, a new `DRAFT` filing is created in the same action with
        its `prior_filing_id` set to the reviewed filing and a deadline one hundred
        twenty days after that filing's filed date."
        With outcome NO_CONTINUING_ACTIVITY no draft is created
        (`new_draft_filing_id` is null), the count moves to 1, and the filing stays
        FILED.

        Design: Corner/endpoints/sar_continuing_no_activity_review
        """
        ctx = setup_filed_sar(
            detection_date="2026-04-20",
            analyst_id="analyst-p5",
            sar_officer_id="saroff-p5",
            activity_start="2026-04-01",
            activity_end="2026-04-20",
        )
        sar = ctx["sar"]
        set_clock("2026-05-15T00:00:00Z")
        resp = api_client.record_continuing_review(
            sar["id"],
            {"outcome": "NO_CONTINUING_ACTIVITY", "note": "quiet period"},
            make_sar_officer_headers("saroff-p5"),
        )
        outcome = validate_success(resp)
        assert outcome["new_draft_filing_id"] is None, (
            "no continuing draft may be created for NO_CONTINUING_ACTIVITY"
        )
        reread = get_sar_filing(sar["id"])
        assert reread["continuing_review_count"] == 1
        assert reread["status"] == "FILED"


class TestSarContinuingFilingSupersedesPrior:
    def test_filing_continuing_sar_supersedes_prior_and_anchors_120d(self, api):
        """PRD §3.6: "When the outcome is `CONTINUING_ACTIVITY`, a new `DRAFT` filing
        is created in the same action with its `prior_filing_id` set to the reviewed
        filing and a deadline one hundred twenty days after that filing's filed date."
        PRD §3.6: "for a continuing filing, the prior filing moves `FILED` →
        `SUPERSEDED`" and "`filed_late` (true exactly when the filed date is later than
        the `filing_deadline`)".
        Prior filed 2026-05-01 -> continuing deadline 2026-08-29; filed 2026-05-20 is
        not late.

        Design: Corner/endpoints/sar_continuing_filing_supersedes_prior
        """
        ctx = setup_filed_sar(
            detection_date="2026-04-20",
            analyst_id="analyst-p6",
            sar_officer_id="saroff-p6",
            activity_start="2026-04-01",
            activity_end="2026-04-20",
        )
        sar1 = ctx["sar"]
        set_clock("2026-05-10T00:00:00Z")
        resp = api_client.record_continuing_review(
            sar1["id"],
            {
                "outcome": "CONTINUING_ACTIVITY",
                "note": "ongoing",
                "narrative": "continuing",
                "activity_start": "2026-05-01",
                "activity_end": "2026-05-10",
            },
            make_sar_officer_headers("saroff-p6"),
        )
        sar2_id = validate_success(resp)["new_draft_filing_id"]

        set_clock("2026-05-20T00:00:00Z")
        resp = api_client.file_sar(sar2_id, make_sar_officer_headers("saroff-p6"))
        sar2 = validate_success(resp)
        assert sar2["status"] == "FILED"
        assert sar2["filing_deadline"] == "2026-08-29", (
            f"prior filed 2026-05-01 + 120d = 2026-08-29, got {sar2['filing_deadline']}"
        )
        assert sar2["filed_late"] is False

        prior = get_sar_filing(sar1["id"])
        assert prior["status"] == "SUPERSEDED"


class TestOccCaseCreateStaleAccountVersion:
    def test_second_create_with_same_version_rejected_412(self, api):
        """PRD §2.6: "**Manual case opening** requires `expected_account_version`,
        carrying the client's last observed `version` of the target brokerage account.
        Opening a case legitimately mutates the account (case counts, risk
        recalculation, version bump), so if the account's current `version` no longer
        matches the submitted value, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from acting on a stale view of the account."

        Design: Corner/cross_cutting_layers/occ_case_create_stale_account_version
        """
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        observed = get_account_version(account_id)

        resp = api_client.create_case(
            create_case_payload(account_id, observed), TEST_USERS["analyst_headers"]
        )
        validate_success(resp, expected_status=201)

        resp = api_client.create_case(
            create_case_payload(account_id, observed), TEST_USERS["analyst_headers"]
        )
        error = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert error["error_id"] == "ERR_STALE_VERSION"
        assert resp.status_code == 412

        account = get_account(account_id)
        assert account["version"] == observed + 1, (
            "only the first case create may land on the account"
        )
        assert account["open_case_count"] == 1


class TestAnalystCannotFileSar:
    def test_analyst_role_denied_on_file(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is
        rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: `POST /aml/sar-filings/{id}/file` is authorized for `SAROfficer` —
        filing is organizationally segregated from the investigating analysts (§2.1).
        The filing stays DRAFT.

        Design: Corner/rbac/analyst_cannot_file_sar
        """
        ctx = setup_case_in_state(
            "SAR_RECOMMENDED", detection_date="2026-05-01", analyst_id="analyst-b2"
        )
        sar = create_sar_filing(ctx["case"]["id"], sar_officer_id="saroff-b2")
        resp = api_client.file_sar(sar["id"], make_analyst_headers("analyst-b2x"))
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert error["error_id"] == "ERR_UNAUTHORIZED_ROLE"
        assert resp.status_code == 403
        assert get_sar_filing(sar["id"])["status"] == "DRAFT"


class TestSarFilingSodSameIdentityRejected:
    def test_filer_identity_equal_to_recommender_rejected(self, api):
        """PRD §2.10: "The SAR officer who files a SAR must not be the analyst who
        recommended it: filing compares `X-User-ID` to the case's
        `recommending_analyst_id`, and equality is rejected with `ERR_SOD_VIOLATION`."
        Even holding the SAROfficer role, the recommending identity cannot file; a
        distinct SAROfficer identity files successfully.

        Design: Corner/rbac/sar_filing_sod_same_identity_rejected
        """
        ctx = setup_case_in_state(
            "SAR_RECOMMENDED", detection_date="2026-05-01", analyst_id="analyst-sod"
        )
        sar = create_sar_filing(ctx["case"]["id"], sar_officer_id="saroff-b4")

        resp = api_client.file_sar(sar["id"], make_sar_officer_headers("analyst-sod"))
        error = validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert error["error_id"] == "ERR_SOD_VIOLATION"
        assert resp.status_code == 403

        resp = api_client.file_sar(sar["id"], make_sar_officer_headers("saroff-b4"))
        filed = validate_success(resp)
        assert filed["status"] == "FILED"


class TestMatchConfirmTwiceRejected:
    def test_second_confirm_rejected_and_cascade_does_not_refire(self, api):
        """PRD §3.7: "Match disposition belongs to the `ComplianceOfficer`, and all
        three dispositions require `PENDING_REVIEW` (or, for resolution, `CONFIRMED`) —
        anything else yields `ERR_MATCH_NOT_REVIEWABLE`."
        The first confirm fires the restriction cascade once (one FINCEN_314A_MATCH
        alert for the flagged wire); the second confirm is rejected and creates nothing
        new.

        Design: Corner/state_machines/match_confirm_twice_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_scanned_314a_match()
        post_wire(ctx["account"]["id"], ctx["rep"], 500.00)
        resp = api_client.confirm_match(ctx["match"]["id"], TEST_USERS["officer_headers"])
        validate_success(resp)

        resp = api_client.confirm_match(ctx["match"]["id"], TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_MATCH_NOT_REVIEWABLE)
        assert error["error_id"] == "ERR_MATCH_NOT_REVIEWABLE"

        alerts = list_alerts_for_account(ctx["account"]["id"])
        assert len(alerts) == 1, (
            f"the cascade must not fire twice; found {len(alerts)} alerts"
        )


class TestMatchResolveDropsSeverePosture:
    def test_resolve_clears_severe_and_allows_reinstate(self, api):
        """PRD §3.3: "Reinstatement returns a `RESTRICTED` account to `OPEN`, but only
        while no 314(a) match for the account remains in `CONFIRMED`
        (`ERR_MATCH_314A_UNRESOLVED`)".
        PRD §3.7: "Resolution moves `CONFIRMED` → `RESOLVED` and recomputes posture,
        which may relax from `SEVERE` once no `CONFIRMED` matches remain."
        With no other elevation trigger on this LOW account, posture falls to STANDARD
        and reinstatement succeeds.

        Design: Corner/validations/match_resolve_drops_severe_posture
        """
        ctx = setup_scanned_314a_match(confirmed=True)
        account_id = ctx["account"]["id"]
        assert get_account(account_id)["aml_posture"] == "SEVERE"

        resp = api_client.reinstate_account(account_id, TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_MATCH_314A_UNRESOLVED)
        assert error["error_id"] == "ERR_MATCH_314A_UNRESOLVED"

        resp = api_client.resolve_match(ctx["match"]["id"], TEST_USERS["officer_headers"])
        validate_success(resp)
        assert get_account(account_id)["aml_posture"] == "STANDARD", (
            "no CONFIRMED matches remain and no elevation trigger exists"
        )

        resp = api_client.reinstate_account(account_id, TEST_USERS["officer_headers"])
        reinstated = validate_success(resp)
        assert reinstated["lifecycle_status"] == "OPEN"


class TestFincenResponseIncompleteRejected:
    def test_unresolved_match_blocks_response_then_resolved_allows(self, api):
        """PRD §3.7: "a `ComplianceOfficer` submits the response, but only once every
        match of the request sits in `FALSE_POSITIVE` or `RESOLVED`; otherwise
        `ERR_FINCEN_RESPONSE_INCOMPLETE`. Submission stamps `responded_at`, computes
        `responded_late` as true exactly when the responded date is later than the
        `response_deadline`".
        Received 2026-05-01 -> deadline 2026-05-15; submitted 2026-05-10 is not late.

        Design: Corner/validations/fincen_response_incomplete_rejected
        """
        ctx = setup_scanned_314a_match()
        request_id = ctx["request"]["id"]
        set_clock("2026-05-10T00:00:00Z")

        resp = api_client.submit_fincen_response(request_id, TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_FINCEN_RESPONSE_INCOMPLETE)
        assert error["error_id"] == "ERR_FINCEN_RESPONSE_INCOMPLETE"

        resp = api_client.mark_false_positive(
            ctx["match"]["id"], {"rationale": "name coincidence"},
            TEST_USERS["officer_headers"],
        )
        validate_success(resp)

        resp = api_client.submit_fincen_response(request_id, TEST_USERS["officer_headers"])
        submitted = validate_success(resp)
        assert submitted["status"] == "RESPONSE_SUBMITTED"
        assert submitted["responded_late"] is False
