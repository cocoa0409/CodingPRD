"""Scam and fraud response: intake scoring, re-scoring at acknowledgement, the
checkpoint escalation, and the account freeze sweep."""

from test_helpers import (
    acknowledge_fraud_alert,
    assert_fraud_alert,
    assert_instant_offset,
    assert_same_instant,
    change_period_status,
    confirm_fraud_alert,
    list_ledger_entries,
    open_period,
    raise_fraud_alert,
    read_account,
    read_bond,
    read_budget_category,
    read_fraud_alert,
    read_payee,
    read_payment,
    read_period,
    release_payment,
    run_checkpoint,
    schedule_payment,
    set_clock,
    settle_payment,
    setup_billpay_world,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]


def test_intake_scoring_bands_the_alert_and_sets_the_acknowledgement_deadline():
    """PRD §3.5: "*Amount.* A payment of 500000 cents or more contributes 50
    points. A payment of at least 100000 cents but below 500000 contributes 30
    points. Anything below 100000 cents contributes 10 points."
    PRD §3.5: "*Novelty.* A payee whose `settled_payment_count` is exactly zero
    — the practice has never successfully paid them — contributes 40 points."
    PRD §3.5: "*Channel.* A `CHECK` payment contributes 20 points, an `ACH`
    payment 10, and a `BILLER_DIRECT` payment none."
    PRD §3.5: "The band then sets the acknowledgement clock: `ack_due_at` is
    the alert's `created_at` plus 4 hours for a `HIGH` band, plus 24 hours for
    `MEDIUM`, and plus 72 hours for `LOW`."

    Design: Difficulty/dual_variant_calc/fraud_intake_band_vs_review_band_fall_a_step
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=400000)
    payment = schedule_payment(world, amount_cents=120000, channel="CHECK")

    alert = raise_fraud_alert(
        world["account"]["id"],
        payment["id"],
        reason_code="UNRECOGNIZED_PAYEE",
        detail="Client does not recognise this care agency.",
    )

    assert_fraud_alert(alert)
    # 30 (amount) + 40 (never paid) + 20 (CHECK) = 90.
    assert alert["intake_risk_score"] == 90
    assert alert["intake_risk_band"] == "HIGH"
    assert alert["status"] == "NEW"
    assert alert["review_risk_score"] is None
    assert alert["review_risk_band"] is None
    assert_same_instant(alert["ack_due_at"], "2026-06-01T13:00:00Z", "FraudAlert.ack_due_at")
    assert_instant_offset(alert["ack_due_at"], alert["created_at"], 4, "FraudAlert.ack_due_at")


def test_acknowledgement_rescores_the_alert_and_drops_the_band_a_step():
    """PRD §3.5: "An `ACKNOWLEDGE` moves the alert from `NEW` or from
    `ESCALATED` into `ACKNOWLEDGED` — the escalated path rejoins the ordinary
    one and is adjudicated identically — writes the current logical instant to
    `acknowledged_at`, and **re-scores the alert**."
    PRD §3.5: "If payments to that payee settled between intake and
    acknowledgement, the novelty component drops from 40 to 20 or from 20 to 0
    and the band can fall a whole step — while `ack_due_at` keeps the deadline
    the intake band gave it, because the deadline was set once and is never
    recomputed."

    Design: Difficulty/dual_variant_calc/fraud_intake_band_vs_review_band_fall_a_step
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=400000)
    flagged = schedule_payment(world, amount_cents=120000, channel="CHECK")
    alert = raise_fraud_alert(
        world["account"]["id"],
        flagged["id"],
        reason_code="UNRECOGNIZED_PAYEE",
        detail="Client does not recognise this care agency.",
    )
    assert alert["intake_risk_band"] == "HIGH"

    # A second, smaller payment to the SAME payee settles in between, lifting
    # settled_payment_count from 0 to 1.
    other = schedule_payment(world, amount_cents=30000, channel="BILLER_DIRECT")
    release_payment(other["id"])
    settle_payment(other["id"])
    assert read_payee(world["payee"]["id"])["settled_payment_count"] == 1

    acknowledged = acknowledge_fraud_alert(
        alert["id"], disposition_note="Reviewed with the client by phone."
    )

    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["intake_risk_score"] == 90
    assert acknowledged["intake_risk_band"] == "HIGH"
    # 30 (amount) + 20 (thin history) + 20 (CHECK) = 70.
    assert acknowledged["review_risk_score"] == 70
    assert acknowledged["review_risk_band"] == "MEDIUM"
    assert_same_instant(
        acknowledged["ack_due_at"], "2026-06-01T13:00:00Z", "FraudAlert.ack_due_at"
    )


