"""Adverse Drug Reaction (ADR) reporting, deadlines, escalation, and
follow-up archival (PRD §3.8).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_adr,
    setup_platform_at_clock,
    create_vendor,
    create_otc_drug_on_shelf,
    create_customer,
    create_pharmacist,
    advance_clock,
    add_hours,
    add_days,
    add_milliseconds,
    parse_iso,
    iso_z,
    create_adr_payload,
    get_adr_report,
    get_external_events,
    get_audit_logs,
    find_audit_logs,
    find_external_events,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_pharmacist_re_reviewer_headers,
    make_regulatory_headers,
)


# ---------------------------------------------------------------------------
# Creation + deadline (PRD §3.8)
# ---------------------------------------------------------------------------

class TestADRCreationAndDeadline:
    """PRD §3.8: 'On creation the report enters status REPORTED, reported_at
    is set to current_clock_iso, and reporting_deadline_at is computed
    forward-looking from reported_at: a SERIOUS report's deadline is
    reported_at plus 24 hours, and a NON_SERIOUS report's deadline is
    reported_at plus 15 days.'
    """

    def test_serious_adr_deadline_24_hours(self, api):
        """PRD §3.8: SERIOUS deadline = reported_at + 24h."""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="SERIOUS")
        report = s["report"]
        assert report["status"] == "REPORTED"
        assert report["reported_at"] == clock
        # reporting_deadline_at = reported_at + 24h
        expected = add_hours(clock, 24)
        assert report["reporting_deadline_at"] == expected

    def test_non_serious_adr_deadline_15_days(self, api):
        """PRD §3.8: NON_SERIOUS deadline = reported_at + 15 days."""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        report = s["report"]
        expected = add_days(clock, 15)
        assert report["reporting_deadline_at"] == expected


# ---------------------------------------------------------------------------
# Escalation: forward-looking anchored at intake (PRD §3.8)
# ---------------------------------------------------------------------------

class TestADREscalationAnchor:
    """PRD §3.8: 'The deadline is recomputed under the forward-looking
    convention: it remains anchored at the original reported_at and is
    recomputed to reported_at plus 24 hours; the moment of escalation does
    not extend the clock. As a consequence, if 24 hours have already
    elapsed since the original reported_at, the report is already past its
    deadline and a subsequent submit will fail.'
    """

    def test_escalation_anchored_at_intake_not_escalation_time(self, api):
        """PRD §3.8: 'it remains anchored at the original reported_at and
        is recomputed to reported_at plus 24 hours; the moment of
        escalation does not extend the clock.'

        # difficulty: dual_variant_calc/adr_deadline_anchor_variant
        """
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        # Move clock 1ms past 24h since reported_at.
        future = add_milliseconds(add_hours(clock, 24), 1)
        advance_clock(api, pf["id"], future)
        # Escalate severity → SERIOUS.
        api.escalate_adr(pf["id"], report["id"],
                            make_pharmacist_re_reviewer_headers(rr["id"]))
        report_after = get_adr_report(api, pf["id"], report["id"])
        # PRD §3.8: deadline anchored at original reported_at (clock at intake).
        assert report_after["severity"] == "SERIOUS"
        assert report_after["reporting_deadline_at"] == add_hours(clock, 24)

    def test_submit_past_deadline_after_escalation_rejected(self, api):
        """PRD §3.8: 'Submission transitions a report from REPORTED to
        SUBMITTED. The action requires status equal to REPORTED ... and
        current_clock_iso strictly less than reporting_deadline_at (the
        grace allowance is 0 hours, so the deadline is hard); a submission
        past the deadline is rejected with ERR_REPORTING_DEADLINE_PASSED.'

        # difficulty: dual_variant_calc/adr_deadline_anchor_variant
        """
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        # Advance 1ms past 24h.
        future = add_milliseconds(add_hours(clock, 24), 1)
        advance_clock(api, pf["id"], future)
        api.escalate_adr(pf["id"], report["id"],
                            make_pharmacist_re_reviewer_headers(rr["id"]))
        # Now submit — clock is past reporting_deadline_at (which is anchored
        # at intake = clock+24h, but current clock is +24h+1ms).
        resp = api.submit_adr(pf["id"], report["id"],
                                 make_pharmacist_re_reviewer_headers(rr["id"]))
        validate_error(resp, ApiErrorId.ERR_REPORTING_DEADLINE_PASSED.value)


# ---------------------------------------------------------------------------
# Submit + auto FOLLOW_UP_PENDING (PRD §3.8)
# ---------------------------------------------------------------------------

class TestADRSubmit:
    """PRD §3.8: 'Successful submission sets submitted_to_authority_at to
    current_clock_iso, sets follow_up_due_at to submitted_to_authority_at
    plus 7 days when severity is SERIOUS (and leaves it unset for non-serious
    reports), appends an AuditLog row with action ADR_SUBMITTED, and emits
    an ExternalEvent on channel REGULATORY_AUTHORITY with event_type
    adr.submitted ... Immediately after SUBMITTED, a SERIOUS report is
    auto-advanced to FOLLOW_UP_PENDING by the system.'
    """

    def test_submit_serious_auto_advances_to_follow_up_pending(self, api):
        """PRD §3.8: 'Immediately after SUBMITTED, a SERIOUS report is
        auto-advanced to FOLLOW_UP_PENDING by the system.'"""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        report_after = get_adr_report(api, pf["id"], report["id"])
        assert report_after["status"] == "FOLLOW_UP_PENDING"
        # follow_up_due_at = submitted_to_authority_at + 7 days
        assert report_after["follow_up_due_at"] == add_days(clock, 7)

    def test_submit_non_serious_stays_submitted(self, api):
        """PRD §3.8: non-serious doesn't auto-transit to FOLLOW_UP_PENDING."""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        report_after = get_adr_report(api, pf["id"], report["id"])
        assert report_after["status"] == "SUBMITTED"

    def test_submit_emits_adr_submitted_event(self, api):
        """PRD §3.8: 'emits an ExternalEvent on channel REGULATORY_AUTHORITY
        with event_type adr.submitted.'"""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        events = get_external_events(api, pf["id"])
        match = find_external_events(events, channel="REGULATORY_AUTHORITY",
                                         event_type="adr.submitted",
                                         subject_id=report["id"])
        assert len(match) == 1


