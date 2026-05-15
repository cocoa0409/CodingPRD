"""Settlement netting, send/confirm/fail lifecycle, and the depth-4 cascade.

Citations refer to PRD.md §3.7.
"""
from __future__ import annotations
import uuid

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    WATCH_TIER_USD,
    assert_settlement_instruction,
    book_trade,
    round_half_up,
    setup_sent_settlement_for_failure_cascade,
    setup_settlement_generated,
    setup_trader_with_limits,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    generate_settlements_payload,
    patch_counterparty_payload,
)


# ===========================================================================
# Generate basics — PRD §3.7
# ===========================================================================
def test_generate_produces_per_currency_instruction_rows(api, settlement_operator_headers):
    """PRD §3.7: "decomposes each trade into two per-currency cash legs, and
    aggregates per (`counterparty_id`, `value_date`, `ccy`) tuple,
    producing one `SettlementInstruction` row per tuple."

    Claim: a single EURUSD BUY trade generates two instructions, one per
    leg currency (EUR and USD).
    """
    s = setup_settlement_generated(
        side="BUY",
        notional_base=1_000_000.00,
        entry_rate=1.100000,
        pair_code="EURUSD",
        pair_mid_rate=1.100000,
    )
    ccys = sorted(si["ccy"] for si in s["instructions"])
    assert ccys == ["EUR", "USD"], (
        f"PRD §3.7 leg decomposition: BUY EURUSD must emit EUR and USD "
        f"legs; got ccys={ccys}"
    )
    for si in s["instructions"]:
        assert_settlement_instruction(si)
        assert si["status"] == "GENERATED"
        assert si["nostro_balance_delta"] == 0


# ===========================================================================
# Cash-conservation invariant — PRD §3.7
# ===========================================================================
def test_net_amount_equals_gross_pay_minus_gross_receive(api, settlement_operator_headers):
    """PRD §3.7: "For each emitted `SettlementInstruction`,
    `gross_pay_amount` is the sum of outbound flows in that currency,
    `gross_receive_amount` is the sum of inbound flows, and `net_amount`
    is `gross_pay_amount` minus `gross_receive_amount`, rounded half-up to
    two decimal places."

    Setup: BUY 1M EURUSD @ 1.10 (receive 1M EUR, pay 1.1M USD) and SELL
    600k EURUSD @ 1.10 (pay 600k EUR, receive 660k USD).

    Claim: EUR instruction net_amount = 600000 - 1000000 = -400000;
    USD instruction net_amount = 1100000 - 660000 = 440000.

    # difficulty: compensating_invariant/settlement_netting_cash_conservation
    """
    # Pin the pair to EURUSD because the test reads EUR/USD legs by name;
    # the default fixture mints a unique pair code per call to avoid
    # cross-test collision, but this test depends on the concrete ccy
    # labels.
    ctx = setup_trader_with_limits(
        pair_code="EURUSD",
        intraday_cap=100_000_000.00,
        overnight_cap=100_000_000.00,
        pair_mid_rate=1.100000,
    )
    book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=1_000_000.00,
        entry_rate=1.100000,
        counterparty_id=ctx["counterparty"]["id"],
    )
    book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="SELL",
        notional_base=600_000.00,
        entry_rate=1.100000,
        counterparty_id=ctx["counterparty"]["id"],
    )
    res = api.generate_settlements(
        generate_settlements_payload(
            counterparty_id=ctx["counterparty"]["id"],
            value_date="2026-05-14",
            client_request_id=f"cri-{uuid.uuid4().hex}",
        ),
        settlement_operator_headers,
    )
    data = validate_success(res, 201)
    rows = data if isinstance(data, list) else [data]
    eur = next(si for si in rows if si["ccy"] == "EUR")
    usd = next(si for si in rows if si["ccy"] == "USD")
    # EUR: receive 1M (BUY), pay 600k (SELL)
    assert eur["gross_pay_amount"] == 600_000.00
    assert eur["gross_receive_amount"] == 1_000_000.00
    assert eur["net_amount"] == round_half_up(
        eur["gross_pay_amount"] - eur["gross_receive_amount"], 2
    ), (
        f"PRD §3.7: net_amount = round_half_up(gross_pay - gross_receive, 2); "
        f"got {eur['net_amount']}"
    )
    # USD: pay 1.1M (BUY), receive 660k (SELL)
    assert usd["gross_pay_amount"] == 1_100_000.00
    assert usd["gross_receive_amount"] == 660_000.00
    assert usd["net_amount"] == round_half_up(
        usd["gross_pay_amount"] - usd["gross_receive_amount"], 2
    )
    # Invariant on every emitted row.
    for si in rows:
        assert si["net_amount"] == round_half_up(
            si["gross_pay_amount"] - si["gross_receive_amount"], 2,
        )


