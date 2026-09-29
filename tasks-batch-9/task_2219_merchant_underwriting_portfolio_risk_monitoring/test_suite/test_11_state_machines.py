"""Declared transitions, their creation states and the refusals from undeclared ones."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_beneficial_owner,
    advance_to_underwriting,
    api_client,
    approve_termination,
    card_testing_day_overrides,
    chargeback_day_overrides,
    create_assessment,
    create_batch,
    create_draft_application,
    day_start,
    decide_application,
    ingest_activity,
    list_reserve_ledger,
    make_applicant_headers,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_risk_committee_headers,
    make_underwriting_officer_headers,
    merchant_with_open_chargeback_alert,
    onboard_standard_merchant,
    open_program,
    activate_program,
    OwnerSpec,
    pay_batch,
    propose_termination,
    read_alert,
    read_application,
    read_batch,
    read_merchant,
    read_program,
    read_reserve_account,
    read_termination_decision,
    record_verification,
    review_alert,
    run_monitoring,
    screen_owner,
    set_clock,
    submit_application,
    terminate_merchant,
    USER_ANALYST_01,
    USER_ANALYST_02,
    USER_COMMITTEE_01,
    USER_TREASURY_01,
)


class TestCreationStates:
    """New rows land in the state their workflow declares and nowhere else."""

    def test_an_alert_starts_open_and_a_termination_decision_starts_proposed(self):
        """Seventy basis points raises a severity-60 alert; the proposal that follows is PROPOSED.

        PRD 3.7: "Otherwise a new `MonitoringAlert` is inserted with the given `merchant_id` and
        `alert_type`, state `OPEN`, `recurrence_count` 1, and both `detected_on_date` and
        `last_detected_on_date` set to `as_of_date`, with `reviewed_by_user_id` and `review_note`
        null."

        PRD 3.12: "The decision is created in state `PROPOSED` with `proposed_by_user_id` from
        `X-User-ID`, and with `approved_by_user_id`, `rejection_note`, `executed_at` and
        `reversed_at` all null."

        Design: Corner/state_machines/alert_and_termination_decision_start_in_open_and_proposed
        """
        api = api_client
        onboarded, alert = merchant_with_open_chargeback_alert(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )

        assert alert["alert_type"] == "CHARGEBACK_THRESHOLD"
        assert alert["state"] == "OPEN"
        assert alert["observed_metric_bps"] == 70
        assert alert["severity_score"] == 60
        assert alert["recurrence_count"] == 1
        assert alert["detected_on_date"] == "2026-08-05"
        assert alert["last_detected_on_date"] == "2026-08-05"
        assert alert["reviewed_by_user_id"] is None
        assert alert["review_note"] is None

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["open_alert_count"] == 1
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["last_monitoring_run_date"] == "2026-08-05"

        decision = propose_termination(
            api, onboarded.merchant_id, "EXCESSIVE_CHARGEBACKS", USER_ANALYST_01
        )
        assert decision["state"] == "PROPOSED"
        assert decision["proposed_by_user_id"] == USER_ANALYST_01
        assert decision["approved_by_user_id"] is None
        assert decision["rejection_note"] is None
        assert decision["executed_at"] is None
        assert decision["reversed_at"] is None
        assert decision["match_listing_flag"] is False

    def test_approval_mints_a_merchant_and_a_reserve_account_on_pinned_terms(self):
        """Band B prices 500 basis points, so a ROLLING account opens on a 90-day lag.

        PRD 3.5: "The reserve terms are frozen onto the merchant from the authoritative assessment,
        the one with the greatest `assessment_sequence`: `pinned_reserve_pct_bps`,
        `pinned_reserve_cap_cents`, `pinned_reserve_type` and `pinned_assessment_method`."

        PRD 3.5: "The account copies `reserve_type`, `reserve_pct_bps` and `reserve_cap_cents` from
        the merchant's pinned values, sets `release_lag_days` to 90 days when `reserve_type` is
        `ROLLING` and 180 days when it is `CAPPED`, starts in state `ACCRUING` with
        `total_accrued_cents`, `released_to_date_cents`, `offset_to_date_cents` and
        `held_balance_cents` all 0, and `last_release_tranche_end_date` null."

        Design: Corner/state_machines/approval_mints_merchant_and_reserve_account_with_pinned_terms
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )

        application = read_application(api, onboarded.application_id)
        assert application["state"] == "APPROVED"
        assert application["decision_officer_user_id"] == USER_COMMITTEE_01
        assert application["decided_at"].startswith("2026-08-01T00:00:00")

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["application_id"] == onboarded.application_id
        assert merchant["mcc_code"] == "5732"
        assert merchant["monthly_volume_limit_cents"] == 30_000_000
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"
        assert merchant["delayed_payout_days"] == 0
        assert merchant["remediation_required"] is False
        assert merchant["pinned_reserve_pct_bps"] == 500
        assert merchant["pinned_reserve_cap_cents"] == 2_000_000
        assert merchant["pinned_reserve_type"] == "ROLLING"
        assert merchant["pinned_assessment_method"] == "LAG_WEIGHTED"
        assert merchant["version"] == 1

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["reserve_pct_bps"] == 500
        assert account["reserve_cap_cents"] == 2_000_000
        assert account["reserve_type"] == "ROLLING"
        assert account["release_lag_days"] == 90
        assert account["state"] == "ACCRUING"
        assert account["total_accrued_cents"] == 0
        assert account["released_to_date_cents"] == 0
        assert account["offset_to_date_cents"] == 0
        assert account["held_balance_cents"] == 0
        assert account["last_release_tranche_end_date"] is None


