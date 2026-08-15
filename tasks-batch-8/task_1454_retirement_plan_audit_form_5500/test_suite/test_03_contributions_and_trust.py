"""Contributions, trust-statement reconciliation, and the late-deposit scan."""
from test_helpers import (
    MANAGER,
    SPONSOR,
    TPA,
    ApiErrorId,
    add_participant,
    api_client,
    assert_reconciliation_identity,
    create_contribution_payload,
    create_engagement,
    create_late_assessment,
    create_small_plan_engagement,
    create_trust_statement_payload,
    get_single_assessment,
    get_success_data,
    recompute_count,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestContributionInputValidation:

    def test_contribution_invalid_type_rejected(self):
        """PRD §3.4: "A `SponsorAdmin` records a contribution against an
        `engagement_id` and a `participant_id` — the participant must belong to
        the same engagement — with a `type` of `ELECTIVE_DEFERRAL`,
        `EMPLOYER_MATCH`, `EMPLOYER_PROFIT_SHARING`, or `ROLLOVER`".
        PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request".

        Design: Corner/entities/contribution_invalid_enum_rejected
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001")
        resp = api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"], type="EMPLOYER_SAFE_HARBOR"),
            SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_deposit_before_payroll_rejected(self):
        """PRD §3.4: "A `deposit_date` earlier than the `payroll_date` is rejected
        with `ERR_INVALID_DATE_ORDER` (HTTP 422)."

        Design: Corner/validations/contribution_deposit_before_payroll_rejected
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001")
        resp = api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"],
                payroll_date="2025-06-16", deposit_date="2025-06-10"),
            SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_ORDER, expected_status=422)


class TestTrustStatementOverlap:

    def test_shared_boundary_day_rejected(self):
        """PRD §3.4: "Two statements of the same engagement may not have
        overlapping closed intervals; an adjacency in which the next statement's
        `period_start` is exactly one day after the prior statement's `period_end`
        is permitted, but a true overlap is rejected with
        `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/trust_statement_closed_interval_overlap
        """
        eng = create_engagement()
        get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(
                eng["id"], period_start="2025-01-01", period_end="2025-06-30"),
            SPONSOR))
        # Closed intervals: 2025-06-30 belongs to both statements -> true overlap.
        resp = api_client.create_trust_statement(
            create_trust_statement_payload(
                eng["id"], period_start="2025-06-30", period_end="2025-12-31"),
            SPONSOR)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)

    def test_day_after_adjacency_accepted(self):
        """PRD §3.4: "an adjacency in which the next statement's `period_start`
        is exactly one day after the prior statement's `period_end` is permitted".

        Design: Difficulty/resource_temporal_overlap/trust_statement_closed_interval_overlap
        """
        eng = create_engagement()
        first = get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(
                eng["id"], period_start="2025-01-01", period_end="2025-06-30"),
            SPONSOR))
        assert first["status"] == "IMPORTED"
        second = validate_success(
            api_client.create_trust_statement(
                create_trust_statement_payload(
                    eng["id"], period_start="2025-07-01", period_end="2025-12-31"),
                SPONSOR),
            expected_status=201)
        assert second["status"] == "IMPORTED"


