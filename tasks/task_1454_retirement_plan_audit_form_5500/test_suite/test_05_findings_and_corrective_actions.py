"""Findings, late-deposit confirmations, and the corrective-action loop."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    SPONSOR,
    ApiErrorId,
    acknowledge_finding,
    add_participant,
    api_client,
    approve_action,
    create_engagement,
    create_engagement_in_report_issued,
    create_filing_ready_to_file,
    create_late_assessment,
    create_manual_finding,
    create_small_plan_engagement,
    execute_action,
    get_single_finding,
    get_success_data,
    propose_action,
    propose_approved_action,
    set_clock,
    setup_acknowledged_finding,
    setup_confirmed_late_deposit,
    setup_executed_action,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWaivers:

    def test_high_finding_not_waivable_but_low_is(self):
        """PRD §3.6: "An `EngagementManager` may waive a finding, but only a
        non-`HIGH` one: waiving a finding of `severity` `HIGH` is rejected with
        `ERR_WAIVER_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/state_machines/waive_high_severity_finding_rejected
        """
        eng = create_engagement()
        high = create_manual_finding(
            eng["id"], category="LATE_REMITTANCE", severity="HIGH",
            description="chronic late remittance")
        low = create_manual_finding(
            eng["id"], category="FILING_DEFECT", severity="LOW", description="cosmetic")
        resp = api_client.waive_finding(high["id"], {"justification": "immaterial"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ALLOWED)
        high_now = get_success_data(api_client.get_finding(high["id"], SPONSOR))
        assert high_now["status"] == "OPEN"
        waived = validate_success(api_client.waive_finding(
            low["id"], {"justification": "immaterial and corrected informally"}, MANAGER))
        assert waived["status"] == "WAIVED"


class TestCorrectiveActionGates:

    def test_action_on_waived_finding_rejected(self):
        """PRD §3.7: "A corrective action may be proposed against a finding in
        `OPEN`, `ACKNOWLEDGED`, or `CORRECTION_IN_PROGRESS` status; proposing one
        against a finding that is `CORRECTED`, `VERIFIED_CLOSED`, or `WAIVED` is
        rejected with `ERR_CORRECTION_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/validations/corrective_action_on_waived_finding_rejected
        """
        eng = create_engagement()
        finding = create_manual_finding(
            eng["id"], category="FILING_DEFECT", severity="LOW", description="cosmetic")
        get_success_data(api_client.waive_finding(
            finding["id"], {"justification": "immaterial"}, MANAGER))
        resp = api_client.create_corrective_action(
            {
                "engagement_id": eng["id"],
                "finding_id": finding["id"],
                "action_type": "FEE_REDISCLOSURE",
                "principal_cents": 100,
                "planned_execution_date": "2026-04-01",
            },
            SPONSOR,
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_NOT_ALLOWED)

    def test_lost_earnings_requires_confirmed_assessment(self):
        """PRD §3.7: "A `LOST_EARNINGS_DEPOSIT` requires an `assessment_id`
        pointing at a `LateContributionAssessment` that is in `CONFIRMED` status;
        referencing an assessment that is not confirmed is rejected with
        `ERR_ASSESSMENT_NOT_CONFIRMED` (HTTP 409)."

        Design: Corner/validations/lost_earnings_action_requires_confirmed_assessment
        """
        eng, participant = create_small_plan_engagement()
        _contribution, assessment = create_late_assessment(
            eng["id"], participant["id"], amount_cents=100_000)
        assert assessment is not None
        assert assessment["status"] == "ASSESSED"
        finding = create_manual_finding(
            eng["id"], category="LATE_REMITTANCE", severity="MEDIUM",
            description="manual companion finding")
        acknowledge_finding(finding["id"])
        resp = api_client.create_corrective_action(
            {
                "engagement_id": eng["id"],
                "finding_id": finding["id"],
                "action_type": "LOST_EARNINGS_DEPOSIT",
                "principal_cents": 100_000,
                "planned_execution_date": "2026-02-27",
                "assessment_id": assessment["id"],
            },
            SPONSOR,
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_CONFIRMED)
        assessment_now = get_success_data(
            api_client.get_late_contribution_assessment(assessment["id"], SPONSOR))
        assert assessment_now["status"] == "ASSESSED"

    def test_approve_blocked_until_finding_acknowledged(self):
        """PRD §3.7: "An `EngagementManager` approves a `PROPOSED` action, but
        only when two conditions hold: the linked finding must be in
        `ACKNOWLEDGED` or `CORRECTION_IN_PROGRESS` status, otherwise the approval
        is rejected with `ERR_CORRECTION_NOT_ALLOWED`".

        Design: Difficulty/cross_entity_state_dependency/action_approve_requires_acknowledged_finding
        """
        eng = create_engagement()
        finding = create_manual_finding(
            eng["id"], category="FEE_DISCLOSURE_GAP", severity="MEDIUM",
            description="Missing indirect comp detail")
        assert finding["status"] == "OPEN"
        # Proposal against an OPEN finding is allowed; approval is the gated step.
        action = propose_action(
            eng["id"], finding["id"], action_type="FEE_REDISCLOSURE",
            principal_cents=100, planned_execution_date="2026-04-01")
        assert action["status"] == "PROPOSED"
        resp = api_client.approve_corrective_action(action["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CORRECTION_NOT_ALLOWED)
        action_now = get_success_data(api_client.get_corrective_action(action["id"], SPONSOR))
        assert action_now["status"] == "PROPOSED"
        finding_now = get_success_data(api_client.get_finding(finding["id"], SPONSOR))
        assert finding_now["status"] == "OPEN"

    def test_approve_succeeds_on_acknowledged_finding(self):
        """PRD §3.7: "A successful approval sets the action's
        `approved_by_user_id`, moves the action to `APPROVED`, and moves the
        linked finding from `ACKNOWLEDGED` to `CORRECTION_IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/action_approve_requires_acknowledged_finding
        """
        ctx = setup_acknowledged_finding(
            severity="MEDIUM", category="FEE_DISCLOSURE_GAP",
            description="Missing indirect comp detail")
        action = propose_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="FEE_REDISCLOSURE", principal_cents=100,
            planned_execution_date="2026-04-01")
        approved = validate_success(api_client.approve_corrective_action(action["id"], MANAGER))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] is not None
        finding_now = get_success_data(api_client.get_finding(ctx["finding"]["id"], SPONSOR))
        assert finding_now["status"] == "CORRECTION_IN_PROGRESS"


class TestDistributionBalanceGuard:

    def test_distribution_exceeding_balance_rejected(self):
        """PRD §3.7: "For a `CORRECTIVE_DISTRIBUTION`, there is a sufficiency
        guard: the action's `total_amount_cents` may not exceed the participant's
        `account_balance_cents`, and an execution that would overdraw the balance
        is rejected with `ERR_DISTRIBUTION_EXCEEDS_BALANCE` (HTTP 422)."

        Design: Corner/validations/distribution_exceeding_balance_rejected
        """
        ctx = setup_acknowledged_finding(
            severity="MEDIUM", description="refund due",
            participant_opening_balance=4_000)
        action = propose_approved_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="CORRECTIVE_DISTRIBUTION", principal_cents=5_000,
            planned_execution_date="2026-03-01",
            participant_id=ctx["participant"]["id"])
        resp = api_client.execute_corrective_action(action["id"], SPONSOR)
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_EXCEEDS_BALANCE)
        action_now = get_success_data(api_client.get_corrective_action(action["id"], SPONSOR))
        assert action_now["status"] == "APPROVED"
        participant_now = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert participant_now["account_balance_cents"] == 4_000


class TestLostEarningsVariants:
    """Two rounding-pinned variants of the lost-earnings computation."""

    def test_vfcp_variant_earnings(self):
        """PRD §3.7: "Under the `VFCP` variant the annual rate applied to both
        segments is 8.0 percent (the IRS underpayment rate); under the `EPCRS`
        variant it is 5.0 percent (the plan's actual earnings rate proxy), so
        identical dates and principal yield a lower figure under `EPCRS`."
        PRD §3.7: "Each segment's earnings are the principal multiplied by the
        rate (expressed as a percentage, so divided by 100), multiplied by the
        number of days in the segment, and divided by a 365-day year basis."

        Principal 200000c, payroll 2026-01-15, deposit 2026-01-29 (14 days),
        correction 2026-03-31 (61 days):
        seg1 = round(200000*8/100*14/365) = round(613.70) = 614;
        seg2 = round(200000*8/100*61/365) = round(2673.97) = 2674; total 3288.

        Design: Difficulty/dual_variant_calc/lost_earnings_vfcp_vs_epcrs
        """
        ctx = setup_confirmed_late_deposit(
            payroll_date="2026-01-15", deposit_date="2026-01-29",
            amount_cents=200_000)
        set_clock("2026-03-31T00:00:00Z")
        action = propose_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="LOST_EARNINGS_DEPOSIT", principal_cents=200_000,
            planned_execution_date="2026-03-31",
            assessment_id=ctx["assessment"]["id"], earnings_variant="VFCP")
        assert action["earnings_cents"] == 3288
        assert action["total_amount_cents"] == 203_288

    def test_epcrs_variant_earnings_lower(self):
        """PRD §3.7: "under the `EPCRS` variant it is 5.0 percent (the plan's
        actual earnings rate proxy), so identical dates and principal yield a
        lower figure under `EPCRS`."

        Same dates and principal as the VFCP sibling: seg1 = round(383.56) = 384;
        seg2 = round(1671.23) = 1671; total 2055 < 3288.

        Design: Difficulty/dual_variant_calc/lost_earnings_vfcp_vs_epcrs
        """
        ctx = setup_confirmed_late_deposit(
            payroll_date="2026-01-15", deposit_date="2026-01-29",
            amount_cents=200_000)
        set_clock("2026-03-31T00:00:00Z")
        action = propose_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="LOST_EARNINGS_DEPOSIT", principal_cents=200_000,
            planned_execution_date="2026-03-31",
            assessment_id=ctx["assessment"]["id"], earnings_variant="EPCRS")
        assert action["earnings_cents"] == 2055
        assert action["total_amount_cents"] == 202_055

    def test_per_segment_rounding_not_sum_then_round(self):
        """PRD §3.7: "The rounding order is pinned and significant: each segment
        is rounded half-up to whole cents first, and then the two rounded segments
        are summed to produce `earnings_cents`. Rounding the segments first and
        then summing is not the same as summing the raw values and then rounding,
        and the system always rounds per segment."

        Principal 100000c at 8.0%: 10-day segment accrues 219.178c -> 219;
        20-day segment accrues 438.356c -> 438; per-segment total 657.
        Sum-then-round would give round(657.534) = 658.

        Design: Difficulty/combinatorial_formula/lost_earnings_per_segment_rounding
        """
        ctx = setup_confirmed_late_deposit(
            payroll_date="2026-01-05", deposit_date="2026-01-15",
            amount_cents=100_000)
        set_clock("2026-02-04T00:00:00Z")
        action = propose_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="LOST_EARNINGS_DEPOSIT", principal_cents=100_000,
            planned_execution_date="2026-02-04",
            assessment_id=ctx["assessment"]["id"], earnings_variant="VFCP")
        assert action["earnings_cents"] == 657
        assert action["earnings_cents"] != 658, "sum-then-round must NOT be used"
        assert action["total_amount_cents"] == 100_657

    def test_per_segment_rounding_both_segments_round_up(self):
        """PRD §3.7: "each segment is rounded half-up to whole cents first, and
        then the two rounded segments are summed to produce `earnings_cents`. ...
        the system always rounds per segment."

        Principal 100000c at 8.0%: 30-day segment accrues 657.534c -> 658;
        25-day segment accrues 547.945c -> 548; per-segment total 1206.
        Sum-then-round would give round(1205.479) = 1205.

        Design: Difficulty/combinatorial_formula/lost_earnings_per_segment_rounding
        """
        ctx = setup_confirmed_late_deposit(
            payroll_date="2026-02-02", deposit_date="2026-03-04",
            amount_cents=100_000)
        set_clock("2026-03-29T00:00:00Z")
        action = propose_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="LOST_EARNINGS_DEPOSIT", principal_cents=100_000,
            planned_execution_date="2026-03-29",
            assessment_id=ctx["assessment"]["id"], earnings_variant="VFCP")
        assert action["earnings_cents"] == 1206
        assert action["earnings_cents"] != 1205, "sum-then-round must NOT be used"
        assert action["total_amount_cents"] == 101_206


class TestConfirmCascade:

    def test_confirm_high_severity_blocks_and_reverts_filing(self):
        """PRD §3.4: "A `PlanAuditor` confirms an assessment, moving it from
        `ASSESSED` to `CONFIRMED`; this auto-creates an `AuditFinding` whose
        `source` is `LATE_DEPOSIT_AUTO`, whose `category` is `LATE_REMITTANCE`,
        whose `severity` is taken from the assessment's `severity_hint`, whose
        `status` is `OPEN`, and whose `contribution_id` is the assessment's
        contribution."
        PRD §3.4: "The new `OPEN` finding recomputes the engagement's `posture` —
        a `HIGH` severity forces `BLOCKED` — and a posture entering `BLOCKED`
        reverts any `READY_TO_FILE` filing to `SCHEDULES_COMPLETE`."

        Deposit 20 business days after payroll -> 13 days late -> severity HIGH.

        Design: Difficulty/transitive_cascade/late_deposit_confirm_cascade
        """
        eng, participant = create_engagement_in_report_issued()
        contribution, assessment = create_late_assessment(
            eng["id"], participant["id"],
            payroll_date="2025-06-16", deposit_date="2025-07-14",
            amount_cents=300_000)
        assert assessment is not None
        assert assessment["business_days_late"] == 13
        assert assessment["severity_hint"] == "HIGH"
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        assert filing["status"] == "READY_TO_FILE"
        confirmed = validate_success(
            api_client.confirm_late_contribution_assessment(assessment["id"], AUDITOR))
        assert confirmed["status"] == "CONFIRMED"
        findings, meta = validate_paginated(api_client.list_findings(
            SPONSOR, params={"engagement_id": eng["id"], "category": "LATE_REMITTANCE"}))
        assert len(findings) == 1
        finding = findings[0]
        assert finding["source"] == "LATE_DEPOSIT_AUTO"
        assert finding["category"] == "LATE_REMITTANCE"
        assert finding["severity"] == "HIGH"
        assert finding["status"] == "OPEN"
        assert finding["contribution_id"] == contribution["id"]
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "BLOCKED"
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "SCHEDULES_COMPLETE"

    def test_confirm_medium_severity_keeps_filing_ready(self):
        """PRD §2.9: "If none of the `BLOCKED` conditions holds, the posture is
        `AT_RISK` when either (a) any `AuditFinding` of the engagement is in one
        of `OPEN`, `ACKNOWLEDGED`, `CORRECTION_IN_PROGRESS`, or `CORRECTED`
        status, or (b) a filing exists whose logical clock date is later than its
        `effective_due_date` while its status is not `FILED` or `ACCEPTED`."
        PRD §2.9: "Entering the `BLOCKED` posture carries a specific side effect:
        any filing of the engagement that is in `READY_TO_FILE` is automatically
        reverted to `SCHEDULES_COMPLETE`."

        Deposit 10 business days after payroll -> 3 days late -> severity MEDIUM:
        the auto-created OPEN MEDIUM finding drives AT_RISK, not BLOCKED, so the
        READY_TO_FILE filing is not reverted.

        Design: Difficulty/transitive_cascade/late_deposit_confirm_cascade
        """
        eng, participant = create_engagement_in_report_issued()
        _contribution, assessment = create_late_assessment(
            eng["id"], participant["id"],
            payroll_date="2025-06-16", deposit_date="2025-06-30",
            amount_cents=300_000)
        assert assessment is not None
        assert assessment["business_days_late"] == 3
        assert assessment["severity_hint"] == "MEDIUM"
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        # Keep the deadline armer out of the picture: submit window still open.
        set_clock("2026-07-15T00:00:00Z")
        confirmed = validate_success(
            api_client.confirm_late_contribution_assessment(assessment["id"], AUDITOR))
        assert confirmed["status"] == "CONFIRMED"
        finding = get_single_finding(eng["id"], category="LATE_REMITTANCE")
        assert finding["severity"] == "MEDIUM"
        assert finding["status"] == "OPEN"
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "AT_RISK"
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "READY_TO_FILE"


class TestContributionParallelDimensions:

    def test_match_and_scan_move_independent_dimensions(self):
        """PRD §3.4: "A contribution carries two independent state dimensions that
        evolve in parallel and never gate one another. The first dimension,
        `match_status`, begins at `UNMATCHED` and tracks trust reconciliation. The
        second, `timeliness_status`, begins at `PENDING` and tracks remittance
        timing."

        Design: Difficulty/non_linear_state_machine/contribution_parallel_state_dimensions
        """
        eng, participant = create_small_plan_engagement(
            participant_opening_balance=1_000_000)
        participant = get_success_data(api_client.update_participant(
            participant["id"], {"deferral_amount_cy_cents": 500_000}, SPONSOR))
        statement = get_success_data(api_client.create_trust_statement(
            {
                "engagement_id": eng["id"],
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "custodian": "National Trust Co",
                "certification": "CERTIFIED",
                "reported_deposit_total_cents": 500_000,
            },
            SPONSOR,
        ))
        contribution = get_success_data(api_client.create_contribution(
            {
                "engagement_id": eng["id"],
                "participant_id": participant["id"],
                "type": "ELECTIVE_DEFERRAL",
                "payroll_date": "2025-06-16",
                "deposit_date": "2025-06-30",
                "amount_cents": 500_000,
            },
            SPONSOR,
        ))
        assert contribution["match_status"] == "UNMATCHED"
        assert contribution["timeliness_status"] == "PENDING"
        matched = get_success_data(api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR))
        assert matched["match_status"] == "MATCHED"
        assert matched["timeliness_status"] == "PENDING", (
            "matching must not touch the timeliness dimension"
        )
        get_success_data(api_client.late_deposit_scan(eng["id"], AUDITOR))
        after_scan = get_success_data(api_client.get_contribution(contribution["id"], SPONSOR))
        assert after_scan["timeliness_status"] == "LATE"
        assert after_scan["match_status"] == "MATCHED", (
            "the scan must not touch the match dimension"
        )
        unmatched = get_success_data(api_client.unmatch_contribution(contribution["id"], SPONSOR))
        assert unmatched["match_status"] == "UNMATCHED"
        assert unmatched["timeliness_status"] == "LATE", (
            "unmatching must not touch the timeliness dimension"
        )

    def test_correction_moves_timeliness_only_and_completes_loop(self):
        """PRD §3.4: "an assessment in `CONFIRMED` moves automatically to
        `CORRECTED` when its linked lost-earnings corrective action reaches
        `EXECUTED`."
        PRD §3.7: "Execution also cascades the correction loop forward: any linked
        `LateContributionAssessment` moves automatically to `CORRECTED`, the linked
        contribution's `timeliness_status` moves to `CORRECTED`, and the linked
        finding moves automatically to `CORRECTED` once all of its linked
        non-`REJECTED`, non-`VOIDED` corrective actions have reached `EXECUTED` or
        `VERIFIED`, provided at least one such action exists."

        Contribution: 500000c, payroll 2025-06-16, deposit 2025-06-30 (10 business
        days -> LATE by 3, severity MEDIUM); correction date 2026-02-27:
        seg1 = round(40000*14/365) = 1534; seg2 = round(40000*242/365) = 26521;
        earnings 28055, total 528055.

        Design: Difficulty/non_linear_state_machine/contribution_parallel_state_dimensions
        """
        ctx = setup_confirmed_late_deposit(
            payroll_date="2025-06-16", deposit_date="2025-06-30",
            amount_cents=500_000, participant_opening_balance=1_000_000)
        action = propose_approved_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="LOST_EARNINGS_DEPOSIT", principal_cents=500_000,
            planned_execution_date="2026-02-27",
            assessment_id=ctx["assessment"]["id"], earnings_variant="VFCP")
        assert action["earnings_cents"] == 28055
        assert action["total_amount_cents"] == 528_055
        set_clock("2026-02-27T00:00:00Z")
        executed = execute_action(action["id"])
        assert executed["status"] == "EXECUTED"
        contribution_now = get_success_data(
            api_client.get_contribution(ctx["contribution"]["id"], SPONSOR))
        assert contribution_now["timeliness_status"] == "CORRECTED"
        assert contribution_now["match_status"] == "UNMATCHED", (
            "the timeliness correction must not touch the match dimension"
        )
        assert contribution_now["business_days_elapsed"] == 10
        assessment_now = get_success_data(
            api_client.get_late_contribution_assessment(ctx["assessment"]["id"], SPONSOR))
        assert assessment_now["status"] == "CORRECTED"
        assert assessment_now["business_days_late"] == 3
        assert assessment_now["severity_hint"] == "MEDIUM"
        finding_now = get_success_data(api_client.get_finding(ctx["finding"]["id"], SPONSOR))
        assert finding_now["status"] == "CORRECTED"


class TestExecuteVoidBalanceIdentity:

    def test_execute_then_void_restores_balance_exactly(self):
        """PRD §3.7: "The participant's `account_balance_cents` is reversed by
        exactly `total_amount_cents` — deposit types are debited back and
        distributions are credited back — so the balance returns to its
        pre-execution figure."
        PRD §3.7: "A linked finding that had reached `CORRECTED` reverts to
        `CORRECTION_IN_PROGRESS`, reopening the correction loop."

        Design: Difficulty/compensating_invariant/execute_void_corrective_distribution_balance_identity
        """
        ctx = setup_acknowledged_finding(
            severity="MEDIUM", description="ADP excess refund",
            participant_opening_balance=100_000)
        action = propose_approved_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="CORRECTIVE_DISTRIBUTION", principal_cents=5_000,
            planned_execution_date="2026-03-01",
            participant_id=ctx["participant"]["id"])
        set_clock("2026-03-01T00:00:00Z")
        executed = execute_action(action["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["executed_date"] == "2026-03-01"
        # Executed 2026-03-01, within 2.5 months of plan_year_end 2026-01-01.
        assert executed["excise_tax_cents"] == 0
        after_exec = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert after_exec["account_balance_cents"] == 95_000
        voided = validate_success(api_client.void_corrective_action(
            action["id"], {"reason": "posted in error"}, MANAGER))
        assert voided["status"] == "VOIDED"
        after_void = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert after_void["account_balance_cents"] == 100_000, (
            "void must restore the pre-execution balance with zero drift"
        )
        finding_now = get_success_data(api_client.get_finding(ctx["finding"]["id"], SPONSOR))
        assert finding_now["status"] == "CORRECTION_IN_PROGRESS"

    def test_execute_then_void_deposit_type_restores_balance(self):
        """PRD §3.7: "The participant's `account_balance_cents` is reversed by
        exactly `total_amount_cents` — deposit types are debited back and
        distributions are credited back — so the balance returns to its
        pre-execution figure."
        PRD §3.7: "deposit-type actions (the lost-earnings deposit and the
        QNEC/QMAC contributions) credit the participant's `account_balance_cents`".

        Design: Difficulty/compensating_invariant/execute_void_corrective_distribution_balance_identity
        """
        ctx = setup_acknowledged_finding(
            severity="HIGH", category="NONDISCRIMINATION_FAILURE",
            description="ADP failure", participant_opening_balance=100_000)
        action = propose_approved_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="QNEC_CONTRIBUTION", principal_cents=8_000,
            planned_execution_date="2026-03-01",
            participant_id=ctx["participant"]["id"])
        set_clock("2026-03-01T00:00:00Z")
        execute_action(action["id"])
        after_exec = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert after_exec["account_balance_cents"] == 108_000
        voided = validate_success(api_client.void_corrective_action(
            action["id"], {"reason": "posted in error"}, MANAGER))
        assert voided["status"] == "VOIDED"
        after_void = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert after_void["account_balance_cents"] == 100_000


class TestPostureRecovery:

    def test_posture_recovers_after_finding_verified_closed(self):
        """PRD §2.9: "The posture is `BLOCKED` when any of the following holds:
        (a) any `AuditFinding` of the engagement is in `OPEN` status with
        `severity` `HIGH`; ... Otherwise the posture is `ON_TRACK`."
        PRD §3.7: "A corrected finding is closed by a `PlanAuditor`, who verifies
        and closes it — but only when all of its linked non-`VOIDED` corrective
        actions are in `VERIFIED` status; otherwise the close is rejected with
        `ERR_INVALID_STATE_TRANSITION`. A successful close moves the finding from
        `CORRECTED` to `VERIFIED_CLOSED` and recomputes the posture."

        Design: Corner/complexity_layers/posture_recovers_after_finding_verified_closed
        """
        ctx = setup_acknowledged_finding(
            severity="HIGH", category="NONDISCRIMINATION_FAILURE",
            description="ADP failure", participant_opening_balance=100_000)
        eng_now = get_success_data(api_client.get_engagement(ctx["engagement"]["id"], SPONSOR))
        assert eng_now["posture"] == "AT_RISK"  # ACKNOWLEDGED finding, none OPEN
        # Reopen to OPEN would block; instead proceed through the correction loop.
        action = propose_approved_action(
            ctx["engagement"]["id"], ctx["finding"]["id"],
            action_type="CORRECTIVE_DISTRIBUTION", principal_cents=5_000,
            planned_execution_date="2026-03-01",
            participant_id=ctx["participant"]["id"])
        set_clock("2026-03-01T00:00:00Z")
        execute_action(action["id"])
        verified = validate_success(api_client.verify_corrective_action(action["id"], AUDITOR))
        assert verified["status"] == "VERIFIED"
        closed = validate_success(api_client.verify_close_finding(ctx["finding"]["id"], AUDITOR))
        assert closed["status"] == "VERIFIED_CLOSED"
        eng_final = get_success_data(api_client.get_engagement(ctx["engagement"]["id"], SPONSOR))
        assert eng_final["posture"] == "ON_TRACK"
        participant_now = get_success_data(
            api_client.get_participant(ctx["participant"]["id"], SPONSOR))
        assert participant_now["account_balance_cents"] == 95_000