class TestAlertTriageWalksItsDeclaredPath:
    """Acknowledgement, dismissal and the two asymmetric escalation branches."""

    def test_acknowledge_then_dismiss_walks_open_under_review_dismissed(self):
        """The open count survives acknowledgement and only falls when the alert is dismissed.

        PRD 3.8: "`ACKNOWLEDGE` moves an alert `OPEN -> UNDER_REVIEW` and records
        `reviewed_by_user_id` from `X-User-ID`. `DISMISS` moves it `UNDER_REVIEW -> DISMISSED`,
        stores the note and recomputes the merchant's `open_alert_count`."

        Design: Corner/state_machines/alert_acknowledge_then_dismiss_walks_open_under_review_dismissed
        """
        api = api_client
        onboarded, alert = merchant_with_open_chargeback_alert(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )

        acknowledged = review_alert(api, alert["id"], "ACKNOWLEDGE", USER_ANALYST_02)
        assert acknowledged["state"] == "UNDER_REVIEW"
        assert acknowledged["reviewed_by_user_id"] == USER_ANALYST_02
        assert read_merchant(api, onboarded.merchant_id)["open_alert_count"] == 1

        dismissed = review_alert(
            api,
            alert["id"],
            "DISMISS",
            USER_ANALYST_02,
            review_note="Single wholesale dispute, no pattern.",
        )
        assert dismissed["state"] == "DISMISSED"
        assert dismissed["review_note"] == "Single wholesale dispute, no pattern."
        assert dismissed["reviewed_by_user_id"] == USER_ANALYST_02

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["open_alert_count"] == 0
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"

    def test_escalating_a_card_testing_alert_holds_the_funding_and_the_open_batch(self):
        """The enumeration signature freezes the merchant's cash without touching its risk posture.

        PRD 3.8: "When the escalated alert's `alert_type` is `CARD_TESTING` or
        `LAUNDERING_PATTERN` and the merchant's `funding_state` is `NORMAL` or `DELAYED`, the
        ALERT-ESCALATION cascade fires: link two moves `funding_state` to `HELD` with
        `delayed_payout_days` set to 0 and `funding_hold_reason_code` set to `CARD_TESTING` for a
        card-testing alert and `SUSPECTED_LAUNDERING` for a laundering alert, and link three moves
        every settlement batch of that merchant whose `payout_state` is `SCHEDULED` or `DELAYED` to
        `HELD` with `scheduled_payout_date` cleared to null, processed in `period_end_date`
        ascending order breaking ties by `created_at` ascending."

        Design: Corner/state_machines/escalating_a_card_testing_alert_holds_funding_and_open_batches
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
        batch = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)
        assert batch["payout_state"] == "SCHEDULED"

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **card_testing_day_overrides())
        alerts = run_monitoring(api, "2026-08-05")
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["alert_type"] == "CARD_TESTING"
        assert alert["severity_score"] == 85
        assert alert["observed_metric_bps"] == 4118

        review_alert(api, alert["id"], "ACKNOWLEDGE")
        escalated = review_alert(api, alert["id"], "ESCALATE")
        assert escalated["state"] == "ESCALATED"

        merchant = read_merchant(api, merchant_id)
        assert merchant["funding_state"] == "HELD"
        assert merchant["funding_hold_reason_code"] == "CARD_TESTING"
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["delayed_payout_days"] == 0
        assert merchant["open_alert_count"] == 1
        assert merchant["pending_payout_cents"] == 950_000

        frozen = read_batch(api, batch["id"])
        assert frozen["payout_state"] == "HELD"
        assert frozen["scheduled_payout_date"] is None
        assert frozen["net_payout_cents"] == 950_000

    def test_escalating_a_chargeback_threshold_alert_leaves_the_funding_untouched(self):
        """The dispute-ratio branch records the review and moves no money at all.

        PRD 3.8: "When the escalated alert's `alert_type` is `CHARGEBACK_THRESHOLD`, by contrast,
        **no funding change occurs at all**: the escalation records the review and nothing more,
        because a dispute-ratio problem is answered by the remediation program of 3.10 rather than
        by freezing the merchant's cash."

        Design: Corner/state_machines/escalating_a_chargeback_threshold_alert_leaves_funding_untouched
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
        batch = create_batch(api, merchant_id, "2026-08-05", "2026-08-05", 1_000_000)
        assert batch["net_payout_cents"] == 943_000
        assert batch["scheduled_payout_date"] == "2026-08-06"

        alerts = run_monitoring(api, "2026-08-05")
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["alert_type"] == "CHARGEBACK_THRESHOLD"

        review_alert(api, alert["id"], "ACKNOWLEDGE")
        escalated = review_alert(api, alert["id"], "ESCALATE")
        assert escalated["state"] == "ESCALATED"

        merchant = read_merchant(api, merchant_id)
        assert merchant["funding_state"] == "NORMAL"
        assert merchant["funding_hold_reason_code"] is None
        assert merchant["pending_payout_cents"] == 943_000
        assert merchant["open_alert_count"] == 1

        untouched = read_batch(api, batch["id"])
        assert untouched["payout_state"] == "SCHEDULED"
        assert untouched["scheduled_payout_date"] == "2026-08-06"


