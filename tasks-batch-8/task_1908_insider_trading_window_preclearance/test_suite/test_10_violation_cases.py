"""Violation cases: severity scoring, sanctions, escalation cycles, flag cascades."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_insider,
    as_officer,
    assert_same_instant,
    case_action,
    create_current_person,
    create_officer,
    create_person,
    create_preclearance_request_payload,
    find_case_for_confirmation,
    flag_confirmation_with_case,
    get_case,
    get_person,
    get_success_data,
    ingest_confirmation,
    set_logical_clock,
    validate_error,
)


class TestSeverityScoringAndSanction:
    def _setup_flagged_case(self, api, officer_email, subject_email):
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer(officer_email)
        subject = create_person("Subject B", subject_email, department="Finance")
        conf, case = flag_confirmation_with_case(
            officer, subject, ticker="ACME", side="BUY", quantity=400, price=100.00,
            trade_date="2026-08-01T10:00:00Z", broker_ref="BR-D3",
        )
        case_action(officer, case["id"], "BEGIN_INVESTIGATION")
        return officer, subject, conf, case

    def test_severity_score_combines_base_and_value_band(self, api):
        """PRD §3.8: "The base points come from the `violation_type`: 40 for
        `BLACKOUT_TRADE`, 50 for `RESTRICTED_LIST`, 30 for `PLAN_VIOLATION`, 25 for
        `NO_PRECLEARANCE`, and 15 for `OTHER`." PRD §3.8: "Size adds a value-band
        bonus read off the linked confirmation's `trade_value`: 20 points when the
        value is at least 100,000; 10 points when it is at least 25,000 but below
        100,000; nothing below 25,000, and nothing when no confirmation is linked at
        all." PRD §3.8: "The `severity_score` is the sum of these components, capped
        at 100."

        Design: Difficulty/combinatorial_formula/sanction_severity_multi_input_scoring
        """
        officer, subject, conf, case = self._setup_flagged_case(
            api, "officer3@x.com", "subject_b@x.com"
        )
        substantiated = case_action(officer, case["id"], "SUBSTANTIATE")
        assert substantiated["status"] == "SUBSTANTIATED"
        # NO_PRECLEARANCE base 25 + value band 10 (trade_value 40,000) + 0 + 0 = 35
        assert substantiated["severity_score"] == 35

    def test_suspension_30d_band_suspends_person_thirty_days(self, api):
        """PRD §3.8: "a score of 75 or more yields `TERMINATION_REFERRAL`; 50 or
        more, `SUSPENSION_90D`; 25 or more, `SUSPENSION_30D`; below 25, `WARNING`."
        PRD §3.1: "When a sanction of `SUSPENSION_30D` or `SUSPENSION_90D` is recorded
        (§3.8), the person's `status` moves from `ACTIVE` to `SUSPENDED` and
        `suspended_until` is set to thirty or ninety days from that moment,
        respectively."

        Design: Difficulty/combinatorial_formula/sanction_severity_multi_input_scoring
        """
        officer, subject, conf, case = self._setup_flagged_case(
            api, "officer3b@x.com", "subject_b2@x.com"
        )
        case_action(officer, case["id"], "SUBSTANTIATE")
        recorded = case_action(officer, case["id"], "RECORD_SANCTION")
        assert recorded["status"] == "SANCTION_RECORDED"
        assert recorded["sanction"] == "SUSPENSION_30D"
        assert recorded["sanction_recorded_at"] is not None

        person = get_person(subject["id"])
        assert person["status"] == "SUSPENDED"
        assert_same_instant(
            person["suspended_until"], "2026-08-31T00:00:00Z", "suspended_until"
        )


class TestCaseEscalationAndFork:
    def _setup_two_cases(self, api, officer_email, subject_email):
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer(officer_email)
        subject = create_person("Subject E", subject_email, department="Finance")
        conf1, case1 = flag_confirmation_with_case(
            officer, subject, ticker="ACME", side="BUY", quantity=10, price=10.00,
            trade_date="2026-08-01T10:00:00Z", broker_ref="BR-D6-1",
        )
        conf2, case2 = flag_confirmation_with_case(
            officer, subject, ticker="BETA", side="SELL", quantity=5, price=20.00,
            trade_date="2026-08-01T11:00:00Z", broker_ref="BR-D6-2",
        )
        return officer, subject, conf1, case1, conf2, case2

    def test_case_escalation_cycle_then_substantiate(self, api):
        """PRD §3.8: "`ESCALATE` moves an `UNDER_INVESTIGATION` case to `ESCALATED`,
        and `DEESCALATE` returns an `ESCALATED` case to `UNDER_INVESTIGATION` — the
        escalation cycle can repeat as often as the facts demand. From either
        `UNDER_INVESTIGATION` or `ESCALATED`, the officer reaches a finding:
        `SUBSTANTIATE` moves the case to `SUBSTANTIATED`". PRD §3.8: "The base points
        come from the `violation_type`: 40 for `BLACKOUT_TRADE`, 50 for
        `RESTRICTED_LIST`, 30 for `PLAN_VIOLATION`, 25 for `NO_PRECLEARANCE`, and 15
        for `OTHER`."

        Design: Difficulty/non_linear_state_machine/violation_case_escalation_and_fork
        """
        officer, subject, conf1, case1, conf2, case2 = self._setup_two_cases(
            api, "officer6@x.com", "subject_e@x.com"
        )
        case_action(officer, case1["id"], "BEGIN_INVESTIGATION")
        escalated = case_action(officer, case1["id"], "ESCALATE")
        assert escalated["status"] == "ESCALATED"
        back = case_action(officer, case1["id"], "DEESCALATE")
        assert back["status"] == "UNDER_INVESTIGATION"
        substantiated = case_action(officer, case1["id"], "SUBSTANTIATE")
        assert substantiated["status"] == "SUBSTANTIATED"
        # NO_PRECLEARANCE 25 + value 100 below band + EMPLOYEE + no repeats = 25
        assert substantiated["severity_score"] == 25

    def test_unfounded_fork_close_clears_confirmation(self, api):
        """PRD §3.8: "From either `UNDER_INVESTIGATION` or `ESCALATED`, the officer
        reaches a finding: `SUBSTANTIATE` moves the case to `SUBSTANTIATED`, while
        `UNFOUND` moves it to `UNFOUNDED`." PRD §3.8: "An `UNFOUNDED` case also closes
        via `CLOSE`." PRD §3.8: "Closing an `UNFOUNDED` case does that and one thing
        more: the linked confirmation, if still `FLAGGED`, moves to `CLEARED`."

        Design: Difficulty/non_linear_state_machine/violation_case_escalation_and_fork
        """
        officer, subject, conf1, case1, conf2, case2 = self._setup_two_cases(
            api, "officer6b@x.com", "subject_e2@x.com"
        )
        case_action(officer, case2["id"], "BEGIN_INVESTIGATION")
        unfounded = case_action(officer, case2["id"], "UNFOUND")
        assert unfounded["status"] == "UNFOUNDED"
        closed = case_action(officer, case2["id"], "CLOSE")
        assert closed["status"] == "CLOSED"

        conf = get_success_data(
            api.get_trade_confirmation(conf2["id"], as_officer(officer))
        )
        assert conf["status"] == "CLEARED"


class TestFlagCascadeComplianceHold:
    def test_flagged_confirmation_auto_opens_violation_case(self, api):
        """PRD §3.7: "Flagging fires an atomic cascade: a violation case opens
        against the insider with `violation_type` equal to the flagged reason,
        `source` `AUTO_FLAG`, `status` `OPENED`, and a `trade_confirmation_id`
        back-reference".

        Design: Difficulty/transitive_cascade/confirmation_flag_to_case_to_compliance_hold
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer7@x.com")
        subject = create_current_person("Subject F", "subject_f@x.com",
                                        department="Sales")
        conf = ingest_confirmation(
            officer, subject, ticker="BETA", side="BUY", quantity=25, price=40.00,
            trade_date="2026-08-01T10:00:00Z", broker_ref="BR-D7",
        )
        assert conf["status"] == "FLAGGED"
        assert conf["flagged_reason"] == "NO_PRECLEARANCE"

        case = find_case_for_confirmation(officer, conf["id"])
        assert case["status"] == "OPENED"
        assert case["source"] == "AUTO_FLAG"
        assert case["violation_type"] == "NO_PRECLEARANCE"
        assert case["trade_confirmation_id"] == conf["id"]

    def test_open_case_sets_hold_blocking_new_submission(self, api):
        """PRD §3.7: "the insider's `compliance_hold` recomputes to true, immediately
        gating their new preclearance submissions and plan creations with
        `ERR_COMPLIANCE_HOLD`." PRD §3.1: "A third computed flag, `compliance_hold`,
        is true exactly when the person has a violation case in any of `OPENED`,
        `UNDER_INVESTIGATION`, `ESCALATED`, `SUBSTANTIATED`, or `SANCTION_RECORDED`."

        Design: Difficulty/transitive_cascade/confirmation_flag_to_case_to_compliance_hold
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer7b@x.com")
        subject = create_current_person("Subject F2", "subject_f2@x.com",
                                        department="Sales")
        conf = ingest_confirmation(
            officer, subject, ticker="BETA", side="BUY", quantity=25, price=40.00,
            trade_date="2026-08-01T10:00:00Z", broker_ref="BR-D7",
        )
        assert conf["status"] == "FLAGGED"
        assert get_person(subject["id"])["compliance_hold"] is True

        resp = api.create_preclearance_request(
            create_preclearance_request_payload(
                covered_person_id=subject["id"],
                security_ticker="GAMMA",
                trade_side="BUY",
                quantity=10,
                proposed_trade_date="2026-08-20T00:00:00Z",
            ),
            as_insider(subject),
        )
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD)


class TestDuplicateCase:
    def test_duplicate_open_case_for_confirmation_rejected(self, api):
        """PRD §3.8: "One confirmation, one open case: if a case not yet `CLOSED`
        already references the same `trade_confirmation_id`, creation is rejected
        with `ERR_CASE_ALREADY_OPEN`."

        Design: Corner/errors/manual_case_duplicate_for_confirmation_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_e3@x.com")
        subject = create_person("Subject E3", "subject_e3@x.com")
        conf = ingest_confirmation(
            officer, subject, ticker="ACME", side="BUY", quantity=10, price=10.00,
            trade_date="2026-08-01T10:00:00Z", broker_ref="BR-C-E3",
        )
        assert conf["status"] == "FLAGGED"

        resp = api.create_violation_case(
            {
                "covered_person_id": subject["id"],
                "violation_type": "NO_PRECLEARANCE",
                "trade_confirmation_id": conf["id"],
            },
            as_officer(officer),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_OPEN)
