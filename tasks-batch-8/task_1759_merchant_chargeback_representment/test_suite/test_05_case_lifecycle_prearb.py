"""Chargeback lifecycle: notify/accept/reverse gates, expiry, and the
DECIDED_WON -> PRE_ARBITRATION -> DECIDED_WON | DECIDED_LOST cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_chargeback,
    assert_instant_equal,
    assemble_packet,
    create_merchant,
    create_rule,
    get_merchant,
    get_success_data,
    ingest_chargeback,
    ingest_sale,
    ledger_entries,
    make_merchant_user_headers,
    notify,
    post_outcome,
    reserve_account_for,
    set_clock,
    setup_case,
    setup_decided_case,
    setup_notified_case,
    setup_submitted_case,
    submit_packet,
    upload_evidence,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_notify_twice_rejected(api):
    """PRD §3.5: "Notify, accept, reverse, and the pre-arbitration actions each
    permit only the states shown in their transitions; invoking one from any
    other state fails with `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/notify_twice_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    cb = bundle["chargeback"]
    assert_instant_equal(
        cb["merchant_response_due_at"], "2026-07-22T00:00:00Z", "response due"
    )

    resp = api.notify_chargeback(cb["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)

    after = get_success_data(api.get_chargeback(cb["id"], OPS))
    # The rejected notify did not re-stamp the response window.
    assert_instant_equal(
        after["merchant_response_due_at"], "2026-07-22T00:00:00Z", "response due"
    )


def test_terminal_lockdown_merchant_accepted(api):
    """PRD §3.5: "Acceptance moves the case to the terminal `MERCHANT_ACCEPTED`
    state, sets `funds_status` to `DEBIT_FINAL` (the receipt debit stands)".
    PRD §3.5: "Notify, accept, reverse, and the pre-arbitration actions each
    permit only the states shown in their transitions; invoking one from any
    other state fails with `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/terminal_lockdown_merchant_accepted
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    cb = bundle["chargeback"]
    m_id = bundle["merchant"]["id"]
    accepted = validate_success(
        api.accept_chargeback(cb["id"], make_merchant_user_headers(m_id))
    )
    assert accepted["case_status"] == "MERCHANT_ACCEPTED"
    assert accepted["funds_status"] == "DEBIT_FINAL"

    again = api.accept_chargeback(cb["id"], make_merchant_user_headers(m_id))
    validate_error(again, ApiErrorId.ERR_INVALID_CASE_STATE)

    after = get_success_data(api.get_chargeback(cb["id"], OPS))
    assert after["case_status"] == "MERCHANT_ACCEPTED"
    assert after["funds_status"] == "DEBIT_FINAL"


def test_expiry_from_received_without_notify(api):
    """PRD §3.5: "when the clock is set past `representment_due_at`, a case
    still in `RECEIVED` or `MERCHANT_NOTIFIED` becomes `EXPIRED` (terminal),
    its `funds_status` becomes `DEBIT_FINAL`".
    PRD §3.9: the posted-basis numerator counts "chargebacks with `received_at`
    inside the month whose `case_status` is not `REVERSED` at sweep time".

    Design: Corner/state_machines/expiry_from_received_without_notify
    """
    bundle = setup_case(api, received_at="2026-07-15T00:00:00Z")
    cb = bundle["chargeback"]
    assert cb["case_status"] == "RECEIVED"
    assert_instant_equal(
        cb["representment_due_at"], "2026-08-14T00:00:00Z", "representment due"
    )

    set_clock(api, "2026-08-15T00:00:00Z")
    after = get_success_data(api.get_chargeback(cb["id"], OPS))
    assert after["case_status"] == "EXPIRED"
    assert after["funds_status"] == "DEBIT_FINAL"
    # Only REVERSED drops out of the POSTED ratio; expiry still counts.
    assert after["is_ratio_counted"] is True


def test_accept_with_packet_in_flight_rejected(api):
    """PRD §3.5: "no representment packet of this case is currently `ASSEMBLED`
    or `SUBMITTED` (else `ERR_REPRESENTMENT_ALREADY_OPEN`)".

    Design: Corner/state_machines/accept_with_packet_in_flight_rejected
    """
    bundle = setup_notified_case(api, received_at="2026-07-15T00:00:00Z")
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    ev = upload_evidence(api, cb_id, m_id, "RECEIPT", "s3://ev/r.pdf")
    rep = assemble_packet(api, cb_id, m_id, [ev["id"]])
    assert rep["status"] == "ASSEMBLED"

    resp = api.accept_chargeback(cb_id, make_merchant_user_headers(m_id))
    validate_error(resp, ApiErrorId.ERR_REPRESENTMENT_ALREADY_OPEN)