def test_the_checkpoint_escalates_a_new_alert_at_exactly_its_deadline():
    """PRD §3.9: "It moves every fraud alert still in `NEW` whose `ack_due_at`
    is at or before the current logical instant into `ESCALATED`, counting them
    as `alerts_escalated`."
    PRD §3.5: "The periodic checkpoint of §3.9 moves every alert still in `NEW`
    whose `ack_due_at` is at or before the current logical instant into
    `ESCALATED`; the boundary is inclusive, so an alert whose deadline equals
    the clock exactly is escalated."

    Design: Corner/state_machines/corner_checkpoint_escalates_fraud_alert_at_the_acknowledgement_deadline
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    alert = raise_fraud_alert(
        world["account"]["id"],
        payment["id"],
        reason_code="AMOUNT_ANOMALY",
        detail="Three times the usual utility bill.",
        headers=SPECIALIST,
    )
    # 10 (amount) + 40 (never paid) + 10 (ACH) = 60, a MEDIUM band with a
    # 24-hour acknowledgement SLA.
    assert alert["intake_risk_score"] == 60
    assert alert["intake_risk_band"] == "MEDIUM"
    assert_same_instant(alert["ack_due_at"], "2026-06-02T09:00:00Z", "FraudAlert.ack_due_at")

    set_clock("2026-06-02T09:00:00Z")
    swept = run_checkpoint()

    assert swept["alerts_escalated"] == 1
    assert read_fraud_alert(alert["id"])["status"] == "ESCALATED"
    assert read_account(world["account"]["id"])["fraud_posture"] == "NORMAL"


def test_confirming_fraud_freezes_the_account_and_stops_the_in_flight_payment():
    """PRD §3.5: "A `CONFIRM_FRAUD` moves it to `CONFIRMED_FRAUD` and, caused
    by that confirmation, drives the named account's `fraud_posture` to
    `FROZEN`, which in turn runs the freeze sweep below."
    PRD §3.5: "**Hop B.** A payment whose `settlement_status` is `IN_FLIGHT`
    moves to `STOPPED`. It decrements the same three aggregates in the same way
    **and**, unlike hop A, appends one `STOP_PAYMENT_FEE` ledger entry of
    negative 3000 cents dated the current logical date."

    Design: Difficulty/transitive_cascade/fraud_confirm_freezes_account_stops_payment_and_reopens_period
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    period = open_period(world["account"]["id"], "2026-06")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    release_payment(payment["id"])
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)
    alert = raise_fraud_alert(
        world["account"]["id"],
        payment["id"],
        reason_code="THIRD_PARTY_REPORT",
        detail="Adult protective services flagged this remittance.",
    )
    acknowledge_fraud_alert(alert["id"])

    confirmed = confirm_fraud_alert(alert["id"], disposition_note="Confirmed scam remittance.")

    assert confirmed["status"] == "CONFIRMED_FRAUD"
    assert confirmed["intake_risk_score"] == 60
    assert confirmed["intake_risk_band"] == "MEDIUM"
    assert read_account(world["account"]["id"])["fraud_posture"] == "FROZEN"
    assert read_payment(payment["id"])["settlement_status"] == "STOPPED"

    entries = list_ledger_entries(world["account"]["id"])
    assert len(entries) == 1, f"Expected exactly one ledger entry, got {entries}"
    assert entries[0]["entry_type"] == "STOP_PAYMENT_FEE"
    assert entries[0]["amount_cents"] == -3000


def test_the_stop_fee_entry_reverts_the_receiving_period_from_in_review_to_open():
    """PRD §3.5: "**Hop C.** Caused by hop B's new entry: the reconciliation
    period that receives that entry has its `unreconciled_entry_count` raised
    by one."
    PRD §3.5: "**Hop D.** Caused by hop C: if — and only if — that receiving
    period's `status` is `IN_REVIEW`, it reverts to `OPEN`, because a period
    under review can no longer be reviewed once a fresh unreconciled entry has
    landed in it."

    Design: Difficulty/transitive_cascade/fraud_confirm_freezes_account_stops_payment_and_reopens_period
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    period = open_period(world["account"]["id"], "2026-06")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    release_payment(payment["id"])
    change_period_status(period["id"], "IN_REVIEW", SPECIALIST)
    alert = raise_fraud_alert(
        world["account"]["id"],
        payment["id"],
        reason_code="THIRD_PARTY_REPORT",
        detail="Adult protective services flagged this remittance.",
    )
    acknowledge_fraud_alert(alert["id"])

    confirm_fraud_alert(alert["id"], disposition_note="Confirmed scam remittance.")

    after = read_period(period["id"])
    assert after["unreconciled_entry_count"] == 1
    assert after["status"] == "OPEN"

    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
    assert account["cleared_balance_cents"] == 4997000
    assert account["available_balance_cents"] == 4997000
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 0
    assert read_bond(world["bond"]["id"])["exposure_committed_cents"] == 0
