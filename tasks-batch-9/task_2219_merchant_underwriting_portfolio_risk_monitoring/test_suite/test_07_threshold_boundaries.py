"""Exact-equality boundaries: the excessive ratio line and the maturity cutoff day."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    OwnerSpec,
    api_client,
    create_batch,
    day_start,
    ingest_activity,
    make_portfolio_controller_headers,
    onboard_standard_merchant,
    read_alert,
    read_merchant,
    read_reserve_account,
    release_request_payload,
    run_monitoring,
    set_clock,
)

BUSY_DAY = {
    "txn_count": 5_000,
    "volume_cents": 50_000_000,
    "distinct_card_count": 4_800,
    "decline_count": 5,
    "cross_border_count": 0,
    "refund_cents": 0,
    "unique_bin_count": 400,
    "chargeback_network": "VISA",
}


def _merchant_one_basis_point_below_the_line(api):
    """89 chargebacks in 10000 transactions: above early warning, below excessive."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-09T00:00:00Z",
        legal_business_name="Vale & Co Retail LLC",
        mcc_code="5999",
        requested_monthly_volume_cents=300_000_000,
        owners=[OwnerSpec(full_name="Sara Vale")],
    )
    ingest_activity(
        api,
        onboarded.merchant_id,
        "2026-07-08",
        chargeback_count=44,
        chargeback_amount_cents=440_000,
        **BUSY_DAY,
    )
    ingest_activity(
        api,
        onboarded.merchant_id,
        "2026-07-09",
        chargeback_count=45,
        chargeback_amount_cents=450_000,
        **BUSY_DAY,
    )
    set_clock(api, "2026-07-10T00:00:00Z")
    alerts = run_monitoring(api, "2026-07-10")
    assert len(alerts) == 1
    return onboarded, alerts[0]


class TestTheExcessiveChargebackLineIsAnEquality:
    """89 bps warns; 90 bps — one basis point later — restricts."""

    def test_one_basis_point_short_of_the_line_only_warns(self):
        """The alert grades at severity 60 and neither posture moves.

        PRD 3.7: "When it is 65 basis points or more - the early-warning line - the detector
        raises, sets `observed_metric_bps` to that ratio and sets `severity_score` to 90 when the
        ratio is 90 basis points or more, and 60 otherwise."

        Design: Difficulty/boundary_precision_check/count_based_ratio_exactly_at_excessive_threshold_restricts
        """
        api = api_client
        onboarded, alert = _merchant_one_basis_point_below_the_line(api)

        assert alert["severity_score"] == 60
        assert alert["observed_metric_bps"] == 89
        assert alert["recurrence_count"] == 1

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["rolling_chargeback_ratio_bps"] == 89
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["remediation_required"] is False
        assert merchant["funding_state"] == "NORMAL"

    def test_landing_exactly_on_the_line_restricts_on_a_re_detection(self):
        """At exactly 90 bps the existing alert is re-graded and the cascade finally fires.

        PRD 3.7: "When an alert of the same `alert_type` for the same merchant already sits in
        state `OPEN` or `UNDER_REVIEW`, the sweep takes the re-detection path on that existing row
        instead of inserting: `recurrence_count` increments by one, and `severity_score`,
        `observed_metric_bps` and `last_detected_on_date` are overwritten with the current sweep's
        values."

        Design: Difficulty/boundary_precision_check/count_based_ratio_exactly_at_excessive_threshold_restricts
        """
        api = api_client
        onboarded, alert = _merchant_one_basis_point_below_the_line(api)

        set_clock(api, day_start("2026-07-11"))
        ingest_activity(
            api,
            onboarded.merchant_id,
            "2026-07-11",
            chargeback_count=46,
            chargeback_amount_cents=460_000,
            **BUSY_DAY,
        )
        set_clock(api, "2026-07-12T00:00:00Z")
        run_monitoring(api, "2026-07-12")

        re_detected = read_alert(api, onboarded.merchant_id, alert["id"])
        assert re_detected["severity_score"] == 90
        assert re_detected["observed_metric_bps"] == 90
        assert re_detected["recurrence_count"] == 2
        assert re_detected["last_detected_on_date"] == "2026-07-12"

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["rolling_chargeback_ratio_bps"] == 90
        assert merchant["open_alert_count"] == 1
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["funding_state"] == "DELAYED"


def _account_with_one_april_hold(api):
    """A single 50000-cent HOLD effective 2026-04-01 on a ROLLING account."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-04-01T00:00:00Z",
        legal_business_name="Northfold Optics LLC",
        mcc_code="5999",
        owners=[OwnerSpec(full_name="Bo Nystrom")],
    )
    ingest_activity(api, onboarded.merchant_id, "2026-04-01")
    batch = create_batch(api, onboarded.merchant_id, "2026-04-01", "2026-04-01", 1_000_000)
    assert batch["reserve_hold_cents"] == 50_000
    account = read_reserve_account(api, onboarded.reserve_account_id)
    assert account["reserve_type"] == "ROLLING"
    return onboarded, account["version"]


def _ask_for_the_whole_hold(api, reserve_account_id, version):
    return api.create_release_request(
        reserve_account_id,
        release_request_payload(50_000, "2026-04-01", "2026-04-30", version),
        make_portfolio_controller_headers(),
    )


class TestTheMaturityCutoffIncludesItsOwnDay:
    """Day 89 has nothing releasable; day 90 releases the whole hold."""

    def test_the_day_before_the_cutoff_has_no_releasable_balance(self):
        """At clock 2026-06-29 the cutoff is 2026-03-31 and the April hold has not matured.

        PRD 3.10: "The matured hold total is the summed `amount_cents` of the account's `HOLD`
        entries whose `effective_date` is on or before that cutoff, the boundary being inclusive;
        maturity is filtered by `effective_date` only and never by `created_at`."

        Design: Difficulty/boundary_precision_check/hold_maturity_cutoff_inclusive_on_the_exact_day
        """
        api = api_client
        onboarded, version = _account_with_one_april_hold(api)

        set_clock(api, "2026-06-29T00:00:00Z")
        response = _ask_for_the_whole_hold(api, onboarded.reserve_account_id, version)

        validate_error(response, "ERR_NO_RELEASABLE_BALANCE", 409)

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["released_to_date_cents"] == 0
        assert account["held_balance_cents"] == 50_000

    def test_on_the_cutoff_day_itself_the_whole_hold_is_releasable(self):
        """At clock 2026-06-30 the cutoff falls exactly on the hold's effective date.

        PRD 3.10: "The maturity lag is the account's `release_lag_days` - 90 days for a `ROLLING`
        account and 180 days for a `CAPPED` one - and the cutoff is the logical clock date less
        that many days."

        Design: Difficulty/boundary_precision_check/hold_maturity_cutoff_inclusive_on_the_exact_day
        """
        api = api_client
        onboarded, version = _account_with_one_april_hold(api)

        set_clock(api, "2026-06-29T00:00:00Z")
        _ask_for_the_whole_hold(api, onboarded.reserve_account_id, version)

        set_clock(api, "2026-06-30T00:00:00Z")
        accepted = _ask_for_the_whole_hold(api, onboarded.reserve_account_id, version)
        validate_success(accepted, 201)

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["released_to_date_cents"] == 50_000
        assert account["held_balance_cents"] == 0
        assert account["last_release_tranche_end_date"] == "2026-04-30"
        # held_balance_cents is 0, so the ACCRUING -> RELEASING condition is not met.
        assert account["state"] == "ACCRUING"