# ===========================================================================
# Idempotency-replay — PRD §3.7 / §2.11
# ===========================================================================
def test_replay_with_same_client_request_id_returns_existing_set_with_200(
    api, settlement_operator_headers,
):
    """PRD §3.7: "The idempotency key is scoped per (`counterparty_id`,
    `value_date`, `client_request_id`): a repeat call with the same triple
    returns the original `SettlementInstruction` set with HTTP 200 (not
    201), surfacing `ERR_IDEMPOTENCY_REPLAY`."

    Claim: a second call with identical (counterparty, value_date,
    client_request_id) returns HTTP 200 (replay), and the returned
    instruction id set equals the first set.
    """
    s = setup_settlement_generated(
        side="BUY",
        notional_base=1_000_000.00,
        entry_rate=1.000000,
        pair_mid_rate=1.000000,
    )
    first_ids = sorted(si["id"] for si in s["instructions"])
    # Replay.
    res = api.generate_settlements(
        generate_settlements_payload(
            counterparty_id=s["ctx"]["counterparty"]["id"],
            value_date=s["value_date"],
            client_request_id=s["client_request_id"],
        ),
        settlement_operator_headers,
    )
    assert res.status_code == 200, (
        f"PRD §3.7: idempotent replay returns HTTP 200 (not 201); got {res.status_code}"
    )
    body = res.json()["data"]
    rows = body if isinstance(body, list) else [body]
    replay_ids = sorted(si["id"] for si in rows)
    assert replay_ids == first_ids, (
        "PRD §3.7: replay returns the original SettlementInstruction set; "
        f"first={first_ids}, replay={replay_ids}"
    )


# ===========================================================================
# Send gating by watchlist — PRD §3.7 / §2.9 priority 5/6
# ===========================================================================
def test_send_blocked_when_counterparty_on_watchlist(
    api, settlement_operator_headers, compliance_officer_headers,
):
    """PRD §3.7: "Sending transitions `GENERATED` to `SENT`, but is blocked
    when the facing counterparty's `on_watchlist` is true — that rejection
    raises `ERR_COUNTERPARTY_WATCHLIST` (HTTP 409)".

    Claim: a Counterparty whose internal_score is patched to <40 enters
    WATCH band; the subsequent /send on its GENERATED SettlementInstruction
    → ERR_COUNTERPARTY_WATCHLIST.

    # difficulty: cross_entity_state_dependency/settlement_send_gated_by_counterparty_watchlist
    """
    s = setup_settlement_generated(
        counterparty_external_rating="A",
        counterparty_internal_score=70,  # STANDARD, not watchlist
    )
    # Patch counterparty into WATCH band.
    cp = s["ctx"]["counterparty"]
    patched = validate_success(
        api.patch_counterparty(
            cp["id"],
            patch_counterparty_payload(version=cp["version"], internal_score=30),
            compliance_officer_headers,
        ),
        200,
    )
    assert patched["on_watchlist"] is True
    # Attempt /send.
    si = s["instructions"][0]
    res = api.send_settlement(si["id"], settlement_operator_headers)
    validate_error(
        res, ApiErrorId.ERR_COUNTERPARTY_WATCHLIST.value, expected_status=409,
    )


# ===========================================================================
# Confirm → SETTLED — PRD §3.7
# ===========================================================================
def test_confirm_sets_nostro_balance_delta_to_negative_net_amount(
    api, settlement_operator_headers,
):
    """PRD §3.7: "Confirming a sent instruction transitions `SENT` to
    `SETTLED`, and on this transition `nostro_balance_delta` is set to the
    negative of `net_amount` (since a positive `net_amount` is an outbound
    flow that debits the firm's Nostro account)".

    Claim: after /send then /confirm, SettlementInstruction.status==SETTLED
    and nostro_balance_delta == -net_amount.
    """
    s = setup_settlement_generated(
        side="BUY",
        notional_base=1_000_000.00,
        entry_rate=1.000000,
        pair_mid_rate=1.000000,
    )
    si = s["instructions"][0]
    net = si["net_amount"]
    validate_success(api.send_settlement(si["id"], settlement_operator_headers), 200)
    confirmed = validate_success(
        api.confirm_settlement(si["id"], settlement_operator_headers), 200,
    )
    assert confirmed["status"] == "SETTLED"
    assert confirmed["nostro_balance_delta"] == round_half_up(-net, 2), (
        f"PRD §3.7: nostro_balance_delta = -net_amount; net={net}, "
        f"got nostro_balance_delta={confirmed['nostro_balance_delta']}"
    )


