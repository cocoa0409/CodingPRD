"""Monitoring visits, findings, corrective-action plans, the escalation
sweep, and overlap/window rules (PRD §3.9, §2.10)."""

from test_helpers import (
    ApiErrorId,
    accept_cap,
    api_client,
    build_user_headers,
    create_finding_payload,
    create_visit_payload,
    get_grant,
    issue_report,
    open_grant,
    record_finding,
    return_cap,
    schedule_visit,
    set_clock,
    setup_visit_in_progress,
    submit_cap,
    validate_error,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")
MONITOR = build_user_headers("monitor-1", "SEAMonitor")


class TestVisitScheduling:

    def test_monitoring_visit_closed_interval_overlap(self):
        """PRD §3.9: "Visits of the same grant must not overlap as closed day
        intervals — two visits sharing even a single boundary day conflict —
        and the overlap check runs both when a visit is scheduled and when one
        begins, rejected with `ERR_MONITORING_VISIT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/monitoring_visit_closed_interval_overlap
        """
        grant = open_grant(2048, 5_000_000)
        schedule_visit(grant["id"], "2027-01-10", "2027-01-12", "FISCAL")
        # B starts on A's last day: the shared day 2027-01-12 is occupied by
        # both, proving closed-interval semantics.
        resp = api_client.create_visit(
            create_visit_payload(grant["id"],
                                 visit_start_date="2027-01-12",
                                 visit_end_date="2027-01-15",
                                 scope="PROGRAMMATIC"),
            MONITOR,
        )
        validate_error(resp, ApiErrorId.ERR_MONITORING_VISIT_OVERLAP)
        # C starts the day after A ends: disjoint closed intervals coexist.
        created = validate_success(api_client.create_visit(
            create_visit_payload(grant["id"],
                                 visit_start_date="2027-01-13",
                                 visit_end_date="2027-01-20",
                                 scope="PROGRAMMATIC"),
            MONITOR), expected_status=201)
        assert created["status"] == "SCHEDULED"

    def test_visit_overlap_scoped_to_same_grant(self):
        """PRD §3.9: "Visits of the same grant must not overlap as closed day
        intervals — two visits sharing even a single boundary day conflict —
        and the overlap check runs both when a visit is scheduled and when one
        begins, rejected with `ERR_MONITORING_VISIT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/monitoring_visit_closed_interval_overlap
        """
        grant_a = open_grant(2048, 5_000_000)
        grant_b = open_grant(2049, 5_000_000)
        schedule_visit(grant_a["id"], "2027-01-10", "2027-01-12", "FISCAL")
        # The rule scopes to "the same grant": identical dates on another
        # grant do not conflict.
        other = validate_success(api_client.create_visit(
            create_visit_payload(grant_b["id"],
                                 visit_start_date="2027-01-10",
                                 visit_end_date="2027-01-12",
                                 scope="FISCAL"),
            MONITOR), expected_status=201)
        assert other["grant_id"] == grant_b["id"]
        # Adjacency on the near side: ending the day before A starts shares
        # no calendar day.
        adjacent = validate_success(api_client.create_visit(
            create_visit_payload(grant_a["id"],
                                 visit_start_date="2027-01-05",
                                 visit_end_date="2027-01-09",
                                 scope="COMPREHENSIVE"),
            MONITOR), expected_status=201)
        assert adjacent["status"] == "SCHEDULED"

    def test_visit_window_missed_rejected(self):
        """PRD §3.9: "The monitor begins the visit, moving it from `SCHEDULED`
        to `IN_PROGRESS`, only while the current clock date falls inside the
        visit window inclusive of both endpoints; a missed window is rejected
        with `ERR_VISIT_WINDOW_MISSED`, and a visit in any other state with
        `ERR_VISIT_INVALID_STATE`."
        PRD §2.10: "At startup, before any client call, the clock reads
        exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock
        time."

        Design: Corner/errors/visit_window_missed_rejected
        """
        grant = open_grant(2086, 5_000_000)
        visit = schedule_visit(grant["id"], "2026-07-01", "2026-07-31",
                               "PROGRAMMATIC")
        resp = api_client.start_visit(visit["id"], MONITOR)
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_MISSED)

    def test_invalid_date_range_rejected(self):
        """PRD §3.9: "SEA oversight arrives as **monitoring visits**,
        scheduled by an `SEAMonitor` with the `grant_id`, an inclusive day
        interval from `visit_start_date` through `visit_end_date` (an end
        before the start is rejected with `ERR_INVALID_DATE_RANGE`), and a
        `scope` of `PROGRAMMATIC`, `FISCAL`, or `COMPREHENSIVE`."

        Design: Corner/errors/invalid_date_range_rejected
        """
        grant = open_grant(2093, 5_000_000)
        resp = api_client.create_visit(
            create_visit_payload(grant["id"],
                                 visit_start_date="2027-01-15",
                                 visit_end_date="2027-01-10",
                                 scope="FISCAL"),
            MONITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestFindings:

    def test_finding_on_scheduled_visit_rejected(self):
        """PRD §3.9: "Findings may be recorded only while the visit is
        `IN_PROGRESS` — against any other visit status the recording is
        rejected with `ERR_VISIT_NOT_ACCEPTING_FINDINGS`."

        Design: Corner/errors/finding_on_scheduled_visit_rejected
        """
        grant = open_grant(2075, 5_000_000)
        visit = schedule_visit(grant["id"], "2026-08-01", "2026-08-05",
                               "FISCAL")
        resp = api_client.create_finding(
            create_finding_payload(visit["id"],
                                   description="premature finding",
                                   cap_due_date="2026-08-20"),
            MONITOR,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_ACCEPTING_FINDINGS)

    def test_accept_cap_on_open_finding_rejected(self):
        """PRD §3.9: "The analyst or the director submits a CAP from `OPEN`,
        from `ESCALATED`, or from `CAP_RETURNED` (the revision cycle); any
        other status is rejected with `ERR_FINDING_INVALID_STATE`." and "The
        monitor then adjudicates under segregation of duties against
        `cap_submitted_by_user_id`: accepting moves the finding to the
        terminal `VERIFIED` state, while returning requires a `return_note`
        (missing, `ERR_INVALID_REQUEST`) and moves it to `CAP_RETURNED`; both
        record `decided_by_user_id`."

        Design: Corner/errors/accept_cap_on_open_finding_rejected
        """
        grant = open_grant(2076, 5_000_000)
        visit = setup_visit_in_progress(grant["id"])
        finding = record_finding(visit["id"], citation="2 CFR 200.403",
                                 description="cost principles violated",
                                 cap_due_date="2026-08-20")
        resp = api_client.accept_cap(finding["id"], MONITOR)
        validate_error(resp, ApiErrorId.ERR_FINDING_INVALID_STATE)

    def test_submit_cap_short_narrative_rejected(self):
        """PRD §3.9: "The `cap_narrative` must be at least 50 characters (else
        `ERR_NARRATIVE_TOO_SHORT`), and each submission records
        `cap_submitted_by_user_id` and increments `cap_attempt_count` by one,
        moving the finding to `CAP_SUBMITTED`."
        PRD §3.9: "A recorded finding starts in `OPEN` with
        `cap_attempt_count` at zero, and its creation immediately recomputes
        the grant's `monitoring_clearance` and advances the grant's `version`
        by one."

        Design: Corner/errors/submit_cap_short_narrative_rejected
        """
        grant = open_grant(2085, 5_000_000)
        visit = setup_visit_in_progress(grant["id"],
                                        visit_end_date="2026-08-05",
                                        scope="FISCAL")
        finding = record_finding(visit["id"], description="ranking issue",
                                 cap_due_date="2026-08-20")
        resp = api_client.submit_cap(finding["id"],
                                     {"cap_narrative": "will fix"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_NARRATIVE_TOO_SHORT)
        after = validate_success(api_client.get_finding(finding["id"],
                                                        MONITOR))
        assert after["status"] == "OPEN"
        assert after["cap_attempt_count"] == 0

    def test_close_no_action_observation_only(self):
        """PRD §3.9: "One shortcut exists for trivial matters: an `OPEN`
        finding whose `severity` is `OBSERVATION` may be closed without
        corrective action, moving to the terminal `CLOSED_NO_ACTION` state;
        the shortcut is unavailable to any other severity or status, rejected
        with `ERR_FINDING_INVALID_STATE`."
        PRD §3.9: "The moment a finding reaches `VERIFIED` — or an observation
        is closed with no action — the system checks its visit: when that was
        the visit's last finding outside the terminal set (`VERIFIED`,
        `CLOSED_NO_ACTION`), the visit auto-transitions from `REPORT_ISSUED`
        to `CLOSED`."

        Design: Corner/state_machines/close_no_action_observation_only
        """
        grant = open_grant(2041, 5_000_000)
        visit = setup_visit_in_progress(grant["id"])
        f_obs = record_finding(visit["id"], severity="OBSERVATION",
                               description="minor formatting observation",
                               cap_due_date="2026-08-20")
        f_find = record_finding(visit["id"], citation="2 CFR 200.403",
                                severity="FINDING",
                                description="substantive finding",
                                cap_due_date="2026-08-20")
        issue_report(visit["id"])
        resp = api_client.close_no_action(f_find["id"], MONITOR)
        validate_error(resp, ApiErrorId.ERR_FINDING_INVALID_STATE)
        closed = validate_success(api_client.close_no_action(f_obs["id"],
                                                             MONITOR))
        assert closed["status"] == "CLOSED_NO_ACTION"
        visit_after = validate_success(api_client.get_visit(visit["id"],
                                                            MONITOR))
        assert visit_after["status"] == "REPORT_ISSUED", \
            "the bubble-up is conditional on ALL findings being terminal"


class TestCapRevisionCycle:

    def test_finding_cap_revision_cycle(self):
        """PRD §3.9: "The analyst or the director submits a CAP from `OPEN`,
        from `ESCALATED`, or from `CAP_RETURNED` (the revision cycle); any
        other status is rejected with `ERR_FINDING_INVALID_STATE`. The
        `cap_narrative` must be at least 50 characters (else
        `ERR_NARRATIVE_TOO_SHORT`), and each submission records
        `cap_submitted_by_user_id` and increments `cap_attempt_count` by one,
        moving the finding to `CAP_SUBMITTED`."
        PRD §3.9: "The monitor then adjudicates under segregation of duties
        against `cap_submitted_by_user_id`: accepting moves the finding to the
        terminal `VERIFIED` state, while returning requires a `return_note`
        (missing, `ERR_INVALID_REQUEST`) and moves it to `CAP_RETURNED`; both
        record `decided_by_user_id`."

        Design: Difficulty/non_linear_state_machine/finding_cap_revision_cycle
        """
        grant = open_grant(2040, 5_000_000)
        visit = setup_visit_in_progress(grant["id"], scope="PROGRAMMATIC")
        finding = record_finding(
            visit["id"], description="per-pupil amounts decrease down the "
                                     "ranking", cap_due_date="2026-08-10")
        issue_report(visit["id"])

        first = submit_cap(finding["id"],
                           cap_narrative="The district will revise its "
                                         "per-pupil allocation worksheet and "
                                         "resubmit ranking documentation.")
        assert first["status"] == "CAP_SUBMITTED"
        assert first["cap_attempt_count"] == 1

        returned = return_cap(finding["id"],
                              return_note="worksheet lacks board approval "
                                          "evidence")
        assert returned["status"] == "CAP_RETURNED"

        second = submit_cap(finding["id"],
                            cap_narrative="Revised plan now attaches the "
                                          "board-approved allocation "
                                          "worksheet and timeline for "
                                          "correction.")
        assert second["status"] == "CAP_SUBMITTED"
        assert second["cap_attempt_count"] == 2, \
            "the cycle re-entry is a new submission, not an idempotent replay"

        accepted = accept_cap(finding["id"])
        assert accepted["status"] == "VERIFIED"
        visit_after = validate_success(api_client.get_visit(visit["id"],
                                                            MONITOR))
        assert visit_after["status"] == "CLOSED", \
            "the last terminal finding auto-closes the visit"

    def test_returned_cap_keeps_visit_and_grant_open(self):
        """PRD §3.9: "The moment a finding reaches `VERIFIED` — or an
        observation is closed with no action — the system checks its visit:
        when that was the visit's last finding outside the terminal set
        (`VERIFIED`, `CLOSED_NO_ACTION`), the visit auto-transitions from
        `REPORT_ISSUED` to `CLOSED`."
        PRD §3.9: "`FINDINGS_OPEN` when any finding of any visit of the grant
        sits in `OPEN`, `ESCALATED`, `CAP_SUBMITTED`, or `CAP_RETURNED`;
        `CLEARED` when the grant has at least one `CLOSED` visit and no such
        finding; and `NOT_MONITORED` otherwise."

        Design: Difficulty/non_linear_state_machine/finding_cap_revision_cycle
        """
        grant = open_grant(2039, 5_000_000)
        visit = setup_visit_in_progress(grant["id"])
        finding = record_finding(visit["id"], cap_due_date="2026-08-10")
        issue_report(visit["id"])
        submit_cap(finding["id"])
        returned = return_cap(finding["id"])
        assert returned["status"] == "CAP_RETURNED"
        visit_after = validate_success(api_client.get_visit(visit["id"],
                                                            MONITOR))
        assert visit_after["status"] == "REPORT_ISSUED", \
            "CAP_RETURNED is not terminal, so the visit stays open"
        grant_after = get_grant(grant["id"])
        assert grant_after["monitoring_clearance"] == "FINDINGS_OPEN"


class TestZeroFindingAndEscalation:

    def test_zero_finding_visit_auto_closes_on_report(self):
        """PRD §3.9: "Issuing the report moves an `IN_PROGRESS` visit to
        `REPORT_ISSUED` and stamps `report_issued_at`. When the visit has no
        findings at all, it does not linger: it immediately auto-transitions
        to `CLOSED` and the grant's `monitoring_clearance` is recomputed —
        the empty-set closure."
        PRD §3.9: "`FINDINGS_OPEN` when any finding of any visit of the grant
        sits in `OPEN`, `ESCALATED`, `CAP_SUBMITTED`, or `CAP_RETURNED`;
        `CLEARED` when the grant has at least one `CLOSED` visit and no such
        finding; and `NOT_MONITORED` otherwise."

        Design: Corner/state_machines/zero_finding_visit_auto_closes_on_report
        """
        grant = open_grant(2057, 5_000_000)
        visit = setup_visit_in_progress(grant["id"],
                                        visit_end_date="2026-08-03",
                                        scope="FISCAL")
        issued = issue_report(visit["id"])
        assert issued["status"] == "CLOSED", \
            "REPORT_ISSUED -> CLOSED fires within the same request"
        grant_after = get_grant(grant["id"])
        assert grant_after["monitoring_clearance"] == "CLEARED", \
            "one CLOSED visit and no findings"

    def test_finding_escalation_clock_sweep(self):
        """PRD §3.9: "Whenever the logical clock (§2.10) is advanced to a new
        instant, the escalation sweep fires: every finding whose
        `cap_due_date` falls strictly before the new clock date and whose
        status is `OPEN` or `CAP_RETURNED` flips to `ESCALATED`, processed in
        `created_at` ascending order with `updated_at` refreshed. Findings
        already in `CAP_SUBMITTED`, `VERIFIED`, or `CLOSED_NO_ACTION` are
        never escalated. The capability returns the ids of every finding it
        escalated."

        Design: Corner/state_machines/finding_escalation_clock_sweep
        """
        grant = open_grant(2058, 5_000_000)
        visit = setup_visit_in_progress(grant["id"])
        f1 = record_finding(visit["id"], description="ranking file "
                                                     "incomplete",
                            cap_due_date="2026-08-10")
        f2 = record_finding(visit["id"], citation="34 CFR 200.78",
                            severity="OBSERVATION",
                            description="documentation format inconsistent",
                            cap_due_date="2026-08-10")
        issue_report(visit["id"])
        submit_cap(f2["id"],
                   cap_narrative="The district will standardize its "
                                 "documentation format across all Title I "
                                 "schools this quarter.")
        result = set_clock("2026-08-11T00:00:00Z")
        assert result["escalated_finding_ids"] == [f1["id"]], \
            "exactly the overdue OPEN finding is escalated"
        f1_after = validate_success(api_client.get_finding(f1["id"], MONITOR))
        assert f1_after["status"] == "ESCALATED"
        f2_after = validate_success(api_client.get_finding(f2["id"], MONITOR))
        assert f2_after["status"] == "CAP_SUBMITTED", \
            "submitted findings are never escalated"
