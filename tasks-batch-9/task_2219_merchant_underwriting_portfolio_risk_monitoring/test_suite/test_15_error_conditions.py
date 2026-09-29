"""Refusals: which one fires, and that a refused request leaves nothing behind."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    activate_program,
    api_client,
    appeal_payload,
    approve_termination,
    category_rule_payload,
    chargeback_day_overrides,
    create_batch,
    create_category_rule,
    day_activity_payload,
    day_start,
    file_appeal,
    ingest_activity,
    make_merchant_user_headers,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_risk_committee_headers,
    make_underwriting_officer_headers,
    onboard_standard_merchant,
    open_program,
    OwnerSpec,
    propose_termination,
    read_appeal,
    read_batch,
    read_merchant,
    read_program,
    read_reserve_account,
    release_request_payload,
    review_appeal,
    run_monitoring,
    set_clock,
    settle_one_clean_day,
    settlement_batch_payload,
    terminate_merchant,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    USER_COMMITTEE_02,
    USER_TREASURY_01,
)


class TestSettlementPeriodRefusals:
    """The four period-shaped refusals, in the order the ladder declares them."""

    def test_the_four_settlement_period_refusals_fire_in_declared_order(self):
        """Shape, overlap, emptiness and reconciliation each answer in turn.

        PRD 3.9: "`period_start_date` must not be later than `period_end_date` and `period_end_date`
        must not be later than the logical clock date, or `ERR_SETTLEMENT_PERIOD_INVALID`."

        PRD 3.9: "The closed period must not intersect the period of any other `SettlementBatch` of
        the same merchant whose `payout_state` is anything other than `REVERSED`; a single shared
        boundary date is already an intersection"

        PRD 2.6: "On a settlement batch, the period's shape and overlap are checked before the
        period is required to be non-empty, the non-empty check precedes the gross-volume
        reconciliation, and the reconciliation precedes the trailing-volume ceiling."

        Design: Corner/errors/four_settlement_period_refusals_fire_in_declared_priority_order
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, merchant_id, "2026-08-04")
        set_clock(api, day_start("2026-08-05"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            txn_count=2_000,
            volume_cents=2_000_000,
            distinct_card_count=1_900,
        )
        first = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        controller = make_portfolio_controller_headers()

        reversed_period = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-05", "2026-08-04", 2_000_000), controller
        )
        validate_error(reversed_period, "ERR_SETTLEMENT_PERIOD_INVALID", 422)

        overlapping = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-03", "2026-08-04", 1_000_000), controller
        )
        validate_error(overlapping, "ERR_SETTLEMENT_PERIOD_OVERLAP", 409)

        empty = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-03", "2026-08-03", 1_000_000), controller
        )
        validate_error(empty, "ERR_EMPTY_SETTLEMENT_PERIOD", 409)

        mismatched = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-05", "2026-08-05", 1_999_999), controller
        )
        validate_error(mismatched, "ERR_GROSS_VOLUME_MISMATCH", 422)

        batches, meta = validate_paginated(
            api.list_merchant_settlement_batches(merchant_id, controller)
        )
        assert meta["total_count"] == 1
        assert batches[0]["id"] == first["id"]
        stored = read_batch(api, first["id"])
        assert stored["gross_volume_cents"] == 1_000_000
        assert stored["reserve_hold_cents"] == 50_000


