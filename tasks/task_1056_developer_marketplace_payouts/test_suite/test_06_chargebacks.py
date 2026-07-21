"""Chargebacks: representment window, the lost-dispute cascade and its reversal."""
from test_helpers import (
    ApiErrorId,
    assert_developer_accrual_identity,
    file_chargeback,
    ledger_entries,
    lose_chargeback,
    read_developer,
    record_and_capture,
    set_clock,
    setup_marketplace_with_live_app,
    setup_paid_batch_for_purchase,
    single_line_purchase,
    unsettled_ledger_entries,
    validate_error,
    validate_success,
)


def test_representment_exactly_seven_days_after_receipt_is_rejected(api, finance_headers):
    """PRD 3.7: "`FinanceOps` may contest a received dispute by supplying an
    `evidence_ref`, moving it `RECEIVED → REPRESENTED`. The representment window is short:
    the logical clock must be strictly before `received_at` plus seven days. At exactly
    seven days the window has closed, and the attempt is rejected with
    `ERR_REPRESENTMENT_WINDOW_EXPIRED`."

    Design: Corner/validations/corner_chargeback_representment_after_window_returns_422
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Represent", "category": "FINANCE"},
        developer_overrides={"legal_name": "Represent Co", "email": "rp@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-REPR",
        line_items=single_line_purchase(10000),
    )
    chargeback = file_chargeback(api, purchase["id"], 10000, "CB-WIN-1")
    assert chargeback["status"] == "RECEIVED"
    assert chargeback["clawback_cents"] == 0

    set_clock(api, "2026-07-08T00:00:00Z")  # exactly seven days after receipt

    response = api.represent_chargeback(
        chargeback["id"], {"evidence_ref": "EV-1"}, finance_headers
    )
    validate_error(response, ApiErrorId.ERR_REPRESENTMENT_WINDOW_EXPIRED)
    assert response.status_code == 422
    assert validate_success(
        api.get_chargeback(chargeback["id"], finance_headers)
    )["status"] == "RECEIVED"


def test_lost_dispute_claws_back_the_whole_provisional_net(api, finance_headers):
    """PRD 3.7: "The amount reversed, `clawback_cents`, is the purchase's
    `provisional_developer_net_cents` less the sum of `developer_net_reversal_cents` over
    the executed refunds already booked on that purchase, floored at 0 — so a purchase
    that was never refunded gives back the whole provisional net, and a purchase that was
    partly refunded gives back only what the developer still holds."
    PRD 3.7: "A ledger entry of `entry_type` `CLAWBACK` is written whose `amount_cents` is
    the negative of `clawback_cents`."

    Design: Difficulty/transitive_cascade/chargeback_lost_clawback_drives_negative_balance_and_payout_hold
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Dispute App", "category": "FINANCE"},
        developer_overrides={"legal_name": "Dispute Devs", "email": "d@dispute.test"},
    )
    paid = setup_paid_batch_for_purchase(
        api, ctx["app_id"], ctx["plan_id"], 10000, external_order_ref="ORD-CB"
    )
    purchase = paid["purchase"]

    lost = lose_chargeback(api, purchase["id"], 10000, "CB-NEG-1")
    assert lost["status"] == "LOST"
    assert lost["clawback_cents"] == 7000

    clawbacks = ledger_entries(api, purchase_id=purchase["id"], entry_type="CLAWBACK")
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount_cents"] == -7000
    assert clawbacks[0]["settled"] is False


