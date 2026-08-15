"""Accreditation citations and the annual survey: the survey-close citation
cascade, derived program accreditation status and its thresholds, the
complement-approval gate, and the citation response/re-response workflow
(PRD §3.9)."""
from test_helpers import (
    DIO, PD, ApiClient, ApiErrorId, close_survey_payload, list_citations,
    make_citation, make_complement, make_program, make_survey, make_year,
    respond_and_resolve_citation, validate_error, validate_success,
)


def _program_status(api, program_id):
    return validate_success(api.get_program(program_id, DIO))[
        "accreditation_status"]


class TestSurveyCloseCascade:
    def _setup(self, api):
        program = make_program()
        year = make_year(program["id"])
        comp = make_complement(program["id"], year["id"], approve=False)
        validate_success(api.submit_complement(comp["id"], PD))
        survey = make_survey(program["id"], year["id"])
        return program, year, comp, survey

    def test_close_creates_flagged_area_citations(self, api: ApiClient):
        """PRD §3.9: "On close the survey moves to `CLOSED`, the computed
        `flagged_area_count` records how many `area_results` entries fell below
        70.00 compliance, and the citation cascade fires. A
        `resident_response_rate` below 70.00 auto-creates a citation with
        `area_code` `RESPONSE_RATE`, severity `WARNING`, the survey's
        `annual_survey_id` set, and a `citation_code` of
        `SURVEY-RESPONSE_RATE-<year_label>`."
        PRD §3.9: "Each flagged area auto-creates a citation with that area's
        `area_code`, a `citation_code` of `SURVEY-<area_code>-<year_label>`,
        the survey's `annual_survey_id`, and a severity that depends on the
        breadth of the problem: `SERIOUS` when the `flagged_area_count` is 3 or
        more, otherwise `WARNING`."

        Design: Difficulty/transitive_cascade/survey_close_citation_program_status_cascade
        """
        program, year, _, survey = self._setup(api)
        closed = validate_success(api.close_survey(
            survey["id"],
            close_survey_payload(
                resident_response_rate=69.99, faculty_response_rate=90.00,
                area_results=[
                    {"area_code": "DUTY_HOURS", "compliance_pct": 60.00},
                    {"area_code": "EVALUATION", "compliance_pct": 55.00},
                    {"area_code": "CASE_LOGS", "compliance_pct": 65.00},
                    {"area_code": "SUPERVISION", "compliance_pct": 95.00},
                ]), DIO))
        assert closed["status"] == "CLOSED"
        assert closed["flagged_area_count"] == 3

        citations, meta = list_citations(program_id=program["id"])
        assert meta["total_count"] == 4  # 3 flagged areas + 1 response rate
        by_code = {c["citation_code"]: c for c in citations}
        for area in ("DUTY_HOURS", "EVALUATION", "CASE_LOGS"):
            cit = by_code[f"SURVEY-{area}-2026-2027"]
            assert cit["area_code"] == area
            assert cit["severity"] == "SERIOUS"   # flagged_area_count 3 >= 3
            assert cit["annual_survey_id"] == survey["id"]
            assert cit["status"] == "OPEN"
        rr = by_code["SURVEY-RESPONSE_RATE-2026-2027"]
        assert rr["area_code"] == "RESPONSE_RATE"
        assert rr["severity"] == "WARNING"
        assert rr["annual_survey_id"] == survey["id"]

    def test_derived_probationary_gates_complement_approval(self, api: ApiClient):
        """PRD §3.9: "with two or more unresolved `SERIOUS` citations the
        program is `PROBATIONARY`; with exactly one it is
        `CONTINUED_WITH_WARNING`; with none it is `CONTINUED`."
        PRD §3.2: "approval is barred while the program's
        `accreditation_status` is `PROBATIONARY`, surfacing
        `ERR_PROGRAM_PROBATIONARY` (HTTP 403)".

        Design: Difficulty/transitive_cascade/survey_close_citation_program_status_cascade
        """
        program, year, comp, survey = self._setup(api)
        validate_success(api.close_survey(
            survey["id"],
            close_survey_payload(
                resident_response_rate=69.99, faculty_response_rate=90.00,
                area_results=[
                    {"area_code": "DUTY_HOURS", "compliance_pct": 60.00},
                    {"area_code": "EVALUATION", "compliance_pct": 55.00},
                    {"area_code": "CASE_LOGS", "compliance_pct": 65.00},
                    {"area_code": "SUPERVISION", "compliance_pct": 95.00},
                ]), DIO))
        # 3 unresolved SERIOUS >= 2 -> PROBATIONARY.
        assert _program_status(api, program["id"]) == "PROBATIONARY"

        resp = api.approve_complement(comp["id"], DIO)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_PROBATIONARY)
        assert resp.status_code == 403
        assert validate_success(api.get_complement(comp["id"], PD))[
            "status"] == "SUBMITTED"


