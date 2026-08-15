"""Broker trades: GROSS vs NET settlement variants, per-line fee rounding
order and fee-tier boundaries, the certificate lock/unlock cycle, full- and
partial-quantity settlement with serial-range partition conservation,
settlement/expiry window boundaries, transfer ledger sync, and proposal-time
quantity and ownership guards."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_trade,
    assert_certificate,
    assert_trade,
    create_accepted_reading,
    create_active_generator,
    create_broker_account,
    create_meter_reading_payload,
    expire_trade,
    get_account,
    get_certificate,
    get_generator,
    get_generator_account,
    get_trade,
    list_certificates,
    make_broker_trader_headers,
    make_generator_operator_headers,
    propose_and_accept_trade,
    propose_trade,
    run_mint,
    set_clock,
    settle_accepted_trade,
    settle_trade,
    setup_brokers_with_certificates,
    setup_minted_generator,
    transfer_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["registry_admin_headers"]

JULY = ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")


def _setup_120_and_80():
    """Two certificates — 120 MWh (vintage 2026-07) and 80 MWh (vintage
    2026-08) — minted and transferred to broker b1, with b2 empty."""
    setup = setup_brokers_with_certificates(
        readings=[
            {"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 120000},
            {"period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-08-15T00:00:00Z", "metered_kwh": 80000,
             "clock": "2026-09-01T00:00:00Z"},
        ]
    )
    c120 = [c for c in setup["certificates"] if c["quantity_mwh"] == 120][0]
    c80 = [c for c in setup["certificates"] if c["quantity_mwh"] == 80][0]
    return setup, c120, c80


# ---------------------------------------------------------------------------
# GROSS vs NET settlement variants
# ---------------------------------------------------------------------------

def test_trade_settlement_gross_buyer_pays_fee_on_top(api):
    """PRD §3.4: "Under `settlement_mode` `GROSS`, the `buyer_total_cents` is
    the line total plus the broker fee and the `seller_proceeds_cents` is the
    full line total; under `NET`, the buyer pays the line total only and the
    `seller_proceeds_cents` is the line total minus the broker fee."
    PRD §3.4: "The trade's `total_line_cents` is the sum of the line totals
    and its `broker_fee_cents` is the sum of the rounded per-line fees".

    Design: Difficulty/dual_variant_calc/trade_settlement_gross_vs_net
    """
    setup, c120, c80 = _setup_120_and_80()
    b1, b2 = setup["b1"], setup["b2"]

    trade = settle_accepted_trade(
        b1["id"], b2["id"],
        [{"certificate_id": c120["id"], "quantity_mwh": 120},
         {"certificate_id": c80["id"], "quantity_mwh": 80}],
        unit_price_cents_per_mwh=450, settlement_mode="GROSS",
    )
    assert_trade(trade)
    assert trade["status"] == "SETTLED"
    assert trade["total_line_cents"] == 90000  # 120*450 + 80*450
    # per line: round(54000*35/10000)=189 (120 MWh -> 35 bps) +
    #           round(36000*50/10000)=180 (80 MWh -> 50 bps)
    assert trade["broker_fee_cents"] == 369
    assert trade["buyer_total_cents"] == 90369, "GROSS: buyer pays lines + fee on top"
    assert trade["seller_proceeds_cents"] == 90000, "GROSS: seller receives the full lines"


def test_trade_settlement_net_fee_deducted_from_seller(api):
    """PRD §3.4: "Under `settlement_mode` `GROSS`, the `buyer_total_cents` is
    the line total plus the broker fee and the `seller_proceeds_cents` is the
    full line total; under `NET`, the buyer pays the line total only and the
    `seller_proceeds_cents` is the line total minus the broker fee."

    Design: Difficulty/dual_variant_calc/trade_settlement_gross_vs_net
    """
    setup, c120, c80 = _setup_120_and_80()
    b1, b2 = setup["b1"], setup["b2"]

    gross = settle_accepted_trade(
        b1["id"], b2["id"],
        [{"certificate_id": c120["id"], "quantity_mwh": 120},
         {"certificate_id": c80["id"], "quantity_mwh": 80}],
        unit_price_cents_per_mwh=450, settlement_mode="GROSS",
    )
    # After the full-quantity GROSS settle both certificates are held by b2,
    # so the identical NET trade runs in the reverse direction.
    net = settle_accepted_trade(
        b2["id"], b1["id"],
        [{"certificate_id": c120["id"], "quantity_mwh": 120},
         {"certificate_id": c80["id"], "quantity_mwh": 80}],
        unit_price_cents_per_mwh=450, settlement_mode="NET",
    )
    assert net["status"] == "SETTLED"
    assert net["total_line_cents"] == 90000
    assert net["broker_fee_cents"] == 369
    assert net["buyer_total_cents"] == 90000, "NET: buyer pays the line total only"
    assert net["seller_proceeds_cents"] == 89631, "NET: fee is deducted from seller proceeds"

    assert gross["buyer_total_cents"] != net["buyer_total_cents"]
    assert gross["seller_proceeds_cents"] != net["seller_proceeds_cents"], (
        "identical items and price settle to different money under the two modes"
    )


# ---------------------------------------------------------------------------
# Per-line fee rounding order (pinned) and fee-tier boundaries
# ---------------------------------------------------------------------------

def test_broker_fee_rounded_per_line_before_summation(api):
    """PRD §3.4: "The broker fee is computed per line and rounded per line
    before any summation ... each line's fee is its line total multiplied by
    the applicable basis-point rate, divided by ten thousand, and rounded
    half-up to a whole cent. The trade's `total_line_cents` is the sum of the
    line totals and its `broker_fee_cents` is the sum of the rounded per-line
    fees — computing the fee on the aggregate total instead is a different,
    non-conformant algorithm and yields different cents."

    Design: Difficulty/combinatorial_formula/trade_fee_per_line_rounding_pinned
    """
    setup, c120, c80 = _setup_120_and_80()
    trade = settle_accepted_trade(
        setup["b1"]["id"], setup["b2"]["id"],
        [{"certificate_id": c120["id"], "quantity_mwh": 120},
         {"certificate_id": c80["id"], "quantity_mwh": 80}],
        unit_price_cents_per_mwh=450, settlement_mode="GROSS",
    )
    assert trade["broker_fee_cents"] == 369, (
        "per-line: round_half_up(54000*35/10000)=189 + round_half_up(36000*50/10000)=180"
    )
    assert trade["broker_fee_cents"] != 315, (
        "the aggregate-fee alternative (90000 * 35 bps = 315) is non-conformant"
    )
    assert trade["total_line_cents"] == 90000


def test_broker_fee_tier_selected_by_line_quantity_not_trade_total(api):
    """PRD §3.4: "lines smaller than 100 MWh are charged 50 basis points,
    lines of at least 100 MWh but less than 1000 MWh are charged 35 basis
    points, and lines of 1000 MWh or more are charged 20 basis points" — the
    tier is chosen per line, so a 120-MWh line inside a 200-MWh trade still
    pays 35 bps, not the rate its aggregate would suggest.

    Design: Difficulty/combinatorial_formula/trade_fee_per_line_rounding_pinned
    """
    setup, c120, c80 = _setup_120_and_80()
    trade = settle_accepted_trade(
        setup["b1"]["id"], setup["b2"]["id"],
        [{"certificate_id": c120["id"], "quantity_mwh": 120},
         {"certificate_id": c80["id"], "quantity_mwh": 80}],
        unit_price_cents_per_mwh=450, settlement_mode="GROSS",
    )
    # 120-MWh line -> 35 bps: round_half_up(54000 * 35 / 10000) = 189
    #  80-MWh line -> 50 bps: round_half_up(36000 * 50 / 10000) = 180
    assert trade["broker_fee_cents"] == 189 + 180
    # A trade-level tier read would charge the whole 200 MWh at one rate:
    # 90000 * 35/10000 = 315 or 90000 * 50/10000 = 450 — neither matches.
    assert trade["broker_fee_cents"] not in (315, 450)
    assert trade["buyer_total_cents"] == 90000 + 369


def test_broker_fee_tier_boundary_and_half_up_rounding(api):
    """PRD §3.4: "lines smaller than 100 MWh are charged 50 basis points,
    lines of at least 100 MWh but less than 1000 MWh are charged 35 basis
    points" and "rounded half-up to a whole cent" — 100 MWh lands in the
    35-bps tier (45000*35/10000 = 157.5 -> 158), 99 MWh stays at 50 bps
    (44550*50/10000 = 222.75 -> 223).

    Design: Corner/calculations/broker_fee_tier_boundary_and_half_up_rounding
    """
    s100 = setup_brokers_with_certificates(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 100000}],
        legal_name="Exact Solar", facility_code="EX1",
    )
    c100 = s100["certificates"][0]
    assert c100["quantity_mwh"] == 100

    gen99 = create_active_generator(legal_name="Under Wind", facility_code="UN1",
                                    technology="WIND", region_code="ERCOT")
    create_accepted_reading(gen99["id"], JULY[0], JULY[1], 99000)
    run_mint(gen99["id"])
    c99 = list_certificates(generator_id=gen99["id"])[0]
    assert c99["quantity_mwh"] == 99

    b1, b2 = s100["b1"], s100["b2"]
    transfer_certificate(c99["id"], b1["id"])

    t1 = settle_accepted_trade(
        b1["id"], b2["id"], [{"certificate_id": c100["id"], "quantity_mwh": 100}],
        unit_price_cents_per_mwh=450, settlement_mode="GROSS",
    )
    t2 = settle_accepted_trade(
        b1["id"], b2["id"], [{"certificate_id": c99["id"], "quantity_mwh": 99}],
        unit_price_cents_per_mwh=450, settlement_mode="GROSS",
    )
    assert t1["broker_fee_cents"] == 158, "100 MWh is 'at least 100' -> 35 bps; 157.5 rounds half-up"
    assert t2["broker_fee_cents"] == 223, "99 MWh is 'smaller than 100' -> 50 bps; 222.75 rounds half-up"
    assert t1["buyer_total_cents"] == 45158
    assert t2["buyer_total_cents"] == 44773


# ---------------------------------------------------------------------------
# Certificate lock/unlock cycle through trade accept and expiry
# ---------------------------------------------------------------------------

def test_accept_locks_certificate_and_moves_holdings(api):
    """PRD §3.4: "Acceptance locks every item certificate atomically: all of
    them move from `ACTIVE` to `LOCKED` or none do, and the holder account's
    `locked_holdings_mwh` rises while its `active_holdings_mwh` falls by the
    locked quantities. Acceptance stamps `accepted_at` and fixes the
    `settlement_deadline` exactly five days later."

    Design: Difficulty/non_linear_state_machine/certificate_lock_unlock_cycle
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]

    trade = propose_and_accept_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
        unit_price_cents_per_mwh=300, settlement_mode="GROSS",
    )
    assert trade["status"] == "ACCEPTED"
    assert trade["accepted_at"] is not None
    assert trade["settlement_deadline"] is not None

    locked = get_certificate(cert["id"])
    assert locked["status"] == "LOCKED"
    seller = get_account(b1["id"])
    assert seller["locked_holdings_mwh"] == 1
    assert seller["active_holdings_mwh"] == 0


