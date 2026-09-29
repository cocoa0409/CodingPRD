"""The two long cascades: a chargeback breach outward, and an appeal grant back inward."""

from __future__ import annotations

from test_helpers import (
    OwnerSpec,
    api_client,
    approve_termination,
    create_batch,
    day_start,
    decide_appeal,
    execute_termination,
    file_appeal,
    ingest_activity,
    list_reserve_ledger,
    onboard_standard_merchant,
    propose_termination,
    read_appeal,
    read_batch,
    read_merchant,
    read_reserve_account,
    read_termination_decision,
    review_appeal,
    run_monitoring,
    set_clock,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    USER_COMMITTEE_02,
    USER_TREASURY_01,
)


def _breach_the_count_based_ratio(api):
    """Push the trailing window to 27 chargebacks in 3000 transactions and sweep."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-08T00:00:00Z",
        legal_business_name="Kestrel Trading LLC",
        mcc_code="5999",
        requested_monthly_volume_cents=300_000_000,
        average_ticket_cents=45_000,
        owners=[OwnerSpec(full_name="Petra Vance")],
    )
    merchant_id = onboarded.merchant_id
    ingest_activity(
        api,
        merchant_id,
        "2026-07-08",
        txn_count=2_000,
        volume_cents=90_000_000,
        distinct_card_count=1_900,
        decline_count=5,
        unique_bin_count=300,
        chargeback_count=17,
        chargeback_amount_cents=170_000,
        chargeback_network="VISA",
    )
    batch = create_batch(api, merchant_id, "2026-07-08", "2026-07-08", 90_000_000)
    assert batch["payout_state"] == "SCHEDULED"
    assert batch["scheduled_payout_date"] == "2026-07-09"

    set_clock(api, day_start("2026-07-10"))
    ingest_activity(
        api,
        merchant_id,
        "2026-07-10",
        txn_count=1_000,
        volume_cents=8_000_000,
        distinct_card_count=950,
        decline_count=5,
        unique_bin_count=300,
        chargeback_count=10,
        chargeback_amount_cents=100_000,
        chargeback_network="VISA",
    )
    alerts = run_monitoring(api, "2026-07-10")
    return onboarded, batch, alerts


class TestTheChargebackBreachCascade:
    """One sweep, four consequences: alert, risk posture, payout posture, open batch."""

    def test_the_sweep_raises_one_alert_at_the_severe_grade(self):
        """27 chargebacks in 3000 transactions is 90 bps, which grades at severity 90.

        PRD 3.7: "When it is 65 basis points or more - the early-warning line - the detector
        raises, sets `observed_metric_bps` to that ratio and sets `severity_score` to 90 when the
        ratio is 90 basis points or more, and 60 otherwise."

        Design: Difficulty/transitive_cascade/chargeback_breach_cascades_run_alert_account_funding_batch
        """
        api = api_client
        onboarded, _, alerts = _breach_the_count_based_ratio(api)

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["alert_type"] == "CHARGEBACK_THRESHOLD"
        assert alert["observed_metric_bps"] == 90
        assert alert["severity_score"] == 90
        assert alert["state"] == "OPEN"
        assert alert["detected_on_date"] == "2026-07-10"

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["rolling_chargeback_ratio_bps"] == 90
        assert merchant["open_alert_count"] == 1
        assert merchant["last_monitoring_run_date"] == "2026-07-10"

    def test_the_alert_restricts_the_account_which_delays_funding_which_pushes_the_batch(self):
        """The already-scheduled batch is re-dated to the sweep date plus seven days.

        PRD 3.7: "Link four walks every settlement batch of that merchant whose `payout_state` is
        `SCHEDULED`, in `period_end_date` ascending order breaking ties by `created_at` ascending,
        moving each `SCHEDULED -> DELAYED` with `scheduled_payout_date` set to the triggering
        sweep's `as_of_date` plus 7 days; `pending_payout_cents` is then recomputed."

        Design: Difficulty/transitive_cascade/chargeback_breach_cascades_run_alert_account_funding_batch
        """
        api = api_client
        onboarded, created, _ = _breach_the_count_based_ratio(api)

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["remediation_required"] is True
        assert merchant["funding_state"] == "DELAYED"
        assert merchant["delayed_payout_days"] == 7

        batch = read_batch(api, created["id"])
        assert batch["payout_state"] == "DELAYED"
        assert batch["scheduled_payout_date"] == "2026-07-17"
        assert batch["net_payout_cents"] == 85_330_000


def _appeal_under_review_against_a_terminated_merchant(api):
    """Terminate a merchant holding reserve and a batch, then get its appeal to UNDER_REVIEW."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-01T00:00:00Z",
        legal_business_name="Halyard Outfitters LLC",
        mcc_code="5999",
        owners=[OwnerSpec(full_name="Sofia Vega")],
    )
    merchant_id = onboarded.merchant_id
    ingest_activity(api, merchant_id, "2026-07-01")
    batch = create_batch(api, merchant_id, "2026-07-01", "2026-07-01", 1_000_000)
    assert batch["reserve_hold_cents"] == 50_000
    assert batch["net_payout_cents"] == 950_000

    set_clock(api, day_start("2026-07-05"))
    decision = propose_termination(
        api, merchant_id, "SUSPECTED_LAUNDERING", USER_ANALYST_01
    )
    approve_termination(api, decision["id"], USER_COMMITTEE_01)
    execute_termination(api, decision["id"], USER_TREASURY_01)

    appeal = file_appeal(
        api,
        merchant_id,
        decision["id"],
        "Flagged volume was a single wholesale customer; contracts and invoices attached.",
    )
    review_appeal(api, appeal["id"], USER_COMMITTEE_02)
    set_clock(api, "2026-07-07T00:00:00Z")
    return onboarded, decision, appeal, batch


