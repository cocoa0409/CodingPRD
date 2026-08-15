"""Late-filing penalty/interest computation and state audit cases
(PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import (
    CO,
    HA,
    READER,
    SA,
    TO,
    add_line_item,
    create_owner,
    create_property,
    create_report,
    create_rule,
    run_sweep,
    send_letter,
    set_clock,
    setup_draft_report_with_lines,
    submit_report,
)

SA_H = TEST_USERS["state_auditor_headers"]
TO_H = TEST_USERS["treasury_ops_headers"]
CO_H = TEST_USERS["compliance_officer_headers"]


class TestLatePenaltyTierAndCap:
    def test_thirty_days_late_uses_daily_rate(self, api):
        """PRD §3.8: "Otherwise the penalty picks its rate by tier: from one
        day late up to the rule's `gross_negligence_day_threshold` the per-day
        rate is `daily_penalty_cents`"
        PRD §3.8: "The cap is `penalty_cap_pct` percent of the report's
        `total_provisional_cents`, computed with floor rounding to whole cents,
        and the `penalty_cents` is the lesser of the raw amount and the cap."

        Design: Difficulty/combinatorial_formula/late_penalty_gross_tier_and_cap_interaction
        """
        setup = setup_draft_report_with_lines([2000000, 2000000])
        set_clock("2026-12-01T00:00:00Z")  # 30 days past due 2026-11-01
        submit_report(setup["report"]["id"])
        assessment = get_success_data(
            api.create_penalty_assessment(setup["report"]["id"], SA_H), 201
        )
        assert assessment["days_late"] == 30
        # 10000 * 30 = 300000; cap floor(25% * 4000000) = 1000000 not binding.
        assert assessment["penalty_cents"] == 300000
        # per-line round_half_up(2000000*1200*30/3650000) = 19726; x2 lines.
        assert assessment["interest_cents"] == 39452
        assert assessment["total_cents"] == 339452

    def test_thirty_one_days_late_applies_gross_rate_to_all_days(self, api):
        """PRD §3.8: "once the days late run strictly beyond that threshold,
        the `gross_daily_penalty_cents` rate applies — and it applies to every
        day late, not merely to the days past the threshold."

        Design: Difficulty/combinatorial_formula/late_penalty_gross_tier_and_cap_interaction
        """
        create_rule()
        owner = create_owner()
        props = [
            create_property(owner["id"], original_value_cents=2000000,
                            last_contact_date="2024-04-10")
            for _ in range(2)
        ]
        set_clock("2027-08-01T00:00:00Z")  # anniversary 2027-04-10 has passed
        run_sweep()
        for p in props:
            send_letter(p["id"])
        set_clock("2027-09-01T00:00:00Z")
        run_sweep()  # letters expire; both properties REPORTABLE
        report = create_report(report_year=2027)
        for p in props:
            add_line_item(report["id"], p["id"])
        set_clock("2027-12-02T00:00:00Z")  # 31 days past due 2027-11-01
        submit_report(report["id"])
        assessment = get_success_data(
            api.create_penalty_assessment(report["id"], SA_H), 201
        )
        assert assessment["days_late"] == 31
        # Gross rate on ALL days: 25000 * 31 = 775000, not 300000 + 25000.
        assert assessment["penalty_cents"] == 775000
        # per-line round_half_up(2000000*1200*31/3650000) = 20384; x2 lines.
        assert assessment["interest_cents"] == 40768
        assert assessment["total_cents"] == 815768


class TestLateInterestRoundingOrder:
    def _assessed_two_small_lines(self):
        setup = setup_draft_report_with_lines([33333, 33333])
        set_clock("2026-11-11T00:00:00Z")  # 10 days late
        submit_report(setup["report"]["id"])
        set_clock("2026-12-11T00:00:00Z")  # 40 interest days from due date
        return get_success_data(
            api_client.create_penalty_assessment(setup["report"]["id"], SA_H), 201
        )

    def test_per_line_round_half_up_then_sum(self, api):
        """PRD §3.8: "The assessment's `interest_cents` is the sum of those
        per-line amounts, and the rounding order is pinned: each line is
        rounded first and the rounded amounts are then summed, never the
        reverse."

        Design: Difficulty/combinatorial_formula/late_interest_round_per_line_then_sum
        """
        assessment = self._assessed_two_small_lines()
        # Per line: round_half_up(33333*1200*40/3650000) = 438; 438 + 438 = 876.
        # (Sum-then-round would give 877.)
        assert assessment["interest_cents"] == 876

    def test_penalty_cap_binds_below_raw_amount(self, api):
        """PRD §3.8: "The cap is `penalty_cap_pct` percent of the report's
        `total_provisional_cents`, computed with floor rounding to whole cents,
        and the `penalty_cents` is the lesser of the raw amount and the cap."

        Design: Difficulty/combinatorial_formula/late_interest_round_per_line_then_sum
        """
        assessment = self._assessed_two_small_lines()
        # raw 10000 * 10 = 100000; cap floor(66666 * 25 / 100) = 16666.
        assert assessment["penalty_cents"] == 16666
        assert assessment["days_late"] == 10
        assert assessment["total_cents"] == 17542


class TestOnTimeReport:
    def test_zero_days_late_zero_penalty_and_interest(self, api):
        """PRD §3.8: "The `days_late` is the number of whole days from the
        report's `due_date` to its `submitted_date`, floored at zero — a report
        submitted on or before its due date is never late, and both the penalty
        and the interest of such a report are zero."

        Design: Corner/calculations/late_penalty_zero_when_on_time
        """
        setup = setup_draft_report_with_lines([70000])
        set_clock("2026-11-01T00:00:00Z")  # exactly the due date
        submit_report(setup["report"]["id"])
        assessment = get_success_data(
            api.create_penalty_assessment(setup["report"]["id"], SA_H), 201
        )
        assert assessment["days_late"] == 0
        assert assessment["penalty_cents"] == 0
        assert assessment["interest_cents"] == 0
        assert assessment["total_cents"] == 0
        assert assessment["status"] == "ASSESSED"


class TestPenaltyWorkflow:
    def _assessed_report(self):
        setup = setup_draft_report_with_lines([500000])
        set_clock("2026-11-11T00:00:00Z")  # 10 days late
        submit_report(setup["report"]["id"])
        assessment = get_success_data(
            api_client.create_penalty_assessment(setup["report"]["id"], SA_H), 201
        )
        return setup, assessment

    def test_second_active_assessment_rejected(self, api):
        """PRD §3.8: "at most one active assessment, meaning one in `ASSESSED`
        or `DISPUTED`, may exist per report (else
        `ERR_PENALTY_ALREADY_ASSESSED`)."

        Design: Corner/errors/penalty_already_assessed_rejected
        """
        setup, _ = self._assessed_report()
        resp = api.create_penalty_assessment(setup["report"]["id"], SA_H)
        validate_error(resp, ApiErrorId.ERR_PENALTY_ALREADY_ASSESSED, 409)

    def test_dispute_uphold_pay_cycle_preserves_amounts(self, api):
        """PRD §3.8: "A `ComplianceOfficer` disputes an `ASSESSED` assessment,
        recording a `dispute_reason` and moving it to `DISPUTED`. And a
        `StateAuditor` may waive an assessment from either `ASSESSED` or
        `DISPUTED`, recording a `waiver_reason` and moving it to the terminal
        `WAIVED`; a dispute that does not persuade is instead upheld — a
        `StateAuditor` returns a `DISPUTED` assessment to `ASSESSED`, with any
        other origin refused as `ERR_PENALTY_NOT_DISPUTED`."
        PRD §3.8: "A `TreasuryOps` operator pays the assessment, moving it to
        the terminal `PAID` — any origin other than `ASSESSED` is refused with
        `ERR_PENALTY_NOT_ASSESSED`."

        Design: Corner/state_machines/penalty_dispute_uphold_pay_cycle
        """
        _, assessment = self._assessed_report()
        aid = assessment["id"]
        # days_late 10: penalty min(10000*10, floor(500000*25/100)) = 100000;
        # interest round_half_up(500000*1200*10/3650000) = 1644.
        assert assessment["days_late"] == 10
        assert assessment["penalty_cents"] == 100000
        assert assessment["interest_cents"] == 1644
        assert assessment["total_cents"] == 101644
        # uphold requires DISPUTED.
        e1 = api.uphold_penalty(aid, SA_H)
        validate_error(e1, ApiErrorId.ERR_PENALTY_NOT_DISPUTED, 409)
        disputed = get_success_data(
            api.dispute_penalty(
                aid, {"dispute_reason": "postmark proves timely mailing"}, CO_H
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        # pay requires ASSESSED.
        e2 = api.pay_penalty(aid, TO_H)
        validate_error(e2, ApiErrorId.ERR_PENALTY_NOT_ASSESSED, 409)
        upheld = get_success_data(api.uphold_penalty(aid, SA_H), 200)
        assert upheld["status"] == "ASSESSED"
        assert upheld["penalty_cents"] == 100000
        assert upheld["interest_cents"] == 1644
        paid = get_success_data(api.pay_penalty(aid, TO_H), 200)
        assert paid["status"] == "PAID"


class TestAuditCase:
    def test_lookback_overlap_closed_interval(self, api):
        """PRD §3.8: "Two non-`CLOSED` audits for the same state may not hold
        overlapping lookback windows, and touching counts as overlap — a shared
        boundary year is already an intersection — else
        `ERR_AUDIT_LOOKBACK_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_lookback_closed_interval_adjacency_is_overlap
        """
        get_success_data(
            api.create_audit_case(
                {"state_code": "CA", "lookback_start_year": 2020,
                 "lookback_end_year": 2022},
                SA_H,
            ),
            201,
        )
        touching = api.create_audit_case(
            {"state_code": "CA", "lookback_start_year": 2022,
             "lookback_end_year": 2024},
            SA_H,
        )
        validate_error(touching, ApiErrorId.ERR_AUDIT_LOOKBACK_OVERLAP, 409)
        disjoint = api.create_audit_case(
            {"state_code": "CA", "lookback_start_year": 2023,
             "lookback_end_year": 2024},
            SA_H,
        )
        validate_success(disjoint, 201)

    def test_closed_audits_no_longer_overlap(self, api):
        """PRD §3.8: "Two non-`CLOSED` audits for the same state may not hold
        overlapping lookback windows"
        PRD §3.8: "The case opens `OPENED` and advances one step per call along
        `OPENED → FIELDWORK → FINDINGS_ISSUED → CLOSED`"

        Design: Difficulty/resource_temporal_overlap/audit_lookback_closed_interval_adjacency_is_overlap
        """
        a1 = get_success_data(
            api.create_audit_case(
                {"state_code": "CA", "lookback_start_year": 2020,
                 "lookback_end_year": 2022},
                SA_H,
            ),
            201,
        )
        a3 = get_success_data(
            api.create_audit_case(
                {"state_code": "CA", "lookback_start_year": 2023,
                 "lookback_end_year": 2024},
                SA_H,
            ),
            201,
        )
        for audit in (a1, a3):
            for _ in range(3):
                get_success_data(api.advance_audit_case(audit["id"], SA_H), 200)
        # Both audits CLOSED; the previously-touching window is now allowed.
        a4 = api.create_audit_case(
            {"state_code": "CA", "lookback_start_year": 2022,
             "lookback_end_year": 2024},
            SA_H,
        )
        validate_success(a4, 201)

    def test_audit_advances_to_closed_then_locks(self, api):
        """PRD §3.8: "The case opens `OPENED` and advances one step per call
        along `OPENED → FIELDWORK → FINDINGS_ISSUED → CLOSED`; advancing a
        `CLOSED` case is impossible and is refused with
        `ERR_AUDIT_CASE_NOT_ADVANCEABLE`."
        PRD §3.8: "The estimate is the sum over all candidates, and an empty
        candidate set yields zero."

        Design: Corner/state_machines/audit_closed_lockdown
        """
        audit = get_success_data(
            api.create_audit_case(
                {"state_code": "CA", "lookback_start_year": 2019,
                 "lookback_end_year": 2021},
                SA_H,
            ),
            201,
        )
        s1 = get_success_data(api.advance_audit_case(audit["id"], SA_H), 200)
        assert s1["status"] == "FIELDWORK"
        s2 = get_success_data(api.advance_audit_case(audit["id"], SA_H), 200)
        assert s2["status"] == "FINDINGS_ISSUED"
        assert s2["estimated_exposure_cents"] == 0  # empty candidate set
        s3 = get_success_data(api.advance_audit_case(audit["id"], SA_H), 200)
        assert s3["status"] == "CLOSED"
        resp = api.advance_audit_case(audit["id"], SA_H)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_NOT_ADVANCEABLE, 409)

    def test_exposure_estimate_computed_at_findings(self, api):
        """PRD §3.8: "For each candidate, under its applicable dormancy rule:
        the missed due date is the report-window derivation of §3.2 taken
        without the roll-forward — the first eligible cycle's due date, even
        though it has passed; the days past due run from that missed date to
        the current date, floored at zero; the candidate's penalty is the
        applicable per-day rate — `daily_penalty_cents` while the days past due
        are at or below the `gross_negligence_day_threshold`,
        `gross_daily_penalty_cents` beyond it — times the days past due, capped
        at the floor of `penalty_cap_pct` percent of the property's
        `original_value_cents`"
        PRD §3.8: "A dedicated computed read of the exposure returns the
        `estimated_exposure_cents` together with the `candidate_property_ids`
        behind it."

        Design: Corner/calculations/audit_exposure_estimate_computed
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=200000,
                               last_contact_date="2021-04-01")
        run_sweep()  # DORMANT at default clock 2026-08-01; dormancy_date 2024-04-02
        audit = get_success_data(
            api.create_audit_case(
                {"state_code": "CA", "lookback_start_year": 2024,
                 "lookback_end_year": 2025},
                SA_H,
            ),
            201,
        )
        get_success_data(api.advance_audit_case(audit["id"], SA_H), 200)
        findings = get_success_data(api.advance_audit_case(audit["id"], SA_H), 200)
        assert findings["status"] == "FINDINGS_ISSUED"
        # missed due 2024-11-01; 638 days past due at 2026-08-01:
        # exposure = 200000 + min(25000*638, 50000) + round_half_up(200000*1200*638/3650000)
        #          = 200000 + 50000 + 41951 = 291951.
        assert findings["estimated_exposure_cents"] == 291951
        exposure = get_success_data(api.get_audit_exposure(audit["id"], READER), 200)
        assert exposure["estimated_exposure_cents"] == 291951
        assert exposure["candidate_property_ids"] == [prop["id"]]
