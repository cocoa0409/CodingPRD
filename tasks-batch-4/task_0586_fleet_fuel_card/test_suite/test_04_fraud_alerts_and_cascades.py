"""The fraud-review axis, the alert cycle, and the confirm cascade that reaches
all the way down to the account ledger."""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    assert_credit_ledger_invariant,
    assert_fraud_alert,
    capture_fill,
    read_account,
    read_card,
    read_transaction,
    resolution_note_payload,
    setup_cascade_scenario,
    setup_confirmed_alert,
    setup_flagged_transaction,
    setup_investigating_alert,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# The alert cycle: CONFIRMED -> INVESTIGATING -> CONFIRMED
# --------------------------------------------------------------------------- #

def test_reopen_cycles_confirmed_alert_back_to_investigating(api):
    """PRD §3.6: "A confirmed alert may be reopened by a `FraudAnalyst`, cycling it
    from `CONFIRMED` back to `INVESTIGATING` for further review; reopening does not
    un-suspend the card."

    Design: Difficulty/non_linear_state_machine/fraud_alert_reopen_cycle_confirmed_to_investigating
    """
    scenario = setup_confirmed_alert(api)
    assert scenario["alert"]["status"] == "CONFIRMED"

    reopened = validate_success(
        api.reopen_fraud_alert(
            scenario["alert"]["id"], ANALYST, resolution_note_payload("need another look")
        )
    )

    assert_fraud_alert(reopened)
    assert reopened["status"] == "INVESTIGATING", (
        "reopen is the back-edge CONFIRMED -> INVESTIGATING"
    )


def test_reopen_does_not_unsuspend_the_card(api):
    """PRD §3.6: "A confirmed alert may be reopened by a `FraudAnalyst`, cycling it
    from `CONFIRMED` back to `INVESTIGATING` for further review; reopening does not
    un-suspend the card."
    PRD §3.6: "Confirming requires the alert be `INVESTIGATING` and the alert's card
    not be `CANCELLED`; on confirm, the alert moves to `CONFIRMED` and, as the root
    of a cascade, its `FuelCard` is transitioned `ACTIVE → SUSPENDED` — which itself
    voids the card's open transactions, which themselves release holds and reverse
    accrued rebate."

    Design: Difficulty/non_linear_state_machine/fraud_alert_reopen_cycle_confirmed_to_investigating
    """
    scenario = setup_confirmed_alert(api)
    account_id = scenario["account"]["id"]
    card_id = scenario["card"]["id"]
    assert read_card(api, account_id, card_id)["status"] == "SUSPENDED"

    validate_success(api.reopen_fraud_alert(scenario["alert"]["id"], ANALYST))

    assert read_card(api, account_id, card_id)["status"] == "SUSPENDED", (
        "cycling the alert back to INVESTIGATING must leave the card suspended"
    )


# --------------------------------------------------------------------------- #
# The two axes of a transaction evolve independently
# --------------------------------------------------------------------------- #

def test_dismiss_clears_review_axis_without_touching_posting_axis(api):
    """PRD §3.5: "A posting transition never changes the review axis and vice versa."
    PRD §3.6: "Dismissing requires the alert be `INVESTIGATING`; it moves the alert
    to the terminal `DISMISSED` and, on the review axis, transitions the flagged
    transaction's `review_status` from `FLAGGED` to `CLEARED` (leaving
    `posting_status` untouched)."

    Design: Difficulty/non_linear_state_machine/transaction_posting_and_review_axes_independent
    """
    scenario = setup_investigating_alert(api, capture_txn=True)
    txn_id = scenario["transaction"]["id"]
    assert scenario["transaction"]["posting_status"] == "CAPTURED"
    assert scenario["transaction"]["review_status"] == "FLAGGED"

    dismissed = validate_success(
        api.dismiss_fraud_alert(
            scenario["alert"]["id"], ANALYST, resolution_note_payload("false positive")
        )
    )
    assert dismissed["status"] == "DISMISSED"

    txn = read_transaction(api, txn_id)
    assert txn["review_status"] == "CLEARED", "the review axis advances FLAGGED -> CLEARED"
    assert txn["posting_status"] == "CAPTURED", "the money axis is untouched by the dismissal"


def test_capture_does_not_touch_the_review_axis(api):
    """PRD §3.5: "A transaction carries two independent status axes."
    PRD §3.5: "A posting transition never changes the review axis and vice versa."
    PRD §3.4: "A `FuelCard`'s tank-fill exposure is checked against the resolved
    vehicle: when a fill's `gallons` exceeds the vehicle's `tank_capacity_gallons`,
    the transaction still authorizes but its `review_status` is set to `FLAGGED` and
    a `FraudAlert` is created in status `OPEN`, recording the flagged
    `transaction_id`, the `card_id`, and a `rule_code` of `OVER_TANK_FILL`."

    Design: Difficulty/non_linear_state_machine/transaction_posting_and_review_axes_independent
    """
    scenario = setup_flagged_transaction(api)
    txn = scenario["transaction"]
    assert txn["posting_status"] == "AUTHORIZED"
    assert txn["review_status"] == "FLAGGED"

    captured = capture_fill(api, txn["id"])

    assert captured["posting_status"] == "CAPTURED", "the money axis advances"
    assert captured["review_status"] == "FLAGGED", (
        "a posting transition leaves the fraud-review axis exactly where it was"
    )