def test_expire_unlocks_certificate_and_strikes_buyer(api):
    """PRD §3.4: "A `RegistryAdmin` may expire an `ACCEPTED` trade once the
    logical clock has passed its `settlement_deadline` ... moving it to
    `EXPIRED`, unlocking every item certificate from `LOCKED` back to
    `ACTIVE` with ownership unchanged, and adding one to the buyer account's
    `failure_strikes`".

    Design: Difficulty/non_linear_state_machine/certificate_lock_unlock_cycle
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]
    trade = propose_and_accept_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )
    # Accepted at the 2026-08-01 startup clock; deadline 2026-08-06.
    set_clock("2026-08-07T00:00:00Z")
    expired = expire_trade(trade["id"])
    assert expired["status"] == "EXPIRED"

    after = get_certificate(cert["id"])
    assert after["status"] == "ACTIVE", "expiry unlocks LOCKED -> ACTIVE"
    assert after["account_id"] == b1["id"], "ownership is unchanged by expiry"
    assert after["serial_start"] == 1 and after["serial_end"] == 1
    assert after["quantity_mwh"] == 1, "the lock cycle conserves the batch"

    buyer = get_account(b2["id"])
    assert buyer["failure_strikes"] == 1, "the buyer is struck for missing the deadline"


# ---------------------------------------------------------------------------
# Full- vs partial-quantity settlement and serial partition conservation
# ---------------------------------------------------------------------------

def test_full_quantity_settle_moves_certificate_row_to_buyer(api):
    """PRD §3.4: "When the item's quantity equals the certificate's whole
    quantity, the locked certificate row itself changes hands: its
    `account_id` becomes the buyer and its status returns from `LOCKED` to
    `ACTIVE`."

    Design: Difficulty/boundary_precision_check/full_quantity_settle_no_remainder
    """
    setup = setup_brokers_with_certificates(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 5000}]
    )
    cert = setup["certificates"][0]
    assert cert["quantity_mwh"] == 5
    assert cert["serial_start"] == 1 and cert["serial_end"] == 5
    b1, b2 = setup["b1"], setup["b2"]

    trade = settle_accepted_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 5}],
        settlement_mode="NET",
    )
    assert trade["status"] == "SETTLED"

    moved = get_certificate(cert["id"])
    assert moved["account_id"] == b2["id"], "the same row changes hands on a full-quantity settle"
    assert moved["status"] == "ACTIVE"
    assert moved["serial_start"] == 1 and moved["serial_end"] == 5
    assert moved["quantity_mwh"] == 5, "the serial range stays intact (no split)"

    all_certs = list_certificates(generator_id=setup["generator"]["id"])
    assert len(all_certs) == 1, "a full-quantity settle creates no remainder row"


def test_full_quantity_settle_recomputes_holdings(api):
    """PRD §3.4: "Holdings on both the seller's and buyer's accounts are
    recomputed as ownership moves."
    PRD §2.9: "Locking, transferring, retiring, and revoking move whole
    quantities between an account's `active_holdings_mwh` and
    `locked_holdings_mwh` or out of holdings entirely, but never create or
    destroy units".

    Design: Difficulty/boundary_precision_check/full_quantity_settle_no_remainder
    """
    setup = setup_brokers_with_certificates(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 5000}]
    )
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]
    settle_accepted_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 5}],
        settlement_mode="NET",
    )
    seller = get_account(b1["id"])
    buyer = get_account(b2["id"])
    assert seller["active_holdings_mwh"] == 0
    assert seller["locked_holdings_mwh"] == 0
    assert buyer["active_holdings_mwh"] == 5
    assert buyer["locked_holdings_mwh"] == 0


def test_partial_settle_partitions_serial_range(api):
    """PRD §3.4: "When the item's quantity is smaller, the batch splits in
    two — the original row remains with the seller as the remainder, its
    `serial_start` advanced by the transferred quantity and its `quantity_mwh`
    reduced accordingly ... while a brand-new certificate row is created for
    the transferred slice with `serial_start` equal to the original range's
    old start and `serial_end` equal to that old start plus the transferred
    quantity minus one, owned by the buyer and `ACTIVE`, copying
    `generator_id`, `vintage_month`, `region_code`, `technology`, and
    `serial_prefix` from the original. The two serial ranges partition the
    original range with no gap and no overlap, and the two quantities sum
    exactly to the pre-split `quantity_mwh`."

    Design: Difficulty/compensating_invariant/serial_partition_conservation
    """
    setup = setup_brokers_with_certificates(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 100000}]
    )
    cert = setup["certificates"][0]
    assert cert["quantity_mwh"] == 100
    assert cert["serial_start"] == 1 and cert["serial_end"] == 100
    b1, b2 = setup["b1"], setup["b2"]

    trade = settle_accepted_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 37}],
        settlement_mode="GROSS",
    )
    assert trade["status"] == "SETTLED"

    buyer_rows = list_certificates(account_id=b2["id"])
    assert len(buyer_rows) == 1
    slice_cert = buyer_rows[0]
    assert_certificate(slice_cert)
    assert slice_cert["id"] != cert["id"], "the transferred slice is a new row"
    assert slice_cert["serial_start"] == 1 and slice_cert["serial_end"] == 37
    assert slice_cert["quantity_mwh"] == 37
    assert slice_cert["status"] == "ACTIVE"
    # Snapshots copy from the original batch.
    assert slice_cert["generator_id"] == cert["generator_id"]
    assert slice_cert["vintage_month"] == cert["vintage_month"]
    assert slice_cert["region_code"] == cert["region_code"]
    assert slice_cert["technology"] == cert["technology"]
    assert slice_cert["serial_prefix"] == cert["serial_prefix"]

    remainder = get_certificate(cert["id"])
    assert remainder["serial_start"] == 38 and remainder["serial_end"] == 100
    assert remainder["quantity_mwh"] == 63
    assert remainder["account_id"] == b1["id"]
    assert remainder["status"] == "ACTIVE", "the remainder returns LOCKED -> ACTIVE"

    assert 37 + 63 == 100, "units are conserved across the split"
    assert get_generator(setup["generator"]["id"])["lifetime_minted_mwh"] == 100


def test_remainder_lock_expire_round_trip_without_drift(api):
    """PRD §3.4: "A `RegistryAdmin` may expire an `ACCEPTED` trade once the
    logical clock has passed its `settlement_deadline` ... unlocking every
    item certificate from `LOCKED` back to `ACTIVE` with ownership unchanged"
    — after a split, a lock-then-expire round on the remainder restores it
    with zero drift in units, serials, or holdings.
    PRD §2.9: "the two resulting quantities sum exactly to the original
    `quantity_mwh`."

    Design: Difficulty/compensating_invariant/serial_partition_conservation
    """
    setup = setup_brokers_with_certificates(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 100000}]
    )
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]
    settle_accepted_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 37}],
    )
    # Lock the remainder via a second accepted trade, then let it expire.
    trade2 = propose_and_accept_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 10}],
    )
    assert get_certificate(cert["id"])["status"] == "LOCKED"

    set_clock("2026-08-07T00:00:00Z")  # past trade2's deadline (accepted 08-01 + 5d)
    expire_trade(trade2["id"])

    remainder = get_certificate(cert["id"])
    assert remainder["status"] == "ACTIVE", "expiry compensates the lock fully"
    assert remainder["account_id"] == b1["id"]
    assert remainder["serial_start"] == 38 and remainder["serial_end"] == 100
    assert remainder["quantity_mwh"] == 63

    seller = get_account(b1["id"])
    buyer = get_account(b2["id"])
    assert seller["active_holdings_mwh"] == 63
    assert seller["locked_holdings_mwh"] == 0
    assert buyer["active_holdings_mwh"] == 37
    assert seller["active_holdings_mwh"] + buyer["active_holdings_mwh"] == 100, (
        "holdings stay conserved through split + lock + expire"
    )


# ---------------------------------------------------------------------------
# Trade state machine guards and settlement window boundaries
# ---------------------------------------------------------------------------

def test_trade_settle_twice_and_cancel_accepted_rejected(api):
    """PRD §3.4: "Any accept, settle, cancel, or expire attempted from a
    state the transition does not allow is rejected with
    `ERR_TRADE_STATE_INVALID`." and "Settlement stamps `settled_at` and moves
    the trade to the terminal `SETTLED` state." and "The seller may cancel a
    `PROPOSED` trade".

    Design: Corner/state_machines/trade_settle_twice_and_cancel_accepted_rejected
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]
    trade = propose_and_accept_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )

    # Cancel requires PROPOSED; this trade is ACCEPTED.
    resp_cancel = api.cancel_trade(trade["id"], make_broker_trader_headers(b1["id"]))
    validate_error(resp_cancel, ApiErrorId.ERR_TRADE_STATE_INVALID, expected_status=409)

    settled = settle_trade(trade["id"], b2["id"])
    assert settled["status"] == "SETTLED"
    assert settled["settled_at"] is not None

    resp_again = api.settle_trade(trade["id"], make_broker_trader_headers(b2["id"]))
    validate_error(resp_again, ApiErrorId.ERR_TRADE_STATE_INVALID, expected_status=409)


