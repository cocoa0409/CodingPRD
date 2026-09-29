"""Edges where one cent or one point inverts the answer.

The liquidity bands are closed at their lower ends, so a balance sitting exactly on a
threshold belongs to the lower band — and that single comparison decides the tier, the
alert's threshold figure, the posture and whether in-flight traffic is parked.

The reconciliation tolerance is inclusive too, and it is tested on an empty input set so
that "no rows" is proven legal and a zero fee is proven to post no entry at all. The
fraud hold band closes the same way: exactly sixty holds, fifty-nine clears.
"""

from test_helpers import (
    FRAUD_HOLD_THRESHOLD,
    PAYMENT_OPERATOR_DELTA,
    ROUTING_BETA,
    SEGMENT_MULTIPLIERS,
    VARIANCE_TOLERANCE_CENTS,
    assert_account_position,
    assert_alert,
    assert_fraud_review_shape,
    assert_ledger_entry,
    assert_reconciliation_figures,
    configure_participant,
    cutoff_cycle,
    list_alerts,
    list_fraud_reviews,
    list_ledger_entries,
    live_alpha,
    live_delta,
    open_settlement_cycle,
    originate_transfer,
    read_account,
    read_cycle,
    read_participant,
    set_clock,
    submit_reconciliation_run,
    withdraw_from_account,
)

DELTA_CONSUMER_POLICY = {
    "segment": "CONSUMER",
    "per_transaction_limit_cents": 5_000_000,
    "daily_aggregate_limit_cents": 20_000_000,
    "rolling_window_count_limit": 5,
    "rolling_window_amount_limit_cents": 10_000_000,
    "effective_from": "2026-08-01T00:00:00Z",
}


def _live_alpha_position(api):
    """Alpha live with 1,200,000,000 cents and the standard three thresholds."""
    set_clock(api, "2026-08-03T13:00:00Z")
    return live_alpha(api)


def test_balance_landing_exactly_on_the_critical_threshold_is_red(api):
    """Equality belongs to the lower band, and the whole chain follows from it.

    PRD 2.9: "If the balance is strictly below `floor_cents` the tier is `BREACH`;
    otherwise, if it is at or below `critical_threshold_cents` the tier is `RED`;
    otherwise, if it is at or below `warning_threshold_cents` the tier is `AMBER`;
    otherwise the tier is `GREEN`."

    Design: Difficulty/boundary_precision_check/balance_exactly_at_critical_threshold_is_red
    """
    alpha = _live_alpha_position(api)

    withdraw_from_account(api, alpha.account_id, 200_000_000, "Return of surplus prefunding")

    entries = list_ledger_entries(api, alpha.account_id)
    assert len(entries) == 1
    assert_ledger_entry(
        entries[0],
        entry_type="WITHDRAWAL_DEBIT",
        amount_cents=-200_000_000,
        balance_after_cents=1_000_000_000,
        sequence_no=1,
    )

    account = read_account(api, alpha.account_id)
    assert account["current_balance_cents"] == account["critical_threshold_cents"]
    assert_account_position(
        account,
        current_balance_cents=1_000_000_000,
        reserved_cents=0,
        available_cents=1_000_000_000,
        alert_tier="RED",
    )

    alerts = list_alerts(api, alpha.account_id)
    assert len(alerts) == 1
    assert_alert(
        alerts[0],
        tier="RED",
        status="OPEN",
        threshold_cents=1_000_000_000,
        observed_balance_cents=1_000_000_000,
    )
    assert read_participant(api, alpha.id)["operational_posture"] == "SEND_FROZEN"


def test_one_cent_above_the_critical_threshold_is_amber(api):
    """A single cent moves the tier, the alert's threshold figure and the posture.

    PRD 2.9: "its `threshold_cents` set to the constant that was crossed —
    `warning_threshold_cents` for an `AMBER` alert, `critical_threshold_cents` for a
    `RED` alert, and `floor_cents` for a `BREACH` alert."

    Design: Difficulty/boundary_precision_check/balance_exactly_at_critical_threshold_is_red
    """
    alpha = _live_alpha_position(api)

    withdraw_from_account(api, alpha.account_id, 199_999_999, "Return of surplus prefunding")

    assert_account_position(
        read_account(api, alpha.account_id),
        current_balance_cents=1_000_000_001,
        reserved_cents=0,
        available_cents=1_000_000_001,
        alert_tier="AMBER",
    )

    alerts = list_alerts(api, alpha.account_id)
    assert len(alerts) == 1
    assert_alert(
        alerts[0],
        tier="AMBER",
        status="OPEN",
        threshold_cents=1_100_000_000,
        observed_balance_cents=1_000_000_001,
    )
    assert read_participant(api, alpha.id)["operational_posture"] == "THROTTLED"


