"""Bet-placement gates: validation precedence, cross-entity state dependency,
parlay composition, duplicate legs, boundary, and the RG/geo/funds/risk errors.

Covers difficulty rules priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, plus corner validation
and error claims.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    make_bettor_headers,
    validate_success, validate_error,
    ApiErrorId,
)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/kyc_vs_geo_kyc_wins
# ===========================================================================
def test_unverified_kyc_and_missing_geo_returns_kyc_error(api):
    """PRD §2.10: "then the requirement that identity be verified
    (ERR_KYC_NOT_VERIFIED), then for placement the geolocation eligibility gate
    (ERR_GEO_INELIGIBLE)".
    PRD §3.7: "the account ... must be KYC-verified (ERR_KYC_NOT_VERIFIED), and
    must have a current eligible geo-check (ERR_GEO_INELIGIBLE)."

    A placement that is BOTH unverified-KYC AND missing a geo-check surfaces the
    higher-priority ERR_KYC_NOT_VERIFIED, not ERR_GEO_INELIGIBLE.

    Design: Difficulty/priority_pair_validation_conflict/kyc_vs_geo_kyc_wins
    """
    acct = fx.register_account()  # PENDING KYC, no geo-check
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], acct["version"]),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_KYC_NOT_VERIFIED.value)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/state_invalid_vs_fiscal_insufficient_state_wins
# ===========================================================================
def test_cashout_already_cashed_out_returns_invalid_state(api):
    """PRD §2.10: "State validity (ERR_INVALID_STATE) is checked fifth."
    PRD §3.9: "Cash-out is only offered while the ticket is genuinely live and
    unresolved: the bet must be in PLACED status (otherwise ERR_INVALID_STATE)".

    Cashing out a bet that is already CASHED_OUT returns ERR_INVALID_STATE — the
    state precondition is reached before any fiscal balance check.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_vs_fiscal_insufficient_state_wins
    """
    acct, ev, mkt, sel, bet, v = fx.setup_single_bet(stake_cents=5000, american_odds=200,
                                                      liability_cap_cents=90_000_000)
    # First cash-out succeeds.
    validate_success(api.cash_out_bet(bet["id"], {"expected_account_version": v},
                                      make_bettor_headers(acct["id"])), 200)
    v2 = fx.get_account(acct["id"])["version"]
    # Second cash-out on the now-CASHED_OUT bet.
    resp = api.cash_out_bet(bet["id"], {"expected_account_version": v2},
                            make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty/boundary_precision_check/deposit_limit_exact_boundary_allows_equal
# ===========================================================================
def test_deposit_at_exact_limit_boundary_allowed(api):
    """PRD §3.3: "If that windowed total plus the new deposit would exceed the
    control's limit_cents, the deposit is rejected with
    ERR_DEPOSIT_LIMIT_EXCEEDED; a total exactly equal to the limit is allowed,
    since the boundary is a strict greater-than."

    DAILY DEPOSIT_LIMIT 50000; a prior 30000 deposit; a new 20000 lands at exactly
    50000 and is ACCEPTED.

    Design: Difficulty/boundary_precision_check/deposit_limit_exact_boundary_allows_equal
    """
    acct, v = fx.create_verified_bettor()
    fx.set_rg_control(acct["id"], "DEPOSIT_LIMIT", v, period="DAILY", limit_cents=50000)
    v = fx.get_account(acct["id"])["version"]
    fx.deposit(acct["id"], 30000, v)
    v = fx.get_account(acct["id"])["version"]

    resp = api.create_deposit(acct["id"], f.deposit_payload(20000, v), make_bettor_headers(acct["id"]))
    entry = validate_success(resp, 201)
    assert entry["entry_type"] == "DEPOSIT", f"deposit should be accepted, got {entry}"
    bal = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert bal["cash_balance_cents"] == 50000, (
        f"balance at the exact 50000 limit should be 50000, got {bal['cash_balance_cents']}")


def test_deposit_one_cent_over_limit_rejected(api):
    """PRD §3.3: "If that windowed total plus the new deposit would exceed the
    control's limit_cents, the deposit is rejected with ERR_DEPOSIT_LIMIT_EXCEEDED
    ... since the boundary is a strict greater-than."

    Prior 30000 deposit + a new 20001 = 50001 > 50000 limit → rejected (X+1 side
    of the strict-> boundary).

    Design: Difficulty/boundary_precision_check/deposit_limit_exact_boundary_allows_equal
    """
    acct, v = fx.create_verified_bettor()
    fx.set_rg_control(acct["id"], "DEPOSIT_LIMIT", v, period="DAILY", limit_cents=50000)
    v = fx.get_account(acct["id"])["version"]
    fx.deposit(acct["id"], 30000, v)
    v = fx.get_account(acct["id"])["version"]

    resp = api.create_deposit(acct["id"], f.deposit_payload(20001, v), make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_LIMIT_EXCEEDED.value)


# ===========================================================================
# Difficulty/boundary_precision_check/empty_legs_array_rejected_on_bet_create
# ===========================================================================
def test_single_bet_with_empty_legs_rejected(api):
    """PRD §3.7: "A SINGLE carries exactly one leg."
    PRD §3.7: "A composition that contradicts the declared type is rejected with
    ERR_PARLAY_COMPOSITION_INVALID."

    A SINGLE with a zero-length legs array fails composition (the empty set is not
    one leg).

    Design: Difficulty/boundary_precision_check/empty_legs_array_rejected_on_bet_create
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    resp = api.create_bet(
        {"account_id": acct["id"], "bet_type": "SINGLE", "stake_cents": 5000,
         "legs": [], "expected_account_version": v},
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_PARLAY_COMPOSITION_INVALID.value)