class TestUndeclaredTransitionsAreRefused:
    """Each family answers with its own state error and changes nothing."""

    def test_three_transitions_from_undeclared_source_states_are_rejected(self):
        """A DRAFT advance, a dismissal of an OPEN alert and an execution of a PROPOSED decision.

        PRD 3.3: "Advancing an application from `IN_VERIFICATION` to `UNDERWRITING` is the single
        point at which the facilitator commits to pricing the risk, and it is guarded by five
        substantive checks in addition to the state guard."

        PRD 3.8: "A disposition the current state does not permit - acknowledging anything other
        than an `OPEN` alert, or dismissing or escalating anything other than an `UNDER_REVIEW`
        alert - is rejected with `ERR_ALERT_STATE_INVALID`."

        PRD 2.6: "Then remediation-program state, with `ERR_PROGRAM_STATE_INVALID` (409). Then
        termination-decision state, with `ERR_TERMINATION_STATE_INVALID` (409). Then appeal state,
        with `ERR_APPEAL_STATE_INVALID` (409)."

        Design: Corner/state_machines/transitions_from_undeclared_source_states_are_rejected
        """
        api = api_client
        onboarded, alert = merchant_with_open_chargeback_alert(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        draft = create_draft_application(api, legal_business_name="Fernbrook Tea LLC")
        decision = propose_termination(api, onboarded.merchant_id)

        validate_error(
            api.advance_to_underwriting(draft["id"], make_underwriting_officer_headers()),
            "ERR_APPLICATION_STATE_INVALID",
            409,
        )
        validate_error(
            api.review_alert(
                alert["id"], {"disposition": "DISMISS"}, make_risk_analyst_headers()
            ),
            "ERR_ALERT_STATE_INVALID",
            409,
        )
        validate_error(
            api.execute_termination_decision(
                decision["id"], make_portfolio_controller_headers()
            ),
            "ERR_TERMINATION_STATE_INVALID",
            409,
        )

        assert read_application(api, draft["id"])["state"] == "DRAFT"
        assert read_alert(api, onboarded.merchant_id, alert["id"])["state"] == "OPEN"
        assert read_termination_decision(api, decision["id"])["state"] == "PROPOSED"

    def test_a_declined_application_is_terminal_for_submit_and_withdraw(self):
        """Neither re-submission nor withdrawal is available once the committee has declined.

        PRD 3.1: "`WITHDRAWN`, `APPROVED` and `DECLINED` are the three terminal application states,
        and a request against a terminal application is rejected with
        `ERR_APPLICATION_STATE_INVALID`."

        PRD 3.5: "`DECLINE` moves the application to `DECLINED` and requires `decline_reason_code`
        in the body, one of `PROHIBITED_CATEGORY`, `INSUFFICIENT_CREDIT`, `VERIFICATION_FAILED` or
        `OWNERSHIP_UNVERIFIED`; the code is stored on the application and no `Merchant` is created."

        Design: Corner/state_machines/declined_application_is_terminal_for_submit_and_withdraw
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Fernbrook Tea LLC"
        )["id"]
        owner = add_beneficial_owner(
            api, application_id, full_name="Ola Bergman", ownership_pct=100.00
        )
        submit_application(api, application_id)
        record_verification(api, application_id)
        screen_owner(api, owner["id"])
        advanced = advance_to_underwriting(api, application_id)
        create_assessment(api, application_id, advanced["version"])

        set_clock(api, "2026-08-02T00:00:00Z")
        declined = decide_application(
            api,
            application_id,
            "DECLINE",
            USER_COMMITTEE_01,
            decline_reason_code="INSUFFICIENT_CREDIT",
        )
        assert declined["state"] == "DECLINED"
        assert declined["decline_reason_code"] == "INSUFFICIENT_CREDIT"
        assert declined["decided_at"].startswith("2026-08-02T00:00:00")

        validate_error(
            api.submit_application(application_id, make_applicant_headers(application_id)),
            "ERR_APPLICATION_STATE_INVALID",
            409,
        )
        validate_error(
            api.withdraw_application(application_id, make_applicant_headers(application_id)),
            "ERR_APPLICATION_STATE_INVALID",
            409,
        )

        assert read_application(api, application_id)["state"] == "DECLINED"
        _, meta = validate_paginated(
            api.list_onboarded_merchants(application_id, make_underwriting_officer_headers())
        )
        assert meta["total_count"] == 0

    def test_a_paid_batch_is_terminal_for_pay_and_reverse(self):
        """Payment empties the pending set and closes the batch to both further calls.

        PRD 3.9: "The batch's `payout_state` must be `SCHEDULED`, `DELAYED` or `HELD` - a paid
        batch cannot be reversed, and the attempt yields `ERR_BATCH_STATE_INVALID` - and the
        merchant's reserve account must not be `CLOSED`, or `ERR_RESERVE_ACCOUNT_CLOSED`."

        PRD 3.9: "On success the batch moves to `PAID`, `paid_at` is stamped from the logical clock,
        and `net_payout_cents` is subtracted from `Merchant.pending_payout_cents` as the batch
        leaves the pending set."

        Design: Corner/state_machines/paid_batch_is_terminal_for_pay_and_reverse
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, onboarded.merchant_id, "2026-08-04")
        batch = create_batch(api, onboarded.merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        set_clock(api, day_start("2026-08-05"))
        paid = pay_batch(api, batch["id"])
        assert paid["payout_state"] == "PAID"
        assert paid["paid_at"].startswith("2026-08-05T00:00:00")

        validate_error(
            api.pay_settlement_batch(batch["id"], make_portfolio_controller_headers()),
            "ERR_BATCH_STATE_INVALID",
            409,
        )
        validate_error(
            api.reverse_settlement_batch(
                batch["id"], "FUNDING_ERROR", make_portfolio_controller_headers()
            ),
            "ERR_BATCH_STATE_INVALID",
            409,
        )

        final = read_batch(api, batch["id"])
        assert final["payout_state"] == "PAID"
        assert final["reversed_at"] is None

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["pending_payout_cents"] == 0
        assert merchant["reserve_balance_cents"] == 50_000
        assert merchant["lifetime_reversed_cents"] == 0

    def test_a_second_execution_of_the_same_termination_is_rejected(self):
        """A second execute is refused and nothing in the cascade repeats.

        The first execution left the merchant `TERMINATED`, and PRD 2.6 puts the merchant
        `account_state` guard ahead of the termination-decision guard, so that is the refusal.

        PRD 3.12: "Execution requires the merchant's `account_state` to be `ACTIVE` or
        `RESTRICTED`, and requires that the merchant have no `RemediationProgram` in state `DRAFT`
        or `ACTIVE`"

        PRD 2.6: "**State guards, in this exact sub-order.** Application state, with
        `ERR_APPLICATION_STATE_INVALID` (409). Then merchant `account_state`, with
        `ERR_MERCHANT_ACCOUNT_STATE_INVALID` (409). ... Then termination-decision state, with
        `ERR_TERMINATION_STATE_INVALID` (409)."

        PRD 3.12: "On success `executed_at` is stamped from the logical clock, the decision moves
        `APPROVED -> EXECUTED`, and the TERMINATION-EXEC cascade runs: `account_state` moves to
        `TERMINATED` with `terminated_at` set from the logical clock; that termination moves
        `funding_state` to `HELD` with `funding_hold_reason_code` `TERMINATION_PENDING` and
        `delayed_payout_days` 0"

        Design: Corner/state_machines/second_execute_of_the_same_termination_is_rejected
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, onboarded.merchant_id, "2026-08-04")
        create_batch(api, onboarded.merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        set_clock(api, day_start("2026-08-06"))
        executed = terminate_merchant(api, onboarded.merchant_id, "SUSPECTED_LAUNDERING")
        assert executed["state"] == "EXECUTED"

        validate_error(
            api.execute_termination_decision(
                executed["id"], make_portfolio_controller_headers()
            ),
            "ERR_MERCHANT_ACCOUNT_STATE_INVALID",
            409,
        )

        again = read_termination_decision(api, executed["id"])
        assert again["state"] == "EXECUTED"
        assert again["executed_at"] == executed["executed_at"]

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "TERMINATED"
        assert merchant["funding_state"] == "HELD"
        assert merchant["funding_hold_reason_code"] == "TERMINATION_PENDING"

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["state"] == "CLOSED"
        assert account["held_balance_cents"] == 50_000
        assert account["released_to_date_cents"] == 0
        assert len(list_reserve_ledger(api, onboarded.reserve_account_id)) == 1


class TestSelfLoopsAndPreconditions:
    """The verification lap, and the two referential gates on the intake path."""

    def test_the_information_request_lap_returns_the_application_to_verification(self):
        """A failed attempt asks for the registry match; the next attempt passes on index two.

        PRD 3.2: "The `FAILED` result itself drives the application onward from `IN_VERIFICATION`
        to `INFO_REQUESTED`, with `outstanding_info_items` set to the uppercase names of exactly
        those checks that came back false, listed in the fixed order `REGISTRY_MATCH`,
        `ADDRESS_MATCH`, `TAX_ID_MATCH`, `BANK_ACCOUNT_MATCH`."

        PRD 3.2: "`attempt_index` is a one-based ordinal assigned as the application's previous
        greatest `attempt_index` plus one, and the attempt bearing the greatest `attempt_index` is
        the authoritative one for every downstream check."

        Design: Corner/state_machines/application_info_request_and_resubmit_cycle_returns_to_verification
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Fernbrook Tea LLC"
        )["id"]
        add_beneficial_owner(api, application_id, full_name="Ola Bergman", ownership_pct=100.00)
        submit_application(api, application_id)

        first = record_verification(api, application_id, registry_match=False)
        assert first["attempt_index"] == 1
        assert first["mismatch_count"] == 1
        assert first["status"] == "FAILED"

        after_failure = read_application(api, application_id)
        assert after_failure["state"] == "INFO_REQUESTED"
        assert after_failure["outstanding_info_items"] == ["REGISTRY_MATCH"]
        assert after_failure["verification_attempt_count"] == 1

        resubmitted = submit_application(api, application_id)
        assert resubmitted["state"] == "SUBMITTED"
        assert resubmitted["outstanding_info_items"] == []

        second = record_verification(api, application_id)
        assert second["attempt_index"] == 2
        assert second["mismatch_count"] == 0
        assert second["status"] == "PASSED"

        after_pass = read_application(api, application_id)
        assert after_pass["state"] == "IN_VERIFICATION"
        assert after_pass["verification_attempt_count"] == 2

        _, meta = validate_paginated(
            api.list_business_verifications(application_id, make_underwriting_officer_headers())
        )
        assert meta["total_count"] == 2

    def test_approval_without_a_credit_assessment_is_rejected(self):
        """An unpriced application cannot be approved, and no merchant appears.

        PRD 3.5: "The application must be in `UNDERWRITING`, and at least one `CreditAssessment`
        must exist for it; a decision on an unpriced application is rejected with
        `ERR_CREDIT_ASSESSMENT_REQUIRED`."

        Design: Corner/state_machines/approval_without_a_credit_assessment_is_rejected
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Fernbrook Tea LLC"
        )["id"]
        owner = add_beneficial_owner(
            api, application_id, full_name="Ola Bergman", ownership_pct=100.00
        )
        submit_application(api, application_id)
        record_verification(api, application_id)
        screen_owner(api, owner["id"])
        advance_to_underwriting(api, application_id)

        response = api.decide_application(
            application_id, {"decision": "APPROVE"}, make_risk_committee_headers()
        )

        validate_error(response, "ERR_CREDIT_ASSESSMENT_REQUIRED", 409)

        application = read_application(api, application_id)
        assert application["state"] == "UNDERWRITING"
        assert application["decided_at"] is None
        assert application["decision_officer_user_id"] is None
        _, meta = validate_paginated(
            api.list_onboarded_merchants(application_id, make_underwriting_officer_headers())
        )
        assert meta["total_count"] == 0

    def test_submission_without_a_beneficial_owner_is_rejected(self):
        """The application stays in DRAFT with no ownership disclosed at all.

        PRD 3.1: "At least one beneficial owner must exist, or the request is rejected with
        `ERR_BENEFICIAL_OWNERS_REQUIRED`."

        Design: Corner/state_machines/submit_without_a_beneficial_owner_is_rejected
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Fernbrook Tea LLC"
        )["id"]

        response = api.submit_application(
            application_id, make_applicant_headers(application_id)
        )

        validate_error(response, "ERR_BENEFICIAL_OWNERS_REQUIRED", 409)

        application = read_application(api, application_id)
        assert application["state"] == "DRAFT"
        assert float(application["owner_ownership_pct_total"]) == 0.00
        assert application["mcc_disposition"] == "ALLOWED"
        assert application["version"] == 1