def test_balance_resting_exactly_on_the_floor_is_red_and_not_breach(api):
    """The floor comparison is strict, so equality stays in the band above.

    PRD 3.3: "An adjustment may take the balance below `floor_cents`, which is exactly
    the situation a `BREACH` band is meant to surface, but it may never take
    `current_balance_cents` below zero; an adjustment that would is refused with
    `ERR_LEDGER_ADJUSTMENT_WOULD_GO_NEGATIVE`."

    Design: Difficulty/boundary_precision_check/balance_exactly_at_critical_threshold_is_red
    """
    alpha = _live_alpha_position(api)
    withdraw_from_account(api, alpha.account_id, 200_000_000)

    withdraw_from_account(api, alpha.account_id, 800_000_000, "Second surplus return")

    account = read_account(api, alpha.account_id)
    assert account["current_balance_cents"] == account["floor_cents"]
    assert_account_position(
        account,
        current_balance_cents=200_000_000,
        reserved_cents=0,
        available_cents=200_000_000,
        alert_tier="RED",
    )
    entries = list_ledger_entries(api, alpha.account_id)
    assert len(entries) == 2
    assert_ledger_entry(
        entries[1],
        entry_type="WITHDRAWAL_DEBIT",
        amount_cents=-800_000_000,
        balance_after_cents=200_000_000,
        sequence_no=2,
    )
    alerts = list_alerts(api, alpha.account_id)
    assert len(alerts) == 1
    assert alerts[0]["tier"] == "RED"
    assert read_participant(api, alpha.id)["operational_posture"] == "SEND_FROZEN"


def _empty_cut_off_cycle(api):
    """A live bank that settled nothing, with its cycle taken to cutoff."""
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    cycle = open_settlement_cycle(api, "2026-08-03")
    set_clock(api, "2026-08-03T23:00:00Z")
    cut = cutoff_cycle(api, cycle["id"])
    assert cut["status"] == "CUTOFF"
    assert cut["assessed_fee_total_cents"] == 0
    assert cut["settled_transfer_count"] == 0
    assert list_ledger_entries(api, alpha.account_id) == []
    assert_account_position(
        read_account(api, alpha.account_id),
        current_balance_cents=1_200_000_000,
        reserved_cents=0,
        available_cents=1_200_000_000,
        alert_tier="GREEN",
    )
    set_clock(api, "2026-08-03T23:30:00Z")
    return alpha, cycle


def test_variance_of_exactly_the_tolerance_balances_on_an_empty_input_set(api):
    """Zero rows is legal, and a variance sitting on the tolerance is still balanced.

    PRD 3.10: "The `outcome` is `BALANCED` when the magnitude of the variance is at or
    below the tolerance of 100 cents — a variance of exactly 100 cents in either
    direction is `BALANCED` — and `OUT_OF_BALANCE` otherwise."

    Design: Difficulty/boundary_precision_check/empty_input_reconciliation_variance_at_tolerance_edge
    """
    alpha, cycle = _empty_cut_off_cycle(api)

    run = submit_reconciliation_run(api, cycle["id"], alpha.id, VARIANCE_TOLERANCE_CENTS, "FINAL")

    assert run["variant"] == "FINAL"
    assert_reconciliation_figures(
        run,
        rail_net_position_cents=0,
        variance_cents=100,
        outcome="BALANCED",
        included_transfer_count=0,
        fee_component_cents=0,
        revision=1,
    )
    assert read_cycle(api, cycle["id"])["status"] == "RECONCILING"
    assert list_ledger_entries(api, alpha.account_id) == []