# ===========================================================================
# Difficulty/cross_entity_state_dependency/bet_placement_requires_market_open_and_event_scheduled
# ===========================================================================
def test_placement_blocked_when_event_live_suspends_market(api):
    """PRD §3.7: "Every leg's market must be OPEN and its event SCHEDULED with a
    starts_at still in the future relative to the clock; any leg failing this
    temporal gate yields ERR_MARKET_NOT_OPEN."
    PRD §3.6: "going live suspends betting by moving every OPEN market on the event
    to SUSPENDED so that no new wagers land while play is underway."

    Taking the event LIVE (which suspends its market) makes the same placement
    return ERR_MARKET_NOT_OPEN.

    Design: Difficulty/cross_entity_state_dependency/bet_placement_requires_market_open_and_event_scheduled
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9_000_000)
    fx.take_event_live(ev["id"])
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_MARKET_NOT_OPEN.value)


# ===========================================================================
# Difficulty/cross_entity_state_dependency/result_post_requires_event_live_not_scheduled
# ===========================================================================
def test_post_result_on_scheduled_event_returns_invalid_state(api):
    """PRD §3.10: "An event may be settled only from LIVE."
    PRD §2.9: "Where an operation drives a state machine, the target must already
    be in a valid originating state for that transition; otherwise the request is
    rejected with ERR_INVALID_STATE."

    Posting a result while the event is still SCHEDULED (never taken LIVE) returns
    ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/result_post_requires_event_live_not_scheduled
    """
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9_000_000)
    resp = api.post_event_result(ev["id"], {"home_score": 100, "away_score": 90}, fx.SETTLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty/resource_temporal_overlap/same_game_parlay_two_legs_same_market_rejected
# ===========================================================================
def test_same_game_parlay_two_legs_same_market_rejected(api):
    """PRD §3.7: "No two legs may reference the same Selection, and for a
    same-game parlay no two legs may sit on the same market; a violation of either
    rule is rejected with ERR_DUPLICATE_LEG."

    A SAME_GAME_PARLAY whose two legs reference two selections of the SAME market
    collide on the same market_id → ERR_DUPLICATE_LEG.

    Design: Difficulty/resource_temporal_overlap/same_game_parlay_two_legs_same_market_rejected
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev = fx.create_event(sport="NBA")
    mkt = fx.create_market(ev["id"], market_type="MONEYLINE", liability_cap_cents=90_000_000)
    sel1 = fx.create_selection(mkt["id"], "HOME", -150)
    sel2 = fx.create_selection(mkt["id"], "AWAY", 130)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SAME_GAME_PARLAY", 3000, [sel1["id"], sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LEG.value)


# ===========================================================================
# Difficulty/resource_temporal_overlap/parlay_legs_must_span_distinct_events
# ===========================================================================
def test_parlay_legs_on_same_event_rejected(api):
    """PRD §3.7: "A PARLAY must span at least two distinct events — its legs
    reference selections whose markets belong to two or more different events ...
    A composition that contradicts the declared type is rejected with
    ERR_PARLAY_COMPOSITION_INVALID."

    A PARLAY whose two legs sit on two markets of the SAME event spans only one
    event → ERR_PARLAY_COMPOSITION_INVALID.

    Design: Difficulty/resource_temporal_overlap/parlay_legs_must_span_distinct_events
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev = fx.create_event(sport="NBA")
    mkt1 = fx.create_market(ev["id"], market_type="MONEYLINE", liability_cap_cents=90_000_000)
    sel1 = fx.create_selection(mkt1["id"], "HOME", -150)
    mkt2 = fx.create_market(ev["id"], market_type="TOTAL", line=210.5, liability_cap_cents=90_000_000)
    sel2 = fx.create_selection(mkt2["id"], "OVER", -110)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "PARLAY", 3000, [sel1["id"], sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_PARLAY_COMPOSITION_INVALID.value)


# ===========================================================================
# Corner/validations/insufficient_funds_on_oversized_stake
# ===========================================================================
def test_stake_over_balance_returns_insufficient_funds(api):
    """PRD §3.7: "the stake must be affordable: stake_cents may not exceed the
    available balance in the named bucket — cash_balance_cents for a cash stake,
    bonus_balance_cents for a bonus stake — and an overspend is rejected with
    ERR_INSUFFICIENT_FUNDS."

    Bettor with only 4000 cash attempts a 5000 stake → ERR_INSUFFICIENT_FUNDS.

    Design: Corner/validations/insufficient_funds_on_oversized_stake
    """
    acct, v = fx.create_funded_bettor(deposit_cents=4000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ===========================================================================
# Corner/validations/risk_limit_exceeded_suspends_placement
# ===========================================================================
def test_placement_over_market_liability_cap_rejected(api):
    """PRD §3.7: "The platform recomputes the market liability that the new bet
    would create and rejects the placement with ERR_RISK_LIMIT_EXCEEDED if
    accepting it would push any touched market's current_liability_cents above
    that market's liability_cap_cents."
    PRD §3.8: "It is computed as the sum, over every bet currently in PLACED
    status that includes at least one leg whose selection belongs to this market,
    of that bet's potential_payout_cents minus its stake_cents."

    Market cap 9000; a SINGLE stake 5000 @+200 creates liability 15000-5000=10000
    > 9000 → ERR_RISK_LIMIT_EXCEEDED.

    Design: Corner/validations/risk_limit_exceeded_suspends_placement
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_RISK_LIMIT_EXCEEDED.value)