class TestFundingAndSettlementStateMovement:
    """Holding then releasing funding, and two settlements accruing side by side."""

    def test_releasing_funding_from_held_restores_the_batch_to_its_own_due_date(self):
        """An ACTIVE merchant returns to NORMAL and the batch is re-dated to period end plus one.

        PRD 3.8: "When `account_state` is `ACTIVE`, `funding_state` moves `HELD -> NORMAL`,
        `funding_hold_reason_code` is cleared, `delayed_payout_days` is set to 0, and every batch of
        the merchant whose `payout_state` is `HELD` moves to `SCHEDULED` with
        `scheduled_payout_date` set to its own `period_end_date` plus 1 day."

        Design: Corner/state_machines/funding_release_from_held_restores_scheduled_batches
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
        batch = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        validate_success(
            api.place_funding_hold(
                merchant_id, "SUSPECTED_LAUNDERING", make_risk_analyst_headers()
            )
        )
        held = read_batch(api, batch["id"])
        assert held["payout_state"] == "HELD"
        assert held["scheduled_payout_date"] is None

        released = validate_success(
            api.release_funding_hold(merchant_id, make_risk_committee_headers())
        )
        assert released["funding_state"] == "NORMAL"
        assert released["funding_hold_reason_code"] is None
        assert released["delayed_payout_days"] == 0
        assert released["account_state"] == "ACTIVE"

        restored = read_batch(api, batch["id"])
        assert restored["payout_state"] == "SCHEDULED"
        assert restored["scheduled_payout_date"] == "2026-08-05"
        assert restored["reserve_hold_cents"] == 50_000
        assert restored["net_payout_cents"] == 950_000

        merchant = read_merchant(api, merchant_id)
        assert merchant["pending_payout_cents"] == 950_000
        assert merchant["reserve_balance_cents"] == 50_000

    def test_two_clean_batches_accumulate_reserve_and_pending_payout(self):
        """Each period holds its own 50000 cents and both stay in the pending set.

        PRD 2.12: "`total_accrued_cents` is the sum of `amount_cents` over the account's `HOLD`
        entries, `released_to_date_cents` the sum over its `RELEASE` entries, and
        `offset_to_date_cents` the sum over its `OFFSET_LOSS` entries; `held_balance_cents` is
        `total_accrued_cents` less `released_to_date_cents` less `offset_to_date_cents`."

        PRD 2.8: "`Merchant.reserve_balance_cents` mirrors the reserve account's
        `held_balance_cents`; `pending_payout_cents` is the sum of `net_payout_cents` over the
        merchant's batches whose `payout_state` is `SCHEDULED`, `DELAYED` or `HELD`"

        Design: Corner/state_machines/two_clean_batches_accumulate_reserve_and_pending_payout
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
        first = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)
        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05")
        second = create_batch(api, merchant_id, "2026-08-05", "2026-08-05", 1_000_000)

        assert first["reserve_hold_cents"] == 50_000
        assert second["reserve_hold_cents"] == 50_000
        assert first["scheduled_payout_date"] == "2026-08-05"
        assert second["scheduled_payout_date"] == "2026-08-06"

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 100_000
        assert account["held_balance_cents"] == 100_000
        assert account["released_to_date_cents"] == 0
        assert account["offset_to_date_cents"] == 0
        assert account["state"] == "ACCRUING"

        merchant = read_merchant(api, merchant_id)
        assert merchant["reserve_balance_cents"] == 100_000
        assert merchant["pending_payout_cents"] == 1_900_000

        entries = list_reserve_ledger(api, onboarded.reserve_account_id)
        assert len(entries) == 2
        assert [entry["entry_type"] for entry in entries] == ["HOLD", "HOLD"]
        assert {entry["reason_code"] for entry in entries} == {"SETTLEMENT_HOLD"}