class TestSurveyResponseRateBoundary:
    def test_exactly_70_creates_no_citation(self, api: ApiClient):
        """PRD §3.9: "A `resident_response_rate` below 70.00 auto-creates a
        citation with `area_code` `RESPONSE_RATE`, severity `WARNING`" — and
        "the computed `flagged_area_count` records how many `area_results`
        entries fell below 70.00 compliance" (70.00 is not below 70.00).

        Design: Difficulty/boundary_precision_check/survey_response_rate_exact_boundary
        """
        program = make_program()
        year = make_year(program["id"])
        survey = make_survey(program["id"], year["id"])
        closed = validate_success(api.close_survey(
            survey["id"],
            close_survey_payload(
                resident_response_rate=70.00, faculty_response_rate=100.00,
                area_results=[
                    {"area_code": "DUTY_HOURS", "compliance_pct": 70.00},
                    {"area_code": "EVALUATION", "compliance_pct": 100.00},
                ]), DIO))
        assert closed["status"] == "CLOSED"
        assert closed["flagged_area_count"] == 0
        _, meta = list_citations(program_id=program["id"])
        assert meta["total_count"] == 0
        assert _program_status(api, program["id"]) == "CONTINUED"

    def test_just_below_70_creates_warning_citation(self, api: ApiClient):
        """PRD §3.9: "A `resident_response_rate` below 70.00 auto-creates a
        citation with `area_code` `RESPONSE_RATE`, severity `WARNING`, the
        survey's `annual_survey_id` set, and a `citation_code` of
        `SURVEY-RESPONSE_RATE-<year_label>`."

        Design: Difficulty/boundary_precision_check/survey_response_rate_exact_boundary
        """
        program = make_program()
        year = make_year(program["id"])
        survey = make_survey(program["id"], year["id"])
        closed = validate_success(api.close_survey(
            survey["id"],
            close_survey_payload(
                resident_response_rate=69.99, faculty_response_rate=100.00,
                area_results=[
                    {"area_code": "DUTY_HOURS", "compliance_pct": 70.00},
                ]), DIO))
        assert closed["flagged_area_count"] == 0
        citations, meta = list_citations(program_id=program["id"])
        assert meta["total_count"] == 1
        cit = citations[0]
        assert cit["citation_code"] == "SURVEY-RESPONSE_RATE-2026-2027"
        assert cit["area_code"] == "RESPONSE_RATE"
        assert cit["severity"] == "WARNING"
        assert cit["annual_survey_id"] == survey["id"]
        # A WARNING citation never moves the program off CONTINUED.
        assert _program_status(api, program["id"]) == "CONTINUED"


class TestComplementApprovalProbationaryGate:
    def _setup(self, api):
        program = make_program()
        year = make_year(program["id"])
        comp = make_complement(program["id"], year["id"], approve=False)
        validate_success(api.submit_complement(comp["id"], PD))
        c1 = make_citation(program["id"], citation_code="IV.A.1",
                           area_code="SUPERVISION")
        c2 = make_citation(program["id"], citation_code="III.B.3",
                           area_code="DUTY_HOURS")
        return program, comp, c1, c2

    def test_two_open_serious_citations_block_approval(self, api: ApiClient):
        """PRD §3.9: "with two or more unresolved `SERIOUS` citations the
        program is `PROBATIONARY`" and "Because the pipeline of §2.8 gates
        complement approval on this figure, a program that falls to
        `PROBATIONARY` cannot approve complement rows until its citations are
        worked down (`ERR_PROGRAM_PROBATIONARY`)."

        Design: Difficulty/cross_entity_state_dependency/complement_approve_blocked_when_program_probationary
        """
        program, comp, _, _ = self._setup(api)
        assert _program_status(api, program["id"]) == "PROBATIONARY"
        resp = api.approve_complement(comp["id"], DIO)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_PROBATIONARY)
        assert resp.status_code == 403
        assert validate_success(api.get_complement(comp["id"], PD))[
            "status"] == "SUBMITTED"

    def test_resolving_citations_restores_approval(self, api: ApiClient):
        """PRD §3.9: "resolving the last unresolved `SERIOUS` citation drops
        the program back out of its warning or probationary band".

        Design: Difficulty/cross_entity_state_dependency/complement_approve_blocked_when_program_probationary
        """
        program, comp, c1, c2 = self._setup(api)
        respond_and_resolve_citation(c1["id"])
        respond_and_resolve_citation(c2["id"])
        assert _program_status(api, program["id"]) == "CONTINUED"
        approved = validate_success(api.approve_complement(comp["id"], DIO))
        assert approved["status"] == "APPROVED"


