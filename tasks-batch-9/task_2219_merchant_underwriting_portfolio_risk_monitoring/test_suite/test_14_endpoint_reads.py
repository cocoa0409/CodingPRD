"""Collection and detail reads: their declared filters, orders and computed payloads."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_beneficial_owner,
    advance_to_underwriting,
    api_client,
    application_payload,
    card_testing_day_overrides,
    chargeback_day_overrides,
    create_assessment,
    create_batch,
    create_draft_application,
    create_forecast,
    day_start,
    file_appeal,
    ingest_activity,
    make_applicant_headers,
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
    read_reserve_account,
    record_verification,
    review_alert,
    run_monitoring,
    screen_owner,
    set_clock,
    submit_application,
    terminate_merchant,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    USER_TREASURY_01,
)


class TestApplicationChildCollections:
    """Owners, verification attempts and assessments each read back through their parent."""

    def test_the_three_application_child_collections_read_back_their_rows(self):
        """Each collection answers on its own filter and reports a single unfiltered page.

        PRD 2.3: "Collections also accept optional equality filters, all of which narrow the result
        set before pagination is applied: `disposition` on category rules; `state` and `mcc_code` on
        applications; `status` on an application's beneficial owners; `method` on an application's
        credit assessments"

        PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to 10, its minimum
        accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/endpoints/application_child_collection_reads_return_the_stored_rows
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Ridgeline Cycles LLC"
        )["id"]
        owner = add_beneficial_owner(
            api, application_id, full_name="Nadia Pike", ownership_pct=100.00
        )
        submit_application(api, application_id)
        record_verification(api, application_id)
        screen_owner(api, owner["id"])
        advanced = advance_to_underwriting(api, application_id)
        create_assessment(api, application_id, advanced["version"], "LAG_WEIGHTED")

        officer = make_underwriting_officer_headers()

        cleared, cleared_meta = validate_paginated(
            api.list_beneficial_owners(application_id, officer, status="CLEARED")
        )
        assert len(cleared) == 1
        assert cleared[0]["id"] == owner["id"]
        assert cleared_meta["total_count"] == 1
        assert cleared_meta["limit"] == 10
        assert cleared_meta["offset"] == 0
        assert cleared_meta["has_more"] is False

        pending, pending_meta = validate_paginated(
            api.list_beneficial_owners(application_id, officer, status="PENDING")
        )
        assert pending == []
        assert pending_meta["total_count"] == 0

        attempts, attempts_meta = validate_paginated(
            api.list_business_verifications(application_id, officer)
        )
        assert len(attempts) == 1
        assert attempts[0]["attempt_index"] == 1
        assert attempts[0]["status"] == "PASSED"
        assert attempts_meta["total_count"] == 1

        lag_weighted, lag_meta = validate_paginated(
            api.list_credit_assessments(application_id, officer, method="LAG_WEIGHTED")
        )
        assert len(lag_weighted) == 1
        assert lag_weighted[0]["reserve_pct_bps"] == 500
        assert lag_weighted[0]["reserve_type"] == "ROLLING"
        assert lag_meta["total_count"] == 1

        _, chargeback_meta = validate_paginated(
            api.list_credit_assessments(
                application_id, officer, method="CHARGEBACK_WEIGHTED"
            )
        )
        assert chargeback_meta["total_count"] == 0


