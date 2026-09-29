"""Layers that cut across the workflows: version tokens, re-detection and read-after-write."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_beneficial_owner,
    advance_to_underwriting,
    api_client,
    chargeback_day_overrides,
    create_assessment,
    create_draft_application,
    credit_assessment_payload,
    day_start,
    ingest_activity,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_underwriting_officer_headers,
    onboard_standard_merchant,
    OwnerSpec,
    read_application,
    read_merchant,
    read_reserve_account,
    record_verification,
    run_monitoring,
    screen_owner,
    set_clock,
    settlement_batch_payload,
    submit_application,
)


class TestOptimisticConcurrencyOnTheApplication:
    """The assessment token is spent by the write that used it."""

    def test_a_successful_assessment_stales_the_token_that_created_it(self):
        """The officer's own success invalidates the version it was pinned to.

        PRD 2.9: "If the supplied value does not equal the application's current `version`, the
        request is rejected with `ERR_STALE_APPLICATION_VERSION` and HTTP 412, which is what stops
        an officer from re-pinning reserve terms computed from a view of the application another
        writer has already replaced."

        PRD 3.4: "That re-pinning is a mutation of the application, so its `version` increments -
        which is precisely why the next assessment's `expected_application_version` must carry the
        new number."

        PRD 3.4: "Add five components together: `base_reserve_bps`, `lag_uplift_bps`,
        `chargeback_uplift_bps`, `thin_file_uplift_bps` and `mcc_uplift_bps`."

        Design: Corner/cross-cutting complexity layers/a_successful_assessment_stales_the_token_that_created_it
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api,
            legal_business_name="Fernhollow Textiles",
            credit_score=610,
            avg_delivery_lag_days=21,
            declared_chargeback_ratio_bps=320,
            requested_monthly_volume_cents=30_000_000,
        )["id"]
        owner = add_beneficial_owner(
            api, application_id, full_name="Dana Reyes", ownership_pct=100.00
        )
        submit_application(api, application_id)
        record_verification(api, application_id)
        screen_owner(api, owner["id"])
        advanced = advance_to_underwriting(api, application_id)
        pinned_version = advanced["version"]

        officer = make_underwriting_officer_headers()

        first = create_assessment(api, application_id, pinned_version, "LAG_WEIGHTED")
        assert first["reserve_pct_bps"] == 1_350
        assert first["reserve_type"] == "CAPPED"
        assert first["exposure_estimate_cents"] == 21_000_000
        assert first["reserve_cap_cents"] == 24_300_000
        assert first["assessment_sequence"] == 1

        repinned = read_application(api, application_id)
        assert repinned["current_assessment_method"] == "LAG_WEIGHTED"
        assert repinned["current_reserve_pct_bps"] == 1_350
        assert repinned["version"] != pinned_version

        replayed = api.create_credit_assessment(
            credit_assessment_payload(application_id, pinned_version, "CHARGEBACK_WEIGHTED"),
            officer,
        )
        validate_error(replayed, "ERR_STALE_APPLICATION_VERSION", 412)

        _, after_refusal = validate_paginated(
            api.list_credit_assessments(application_id, officer)
        )
        assert after_refusal["total_count"] == 1
        assert read_application(api, application_id)["current_reserve_pct_bps"] == 1_350

        second = create_assessment(
            api, application_id, repinned["version"], "CHARGEBACK_WEIGHTED"
        )
        assert second["reserve_pct_bps"] == 1_860
        assert second["reserve_type"] == "CAPPED"
        assert second["exposure_estimate_cents"] == 3_840_000
        assert second["reserve_cap_cents"] == 7_680_000
        assert second["assessment_sequence"] == 2

        application = read_application(api, application_id)
        assert application["current_assessment_method"] == "CHARGEBACK_WEIGHTED"
        assert application["current_reserve_pct_bps"] == 1_860
        assert application["current_reserve_cap_cents"] == 7_680_000
        assert application["current_reserve_type"] == "CAPPED"
        assert application["state"] == "UNDERWRITING"

        assessments, meta = validate_paginated(
            api.list_credit_assessments(application_id, officer)
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in assessments] == [first["id"], second["id"]]


