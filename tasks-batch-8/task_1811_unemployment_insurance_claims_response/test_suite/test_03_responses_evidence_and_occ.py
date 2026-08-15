"""Response drafting, documentation assembly scoring, submission gates,
amendment supersession, coding confirmation, and claim-level OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attach_evidence,
    create_claim,
    create_employer,
    create_separation,
    create_state_rule,
    draft_response,
    get_claim,
    get_response,
    get_separation,
    get_success_data,
    set_clock,
    submit_response,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["claims_analyst_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]


class TestCompletenessScoreDualOutcome:
    def _setup_two_claims_with_incident_reports(self, api):
        """Two identical misconduct claims; claim1's incident report is
        authenticated, claim2's is not."""
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="DocCo")
        separation = create_separation(employer["id"],
                                       separation_reason="DISCHARGE_MISCONDUCT")
        claim1, resp1 = self._draft_with_report(employer, separation, True)
        claim2, resp2 = self._draft_with_report(employer, separation, False)
        return employer, separation, claim1, resp1, claim2, resp2

    def _draft_with_report(self, employer, separation, authenticated):
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="PROTEST",
                              separation_reason_code="DISCHARGE_MISCONDUCT",
                              narrative="Terminated for cause per attached incident report.")
        attach_evidence(claim["id"], resp["id"],
                        doc_category="FINAL_INCIDENT_REPORT",
                        doc_date="2026-07-29T00:00:00Z",
                        authenticated=authenticated)
        return claim, resp

    def test_authentication_flag_diverges_completeness_score(self, api):
        """PRD §3.4: "Each document's contribution is its category's base
        weight — 25 for `WRITTEN_WARNING`, 20 for `SIGNED_POLICY`, 30 for
        `FINAL_INCIDENT_REPORT`, 15 for `ATTENDANCE_RECORD`, 10 for
        `PERFORMANCE_REVIEW`, 25 for `RESIGNATION_LETTER`, and 5 for `OTHER` —
        plus 10 points when the document is authenticated, minus 5 points when
        its `doc_date` is later than the claim's `notice_received_at`, a
        post-hoc discount."

        Design: Difficulty/dual_variant_calc/completeness_score_category_presence_vs_absence
        """
        _emp, _sep, _c1, resp1, _c2, resp2 = \
            self._setup_two_claims_with_incident_reports(api)
        # Authenticated incident report: 30 base + 10 authenticated = 40.
        assert get_response(resp1["id"])["completeness_score"] == 40
        # Unauthenticated incident report: 30 base only.
        assert get_response(resp2["id"])["completeness_score"] == 30

    def test_submit_gate_accepts_40_rejects_30(self, api):
        """PRD §3.4: "its `completeness_score` must be at least 40 (otherwise
        `ERR_RESPONSE_INCOMPLETE`)"

        Design: Difficulty/dual_variant_calc/completeness_score_category_presence_vs_absence
        """
        _emp, _sep, claim1, resp1, claim2, resp2 = \
            self._setup_two_claims_with_incident_reports(api)

        submitted = submit_response(claim1["id"], resp1["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["timeliness"] == "ON_TIME"

        version = get_claim(claim2["id"])["version"]
        resp = api.submit_response(claim2["id"], resp2["id"], version, ANALYST)
        validate_error(resp, ApiErrorId.ERR_RESPONSE_INCOMPLETE, 422)
        assert get_response(resp2["id"])["status"] == "DRAFT"


class TestDocumentationAssemblyScore:
    def test_category_best_counts_once(self, api):
        """PRD §3.4: "Within each category only the single best-scoring
        document contributes. The raw score is the sum of those per-category
        bests across the categories present, and the response's
        `completeness_score` is that raw sum capped at 100."

        Design: Corner/calculations/documentation_score_category_best_and_posthoc_discount
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="ScoreCo")
        separation = create_separation(employer["id"],
                                       separation_reason="DISCHARGE_MISCONDUCT")
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="PROTEST",
                              separation_reason_code="DISCHARGE_MISCONDUCT")
        # WRITTEN_WARNING category: authenticated 25+10=35 beats unauthenticated 25.
        attach_evidence(claim["id"], resp["id"], doc_category="WRITTEN_WARNING",
                        doc_date="2026-06-01T00:00:00Z", authenticated=True)
        attach_evidence(claim["id"], resp["id"], doc_category="WRITTEN_WARNING",
                        doc_date="2026-06-15T00:00:00Z", authenticated=False)
        # SIGNED_POLICY: unauthenticated, dated before the notice -> 20.
        attach_evidence(claim["id"], resp["id"], doc_category="SIGNED_POLICY",
                        doc_date="2026-01-10T00:00:00Z", authenticated=False)

        assert get_response(resp["id"])["completeness_score"] == 55

    def test_post_hoc_document_takes_discount(self, api):
        """PRD §3.4: "plus 10 points when the document is authenticated, minus
        5 points when its `doc_date` is later than the claim's
        `notice_received_at`, a post-hoc discount."

        Design: Corner/calculations/documentation_score_category_best_and_posthoc_discount
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="PostHocCo")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"],
                             notice_received_at="2026-08-03T09:00:00Z")
        resp = draft_response(claim["id"], response_type="PROTEST")
        # PERFORMANCE_REVIEW authenticated but created after the notice:
        # 10 base + 10 authenticated - 5 post-hoc = 15.
        attach_evidence(claim["id"], resp["id"], doc_category="PERFORMANCE_REVIEW",
                        doc_date="2026-08-04T00:00:00Z", authenticated=True)

        assert get_response(resp["id"])["completeness_score"] == 15

    def test_delete_evidence_recomputes_score(self, api):
        """PRD §3.4: "Each attachment and each removal (removal restricted to
        `ClaimsAnalyst`, returning 204 with no data) recomputes the
        documentation assembly score on the referenced response — or, when
        `response_id` is omitted, on the claim's latest `DRAFT` response"

        Design: Corner/endpoints/delete_evidence_recomputes_score
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="DelCo")
        separation = create_separation(employer["id"],
                                       separation_reason="DISCHARGE_MISCONDUCT")
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="PROTEST",
                              separation_reason_code="DISCHARGE_MISCONDUCT")
        doc = attach_evidence(claim["id"], resp["id"])
        assert get_response(resp["id"])["completeness_score"] == 40

        delete_resp = api.delete_evidence(doc["id"], ANALYST)
        assert delete_resp.status_code == 204
        assert get_response(resp["id"])["completeness_score"] == 0


class TestSubmissionGatesAndOcc:
    def test_double_submit_rejected_idempotency(self, api):
        """PRD §3.4: "The response must still be `DRAFT` (otherwise
        `ERR_RESPONSE_NOT_DRAFT`)"
        PRD §3.4: "On submission the server stamps `filed_at` from the logical
        clock and computes `timeliness`"

        Design: Corner/state_machines/double_submit_rejected_idempotency
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="IdemCo")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="NO_PROTEST",
                              narrative="n")
        attach_evidence(claim["id"], resp["id"])

        set_clock("2026-08-04T09:00:00Z")
        submitted = submit_response(claim["id"], resp["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["filed_at"] == "2026-08-04T09:00:00Z"

        version = get_claim(claim["id"])["version"]
        err = api.submit_response(claim["id"], resp["id"], version, ANALYST)
        validate_error(err, ApiErrorId.ERR_RESPONSE_NOT_DRAFT, 409)
        after = get_response(resp["id"])
        assert after["status"] == "SUBMITTED"
        assert after["filed_at"] == "2026-08-04T09:00:00Z"
        assert after["timeliness"] == "ON_TIME"

    def test_occ_stale_claim_version_rejected(self, api):
        """PRD §2.9: "requires `expected_claim_version` carrying the client's
        last observed `version` of the parent claim. A drafter who loaded the
        claim before a colleague attached new evidence — an attachment that
        itself bumps the claim's version — holds a stale version and must
        re-read the claim before filing."
        PRD §2.9: "if the value does not match the parent entity's current
        `version` — because another writer has advanced that version since the
        client last read the parent — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_claim_version_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="OccCo")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="NO_PROTEST",
                              narrative="n")
        stale_version = get_claim(claim["id"])["version"]
        # Attaching evidence recomputes the score and bumps the claim version.
        attach_evidence(claim["id"], resp["id"])

        err = api.submit_response(claim["id"], resp["id"], stale_version, ANALYST)
        validate_error(err, ApiErrorId.ERR_STALE_VERSION, 412)
        assert get_response(resp["id"])["status"] == "DRAFT"


class TestAcceptanceSupersession:
    def test_response_accept_supersedes_sibling_draft(self, api):
        """PRD §3.4: "Acceptance moves the response to `ACCEPTED` and
        supersedes every other `SUBMITTED` or `DRAFT` response on the same
        claim — including the earlier response an accepted amendment named in
        `amendment_of`, which moves from `SUBMITTED` to `SUPERSEDED`."
        PRD §3.4: "from `RESPONSE_SUBMITTED` only an amendment (one with
        `amendment_of` set) may be drafted."

        Design: Corner/state_machines/response_accept_supersedes_sibling_draft
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="SupCo")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"])
        resp1 = draft_response(claim["id"], response_type="NO_PROTEST",
                               narrative="first")
        attach_evidence(claim["id"], resp1["id"])
        submit_response(claim["id"], resp1["id"])
        assert get_claim(claim["id"])["status"] == "RESPONSE_SUBMITTED"

        resp2 = draft_response(claim["id"], response_type="PROTEST",
                               narrative="amended", amendment_of=resp1["id"])
        assert resp2["status"] == "DRAFT"

        accepted = validate_success(
            api.accept_response(claim["id"], resp1["id"], LIAISON), 200)
        assert accepted["status"] == "ACCEPTED"
        assert get_response(resp2["id"])["status"] == "SUPERSEDED"