class TestTerminationExecutionAndItsBlockers:
    """Execution closes four dependents, unless a live remediation program stands in the way."""

    def test_execution_freezes_the_batch_closes_the_reserve_and_closes_the_alert(self):
        """One call ends the account, the funding, the batch, the reserve account and the alert.

        PRD 3.12: "that hold moves every settlement batch whose `payout_state` is `SCHEDULED` or
        `DELAYED` to `HELD` with `scheduled_payout_date` cleared, in `period_end_date` then
        `created_at` ascending order, and moves the merchant's reserve account to `CLOSED` from
        whichever of `ACCRUING`, `CAP_REACHED` or `RELEASING` it occupied; and closing the reserve
        account moves every alert of the merchant whose state is `OPEN`, `UNDER_REVIEW` or
        `ESCALATED` to `CLOSED`, processed in `created_at` ascending order, with `open_alert_count`
        recomputed."

        Design: Corner/state_machines/termination_execute_cascade_closes_alerts_and_reserve_account
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
        batch = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 14))
        set_clock(api, day_start("2026-08-06"))
        alerts = run_monitoring(api, "2026-08-06")
        assert len(alerts) == 1
        assert alerts[0]["observed_metric_bps"] == 70

        executed = terminate_merchant(api, merchant_id, "SUSPECTED_LAUNDERING")
        assert executed["state"] == "EXECUTED"
        assert executed["executed_at"].startswith("2026-08-06T00:00:00")

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "TERMINATED"
        assert merchant["terminated_at"].startswith("2026-08-06T00:00:00")
        assert merchant["funding_state"] == "HELD"
        assert merchant["funding_hold_reason_code"] == "TERMINATION_PENDING"
        assert merchant["delayed_payout_days"] == 0
        assert merchant["pending_payout_cents"] == 950_000
        assert merchant["open_alert_count"] == 0

        frozen = read_batch(api, batch["id"])
        assert frozen["payout_state"] == "HELD"
        assert frozen["scheduled_payout_date"] is None

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["state"] == "CLOSED"
        assert account["held_balance_cents"] == 50_000

        assert read_alert(api, merchant_id, alerts[0]["id"])["state"] == "CLOSED"

    def test_execution_is_blocked_while_a_remediation_program_is_active(self):
        """An open programme must be resolved first, so the approved decision stays unexecuted.

        PRD 3.12: "Execution requires the merchant's `account_state` to be `ACTIVE` or
        `RESTRICTED`, and requires that the merchant have no `RemediationProgram` in state `DRAFT`
        or `ACTIVE` - an open remediation programme must be resolved before the account is closed,
        and an attempt while one is open is rejected with `ERR_PROGRAM_STATE_INVALID`."

        Design: Corner/state_machines/termination_execute_blocked_by_an_active_remediation_program
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
        restricted = read_merchant(api, merchant_id)
        assert restricted["account_state"] == "RESTRICTED"
        assert restricted["remediation_required"] is True

        program = open_program(
            api, merchant_id, "2026-08-06", "2026-11-04", USER_ANALYST_01, target_ratio_bps=65
        )
        activated = activate_program(api, program["id"], USER_COMMITTEE_01)
        assert activated["state"] == "ACTIVE"

        decision = propose_termination(
            api, merchant_id, "REMEDIATION_FAILURE", USER_ANALYST_01
        )
        approve_termination(api, decision["id"], USER_COMMITTEE_01)

        response = api.execute_termination_decision(
            decision["id"], make_portfolio_controller_headers(USER_TREASURY_01)
        )

        validate_error(response, "ERR_PROGRAM_STATE_INVALID", 409)

        assert read_program(api, program["id"])["state"] == "ACTIVE"
        assert read_program(api, program["id"])["months_elapsed"] == 0
        unexecuted = read_termination_decision(api, decision["id"])
        assert unexecuted["state"] == "APPROVED"
        assert unexecuted["executed_at"] is None

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["remediation_required"] is True
        assert merchant["funding_state"] == "DELAYED"
        assert merchant["delayed_payout_days"] == 7
        assert merchant["terminated_at"] is None
