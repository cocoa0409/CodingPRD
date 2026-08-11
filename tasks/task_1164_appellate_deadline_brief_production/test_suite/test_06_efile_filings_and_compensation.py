"""E-filing gates, clerk review of filings, compensating reversals."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_brief, assert_filing,
    find_deadline,
    attorney_headers,
    setup_record_pending_case, setup_briefing_case,
    create_brief, submit_brief, approve_brief, efile_brief,
    walk_brief_to_ready, walk_brief_to_efiled, walk_brief_to_accepted,
    order_transcript, list_case_deadlines,
    create_attorney, set_clock,
    deliver_transcript_payload,
    CLERK, TEST_DEFAULTS,
)


class TestEfileRecordGate:
    def _setup_ready_brief_with_incomplete_record(self, api):
        """Notice accepted, record DESIGNATED with an undelivered transcript,
        schedule still PENDING, brief walked to READY."""
        ctx = setup_record_pending_case(court_overrides={"code": "CE1"})
        reviewer = create_attorney(admitted_court_ids=[ctx["court"]["id"]])
        ctx["reviewer"] = reviewer
        headers = attorney_headers(ctx["attorney"])
        validate_success(api.designate_record(ctx["record"]["id"], headers), 200)
        order_transcript(ctx["record"]["id"], ctx["attorney"])  # never delivered
        brief = create_brief(ctx, "OPENING")
        walk_brief_to_ready(ctx, brief)
        return ctx, brief

    def test_efile_blocked_when_record_not_complete(self, api):
        """PRD §3.5: "the record must be `COMPLETE` or `FILED` and the schedule
        must be `ACTIVE`, else `ERR_RECORD_NOT_COMPLETE`."
        PRD §2.9: "11. **Record and schedule readiness** — on brief e-filing, the
        record must be `COMPLETE` or `FILED` and the briefing schedule must be
        `ACTIVE`; otherwise `ERR_RECORD_NOT_COMPLETE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/brief_efile_gated_by_record_state
        """
        ctx, brief = self._setup_ready_brief_with_incomplete_record(api)
        headers = attorney_headers(ctx["attorney"])
        record = validate_success(api.get_record(ctx["record"]["id"], headers), 200)
        assert record["status"] == "DESIGNATED", (
            f"record must be stuck short of COMPLETE, got {record['status']}"
        )

        res = api.efile_brief(brief["id"], {"served_party_emails": ["o@x.com"]}, headers)
        validate_error(res, ApiErrorId.ERR_RECORD_NOT_COMPLETE.value, expected_status=409)
        brief_after = validate_success(api.get_brief(brief["id"], headers), 200)
        assert brief_after["status"] == "READY", (
            "a failed e-file must not move the brief out of READY"
        )

    def test_efile_succeeds_once_record_completes(self, api):
        """PRD §3.5: "the record must be `COMPLETE` or `FILED` and the schedule
        must be `ACTIVE`, else `ERR_RECORD_NOT_COMPLETE`."
        PRD §3.5: "A successful e-filing moves the brief from `READY` to
        `EFILED`, creates a filing row of `filing_type` `BRIEF`, `method`
        `EFILE`, status `SUBMITTED`, and increments both the brief's and the
        case's `version`."

        Design: Difficulty/cross_entity_state_dependency/brief_efile_gated_by_record_state
        """
        ctx, brief = self._setup_ready_brief_with_incomplete_record(api)
        headers = attorney_headers(ctx["attorney"])

        # Now deliver the transcript: record ASSEMBLING -> COMPLETE, schedule ACTIVE.
        transcripts = get_success_data(
            api.list_transcript_orders(ctx["record"]["id"], headers)
        )
        transcripts = transcripts if isinstance(transcripts, list) else [transcripts]
        tid = transcripts[0]["id"]
        validate_success(api.begin_preparation(tid, CLERK), 200)
        validate_success(api.deliver_transcript(tid, deliver_transcript_payload(), CLERK), 200)
        record = validate_success(api.get_record(ctx["record"]["id"], headers), 200)
        assert record["status"] == "COMPLETE"

        res = api.efile_brief(brief["id"], {"served_party_emails": ["o@x.com"]}, headers)
        filing = validate_success(res, 200)
        assert_filing(filing)
        assert filing["filing_type"] == "BRIEF"
        assert filing["method"] == "EFILE"
        assert filing["status"] == "SUBMITTED"
        brief_after = validate_success(api.get_brief(brief["id"], headers), 200)
        assert brief_after["status"] == "EFILED"


class TestEfileServiceRequirement:
    def test_efile_with_empty_service_list_returns_service_incomplete(self, api):
        """PRD §3.5: "the `served_party_emails` list must name at least one
        served party, else `ERR_SERVICE_INCOMPLETE`."
        PRD §2.9: "16. **Service completeness** — on filing creation and on brief
        e-filing, the served-party list must satisfy the filing's service
        requirement; otherwise `ERR_SERVICE_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/efile_with_empty_service_list_returns_service_incomplete
        """
        ctx = setup_briefing_case(court_overrides={"code": "V3"})
        brief = create_brief(ctx, "OPENING")
        walk_brief_to_ready(ctx, brief)

        res = api.efile_brief(
            brief["id"], {"served_party_emails": []}, attorney_headers(ctx["attorney"])
        )
        validate_error(res, ApiErrorId.ERR_SERVICE_INCOMPLETE.value, expected_status=422)


class TestEfileStateGatePriority:
    def test_efile_draft_brief_late_and_over_limit_surfaces_state_error(self, api):
        """PRD §2.9: "Requests are validated in a fixed priority order, and when
        several rules could fail on the same request the earliest rule's error is
        the one returned."
        PRD §3.5: "The checks run in priority order: the brief must be `READY`
        (state); the attorney must be admitted (`ERR_NOT_ADMITTED`); the filing
        must occur at or before the brief's `due_at` — a late filing is rejected
        with `ERR_DEADLINE_PASSED`; the brief must not be `over_limit`; the
        record must be `COMPLETE` or `FILED` and the schedule must be `ACTIVE`,
        else `ERR_RECORD_NOT_COMPLETE`; and the `served_party_emails` list must
        name at least one served party, else `ERR_SERVICE_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_late_overlimit
        """
        ctx = setup_briefing_case(court_overrides={
            "code": "PV2", "uses_word_count": True, "max_words_opening": 1000,
        })
        brief = create_brief(ctx, "RESPONSE", page_count=5, word_count=5000)
        assert brief["over_limit"] is True, "setup: brief must be over the 1000-word limit"
        # Advance the logical clock well past the brief's due date.
        set_clock("2027-06-01T00:00:00Z")

        res = api.efile_brief(
            brief["id"], {"served_party_emails": ["o@x.com"]},
            attorney_headers(ctx["attorney"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        brief_after = validate_success(
            api.get_brief(brief["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert brief_after["status"] == "DRAFT"

    def test_efile_draft_brief_on_time_within_limit_surfaces_state_error(self, api):
        """PRD §3.5: "The checks run in priority order: the brief must be
        `READY` (state); the attorney must be admitted (`ERR_NOT_ADMITTED`); the
        filing must occur at or before the brief's `due_at` — a late filing is
        rejected with `ERR_DEADLINE_PASSED`; the brief must not be `over_limit`;
        the record must be `COMPLETE` or `FILED` and the schedule must be
        `ACTIVE`, else `ERR_RECORD_NOT_COMPLETE`; and the `served_party_emails`
        list must name at least one served party, else `ERR_SERVICE_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_late_overlimit
        """
        ctx = setup_briefing_case(court_overrides={"code": "PV2B"})
        brief = create_brief(ctx, "OPENING")  # DRAFT, within limit, not late

        res = api.efile_brief(
            brief["id"], {"served_party_emails": ["o@x.com"]},
            attorney_headers(ctx["attorney"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestFilingRejectCompensation:
    def _setup_efiled_brief(self, api, code):
        ctx = setup_briefing_case(court_overrides={"code": code})
        brief = create_brief(ctx, "OPENING")
        filing = walk_brief_to_efiled(ctx, brief)
        return ctx, brief, filing

    def test_rejecting_brief_filing_returns_brief_to_draft(self, api):
        """PRD §3.6: "Rejection takes a `reason` and moves the filing from
        `SUBMITTED` to `REJECTED`. Rejection of a brief filing compensates: the
        brief returns from `EFILED` to `DRAFT` so it can be redrafted."

        Design: Difficulty/transitive_cascade/filing_reject_compensation_cascade
        """
        ctx, brief, filing = self._setup_efiled_brief(api, "RJCT")
        headers = attorney_headers(ctx["attorney"])
        before = validate_success(api.get_brief(brief["id"], headers), 200)
        assert before["status"] == "EFILED"

        res = api.reject_filing(filing["id"], {"reason": "formatting defects"}, CLERK)
        filing_after = validate_success(res, 200)
        assert_filing(filing_after)
        assert filing_after["status"] == "REJECTED"

        brief_after = validate_success(api.get_brief(brief["id"], headers), 200)
        assert brief_after["status"] == "DRAFT", (
            f"rejected brief filing must return the brief to DRAFT, got {brief_after['status']}"
        )

    def test_brief_deadline_remains_unmet_after_filing_reject(self, api):
        """PRD §3.5: "The corresponding brief deadline is marked met when the
        filing is accepted (§3.6)."
        PRD §3.6: "Rejection of a brief filing compensates: the brief returns
        from `EFILED` to `DRAFT` so it can be redrafted."

        Design: Difficulty/transitive_cascade/filing_reject_compensation_cascade
        """
        ctx, brief, filing = self._setup_efiled_brief(api, "RJC2")
        headers = attorney_headers(ctx["attorney"])
        deadline = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")
        assert deadline["met"] is False, "deadline must be unmet while the filing is undecided"

        validate_success(api.reject_filing(filing["id"], {"reason": "formatting"}, CLERK), 200)
        deadline_after = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")
        assert deadline_after["met"] is False, (
            "deadline must remain unmet after the brief filing is rejected"
        )
        # The returned brief is a DRAFT again and can be redrafted.
        brief_after = validate_success(api.get_brief(brief["id"], headers), 200)
        assert brief_after["status"] == "DRAFT"
        edited = validate_success(
            api.update_brief(brief["id"], {"word_count": 1200}, headers), 200
        )
        assert edited["word_count"] == 1200


class TestStrikeCompensation:
    def test_accepted_filing_marks_deadline_met(self, api):
        """PRD §3.6: "Accepting a `BRIEF` filing moves the brief from `EFILED` to
        `ACCEPTED`, sets the corresponding deadline's `met` to true with
        `met_at` stamped, and — when the accepted brief was the response brief —
        opens the reply window on the schedule."

        Design: Difficulty/compensating_invariant/filing_reject_restores_deadline_met_invariant
        """
        ctx = setup_briefing_case(court_overrides={"code": "CI2"})
        brief = create_brief(ctx, "OPENING")
        filing = walk_brief_to_accepted(ctx, brief)

        headers = attorney_headers(ctx["attorney"])
        brief_after = validate_success(api.get_brief(brief["id"], headers), 200)
        assert brief_after["status"] == "ACCEPTED"
        deadline = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")
        assert deadline["met"] is True, "accepting the brief filing must mark the deadline met"
        assert deadline["met_at"] is not None, "met_at must be stamped on acceptance"

    def test_striking_brief_resets_deadline_met(self, api):
        """PRD §3.5: "A `CourtClerk` strikes an `ACCEPTED` brief, supplying a
        `reason` that cites the court's order; the brief moves to `STRICKEN`,
        the deadline's `met` flag is reset to false as a compensating reversal,
        the case posture is recomputed, and the brief's `version` increments."
        PRD §3.2: "a deadline row also tracks `tolled` (whether a tolling event
        currently suspends it), `met` (whether the corresponding act has been
        performed), and `met_at` (when it was satisfied, null while unmet)."

        Design: Difficulty/compensating_invariant/filing_reject_restores_deadline_met_invariant
        """
        ctx = setup_briefing_case(court_overrides={"code": "CI2S"})
        brief = create_brief(ctx, "OPENING")
        walk_brief_to_accepted(ctx, brief)

        res = api.strike_brief(brief["id"], {"reason": "court order 26-115"}, CLERK)
        stricken = validate_success(res, 200)
        assert stricken["status"] == "STRICKEN"

        deadline = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")
        assert deadline["met"] is False, (
            "striking the accepted brief must reset the deadline's met flag"
        )
        assert deadline["met_at"] is None, "met_at must be null while the deadline is unmet"


class TestFilingClerkExclusivity:
    def test_attorney_cannot_accept_filing(self, api):
        """PRD §3.6: "Acceptance and rejection belong to the `CourtClerk` alone."
        PRD §2.1: "A request whose role is recognized but not permitted to
        invoke the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/attorney_cannot_accept_filing
        """
        from test_helpers import (
            create_court, create_attorney as _mk_attorney, create_case,
            create_filing_payload, reset_clock,
        )
        reset_clock()
        court = create_court(code="RB2")
        attorney = _mk_attorney(admitted_court_ids=[court["id"]])
        case = create_case(court, attorney)
        filing = validate_success(
            api.create_filing(
                case["id"], create_filing_payload("NOTICE_OF_APPEAL"),
                attorney_headers(attorney),
            ), 201,
        )
        res = api.accept_filing(filing["id"], attorney_headers(attorney))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)
