"""Tax-loss harvest: screening, the execute cascade, reinvestment, branching,
and validation-priority conflicts.

Queue A: non_linear_state_machine/harvest_branch_execute_vs_reject_vs_reverse,
cross_entity_state_dependency/harvest_execute_blocked_by_frozen_account,
priority_pair_validation_conflict/forbidden_beats_invalid_state_on_harvest_reject,
priority_pair_validation_conflict/account_not_operable_beats_correlation_on_frozen_harvest_execute.
Queue B (validations, calculations, consistency_model): harvest_on_gain_lot_returns_not_a_loss,
harvest_replacement_substantially_identical_rejected, harvest_replacement_delisted_rejected,
harvest_reinvestment_floor_shares_and_cash_remainder, harvest_cascade_visible_in_same_request.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_model,
    create_security,
    create_active_account,
    open_tax_lot,
    get_account,
    get_tax_lot,
    get_harvest,
    setup_proposed_harvest,
    setup_executed_harvest,
    propose_harvest,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ─── harvest_branch_execute_vs_reject_vs_reverse ────────────────────
def test_reject_proposed_harvest_no_ledger_change(api):
    """PRD §3.7: "A proposed harvest may be rejected by a compliance operator before it executes; rejection moves the event from `PROPOSED` to `REJECTED` with no ledger changes."

    Design: Difficulty/non_linear_state_machine/harvest_branch_execute_vs_reject_vs_reverse
    """
    s = setup_proposed_harvest(
        "2026-05-01T00:00:00.000Z", "branch@x.com", src_ticker="CCC", repl_ticker="DDD"
    )
    rejected = get_success_data(api.reject_harvest_event(s["harvest"]["id"], COMPLIANCE))
    assert rejected["status"] == "REJECTED"
    # No ledger change: the source lot stays OPEN.
    assert get_tax_lot(s["source_lot"]["id"])["status"] == "OPEN"


def test_execute_rejected_harvest_returns_invalid_state(api):
    """PRD §3.4: "Execution is allowed only on an event still in `PROPOSED` status (otherwise `ERR_INVALID_STATE`)".

    Design: Difficulty/non_linear_state_machine/harvest_branch_execute_vs_reject_vs_reverse
    """
    s = setup_proposed_harvest(
        "2026-05-02T00:00:00.000Z", "branch2@x.com", src_ticker="CC2", repl_ticker="DD2"
    )
    get_success_data(api.reject_harvest_event(s["harvest"]["id"], COMPLIANCE))
    res = api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── harvest_execute_blocked_by_frozen_account ──────────────────────
def test_execute_harvest_on_frozen_account_blocked(api):
    """PRD §3.4: "Proposal and execution both require the owning account to be operable — its `status` must be `ACTIVE` or `REBALANCE_DUE`; an account that is `FROZEN`, `CLOSED`, or `PENDING_PROFILE` cannot be harvested, and the attempt is rejected with `ERR_ACCOUNT_NOT_OPERABLE`."

    Design: Difficulty/cross_entity_state_dependency/harvest_execute_blocked_by_frozen_account
    """
    s = setup_proposed_harvest(
        "2026-05-10T00:00:00.000Z", "xdep1@x.com", src_ticker="KKK", repl_ticker="LLL"
    )
    get_success_data(api.freeze_account(s["account"]["id"], COMPLIANCE))
    res = api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_OPERABLE.value)


def test_frozen_account_blocked_harvest_leaves_source_lot_open(api):
    """PRD §3.4: "an account that is `FROZEN`, `CLOSED`, or `PENDING_PROFILE` cannot be harvested, and the attempt is rejected with `ERR_ACCOUNT_NOT_OPERABLE`." PRD
    §3.4: when execution is rejected the cascade that would close the source lot
    never runs — "First, the source lot is closed" happens only "When every
    screen passes".

    Design: Difficulty/cross_entity_state_dependency/harvest_execute_blocked_by_frozen_account
    """
    s = setup_proposed_harvest(
        "2026-05-11T00:00:00.000Z", "xdep1b@x.com", src_ticker="KK2", repl_ticker="LL2"
    )
    get_success_data(api.freeze_account(s["account"]["id"], COMPLIANCE))
    api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    assert get_tax_lot(s["source_lot"]["id"])["status"] == "OPEN"


# ─── forbidden_beats_invalid_state_on_harvest_reject ────────────────
def test_advisor_reject_executed_harvest_returns_forbidden(api):
    """PRD §2.10: "Authorization is checked next: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`. ... Only after these generic gates does the server evaluate state-machine eligibility and the domain-specific business rules described in Section 3".

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_harvest_reject
    """
    # Reject is Compliance-only; calling it as Advisor on an EXECUTED harvest
    # violates both authorization (priority 2) and state (priority 6).
    s = setup_executed_harvest(
        "2026-04-15T00:00:00.000Z", "pri1@x.com", src_ticker="GGG", repl_ticker="HHH"
    )
    res = api.reject_harvest_event(s["harvest"]["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_advisor_reject_executed_harvest_leaves_it_executed(api):
    """PRD §2.10: "Authorization is checked next: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`." PRD §3.7: "rejection moves the event from `PROPOSED` to `REJECTED` with no ledger changes." A forbidden caller never transitions the event.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_harvest_reject
    """
    s = setup_executed_harvest(
        "2026-04-16T00:00:00.000Z", "pri1b@x.com", src_ticker="GG2", repl_ticker="HH2"
    )
    api.reject_harvest_event(s["harvest"]["id"], ADVISOR)
    assert get_harvest(s["harvest"]["id"])["status"] == "EXECUTED"


# ─── account_not_operable_beats_correlation_on_frozen_harvest_execute ─
def test_frozen_account_beats_correlation_on_execute(api):
    """PRD §2.10: "an account's operability gate and the account-status-versus-transition checks precede the wash-sale and lot-eligibility checks".

    Design: Difficulty/priority_pair_validation_conflict/account_not_operable_beats_correlation_on_frozen_harvest_execute
    """
    # Replacement is highly correlated (0.98 > 0.95) AND the account is FROZEN:
    # operability gate (priority 7) precedes the correlation check (priority 9).
    s = setup_proposed_harvest(
        "2026-04-20T00:00:00.000Z",
        "pri2@x.com",
        src_ticker="III",
        repl_ticker="JJJ",
        correlation=0.98,
    )
    get_success_data(api.freeze_account(s["account"]["id"], COMPLIANCE))
    res = api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_OPERABLE.value)


def test_unfrozen_too_correlated_harvest_then_surfaces_correlation_error(api):
    """PRD §3.4: "the absolute value of the correlation between the source lot's security and the replacement security must be at most the maximum replacement correlation the platform permits, which is 0.95; a replacement whose absolute correlation exceeds 0.95 is rejected with `ERR_REPLACEMENT_TOO_CORRELATED` because it would be a wash-sale-equivalent substitute."

    Design: Difficulty/priority_pair_validation_conflict/account_not_operable_beats_correlation_on_frozen_harvest_execute
    """
    # With the operability gate satisfied (ACTIVE account), the lower-priority
    # correlation check is the one that now fires for the 0.98 replacement.
    s = setup_proposed_harvest(
        "2026-04-21T00:00:00.000Z",
        "pri2b@x.com",
        src_ticker="II2",
        repl_ticker="JJ2",
        correlation=0.98,
    )
    res = api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_REPLACEMENT_TOO_CORRELATED.value)


# ─── Queue B harvest validations ────────────────────────────────────
def test_harvest_on_gain_lot_returns_not_a_loss(api):
    """PRD §3.4: "The lot must genuinely be a loss lot — its `unrealized_gain_cents` must be less than zero — or execution is rejected with `ERR_NOT_A_LOSS_LOT`."

    Design: Corner/validations/harvest_on_gain_lot_returns_not_a_loss
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="GL", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    a = create_security(
        "GL1", "US_EQUITY", 10000, correlated_with=[{"ticker": "GL2", "correlation": 0.05}]
    )
    b = create_security(
        "GL2", "US_EQUITY", 4000, correlated_with=[{"ticker": "GL1", "correlation": 0.05}]
    )
    acct = create_active_account("gainlot@x.com")
    # 5sh cost 40000, price 10000 -> mkt 50000 -> unrealized +10000 (a gain lot).
    gain_lot = open_tax_lot(acct["id"], a["id"], 5, 40000)
    acct_v = get_account(acct["id"])["version"]
    harvest = propose_harvest(acct["id"], gain_lot["id"], b["id"], acct_v)
    res = api.execute_harvest_event(harvest["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_NOT_A_LOSS_LOT.value)
    assert get_tax_lot(gain_lot["id"])["status"] == "OPEN"


def test_harvest_replacement_same_security_rejected(api):
    """PRD §3.4: "The replacement security must not be the same security as the source lot's security, since selling and immediately rebuying the identical security is the very wash sale the platform exists to avoid; an identical replacement is rejected with `ERR_SUBSTANTIALLY_IDENTICAL`."

    Design: Corner/validations/harvest_replacement_substantially_identical_rejected
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="SI", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    a = create_security("SI1", "US_EQUITY", 10000)
    acct = create_active_account("samesec@x.com")
    lot = open_tax_lot(acct["id"], a["id"], 5, 60000)  # loss lot
    acct_v = get_account(acct["id"])["version"]
    harvest = propose_harvest(acct["id"], lot["id"], a["id"], acct_v)  # replacement == source sec
    res = api.execute_harvest_event(harvest["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_SUBSTANTIALLY_IDENTICAL.value)


def test_harvest_replacement_delisted_rejected(api):
    """PRD §3.4: "The replacement security must still be active, or the harvest is rejected with `ERR_SECURITY_DELISTED`."

    Design: Corner/validations/harvest_replacement_delisted_rejected
    """
    s = setup_proposed_harvest(
        "2026-05-01T00:00:00.000Z", "delisted@x.com", src_ticker="DL1", repl_ticker="DL2"
    )
    get_success_data(api.delist_security(s["repl_sec"]["id"], COMPLIANCE))
    res = api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_SECURITY_DELISTED.value)


def test_harvest_reinvestment_floor_shares_and_cash_remainder(api):
    """PRD §3.4: "a new `OPEN` tax lot in the replacement security whose `quantity` is the proceeds in cents divided by the replacement security's `price_cents`, taking the whole-number floor, and whose `cost_basis_cents` is that quantity multiplied by the price; whatever proceeds remain after buying whole shares are credited back to the account's `cash_balance_cents` as automatic reinvestment".

    Design: Corner/calculations/harvest_reinvestment_floor_shares_and_cash_remainder
    """
    s = setup_executed_harvest(
        "2026-05-01T00:00:00.000Z", "reinv@x.com", src_ticker="RI1", repl_ticker="RI2"
    )
    repl_lot_id = s["harvest"]["replacement_lot_id"]
    repl_lot = get_tax_lot(repl_lot_id)
    # proceeds 50000 / price 4000 -> floor 12 shares, cost 48000, remainder 2000.
    assert repl_lot["quantity"] == 12
    assert repl_lot["cost_basis_cents"] == 48000
    assert get_account(s["account"]["id"])["cash_balance_cents"] == 2000


def test_harvest_cascade_visible_in_execute_response(api):
    """PRD §3.4: "the event's `realized_loss_cents` records the positive magnitude of that loss, namely cost basis minus proceeds." PRD §3.4: "the new lot's `id` becomes the event's `replacement_lot_id`." PRD §3.4: "the event's `disallowed_loss_cents` records the disallowed magnitude, which is 0 when the replacement and window are clean."

    Design: Corner/consistency_model/harvest_cascade_visible_in_same_request
    """
    s = setup_proposed_harvest(
        "2026-05-01T00:00:00.000Z", "immediate@x.com", src_ticker="IM1", repl_ticker="IM2"
    )
    res = api.execute_harvest_event(s["harvest"]["id"], ADVISOR)
    executed = validate_success(res, 200)
    assert executed["status"] == "EXECUTED"
    assert executed["realized_loss_cents"] == 10000
    assert executed["disallowed_loss_cents"] == 0
    assert executed["replacement_lot_id"] is not None
