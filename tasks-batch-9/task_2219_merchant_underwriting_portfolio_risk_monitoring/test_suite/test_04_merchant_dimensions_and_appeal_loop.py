"""Two orthogonal merchant dimensions, and the cyclic appeal negotiation loop."""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data

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
    make_risk_analyst_headers,
    make_risk_committee_headers,
    onboard_standard_merchant,
    propose_termination,
    read_appeal,
    read_batch,
    read_merchant,
    read_termination_decision,
    request_appeal_info,
    respond_to_appeal,
    review_appeal,
    run_monitoring,
    set_clock,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    USER_COMMITTEE_02,
    USER_TREASURY_01,
)


def _restricted_merchant_with_a_delayed_batch(api):
    """Breach the count-based ratio so the merchant is RESTRICTED with a DELAYED batch."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-08T00:00:00Z",
        legal_business_name="Lantern Goods LLC",
        mcc_code="5999",
        requested_monthly_volume_cents=300_000_000,
        average_ticket_cents=45_000,
        owners=[OwnerSpec(full_name="Omar Diaz")],
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
    run_monitoring(api, "2026-07-10")

    merchant = read_merchant(api, merchant_id)
    assert merchant["account_state"] == "RESTRICTED"
    assert merchant["funding_state"] == "DELAYED"
    return onboarded, batch["id"]


class TestFundingPostureMovesWhileRiskPostureStandsStill:
    """funding_state walks NORMAL to DELAYED to HELD to DELAYED under a frozen RESTRICTED."""

    def test_holding_funding_freezes_the_batches_and_leaves_the_risk_posture_alone(self):
        """The hold empties the payout schedule while account_state stays RESTRICTED.

        PRD 3.8: "Both the `NORMAL -> HELD` and the `DELAYED -> HELD` transitions behave
        identically: `delayed_payout_days` is set to 0, every settlement batch of the merchant
        whose `payout_state` is `SCHEDULED` or `DELAYED` moves to `HELD` with
        `scheduled_payout_date` cleared to null in `period_end_date` then `created_at` ascending
        order, and `pending_payout_cents` is recomputed"

        Design: Difficulty/non_linear_state_machine/merchant_funding_dimension_moves_while_account_dimension_frozen
        """
        api = api_client
        onboarded, batch_id = _restricted_merchant_with_a_delayed_batch(api)

        get_success_data(
            api.place_funding_hold(
                onboarded.merchant_id,
                "EXCESSIVE_CHARGEBACKS",
                make_risk_analyst_headers(USER_ANALYST_01),
            )
        )

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["funding_state"] == "HELD"
        assert merchant["delayed_payout_days"] == 0
        assert merchant["funding_hold_reason_code"] == "EXCESSIVE_CHARGEBACKS"

        batch = read_batch(api, batch_id)
        assert batch["payout_state"] == "HELD"
        assert batch["scheduled_payout_date"] is None

    def test_lifting_the_hold_on_a_restricted_merchant_lands_on_delayed_not_normal(self):
        """The release target is read off the risk dimension, so DELAYED and 7 days come back.

        PRD 3.8: "When `account_state` is `RESTRICTED`, `funding_state` moves `HELD -> DELAYED`
        instead, `funding_hold_reason_code` is cleared, `delayed_payout_days` is set to 7, and
        every `HELD` batch moves to `DELAYED` with `scheduled_payout_date` set to the logical
        clock date plus 7 days."

        Design: Difficulty/non_linear_state_machine/merchant_funding_dimension_moves_while_account_dimension_frozen
        """
        api = api_client
        onboarded, batch_id = _restricted_merchant_with_a_delayed_batch(api)

        get_success_data(
            api.place_funding_hold(
                onboarded.merchant_id,
                "EXCESSIVE_CHARGEBACKS",
                make_risk_analyst_headers(USER_ANALYST_01),
            )
        )
        get_success_data(
            api.release_funding_hold(
                onboarded.merchant_id, make_risk_committee_headers(USER_COMMITTEE_01)
            )
        )

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "RESTRICTED"
        assert merchant["funding_state"] == "DELAYED"
        assert merchant["funding_state"] != "NORMAL"
        assert merchant["delayed_payout_days"] == 7
        assert merchant["funding_hold_reason_code"] is None

        batch = read_batch(api, batch_id)
        assert batch["payout_state"] == "DELAYED"
        assert batch["scheduled_payout_date"] == "2026-07-17"


def _appeal_awaiting_information(api):
    """Terminate a merchant, file an appeal and take it to INFO_REQUESTED."""
    onboarded = onboard_standard_merchant(
        api,
        clock="2026-07-01T00:00:00Z",
        legal_business_name="Beacon Tools LLC",
        mcc_code="5999",
        owners=[OwnerSpec(full_name="Nils Berg")],
    )
    decision = propose_termination(
        api,
        onboarded.merchant_id,
        "EXCESSIVE_CHARGEBACKS",
        USER_ANALYST_01,
        match_listing_flag=True,
    )
    approve_termination(api, decision["id"], USER_COMMITTEE_01)
    set_clock(api, "2026-07-05T00:00:00Z")
    execute_termination(api, decision["id"], USER_TREASURY_01)

    appeal = file_appeal(
        api,
        onboarded.merchant_id,
        decision["id"],
        "Chargeback spike traced to a compromised BIN range; new 3DS rules in force.",
    )
    review_appeal(api, appeal["id"], USER_COMMITTEE_02)
    request_appeal_info(
        api,
        appeal["id"],
        ["Provide the acquirer dispute export for June."],
        USER_COMMITTEE_02,
    )
    return onboarded, decision, appeal


class TestTheAppealNegotiationLoopCountsItsLaps:
    """Two evidence rounds are walked before the appeal is finally upheld."""

    def test_each_answer_returns_the_appeal_to_review_and_counts_one_more_lap(self):
        """Respond, request again, respond: the round count reads 1 then 2, never 1 twice.

        PRD 3.12: "The merchant answers with a `response_text`, which moves the appeal
        `INFO_REQUESTED -> UNDER_REVIEW`, clears `outstanding_info_items` to an empty list and
        increments `response_round_count` by one; only the owning merchant may respond, so
        `X-User-ID` must equal the appeal's `merchant_id`. That lap may repeat without limit, and
        `response_round_count` counts the laps."

        Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle_counts_two_rounds_then_upholds
        """
        api = api_client
        onboarded, _, appeal = _appeal_awaiting_information(api)
        appeal_id = appeal["id"]

        first = respond_to_appeal(
            api, appeal_id, onboarded.merchant_id, "June acquirer dispute export attached."
        )
        assert first["state"] == "UNDER_REVIEW"
        assert first["response_round_count"] == 1
        assert first["outstanding_info_items"] == []

        requested_again = request_appeal_info(
            api,
            appeal_id,
            ["Also provide the 3DS enrollment confirmation."],
            USER_COMMITTEE_02,
        )
        assert requested_again["state"] == "INFO_REQUESTED"
        assert requested_again["response_round_count"] == 1

        second = respond_to_appeal(
            api, appeal_id, onboarded.merchant_id, "3DS enrollment confirmation attached."
        )
        assert second["state"] == "UNDER_REVIEW"
        assert second["response_round_count"] == 2
        assert second["outstanding_info_items"] == []

    def test_upholding_after_two_rounds_changes_nothing_but_the_appeal(self):
        """The terminal UPHELD leaves the executed decision and the terminated merchant as they were.

        PRD 3.12: "`UPHOLD` moves the appeal `UNDER_REVIEW -> UPHELD` and changes nothing else:
        the merchant remains `TERMINATED` and its reserve account remains `CLOSED`."

        Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle_counts_two_rounds_then_upholds
        """
        api = api_client
        onboarded, decision, appeal = _appeal_awaiting_information(api)
        appeal_id = appeal["id"]

        respond_to_appeal(
            api, appeal_id, onboarded.merchant_id, "June acquirer dispute export attached."
        )
        request_appeal_info(
            api,
            appeal_id,
            ["Also provide the 3DS enrollment confirmation."],
            USER_COMMITTEE_02,
        )
        respond_to_appeal(
            api, appeal_id, onboarded.merchant_id, "3DS enrollment confirmation attached."
        )
        decide_appeal(api, appeal_id, "UPHOLD", USER_COMMITTEE_02)

        decided = read_appeal(api, appeal_id)
        assert decided["state"] == "UPHELD"
        assert decided["response_round_count"] == 2
        assert decided["outstanding_info_items"] == []

        assert read_termination_decision(api, decision["id"])["state"] == "EXECUTED"

        merchant = read_merchant(api, onboarded.merchant_id)
        assert merchant["account_state"] == "TERMINATED"
        assert merchant["funding_state"] == "HELD"