def test_lost_dispute_drives_negative_balance_and_holds_payouts(api, finance_headers):
    """PRD 3.7: "The developer's `unpaid_accrual_cents` is then recomputed from the
    unsettled ledger, and when that recomputation comes out negative the shortfall is
    moved: `negative_balance_cents` becomes the magnitude of the negative accrual,
    `unpaid_accrual_cents` is set to 0, and `payout_hold` is set to true."
    PRD 3.7: "A dispute lost against a purchase whose `settlement_status` was already
    `PAID` follows the same shape on the settlement dimension, `PAID → CLAWED_BACK`, with
    the clawback entry written unsettled so that it drives the accrual negative and
    therefore the negative balance positive — the marketplace recovers money it has
    already paid out of future earnings."

    Design: Difficulty/transitive_cascade/chargeback_lost_clawback_drives_negative_balance_and_payout_hold
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Dispute App", "category": "FINANCE"},
        developer_overrides={"legal_name": "Dispute Devs", "email": "d@dispute.test"},
    )
    paid = setup_paid_batch_for_purchase(
        api, ctx["app_id"], ctx["plan_id"], 10000, external_order_ref="ORD-CB-2"
    )
    purchase = paid["purchase"]
    assert validate_success(
        api.get_purchase(purchase["id"], finance_headers)
    )["settlement_status"] == "PAID"

    lose_chargeback(api, purchase["id"], 10000, "CB-NEG-2")

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["payment_status"] == "CHARGED_BACK"
    assert after["settlement_status"] == "CLAWED_BACK"

    developer = read_developer(api, ctx["developer_id"])
    assert developer["unpaid_accrual_cents"] == 0
    assert developer["negative_balance_cents"] == 7000
    assert developer["payout_hold"] is True


def test_chargeback_reversal_restores_the_accrual_and_clears_the_hold(api, finance_headers):
    """PRD 3.7: "Reversal is the compensating action, taken with a `reason` when the
    network overturns its own decision, and it is available only from `LOST`."
    PRD 3.7: "The test of a correct reversal is arithmetic: the developer's accrual less
    the developer's negative balance must equal the sum of `amount_cents` over that
    developer's unsettled ledger entries, both before the dispute was lost and again after
    it has been reversed, with both sides returned to their pre-dispute values."

    Design: Difficulty/compensating_invariant/chargeback_reversal_restores_developer_unsettled_accrual_balance
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Rev App", "category": "GAMES"},
        developer_overrides={"legal_name": "Reversal Rangers", "email": "r@rev.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-REV",
        line_items=single_line_purchase(10000),
    )
    before = read_developer(api, ctx["developer_id"])
    assert before["unpaid_accrual_cents"] == 7000
    assert_developer_accrual_identity(
        before, unsettled_ledger_entries(api, ctx["developer_id"])
    )

    chargeback = lose_chargeback(api, purchase["id"], 10000, "CB-REV-1")
    mid = read_developer(api, ctx["developer_id"])
    assert mid["unpaid_accrual_cents"] == 0

    reversed_cb = validate_success(
        api.reverse_chargeback(
            chargeback["id"], {"reason": "issuer reversed the dispute"}, finance_headers
        )
    )
    assert reversed_cb["status"] == "REVERSED"

    after = read_developer(api, ctx["developer_id"])
    assert after["unpaid_accrual_cents"] == 7000
    assert after["negative_balance_cents"] == 0
    assert after["payout_hold"] is False
    assert_developer_accrual_identity(
        after, unsettled_ledger_entries(api, ctx["developer_id"])
    )


def test_chargeback_reversal_returns_the_purchase_to_captured_and_accrued(api, finance_headers):
    """PRD 3.7: "The dispute moves `LOST → REVERSED`; a ledger entry of `entry_type`
    `CLAWBACK_REVERSAL` is written whose `amount_cents` is the positive `clawback_cents`;
    the purchase's `payment_status` returns to `CAPTURED` when its `refunded_gross_cents`
    is 0 and to `PARTIALLY_REFUNDED` otherwise; the `settlement_status` returns to
    `ACCRUED`; and `unpaid_accrual_cents`, `negative_balance_cents` and `payout_hold` are
    all recomputed from the ledger, as is the risk score with its `risk_variant`."

    Design: Difficulty/compensating_invariant/chargeback_reversal_restores_developer_unsettled_accrual_balance
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Rev App", "category": "GAMES"},
        developer_overrides={"legal_name": "Reversal Rangers", "email": "r@rev.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-REV-2",
        line_items=single_line_purchase(10000),
    )
    chargeback = lose_chargeback(api, purchase["id"], 10000, "CB-REV-2")
    validate_success(
        api.reverse_chargeback(chargeback["id"], {"reason": "network overturned"},
                               finance_headers)
    )

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["payment_status"] == "CAPTURED"
    assert after["settlement_status"] == "ACCRUED"

    credits = ledger_entries(api, purchase_id=purchase["id"],
                             entry_type="CLAWBACK_REVERSAL")
    assert len(credits) == 1
    assert credits[0]["amount_cents"] == 7000
