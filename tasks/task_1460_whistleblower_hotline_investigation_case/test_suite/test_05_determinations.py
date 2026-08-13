"""Determination lifecycle: draft OCC + supersede, submit gates, review outcomes, SoD."""
from test_helpers import (
    ApiErrorId,
    activate_assignment,
    add_conducted_interview,
    add_determination,
    add_sealed_evidence,
    create_case,
    create_determination_payload,
    create_evidence_payload,
    create_interview_payload,
    create_review_payload,
    create_staff,
    get_case,
    make_intake_headers,
    make_investigator_headers,
    make_officer_headers,
    propose_assignment_auto,
    review_approve,
    screen_clear,
    setup_case_determination_review,
    setup_case_under_investigation,
    setup_case_triaged,
    submit_determination,
    triage_case,
    validate_error,
    validate_success,
    api_client,
)


class TestDeterminationDraftOCC:
    def test_stale_version_on_draft_returns_412(self, api):
        """PRD §2.8: "When creating a determination draft for a case, the request must
        likewise carry `expected_case_version` ... rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/validations/occ_determination_draft_stale_version_returns_412
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        v = get_case(ctx["case"]["id"], staff["h_off"])["version"]
        d1 = add_determination(ctx, finding="INCONCLUSIVE",
                               rationale="First draft written against the initially observed case version.")
        resp = api.create_determination(ctx["case"]["id"], create_determination_payload(
            v, finding="UNSUBSTANTIATED",
            rationale="Second writer still carrying the pre-draft case version value.",
        ), staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_failed_stale_call_does_not_supersede_prior_draft(self, api):
        """PRD §2.4: "every mutation in this system is applied atomically within the
        request that triggered it" — the rejected draft leaves the existing DRAFT
        untouched (no supersede side effect).

        Design: Corner/validations/occ_determination_draft_stale_version_returns_412
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        v = get_case(ctx["case"]["id"], staff["h_off"])["version"]
        d1 = add_determination(ctx, finding="INCONCLUSIVE",
                               rationale="First draft written against the initially observed case version.")
        api.create_determination(ctx["case"]["id"], create_determination_payload(
            v, finding="UNSUBSTANTIATED",
            rationale="Second writer still carrying the pre-draft case version value.",
        ), staff["h_inv"])
        resp = api.get_determination(d1["id"], staff["h_off"])
        assert validate_success(resp)["status"] == "DRAFT"

    def test_new_draft_supersedes_prior_draft(self, api):
        """PRD §3.6: "Creating it moves any existing `DRAFT` determination of the
        case to `SUPERSEDED`".

        Design: Corner/state_machines/determination_new_draft_supersedes_prior_draft
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        d1 = add_determination(ctx, finding="INCONCLUSIVE",
                               rationale="First draft was incomplete and is being reworked by the investigator.")
        d2 = add_determination(ctx, finding="UNSUBSTANTIATED",
                               rationale="Second draft supersedes the first with a complete evidence review.")
        assert d2["status"] == "DRAFT"
        resp = api.list_determinations(ctx["case"]["id"], staff["h_off"])
        rows = resp.json()["data"]
        by_id = {r["id"]: r for r in rows}
        assert by_id[d1["id"]]["status"] == "SUPERSEDED"
        assert by_id[d2["id"]]["status"] == "DRAFT"
        drafts = [r for r in rows if r["status"] == "DRAFT"]
        assert len(drafts) == 1


class TestSubmitGates:
    def test_submit_without_conducted_interview_rejected(self, api):
        """PRD §3.6: "at least one interview of the case must have reached
        `CONDUCTED` (`ERR_NO_CONDUCTED_INTERVIEW`)".

        Design: Corner/state_machines/submit_without_conducted_interview_returns_no_conducted_interview
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        # SCHEDULED but not concluded interview
        api.create_interview(create_interview_payload(ctx["case"]["id"]), staff["h_inv"])
        add_sealed_evidence(ctx)
        det = add_determination(ctx)
        resp = api.submit_determination(det["id"], staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_NO_CONDUCTED_INTERVIEW)

    def test_submit_with_unsealed_evidence_rejected(self, api):
        """PRD §3.6: "no evidence item of the case may still be `PRESERVED`
        (`ERR_UNSEALED_EVIDENCE`)".

        Design: Corner/state_machines/submit_with_unsealed_evidence_returns_unsealed_evidence
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        add_conducted_interview(ctx)
        # PRESERVED (unsealed) evidence
        api.create_evidence_item(create_evidence_payload(
            ctx["case"]["id"], evidence_type="PHOTO", description="Warehouse floor photo",
            checksum="d" * 64,
        ), staff["h_inv"])
        det = add_determination(ctx)
        resp = api.submit_determination(det["id"], staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_UNSEALED_EVIDENCE)

    def test_submit_twice_returns_not_draft(self, api):
        """PRD §3.6: "submitting from any other state fails with
        `ERR_DETERMINATION_NOT_DRAFT`".

        Design: Corner/errors/submit_twice_returns_not_draft
        """
        ctx = setup_case_determination_review()
        staff = ctx["staff"]
        resp = api.submit_determination(ctx["determination"]["id"], staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_DRAFT)


class TestReview:
    def test_review_draft_rejected(self, api):
        """PRD §3.6: "applies to a `SUBMITTED` determination
        (`ERR_DETERMINATION_NOT_SUBMITTED`)".

        Design: Corner/errors/review_draft_determination_rejected
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        det = add_determination(ctx, finding="INCONCLUSIVE",
                                rationale="Draft pending interviews; review attempted prematurely here.")
        resp = api.review_determination(det["id"], create_review_payload(
            decision="APPROVE", review_notes="Premature review.",
            notice_summary="Case closed with no findings disclosed.",
        ), staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_SUBMITTED)

    def test_self_review_rejected_for_dual_capability_staff(self, api):
        """PRD §3.6: "Review belongs to a `ComplianceOfficer` who is not the decider
        (`ERR_SOD_SELF_REVIEW`)".

        Design: Corner/errors/sod_self_review_by_dual_capability_staff
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        s_off2 = create_staff("Oscar Officer", "officer2@corp.example", ["OFFICER"])
        s_dual = create_staff("Dana Dual", "dual@corp.example", ["INVESTIGATION", "OFFICER"])
        case, _ = create_case()
        triaged = triage_case(case["id"], make_intake_headers(s_int["id"]))
        # override assignment to dual, screen by intake, activate by off2
        resp = api.create_assignment(case["id"], {
            "expected_case_version": triaged["version"], "investigator_id": s_dual["id"],
            "override_reason": "Dual-capacity staffing",
        }, make_officer_headers(s_off2["id"]))
        a1 = validate_success(resp, expected_status=201)
        api.screen_assignment(a1["id"], {"outcome": "CLEAR"}, make_intake_headers(s_int["id"]))
        api.activate_assignment(a1["id"], make_officer_headers(s_off2["id"]))
        h_dual_inv = make_investigator_headers(s_dual["id"])
        iv = validate_success(api.create_interview(
            create_interview_payload(case["id"]), h_dual_inv), expected_status=201)
        api.conclude_interview(iv["id"], {"outcome": "CONDUCTED",
                                          "summary": "Interview conducted on site with the witness present throughout."},
                               h_dual_inv)
        ev = validate_success(api.create_evidence_item(
            create_evidence_payload(case["id"]), h_dual_inv), expected_status=201)
        api.seal_evidence(ev["id"], make_intake_headers(s_int["id"]))
        v = get_case(case["id"], make_officer_headers(s_off2["id"]))["version"]
        det = validate_success(api.create_determination(case["id"], create_determination_payload(v),
                                                        h_dual_inv), expected_status=201)
        api.submit_determination(det["id"], h_dual_inv)
        # dual (decider) reviews as officer -> SoD self-review
        resp2 = api.review_determination(det["id"], create_review_payload(
            decision="APPROVE", review_notes="Reviewing my own draft.",
            notice_summary="Case closed with no findings disclosed.",
        ), make_officer_headers(s_dual["id"]))
        validate_error(resp2, ApiErrorId.ERR_SOD_SELF_REVIEW)

    def test_intake_cannot_review_determination(self, api):
        """PRD §2.1: "If the role is valid but not permitted for the target endpoint,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.11: "Second, whether the role is permitted for the endpoint at all
        (`ERR_INSUFFICIENT_PERMISSIONS`)". (PRD §4 authorizes only
        ComplianceOfficer for determination review.)

        Design: Corner/rbac/intake_cannot_review_determination
        """
        s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
        resp = api.review_determination("33333333-3333-3333-3333-333333333333",
                                        create_review_payload(
                                            decision="APPROVE", review_notes="Role probe review.",
                                            notice_summary="Case closed with no findings disclosed."),
                                        make_intake_headers(s_int["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestDualRevertLoops:
    """Difficulty: case_dual_revert_loops (2 tests)."""

    def _traverse_loops(self, api):
        """Case goes ASSIGNED->TRIAGED via release, then DETERMINATION_REVIEW->
        UNDER_INVESTIGATION via RETURN, then fresh draft submitted."""
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        # loop 1
        a1 = propose_assignment_auto(ctx["case"]["id"], ctx["case"]["version"], staff["h_int"])
        api.release_assignment(a1["id"], staff["h_off"])
        case_after_release = get_case(ctx["case"]["id"], staff["h_off"])
        # re-assign and proceed
        a2 = propose_assignment_auto(ctx["case"]["id"], case_after_release["version"], staff["h_int"])
        screen_clear(a2["id"], staff["h_int"])
        activate_assignment(a2["id"], staff["h_off"])
        ctx["case"] = get_case(ctx["case"]["id"], staff["h_off"])
        add_conducted_interview(ctx)
        add_sealed_evidence(ctx)
        d1 = add_determination(ctx)
        submit_determination(ctx, d1["id"])
        # loop 2: RETURN
        api.review_determination(d1["id"], create_review_payload(decision="RETURN",
                                                                 review_notes="Needs more analysis."),
                                 staff["h_off"])
        case_after_return = get_case(ctx["case"]["id"], staff["h_off"])
        d2 = add_determination(ctx, rationale="Re-reviewed evidence confirms the allegation remains unsupported overall.")
        submit_determination(ctx, d2["id"])
        return ctx, case_after_release, case_after_return, d1, d2

    def test_release_and_return_loops_restore_prior_states(self, api):
        """PRD §3.4: "Release unwinds an assignment and always returns the case to
        `TRIAGED`." PRD §3.6: "A `RETURN` decision moves the determination to
        `RETURNED`, sends the case back to `UNDER_INVESTIGATION`".

        Design: Difficulty/non_linear_state_machine/case_dual_revert_loops
        """
        ctx, after_release, after_return, d1, _d2 = self._traverse_loops(api)
        assert after_release["status"] == "TRIAGED"
        assert after_return["status"] == "UNDER_INVESTIGATION"
        resp = api.get_determination(d1["id"], ctx["staff"]["h_off"])
        assert validate_success(resp)["status"] == "RETURNED"

    def test_case_completes_to_closure_ready_after_both_loops(self, api):
        """PRD §3.6: "An `APPROVE` decision on an `UNSUBSTANTIATED` or `INCONCLUSIVE`
        finding moves the determination to `APPROVED` ... and moves the case
        directly to `CLOSURE_READY`".

        Design: Difficulty/non_linear_state_machine/case_dual_revert_loops
        """
        ctx, _ar, _aret, _d1, d2 = self._traverse_loops(api)
        review_approve(ctx, d2["id"])
        case = get_case(ctx["case"]["id"], ctx["staff"]["h_off"])
        assert case["status"] == "CLOSURE_READY"
        events = api.list_case_status_events(ctx["case"]["id"], ctx["staff"]["h_off"]).json()["data"]
        types = {e["event_type"] for e in events}
        assert "ASSIGNMENT_RELEASED" in types
        assert "DETERMINATION_RETURNED" in types