class TestMatchingAndReconciliation:

    def test_match_outside_statement_period_rejected(self):
        """PRD §3.4: "the contribution's `deposit_date` must fall within the
        statement's closed interval from `period_start` to `period_end`; a deposit
        date outside that interval, or a statement of a different engagement, is
        rejected with `ERR_STATEMENT_PERIOD_MISMATCH` (HTTP 422)."

        Design: Corner/validations/match_outside_statement_period_rejected
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001")
        statement = get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(
                eng["id"], period_start="2025-01-01", period_end="2025-06-30",
                reported_deposit_total_cents=100_000),
            SPONSOR))
        contribution = get_success_data(api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"],
                payroll_date="2025-08-01", deposit_date="2025-08-15"),
            SPONSOR))
        resp = api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_MISMATCH)
        contribution_now = get_success_data(
            api_client.get_contribution(contribution["id"], SPONSOR))
        assert contribution_now["match_status"] == "UNMATCHED"

    def test_match_response_and_statement_reflect_side_effects_immediately(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "A successful match sets the contribution's `trust_statement_id`,
        moves `match_status` to `MATCHED`, adds the contribution's `amount_cents`
        to the statement's `matched_contribution_cents`, recomputes the statement's
        `unreconciled_deposit_cents`, and recomputes the participant's
        `account_balance_cents` to include the now-matched contribution."

        Design: Corner/consistency_model/mutation_response_immediately_reflects_side_effects
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001", deferral_amount_cy_cents=250_000)
        statement = get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(eng["id"], reported_deposit_total_cents=250_000),
            SPONSOR))
        contribution = get_success_data(api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"],
                payroll_date="2025-06-16", deposit_date="2025-06-20",
                amount_cents=250_000),
            SPONSOR))
        matched = validate_success(api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR))
        assert matched["match_status"] == "MATCHED"
        assert matched["trust_statement_id"] == statement["id"]
        statement_now = get_success_data(
            api_client.get_trust_statement(statement["id"], SPONSOR))
        assert statement_now["matched_contribution_cents"] == 250_000
        assert statement_now["unreconciled_deposit_cents"] == 0
        participant_now = get_success_data(
            api_client.get_participant(participant["id"], SPONSOR))
        assert participant_now["account_balance_cents"] == 250_000

    def test_resolve_records_adjustment_and_restores_posture(self):
        """PRD §3.4: "An `EngagementManager` resolves a `DISCREPANCY` statement by
        recording an `adjustment_cents` and a `note`; this moves the statement to
        `RESOLVED`, records the adjustment, recomputes
        `unreconciled_deposit_cents`, and recomputes the posture."
        PRD §3.4: "The `unreconciled_deposit_cents` is the
        `reported_deposit_total_cents` minus the `matched_contribution_cents`
        minus the `adjustment_cents`".

        Design: Corner/state_machines/trust_statement_resolve_records_adjustment
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001", deferral_amount_cy_cents=250_000)
        statement = get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(eng["id"], reported_deposit_total_cents=260_000),
            SPONSOR))
        contribution = get_success_data(api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"],
                payroll_date="2025-06-16", deposit_date="2025-06-20",
                amount_cents=250_000),
            SPONSOR))
        get_success_data(api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR))
        reconciled = get_success_data(api_client.reconcile_trust_statement(
            statement["id"], TPA))
        assert reconciled["status"] == "DISCREPANCY"
        assert reconciled["unreconciled_deposit_cents"] == 10_000
        resolved = validate_success(api_client.resolve_trust_statement(
            statement["id"],
            {"adjustment_cents": 10_000,
             "note": "custodian fee posting omitted from deposit detail"},
            MANAGER))
        assert resolved["status"] == "RESOLVED"
        assert resolved["adjustment_cents"] == 10_000
        assert resolved["unreconciled_deposit_cents"] == 0
        assert_reconciliation_identity(resolved)
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "ON_TRACK"

    def test_match_unmatch_restores_exact_pre_match_values(self):
        """PRD §3.4: "A `SponsorAdmin` unmatching a previously matched contribution
        clears its `trust_statement_id`, returns `match_status` to `UNMATCHED`,
        subtracts the contribution's `amount_cents` from the statement's
        `matched_contribution_cents`, and recomputes both the statement's
        `unreconciled_deposit_cents` and the participant's
        `account_balance_cents`."
        PRD §3.4: "The `unreconciled_deposit_cents` is the
        `reported_deposit_total_cents` minus the `matched_contribution_cents`
        minus the `adjustment_cents`".

        Design: Difficulty/compensating_invariant/match_unmatch_reconciliation_identity
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001", deferral_amount_cy_cents=500_000)
        statement = get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(
                eng["id"], certification="CERTIFIED",
                reported_deposit_total_cents=500_000),
            SPONSOR))
        assert_reconciliation_identity(statement)
        assert statement["unreconciled_deposit_cents"] == 500_000
        contribution = get_success_data(api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"],
                payroll_date="2025-06-16", deposit_date="2025-06-30",
                amount_cents=500_000),
            SPONSOR))
        get_success_data(api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR))
        after_match = get_success_data(api_client.get_trust_statement(statement["id"], SPONSOR))
        assert after_match["matched_contribution_cents"] == 500_000
        assert after_match["unreconciled_deposit_cents"] == 0
        assert_reconciliation_identity(after_match)
        get_success_data(api_client.unmatch_contribution(contribution["id"], SPONSOR))
        after_unmatch = get_success_data(
            api_client.get_trust_statement(statement["id"], SPONSOR))
        assert after_unmatch["matched_contribution_cents"] == 0
        assert after_unmatch["unreconciled_deposit_cents"] == 500_000, (
            "unmatch must restore the exact pre-match unreconciled figure"
        )
        assert_reconciliation_identity(after_unmatch)

    def test_reconciled_statement_reverts_to_discrepancy_on_unmatch(self):
        """PRD §3.4: "A `TPASpecialist` reconciles a statement: when
        `unreconciled_deposit_cents` is exactly zero, the statement moves to
        `RECONCILED`; otherwise it moves to `DISCREPANCY`."
        PRD §3.4: "if the statement was in `RECONCILED` and the recomputed
        `unreconciled_deposit_cents` is now non-zero, the statement reverts to
        `DISCREPANCY`."

        Design: Difficulty/compensating_invariant/match_unmatch_reconciliation_identity
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001", deferral_amount_cy_cents=500_000)
        statement = get_success_data(api_client.create_trust_statement(
            create_trust_statement_payload(
                eng["id"], certification="CERTIFIED",
                reported_deposit_total_cents=500_000),
            SPONSOR))
        contribution = get_success_data(api_client.create_contribution(
            create_contribution_payload(
                eng["id"], participant["id"],
                payroll_date="2025-06-16", deposit_date="2025-06-30",
                amount_cents=500_000),
            SPONSOR))
        get_success_data(api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR))
        reconciled = get_success_data(api_client.reconcile_trust_statement(
            statement["id"], TPA))
        assert reconciled["status"] == "RECONCILED"
        get_success_data(api_client.unmatch_contribution(contribution["id"], SPONSOR))
        after_unmatch = get_success_data(
            api_client.get_trust_statement(statement["id"], SPONSOR))
        assert after_unmatch["status"] == "DISCREPANCY"
        assert after_unmatch["unreconciled_deposit_cents"] == 500_000
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "BLOCKED"
        # Cycle closed: re-match and re-reconcile returns to RECONCILED.
        get_success_data(api_client.match_contribution(
            contribution["id"], {"trust_statement_id": statement["id"]}, SPONSOR))
        final = get_success_data(api_client.reconcile_trust_statement(
            statement["id"], TPA))
        assert final["status"] == "RECONCILED"
        assert final["matched_contribution_cents"] == 500_000
        assert final["unreconciled_deposit_cents"] == 0
        assert_reconciliation_identity(final)


