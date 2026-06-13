"""Settle-up lifecycle, confirm fiscal/OCC validations, and self-settlement.

Translates queue-A boundary_precision_check (zero-debt), priority_pair (frozen
beats fiscal), cross_entity_state_dependency (frozen blocks confirm), plus
queue-B settlement corner instances (self-settlement, exceeds-debt, OCC stale,
cancelled-then-confirm invalid state).
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    build_household_with_members,
    post_expense,
    propose_settlement,
    current_household_version,
    freeze_household_via_dispute,
    create_settlement_payload,
)

api = api_client


def _household_two_members(names=("M1", "M2"), capacity=3):
    return build_household_with_members(
        api, [{"full_name": n} for n in names],
        listing_overrides={"capacity": capacity},
    )


def test_self_settlement_rejected():
    """PRD §3.7: "the two parties must be distinct — a settlement whose `from_profile_id`
    equals its `to_profile_id` is rejected with `ERR_SELF_SETTLEMENT`."

    Design: Corner/validations/self_settlement_rejected
    """
    env = build_household_with_members(api, [{"full_name": "SsM1"}], listing_overrides={"capacity": 3})
    m1 = env["members"][0]
    resp = api.create_settlement(
        create_settlement_payload(env["household"]["id"], m1["id"], m1["id"], 100),
        make_roommate_headers(m1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_SETTLEMENT.value)


def test_confirm_with_zero_debt_rejected():
    """PRD §3.7: "confirming when the debtor has no outstanding debt at all (their
    `net_balance_cents` is zero or positive) is rejected with `ERR_NO_OUTSTANDING_DEBT`."

    No posted expenses -> both members net 0; confirming a 1-cent settlement is rejected.

    Design: Difficulty/boundary_precision_check/settle_up_with_zero_debt_rejected
    """
    env = _household_two_members(("M1.12", "M2.12"))
    m1, m2 = env["members"]
    settlement = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=1)
    hv = current_household_version(api, env)
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_OUTSTANDING_DEBT.value)


def test_confirm_at_zero_debt_boundary_second_arrangement():
    """PRD §3.7: "confirming when the debtor has no outstanding debt at all (their
    `net_balance_cents` is zero or positive) is rejected with `ERR_NO_OUTSTANDING_DEBT`."

    A creditor-side debtor (positive net balance after being paid up front) likewise has
    no outstanding debt: M1 paid an expense so M1's balance is positive; a settlement
    proposing M1 as debtor is rejected at confirm.

    Design: Difficulty/boundary_precision_check/settle_up_with_zero_debt_rejected
    """
    env = _household_two_members(("Z1", "Z2"))
    m1, m2 = env["members"]
    # M1 fronts an expense, so M1 is a creditor (positive balance, no debt).
    post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    settlement = propose_settlement(api, env, debtor=m1, creditor=m2, amount_cents=1)
    hv = current_household_version(api, env)
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_OUTSTANDING_DEBT.value)


def test_confirm_exceeding_debt_rejected():
    """PRD §3.7: "The settlement's `amount_cents` must not exceed the debtor's
    outstanding debt — the absolute value of the debtor's `net_balance_cents` when that
    balance is negative — and an amount that exceeds it is rejected with
    `ERR_SETTLEMENT_EXCEEDS_DEBT`."

    M2 owes 4500; a 5000 settlement exceeds the debt.

    Design: Corner/errors/settlement_exceeds_debt_error_triggerable
    """
    env = _household_two_members(("ExdM1", "ExdM2"))
    m1, m2 = env["members"]
    post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    settlement = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=5000)
    hv = current_household_version(api, env)
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_DEBT.value)


def test_confirm_on_frozen_household_rejected():
    """PRD §2.9: "any ledger-mutating write attempted against a frozen household is
    rejected with `ERR_HOUSEHOLD_FROZEN`. Four operations are gated by this freeze —
    logging a new expense, confirming a settlement, recording a bill payment, and moving
    a member out."

    Design: Difficulty/cross_entity_state_dependency/settlement_confirm_blocked_by_household_frozen
    """
    env = _household_two_members(("M1.fz", "M2.fz"))
    m1, m2 = env["members"]
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    settlement = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=4500)
    hv = current_household_version(api, env)
    # Freeze via a dispute filed by M1 (so M1 the confirming creditor is not self-adjudicating).
    freeze_household_via_dispute(api, env, filer=m1, expense=expense, mediator_id="med-fz")
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN.value)


def test_confirm_on_frozen_household_rejected_within_debt():
    """PRD §3.7: "The household must not be `FROZEN`, and the debtor's membership must be
    in `ACTIVE` or `MOVED_OUT` status."
    PRD §2.9: "While a dispute is being actively reviewed, the household is held in
    `FROZEN`, and the ledger is sealed: any ledger-mutating write attempted against a
    frozen household is rejected with `ERR_HOUSEHOLD_FROZEN`."

    A confirm whose amount (1000) is well within M2's 4500 debt is still rejected because
    the household is FROZEN — the freeze blocks the confirm regardless of fiscal validity.

    Design: Difficulty/cross_entity_state_dependency/settlement_confirm_blocked_by_household_frozen
    """
    env = _household_two_members(("Fb1", "Fb2"))
    m1, m2 = env["members"]
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    settlement = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=1000)
    hv = current_household_version(api, env)
    freeze_household_via_dispute(api, env, filer=m1, expense=expense, mediator_id="med-fb")
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN.value)


def test_frozen_gate_precedes_fiscal_exceeds_debt_check():
    """PRD §2.11: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`), then the frozen-household gate
    (`ERR_HOUSEHOLD_FROZEN`). Only after all of those pass does the system evaluate the
    operation-specific business rules described in Section 3."

    A confirm that is BOTH on a FROZEN household AND exceeds the debt returns
    ERR_HOUSEHOLD_FROZEN (the gate is evaluated before the fiscal rule).

    Design: Difficulty/priority_pair_validation_conflict/frozen_state_beats_settlement_fiscal
    """
    env = _household_two_members(("M1.9", "M2.9"))
    m1, m2 = env["members"]
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    # M2 owes 4500; propose 9999 which exceeds the debt.
    settlement = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=9999)
    hv = current_household_version(api, env)
    freeze_household_via_dispute(api, env, filer=m1, expense=expense, mediator_id="med-pp")
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN.value)


def test_frozen_gate_precedes_no_outstanding_debt_check():
    """PRD §2.11: "then the frozen-household gate (`ERR_HOUSEHOLD_FROZEN`). Only after
    all of those pass does the system evaluate the operation-specific business rules
    described in Section 3."

    A confirm that is BOTH on a FROZEN household AND a debtor with no outstanding debt
    returns ERR_HOUSEHOLD_FROZEN — the freeze gate is evaluated before the fiscal
    no-debt business rule.

    Design: Difficulty/priority_pair_validation_conflict/frozen_state_beats_settlement_fiscal
    """
    env = _household_two_members(("Pp1", "Pp2"))
    m1, m2 = env["members"]
    # Freeze the household via a dispute on an expense filed by M1. The expense also
    # makes M2 a debtor; we use a tiny settlement so the no-debt path is the relevant
    # fiscal rule for the second arrangement.
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    # M1 (the creditor/filer) has a positive balance, so a settlement with M1 as debtor
    # would otherwise hit ERR_NO_OUTSTANDING_DEBT.
    settlement = propose_settlement(api, env, debtor=m1, creditor=m2, amount_cents=1)
    hv = current_household_version(api, env)
    freeze_household_via_dispute(api, env, filer=m1, expense=expense, mediator_id="med-pp2")
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_FROZEN.value)


def test_confirm_with_stale_household_version_rejected():
    """PRD §2.10: "If that value does not equal the household's current `version` —
    because some other ledger write advanced the household since the client read it —
    the confirm is rejected with `ERR_STALE_HOUSEHOLD_VERSION` and HTTP status 412."

    Two settlements share one observed version; confirming the first bumps the version,
    so confirming the second with the stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_household_version_on_confirm
    """
    env = build_household_with_members(
        api, [{"full_name": "OccM1"}, {"full_name": "OccM2"}, {"full_name": "OccM3"}],
        listing_overrides={"capacity": 4},
    )
    m1, m2, m3 = env["members"]
    post_expense(api, env, payer=m1, participants=[m1, m2, m3], total_amount_cents=9000)
    settle_a = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=3000)
    settle_b = propose_settlement(api, env, debtor=m3, creditor=m1, amount_cents=3000)
    hv = current_household_version(api, env)

    creditor = make_roommate_headers(m1["id"])
    validate_success(api.confirm_settlement(settle_a["id"], {"expected_household_version": hv}, creditor))
    resp = api.confirm_settlement(settle_b["id"], {"expected_household_version": hv}, creditor)
    validate_error(resp, ApiErrorId.ERR_STALE_HOUSEHOLD_VERSION.value)


def test_confirm_cancelled_settlement_is_invalid_state():
    """PRD §3.7: "The lifecycle runs `PROPOSED` to `CONFIRMED`, `DISPUTED`, or
    `CANCELLED`, where `CONFIRMED` and `CANCELLED` are terminal and `DISPUTED` can cycle
    back to `PROPOSED`."
    PRD §3.2: "an action requested from a state where it is not defined is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settlement_cancel_then_confirm_invalid_state
    """
    env = _household_two_members(("ScanM1", "ScanM2"))
    m1, m2 = env["members"]
    post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)
    settlement = propose_settlement(api, env, debtor=m2, creditor=m1, amount_cents=4500)
    validate_success(api.cancel_settlement(settlement["id"], make_roommate_headers(m2["id"])))
    hv = current_household_version(api, env)
    resp = api.confirm_settlement(
        settlement["id"], {"expected_household_version": hv}, make_roommate_headers(m1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