class TestCitationResponseCycle:
    def _setup(self, api):
        program = make_program()
        citation = make_citation(program["id"], citation_code="IV.A.2",
                                 severity="SERIOUS", area_code="DUTY_HOURS")
        return program, citation

    def test_program_status_tracks_unresolved_serious(self, api: ApiClient):
        """PRD §3.9: "Unresolved means every status except `RESOLVED`, and the
        program's computed `accreditation_status` derives from the unresolved
        serious set: with two or more unresolved `SERIOUS` citations the
        program is `PROBATIONARY`; with exactly one it is
        `CONTINUED_WITH_WARNING`; with none it is `CONTINUED`."

        Design: Difficulty/non_linear_state_machine/citation_escalation_re_response_cycle
        """
        program, citation = self._setup(api)
        assert _program_status(api, program["id"]) == "CONTINUED_WITH_WARNING"

        validate_success(api.draft_citation_response(
            citation["id"], {"response_text": "Root cause: schedule template."},
            PD))
        validate_success(api.submit_citation_response(citation["id"], PD))
        # Escalated is still unresolved.
        validate_success(api.escalate_citation(
            citation["id"],
            {"escalation_reason": "Site visitor found response inadequate"},
            DIO))
        assert _program_status(api, program["id"]) == "CONTINUED_WITH_WARNING"

        # Re-response cycle then resolution drops the program back.
        validate_success(api.draft_citation_response(
            citation["id"],
            {"response_text": "Revised plan with quarterly audits."}, PD))
        validate_success(api.submit_citation_response(citation["id"], PD))
        validate_success(api.resolve_citation(
            citation["id"], {"resolution_note": "ACGME accepted revised response"},
            DIO))
        assert _program_status(api, program["id"]) == "CONTINUED"

    def test_re_response_cycle_transitions_and_versions(self, api: ApiClient):
        """PRD §3.9: "Drafting a response is allowed from `OPEN` or from
        `ESCALATED` (otherwise `ERR_CITATION_NOT_DRAFTABLE`, HTTP 409) — the
        latter is the re-response cycle after an escalated submission".
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource".

        Design: Difficulty/non_linear_state_machine/citation_escalation_re_response_cycle
        """
        _, citation = self._setup(api)
        c = validate_success(api.draft_citation_response(
            citation["id"], {"response_text": "First draft."}, PD))
        assert c["status"] == "RESPONSE_DRAFTED"
        c = validate_success(api.submit_citation_response(citation["id"], PD))
        assert c["status"] == "RESPONSE_SUBMITTED"
        c = validate_success(api.escalate_citation(
            citation["id"], {"escalation_reason": "Inadequate response"}, DIO))
        assert c["status"] == "ESCALATED"
        c = validate_success(api.draft_citation_response(
            citation["id"], {"response_text": "Second draft."}, PD))
        assert c["status"] == "RESPONSE_DRAFTED"
        c = validate_success(api.submit_citation_response(citation["id"], PD))
        assert c["status"] == "RESPONSE_SUBMITTED"
        c = validate_success(api.resolve_citation(
            citation["id"], {"resolution_note": "Accepted"}, DIO))
        assert c["status"] == "RESOLVED"
        # create 1 + 6 transitions.
        assert c["version"] == 7