class TestCodingConfirmationGate:
    def test_misconduct_coding_confirm_without_evidence_rejected(self, api):
        """PRD §3.2: "when the reason is `DISCHARGE_MISCONDUCT`, at least one
        evidence document in the `WRITTEN_WARNING`, `SIGNED_POLICY`, or
        `FINAL_INCIDENT_REPORT` category must already be attached to some claim
        referencing that separation, or the confirmation is rejected with
        `ERR_CODING_EVIDENCE_MISSING`."

        Design: Corner/validations/misconduct_coding_confirm_without_evidence_rejected
        """
        employer = create_employer(legal_name="CodeCo")
        sep_m = create_separation(employer["id"], claimant_name="Uli",
                                  ssn_last4="1019",
                                  separation_reason="DISCHARGE_MISCONDUCT")
        sep_l = create_separation(employer["id"], claimant_name="Vic",
                                  ssn_last4="1020", separation_reason="LAYOFF")

        err = api.confirm_coding(sep_m["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_CODING_EVIDENCE_MISSING, 422)
        assert get_separation(sep_m["id"])["reason_coding_confidence"] == "UNREVIEWED"

        confirmed = validate_success(api.confirm_coding(sep_l["id"], ANALYST), 200)
        assert confirmed["reason_coding_confidence"] == "CONFIRMED"
