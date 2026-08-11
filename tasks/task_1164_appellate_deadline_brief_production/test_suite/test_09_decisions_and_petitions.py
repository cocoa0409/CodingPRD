"""Decisions, rehearing windows, further-review petitions, posture arc."""
from datetime import timedelta

import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_case, assert_decision, assert_petition,
    assert_instant_equal, add_calendar_days, iso_utc, parse_ts,
    attorney_headers,
    create_attorney,
    setup_record_pending_case, setup_argument_pending_case, setup_decided_case,
    complete_record, get_case_schedule, get_case_record,
    create_brief, walk_brief_to_accepted,
    waive_argument, enter_decision,
    create_petition_payload,
    set_clock, read_clock,
    CLERK,
)


class TestRehearingWindowByJurisdiction:
    def test_federal_court_rehearing_window_is_fourteen_days(self, api):
        """PRD §3.8: "The `rehearing_deadline_at` is `issued_at` plus a
        jurisdiction-dependent window — fourteen calendar days for a `FEDERAL`
        court, thirty for any other jurisdiction — and the same ninety-day
        window that governs certiorari petitions is anchored at `issued_at` as
        well."

        Design: Difficulty/combinatorial_formula/rehearing_window_jurisdiction_dependent_chronological
        """
        ctx = setup_decided_case(
            court_overrides={"code": "FED-CT", "jurisdiction_type": "FEDERAL"},
        )
        decision = ctx["decision"]
        assert_decision(decision)
        expected = iso_utc(add_calendar_days(decision["issued_at"], 14))
        assert_instant_equal(
            decision["rehearing_deadline_at"], expected,
            "FEDERAL court rehearing deadline must be issued_at plus fourteen days",
        )

    def test_state_court_rehearing_window_is_thirty_days(self, api):
        """PRD §3.8: "The `rehearing_deadline_at` is `issued_at` plus a
        jurisdiction-dependent window — fourteen calendar days for a `FEDERAL`
        court, thirty for any other jurisdiction — and the same ninety-day
        window that governs certiorari petitions is anchored at `issued_at` as
        well."

        Design: Difficulty/combinatorial_formula/rehearing_window_jurisdiction_dependent_chronological
        """
        ctx = setup_decided_case(
            court_overrides={"code": "ST-CT", "jurisdiction_type": "STATE",
                             "appeal_deadline_days": 60, "reply_brief_window_days": 21},
        )
        decision = ctx["decision"]
        assert_decision(decision)
        expected = iso_utc(add_calendar_days(decision["issued_at"], 30))
        assert_instant_equal(
            decision["rehearing_deadline_at"], expected,
            "STATE court rehearing deadline must be issued_at plus thirty days",
        )