class TestMerchantListingAndRiskSummary:
    """The two-dimensional merchant filter set, and the computed risk file."""

    def test_the_merchant_filters_compose_across_both_state_dimensions(self):
        """Three merchants in three postures answer four filters and one narrow page.

        PRD 2.3: "`status` on an application's beneficial owners; `method` on an application's credit
        assessments; `account_state`, `funding_state` and `remediation_required` on merchants"

        PRD 2.3: "Collections also accept optional equality filters, all of which narrow the result
        set before pagination is applied"

        Design: Corner/endpoints/merchant_list_filters_compose_across_both_state_dimensions
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
        third = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Fernbrook Tea LLC",
            owners=[OwnerSpec(full_name="Iris Calloway")],
        )

        set_clock(api, day_start("2026-08-05"))
        validate_success(
            api.place_funding_hold(
                second.merchant_id, "SUSPECTED_LAUNDERING", make_risk_analyst_headers()
            )
        )
        ingest_activity(
            api, third.merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 9)
        )
        run_monitoring(api, "2026-08-05")

        analyst = make_risk_analyst_headers()

        everyone, everyone_meta = validate_paginated(api.list_merchants(analyst))
        assert [row["id"] for row in everyone] == [
            first.merchant_id,
            second.merchant_id,
            third.merchant_id,
        ]
        assert everyone_meta["total_count"] == 3
        assert everyone_meta["has_more"] is False

        active, _ = validate_paginated(api.list_merchants(analyst, account_state="ACTIVE"))
        assert [row["id"] for row in active] == [first.merchant_id, second.merchant_id]

        held, _ = validate_paginated(api.list_merchants(analyst, funding_state="HELD"))
        assert [row["id"] for row in held] == [second.merchant_id]

        remediating, _ = validate_paginated(
            api.list_merchants(analyst, remediation_required=True)
        )
        assert [row["id"] for row in remediating] == [third.merchant_id]

        composed, _ = validate_paginated(
            api.list_merchants(analyst, account_state="ACTIVE", funding_state="NORMAL")
        )
        assert [row["id"] for row in composed] == [first.merchant_id]

        page, page_meta = validate_paginated(api.list_merchants(analyst, limit=1, offset=1))
        assert [row["id"] for row in page] == [second.merchant_id]
        assert page_meta["total_count"] == 3
        assert page_meta["has_more"] is True

    def test_the_risk_summary_is_computed_over_five_stored_entities(self):
        """Metrics, alert, reserve account and unpaid batch are gathered at read time.

        PRD 3.6: "A read-only risk summary assembles a merchant's position without persisting
        anything, recomputing from stored rows at read time."

        PRD 3.6: "a `gating_ratio_band` derived solely from the count-based variant: `NORMAL` when
        `rolling_chargeback_ratio_bps` is below 65 basis points, `EARLY_WARNING` when it is 65 or
        more but below 90, and `EXCESSIVE` when it is 90 or more."

        Design: Corner/endpoints/risk_summary_is_a_computed_read_over_five_entities
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
        create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)
        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 14))
        set_clock(api, day_start("2026-08-06"))
        alerts = run_monitoring(api, "2026-08-06")
        assert len(alerts) == 1

        summary = validate_success(api.get_risk_summary(merchant_id, make_risk_analyst_headers()))

        assert summary["merchant_id"] == merchant_id
        assert summary["account_state"] == "ACTIVE"
        assert summary["funding_state"] == "NORMAL"
        assert summary["rolling_chargeback_ratio_bps"] == 70
        assert summary["amount_based_chargeback_ratio_bps"] == 70
        assert summary["gating_ratio_band"] == "EARLY_WARNING"
        assert summary["open_alert_count"] == 1
        assert summary["reserve_account_id"] == onboarded.reserve_account_id
        assert summary["reserve_type"] == "ROLLING"
        assert summary["reserve_held_balance_cents"] == 50_000
        assert summary["reserve_releasable_cents"] == 0
        assert summary["unpaid_settlement_exposure_cents"] == 950_000
        assert summary["remediation_required"] is False


