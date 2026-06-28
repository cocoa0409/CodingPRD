"""Settlement grading cascade, self-exclusion cascade, parallel/cyclic state
machines, and conservation invariants.

Covers difficulty rules transitive_cascade, non_linear_state_machine, and
compensating_invariant, plus corner state-machine/consistency claims.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    make_bettor_headers,
    validate_success, validate_error,
    ApiErrorId,
    find_ledger_entry,
)


# ===========================================================================
# Difficulty/transitive_cascade/event_settle_grades_selection_then_leg_then_bet_then_wr
# ===========================================================================
def test_event_settle_cascades_to_selection_leg_bet_and_wagering_progress(api):
    """PRD §3.10: "On success the scores and the agent's identifier in
    result_posted_by are recorded and the event moves to SETTLED, which sets off
    the grading cascade in one atomic step."
    PRD §3.10: "If at least one leg is LOST, the bet is LOST: its
    actual_payout_cents is zero, no payout entry is posted, and settled_at is
    stamped."
    PRD §3.11: "Note that a settled losing qualifying bet still advances the
    requirement — it is the act of wagering at sufficient odds, not winning, that
    counts."
    PRD §3.11: "When progress reaches or passes the target, the grant moves from
    ACTIVE to COMPLETED".

    A SINGLE @+200 (3.0 >= min-odds floor) of stake 10000 bound to a grant
    (target 10000) settles LOST → selection LOST, bet LOST, progress 10000, grant
    COMPLETED.

    Design: Difficulty/transitive_cascade/event_settle_grades_selection_then_leg_then_bet_then_wr
    """
    promo = fx.create_promotion("BET10", bonus_cents=2000, wagering_multiplier=5,
                                min_odds_american=-200, max_claims=10)
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    grant = fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])

    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 10000, [sel["id"]], v,
                       stake_bucket="CASH", bonus_grant_id=grant["id"])
    fx.take_event_live(ev["id"])
    # HOME wins (home 110 > away 90) → AWAY selection LOST.
    fx.settle_event(ev["id"], home_score=110, away_score=90)

    sel_data = validate_success(api.get_selection(sel["id"], fx.OPS), 200)
    assert sel_data["result"] == "LOST", f"selection should be LOST, got {sel_data['result']}"

    bet_data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert bet_data["status"] == "LOST", f"bet should be LOST, got {bet_data['status']}"

    grant_data = validate_success(api.get_bonus_grant(grant["id"], make_bettor_headers(acct["id"])), 200)
    assert grant_data["wagering_progress_cents"] == 10000, (
        f"losing qualifying stake should advance progress to 10000, got "
        f"{grant_data['wagering_progress_cents']}")
    assert grant_data["status"] == "COMPLETED", (
        f"grant should COMPLETE when progress reaches target, got {grant_data['status']}")


def test_settlement_grades_bet_leg_result_mirrors_selection(api):
    """PRD §3.10: "First, every market on the event moves to SETTLED and each of
    its selections is graded WON, LOST, or PUSH according to that market's
    market_type and line against the official scores. Second, that selection grade
    is mirrored into the leg_result of every BetLeg sitting on those selections."

    After settlement, the bet's single leg carries leg_result LOST mirroring the
    LOST selection.

    Design: Difficulty/transitive_cascade/event_settle_grades_selection_then_leg_then_bet_then_wr
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=110, away_score=90)  # AWAY LOST

    from test_helpers import validate_paginated
    legs, _ = validate_paginated(api.list_bet_legs_of_bet(bet["id"], make_bettor_headers(acct["id"])))
    assert len(legs) == 1, f"expected one leg, got {len(legs)}"
    assert legs[0]["leg_result"] == "LOST", (
        f"leg_result must mirror the LOST selection, got {legs[0]['leg_result']}")


