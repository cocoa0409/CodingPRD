"""Chargeback receipt cascade, reason-code rule windows, and alert deflection."""
from test_helpers import (
    ALERT_RESPONSE_HOURS,
    DEFAULT_CLOCK_UTC,
    TEST_USERS,
    ApiErrorId,
    assert_chargeback,
    assert_instant_equal,
    assert_prevention_alert,
    create_chargeback_payload,
    create_merchant,
    create_prevention_alert_payload,
    create_reason_code_rule_payload,
    create_rule,
    get_merchant,
    get_success_data,
    ingest_chargeback,
    ingest_sale,
    ledger_entries,
    list_fees,
    make_merchant_user_headers,
    notify,
    reserve_account_for,
    set_clock,
    setup_case,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]


def test_chargeback_deadline_fields_computed_from_logical_clock(api):
    """PRD §3.5: "The case stamps `received_at` from the logical clock,
    computes `representment_due_at` as exactly `representment_days` calendar
    days after `received_at` (the network hard deadline, inclusive)".
    PRD §3.5: "Notification is an `AcquirerOps` action that moves the case
    `RECEIVED` → `MERCHANT_NOTIFIED`, stamps `merchant_notified_at` from the
    logical clock, computes `merchant_response_due_at` as exactly
    `merchant_response_days` calendar days after `merchant_notified_at`".

    Design: Corner/entities/chargeback_computed_deadlines
    """
    bundle = setup_case(api, received_at="2026-07-15T00:00:00Z")
    cb = bundle["chargeback"]
    assert_instant_equal(cb["received_at"], "2026-07-15T00:00:00Z", "received_at")
    assert_instant_equal(
        cb["representment_due_at"], "2026-08-14T00:00:00Z", "representment_due_at"
    )
    # The merchant-response window has a different anchor and does not exist
    # before notification.
    assert cb.get("merchant_response_due_at") is None

    notified = notify(api, cb["id"])
    assert_instant_equal(
        notified["merchant_response_due_at"], "2026-07-22T00:00:00Z",
        "merchant_response_due_at",
    )


def test_initial_states_and_alert_response_window(api):
    """PRD §3.5: "On the lifecycle axis, `case_status` starts at `RECEIVED`; on
    the money axis, `funds_status` starts at `MERCHANT_DEBITED`." and receipt
    "initializes `recredited_cents` to zero and `is_ratio_counted` to true".
    PRD §2.5: "At startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`."
    PRD §3.4: "A new alert is `OPEN`, stamped with `received_at` at ingest, and
    its `response_due_at` is exactly 72 hours later — the response window."

    Design: Corner/state_machines/initial_states_and_alert_window
    """
    bundle = setup_case(api)  # no clock set: receipt happens at the default
    cb = bundle["chargeback"]
    assert_chargeback(cb)
    assert cb["case_status"] == "RECEIVED"
    assert cb["funds_status"] == "MERCHANT_DEBITED"
    assert cb["is_ratio_counted"] is True
    assert cb["recredited_cents"] == 0
    assert_instant_equal(cb["received_at"], DEFAULT_CLOCK_UTC, "received_at")

    resp = api.create_prevention_alert(
        create_prevention_alert_payload(
            transaction_id=bundle["txn"]["id"], alert_type="FRAUD_ALERT"
        ),
        OPS,
    )
    alert = validate_success(resp, 201)
    assert_prevention_alert(alert)
    assert alert["status"] == "OPEN"
    # received at the default clock; response window is exactly 72 hours.
    assert_instant_equal(alert["received_at"], DEFAULT_CLOCK_UTC, "alert received_at")
    assert_instant_equal(
        alert["response_due_at"], "2026-08-04T00:00:00Z", "alert response_due_at"
    )
    assert ALERT_RESPONSE_HOURS == 72


