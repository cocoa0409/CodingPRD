"""Account creation/validation, geo-check computed fields, listing, deposits,
KYC age/SoD rules, withdrawals, promotions, line-move snapshots, RBAC, and
cooling-off auto-clear.

Covers corner sections entities, state_machines, calculations, validations,
endpoints, errors, and rbac that are not owned by a difficulty stub.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    make_bettor_headers, make_trading_ops_headers, make_settlement_agent_headers,
    TEST_USERS, NO_AUTH_HEADERS,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_account, assert_geo_check,
    NON_EXISTENT_UUID,
)


# ===========================================================================
# Corner/entities/create_account_returns_201_pending_active_zero_balances
# ===========================================================================
def test_create_account_returns_pending_active_zero_balances(api):
    """PRD §3.1: "A newly created account opens with kyc_status of PENDING,
    rg_status of ACTIVE, a cash_balance_cents and bonus_balance_cents of zero, and
    a lifetime_deposits_cents of zero."
    PRD §2.4: "version is an integer that begins at 1".

    Design: Corner/entities/create_account_returns_201_pending_active_zero_balances
    """
    resp = api.create_account(f.create_account_payload(), None)
    data = validate_success(resp, 201)
    assert_account(data)
    assert data["kyc_status"] == "PENDING", f"got {data['kyc_status']}"
    assert data["rg_status"] == "ACTIVE", f"got {data['rg_status']}"
    assert data["cash_balance_cents"] == 0, f"got {data['cash_balance_cents']}"
    assert data["bonus_balance_cents"] == 0, f"got {data['bonus_balance_cents']}"
    assert data["version"] == 1, f"version must begin at 1, got {data['version']}"


# ===========================================================================
# Corner/entities/get_account_not_found_returns_404
# ===========================================================================
def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.9: "the parent must exist before the child is resolved, and any
    missing resource along the path yields ERR_NOT_FOUND."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, TEST_USERS["compliance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner/entities/create_account_missing_required_field_rejected
# ===========================================================================
def test_create_account_missing_residence_state_rejected(api):
    """PRD §2.10: "Field-level malformation — a missing required field, a bad enum
    member, a non-positive cents amount, or American odds whose magnitude is below
    100 — is the lowest-priority structural check and surfaces as
    ERR_INVALID_REQUEST."
    PRD §3.1: "by supplying a login email, a legal full_name, a date_of_birth as
    an ISO YYYY-MM-DD date, and a residence_state."

    Design: Corner/entities/create_account_missing_required_field_rejected
    """
    resp = api.create_account(
        {"email": "missing@x.com", "full_name": "No State", "date_of_birth": "1990-01-01"},
        None)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/invalid_residence_state_enum_rejected
# ===========================================================================
def test_create_account_invalid_residence_state_rejected(api):
    """PRD §3.1: "The residence state must be one of the six permitted
    jurisdictions — NJ, NY, PA, CO, AZ, or NV".
    PRD §2.10: "a bad enum member ... surfaces as ERR_INVALID_REQUEST."

    Design: Corner/entities/invalid_residence_state_enum_rejected
    """
    resp = api.create_account(f.create_account_payload(residence_state="ZZ"), None)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/selection_american_odds_below_100_magnitude_rejected
# ===========================================================================
def test_selection_american_odds_below_100_magnitude_rejected(api):
    """PRD §3.5: "the American odds must be nonzero and have magnitude at least
    100".
    PRD §2.10: "American odds whose magnitude is below 100 — is the lowest-priority
    structural check and surfaces as ERR_INVALID_REQUEST."

    Design: Corner/entities/selection_american_odds_below_100_magnitude_rejected
    """
    ev = fx.create_event(sport="NBA")
    mkt = fx.create_market(ev["id"], market_type="MONEYLINE", liability_cap_cents=9_000_000)
    resp = api.create_selection(mkt["id"], f.selection_payload("HOME", 50), fx.OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/geocheck_computed_eligible_and_immutable_id_only
# ===========================================================================
def test_geocheck_eligible_computed_and_append_only_shape(api):
    """PRD §3.4: "eligible is true only when the detected state is one of the
    permitted betting states, the accuracy radius is at most the maximum permitted
    accuracy, and the VPN-suspected flag is false".
    PRD §3.4: "The detected state may be any of NJ, NY, PA, CO, AZ, NV, FL, TX, CA,
    or INTL, but only the first six are permitted for betting."
    PRD §2.4: "These are GeoCheck ... they have neither updated_at nor version."

    Design: Corner/entities/geocheck_computed_eligible_and_immutable_id_only
    """
    acct = fx.register_account()
    g1 = validate_success(api.create_geo_check(
        acct["id"], f.geo_check_payload("NJ", 20), make_bettor_headers(acct["id"])), 201)
    assert_geo_check(g1)
    assert g1["eligible"] is True, f"NJ/20m/no-vpn must be eligible, got {g1['eligible']}"
    g2 = validate_success(api.create_geo_check(
        acct["id"], f.geo_check_payload("INTL", 20), make_bettor_headers(acct["id"])), 201)
    assert g2["eligible"] is False, f"INTL is not a permitted betting state, got {g2['eligible']}"


# ===========================================================================
# Corner/entities/geocheck_vpn_suspected_marks_ineligible
# ===========================================================================
def test_geocheck_vpn_suspected_is_ineligible(api):
    """PRD §3.4: "eligible is true only when the detected state is one of the
    permitted betting states, the accuracy radius is at most the maximum permitted
    accuracy, and the VPN-suspected flag is false".

    Permitted state NJ but is_vpn_suspected true → eligible false.

    Design: Corner/entities/geocheck_vpn_suspected_marks_ineligible
    """
    acct = fx.register_account()
    g = validate_success(api.create_geo_check(
        acct["id"], f.geo_check_payload("NJ", 20, is_vpn_suspected=True),
        make_bettor_headers(acct["id"])), 201)
    assert g["eligible"] is False, f"VPN-suspected must be ineligible, got {g['eligible']}"


# ===========================================================================
# Corner/entities/list_accounts_paginated_envelope
# ===========================================================================
def test_list_accounts_paginated_envelope(api):
    """PRD §2.3: "The meta block of every list response carries the pagination
    fields limit, offset, total_count, and has_more, where total_count reflects
    the full count of matching records before the page window is applied, and
    has_more is true when records beyond the current window remain."

    Two accounts, limit 1 → total_count 2, has_more true.

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    fx.register_account()
    fx.register_account(residence_state="NY")
    data, meta = validate_paginated(api.list_accounts(
        TEST_USERS["compliance_officer_headers"], {"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more should be true with limit 1, got {meta['has_more']}"
    assert len(data) == 1, f"page window of 1 should return 1 record, got {len(data)}"


# ===========================================================================
# Corner/entities/deposit_returns_ledgerentry_with_signed_amount
# ===========================================================================
def test_deposit_returns_positive_cash_ledger_entry(api):
    """PRD §3.3: "A successful deposit appends a positive DEPOSIT ledger entry to
    the CASH bucket, raising both cash_balance_cents and lifetime_deposits_cents".
    PRD §2.7: "Each LedgerEntry records a signed amount_cents — negative for debits
    ... positive for credits".

    Design: Corner/entities/deposit_returns_ledgerentry_with_signed_amount
    """
    acct, v = fx.create_verified_bettor()
    entry = validate_success(api.create_deposit(
        acct["id"], f.deposit_payload(30000, v), make_bettor_headers(acct["id"])), 201)
    assert entry["entry_type"] == "DEPOSIT", f"got {entry['entry_type']}"
    assert entry["bucket"] == "CASH", f"got {entry['bucket']}"
    assert entry["amount_cents"] == 30000, f"got {entry['amount_cents']}"


# ===========================================================================
# Corner/state_machines/kyc_decision_on_already_verified_returns_invalid_state
# ===========================================================================
def test_second_kyc_verify_returns_invalid_state(api):
    """PRD §3.1: "verifying advances kyc_status from PENDING to VERIFIED".
    PRD §2.9: "the target must already be in a valid originating state for that
    transition; otherwise the request is rejected with ERR_INVALID_STATE."

    A second VERIFY on an already-VERIFIED account (no longer PENDING) →
    ERR_INVALID_STATE.

    Design: Corner/state_machines/kyc_decision_on_already_verified_returns_invalid_state
    """
    acct = fx.register_account()
    verified = fx.verify_kyc(acct["id"], acct["version"])
    resp = api.kyc_decision(
        acct["id"], f.kyc_decision_payload("VERIFY", verified["version"]),
        TEST_USERS["compliance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner/state_machines/self_excluded_is_terminal_no_rg_control_advances
# ===========================================================================
def test_self_excluded_terminal_blocks_cooling_off(api):
    """PRD §3.1: "rg_status ... may move to COOLING_OFF or to SELF_EXCLUDED, the
    latter being terminal and irreversible."
    PRD §3.2: "either way rg_status moves to SELF_EXCLUDED and never moves again."

    After SELF_EXCLUDED, a COOLING_OFF rg-control attempt → ERR_INVALID_STATE.

    Design: Corner/state_machines/self_excluded_is_terminal_no_rg_control_advances
    """
    acct = fx.register_account()
    validate_success(api.create_rg_control(
        acct["id"], f.rg_control_payload("SELF_EXCLUSION", acct["version"]),
        TEST_USERS["compliance_officer_headers"]), 201)
    v1 = fx.get_account(acct["id"], TEST_USERS["compliance_officer_headers"])["version"]
    resp = api.create_rg_control(
        acct["id"], f.rg_control_payload("COOLING_OFF", v1, duration_days=7),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner/state_machines/cooling_off_auto_clears_when_clock_passes_until
# ===========================================================================
def test_cooling_off_auto_clears_when_clock_passes_until(api):
    """PRD §3.2: "The freeze is self-clearing: when the clock reaches or passes
    cooling_off_until, the next read of the account ... transitions rg_status from
    COOLING_OFF back to ACTIVE and clears cooling_off_until to null."

    COOLING_OFF for 7 days (until 2026-01-08); advancing the clock to 2026-01-10
    and reading the account re-evaluates rg_status to ACTIVE and clears
    cooling_off_until.

    Design: Corner/state_machines/cooling_off_auto_clears_when_clock_passes_until
    """
    acct = fx.register_account()
    fx.set_rg_control(acct["id"], "COOLING_OFF", acct["version"], duration_days=7)
    fx.set_clock("2026-01-10T00:00:00Z")
    data = validate_success(api.get_account(acct["id"], make_bettor_headers(acct["id"])), 200)
    assert data["rg_status"] == "ACTIVE", f"cooling-off should self-clear to ACTIVE, got {data['rg_status']}"
    assert data["cooling_off_until"] is None, (
        f"cooling_off_until should clear to null, got {data['cooling_off_until']}")


# ===========================================================================
# Corner/state_machines/market_reopen_blocked_when_event_live
# ===========================================================================
def test_market_reopen_while_event_live_returns_event_locked(api):
    """PRD §3.6: "Reopening a SUSPENDED market back to OPEN is conditional: it is
    allowed only while the event is still SCHEDULED — otherwise the reopen is
    rejected with ERR_EVENT_LOCKED".

    Taking the event LIVE suspends the market; reopening it while the event is LIVE
    → ERR_EVENT_LOCKED.

    Design: Corner/state_machines/market_reopen_blocked_when_event_live
    """
    ev = fx.create_event(sport="NBA")
    mkt = fx.create_market(ev["id"], market_type="MONEYLINE", liability_cap_cents=9_000_000)
    fx.take_event_live(ev["id"])  # suspends the market
    resp = api.set_market_status(mkt["id"], {"to": "OPEN"}, fx.OPS)
    validate_error(resp, ApiErrorId.ERR_EVENT_LOCKED.value)


# ===========================================================================
# Corner/calculations/wr_min_odds_floor_excludes_short_priced_bet
# ===========================================================================
def test_wr_min_odds_floor_excludes_short_priced_bet(api):
    """PRD §3.11: "it qualifies only if its combined_decimal_odds meets the
    promotion's minimum-odds floor: the min_odds_american is converted to its
    decimal form and the bet's combined decimal odds must be at or above that
    floor (the boundary is inclusive)."

    Promotion min_odds_american -200 (decimal 1.5); a settled bet at -250 (decimal
    1.4 < 1.5) contributes 0, leaving progress 0 and grant ACTIVE.

    Design: Corner/calculations/wr_min_odds_floor_excludes_short_priced_bet
    """
    promo = fx.create_promotion("WRF", bonus_cents=2000, wagering_multiplier=5,
                                min_odds_american=-200, max_claims=10)
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    grant = fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])

    ev, mkt, sel = fx.create_board(selection_name="HOME", american_odds=-250,
                                   liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 4000, [sel["id"]], v,
                 stake_bucket="CASH", bonus_grant_id=grant["id"])
    fx.take_event_live(ev["id"])
    fx.settle_event(ev["id"], home_score=110, away_score=90)  # HOME -250 WON, but odds below floor

    grant_data = validate_success(api.get_bonus_grant(grant["id"], make_bettor_headers(acct["id"])), 200)
    assert grant_data["wagering_progress_cents"] == 0, (
        f"-250 is below the -200 floor → 0 contribution, got {grant_data['wagering_progress_cents']}")
    assert grant_data["status"] == "ACTIVE", f"grant should stay ACTIVE, got {grant_data['status']}"


# ===========================================================================
# Corner/validations/withdrawal_blocked_by_unmet_wagering_requirement
# ===========================================================================
def test_withdrawal_blocked_by_unmet_wagering_requirement(api):
    """PRD §3.3: "a withdrawal is blocked while the account holds any ACTIVE
    BonusGrant whose wagering requirement is not yet met — funds cannot be
    withdrawn out from under an unmet bonus obligation — and such an attempt is
    rejected with ERR_WR_NOT_MET."

    Verified bettor with cash 100000 and an ACTIVE unmet grant attempts a
    withdrawal → ERR_WR_NOT_MET.

    Design: Corner/validations/withdrawal_blocked_by_unmet_wagering_requirement
    """
    promo = fx.create_promotion("WRW", bonus_cents=2000, wagering_multiplier=5,
                                min_odds_american=-200, max_claims=10)
    acct, v = fx.create_funded_bettor(deposit_cents=100_000, geo=False)
    fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    resp = api.create_withdrawal(
        acct["id"], f.withdrawal_payload(10000, v), make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_WR_NOT_MET.value)


# ===========================================================================
# Corner/endpoints/underage_kyc_verify_rejected
# ===========================================================================
def test_underage_kyc_verify_rejected(api):
    """PRD §3.1: "Verification additionally enforces the minimum-age rule: the
    account holder must be at least 21 years old, measured from date_of_birth
    against the current clock date, and an attempt to verify an underage account
    is rejected with ERR_UNDERAGE."

    DOB 2010-01-01 (age 16 at the 2026-01-01 default clock) → ERR_UNDERAGE.

    Design: Corner/endpoints/underage_kyc_verify_rejected
    """
    acct = fx.register_account(date_of_birth="2010-01-01")
    resp = api.kyc_decision(
        acct["id"], f.kyc_decision_payload("VERIFY", acct["version"]),
        TEST_USERS["compliance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNDERAGE.value)


# ===========================================================================
# Corner/endpoints/settlement_agent_sod_conflict_with_market_setter
# ===========================================================================
def test_settlement_agent_sod_conflict_with_market_setter(api):
    """PRD §3.10: "if the posting agent's identifier matches any set_by recorded
    on a market of that event, the post is rejected with ERR_SOD_CONFLICT."

    The market is created by TradingOps id 'opsA'; a SettlementAgent posting the
    result with the SAME id 'opsA' → ERR_SOD_CONFLICT.

    Design: Corner/endpoints/settlement_agent_sod_conflict_with_market_setter
    """
    ops_a = make_trading_ops_headers("opsA")
    ev = fx.create_event(ops_headers=ops_a, sport="NBA")
    fx.create_market(ev["id"], ops_headers=ops_a, market_type="MONEYLINE",
                     liability_cap_cents=9_000_000)
    validate_success(api.set_event_status(ev["id"], {"to": "LIVE"}, ops_a), 200)
    resp = api.post_event_result(
        ev["id"], {"home_score": 100, "away_score": 90}, make_settlement_agent_headers("opsA"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT.value)


# ===========================================================================
# Corner/endpoints/line_move_does_not_change_existing_leg_snapshot
# ===========================================================================
def test_line_move_does_not_change_existing_leg_snapshot(api):
    """PRD §3.5: "the selection's stored American and decimal odds update, but any
    BetLeg already snapshotted at the old price keeps its captured odds untouched."
    PRD §3.7: "the odds_at_placement copied from the selection's current American
    odds (immune to later line moves)".

    A bet placed @-150, then a re-price to +120, leaves the BetLeg.odds_at_placement
    at -150 and the bet's combined_decimal_odds at 1.6667.

    Design: Corner/endpoints/line_move_does_not_change_existing_leg_snapshot
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="HOME", american_odds=-150,
                                   liability_cap_cents=90_000_000)
    bet = fx.place_bet(acct["id"], "SINGLE", 5000, [sel["id"]], v)
    validate_success(api.reprice_selection(sel["id"], f.reprice_payload(120), fx.OPS), 200)

    legs, _ = validate_paginated(api.list_bet_legs_of_bet(bet["id"], make_bettor_headers(acct["id"])))
    assert len(legs) == 1, f"expected one leg, got {len(legs)}"
    assert legs[0]["odds_at_placement"] == -150, (
        f"snapshot must stay -150 after the line move, got {legs[0]['odds_at_placement']}")
    bet_data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert bet_data["combined_decimal_odds"] == 1.6667, (
        f"combined odds unchanged by the line move, got {bet_data['combined_decimal_odds']}")


# ===========================================================================
# Corner/errors/promo_already_claimed_rejected
# ===========================================================================
def test_second_claim_of_same_promotion_rejected(api):
    """PRD §3.11: "the account must not already hold a grant for that promotion,
    any failure of which is rejected with ERR_PROMO_UNAVAILABLE."

    A second bonus-claim of the same promotion by the same account →
    ERR_PROMO_UNAVAILABLE.

    Design: Corner/errors/promo_already_claimed_rejected
    """
    promo = fx.create_promotion("PRX", bonus_cents=2000, wagering_multiplier=5, max_claims=10)
    acct, v = fx.create_verified_bettor()
    fx.deposit(acct["id"], 100_000, v)
    v = fx.get_account(acct["id"])["version"]
    fx.claim_bonus(acct["id"], promo["id"], v)
    v = fx.get_account(acct["id"])["version"]
    resp = api.claim_bonus(
        acct["id"], f.bonus_claim_payload(promo["id"], v), make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_PROMO_UNAVAILABLE.value)


# ===========================================================================
# Corner/errors/cashout_unavailable_when_market_suspended
# ===========================================================================
def test_cashout_when_market_suspended_returns_unavailable(api):
    """PRD §3.9: "no leg's market may be SUSPENDED nor its event LIVE or SETTLED,
    any of which yields ERR_CASHOUT_UNAVAILABLE."

    The bet's market is manually SUSPENDED while the event is still SCHEDULED;
    cashing out → ERR_CASHOUT_UNAVAILABLE.

    Design: Corner/errors/cashout_unavailable_when_market_suspended
    """
    acct, ev, mkt, sel, bet, v = fx.setup_single_bet(stake_cents=5000, american_odds=200,
                                                      liability_cap_cents=90_000_000)
    validate_success(api.set_market_status(mkt["id"], {"to": "SUSPENDED"}, fx.OPS), 200)
    v = fx.get_account(acct["id"])["version"]
    resp = api.cash_out_bet(bet["id"], {"expected_account_version": v}, make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_CASHOUT_UNAVAILABLE.value)


# ===========================================================================
# Corner/rbac/bettor_cannot_post_event_result
# ===========================================================================
def test_bettor_cannot_post_event_result(api):
    """PRD §4 (endpoint table): POST /events/{id}/result is authorized for
    SettlementAgent only.
    PRD §2.1: "A request whose role is not permitted to perform the requested
    operation is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/bettor_cannot_post_event_result
    """
    ev = fx.create_event(sport="NBA")
    fx.create_market(ev["id"], market_type="MONEYLINE", liability_cap_cents=9_000_000)
    fx.take_event_live(ev["id"])
    resp = api.post_event_result(
        ev["id"], {"home_score": 100, "away_score": 90}, make_bettor_headers("someone"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Corner/rbac/bettor_cannot_act_on_other_accounts_deposit
# ===========================================================================
def test_bettor_cannot_deposit_to_other_account(api):
    """PRD §2.1: "A Bettor may act only on their own account and their own bets,
    deposits, withdrawals, geo-checks, cooling-off and limit controls, and bonus
    claims; an attempt to act on another account's resources is rejected with
    ERR_FORBIDDEN."

    Bettor A (X-User-ID = acctA) depositing to account B → ERR_FORBIDDEN.

    Design: Corner/rbac/bettor_cannot_act_on_other_accounts_deposit
    """
    acct_a, _ = fx.create_verified_bettor()
    acct_b, vb = fx.create_verified_bettor()
    resp = api.create_deposit(
        acct_b["id"], f.deposit_payload(5000, vb), make_bettor_headers(acct_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Corner/rbac/trading_ops_cannot_decide_kyc
# ===========================================================================
def test_trading_ops_cannot_decide_kyc(api):
    """PRD §4 (endpoint table): POST /accounts/{id}/kyc-decision is authorized for
    ComplianceOfficer only.
    PRD §3.1: "Identity verification is the exclusive province of the compliance
    team."

    Design: Corner/rbac/trading_ops_cannot_decide_kyc
    """
    acct = fx.register_account()
    resp = api.kyc_decision(
        acct["id"], f.kyc_decision_payload("VERIFY", acct["version"]),
        TEST_USERS["trading_ops_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Corner/rbac/missing_auth_headers_unauthenticated
# ===========================================================================
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request other than self-service account registration and
    the health probe must carry two HTTP headers: X-User-ID ... and X-User-Role
    ... A request that omits either header on a protected endpoint is rejected with
    ERR_UNAUTHENTICATED."

    A protected GET /accounts call with no auth headers → ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_accounts(NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