# ===========================================================================
# Difficulty/transitive_cascade/self_exclusion_voids_bet_refunds_and_forfeits_bonus
# ===========================================================================
def test_self_exclusion_voids_placed_bet_refunds_stake_and_forfeits_bonus(api):
    """PRD §3.2: "Imposing self-exclusion triggers a cascade in the same atomic
    request: every Bet of the account still in PLACED is moved to VOIDED and its
    stake is refunded by a VOID_REFUND LedgerEntry credited back to whichever
    bucket funded it; any BonusGrant of the account still ACTIVE is moved to
    FORFEITED and the corresponding bonus balance is zeroed via a negative BONUS
    ledger entry."

    Design: Difficulty/transitive_cascade/self_exclusion_voids_bet_refunds_and_forfeits_bonus
    """
    promo = fx.create_promotion("SX10", bonus_cents=2000, wagering_multiplier=5,
                                min_odds_american=-200, max_claims=10)
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    grant = fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])

    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v, stake_bucket="CASH")
    v = fx.get_account(acct["id"])["version"]

    # ComplianceOfficer imposes self-exclusion → cascade.
    validate_success(api.create_rg_control(
        acct["id"], f.rg_control_payload("SELF_EXCLUSION", v), fx.COMPLIANCE), 201)

    acct_data = validate_success(api.get_account(acct["id"], fx.COMPLIANCE), 200)
    assert acct_data["rg_status"] == "SELF_EXCLUDED", (
        f"rg_status should be SELF_EXCLUDED, got {acct_data['rg_status']}")
    assert acct_data["bonus_balance_cents"] == 0, (
        f"forfeited bonus balance should be 0, got {acct_data['bonus_balance_cents']}")

    bet_data = validate_success(api.get_bet(bet["id"], fx.COMPLIANCE), 200)
    assert bet_data["status"] == "VOIDED", f"placed bet should be VOIDED, got {bet_data['status']}"
    assert bet_data["actual_payout_cents"] == 5000, (
        f"voided stake refund should set actual_payout_cents to the 5000 stake, got "
        f"{bet_data['actual_payout_cents']}")

    grant_data = validate_success(api.get_bonus_grant(grant["id"], fx.COMPLIANCE), 200)
    assert grant_data["status"] == "FORFEITED", (
        f"active grant should be FORFEITED, got {grant_data['status']}")