def test_duplicate_network_case_rejected_globally(api):
    """PRD §3.5: "the `network_case_id` must be globally unique across all
    chargebacks (else `ERR_DUPLICATE_NETWORK_CASE`)".

    Design: Corner/validations/duplicate_network_case_rejected
    """
    create_rule(api)
    m1 = create_merchant(api, legal_name="DupA", reserve_rate_bps=0)
    m2 = create_merchant(api, legal_name="DupB", reserve_rate_bps=0)
    ingest_sale(api, m1["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_sale(api, m2["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_chargeback(api, m1["id"], "T-1", "NC-DUP", 5000)

    resp = api.create_chargeback(
        create_chargeback_payload(
            merchant_id=m2["id"],
            transaction_external_ref="T-1",
            network_case_id="NC-DUP",
            amount_cents=5000,
        ),
        OPS,
    )
    # Global uniqueness: a different merchant's sale does not rescue the reuse.
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_NETWORK_CASE)


def test_chargeback_amount_exceeds_transaction_rejected(api):
    """PRD §3.5: "the disputed amount must be strictly positive and no greater
    than the transaction's `amount_cents`, partial chargebacks being allowed,
    else `ERR_CHARGEBACK_AMOUNT_EXCEEDS_TRANSACTION`".

    Design: Corner/validations/chargeback_amount_exceeds_transaction_rejected
    """
    create_rule(api)
    m = create_merchant(api, legal_name="Amt M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_sale(api, m["id"], "T-2", 10000, "2026-07-10T00:00:00Z")

    over = api.create_chargeback(
        create_chargeback_payload(
            merchant_id=m["id"],
            transaction_external_ref="T-1",
            network_case_id="NC-AM1",
            amount_cents=10001,
        ),
        OPS,
    )
    validate_error(over, ApiErrorId.ERR_CHARGEBACK_AMOUNT_EXCEEDS_TRANSACTION)

    partial = api.create_chargeback(
        create_chargeback_payload(
            merchant_id=m["id"],
            transaction_external_ref="T-2",
            network_case_id="NC-AM2",
            amount_cents=6000,
        ),
        OPS,
    )
    data = validate_success(partial, 201)
    assert data["case_status"] == "RECEIVED"
    assert data["amount_cents"] == 6000


def test_rule_window_gap_no_coverage_rejected(api):
    """PRD §3.2: "At chargeback ingest, exactly one rule whose half-open window
    covers the case's `received_at` must exist for the case's (`network`,
    `reason_code`); otherwise ingest fails with `ERR_REASON_CODE_RULE_NOT_FOUND`
    (§3.5)."

    Design: Corner/calculations/rule_window_gap_no_coverage_rejected
    """
    create_rule(api, effective_to="2026-07-01T00:00:00Z")  # covers until July only
    m = create_merchant(api, legal_name="Gap M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-06-20T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")

    resp = api.create_chargeback(
        create_chargeback_payload(
            merchant_id=m["id"],
            transaction_external_ref="T-1",
            network_case_id="NC-G1",
            amount_cents=10000,
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_REASON_CODE_RULE_NOT_FOUND)


def _setup_rule_window_pair(api):
    """R1 covers VISA 10.4 as [2026-01-01, 2026-07-01) fee 2000; R2 continues
    as [2026-07-01, open) fee 3500. Returns the merchant for a June sale."""
    r1 = create_rule(api, chargeback_fee_cents=2000,
                     effective_to="2026-07-01T00:00:00Z")
    assert r1["chargeback_fee_cents"] == 2000
    r2 = create_rule(api, chargeback_fee_cents=3500,
                     effective_from="2026-07-01T00:00:00Z")
    assert r2["chargeback_fee_cents"] == 3500
    m = create_merchant(api, legal_name="Window M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-06-20T00:00:00Z")
    set_clock(api, "2026-07-01T00:00:00Z")
    return m


def test_reason_rule_half_open_adjacency_legal_straddle_rejected(api):
    """PRD §3.2: "Windows of the same (`network`, `reason_code`) pair are
    half-open and must not overlap — adjacency is allowed — and an overlapping
    creation is rejected with `ERR_RULE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/reason_rule_half_open_window_overlap
    """
    _setup_rule_window_pair(api)  # the adjacent R2 was accepted in setup
    straddle = api.create_reason_code_rule(
        create_reason_code_rule_payload(
            chargeback_fee_cents=9999,
            effective_from="2026-06-15T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        ),
        OPS,
    )
    validate_error(straddle, ApiErrorId.ERR_RULE_WINDOW_OVERLAP)


def test_reason_rule_boundary_instant_resolves_to_successor(api):
    """PRD §3.2: "Each rule's window runs from `effective_from` (inclusive) to
    `effective_to` (exclusive); a null `effective_to` is open-ended."
    PRD §3.5: receipt auto-creates "a `CHARGEBACK_FEE` fee assessment for the
    rule's `chargeback_fee_cents`".

    Design: Difficulty/resource_temporal_overlap/reason_rule_half_open_window_overlap
    """
    m = _setup_rule_window_pair(api)
    cb = ingest_chargeback(api, m["id"], "T-1", "NC-W1", 10000)
    # Received exactly at the shared boundary 2026-07-01T00:00:00Z: R1's window
    # excluded its end, so the successor rule prices the fee.
    assert_instant_equal(cb["received_at"], "2026-07-01T00:00:00Z", "received_at")
    fees = list_fees(api, chargeback_id=cb["id"])
    assert len(fees) == 1
    assert fees[0]["kind"] == "CHARGEBACK_FEE"
    assert fees[0]["amount_cents"] == 3500


def _setup_deflected_sale(api):
    """Merchant + one sale + REFUND_OPPORTUNITY alert actioned REFUND."""
    create_rule(api)
    m = create_merchant(api, legal_name="Deflect M", reserve_rate_bps=0)
    txn = ingest_sale(api, m["id"], "T-1", 10000, "2026-07-25T00:00:00Z")
    alert = get_success_data(
        api.create_prevention_alert(
            create_prevention_alert_payload(
                transaction_id=txn["id"], alert_type="REFUND_OPPORTUNITY"
            ),
            OPS,
        )
    )
    return m, txn, alert


def test_alert_refund_deflection_moves_money(api):
    """PRD §3.4: "the transaction moves `SETTLED` → `REFUNDED`, the merchant's
    `clearing_balance_cents` decreases by the transaction's full `amount_cents`
    to fund the refund, and the alert becomes `ACTIONED_REFUND`; because a
    refunded sale can no longer be charged back, the case never reaches
    receipt."

    Design: Difficulty/cross_entity_state_dependency/chargeback_ingest_blocked_by_refunded_transaction
    """
    m, txn, alert = _setup_deflected_sale(api)
    resp = api.action_prevention_alert(
        alert["id"], {"action": "REFUND"}, make_merchant_user_headers(m["id"])
    )
    actioned = validate_success(resp)
    assert actioned["status"] == "ACTIONED_REFUND"

    txn_after = get_success_data(api.get_transaction(txn["id"], OPS))
    assert txn_after["status"] == "REFUNDED"
    # Sale credit +10000 then refund -10000.
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 0


def test_chargeback_ingest_blocked_by_refunded_transaction(api):
    """PRD §3.5: "the transaction must be `SETTLED` — a sale refunded through
    alert deflection is no longer chargebackable and fails with
    `ERR_TRANSACTION_NOT_CHARGEBACKABLE`".

    Design: Difficulty/cross_entity_state_dependency/chargeback_ingest_blocked_by_refunded_transaction
    """
    m, _txn, alert = _setup_deflected_sale(api)
    validate_success(
        api.action_prevention_alert(
            alert["id"], {"action": "REFUND"}, make_merchant_user_headers(m["id"])
        )
    )

    resp = api.create_chargeback(
        create_chargeback_payload(
            merchant_id=m["id"],
            transaction_external_ref="T-1",
            network_case_id="NC-X1",
            amount_cents=10000,
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_CHARGEBACKABLE)
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 0


def test_immediate_consistency_after_chargeback_ingest(api):
    """PRD §3.5: "Receipt then moves money: the merchant's
    `clearing_balance_cents` decreases by the disputed `amount_cents` (the
    receipt debit), the transaction flips `SETTLED` → `CHARGED_BACK`, and a
    `CHARGEBACK_FEE` fee assessment for the rule's `chargeback_fee_cents` is
    auto-created with `assessed_by_user_id` set to the literal `system`
    (§3.8)."
    PRD §3.5: "For a `HIGH_RISK` merchant there is a further cascade: a reserve
    `HOLD` entry for the full disputed amount is posted with `source_kind`
    `CHARGEBACK_RECEIPT`, the case's id as `source_id`, and a null
    `release_eligible_at`".

    Design: Corner/consistency/immediate_consistency_after_ingest
    """
    create_rule(api)
    m = create_merchant(api, legal_name="IC M", risk_tier="HIGH_RISK", reserve_rate_bps=0)
    txn = ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    cb = ingest_chargeback(api, m["id"], "T-1", "NC-IC1", 10000)
    assert cb["case_status"] == "RECEIVED"

    # Every cascade effect is readable in the very next requests.
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 0

    fees = list_fees(api, chargeback_id=cb["id"])
    assert len(fees) == 1
    assert fees[0]["kind"] == "CHARGEBACK_FEE"
    assert fees[0]["amount_cents"] == 2500
    assert fees[0]["status"] == "ASSESSED"
    assert fees[0]["assessed_by_user_id"] == "system"

    ra = reserve_account_for(api, m["id"])
    assert ra["held_cents"] == 10000
    entries = [e for e in ledger_entries(api, ra["id"]) if e["source_kind"] == "CHARGEBACK_RECEIPT"]
    assert len(entries) == 1
    assert entries[0]["source_id"] == cb["id"]
    assert entries[0]["release_eligible_at"] is None

    txn_after = get_success_data(api.get_transaction(txn["id"], OPS))
    assert txn_after["status"] == "CHARGED_BACK"


def test_alert_action_after_expiry_sweep_rejected(api):
    """PRD §3.4: "Because the response window is enforced by the expiry sweep
    rather than at action time, an alert whose `response_due_at` has passed is
    flipped to `EXPIRED` at the next clock set, and a late action then fails
    the state check with `ERR_ALERT_NOT_OPEN`."

    Design: Corner/state_machines/alert_action_after_expiry_sweep_rejected
    """
    create_rule(api)
    m = create_merchant(api, legal_name="AlertExp M", reserve_rate_bps=0)
    txn = ingest_sale(api, m["id"], "T-1", 10000, "2026-07-25T00:00:00Z")
    alert = get_success_data(
        api.create_prevention_alert(
            create_prevention_alert_payload(
                transaction_id=txn["id"], alert_type="DISPUTE_ALERT"
            ),
            OPS,
        )
    )
    # Ingested at the default clock 2026-08-01T00:00:00Z; due 2026-08-04T00:00:00Z.
    set_clock(api, "2026-08-04T00:00:01Z")

    alert_after = get_success_data(api.get_prevention_alert(alert["id"], OPS))
    assert alert_after["status"] == "EXPIRED"

    resp = api.action_prevention_alert(
        alert["id"], {"action": "REFUND"}, make_merchant_user_headers(m["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ALERT_NOT_OPEN)


def _setup_late_alert_on_charged_back_sale(api):
    """Sale T-1 charged back; a late DISPUTE_ALERT arrives for the same sale."""
    create_rule(api)
    m = create_merchant(api, legal_name="Late Alert M", reserve_rate_bps=0)
    txn = ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    cb = ingest_chargeback(api, m["id"], "T-1", "NC-L1", 10000)
    assert cb["case_status"] == "RECEIVED"
    alert = get_success_data(
        api.create_prevention_alert(
            create_prevention_alert_payload(
                transaction_id=txn["id"], alert_type="DISPUTE_ALERT"
            ),
            OPS,
        )
    )
    return m, txn, alert


def test_alert_refund_blocked_by_charged_back_transaction(api):
    """PRD §3.4: "An `action` of `REFUND` additionally requires the referenced
    transaction to still be `SETTLED` — otherwise the request fails with
    `ERR_TRANSACTION_NOT_REFUNDABLE`".

    Design: Difficulty/cross_entity_state_dependency/alert_refund_blocked_by_charged_back_transaction
    """
    m, txn, alert = _setup_late_alert_on_charged_back_sale(api)
    txn_now = get_success_data(api.get_transaction(txn["id"], OPS))
    assert txn_now["status"] == "CHARGED_BACK"

    resp = api.action_prevention_alert(
        alert["id"], {"action": "REFUND"}, make_merchant_user_headers(m["id"])
    )
    validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_REFUNDABLE)


def test_alert_refund_failure_leaves_alert_open(api):
    """PRD §3.4: "An `action` of `REFUND` additionally requires the referenced
    transaction to still be `SETTLED` — otherwise the request fails with
    `ERR_TRANSACTION_NOT_REFUNDABLE`" — a failed action performs no transition,
    so the alert remains `OPEN` and actionable.

    Design: Difficulty/cross_entity_state_dependency/alert_refund_blocked_by_charged_back_transaction
    """
    m, _txn, alert = _setup_late_alert_on_charged_back_sale(api)
    validate_error(
        api.action_prevention_alert(
            alert["id"], {"action": "REFUND"}, make_merchant_user_headers(m["id"])
        ),
        ApiErrorId.ERR_TRANSACTION_NOT_REFUNDABLE,
    )

    alert_after = get_success_data(api.get_prevention_alert(alert["id"], OPS))
    assert alert_after["status"] == "OPEN"