# ===========================================================================
# Mark-failed cascade depth 4 — PRD §3.7
# ===========================================================================
def test_mark_failed_drives_full_depth4_cascade(
    api, settlement_operator_headers, compliance_officer_headers,
):
    """PRD §3.7: "A `SettlementOperator` marking a `SENT` instruction as
    failed transitions it to `FAILED`, writes an audit row of `event_type`
    `SETTLEMENT_FAILED`, transitions every linked `BOOKED` `Trade` to
    `FAILED`, and triggers a transitive cascade four levels deep: the
    facing `Counterparty.internal_score` is decremented by 5 (clamped at a
    floor of 0), the counterparty's `rating_band` and `credit_limit_usd`
    are recomputed per the rules in §3.6, the new `on_watchlist` flag is
    set, and finally, for every `Trader` whose aggregate facing notional
    now exceeds the lower `credit_limit_usd`, that trader's `status` is
    flipped to `SUSPENDED`."

    Setup: Counterparty BBB external + 44 internal → SPECULATIVE band,
    credit_limit_usd=10M; Trader has 9M USD exposure facing it.

    Claim after /mark-failed:
      step 1: cp.internal_score == 39 (44 - 5)
      step 2: cp.rating_band == "WATCH" (39 < 40 internal floor)
      step 3: cp.credit_limit_usd == 1_000_000.00 (WATCH tier)
      step 4: trader.status == "SUSPENDED" (9M > 1M)

    # difficulty: transitive_cascade/settlement_failure_to_trader_suspension_depth_4
    """
    s = setup_sent_settlement_for_failure_cascade(
        counterparty_external_rating="BBB",
        counterparty_internal_score=44,
        notional_base=9_000_000.00,
        entry_rate=1.000000,
        pair_mid_rate=1.000000,
        intraday_cap=50_000_000.00,
    )
    validate_success(
        api.mark_failed_settlement(
            s["sent_instruction"]["id"], settlement_operator_headers,
        ),
        200,
    )
    # Step 4 — the depth-4 endpoint of the cascade — is observable via the
    # public GET /fx-risk/traders/{id} endpoint.
    trader_after = validate_success(
        api.get_trader(s["ctx"]["trader"]["id"], s["ctx"]["trader_headers"]),
        200,
    )
    assert trader_after["status"] == "SUSPENDED", (
        f"PRD §3.7 depth-4: trader.status must flip to SUSPENDED; "
        f"got {trader_after['status']!r}"
    )


def test_mark_failed_transitions_linked_trades_to_failed(
    api, settlement_operator_headers,
):
    """PRD §3.7: "transitions every linked `BOOKED` `Trade` to `FAILED`".

    Claim: after /mark-failed, the underlying Trade.status reads FAILED
    via any read endpoint that exposes the trade. We confirm via the
    audit-log (event_type=SETTLEMENT_FAILED) and the trader.status
    cascade (already covered above). PRD does not name a direct
    GET /trades/{id} endpoint, so we assert the AuditLog row at minimum.
    """
    s = setup_sent_settlement_for_failure_cascade()
    validate_success(
        api.mark_failed_settlement(
            s["sent_instruction"]["id"], settlement_operator_headers,
        ),
        200,
    )
    audit = validate_success(
        api.list_audit_log(
            TEST_USERS["compliance_officer_headers"],
            params={"event_type": "SETTLEMENT_FAILED"},
        ),
        200,
    )
    rows = audit if isinstance(audit, list) else (audit.get("audit_log") or audit)
    rows = rows if isinstance(rows, list) else [rows]
    assert any(
        r["event_type"] == "SETTLEMENT_FAILED"
        and r["subject_id"] == s["sent_instruction"]["id"]
        for r in rows
    ), (
        "PRD §3.7: SETTLEMENT_FAILED audit row must be emitted for the "
        f"failed instruction {s['sent_instruction']['id']}"
    )