def test_self_exclusion_refund_restores_cash_balance(api):
    """PRD §3.2: "every Bet of the account still in PLACED is moved to VOIDED and
    its stake is refunded by a VOID_REFUND LedgerEntry credited back to whichever
    bucket funded it".

    After a 5000 cash stake is voided by self-exclusion, the VOID_REFUND restores
    the cash balance to its pre-bet value (100000 deposit, no other movements).

    Design: Difficulty/transitive_cascade/self_exclusion_voids_bet_refunds_and_forfeits_bonus
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v, stake_bucket="CASH")
    v = fx.get_account(acct["id"])["version"]

    validate_success(api.create_rg_control(
        acct["id"], f.rg_control_payload("SELF_EXCLUSION", v), fx.COMPLIANCE), 201)

    acct_data = validate_success(api.get_account(acct["id"], fx.COMPLIANCE), 200)
    assert acct_data["cash_balance_cents"] == 100000, (
        f"VOID_REFUND must restore cash to 100000, got {acct_data['cash_balance_cents']}")


# ===========================================================================
# Difficulty/non_linear_state_machine/account_kyc_and_rg_dimensions_evolve_independently
# ===========================================================================
def test_account_kyc_and_rg_dimensions_are_independent(api):
    """PRD §3.1: "An account carries two independent status dimensions that
    evolve on separate machines. The first is kyc_status ... The second is
    rg_status ... The two dimensions advance without interfering with each other."

    VERIFY moves kyc_status PENDING→VERIFIED while rg_status stays ACTIVE; a later
    COOLING_OFF moves rg_status ACTIVE→COOLING_OFF while kyc_status stays VERIFIED.

    Design: Difficulty/non_linear_state_machine/account_kyc_and_rg_dimensions_evolve_independently
    """
    acct = fx.register_account()
    verified = fx.verify_kyc(acct["id"], acct["version"])
    assert verified["kyc_status"] == "VERIFIED", f"got {verified['kyc_status']}"
    assert verified["rg_status"] == "ACTIVE", (
        f"VERIFY must leave rg axis ACTIVE, got {verified['rg_status']}")

    fx.set_rg_control(acct["id"], "COOLING_OFF", verified["version"], duration_days=7)
    final = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert final["kyc_status"] == "VERIFIED", (
        f"COOLING_OFF must leave kyc axis VERIFIED, got {final['kyc_status']}")
    assert final["rg_status"] == "COOLING_OFF", f"got {final['rg_status']}"


def test_kyc_dimension_can_reach_verified_without_touching_rg(api):
    """PRD §3.1: "verifying advances kyc_status from PENDING to VERIFIED ... and
    the account's version increments by one."
    PRD §3.1: "A newly created account opens with kyc_status of PENDING,
    rg_status of ACTIVE".

    Verifying an account leaves rg_status at its initial ACTIVE — the kyc axis
    moves alone.

    Design: Difficulty/non_linear_state_machine/account_kyc_and_rg_dimensions_evolve_independently
    """
    acct = fx.register_account()
    assert acct["rg_status"] == "ACTIVE"
    verified = fx.verify_kyc(acct["id"], acct["version"])
    assert verified["kyc_status"] == "VERIFIED"
    assert verified["rg_status"] == "ACTIVE", (
        f"rg dimension untouched by KYC verify, got {verified['rg_status']}")
    assert verified["version"] == acct["version"] + 1, "version must increment by exactly 1"


# ===========================================================================
# Difficulty/non_linear_state_machine/market_open_suspend_reopen_cycle
# ===========================================================================
def test_market_open_suspend_reopen_returns_to_open(api):
    """PRD §3.6: "a TradingOps operator can suspend or reopen one manually by
    supplying the target to state ... Reopening a SUSPENDED market back to OPEN is
    conditional: it is allowed only while the event is still SCHEDULED".

    OPEN → SUSPENDED → OPEN cycles back to a previously-visited state.

    Design: Difficulty/non_linear_state_machine/market_open_suspend_reopen_cycle
    """
    ev, mkt, sel = fx.create_board(liability_cap_cents=9_000_000)
    s1 = validate_success(api.set_market_status(mkt["id"], {"to": "SUSPENDED"}, fx.OPS), 200)
    assert s1["status"] == "SUSPENDED", f"intermediate state should be SUSPENDED, got {s1['status']}"
    s2 = validate_success(api.set_market_status(mkt["id"], {"to": "OPEN"}, fx.OPS), 200)
    assert s2["status"] == "OPEN", f"reopen should return market to OPEN, got {s2['status']}"


def test_reopened_market_accepts_a_new_bet(api):
    """PRD §3.6: "Suspending an OPEN market blocks new legs from referencing its
    selections".
    PRD §3.7: "Every leg's market must be OPEN and its event SCHEDULED with a
    starts_at still in the future relative to the clock".

    After the OPEN→SUSPENDED→OPEN round trip the market is OPEN again and a fresh
    placement on its selection succeeds.

    Design: Difficulty/non_linear_state_machine/market_open_suspend_reopen_cycle
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    validate_success(api.set_market_status(mkt["id"], {"to": "SUSPENDED"}, fx.OPS), 200)
    validate_success(api.set_market_status(mkt["id"], {"to": "OPEN"}, fx.OPS), 200)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", f"reopened market should accept the bet, got {data['status']}"