def test_one_cent_past_the_tolerance_puts_the_cycle_out_of_balance(api):
    """The same empty run one cent further out inverts the outcome and the cycle.

    PRD 3.10: "From those inputs, `rail_net_position_cents` is the credit total minus
    the debit total plus the fee component, `variance_cents` is `core_deposit_total_cents`
    minus that rail net position, and `included_transfer_count` is the number of debit
    rows plus the number of credit rows the variant admitted."

    Design: Difficulty/boundary_precision_check/empty_input_reconciliation_variance_at_tolerance_edge
    """
    alpha, cycle = _empty_cut_off_cycle(api)

    run = submit_reconciliation_run(api, cycle["id"], alpha.id, 101, "FINAL")

    assert_reconciliation_figures(
        run,
        rail_net_position_cents=0,
        variance_cents=101,
        outcome="OUT_OF_BALANCE",
        included_transfer_count=0,
        fee_component_cents=0,
        revision=1,
    )
    assert read_cycle(api, cycle["id"])["status"] == "OUT_OF_BALANCE"


def _live_delta_consumer(api, fraud_risk_baseline):
    """Delta live on a CONSUMER policy with one never-used customer account."""
    set_clock(api, "2026-08-03T13:00:00Z")
    delta = live_delta(api)
    delta = configure_participant(
        api,
        delta,
        policy=DELTA_CONSUMER_POLICY,
        customer_reference="CUST-DELTA-0001",
        customer_segment="CONSUMER",
        fraud_risk_baseline=fraud_risk_baseline,
    )
    open_settlement_cycle(api)
    return delta


def _delta_send(api, delta, amount_cents):
    return originate_transfer(
        api,
        delta.id,
        delta.account_id,
        delta.customer_account_id,
        amount_cents,
        operator=PAYMENT_OPERATOR_DELTA,
        receiver_routing_number=ROUTING_BETA,
    )


def test_score_of_exactly_sixty_is_held_for_review(api):
    """Sixty holds, the multiplier of one is still applied and the zero term is omitted.

    PRD 3.4: "A score of at least 60 but below 85 is held: the transfer moves
    `INITIATED → FRAUD_HOLD`, its amount **stays** inside the reservation set because
    `FRAUD_HOLD` is one of the three reserving states, and one `FraudReview` is created in
    `QUEUED` status with `credit_transfer_id` pointing at the transfer,
    `score_at_origination` copied from the frozen score, `sla_deadline_at` still null, and
    `queue_priority` set to 1 when `score_at_origination` is at least 75 — that is, within
    10 points of the block threshold — and 2 otherwise, with the lower value worked first."

    Design: Difficulty/boundary_precision_check/fraud_score_exactly_at_hold_threshold_holds
    """
    assert SEGMENT_MULTIPLIERS["CONSUMER"] == "1.00"
    delta = _live_delta_consumer(api, 28)

    transfer = _delta_send(api, delta, 1_000_000)

    assert transfer["fraud_score"] == FRAUD_HOLD_THRESHOLD == 60
    assert transfer["clearing_status"] == "FRAUD_HOLD"
    assert transfer["fraud_reason_codes"] == ["AMOUNT_BAND", "NEW_BENEFICIARY"]

    reviews = list_fraud_reviews(api, transfer["id"])
    assert len(reviews) == 1
    review = reviews[0]
    assert_fraud_review_shape(review)
    assert review["status"] == "QUEUED"
    assert review["credit_transfer_id"] == transfer["id"]
    assert review["score_at_origination"] == 60
    assert review["queue_priority"] == 2
    assert review["assigned_reviewer_user_id"] is None
    assert review["sla_deadline_at"] is None

    assert_account_position(
        read_account(api, delta.account_id),
        current_balance_cents=1_200_000_000,
        reserved_cents=1_000_000,
        available_cents=1_199_000_000,
        alert_tier="GREEN",
    )


def test_score_one_point_below_the_hold_threshold_clears(api):
    """One point of baseline is the whole difference between a hold and a clean send.

    PRD 3.4: "A score below 60 leaves the transfer in `INITIATED`, and it proceeds to the
    ordinary clearing path."

    Design: Difficulty/boundary_precision_check/fraud_score_exactly_at_hold_threshold_holds
    """
    delta = _live_delta_consumer(api, 27)

    transfer = _delta_send(api, delta, 1_000_000)

    assert transfer["fraud_score"] == 59
    assert transfer["clearing_status"] == "INITIATED"
    assert list_fraud_reviews(api, transfer["id"]) == []
    assert read_account(api, delta.account_id)["reserved_cents"] == 1_000_000