class TestUniquenessRefusals:
    """A day, a category rule and an appeal are each claimed exactly once."""

    def test_three_uniqueness_refusals_leave_the_original_rows_intact(self):
        """The repeat is refused and the first row keeps its own values.

        PRD 3.6: "the pair of `merchant_id` and `business_date` must be unique across all activity
        rows - a day is ingested once and never restated - with a repeat rejected as
        `ERR_DUPLICATE_ACTIVITY_DATE`."

        PRD 3.1: "Only one rule may exist per `mcc_code`; a second registration for the same code is
        rejected with `ERR_DUPLICATE_CATEGORY_RULE`."

        PRD 3.12: "And no appeal in state `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` may
        already exist against the same `termination_decision_id`, or `ERR_DUPLICATE_APPEAL`."

        Design: Corner/errors/three_uniqueness_refusals_leave_the_original_rows_intact
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        original_rule = create_category_rule(
            api, "7995", disposition="RESTRICTED_REVIEW", reserve_uplift_bps=400
        )
        duplicate_rule = api.create_category_rule(
            category_rule_payload("7995", disposition="PROHIBITED"),
            make_underwriting_officer_headers(),
        )
        validate_error(duplicate_rule, "ERR_DUPLICATE_CATEGORY_RULE", 409)

        officer = make_underwriting_officer_headers()
        rules, rules_meta = validate_paginated(api.list_category_rules(officer))
        assert rules_meta["total_count"] == 1
        assert rules[0]["id"] == original_rule["id"]
        assert rules[0]["disposition"] == "RESTRICTED_REVIEW"
        assert rules[0]["reserve_uplift_bps"] == 400
        _, prohibited_meta = validate_paginated(
            api.list_category_rules(officer, disposition="PROHIBITED")
        )
        assert prohibited_meta["total_count"] == 0

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", volume_cents=1_000_000)
        duplicate_day = api.create_day_activity(
            day_activity_payload(merchant_id, "2026-08-05", volume_cents=9_999),
            make_risk_analyst_headers(),
        )
        validate_error(duplicate_day, "ERR_DUPLICATE_ACTIVITY_DATE", 409)

        days, days_meta = validate_paginated(
            api.list_day_activity(merchant_id, make_risk_analyst_headers())
        )
        assert days_meta["total_count"] == 1
        assert days[0]["volume_cents"] == 1_000_000

        set_clock(api, day_start("2026-08-06"))
        decision = terminate_merchant(api, merchant_id, "EXCESSIVE_CHARGEBACKS")
        appeal = file_appeal(api, merchant_id, decision["id"])
        duplicate_appeal = api.create_appeal(
            appeal_payload(merchant_id, decision["id"], evidence_summary="Second attempt."),
            make_merchant_user_headers(merchant_id),
        )
        validate_error(duplicate_appeal, "ERR_DUPLICATE_APPEAL", 409)

        appeals, appeals_meta = validate_paginated(
            api.list_merchant_appeals(merchant_id, make_risk_analyst_headers())
        )
        assert appeals_meta["total_count"] == 1
        assert appeals[0]["id"] == appeal["id"]
        assert appeals[0]["state"] == "SUBMITTED"
        assert appeals[0]["response_round_count"] == 0


class TestAppealWindowAndAppealStates:
    """The thirty-day filing window, and the operations each appeal state declares."""

    def test_the_appeal_window_closes_the_day_after_the_thirtieth(self):
        """Day thirty is still inside the window; day thirty-one is not.

        PRD 3.12: "The logical clock date must be at most 30 days after the date on which that
        decision's `executed_at` fell, or `ERR_APPEAL_WINDOW_EXPIRED`."

        Design: Corner/errors/the_appeal_window_closes_the_day_after_the_thirtieth
        """
        api = api_client
        first = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        second = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Larkmead Supply LLC",
            owners=[OwnerSpec(full_name="Ola Bergman")],
        )

        set_clock(api, day_start("2026-08-06"))
        first_decision = terminate_merchant(api, first.merchant_id, "EXCESSIVE_CHARGEBACKS")
        second_decision = terminate_merchant(api, second.merchant_id, "EXCESSIVE_CHARGEBACKS")
        assert first_decision["executed_at"].startswith("2026-08-06")

        set_clock(api, day_start("2026-09-05"))
        on_the_last_day = file_appeal(api, first.merchant_id, first_decision["id"])
        assert on_the_last_day["state"] == "SUBMITTED"
        assert on_the_last_day["filed_on_date"] == "2026-09-05"

        set_clock(api, day_start("2026-09-06"))
        too_late = api.create_appeal(
            appeal_payload(second.merchant_id, second_decision["id"]),
            make_merchant_user_headers(second.merchant_id),
        )
        validate_error(too_late, "ERR_APPEAL_WINDOW_EXPIRED", 409)

        _, meta = validate_paginated(
            api.list_merchant_appeals(second.merchant_id, make_risk_analyst_headers())
        )
        assert meta["total_count"] == 0

    def test_appeal_actions_out_of_state_are_refused(self):
        """Responding and deciding are only declared from the states that name them.

        PRD 3.12: "Any operation attempted from a state that does not declare it - reviewing
        anything other than a `SUBMITTED` appeal, requesting information or deciding from anything
        other than `UNDER_REVIEW`, or responding from anything other than `INFO_REQUESTED` - is
        rejected with `ERR_APPEAL_STATE_INVALID`."

        PRD 3.12: "A `RiskCommitteeApprover` takes up a `SUBMITTED` appeal, moving it `SUBMITTED ->
        UNDER_REVIEW` and recording `reviewer_user_id` from `X-User-ID`."

        Design: Corner/errors/appeal_actions_out_of_state_are_refused_without_touching_the_appeal
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id
        set_clock(api, day_start("2026-08-06"))
        decision = terminate_merchant(api, merchant_id, "EXCESSIVE_CHARGEBACKS")
        appeal = file_appeal(api, merchant_id, decision["id"])

        early_response = api.respond_to_appeal_info(
            appeal["id"], "Documents attached.", make_merchant_user_headers(merchant_id)
        )
        validate_error(early_response, "ERR_APPEAL_STATE_INVALID", 409)

        early_decision = api.decide_appeal(
            appeal["id"], {"outcome": "UPHOLD"}, make_risk_committee_headers(USER_COMMITTEE_02)
        )
        validate_error(early_decision, "ERR_APPEAL_STATE_INVALID", 409)

        untouched = read_appeal(api, appeal["id"])
        assert untouched["state"] == "SUBMITTED"
        assert untouched["reviewer_user_id"] is None
        assert untouched["response_round_count"] == 0

        under_review = review_appeal(api, appeal["id"], USER_COMMITTEE_02)
        assert under_review["state"] == "UNDER_REVIEW"
        assert under_review["reviewer_user_id"] == USER_COMMITTEE_02

        premature_response = api.respond_to_appeal_info(
            appeal["id"], "Documents attached.", make_merchant_user_headers(merchant_id)
        )
        validate_error(premature_response, "ERR_APPEAL_STATE_INVALID", 409)

        info_requested = validate_success(
            api.request_appeal_info(
                appeal["id"], ["BANK_LETTER"], make_risk_committee_headers(USER_COMMITTEE_02)
            )
        )
        assert info_requested["state"] == "INFO_REQUESTED"
        assert info_requested["outstanding_info_items"] == ["BANK_LETTER"]
        assert info_requested["response_round_count"] == 0


class TestDutySeparation:
    """The four duty checks compare identifiers, not the role that was presented."""

    def test_segregation_of_duties_compares_user_ids_not_roles(self):
        """A second seat with the first seat's identifier is still the first actor.

        PRD 2.11: "Approving a termination requires an `X-User-ID` different from the decision's
        `proposed_by_user_id`; rejecting one carries the same restriction. Activating a remediation
        program requires an `X-User-ID` different from the program's `opened_by_user_id`."

        PRD 3.11: "the same user opening and activating is rejected with
        `ERR_SEGREGATION_OF_DUTIES`, and a program not in `DRAFT` with `ERR_PROGRAM_STATE_INVALID`."

        Design: Corner/errors/segregation_of_duties_compares_user_ids_not_roles
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 9))
        run_monitoring(api, "2026-08-05")
        assert read_merchant(api, merchant_id)["account_state"] == "RESTRICTED"

        program = open_program(
            api, merchant_id, "2026-08-06", "2026-11-04", USER_COMMITTEE_01
        )
        assert program["opened_by_user_id"] == USER_COMMITTEE_01

        same_hand = api.activate_remediation_program(
            program["id"], make_risk_committee_headers(USER_COMMITTEE_01)
        )
        validate_error(same_hand, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert read_program(api, program["id"])["state"] == "DRAFT"

        activated = activate_program(api, program["id"], USER_COMMITTEE_02)
        assert activated["state"] == "ACTIVE"
        assert activated["activated_by_user_id"] == USER_COMMITTEE_02

        decision = propose_termination(
            api, merchant_id, "EXCESSIVE_CHARGEBACKS", USER_COMMITTEE_01
        )
        assert decision["proposed_by_user_id"] == USER_COMMITTEE_01

        self_approval = api.approve_termination_decision(
            decision["id"], make_risk_committee_headers(USER_COMMITTEE_01)
        )
        validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES", 403)

        approved = approve_termination(api, decision["id"], USER_COMMITTEE_02)
        assert approved["state"] == "APPROVED"
        assert approved["approved_by_user_id"] == USER_COMMITTEE_02

    def test_the_appeal_decider_may_not_be_the_proposer_or_the_approver(self):
        """Two of the three termination seats are barred from the appeal decision.

        PRD 3.12: "Both outcomes require the appeal to be in `UNDER_REVIEW` and require that the
        deciding `X-User-ID` be neither the `proposed_by_user_id` nor the `approved_by_user_id` of
        the appealed decision, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`"

        PRD 3.12: "`UPHOLD` moves the appeal `UNDER_REVIEW -> UPHELD` and changes nothing else: the
        merchant remains `TERMINATED` and its reserve account remains `CLOSED`."

        Design: Corner/errors/the_appeal_decider_may_not_be_the_approver_of_the_decision
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id
        set_clock(api, day_start("2026-08-06"))
        decision = terminate_merchant(
            api,
            merchant_id,
            "EXCESSIVE_CHARGEBACKS",
            proposer=USER_ANALYST_01,
            approver=USER_COMMITTEE_01,
            executor=USER_TREASURY_01,
        )
        appeal = file_appeal(api, merchant_id, decision["id"])
        review_appeal(api, appeal["id"], USER_COMMITTEE_02)

        as_proposer = api.decide_appeal(
            appeal["id"], {"outcome": "UPHOLD"}, make_risk_committee_headers(USER_ANALYST_01)
        )
        validate_error(as_proposer, "ERR_SEGREGATION_OF_DUTIES", 403)

        as_approver = api.decide_appeal(
            appeal["id"], {"outcome": "UPHOLD"}, make_risk_committee_headers(USER_COMMITTEE_01)
        )
        validate_error(as_approver, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert read_appeal(api, appeal["id"])["state"] == "UNDER_REVIEW"

        decided = validate_success(
            api.decide_appeal(
                appeal["id"], {"outcome": "UPHOLD"}, make_risk_committee_headers(USER_COMMITTEE_02)
            )
        )
        assert decided["state"] == "UPHELD"
        assert decided["decided_at"].startswith("2026-08-06")
        assert read_merchant(api, merchant_id)["account_state"] == "TERMINATED"
        assert read_reserve_account(api, onboarded.reserve_account_id)["state"] == "CLOSED"


class TestRemediationSequenceAndEligibility:
    """Month evaluation is strictly sequential, and a program needs the flag first."""

    def test_month_index_must_be_exactly_one_past_months_elapsed(self):
        """Skipping ahead and replaying are both refused; only the next month is accepted.

        PRD 3.11: "Evaluation is strictly sequential: `month_index` must equal `months_elapsed` plus
        one, or the request is rejected with `ERR_MONTH_INDEX_OUT_OF_SEQUENCE`, and the program must
        be `ACTIVE`, or `ERR_PROGRAM_STATE_INVALID`."

        PRD 3.11: "The month is **compliant** when that observed ratio is strictly below
        `target_ratio_bps`; equalling the target is not compliance, and a month with no transactions
        at all is compliant with a ratio of 0."

        Design: Corner/errors/month_index_must_be_exactly_one_past_months_elapsed
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 9))
        run_monitoring(api, "2026-08-05")

        program = open_program(
            api,
            merchant_id,
            "2026-08-06",
            "2026-11-04",
            USER_ANALYST_01,
            target_ratio_bps=80,
            monitoring_month_count=3,
        )
        activate_program(api, program["id"], USER_COMMITTEE_01)

        set_clock(api, day_start("2026-09-05"))
        skipped = api.evaluate_remediation_month(program["id"], 2, make_risk_analyst_headers())
        validate_error(skipped, "ERR_MONTH_INDEX_OUT_OF_SEQUENCE", 409)
        assert read_program(api, program["id"])["months_elapsed"] == 0

        first_month = validate_success(
            api.evaluate_remediation_month(program["id"], 1, make_risk_analyst_headers())
        )
        assert first_month["months_elapsed"] == 1
        assert first_month["last_observed_ratio_bps"] == 0
        assert first_month["consecutive_compliant_months"] == 1
        assert first_month["state"] == "ACTIVE"

        replayed = api.evaluate_remediation_month(program["id"], 1, make_risk_analyst_headers())
        validate_error(replayed, "ERR_MONTH_INDEX_OUT_OF_SEQUENCE", 409)
        assert read_program(api, program["id"])["months_elapsed"] == 1

    def test_a_program_cannot_be_opened_for_a_merely_early_warning_merchant(self):
        """An alert below the breach line does not set the flag a program needs.

        PRD 3.11: "A program may only be opened while the merchant's `remediation_required` is true
        - the flag the CB-BREACH cascade sets - and an attempt against a merchant whose flag is
        false is rejected with `ERR_REMEDIATION_NOT_REQUIRED`"

        PRD 3.7: "sets `severity_score` to 90 when the ratio is 90 basis points or more, and 60
        otherwise. When the resulting `severity_score` is 90 or more and the merchant's
        `account_state` is `ACTIVE`, the CB-BREACH cascade fires"

        Design: Corner/errors/a_program_cannot_be_opened_for_a_merely_early_warning_merchant
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 7))
        alerts = run_monitoring(api, "2026-08-05")
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "CHARGEBACK_THRESHOLD"
        assert alerts[0]["observed_metric_bps"] == 70
        assert alerts[0]["severity_score"] == 60

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["remediation_required"] is False

        refused = api.create_remediation_program(
            {
                "merchant_id": merchant_id,
                "window_start_date": "2026-08-06",
                "window_end_date": "2026-11-04",
                "target_ratio_bps": 65,
                "monitoring_month_count": 3,
            },
            make_risk_analyst_headers(),
        )
        validate_error(refused, "ERR_REMEDIATION_NOT_REQUIRED", 409)

        _, meta = validate_paginated(
            api.list_merchant_remediation_programs(merchant_id, make_risk_analyst_headers())
        )
        assert meta["total_count"] == 0