# ===========================================================================
# Difficulty/compensating_invariant/void_refund_conserves_total_account_value
# ===========================================================================
def test_event_void_refund_conserves_cash_balance(api):
    """PRD §3.6: "The operator may instead void an event from either SCHEDULED or
    LIVE: voiding cascades down, moving every market on the event to VOIDED and
    every selection to VOID, and moving every PLACED bet that has any leg on the
    event to VOIDED with its stake refunded through a VOID_REFUND entry to the
    funding bucket."

    STAKE -5000 on placement paired with VOID_REFUND +5000 on event void leaves
    cash_balance_cents back at the pre-bet 100000.

    Design: Difficulty/compensating_invariant/void_refund_conserves_total_account_value
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)

    fx.void_event(ev["id"])

    acct_data = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert acct_data["cash_balance_cents"] == 100000, (
        f"STAKE -5000 + VOID_REFUND +5000 conserves cash at 100000, got "
        f"{acct_data['cash_balance_cents']}")

    bet_data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert bet_data["status"] == "VOIDED", f"got {bet_data['status']}"
    assert bet_data["actual_payout_cents"] == 5000, (
        f"refunded stake should appear as actual_payout_cents 5000, got "
        f"{bet_data['actual_payout_cents']}")


def test_void_refund_ledger_pair_sums_to_zero(api):
    """PRD §2.7: "An account's cash_balance_cents is the sum of amount_cents
    across all of its LedgerEntry rows whose bucket is CASH".
    PRD §3.6: "moving every PLACED bet that has any leg on the event to VOIDED with
    its stake refunded through a VOID_REFUND entry to the funding bucket."

    The STAKE debit and the VOID_REFUND credit for the bet net to zero in the
    CASH bucket, so the derived cash balance is unchanged.

    Design: Difficulty/compensating_invariant/void_refund_conserves_total_account_value
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    fx.void_event(ev["id"])

    from test_helpers import validate_paginated
    entries, _ = validate_paginated(api.list_ledger_entries(fx.COMPLIANCE, {"ref_id": bet["id"]}))
    stake = find_ledger_entry(entries, entry_type="STAKE", bucket="CASH", amount_cents=-5000)
    refund = find_ledger_entry(entries, entry_type="VOID_REFUND", bucket="CASH", amount_cents=5000)
    assert stake is not None, f"expected a STAKE -5000 CASH entry, got {entries}"
    assert refund is not None, f"expected a VOID_REFUND +5000 CASH entry, got {entries}"
    assert stake["amount_cents"] + refund["amount_cents"] == 0, "stake/refund pair must net to zero"


# ===========================================================================
# Difficulty/compensating_invariant/bonus_completion_conserves_total_bankroll_across_buckets
# ===========================================================================
def test_bonus_completion_converts_bonus_to_cash_conserving_bankroll(api):
    """PRD §3.11: "When progress reaches or passes the target, the grant moves
    from ACTIVE to COMPLETED, and the remaining bonus balance is converted to cash
    by a matched ledger pair — a BONUS debit and an equal-magnitude CASH credit —
    which finally makes those funds withdrawable."
    PRD §3.11: "Note that a settled losing qualifying bet still advances the
    requirement".

    Deposit 100000, claim bonus 2000 (target 10000), place a 10000 cash stake @+200
    (>= floor) bound to the grant; it settles LOST advancing progress to 10000 and
    completing the grant. Cash = 90000 post-stake + 2000 converted = 92000; bonus 0;
    the cash+bonus bankroll is conserved at 92000 across the conversion.

    Design: Difficulty/compensating_invariant/bonus_completion_conserves_total_bankroll_across_buckets
    """
    promo = fx.create_promotion("BC10", bonus_cents=2000, wagering_multiplier=5,
                                min_odds_american=-200, max_claims=10)
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    grant = fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])

    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 10000, [sel["id"]], v,
                       stake_bucket="CASH", bonus_grant_id=grant["id"])
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=110, away_score=90)  # AWAY LOST (qualifying)

    grant_data = validate_success(api.get_bonus_grant(grant["id"], make_bettor_headers(acct["id"])), 200)
    assert grant_data["status"] == "COMPLETED", f"got {grant_data['status']}"
    assert grant_data["wagering_progress_cents"] == 10000, (
        f"progress should reach target 10000, got {grant_data['wagering_progress_cents']}")

    acct_data = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert acct_data["bonus_balance_cents"] == 0, (
        f"remaining bonus must be debited to 0, got {acct_data['bonus_balance_cents']}")
    assert acct_data["cash_balance_cents"] == 92000, (
        f"90000 post-stake + 2000 converted bonus == 92000, got {acct_data['cash_balance_cents']}")


# ===========================================================================
# Corner/state_machines/event_void_cascades_markets_and_selections_void
# ===========================================================================
def test_event_void_cascades_market_voided_and_selection_void(api):
    """PRD §3.6: "voiding cascades down, moving every market on the event to
    VOIDED and every selection to VOID".

    Design: Corner/state_machines/event_void_cascades_markets_and_selections_void
    """
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=9_000_000)
    fx.void_event(ev["id"])
    mkt_data = validate_success(api.get_market(mkt["id"], fx.OPS), 200)
    assert mkt_data["status"] == "VOIDED", f"got {mkt_data['status']}"
    sel_data = validate_success(api.get_selection(sel["id"], fx.OPS), 200)
    assert sel_data["result"] == "VOID", f"got {sel_data['result']}"


