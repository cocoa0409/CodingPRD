"""Account standing: the three-strike suspension threshold, strike reset on
reinstatement, account-gated settlement, the depth-5 revoke -> trade-fail ->
strike -> suspend -> cancel cascade, accept-after-retirement preconditions,
wholesale claim-reference uniqueness, and the double-retirement guard."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_trade,
    create_account,
    create_broker_account,
    create_program,
    expire_trade,
    get_account,
    get_certificate,
    get_generator,
    get_trade,
    make_broker_trader_headers,
    propose_and_accept_trade,
    propose_trade,
    retire_voluntary,
    retire_wholesale,
    set_clock,
    setup_brokers_with_certificates,
    setup_minted_generator,
    settle_trade,
    transfer_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["registry_admin_headers"]


def _four_certificate_setup():
    """Four 1-MWh certificates (vintages 2026-07..2026-10) in broker b1."""
    setup = setup_brokers_with_certificates(
        readings=[
            {"period_start": "2026-07-01T00:00:00Z", "period_end": "2026-08-01T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-08-10T00:00:00Z"},
            {"period_start": "2026-08-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-09-05T00:00:00Z"},
            {"period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-20T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-09-25T00:00:00Z"},
            {"period_start": "2026-10-01T00:00:00Z", "period_end": "2026-10-05T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-10-05T00:00:00Z"},
        ]
    )
    certs = {c["vintage_month"]: c for c in setup["certificates"]}
    return setup, [certs["2026-07"], certs["2026-08"], certs["2026-09"], certs["2026-10"]]


def _three_accepted_trades_plus_proposed(b1, b2, certs):
    t1 = propose_and_accept_trade(b1["id"], b2["id"],
                                  [{"certificate_id": certs[0]["id"], "quantity_mwh": 1}])
    t2 = propose_and_accept_trade(b1["id"], b2["id"],
                                  [{"certificate_id": certs[1]["id"], "quantity_mwh": 1}])
    t3 = propose_and_accept_trade(b1["id"], b2["id"],
                                  [{"certificate_id": certs[2]["id"], "quantity_mwh": 1}])
    t4 = propose_trade(b1["id"], b2["id"],
                       [{"certificate_id": certs[3]["id"], "quantity_mwh": 1}])
    return t1, t2, t3, t4


# ---------------------------------------------------------------------------
# Revoke -> trade-fail -> strike -> suspend -> cancel cascade
# ---------------------------------------------------------------------------

def test_revoke_locked_certificate_fails_trade_and_strikes_seller(api):
    """PRD §3.4: "if a certificate referenced by an `ACCEPTED` trade is
    revoked, the trade fails: it moves to `FAILED`, every other item
    certificate not itself revoked unlocks from `LOCKED` to `ACTIVE`, and the
    seller account's `failure_strikes` increases by one, with the same
    three-strike suspension cascade."

    Design: Difficulty/transitive_cascade/certificate_revoke_strike_suspension_cascade
    """
    setup, certs = _four_certificate_setup()
    b1, b2 = setup["b1"], setup["b2"]
    t1, t2, t3, t4 = _three_accepted_trades_plus_proposed(b1, b2, certs)

    revoked = validate_success(
        api.revoke_certificate(certs[0]["id"], {"reason": "meter fraud"}, ADMIN)
    )
    assert revoked["status"] == "REVOKED"

    assert get_trade(t1["id"])["status"] == "FAILED", (
        "the trade locking the revoked certificate fails"
    )
    seller = get_account(b1["id"])
    assert seller["failure_strikes"] == 1, "one failure strikes the seller once"
    assert seller["status"] == "ACTIVE", "one strike is below the three-strike threshold"

    # Sibling trades are untouched by a single revoke.
    assert get_trade(t2["id"])["status"] == "ACCEPTED"
    assert get_trade(t3["id"])["status"] == "ACCEPTED"
    assert get_trade(t4["id"])["status"] == "PROPOSED"
    assert get_certificate(certs[1]["id"])["status"] == "LOCKED"


def test_third_strike_suspends_seller_and_cancels_proposed_trades(api):
    """PRD §3.4: "the moment an account's `failure_strikes` reaches three,
    the account transitions to `SUSPENDED` on its own. Either way, suspension
    cancels every `PROPOSED` trade on which the account is the seller — those
    trades move to `CANCELLED` without touching any certificates, because no
    locks are taken while a trade is merely proposed."
    PRD §3.4: "either path decrements the minting generator's
    `lifetime_minted_mwh` by the same quantity".

    Design: Difficulty/transitive_cascade/certificate_revoke_strike_suspension_cascade
    """
    setup, certs = _four_certificate_setup()
    b1, b2 = setup["b1"], setup["b2"]
    t1, t2, t3, t4 = _three_accepted_trades_plus_proposed(b1, b2, certs)

    for cert in certs[:3]:
        validate_success(api.revoke_certificate(cert["id"], {"reason": "meter fraud"}, ADMIN))

    assert get_trade(t1["id"])["status"] == "FAILED"
    assert get_trade(t2["id"])["status"] == "FAILED"
    assert get_trade(t3["id"])["status"] == "FAILED"

    seller = get_account(b1["id"])
    assert seller["failure_strikes"] == 3
    assert seller["status"] == "SUSPENDED", "the third failure auto-suspends the seller"

    assert get_trade(t4["id"])["status"] == "CANCELLED", (
        "the suspension cancels the seller's unrelated PROPOSED trade"
    )
    c4 = get_certificate(certs[3]["id"])
    assert c4["status"] == "ACTIVE", "a merely-proposed trade never locked its certificate"
    assert c4["account_id"] == b1["id"]
    assert get_account(b1["id"])["active_holdings_mwh"] == 1

    assert get_generator(setup["generator"]["id"])["lifetime_minted_mwh"] == 1, (
        "4 minted - 3 revoked"
    )


# ---------------------------------------------------------------------------
# Strike threshold boundary and reinstatement reset
# ---------------------------------------------------------------------------

def test_strike_threshold_exactly_three_suspends(api):
    """PRD §3.4: "the moment an account's `failure_strikes` reaches three,
    the account transitions to `SUSPENDED` on its own" — strikes one and two
    leave the account ACTIVE; the third flips it.
    PRD §3.4: "adding one to the buyer account's `failure_strikes`" (on
    expiry).

    Design: Corner/cross_cutting_complexity_layers/strike_threshold_exactly_three_suspends
    """
    setup = setup_brokers_with_certificates(
        readings=[
            {"period_start": "2026-07-01T00:00:00Z", "period_end": "2026-08-01T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-08-10T00:00:00Z"},
            {"period_start": "2026-08-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-09-05T00:00:00Z"},
            {"period_start": "2026-09-01T00:00:00Z", "period_end": "2026-09-20T00:00:00Z",
             "metered_kwh": 1000, "clock": "2026-09-25T00:00:00Z"},
        ]
    )
    certs = setup["certificates"]
    assert len(certs) == 3
    b1, b2 = setup["b1"], setup["b2"]

    trades = [
        propose_and_accept_trade(b1["id"], b2["id"],
                                 [{"certificate_id": c["id"], "quantity_mwh": 1}])
        for c in certs
    ]
    # All three accepted at clock 2026-09-25 -> deadline 2026-09-30.
    set_clock("2026-10-01T00:00:00Z")

    expire_trade(trades[0]["id"])
    buyer = get_account(b2["id"])
    assert buyer["failure_strikes"] == 1 and buyer["status"] == "ACTIVE"

    expire_trade(trades[1]["id"])
    buyer = get_account(b2["id"])
    assert buyer["failure_strikes"] == 2 and buyer["status"] == "ACTIVE", (
        "two strikes are still below the threshold"
    )

    expire_trade(trades[2]["id"])
    buyer = get_account(b2["id"])
    assert buyer["failure_strikes"] == 3
    assert buyer["status"] == "SUSPENDED", "the threshold is inclusive at exactly three"

    for c in certs:
        after = get_certificate(c["id"])
        assert after["status"] == "ACTIVE"
        assert after["account_id"] == b1["id"], "expiry unlocks with ownership unchanged"


def test_account_suspend_reinstate_cycle_resets_strikes(api):
    """PRD §3.4: "An account may be suspended by a `RegistryAdmin` (`ACTIVE`
    to `SUSPENDED`) and later reinstated (`SUSPENDED` to `ACTIVE`), with
    reinstatement resetting `failure_strikes` to zero".

    Design: Corner/state_machines/account_suspend_reinstate_cycle_resets_strikes
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]
    trade = propose_and_accept_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )
    set_clock("2026-08-07T00:00:00Z")  # past the 2026-08-06 deadline
    expire_trade(trade["id"])
    assert get_account(b2["id"])["failure_strikes"] == 1

    suspended = validate_success(api.suspend_account(b2["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(api.reinstate_account(b2["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["failure_strikes"] == 0, "reinstatement resets the strike ledger"

    cert_after = get_certificate(cert["id"])
    assert cert_after["status"] == "ACTIVE"
    assert cert_after["account_id"] == b1["id"], "expiry had already unlocked it to the seller"


# ---------------------------------------------------------------------------
# Account standing gates settlement
# ---------------------------------------------------------------------------

def _accepted_1mwh_trade():
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    trade = propose_and_accept_trade(
        setup["b1"]["id"], setup["b2"]["id"],
        [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )
    return setup, cert, trade


def test_settle_with_suspended_buyer_rejected(api):
    """PRD §3.4: "Settlement is likewise the buyer's move and is permitted
    only while the logical clock is at or before the `settlement_deadline`;
    ... and both accounts must still be in `ACTIVE` standing".
    PRD §2.8: "On a settlement, account standing is verified before the
    trade's own state-machine position, so a suspended buyer surfaces
    `ERR_ACCOUNT_NOT_ACTIVE` rather than `ERR_TRADE_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/trade_settle_requires_active_buyer_account
    """
    setup, cert, trade = _accepted_1mwh_trade()
    b1, b2 = setup["b1"], setup["b2"]
    validate_success(api.suspend_account(b2["id"], ADMIN))

    resp = api.settle_trade(trade["id"], make_broker_trader_headers(b2["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)

    assert get_trade(trade["id"])["status"] == "ACCEPTED", "a rejected settle moves nothing"
    locked = get_certificate(cert["id"])
    assert locked["status"] == "LOCKED"
    assert locked["account_id"] == b1["id"]


def test_settle_with_suspended_seller_rejected(api):
    """PRD §3.4: "both accounts must still be in `ACTIVE` standing" — the
    gate is symmetric between buyer and seller.

    Design: Difficulty/cross_entity_state_dependency/trade_settle_requires_active_buyer_account
    """
    setup, cert, trade = _accepted_1mwh_trade()
    b1, b2 = setup["b1"], setup["b2"]
    validate_success(api.suspend_account(b1["id"], ADMIN))

    resp = api.settle_trade(trade["id"], make_broker_trader_headers(b2["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)

    assert get_trade(trade["id"])["status"] == "ACCEPTED"
    assert get_certificate(cert["id"])["status"] == "LOCKED"


# ---------------------------------------------------------------------------
# Accept-time certificate revalidation and double-retirement guard
# ---------------------------------------------------------------------------

def test_trade_accept_after_certificate_retired_rejected(api):
    """PRD §3.4: "every item certificate is still `ACTIVE` and still held by
    the selling account: ownership can drift between proposal and acceptance,
    and any certificate that no longer qualifies fails the acceptance with
    `ERR_CERTIFICATE_NOT_ACTIVE`."

    Design: Corner/state_machines/trade_accept_after_certificate_retired_rejected
    """
    setup = setup_brokers_with_certificates()
    cert = setup["certificates"][0]
    b1, b2 = setup["b1"], setup["b2"]
    program = create_program()
    trade = propose_trade(
        b1["id"], b2["id"], [{"certificate_id": cert["id"], "quantity_mwh": 1}],
    )
    retire_voluntary(cert["id"], program["id"])

    resp = api.accept_trade(trade["id"], make_broker_trader_headers(b2["id"]))
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE, expected_status=409)
    assert get_trade(trade["id"])["status"] == "PROPOSED", (
        "a failed acceptance takes no locks and moves nothing"
    )


def test_certificate_double_retirement_rejected(api):
    """PRD §3.7: "the certificate must be `ACTIVE` — retiring a `LOCKED`,
    `RETIRED`, or `REVOKED` certificate is rejected with
    `ERR_CERTIFICATE_NOT_ACTIVE`" and "A certificate's terminal `RETIRED`
    status makes a second retirement of the same batch impossible."
    PRD §3.4: "a `RETIRED` or already `REVOKED` certificate is rejected with
    `ERR_CERTIFICATE_NOT_ACTIVE`" (on revoke).

    Design: Corner/state_machines/certificate_double_retirement_rejected
    """
    setup = setup_minted_generator()
    cert = setup["certificates"][0]
    program = create_program()
    retire_voluntary(cert["id"], program["id"])
    assert get_certificate(cert["id"])["status"] == "RETIRED"

    resp_retire = api.create_retirement(
        {"certificate_id": cert["id"], "purpose": "VOLUNTARY_PROGRAM",
         "program_id": program["id"]},
        TEST_USERS["program_manager_headers"],
    )
    validate_error(resp_retire, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE, expected_status=409)

    resp_revoke = api.revoke_certificate(cert["id"], {"reason": "too late"}, ADMIN)
    validate_error(resp_revoke, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE, expected_status=409)

    rows, meta = validate_paginated(
        api.list_retirements(ADMIN, params={"certificate_id": cert["id"]})
    )
    assert meta["total_count"] == 1, "exactly one retirement row exists for the batch"


# ---------------------------------------------------------------------------
# Wholesale claim-reference uniqueness
# ---------------------------------------------------------------------------

def test_wholesale_duplicate_claim_reference_rejected(api):
    """PRD §3.7: "For `WHOLESALE_CLAIM`, the `external_claim_reference` must
    be unique across all retirements ever recorded; a duplicate is rejected
    with `ERR_DUPLICATE_CLAIM_REFERENCE`."

    Design: Corner/validations/wholesale_duplicate_claim_reference_rejected
    """
    setup = setup_brokers_with_certificates()
    b1 = setup["b1"]
    cert1 = setup["certificates"][0]
    # A second certificate from another generator, also transferred to b1.
    other = setup_minted_generator(
        legal_name="West Wind", facility_code="WW1", technology="WIND",
        region_code="ERCOT",
    )
    cert2 = other["certificates"][0]
    transfer_certificate(cert2["id"], b1["id"])

    first = retire_wholesale(cert1["id"], b1["id"], "CLAIM-2026-0001")
    assert first["purpose"] == "WHOLESALE_CLAIM"

    resp = api.create_retirement(
        {"certificate_id": cert2["id"], "purpose": "WHOLESALE_CLAIM",
         "external_claim_reference": "CLAIM-2026-0001"},
        make_broker_trader_headers(b1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM_REFERENCE, expected_status=409)
    assert get_certificate(cert2["id"])["status"] == "ACTIVE", (
        "the duplicate reference leaves the second certificate untouched"
    )