# --------------------------------------------------------------------------- #
# Confirm: FraudAlert -> FuelCard -> Transaction -> FleetAccount
# --------------------------------------------------------------------------- #

def test_confirming_alert_suspends_card_and_voids_its_open_transactions(api):
    """PRD §3.6: "Confirming requires the alert be `INVESTIGATING` and the alert's
    card not be `CANCELLED`; on confirm, the alert moves to `CONFIRMED` and, as the
    root of a cascade, its `FuelCard` is transitioned `ACTIVE → SUSPENDED` — which
    itself voids the card's open transactions, which themselves release holds and
    reverse accrued rebate."
    PRD §3.2: "Suspension is not merely a flag: every transaction of this card whose
    `posting_status` is `AUTHORIZED` or `CAPTURED` is transitioned to `VOIDED`, which
    in turn releases each transaction's hold and reverses any rebate that transaction
    had accrued (§3.5)."

    Design: Difficulty/transitive_cascade/fraud_confirm_cascades_card_txn_ledger_depth3
    """
    scenario = setup_cascade_scenario(api)

    confirmed = validate_success(
        api.confirm_fraud_alert(
            scenario["alert"]["id"], ANALYST, resolution_note_payload("confirmed skimming")
        )
    )

    assert confirmed["status"] == "CONFIRMED"
    card = read_card(api, scenario["account"]["id"], scenario["card"]["id"])
    assert card["status"] == "SUSPENDED", "link 1: the alert's card is suspended"

    normal = read_transaction(api, scenario["normal_txn"]["id"])
    flagged = read_transaction(api, scenario["flagged_txn"]["id"])
    assert normal["posting_status"] == "VOIDED", "link 2: the CAPTURED fill is voided"
    assert flagged["posting_status"] == "VOIDED", "link 2: the AUTHORIZED fill is voided"


def test_confirming_alert_reverses_holds_and_rebate_on_the_account(api):
    """PRD §3.6: "Confirming requires the alert be `INVESTIGATING` and the alert's
    card not be `CANCELLED`; on confirm, the alert moves to `CONFIRMED` and, as the
    root of a cascade, its `FuelCard` is transitioned `ACTIVE → SUSPENDED` — which
    itself voids the card's open transactions, which themselves release holds and
    reverse accrued rebate."
    PRD §3.5: "Voiding a `CAPTURED` transaction moves it to `VOIDED`, sets
    `hold_amount_cents` to 0, and subtracts the previously accrued
    `provisional_rebate_cents` from the account's `rebate_accrual_cents`."
    PRD §2.7: "`available_credit_cents` is `credit_limit_cents` minus
    `outstanding_holds_cents` minus `settled_spend_cents`."

    Design: Difficulty/transitive_cascade/fraud_confirm_cascades_card_txn_ledger_depth3
    """
    scenario = setup_cascade_scenario(api)
    account_id = scenario["account"]["id"]
    before = read_account(api, account_id)
    assert before["rebate_accrual_cents"] == 500, "the captured 100-gallon fill accrued 500"
    assert before["outstanding_holds_cents"] == 120_000, "40000 + 80000 held"

    validate_success(api.confirm_fraud_alert(scenario["alert"]["id"], ANALYST))

    account = read_account(api, account_id)
    assert account["rebate_accrual_cents"] == 0, "link 3: the accrued rebate is reversed"
    assert account["outstanding_holds_cents"] == 0, "link 3: both holds are released"
    assert account["available_credit_cents"] == 100_000_000, (
        "available credit returns to the whole limit"
    )
    assert_credit_ledger_invariant(account)


# --------------------------------------------------------------------------- #
# Alert state guards
# --------------------------------------------------------------------------- #

def test_dismiss_of_open_alert_rejected(api):
    """PRD §3.6: "Dismissing requires the alert be `INVESTIGATING`; it moves the
    alert to the terminal `DISMISSED` and, on the review axis, transitions the
    flagged transaction's `review_status` from `FLAGGED` to `CLEARED` (leaving
    `posting_status` untouched)."
    PRD §2.9: "5. **Transition state** — the target is in a state that permits the
    requested transition, else the applicable state error: `ERR_CARD_NOT_ACTIVE`,
    `ERR_INVALID_CARD_STATE`, `ERR_INVALID_TXN_STATE`, `ERR_INVALID_ALERT_STATE`,
    `ERR_INVALID_FAULT_STATE`, or `ERR_INVALID_REPORT_STATE` (all 409)."

    Design: Corner/state_machines/dismiss_open_alert_rejected_idempotency
    """
    scenario = setup_flagged_transaction(api)
    assert scenario["alert"]["status"] == "OPEN"

    resp = api.dismiss_fraud_alert(
        scenario["alert"]["id"], ANALYST, resolution_note_payload("premature")
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_ALERT_STATE.value)