def test_settlement_window_and_expire_boundary(api):
    """PRD §3.4: "Settlement is likewise the buyer's move and is permitted
    only while the logical clock is at or before the `settlement_deadline`; a
    late attempt is rejected with `ERR_SETTLEMENT_WINDOW_EXPIRED`" and "A
    `RegistryAdmin` may expire an `ACCEPTED` trade once the logical clock has
    passed its `settlement_deadline` — an expiry attempted at or before the
    deadline is rejected with `ERR_TRADE_NOT_EXPIRED`" and "Acceptance stamps
    `accepted_at` and fixes the `settlement_deadline` exactly five days
    later."

    Design: Corner/validations/settlement_window_and_expire_boundary
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]

    # t1 accepted at the 2026-08-01 startup clock -> deadline 2026-08-06.
    t1 = propose_and_accept_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )
    set_clock("2026-08-06T00:00:00Z")
    settled = settle_trade(t1["id"], b2["id"])
    assert settled["status"] == "SETTLED", "settle at exactly the deadline is inclusive"

    # t2: b2 (now holding the certificate) sells back to b1; accepted at
    # 2026-08-06 -> deadline 2026-08-11.
    t2 = propose_and_accept_trade(
        b2["id"], b1["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )

    early_expire = api.expire_trade(t2["id"], ADMIN)
    validate_error(early_expire, ApiErrorId.ERR_TRADE_NOT_EXPIRED, expected_status=409)

    set_clock("2026-08-12T00:00:00Z")  # one day past t2's deadline
    late_settle = api.settle_trade(t2["id"], make_broker_trader_headers(b1["id"]))
    validate_error(late_settle, ApiErrorId.ERR_SETTLEMENT_WINDOW_EXPIRED, expected_status=422)

    expired = expire_trade(t2["id"])
    assert expired["status"] == "EXPIRED"
    cert_after = get_certificate(cert["id"])
    assert cert_after["status"] == "ACTIVE"
    assert cert_after["account_id"] == b2["id"], "t2's seller keeps the certificate"
    assert get_account(b1["id"])["failure_strikes"] == 1, "t2's buyer takes the strike"


# ---------------------------------------------------------------------------
# Transfers, proposal ownership, and quantity guards
# ---------------------------------------------------------------------------

def test_certificate_transfer_holdings_ledger_sync(api):
    """PRD §3.4: "the certificate keeps its `ACTIVE` status, its `account_id`
    is reassigned, holdings are recomputed on both accounts, and the
    certificate's `version` increments."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    by exactly one on every mutation of the resource."

    Design: Corner/endpoints/certificate_transfer_holdings_ledger_sync
    """
    setup = setup_minted_generator(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 5000}]
    )
    cert = setup["certificates"][0]
    assert cert["quantity_mwh"] == 5
    gacc = setup["account"]
    b1 = create_broker_account("Broker One")

    assert get_account(gacc["id"])["active_holdings_mwh"] == 5
    assert get_account(b1["id"])["active_holdings_mwh"] == 0

    moved = transfer_certificate(cert["id"], b1["id"])
    assert moved["account_id"] == b1["id"]
    assert moved["status"] == "ACTIVE"
    assert moved["version"] == cert["version"] + 1, "transfer increments the version by one"

    assert get_account(gacc["id"])["active_holdings_mwh"] == 0
    assert get_account(b1["id"])["active_holdings_mwh"] == 5, (
        "holdings move within the same request"
    )


def test_broker_cannot_propose_from_others_account(api):
    """PRD §2.1: "Proposing a trade requires `X-User-ID` to equal the trade's
    `from_account_id`" and "A request whose role is not permitted for the
    target endpoint — or that fails an ownership, purpose, or scope match
    described below — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/broker_cannot_propose_from_others_account
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]

    resp = api.create_trade(
        {
            "from_account_id": b1["id"],
            "to_account_id": b2["id"],
            "items": [{"certificate_id": cert["id"], "quantity_mwh": 1}],
            "unit_price_cents_per_mwh": 300,
            "settlement_mode": "GROSS",
        },
        make_broker_trader_headers(b2["id"]),  # caller is not the seller
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    trades, meta = validate_paginated(
        api.list_trades(ADMIN, params={"from_account_id": b1["id"]})
    )
    assert meta["total_count"] == 0, "a forbidden proposal must not create a trade"


def test_quantity_invalid_zero_and_over(api):
    """PRD §3.2: "`metered_kwh` must be a positive integer, with non-positive
    values rejected as `ERR_QUANTITY_INVALID`."
    PRD §3.4: "each line's `quantity_mwh` must be at least one and no more
    than that certificate's own `quantity_mwh`, with out-of-range quantities
    rejected as `ERR_QUANTITY_INVALID`."

    Design: Corner/errors/quantity_invalid_zero_and_over
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    assert cert["quantity_mwh"] == 1
    b1, b2 = setup["b1"], setup["b2"]

    # A zero-kWh reading on a June period (no overlap with the July reading,
    # so the quantity rule is the only failure).
    resp_zero = api.create_meter_reading(
        create_meter_reading_payload(
            generator_id=setup["generator"]["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-06-15T00:00:00Z",
            metered_kwh=0,
        ),
        make_generator_operator_headers(setup["generator"]["id"]),
    )
    validate_error(resp_zero, ApiErrorId.ERR_QUANTITY_INVALID, expected_status=400)

    resp_over = api.create_trade(
        {
            "from_account_id": b1["id"],
            "to_account_id": b2["id"],
            "items": [{"certificate_id": cert["id"], "quantity_mwh": 2}],
            "unit_price_cents_per_mwh": 300,
            "settlement_mode": "GROSS",
        },
        make_broker_trader_headers(b1["id"]),
    )
    validate_error(resp_over, ApiErrorId.ERR_QUANTITY_INVALID, expected_status=400)