def test_accept_window_inclusive_boundary(api):
    """PRD §3.5: "the current time is on or before `merchant_response_due_at` —
    the accept window is inclusive, and a late accept fails with
    `ERR_ACCEPT_WINDOW_PASSED`."

    Design: Corner/state_machines/accept_window_inclusive_boundary
    """
    create_rule(api)
    m = create_merchant(api, legal_name="AcceptWin M", reserve_rate_bps=0)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_sale(api, m["id"], "T-2", 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    cb1 = ingest_chargeback(api, m["id"], "T-1", "NC-AW1", 10000)
    cb2 = ingest_chargeback(api, m["id"], "T-2", "NC-AW2", 10000)
    notify(api, cb1["id"])
    notify(api, cb2["id"])
    # Both response windows close at 2026-07-22T00:00:00Z inclusive.
    headers = make_merchant_user_headers(m["id"])

    set_clock(api, "2026-07-22T00:00:00Z")
    at_deadline = api.accept_chargeback(cb1["id"], headers)
    accepted = validate_success(at_deadline)
    assert accepted["case_status"] == "MERCHANT_ACCEPTED"

    set_clock(api, "2026-07-22T00:00:01Z")
    late = api.accept_chargeback(cb2["id"], headers)
    validate_error(late, ApiErrorId.ERR_ACCEPT_WINDOW_PASSED)


def test_reverse_from_decided_won_rejected(api):
    """PRD §3.7: "Reversal is the network or issuer undoing the case entirely,
    available to `AcquirerOps` while the case is `RECEIVED`,
    `MERCHANT_NOTIFIED`, or `REPRESENTED`."
    PRD §3.5: "Notify, accept, reverse, and the pre-arbitration actions each
    permit only the states shown in their transitions; invoking one from any
    other state fails with `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/reverse_from_decided_rejected
    """
    bundle = setup_decided_case(api, "WON", received_at="2026-07-15T00:00:00Z")
    assert bundle["chargeback"]["case_status"] == "DECIDED_WON"

    resp = api.reverse_chargeback(bundle["chargeback"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)


def test_prearbitration_from_represented_rejected(api):
    """PRD §3.7: "`AcquirerOps` can move a won case to `PRE_ARBITRATION`".
    PRD §3.5: "Notify, accept, reverse, and the pre-arbitration actions each
    permit only the states shown in their transitions; invoking one from any
    other state fails with `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/prearb_from_represented_rejected
    """
    bundle = setup_submitted_case(api, received_at="2026-07-15T00:00:00Z")
    assert bundle["chargeback"]["case_status"] == "REPRESENTED"

    resp = api.escalate_pre_arbitration(bundle["chargeback"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)


def test_prearb_cycle_moves_both_axes_and_money(api):
    """PRD §3.7: "A decided win cascades to the chargeback, which moves
    `REPRESENTED` → `DECIDED_WON`: `funds_status` becomes `FUNDS_RETURNED`,
    `recredited_cents` records the returned amount — the full `amount_cents` on
    a `WON`, the recorded `won_amount_cents` on a `PARTIAL_WON` — and the
    merchant's `clearing_balance_cents` increases by `recredited_cents` as the
    re-credit lands."
    PRD §3.7: "`AcquirerOps` can move a won case to `PRE_ARBITRATION`, which
    re-debits the merchant — `funds_status` returns to `MERCHANT_DEBITED`,
    `clearing_balance_cents` decreases by `recredited_cents` to reverse the win
    re-credit".

    Design: Difficulty/non_linear_state_machine/chargeback_parallel_axes_prearb_cycle
    """
    bundle = setup_submitted_case(
        api,
        required_types=("RECEIPT", "DELIVERY_PROOF"),
        merchant_overrides={"reserve_rate_bps": 0},
        received_at="2026-07-15T00:00:00Z",
    )
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    rep_id = bundle["representment"]["id"]

    rep_won = post_outcome(api, rep_id, "WON")
    assert rep_won["status"] == "WON"
    assert rep_won["won_amount_cents"] == 10000
    cb_won = get_success_data(api.get_chargeback(cb_id, OPS))
    assert cb_won["case_status"] == "DECIDED_WON"
    assert cb_won["funds_status"] == "FUNDS_RETURNED"
    assert cb_won["recredited_cents"] == 10000
    # Sale +10000, receipt debit -10000, win re-credit +10000.
    assert get_merchant(api, m_id)["clearing_balance_cents"] == 10000

    get_success_data(api.escalate_pre_arbitration(cb_id, OPS))
    cb_pa = get_success_data(api.get_chargeback(cb_id, OPS))
    assert cb_pa["case_status"] == "PRE_ARBITRATION"
    assert cb_pa["funds_status"] == "MERCHANT_DEBITED"
    # The win re-credit is re-debited.
    assert get_merchant(api, m_id)["clearing_balance_cents"] == 0


def test_prearb_outcome_won_closes_cycle_on_both_axes(api):
    """PRD §3.7: "a `decision` of `WON` returns the case `PRE_ARBITRATION` →
    `DECIDED_WON` with `funds_status` `FUNDS_RETURNED`, re-crediting
    `recredited_cents` to clearing".

    Design: Difficulty/non_linear_state_machine/chargeback_parallel_axes_prearb_cycle
    """
    bundle = setup_decided_case(
        api, "WON", required_types=("RECEIPT", "DELIVERY_PROOF"),
        merchant_overrides={"reserve_rate_bps": 0}, received_at="2026-07-15T00:00:00Z",
    )
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    get_success_data(api.escalate_pre_arbitration(cb_id, OPS))

    get_success_data(api.pre_arbitration_outcome(cb_id, {"decision": "WON"}, OPS))
    cb_final = get_success_data(api.get_chargeback(cb_id, OPS))
    assert cb_final["case_status"] == "DECIDED_WON"
    assert cb_final["funds_status"] == "FUNDS_RETURNED"
    # The cycle closed on both axes with the money back where the win put it.
    assert get_merchant(api, m_id)["clearing_balance_cents"] == 10000


def _setup_invariant_pair(api):
    """Merchant A: fought WON then pre-arb LOST. Merchant B (control): accepted."""
    create_rule(api)
    ma = create_merchant(api, legal_name="Inv A", reserve_rate_bps=0)
    mb = create_merchant(api, legal_name="Inv B", reserve_rate_bps=0)
    ingest_sale(api, ma["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    ingest_sale(api, mb["id"], "T-1", 10000, "2026-07-10T00:00:00Z")
    set_clock(api, "2026-07-15T00:00:00Z")
    cba = ingest_chargeback(api, ma["id"], "T-1", "NC-IA", 10000)
    cbb = ingest_chargeback(api, mb["id"], "T-1", "NC-IB", 10000)
    notify(api, cba["id"])
    notify(api, cbb["id"])

    eva = upload_evidence(api, cba["id"], ma["id"], "RECEIPT", "s3://ev/a.pdf")
    rep = assemble_packet(api, cba["id"], ma["id"], [eva["id"]])
    submit_packet(api, rep["id"], ma["id"])
    post_outcome(api, rep["id"], "WON")
    get_success_data(api.escalate_pre_arbitration(cba["id"], OPS))
    get_success_data(api.pre_arbitration_outcome(cba["id"], {"decision": "LOST"}, OPS))

    validate_success(api.accept_chargeback(cbb["id"], make_merchant_user_headers(mb["id"])))
    return ma, mb, cba, cbb


def test_win_then_prearb_loss_nets_clearing_to_accept_outcome(api):
    """PRD §3.7: "a `decision` of `LOST` moves the case to the terminal
    `DECIDED_LOST` with `funds_status` `DEBIT_FINAL`, `recredited_cents`
    staying as recorded while the pre-arbitration re-debit stands".
    PRD §3.5: "Acceptance moves the case to the terminal `MERCHANT_ACCEPTED`
    state, sets `funds_status` to `DEBIT_FINAL` (the receipt debit stands)".

    Design: Difficulty/compensating_invariant/clearing_money_win_prearb_loss_invariant
    """
    ma, mb, cba, cbb = _setup_invariant_pair(api)
    # Win (+10000) paired with its compensating pre-arb re-debit (-10000) nets
    # to the same clearing as the plain accept: sale +10000, dispute -10000.
    assert get_merchant(api, ma["id"])["clearing_balance_cents"] == 0
    assert get_merchant(api, mb["id"])["clearing_balance_cents"] == 0


def test_win_then_prearb_loss_terminal_states_match_accept(api):
    """PRD §3.7: "a `decision` of `LOST` moves the case to the terminal
    `DECIDED_LOST` with `funds_status` `DEBIT_FINAL`".
    PRD §3.5: "Acceptance moves the case to the terminal `MERCHANT_ACCEPTED`
    state, sets `funds_status` to `DEBIT_FINAL` (the receipt debit stands),
    keeps `is_ratio_counted` true".

    Design: Difficulty/compensating_invariant/clearing_money_win_prearb_loss_invariant
    """
    ma, mb, cba, cbb = _setup_invariant_pair(api)
    cb_a = get_success_data(api.get_chargeback(cba["id"], OPS))
    cb_b = get_success_data(api.get_chargeback(cbb["id"], OPS))
    assert cb_a["case_status"] == "DECIDED_LOST"
    assert cb_a["funds_status"] == "DEBIT_FINAL"
    assert cb_b["case_status"] == "MERCHANT_ACCEPTED"
    assert cb_b["funds_status"] == "DEBIT_FINAL"
    # Zero residual drift between the two merchants despite A traversing
    # WON -> PRE_ARBITRATION -> DECIDED_LOST.
    assert (
        get_merchant(api, ma["id"])["clearing_balance_cents"]
        == get_merchant(api, mb["id"])["clearing_balance_cents"]
    )


def _setup_high_risk_submitted(api):
    """HIGH_RISK merchant, rate 0, EXPOSURE_BASED; one full-amount chargeback
    (receipt holdback posted) fought to a SUBMITTED packet."""
    bundle = setup_submitted_case(
        api,
        required_types=("RECEIPT", "DELIVERY_PROOF"),
        merchant_overrides={
            "risk_tier": "HIGH_RISK",
            "reserve_mode": "EXPOSURE_BASED",
            "reserve_rate_bps": 0,
        },
        received_at="2026-07-15T00:00:00Z",
    )
    ra = reserve_account_for(api, bundle["merchant"]["id"])
    return bundle, ra


def test_network_outcome_win_cascades_case_funds_and_clearing(api):
    """PRD §3.7: "A decided win cascades to the chargeback, which moves
    `REPRESENTED` → `DECIDED_WON`: `funds_status` becomes `FUNDS_RETURNED`,
    `recredited_cents` records the returned amount — the full `amount_cents` on
    a `WON`, the recorded `won_amount_cents` on a `PARTIAL_WON` — and the
    merchant's `clearing_balance_cents` increases by `recredited_cents` as the
    re-credit lands."

    Design: Difficulty/transitive_cascade/network_outcome_win_cascade
    """
    bundle, ra = _setup_high_risk_submitted(api)
    # Pre-outcome: receipt holdback held 10000; EXPOSURE_BASED target is
    # max(0 rate floor, 2 x 10000 open exposure).
    assert ra["held_cents"] == 10000
    assert ra["target_cents"] == 20000

    post_outcome(api, bundle["representment"]["id"], "WON")
    cb = get_success_data(api.get_chargeback(bundle["chargeback"]["id"], OPS))
    assert cb["case_status"] == "DECIDED_WON"
    assert cb["funds_status"] == "FUNDS_RETURNED"
    assert cb["recredited_cents"] == 10000
    # Sale +10000, receipt debit -10000, win re-credit +10000.
    assert get_merchant(api, bundle["merchant"]["id"])["clearing_balance_cents"] == 10000


def test_network_outcome_win_cascades_reserve_release_and_target(api):
    """PRD §3.7: "For a `HIGH_RISK` merchant the receipt holdback is unwound: a
    `RELEASE` entry for the disputed amount posts with `source_kind`
    `CHARGEBACK_WON` and the case as `source_id`, `held_cents` is refolded, and
    `target_cents` is recomputed because the case leaves the open-exposure
    set".

    Design: Difficulty/transitive_cascade/network_outcome_win_cascade
    """
    bundle, ra = _setup_high_risk_submitted(api)
    post_outcome(api, bundle["representment"]["id"], "WON")

    entries = ledger_entries(api, ra["id"])
    assert [(e["entry_type"], e["source_kind"], e["amount_cents"]) for e in entries] == [
        ("HOLD", "CHARGEBACK_RECEIPT", 10000),
        ("RELEASE", "CHARGEBACK_WON", 10000),
    ]
    after = get_success_data(api.get_reserve_account(ra["id"], RISK))
    assert after["held_cents"] == 0
    # The case left the open-exposure set: max(0, 2 x 0) = 0.
    assert after["target_cents"] == 0