# ---------------------------------------------------------------------------
# Acknowledge / archive (PRD §3.8)
# ---------------------------------------------------------------------------

class TestADRAcknowledgeArchive:
    """PRD §3.8: 'A RegulatoryGateway operator may transition a SUBMITTED
    report to ACKNOWLEDGED only when its severity is NON_SERIOUS; serious
    reports must transit through FOLLOW_UP_PENDING and may not be
    acknowledged directly (otherwise ERR_REPORT_REQUIRES_FOLLOW_UP).'
    """

    def test_acknowledge_serious_rejected(self, api):
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        # SERIOUS submission auto-advances to FOLLOW_UP_PENDING; we must
        # construct a SUBMITTED-but-not-yet-followup state to test direct
        # acknowledge. PRD says serious auto-advances on submit, so we
        # cannot directly observe SUBMITTED for SERIOUS — but the rule
        # 'serious reports may not be acknowledged directly' is exercised
        # by attempting acknowledge while in FOLLOW_UP_PENDING.
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        # Now FOLLOW_UP_PENDING. Acknowledge requires SUBMITTED state per
        # PRD's 'A RegulatoryGateway operator may transition a SUBMITTED
        # report to ACKNOWLEDGED only when its severity is NON_SERIOUS'.
        resp = api.acknowledge_adr(pf["id"], report["id"],
                                       TEST_USERS["regulatory_headers"])
        # PRD: 'serious reports must transit through FOLLOW_UP_PENDING and
        # may not be acknowledged directly (otherwise ERR_REPORT_REQUIRES_FOLLOW_UP).'
        # We cannot uniquely commit to ERR_REPORT_REQUIRES_FOLLOW_UP vs a
        # state-not-SUBMITTED rejection here (the report is now in
        # FOLLOW_UP_PENDING, so a state-check could fire first). Both are
        # PRD-faithful — accept either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_REPORT_REQUIRES_FOLLOW_UP.value,
            ApiErrorId.ERR_REPORT_NOT_REPORTED.value,
        ])

    def test_acknowledge_non_serious_succeeds(self, api):
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        resp = api.acknowledge_adr(pf["id"], report["id"],
                                       TEST_USERS["regulatory_headers"])
        data = validate_success(resp)
        assert data["status"] == "ACKNOWLEDGED"

    def test_archive_serious_before_follow_up_due_at_rejected(self, api):
        """PRD §3.8: 'when severity is SERIOUS, current_clock_iso to be at
        or after follow_up_due_at (otherwise ERR_FOLLOW_UP_INCOMPLETE).'"""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        # Do not advance clock 7 days; archive must be rejected.
        resp = api.archive_adr(pf["id"], report["id"],
                                   make_pharmacist_re_reviewer_headers(rr["id"]))
        validate_error(resp, ApiErrorId.ERR_FOLLOW_UP_INCOMPLETE.value)

    def test_archive_serious_after_follow_up_succeeds(self, api):
        """PRD §3.8: serious archive succeeds once clock >= follow_up_due_at."""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        # Advance clock to follow_up_due_at (= clock + 7 days).
        advance_clock(api, pf["id"], add_days(clock, 7))
        resp = api.archive_adr(pf["id"], report["id"],
                                   make_pharmacist_re_reviewer_headers(rr["id"]))
        data = validate_success(resp)
        assert data["status"] == "ARCHIVED"

    def test_archive_appends_audit_log(self, api):
        """PRD §3.8: 'On success, archived_at is set to current_clock_iso
        and an AuditLog row with action ADR_ARCHIVED is appended.'"""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        api.acknowledge_adr(pf["id"], report["id"],
                                TEST_USERS["regulatory_headers"])
        api.archive_adr(pf["id"], report["id"],
                            make_pharmacist_re_reviewer_headers(rr["id"]))
        logs = get_audit_logs(api, pf["id"])
        match = find_audit_logs(logs, subject_id=report["id"],
                                  action="ADR_ARCHIVED")
        assert len(match) == 1


# ---------------------------------------------------------------------------
# Submit state precondition (PRD §3.8)
# ---------------------------------------------------------------------------

class TestADRSubmitState:
    """PRD §3.8: 'The action requires status equal to REPORTED (otherwise
    ERR_REPORT_NOT_REPORTED).'
    """

    def test_double_submit_rejected(self, api):
        """Submit then submit again → ERR_REPORT_NOT_REPORTED."""
        clock = "2025-01-01T00:00:00.000Z"
        s = setup_adr(api, clock_iso=clock, severity="NON_SERIOUS")
        pf, report, rr = s["platform"], s["report"], s["rr_pharmacist"]
        api.submit_adr(pf["id"], report["id"],
                          make_pharmacist_re_reviewer_headers(rr["id"]))
        resp = api.submit_adr(pf["id"], report["id"],
                                 make_pharmacist_re_reviewer_headers(rr["id"]))
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_REPORTED.value)