class TestLedgerAndReserveAccountReads:
    """Ledger entries are reachable from two parents; accounts split by reserve type."""

    def test_ledger_entries_are_scoped_by_batch_and_by_reserve_account(self):
        """Each batch owns one hold; the account owns both of them.

        PRD 3.9: "First, when `reserve_hold_cents` is greater than 0, a `HOLD` entry is appended
        with `reason_code` `SETTLEMENT_HOLD`, `amount_cents` equal to `reserve_hold_cents`,
        `effective_date` equal to the batch's `period_end_date`"

        PRD 2.3: "`entry_type` on a batch's ledger entries; `entry_type` and `reason_code` on a
        reserve account's ledger entries"

        Design: Corner/endpoints/ledger_reads_are_scoped_by_batch_and_by_reserve_account
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
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            txn_count=2_000,
            volume_cents=2_000_000,
            distinct_card_count=1_900,
        )
        second = create_batch(api, merchant_id, "2026-08-05", "2026-08-05", 2_000_000)

        controller = make_portfolio_controller_headers()

        first_entries, first_meta = validate_paginated(
            api.list_batch_ledger_entries(first["id"], controller)
        )
        assert first_meta["total_count"] == 1
        assert first_entries[0]["entry_type"] == "HOLD"
        assert first_entries[0]["amount_cents"] == 50_000
        assert first_entries[0]["effective_date"] == "2026-08-04"
        assert first_entries[0]["tranche_start_date"] is None
        assert first_entries[0]["tranche_end_date"] is None

        second_entries, second_meta = validate_paginated(
            api.list_batch_ledger_entries(second["id"], controller)
        )
        assert second_meta["total_count"] == 1
        assert second_entries[0]["amount_cents"] == 100_000
        assert second_entries[0]["effective_date"] == "2026-08-05"

        _, holds_meta = validate_paginated(
            api.list_reserve_ledger_entries(
                onboarded.reserve_account_id, controller, reason_code="SETTLEMENT_HOLD"
            )
        )
        assert holds_meta["total_count"] == 2

        _, offsets_meta = validate_paginated(
            api.list_reserve_ledger_entries(
                onboarded.reserve_account_id, controller, entry_type="OFFSET_LOSS"
            )
        )
        assert offsets_meta["total_count"] == 0

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["total_accrued_cents"] == 150_000
        assert account["held_balance_cents"] == 150_000

    def test_reserve_account_reads_separate_rolling_from_capped(self):
        """A band-D applicant opens a capped account on a 180-day lag beside a rolling one.

        PRD 3.4: "`reserve_type` is `ROLLING` when `reserve_pct_bps` is below 1000 basis points, and
        `CAPPED` at 1000 or above."

        PRD 2.3: "`payout_state` on a merchant's settlement batches; `state` and `reserve_type` on
        reserve accounts"

        Design: Corner/endpoints/reserve_account_reads_separate_rolling_from_capped
        """
        api = api_client
        rolling = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        capped = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Larkmead Supply LLC",
            credit_score=580,
            owners=[OwnerSpec(full_name="Ola Bergman")],
        )

        rolling_account = read_reserve_account(api, rolling.reserve_account_id)
        assert rolling_account["reserve_pct_bps"] == 500
        assert rolling_account["reserve_type"] == "ROLLING"
        assert rolling_account["release_lag_days"] == 90

        assert capped.assessment["credit_band"] == "D"
        capped_account = read_reserve_account(api, capped.reserve_account_id)
        assert capped_account["reserve_pct_bps"] == 1_500
        assert capped_account["reserve_type"] == "CAPPED"
        assert capped_account["release_lag_days"] == 180
        assert capped_account["reserve_cap_cents"] == 2_000_000
        assert capped_account["held_balance_cents"] == 0

        controller = make_portfolio_controller_headers()
        _, all_meta = validate_paginated(api.list_reserve_accounts(controller))
        assert all_meta["total_count"] == 2

        capped_rows, capped_meta = validate_paginated(
            api.list_reserve_accounts(controller, reserve_type="CAPPED")
        )
        assert capped_meta["total_count"] == 1
        assert capped_rows[0]["id"] == capped.reserve_account_id

        _, accruing_meta = validate_paginated(
            api.list_reserve_accounts(controller, state="ACCRUING")
        )
        assert accruing_meta["total_count"] == 2


class TestWriteEndpointsThatOnlyRecordWhatTheyAreGiven:
    """The information request, and a rejection that changes nothing about the merchant."""

    def test_the_information_request_stores_the_supplied_labels_verbatim(self):
        """The officer's own labels are kept, and the next submission clears them.

        PRD 3.2: "An officer may also request information by hand, supplying
        `outstanding_info_items` explicitly; that operation is declared from both `IN_VERIFICATION`
        and `UNDERWRITING`, and in both cases sets `outstanding_info_items` to the supplied labels
        and moves the application to `INFO_REQUESTED`."

        PRD 3.1: "Each submission clears `outstanding_info_items` to an empty list and recomputes
        both `owner_ownership_pct_total` and `mcc_disposition`, so the figures the underwriter reads
        are the ones the applicant last asserted."

        Design: Corner/endpoints/request_info_writes_the_supplied_item_labels_verbatim
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Ridgeline Cycles LLC"
        )["id"]
        add_beneficial_owner(api, application_id, full_name="Nadia Pike", ownership_pct=100.00)
        submit_application(api, application_id)
        record_verification(api, application_id)

        requested = validate_success(
            api.request_application_info(
                application_id,
                ["BANK_STATEMENTS", "PROCESSING_HISTORY"],
                make_underwriting_officer_headers(),
            )
        )
        assert requested["state"] == "INFO_REQUESTED"
        assert requested["outstanding_info_items"] == ["BANK_STATEMENTS", "PROCESSING_HISTORY"]
        assert requested["verification_attempt_count"] == 1

        resubmitted = submit_application(api, application_id)
        assert resubmitted["state"] == "SUBMITTED"
        assert resubmitted["outstanding_info_items"] == []
        assert float(resubmitted["owner_ownership_pct_total"]) == 100.00

    def test_rejecting_a_termination_leaves_the_merchant_untouched(self):
        """The decision is terminal at REJECTED and the merchant keeps trading.

        PRD 3.12: "Rejection moves it `PROPOSED -> REJECTED`, stores the supplied `rejection_note`
        and likewise records `approved_by_user_id` as the deciding user. `REJECTED` and `REVERSED`
        are terminal."

        Design: Corner/endpoints/rejecting_a_termination_leaves_the_merchant_untouched
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        decision = propose_termination(
            api,
            onboarded.merchant_id,
            "EXCESSIVE_CHARGEBACKS",
            USER_ANALYST_01,
            match_listing_flag=True,
        )

        rejected = validate_success(
            api.reject_termination_decision(
                decision["id"],
                "Ratio is inside tolerance for a seasonal book.",
                make_risk_committee_headers(USER_COMMITTEE_01),
            )
        )
        assert rejected["state"] == "REJECTED"
        assert rejected["rejection_note"] == "Ratio is inside tolerance for a seasonal book."
        assert rejected["approved_by_user_id"] == USER_COMMITTEE_01
        assert rejected["match_listing_flag"] is True
        assert rejected["executed_at"] is None

        rows, meta = validate_paginated(
            api.list_merchant_termination_decisions(
                onboarded.merchant_id, make_risk_analyst_headers(), state="REJECTED"
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == decision["id"]

        late_approval = api.approve_termination_decision(
            decision["id"], make_risk_committee_headers(USER_COMMITTEE_01)
        )
        validate_error(late_approval, "ERR_TERMINATION_STATE_INVALID", 409)

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"
        assert merchant["terminated_at"] is None
        assert read_reserve_account(api, onboarded.reserve_account_id)["state"] == "ACCRUING"


class TestActivityAndAlertReads:
    """Date-bounded activity reads, and the two alert filters."""

    def test_activity_reads_honour_the_from_and_to_date_bounds(self):
        """Both bounds are inclusive, and the rows come back in business-date order.

        PRD 2.3: "`from_date` and `to_date` on a merchant's day activity, both bounds inclusive"

        PRD 3.6: "The server computes `avg_ticket_cents` as `volume_cents` divided by `txn_count`
        rounded half up when `txn_count` is greater than zero, and 0 when the day had no
        transactions, and stamps `ingested_by_user_id` with the acting analyst."

        Design: Corner/endpoints/day_activity_reads_honour_the_from_and_to_date_filters
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-03"))
        ingest_activity(api, merchant_id, "2026-08-03", volume_cents=500_000)
        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, merchant_id, "2026-08-04", volume_cents=1_000_000)
        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", volume_cents=2_000_000)

        analyst = make_risk_analyst_headers()

        bounded, bounded_meta = validate_paginated(
            api.list_day_activity(
                merchant_id, analyst, from_date="2026-08-03", to_date="2026-08-04"
            )
        )
        assert [row["business_date"] for row in bounded] == ["2026-08-03", "2026-08-04"]
        assert bounded_meta["total_count"] == 2

        tail, tail_meta = validate_paginated(
            api.list_day_activity(merchant_id, analyst, from_date="2026-08-05")
        )
        assert tail_meta["total_count"] == 1
        assert tail[0]["business_date"] == "2026-08-05"
        assert tail[0]["avg_ticket_cents"] == 2_000

        everything, everything_meta = validate_paginated(
            api.list_day_activity(merchant_id, analyst)
        )
        assert everything_meta["total_count"] == 3
        assert everything[0]["business_date"] == "2026-08-03"
        assert everything[0]["avg_ticket_cents"] == 500
        assert everything[0]["ingested_by_user_id"] == USER_ANALYST_01

        page, page_meta = validate_paginated(api.list_day_activity(merchant_id, analyst, limit=1))
        assert len(page) == 1
        assert page_meta["total_count"] == 3
        assert page_meta["has_more"] is True

    def test_alert_reads_filter_by_state_and_by_alert_type(self):
        """One day raises two detectors; dismissing one splits the collection cleanly.

        PRD 2.3: "`from_date` and `to_date` on a merchant's day activity, both bounds inclusive;
        `state` and `alert_type` on a merchant's alerts"

        PRD 3.7: "Four detectors then run **in this pinned order**, and each may raise at most one
        alert per merchant per sweep."

        Design: Corner/endpoints/alert_reads_filter_by_state_and_by_alert_type
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
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            **card_testing_day_overrides(
                chargeback_count=1, chargeback_amount_cents=300, chargeback_network="VISA"
            ),
        )
        alerts = run_monitoring(api, "2026-08-05")
        assert [alert["alert_type"] for alert in alerts] == [
            "CHARGEBACK_THRESHOLD",
            "CARD_TESTING",
        ]
        chargeback_alert, card_testing_alert = alerts
        assert chargeback_alert["observed_metric_bps"] == 100
        assert chargeback_alert["severity_score"] == 90
        assert card_testing_alert["observed_metric_bps"] == 4_118
        assert card_testing_alert["severity_score"] == 85

        review_alert(api, card_testing_alert["id"], "ACKNOWLEDGE")
        review_alert(api, card_testing_alert["id"], "DISMISS", review_note="Vendor probe.")

        analyst = make_risk_analyst_headers()

        _, all_meta = validate_paginated(api.list_monitoring_alerts(merchant_id, analyst))
        assert all_meta["total_count"] == 2

        open_rows, open_meta = validate_paginated(
            api.list_monitoring_alerts(merchant_id, analyst, state="OPEN")
        )
        assert open_meta["total_count"] == 1
        assert open_rows[0]["alert_type"] == "CHARGEBACK_THRESHOLD"

        dismissed_rows, dismissed_meta = validate_paginated(
            api.list_monitoring_alerts(merchant_id, analyst, state="DISMISSED")
        )
        assert dismissed_meta["total_count"] == 1
        assert dismissed_rows[0]["alert_type"] == "CARD_TESTING"
        assert dismissed_rows[0]["reviewed_by_user_id"] == USER_ANALYST_01

        _, escalated_meta = validate_paginated(
            api.list_monitoring_alerts(merchant_id, analyst, state="ESCALATED")
        )
        assert escalated_meta["total_count"] == 0

        _, composed_meta = validate_paginated(
            api.list_monitoring_alerts(
                merchant_id, analyst, state="OPEN", alert_type="CARD_TESTING"
            )
        )
        assert composed_meta["total_count"] == 0

        merchant = read_merchant(api, merchant_id)
        assert merchant["open_alert_count"] == 1
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["funding_state"] == "DELAYED"


class TestReverseReachabilityReads:
    """An appeal, a program and a re-application are each found through their parents."""

    def test_an_appeal_is_reachable_from_its_merchant_and_from_its_decision(self):
        """Two collections and one detail read return the same freshly filed appeal.

        PRD 2.10: "or a merchant's activity rows, alerts, settlement batches, reserve account,
        remediation programs, termination decisions and appeals."

        PRD 3.12: "The appeal is created in state `SUBMITTED` with `filed_on_date` set to the
        logical clock date, `response_round_count` 0, `outstanding_info_items` empty, and
        `reviewer_user_id`, `reinstatement_reserve_pct_bps` and `decided_at` null."

        Design: Corner/endpoints/an_appeal_is_reachable_from_its_merchant_and_from_its_decision
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        set_clock(api, day_start("2026-08-06"))
        decision = terminate_merchant(api, onboarded.merchant_id, "EXCESSIVE_CHARGEBACKS")
        appeal = file_appeal(api, onboarded.merchant_id, decision["id"])

        analyst = make_risk_analyst_headers()

        by_merchant, merchant_meta = validate_paginated(
            api.list_merchant_appeals(onboarded.merchant_id, analyst)
        )
        assert merchant_meta["total_count"] == 1
        assert by_merchant[0]["id"] == appeal["id"]

        by_decision, decision_meta = validate_paginated(
            api.list_decision_appeals(decision["id"], analyst)
        )
        assert decision_meta["total_count"] == 1
        assert by_decision[0]["id"] == appeal["id"]

        detail = read_appeal(api, appeal["id"])
        assert detail["state"] == "SUBMITTED"
        assert detail["filed_on_date"] == "2026-08-06"
        assert detail["outstanding_info_items"] == []
        assert detail["response_round_count"] == 0
        assert detail["reviewer_user_id"] is None
        assert detail["reinstatement_reserve_pct_bps"] is None
        assert detail["decided_at"] is None

        _, granted_meta = validate_paginated(
            api.list_merchant_appeals(onboarded.merchant_id, analyst, state="GRANTED")
        )
        assert granted_meta["total_count"] == 0

    def test_a_draft_remediation_program_carries_only_its_creation_defaults(self):
        """Nothing has been evaluated yet, so every counter reads at its opening value.

        PRD 3.11: "The program is created in state `DRAFT` with `months_elapsed` 0,
        `consecutive_compliant_months` 0, `last_observed_ratio_bps` null, `network_program_tier`
        `STANDARD`, `opened_by_user_id` set from `X-User-ID` and `activated_by_user_id` null."

        Design: Corner/endpoints/a_draft_remediation_program_carries_only_its_creation_defaults
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
            target_ratio_bps=65,
            monitoring_month_count=3,
        )

        analyst = make_risk_analyst_headers()
        _, all_meta = validate_paginated(
            api.list_merchant_remediation_programs(merchant_id, analyst)
        )
        assert all_meta["total_count"] == 1
        _, draft_meta = validate_paginated(
            api.list_merchant_remediation_programs(merchant_id, analyst, state="DRAFT")
        )
        assert draft_meta["total_count"] == 1
        _, active_meta = validate_paginated(
            api.list_merchant_remediation_programs(merchant_id, analyst, state="ACTIVE")
        )
        assert active_meta["total_count"] == 0

        assert program["state"] == "DRAFT"
        assert program["months_elapsed"] == 0
        assert program["consecutive_compliant_months"] == 0
        assert program["last_observed_ratio_bps"] is None
        assert program["network_program_tier"] == "STANDARD"
        assert program["opened_by_user_id"] == USER_ANALYST_01
        assert program["activated_by_user_id"] is None
        assert program["target_ratio_bps"] == 65
        assert program["monitoring_month_count"] == 3

    def test_a_re_application_is_only_valid_after_the_prior_merchant_is_terminated(self):
        """The terminated book may re-apply; the trading one may not.

        PRD 3.1: "The named application must itself be `APPROVED` and the `Merchant` onboarded from
        it must have `account_state` `TERMINATED`; anything else - a superseded application still
        under review, or one whose merchant is still trading - is rejected with
        `ERR_SUPERSEDED_APPLICATION_INVALID`."

        Design: Corner/endpoints/a_re_application_is_only_valid_after_the_prior_merchant_is_terminated
        """
        api = api_client
        closed = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        trading = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Larkmead Supply LLC",
            owners=[OwnerSpec(full_name="Ola Bergman")],
        )
        set_clock(api, day_start("2026-08-06"))
        terminate_merchant(api, closed.merchant_id, "EXCESSIVE_CHARGEBACKS")

        re_application = create_draft_application(
            api,
            legal_business_name="Ridgeline Cycles II LLC",
            supersedes_application_id=closed.application_id,
        )
        assert re_application["state"] == "DRAFT"
        assert re_application["mcc_disposition"] == "ALLOWED"
        assert re_application["verification_attempt_count"] == 0
        assert re_application["supersedes_application_id"] == closed.application_id

        officer = make_underwriting_officer_headers()
        _, closed_meta = validate_paginated(
            api.list_superseding_applications(closed.application_id, officer)
        )
        assert closed_meta["total_count"] == 1

        refused = api.create_application(
            application_payload(
                legal_business_name="Larkmead Supply II LLC",
                supersedes_application_id=trading.application_id,
            ),
            make_applicant_headers(trading.application_id),
        )
        validate_error(refused, "ERR_SUPERSEDED_APPLICATION_INVALID", 409)

        _, trading_meta = validate_paginated(
            api.list_superseding_applications(trading.application_id, officer)
        )
        assert trading_meta["total_count"] == 0


class TestForecastAndPayoutEndpoints:
    """A forecast over nothing at all, and a payout asked for one day early."""

    def test_forecasting_an_empty_portfolio_returns_zeros(self):
        """No merchants means every projected figure is zero, not an error.

        PRD 3.13: "`reserve_adequacy_ratio_bps` is `total_reserve_held_cents` multiplied by 10000,
        divided by `gross_expected_loss_cents`, rounded half up, and exactly 0 when
        `gross_expected_loss_cents` is 0."

        PRD 3.13: "`stress_multiplier_bps` accompanies the stressed variant, defaults to 25000 basis
        points, and must lie between 10000 and 100000 basis points inclusive; under `EXPECTED_LOSS`
        it is ignored even when supplied."

        Design: Corner/endpoints/forecasting_an_empty_portfolio_returns_zeros_not_an_error
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")

        base = create_forecast(api, "2026-08-01", "EXPECTED_LOSS")
        assert base["merchant_count"] == 0
        assert base["unpaid_exposure_cents"] == 0
        assert base["gross_expected_loss_cents"] == 0
        assert base["net_expected_loss_cents"] == 0
        assert base["total_reserve_held_cents"] == 0
        assert base["coverage_gap_cents"] == 0
        assert base["reserve_adequacy_ratio_bps"] == 0
        assert base["required_additional_reserve_cents"] == 0
        assert base["projected_adequacy_ratio_bps"] == 0
        assert base["generated_by_user_id"] == USER_TREASURY_01

        stressed = create_forecast(
            api, "2026-08-01", "STRESSED", stress_multiplier_bps=30_000
        )
        assert stressed["method"] == "STRESSED"
        assert stressed["stress_multiplier_bps"] == 30_000
        assert stressed["gross_expected_loss_cents"] == 0

        controller = make_portfolio_controller_headers()
        _, all_meta = validate_paginated(api.list_portfolio_forecasts(controller))
        assert all_meta["total_count"] == 2
        _, stressed_meta = validate_paginated(
            api.list_portfolio_forecasts(controller, method="STRESSED")
        )
        assert stressed_meta["total_count"] == 1

    def test_a_payout_is_refused_before_its_due_date_and_accepted_on_it(self):
        """The scheduled date is the earliest payable day, and it pays in full.

        PRD 3.9: "The batch's `payout_state` must be `SCHEDULED` or `DELAYED`, or the request is
        rejected with `ERR_BATCH_STATE_INVALID`; the logical clock date must be on or after
        `scheduled_payout_date`, or `ERR_PAYOUT_NOT_DUE`"

        Design: Corner/endpoints/payout_is_refused_before_its_scheduled_date_and_accepted_on_it
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
        assert batch["scheduled_payout_date"] == "2026-08-05"

        early = api.pay_settlement_batch(batch["id"], make_portfolio_controller_headers())
        validate_error(early, "ERR_PAYOUT_NOT_DUE", 409)
        not_yet = read_batch(api, batch["id"])
        assert not_yet["payout_state"] == "SCHEDULED"
        assert not_yet["paid_at"] is None
        assert read_merchant(api, merchant_id)["pending_payout_cents"] == 950_000

        set_clock(api, day_start("2026-08-05"))
        paid = validate_success(
            api.pay_settlement_batch(batch["id"], make_portfolio_controller_headers())
        )
        assert paid["payout_state"] == "PAID"
        assert paid["paid_at"].startswith("2026-08-05T00:00:00")
        assert paid["scheduled_payout_date"] == "2026-08-05"
        assert paid["net_payout_cents"] == 950_000

        merchant = read_merchant(api, merchant_id)
        assert merchant["pending_payout_cents"] == 0
        assert merchant["reserve_balance_cents"] == 50_000
        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["held_balance_cents"] == 50_000
        assert account["state"] == "ACCRUING"