# ===========================================================================
# Corner/state_machines/settlement_won_payout_credited_to_cash
# ===========================================================================
def test_settlement_won_payout_credited_to_cash_ledger(api):
    """PRD §3.10: "taking the floor of stake_cents multiplied by that effective
    figure as the actual_payout_cents, credited via a PAYOUT LedgerEntry."
    PRD §3.10: "If every leg resolved to WON, PUSH, or VOID with at least one WON,
    the bet is WON and is paid."

    SINGLE stake 5000 @+200 settled WON → status WON, actual_payout_cents 15000,
    and a PAYOUT entry of 15000 in the CASH bucket tied to the bet.

    Design: Corner/state_machines/settlement_won_payout_credited_to_cash
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=90, away_score=110)  # AWAY @+200 WON

    bet_data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert bet_data["status"] == "WON", f"got {bet_data['status']}"
    assert bet_data["actual_payout_cents"] == 15000, (
        f"floor(5000*3.0)==15000, got {bet_data['actual_payout_cents']}")

    from test_helpers import validate_paginated
    entries, _ = validate_paginated(api.list_ledger_entries(fx.COMPLIANCE, {"ref_id": bet["id"]}))
    payout = find_ledger_entry(entries, entry_type="PAYOUT", bucket="CASH", amount_cents=15000)
    assert payout is not None, f"expected a PAYOUT +15000 CASH entry tied to the bet, got {entries}"


# ===========================================================================
# Corner/consistency_model/settlement_cascade_visible_in_same_request
# ===========================================================================
def test_settlement_cascade_visible_synchronously(api):
    """PRD §2.9 (implied by §3.10's atomic step) — PRD §3.10: "the event moves to
    SETTLED, which sets off the grading cascade in one atomic step."
    PRD §1 (Introduction): "correctness here is a matter of disciplined ordering
    and atomic cascades rather than isolated CRUD."

    The result response itself shows Event.status SETTLED, and an immediately
    following bet read shows the bet already graded — no async lag.

    Design: Corner/consistency_model/settlement_cascade_visible_in_same_request
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    fx.take_event_live(ev["id"])

    result = validate_success(api.post_event_result(
        ev["id"], {"home_score": 90, "away_score": 110}, fx.SETTLER), 200)
    assert result["status"] == "SETTLED", (
        f"result response must show SETTLED, got {result['status']}")

    bet_data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert bet_data["status"] == "WON", (
        f"bet must be graded synchronously on the following read, got {bet_data['status']}")


# ===========================================================================
# Corner/cross_cutting_complexity_layers/derived_balance_reconciles_after_stake_and_payout
# ===========================================================================
def test_cash_balance_reconciles_through_stake_then_payout(api):
    """PRD §2.7: "An account's cash_balance_cents is the sum of amount_cents
    across all of its LedgerEntry rows whose bucket is CASH".
    PRD §3.7: "The stake is debited by appending a negative STAKE LedgerEntry
    against the chosen bucket".
    PRD §3.10: "credited via a PAYOUT LedgerEntry."

    Deposit 100000 → 100000; after a 5000 stake → 95000; after a WON +15000 payout
    → 110000, each derived from the ledger sum.

    Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciles_after_stake_and_payout
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    assert acct["cash_balance_cents"] == 100000, f"got {acct['cash_balance_cents']}"
    ev, mkt, sel = fx.create_board(selection_name="AWAY", american_odds=200,
                                   liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    mid = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert mid["cash_balance_cents"] == 95000, (
        f"after STAKE -5000 balance should be 95000, got {mid['cash_balance_cents']}")
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=90, away_score=110)
    final = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert final["cash_balance_cents"] == 110000, (
        f"after PAYOUT +15000 balance should be 110000, got {final['cash_balance_cents']}")