class TestRepeatedThresholdBreach:
    """A threshold that stays breached updates the alert it already raised."""

    def test_a_repeated_breach_bumps_recurrence_without_re_firing_the_cascade(self):
        """The second sweep re-detects on the same row and leaves the merchant as it was.

        PRD 3.7: "When an alert of the same `alert_type` for the same merchant already sits in state
        `OPEN` or `UNDER_REVIEW`, the sweep takes the re-detection path on that existing row instead
        of inserting: `recurrence_count` increments by one, and `severity_score`,
        `observed_metric_bps` and `last_detected_on_date` are overwritten with the current sweep's
        values."

        PRD 3.7: "A merchant already `RESTRICTED` is not restricted twice, and a merchant whose
        funding is already `DELAYED` or `HELD` does not have its funding posture rewound by link
        three."

        Design: Corner/cross-cutting complexity layers/a_repeated_breach_bumps_recurrence_without_re_firing_the_cascade
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Glasshouse Ceramics",
            owners=[OwnerSpec(full_name="Dana Reyes")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05", **chargeback_day_overrides(1_000, 9))
        first_run = run_monitoring(api, "2026-08-05")
        assert len(first_run) == 1
        assert first_run[0]["recurrence_count"] == 1
        after_first = read_merchant(api, merchant_id)
        assert after_first["account_state"] == "RESTRICTED"
        assert after_first["funding_state"] == "DELAYED"
        assert after_first["delayed_payout_days"] == 7

        set_clock(api, day_start("2026-08-06"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-06",
            **chargeback_day_overrides(1_000, 9, volume_cents=90_000),
        )
        second_run = run_monitoring(api, "2026-08-06")
        assert len(second_run) == 1

        alerts, meta = validate_paginated(
            api.list_monitoring_alerts(merchant_id, make_risk_analyst_headers())
        )
        assert meta["total_count"] == 1
        alert = alerts[0]
        assert alert["alert_type"] == "CHARGEBACK_THRESHOLD"
        assert alert["recurrence_count"] == 2
        assert alert["detected_on_date"] == "2026-08-05"
        assert alert["last_detected_on_date"] == "2026-08-06"
        assert alert["severity_score"] == 90
        assert alert["observed_metric_bps"] == 90
        assert alert["state"] == "OPEN"

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["funding_state"] == "DELAYED"
        assert merchant["delayed_payout_days"] == 7
        assert merchant["remediation_required"] is True
        assert merchant["open_alert_count"] == 1
        assert merchant["last_monitoring_run_date"] == "2026-08-06"

        summary = validate_success(api.get_risk_summary(merchant_id, make_risk_analyst_headers()))
        assert summary["rolling_chargeback_ratio_bps"] == 90
        assert summary["gating_ratio_band"] == "EXCESSIVE"


class TestReadAfterWriteOnSettlement:
    """Nothing about a settlement is deferred past its own response."""

    def test_settlement_writes_are_already_visible_in_their_own_response(self):
        """The creating response carries the waterfall, and the next reads agree with it.

        PRD 3.9: "The account's `total_accrued_cents`, `offset_to_date_cents` and
        `held_balance_cents` are then recomputed, `Merchant.reserve_balance_cents` is set from the
        new `held_balance_cents`, and `net_payout_cents` is added to `Merchant.pending_payout_cents`."

        PRD 3.9: "`net_payout_cents`, the amount payable to the merchant, is the available amount
        less `loss_offset_from_settlement_cents`."

        Design: Corner/consistency model/settlement_writes_are_already_visible_in_their_own_response
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Glasshouse Ceramics",
            owners=[OwnerSpec(full_name="Dana Reyes")],
        )
        merchant_id = onboarded.merchant_id
        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, merchant_id, "2026-08-04")

        controller = make_portfolio_controller_headers()
        batch = validate_success(
            api.create_settlement_batch(
                settlement_batch_payload(merchant_id, "2026-08-04", "2026-08-04", 1_000_000),
                controller,
            ),
            201,
        )
        assert batch["reserve_hold_cents"] == 50_000
        assert batch["net_payout_cents"] == 950_000
        assert batch["loss_offset_from_settlement_cents"] == 0
        assert batch["reserve_offset_cents"] == 0
        assert batch["uncovered_loss_cents"] == 0
        assert batch["payout_state"] == "SCHEDULED"
        assert batch["scheduled_payout_date"] == "2026-08-05"
        assert batch["gross_volume_cents"] == 1_000_000
        assert batch["paid_at"] is None

        entries, entries_meta = validate_paginated(
            api.list_reserve_ledger_entries(onboarded.reserve_account_id, controller)
        )
        assert entries_meta["total_count"] == 1
        assert entries[0]["settlement_batch_id"] == batch["id"]
        assert entries[0]["amount_cents"] == 50_000

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["held_balance_cents"] == 50_000
        assert account["total_accrued_cents"] == 50_000

        merchant = read_merchant(api, merchant_id)
        assert merchant["reserve_balance_cents"] == 50_000
        assert merchant["pending_payout_cents"] == 950_000

        summary = validate_success(api.get_risk_summary(merchant_id, controller))
        assert summary["reserve_held_balance_cents"] == 50_000
        assert summary["unpaid_settlement_exposure_cents"] == 950_000