class TestCitationInvalidTransitions:
    def test_from_open_and_from_drafted(self, api: ApiClient):
        """PRD §3.9: "Submitting the response requires `RESPONSE_DRAFTED`
        (otherwise `ERR_CITATION_RESPONSE_NOT_DRAFTED`, HTTP 409) and moves the
        citation to `RESPONSE_SUBMITTED`."
        PRD §3.9: "From there the DIO either resolves the citation (requiring
        `RESPONSE_SUBMITTED`, otherwise `ERR_CITATION_NOT_RESOLVABLE`,
        HTTP 409)".
        PRD §3.9: "or escalates it (same state requirement, otherwise
        `ERR_CITATION_NOT_ESCALATABLE`, HTTP 409), moving it to `ESCALATED`
        with the `escalation_reason` recorded and the program status
        recomputed".
        PRD §3.9: "Drafting a response is allowed from `OPEN` or from
        `ESCALATED` (otherwise `ERR_CITATION_NOT_DRAFTABLE`, HTTP 409)".

        Design: Corner/state_machines/citation_invalid_transition_errors
        """
        program = make_program()
        citation = make_citation(program["id"], citation_code="IV.A.2",
                                 severity="WARNING", area_code="EVALUATION")

        resp = api.submit_citation_response(citation["id"], PD)
        validate_error(resp, ApiErrorId.ERR_CITATION_RESPONSE_NOT_DRAFTED)
        resp = api.resolve_citation(citation["id"],
                                    {"resolution_note": "premature"}, DIO)
        validate_error(resp, ApiErrorId.ERR_CITATION_NOT_RESOLVABLE)
        resp = api.escalate_citation(citation["id"],
                                     {"escalation_reason": "premature"}, DIO)
        validate_error(resp, ApiErrorId.ERR_CITATION_NOT_ESCALATABLE)

        drafted = validate_success(api.draft_citation_response(
            citation["id"], {"response_text": "First draft."}, PD))
        assert drafted["status"] == "RESPONSE_DRAFTED"
        resp = api.draft_citation_response(
            citation["id"], {"response_text": "Second draft."}, PD)
        validate_error(resp, ApiErrorId.ERR_CITATION_NOT_DRAFTABLE)
        assert validate_success(api.get_citation(citation["id"], PD))[
            "status"] == "RESPONSE_DRAFTED"


class TestSurveyCloseTwice:
    def test_second_close_rejected_without_replaying_cascade(self, api: ApiClient):
        """PRD §3.9: "Closing is the DIO's act and requires `OPEN` (otherwise
        `ERR_SURVEY_NOT_OPEN`, HTTP 409)."

        Design: Corner/state_machines/survey_close_twice_rejected
        """
        program = make_program()
        year = make_year(program["id"])
        survey = make_survey(program["id"], year["id"])
        payload = close_survey_payload(
            resident_response_rate=85.00, faculty_response_rate=90.00,
            area_results=[{"area_code": "DUTY_HOURS", "compliance_pct": 65.00}])
        closed = validate_success(api.close_survey(survey["id"], payload, DIO))
        assert closed["status"] == "CLOSED"
        assert closed["flagged_area_count"] == 1

        resp = api.close_survey(survey["id"], payload, DIO)
        validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_OPEN)
        # One flagged area below the SERIOUS breadth threshold: exactly one
        # WARNING citation from the first close, and no duplicate cascade.
        citations, meta = list_citations(program_id=program["id"])
        assert meta["total_count"] == 1
        assert citations[0]["citation_code"] == "SURVEY-DUTY_HOURS-2026-2027"
        assert citations[0]["severity"] == "WARNING"


class TestDerivedStatusReconciliation:
    def test_status_reconciles_on_resolve(self, api: ApiClient):
        """PRD §3.1: "The program's `accreditation_status` is computed, not
        entered: it starts at `CONTINUED` and thereafter derives from the
        program's unresolved serious citations (§3.9)."
        PRD §3.9: "resolving the last unresolved `SERIOUS` citation drops the
        program back out of its warning or probationary band".

        Design: Corner/cross_cutting_complexity_layers/derived_program_status_reconciles_on_citation_resolve
        """
        program = make_program()
        assert program["accreditation_status"] == "CONTINUED"
        citation = make_citation(program["id"], citation_code="IV.A.2",
                                 area_code="SUPERVISION")
        assert _program_status(api, program["id"]) == "CONTINUED_WITH_WARNING"
        respond_and_resolve_citation(citation["id"])
        assert _program_status(api, program["id"]) == "CONTINUED"

    def test_warning_vs_probationary_threshold(self, api: ApiClient):
        """PRD §3.9: "with two or more unresolved `SERIOUS` citations the
        program is `PROBATIONARY`; with exactly one it is
        `CONTINUED_WITH_WARNING`; with none it is `CONTINUED`."

        Design: Corner/cross_cutting_complexity_layers/program_status_warning_vs_probationary_threshold
        """
        program = make_program()
        make_citation(program["id"], citation_code="IV.A.1",
                      area_code="SUPERVISION")
        assert _program_status(api, program["id"]) == "CONTINUED_WITH_WARNING"
        make_citation(program["id"], citation_code="III.B.3",
                      area_code="DUTY_HOURS")
        assert _program_status(api, program["id"]) == "PROBATIONARY"
