"""Second tests for the difficulty instances, each asserting a distinct
PRD-derivable angle (the complementary branch, the boundary's other side, or a
different observable consequence) from the primary test in earlier files.

Each instance must carry >= 2 tests; this file supplies the second.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    make_bettor_headers,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/kyc_vs_geo_kyc_wins
# Complement: once KYC is verified, the same geo-missing placement surfaces the
# lower-priority ERR_GEO_INELIGIBLE — confirming geo is the *next* gate behind KYC.
# ===========================================================================
def test_geo_error_surfaces_only_after_kyc_passes(api):
    """PRD §2.10: "then the requirement that identity be verified
    (ERR_KYC_NOT_VERIFIED), then for placement the geolocation eligibility gate
    (ERR_GEO_INELIGIBLE)".
    PRD §3.4: "If no such unexpired, eligible reading exists, placement is rejected
    with ERR_GEO_INELIGIBLE."

    With KYC now VERIFIED (the higher-priority gate satisfied) but still no
    geo-check, the placement surfaces ERR_GEO_INELIGIBLE — the gate that
    ERR_KYC_NOT_VERIFIED preempted when both failed.

    Design: Difficulty/priority_pair_validation_conflict/kyc_vs_geo_kyc_wins
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)  # VERIFIED, no geo
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_GEO_INELIGIBLE.value)


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/state_invalid_vs_fiscal_insufficient_state_wins
# Complement: cashing out a settled (terminal, non-PLACED) bet also returns
# ERR_INVALID_STATE — the state gate fires for any non-PLACED status, not just
# CASHED_OUT.
# ===========================================================================
def test_cashout_of_settled_bet_returns_invalid_state(api):
    """PRD §3.9: "the bet must be in PLACED status (otherwise ERR_INVALID_STATE)".
    PRD §2.10: "State validity (ERR_INVALID_STATE) is checked fifth."

    A bet that has reached the terminal WON status (no longer PLACED) cannot be
    cashed out: the state precondition fires ahead of any fiscal check, returning
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_vs_fiscal_insufficient_state_wins
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=90, away_score=110)  # bet WON, terminal
    v = fx.get_account(acct["id"])["version"]
    resp = api.cash_out_bet(bet["id"], {"expected_account_version": v}, make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty/boundary_precision_check/empty_legs_array_rejected_on_bet_create
# Complement: the X side of the boundary — a SINGLE with exactly one leg is
# accepted, confirming the empty-set rejection is about cardinality, not a blanket
# SINGLE ban.
# ===========================================================================
def test_single_with_exactly_one_leg_accepted(api):
    """PRD §3.7: "A SINGLE carries exactly one leg."
    PRD §3.7: "When a placement passes every gate ... The bet opens in status
    PLACED."

    A SINGLE with exactly one leg (the valid cardinality, X side of the empty/one
    boundary) is accepted and opens PLACED — the empty-legs rejection is purely a
    cardinality failure.

    Design: Difficulty/boundary_precision_check/empty_legs_array_rejected_on_bet_create
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", f"one-leg SINGLE should be PLACED, got {data['status']}"
    assert data["bet_type"] == "SINGLE", f"got {data['bet_type']}"