class TestTheAppealGrantCascade:
    """One grant, five consequences, in the reinstatement direction."""

    def test_the_grant_reverses_the_decision_and_brings_the_account_back_restricted(self):
        """Reinstatement is never a return to ACTIVE: the merchant comes back RESTRICTED.

        PRD 3.12: "That reversal moves `account_state` `TERMINATED -> RESTRICTED`, setting
        `reinstated_at` from the logical clock, `remediation_required` to true and `terminated_at`
        back to null"

        Design: Difficulty/transitive_cascade/appeal_grant_cascades_decision_account_funding_batch_reserve
        """
        api = api_client
        onboarded, decision, appeal, _ = _appeal_under_review_against_a_terminated_merchant(api)

        decide_appeal(
            api, appeal["id"], "GRANT", USER_COMMITTEE_02, reinstatement_reserve_pct_bps=900
        )

        assert read_appeal(api, appeal["id"])["state"] == "GRANTED"
        assert read_termination_decision(api, decision["id"])["state"] == "REVERSED"

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["remediation_required"] is True
        assert merchant["terminated_at"] is None
        assert merchant["funding_state"] == "DELAYED"
        assert merchant["delayed_payout_days"] == 7
        assert merchant["funding_hold_reason_code"] is None

    def test_the_reinstated_funding_posture_re_dates_the_held_batch(self):
        """The held batch becomes DELAYED at the clock date plus seven days, not its own period.

        PRD 3.12: "That funding change finally moves every settlement batch of the merchant whose
        `payout_state` is `HELD` to `DELAYED` with `scheduled_payout_date` set to the logical clock
        date plus 7 days"

        Design: Difficulty/transitive_cascade/appeal_grant_cascades_decision_account_funding_batch_reserve
        """
        api = api_client
        onboarded, _, appeal, created = _appeal_under_review_against_a_terminated_merchant(api)

        held = read_batch(api, created["id"])
        assert held["payout_state"] == "HELD"
        assert held["scheduled_payout_date"] is None

        decide_appeal(
            api, appeal["id"], "GRANT", USER_COMMITTEE_02, reinstatement_reserve_pct_bps=900
        )

        batch = read_batch(api, created["id"])
        assert batch["payout_state"] == "DELAYED"
        assert batch["scheduled_payout_date"] == "2026-07-14"
        assert read_merchant(api, onboarded.merchant_id)["pending_payout_cents"] == 950_000

    def test_the_closed_reserve_account_reopens_re_priced_and_returns_its_balance(self):
        """The account reopens at the appealed 900 bps and gives the old balance back.

        PRD 3.12: "and moves the reserve account `CLOSED -> ACCRUING`, re-pinning its
        `reserve_pct_bps` from the merchant's `pinned_reserve_pct_bps` and, when its
        `held_balance_cents` is greater than 0, appending a `RELEASE` entry with `reason_code`
        `REINSTATEMENT_RELEASE` for `amount_cents` equal to that whole `held_balance_cents`,
        `effective_date` the logical clock date and both tranche dates null."

        Design: Difficulty/transitive_cascade/appeal_grant_cascades_decision_account_funding_batch_reserve
        """
        api = api_client
        onboarded, _, appeal, _ = _appeal_under_review_against_a_terminated_merchant(api)

        closed = read_reserve_account(api, onboarded.reserve_account_id)
        assert closed["state"] == "CLOSED"
        assert closed["held_balance_cents"] == 50_000

        decide_appeal(
            api, appeal["id"], "GRANT", USER_COMMITTEE_02, reinstatement_reserve_pct_bps=900
        )

        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["state"] == "ACCRUING"
        assert account["reserve_pct_bps"] == 900
        assert account["released_to_date_cents"] == 50_000
        assert account["held_balance_cents"] == 0

        entries = list_reserve_ledger(api, onboarded.reserve_account_id)
        reinstatements = [
            entry for entry in entries if entry["reason_code"] == "REINSTATEMENT_RELEASE"
        ]
        assert len(reinstatements) == 1
        assert reinstatements[0]["entry_type"] == "RELEASE"
        assert reinstatements[0]["amount_cents"] == 50_000
        assert reinstatements[0]["effective_date"] == "2026-07-07"
        assert reinstatements[0]["tranche_start_date"] is None
        assert reinstatements[0]["tranche_end_date"] is None

        assert read_merchant(api, onboarded.merchant_id)["pinned_reserve_pct_bps"] == 900