class TestLateDepositScanBoundary:

    def test_exactly_at_standard_is_timely(self):
        """PRD §3.4: "A contribution whose `business_days_elapsed` is strictly
        greater than the engagement's `remittance_standard_days` is classified
        `LATE`; a contribution whose elapsed days equal the standard exactly is
        timely."

        Design: Difficulty/boundary_precision_check/late_deposit_exactly_safe_harbor_boundary
        """
        eng, participant = create_small_plan_engagement()
        assert eng["remittance_standard_days"] == 7
        # 2026-01-15 (Thu) -> 2026-01-26 (Mon): exactly 7 business days.
        contribution, assessment = create_late_assessment(
            eng["id"], participant["id"],
            payroll_date="2026-01-15", deposit_date="2026-01-26",
            amount_cents=200_000)
        assert assessment is None, "a deposit exactly at the standard must not be assessed"
        contribution_now = get_success_data(
            api_client.get_contribution(contribution["id"], SPONSOR))
        assert contribution_now["timeliness_status"] == "ON_TIME"
        assert contribution_now["business_days_elapsed"] == 7

    def test_one_business_day_over_standard_is_late(self):
        """PRD §3.4: "A contribution whose `business_days_elapsed` is strictly
        greater than the engagement's `remittance_standard_days` is classified
        `LATE`".
        PRD §3.4: "The assessment computes `business_days_late` as
        `business_days_elapsed` minus the `remittance_standard_days`. ... And it
        computes a `severity_hint`: `HIGH` when `business_days_late` is greater
        than 10, otherwise `MEDIUM`."

        Design: Difficulty/boundary_precision_check/late_deposit_exactly_safe_harbor_boundary
        """
        eng, participant = create_small_plan_engagement()
        # 2026-01-15 (Thu) -> 2026-01-27 (Tue): 8 business days, one over the 7-day standard.
        contribution, assessment = create_late_assessment(
            eng["id"], participant["id"],
            payroll_date="2026-01-15", deposit_date="2026-01-27",
            amount_cents=200_000)
        assert assessment is not None, "a deposit one business day over must be assessed"
        contribution_now = get_success_data(
            api_client.get_contribution(contribution["id"], SPONSOR))
        assert contribution_now["timeliness_status"] == "LATE"
        assert contribution_now["business_days_elapsed"] == 8
        assert assessment["contribution_id"] == contribution["id"]
        assert assessment["business_days_late"] == 1
        assert assessment["severity_hint"] == "MEDIUM"
        assert assessment["status"] == "ASSESSED"