# ===========================================================================
# Difficulty/cross_entity_state_dependency/bet_placement_requires_market_open_and_event_scheduled
# Complement: the positive cross-entity state — while Market OPEN AND Event
# SCHEDULED, the placement succeeds; the gate is specifically about that joint
# state.
# ===========================================================================
def test_placement_succeeds_while_market_open_and_event_scheduled(api):
    """PRD §3.7: "Every leg's market must be OPEN and its event SCHEDULED with a
    starts_at still in the future relative to the clock; any leg failing this
    temporal gate yields ERR_MARKET_NOT_OPEN."

    With the joint precondition satisfied (Market OPEN, Event SCHEDULED, future
    starts_at), the same placement that fails once the event goes LIVE here
    succeeds and opens PLACED.

    Design: Difficulty/cross_entity_state_dependency/bet_placement_requires_market_open_and_event_scheduled
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    assert ev["status"] == "SCHEDULED" and mkt["status"] == "OPEN"
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", (
        f"placement with market OPEN and event SCHEDULED should succeed, got {data['status']}")


# ===========================================================================
# Difficulty/cross_entity_state_dependency/result_post_requires_event_live_not_scheduled
# Complement: the positive transition — once the event is LIVE, the same result
# post succeeds and settles the event.
# ===========================================================================
def test_post_result_succeeds_once_event_live(api):
    """PRD §3.10: "An event may be settled only from LIVE. On success the scores
    and the agent's identifier in result_posted_by are recorded and the event
    moves to SETTLED".

    The same result post that fails while the event is SCHEDULED succeeds once the
    event is taken LIVE — the transition depends on the event's own LIVE status.

    Design: Difficulty/cross_entity_state_dependency/result_post_requires_event_live_not_scheduled
    """
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9_000_000)
    fx.take_event_live(ev["id"])
    data = validate_success(api.post_event_result(
        ev["id"], {"home_score": 100, "away_score": 90}, fx.SETTLER), 200)
    assert data["status"] == "SETTLED", f"LIVE event should settle, got {data['status']}"


# ===========================================================================
# Difficulty/resource_temporal_overlap/same_game_parlay_two_legs_same_market_rejected
# Complement: an SGP whose two legs sit on DIFFERENT markets of the SAME event is
# accepted — the rejection is specifically about same-market correlation, not SGP
# itself.
# ===========================================================================
def test_same_game_parlay_distinct_markets_same_event_accepted(api):
    """PRD §3.7: "A SAME_GAME_PARLAY is the opposite: all of its legs must
    reference selections whose markets share a single event."
    PRD §3.7: "for a same-game parlay no two legs may sit on the same market".

    An SGP with two legs on two distinct markets of one event (same event, no
    same-market collision) is accepted — isolating that the duplicate-leg rejection
    is the same-market case alone.

    Design: Difficulty/resource_temporal_overlap/same_game_parlay_two_legs_same_market_rejected
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev = fx.create_event(sport="NBA")
    mkt1 = fx.create_market(ev["id"], market_type="MONEYLINE", liability_cap_cents=90_000_000)
    sel1 = fx.create_selection(mkt1["id"], "HOME", -150)
    mkt2 = fx.create_market(ev["id"], market_type="TOTAL", line=210.5, liability_cap_cents=90_000_000)
    sel2 = fx.create_selection(mkt2["id"], "OVER", -110)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SAME_GAME_PARLAY", 3000, [sel1["id"], sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", (
        f"SGP across distinct markets of one event should be accepted, got {data['status']}")
    assert data["bet_type"] == "SAME_GAME_PARLAY"


# ===========================================================================
# Difficulty/resource_temporal_overlap/parlay_legs_must_span_distinct_events
# Complement: a PARLAY whose two legs span two DISTINCT events is accepted — the
# rejection is specifically about insufficient event-spread.
# ===========================================================================
def test_parlay_across_two_distinct_events_accepted(api):
    """PRD §3.7: "A PARLAY must span at least two distinct events — its legs
    reference selections whose markets belong to two or more different events."

    A PARLAY whose two legs belong to selections on two different events satisfies
    the >=2-distinct-events rule and is accepted — confirming the same-event PARLAY
    rejection is purely about event-spread.

    Design: Difficulty/resource_temporal_overlap/parlay_legs_must_span_distinct_events
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev1, mkt1, sel1 = fx.create_board(selection_name="HOME", american_odds=-150,
                                      liability_cap_cents=90_000_000)
    ev2, mkt2, sel2 = fx.create_board(selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000,
                                      starts_at="2026-02-02T18:00:00Z")
    resp = api.create_bet(
        f.bet_payload(acct["id"], "PARLAY", 3000, [sel1["id"], sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", (
        f"PARLAY across two distinct events should be accepted, got {data['status']}")
    assert data["bet_type"] == "PARLAY"


# ===========================================================================
# Difficulty/compensating_invariant/bonus_completion_conserves_total_bankroll_across_buckets
# Complement: the bonus-completion ledger pair (BONUS debit + equal CASH credit)
# itself nets to zero, so the total bankroll is conserved across the conversion.
# ===========================================================================
def test_bonus_completion_ledger_pair_nets_to_zero(api):
    """PRD §3.11: "the remaining bonus balance is converted to cash by a matched
    ledger pair — a BONUS debit and an equal-magnitude CASH credit — which finally
    makes those funds withdrawable."
    PRD §2.7: "An account's cash_balance_cents is the sum of amount_cents across all
    of its LedgerEntry rows whose bucket is CASH, and its bonus_balance_cents is the
    equivalent sum over rows whose bucket is BONUS."

    On completion the remaining 2000 bonus is debited from BONUS and an equal 2000
    credited to CASH, so cash+bonus bankroll is conserved at 92000 across the
    matched pair.

    Design: Difficulty/compensating_invariant/bonus_completion_conserves_total_bankroll_across_buckets
    """
    promo = fx.create_promotion("BC11", bonus_cents=2000, wagering_multiplier=5,
                                min_odds_american=-200, max_claims=10)
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    grant = fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 10000, [sel["id"]], v,
                 stake_bucket="CASH", bonus_grant_id=grant["id"])
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=110, away_score=90)  # LOST but qualifying → grant COMPLETES

    acct_data = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    bankroll = acct_data["cash_balance_cents"] + acct_data["bonus_balance_cents"]
    assert acct_data["bonus_balance_cents"] == 0, (
        f"remaining bonus debited to 0, got {acct_data['bonus_balance_cents']}")
    assert bankroll == 92000, (
        f"cash+bonus bankroll conserved at 92000 across the matched pair, got {bankroll}")