class TestCasePostureArc:
    def test_posture_walks_full_arc_open_through_decided(self, api):
        """PRD §3.8: "The full posture arc — `OPEN` to `RECORD_PENDING` to
        `BRIEFING` to `ARGUMENT_PENDING` to `DECIDED` to `CLOSED`, with the
        rehearing-driven loop from `DECIDED` back to `BRIEFING` — is always
        readable as the case's computed `posture`."

        Design: Difficulty/non_linear_state_machine/case_parallel_state_dimensions_posture_x_brief_x_record
        """
        ctx = setup_record_pending_case(court_overrides={"code": "PD-CT"})
        attorney = ctx["attorney"]
        headers = attorney_headers(attorney)
        assert ctx["case"]["posture"] == "OPEN"

        case_now = validate_success(api.get_case(ctx["case"]["id"], headers), 200)
        assert case_now["posture"] == "RECORD_PENDING", (
            "accepting the notice of appeal must move posture OPEN -> RECORD_PENDING"
        )

        record = complete_record(ctx["record"], attorney)
        assert record["status"] == "COMPLETE"
        case_now = validate_success(api.get_case(ctx["case"]["id"], headers), 200)
        assert case_now["posture"] == "BRIEFING", (
            "completing the record must move posture RECORD_PENDING -> BRIEFING"
        )
        ctx["record"] = record
        ctx["schedule"] = get_case_schedule(ctx["case"]["id"], headers)

        # Two briefs ACCEPTED + reply window expiry completes the schedule.
        reviewer = create_attorney(admitted_court_ids=[ctx["court"]["id"]])
        ctx["reviewer"] = reviewer
        opening = create_brief(ctx, "OPENING")
        response = create_brief(ctx, "RESPONSE")
        walk_brief_to_accepted(ctx, opening)
        walk_brief_to_accepted(ctx, response)
        reply_due = parse_ts(ctx["schedule"]["reply_due_at"])
        set_clock(iso_utc(reply_due + timedelta(days=1)))
        case_now = validate_success(api.get_case(ctx["case"]["id"], headers), 200)
        assert case_now["posture"] == "ARGUMENT_PENDING", (
            "completing the briefing schedule must move posture BRIEFING -> ARGUMENT_PENDING"
        )
        ctx["case"] = case_now
        args = get_success_data(api.list_case_oral_arguments(ctx["case"]["id"], headers))
        args = args if isinstance(args, list) else [args]
        ctx["oral_argument"] = [a for a in args if a.get("status") == "REQUESTED"][0]

        waive_argument(ctx)
        decision = enter_decision(ctx, outcome="AFFIRMED", issued_at=read_clock())
        assert_decision(decision)
        case_now = validate_success(api.get_case(ctx["case"]["id"], headers), 200)
        assert case_now["posture"] == "DECIDED", (
            "entering a decision must move posture ARGUMENT_PENDING -> DECIDED"
        )

    def test_rehearing_grant_reopens_case_to_briefing(self, api):
        """PRD §3.8: "Granting a `REHEARING` or `REHEARING_EN_BANC` petition
        reopens the case: posture moves from `DECIDED` back to `BRIEFING` and a
        fresh briefing schedule is created in `PENDING`, starting the briefing
        cycle over."
        PRD §3.8: "The full posture arc — `OPEN` to `RECORD_PENDING` to
        `BRIEFING` to `ARGUMENT_PENDING` to `DECIDED` to `CLOSED`, with the
        rehearing-driven loop from `DECIDED` back to `BRIEFING` — is always
        readable as the case's computed `posture`."

        Design: Difficulty/non_linear_state_machine/case_parallel_state_dimensions_posture_x_brief_x_record
        """
        ctx = setup_decided_case(court_overrides={"code": "PD-RH"})
        headers = attorney_headers(ctx["attorney"])

        petition = validate_success(
            api.create_petition(
                ctx["case"]["id"],
                create_petition_payload(ctx["decision"]["id"], petition_type="REHEARING"),
                headers,
            ), 201,
        )
        validate_success(api.file_petition(petition["id"], headers), 200)
        granted = validate_success(api.grant_petition(petition["id"], CLERK), 200)
        assert granted["status"] == "GRANTED"

        case_now = validate_success(api.get_case(ctx["case"]["id"], headers), 200)
        assert case_now["posture"] == "BRIEFING", (
            f"a granted rehearing petition must reopen the case to BRIEFING, got {case_now['posture']}"
        )
        fresh = get_case_schedule(ctx["case"]["id"], headers, status="PENDING")
        assert fresh["status"] == "PENDING", (
            "a fresh briefing schedule must be created in PENDING on reopening"
        )