# ===========================================================================
# Corner/calculations/wager_limit_gross_excess_rejected
# ===========================================================================
def test_wager_limit_gross_window_excess_rejected(api):
    """PRD §3.7: "If the account holds an ACTIVE WAGER_LIMIT control, the platform
    sums the gross stake_cents of every bet placed within the rolling window ...
    and rejects the placement with ERR_WAGER_LIMIT_EXCEEDED if that gross window
    total plus the new stake would exceed the control's limit_cents."

    WAGER_LIMIT DAILY 10000; prior placed stake 6000 + new 5000 = 11000 > 10000 →
    ERR_WAGER_LIMIT_EXCEEDED.

    Design: Corner/calculations/wager_limit_gross_excess_rejected
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    fx.set_rg_control(acct["id"], "WAGER_LIMIT", v, period="DAILY", limit_cents=10000)
    v = fx.get_account(acct["id"])["version"]
    ev1, mkt1, sel1 = fx.create_board(selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 6000, [sel1["id"]], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])
    ev2, mkt2, sel2 = fx.create_board(selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000,
                                      starts_at="2026-02-02T18:00:00Z")
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_WAGER_LIMIT_EXCEEDED.value)


# ===========================================================================
# Corner/errors/cooling_off_blocks_new_bet_placement
# ===========================================================================
def test_cooling_off_blocks_placement(api):
    """PRD §3.2: "While the freeze stands (the clock is before cooling_off_until),
    placement and deposit attempts are rejected with ERR_RG_COOLING_OFF."

    Verified bettor set COOLING_OFF for 7 days, clock still 2026-01-01 (before the
    until), attempts a placement → ERR_RG_COOLING_OFF.

    Design: Corner/errors/cooling_off_blocks_new_bet_placement
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    fx.set_rg_control(acct["id"], "COOLING_OFF", v, duration_days=7)
    v = fx.get_account(acct["id"])["version"]
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_RG_COOLING_OFF.value)


# ===========================================================================
# Corner/errors/geo_ineligible_blocks_placement_when_no_check
# ===========================================================================
def test_placement_without_geo_check_returns_geo_ineligible(api):
    """PRD §3.4: "At placement the system consults the account's most recent
    geo-check: betting requires that the latest reading is eligible and that its
    expires_at is still after the current clock. If no such unexpired, eligible
    reading exists, placement is rejected with ERR_GEO_INELIGIBLE."

    Verified, funded bettor with NO geo-check at all → ERR_GEO_INELIGIBLE.

    Design: Corner/errors/geo_ineligible_blocks_placement_when_no_check
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_GEO_INELIGIBLE.value)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_version_on_second_placement
# ===========================================================================
def test_second_placement_with_stale_account_version_rejected(api):
    """PRD §2.6: "When a bet placement carries an expected_account_version that
    does not equal the target account's current version, the placement is rejected
    with ERR_STALE_VERSION (HTTP 412)."
    PRD §2.6: "Every successful balance-touching account write increments the
    account's version by exactly 1, so a client must re-read the account after each
    such write before issuing the next."

    The first placement bumps the account version; a second placement still
    carrying the pre-placement version is stale → ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_second_placement
    """
    acct, v_pre = fx.create_funded_bettor(deposit_cents=100_000)
    ev1, mkt1, sel1 = fx.create_board(selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000)
    ev2, mkt2, sel2 = fx.create_board(selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000,
                                      starts_at="2026-02-02T18:00:00Z")
    # First placement uses the current version and advances it.
    fx.place_bet(acct["id"], "SINGLE", 5000, [sel1["id"]], v_pre)
    # Second placement still carries the now-stale v_pre.
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel2["id"]], v_pre),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