class TestReserveReleaseConcurrency:
    """The release token must carry the account version the settlement left behind."""

    def test_a_stale_reserve_account_version_blocks_the_release_request(self):
        """The pre-settlement version is refused; the re-read version releases the balance.

        PRD 2.9: "If the supplied value does not equal the reserve account's current `version`, the
        request is rejected with `ERR_STALE_RESERVE_ACCOUNT_VERSION` and HTTP 412, preventing a
        release sized against a superseded `held_balance_cents`."

        PRD 3.10: "On acceptance a `RELEASE` entry is appended with `reason_code`
        `SCHEDULED_RELEASE`, the supplied `amount_cents` and tranche dates, `effective_date` set to
        the logical clock date, `settlement_batch_id` null and `recorded_by_user_id` set to the
        acting controller."

        Design: Corner/errors/a_stale_reserve_account_version_blocks_the_release_request
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock=day_start("2026-04-01"),
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        stale_version = onboarded.reserve_account["version"]
        settle_one_clean_day(api, onboarded.merchant_id, "2026-04-30", 1_000_000)

        set_clock(api, day_start("2026-07-29"))
        matured = read_reserve_account(api, onboarded.reserve_account_id)
        assert matured["held_balance_cents"] == 50_000
        assert matured["version"] != stale_version

        refused = api.create_release_request(
            onboarded.reserve_account_id,
            release_request_payload(50_000, "2026-04-01", "2026-04-30", stale_version),
            make_portfolio_controller_headers(),
        )
        validate_error(refused, "ERR_STALE_RESERVE_ACCOUNT_VERSION", 412)
        assert read_reserve_account(api, onboarded.reserve_account_id)["released_to_date_cents"] == 0

        entry = validate_success(
            api.create_release_request(
                onboarded.reserve_account_id,
                release_request_payload(50_000, "2026-04-01", "2026-04-30", matured["version"]),
                make_portfolio_controller_headers(),
            ),
            201,
        )
        assert entry["entry_type"] == "RELEASE"
        assert entry["reason_code"] == "SCHEDULED_RELEASE"
        assert entry["amount_cents"] == 50_000
        assert entry["tranche_start_date"] == "2026-04-01"
        assert entry["tranche_end_date"] == "2026-04-30"
        assert entry["effective_date"] == "2026-07-29"
        assert entry["settlement_batch_id"] is None
        assert entry["recorded_by_user_id"] == USER_TREASURY_01

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["released_to_date_cents"] == 50_000
        assert account["held_balance_cents"] == 0
        assert account["last_release_tranche_end_date"] == "2026-04-30"
        assert read_merchant(api, onboarded.merchant_id)["reserve_balance_cents"] == 0