class TestPetitionFilingGate:
    def test_petition_files_when_case_decided(self, api):
        """PRD §3.8: "Filing the petition is deadline-checked first: the filing
        must occur at or before `due_at`, else `ERR_DEADLINE_PASSED`; the case
        must also stand `DECIDED`, else `ERR_DECISION_NOT_ISSUED`, and because
        deadline currency outranks the decision check, a petition that is both
        early-of-no-decision and late surfaces the deadline error first."
        PRD §3.8: "A clean filing moves the petition from `DRAFT` to `FILED` and
        creates a filing row of the matching `filing_type`."
        PRD §3.8: "The new petition sits in `DRAFT` with `filed_at` null and a
        `due_at` computed from the decision's `issued_at` plus the applicable
        court petition window: the fourteen- or thirty-day rehearing window for
        `REHEARING` and `REHEARING_EN_BANC`, the ninety-day window for
        `CERTIORARI`."

        Design: Difficulty/cross_entity_state_dependency/petition_file_gated_by_decision_state
        """
        ctx = setup_decided_case(court_overrides={"code": "CE2"})
        headers = attorney_headers(ctx["attorney"])

        petition = validate_success(
            api.create_petition(
                ctx["case"]["id"],
                create_petition_payload(ctx["decision"]["id"], petition_type="REHEARING"),
                headers,
            ), 201,
        )
        assert_petition(petition)
        assert petition["status"] == "DRAFT"
        assert petition["filed_at"] is None
        expected_due = iso_utc(add_calendar_days(ctx["decision"]["issued_at"], 14))
        assert_instant_equal(petition["due_at"], expected_due)

        filed = validate_success(api.file_petition(petition["id"], headers), 200)
        assert filed["status"] == "FILED"
        filings = get_success_data(api.list_case_filings(
            ctx["case"]["id"], headers, params={"filing_type": "REHEARING_PETITION"}
        ))
        filings = filings if isinstance(filings, list) else [filings]
        assert len(filings) == 1, "petition filing must create a filing row of the matching type"

    def test_petition_file_rejected_when_case_no_longer_decided(self, api):
        """PRD §3.8: "Filing the petition is deadline-checked first: the filing
        must occur at or before `due_at`, else `ERR_DEADLINE_PASSED`; the case
        must also stand `DECIDED`, else `ERR_DECISION_NOT_ISSUED`, and because
        deadline currency outranks the decision check, a petition that is both
        early-of-no-decision and late surfaces the deadline error first."

        Design: Difficulty/cross_entity_state_dependency/petition_file_gated_by_decision_state
        """
        ctx = setup_decided_case(court_overrides={"code": "CE2N"})
        headers = attorney_headers(ctx["attorney"])

        # Reopen the case via a granted rehearing petition: posture DECIDED -> BRIEFING.
        first = validate_success(
            api.create_petition(
                ctx["case"]["id"],
                create_petition_payload(ctx["decision"]["id"], petition_type="REHEARING"),
                headers,
            ), 201,
        )
        validate_success(api.file_petition(first["id"], headers), 200)
        validate_success(api.grant_petition(first["id"], CLERK), 200)
        case_now = validate_success(api.get_case(ctx["case"]["id"], headers), 200)
        assert case_now["posture"] == "BRIEFING"

        # A fresh petition on the same decision can be drafted, but filing it
        # now fails the decision-issued gate (still within its due window).
        second = validate_success(
            api.create_petition(
                ctx["case"]["id"],
                create_petition_payload(ctx["decision"]["id"], petition_type="REHEARING"),
                headers,
            ), 201,
        )
        res = api.file_petition(second["id"], headers)
        validate_error(res, ApiErrorId.ERR_DECISION_NOT_ISSUED.value, expected_status=409)

    def test_late_petition_file_returns_deadline_passed(self, api):
        """PRD §3.8: "Filing the petition is deadline-checked first: the filing
        must occur at or before `due_at`, else `ERR_DEADLINE_PASSED`; the case
        must also stand `DECIDED`, else `ERR_DECISION_NOT_ISSUED`, and because
        deadline currency outranks the decision check, a petition that is both
        early-of-no-decision and late surfaces the deadline error first."

        Design: Corner/errors/err_deadline_passed_on_late_petition_file
        """
        ctx = setup_decided_case(court_overrides={"code": "E2"})
        headers = attorney_headers(ctx["attorney"])
        petition = validate_success(
            api.create_petition(
                ctx["case"]["id"],
                create_petition_payload(ctx["decision"]["id"], petition_type="REHEARING"),
                headers,
            ), 201,
        )
        # Advance the clock well past the rehearing window; the DRAFT petition
        # keeps the case DECIDED (closure requires no pending petitions).
        due = parse_ts(petition["due_at"])
        set_clock(iso_utc(due + timedelta(days=1)))

        res = api.file_petition(petition["id"], headers)
        validate_error(res, ApiErrorId.ERR_DEADLINE_PASSED.value, expected_status=409)
