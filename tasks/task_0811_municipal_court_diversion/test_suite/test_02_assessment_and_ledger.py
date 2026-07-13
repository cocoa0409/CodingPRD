"""Fine assessment, payment waterfall, installment plans, and reversals.

Translates queue-A instances (dual_variant_calc, combinatorial_formula,
compensating_invariant / payment reverse) and queue-B calculation/validation/OCC
instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, SURCHARGE_CAP,
    create_diversion_payload, create_installment_plan_payload, create_payment_payload,
    setup_arraigned_case, setup_granted_diversion,
    fetch_ledger, refetch_ledger,
    TEST_USERS,
)

CASHIER = "cashier_headers"


# ---------------------------------------------------------------------------
# Rule 1 — dual-variant assessment (provisional vs final) on the LedgerAccount.
# ---------------------------------------------------------------------------

def test_provisional_assessment_on_plea(api):
    """PRD §3.4: "The provisional assessment works as follows. First, a subtotal
    is formed by summing, over every charge on the case, that charge's
    base_fine_amount with no severity multiplier applied."

    Design: Difficulty/dual_variant_calc/assessment_provisional_vs_final_on_ledger_account
    """
    ctx = setup_arraigned_case(api, charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}])
    ledger = ctx["ledger_account"]
    # subtotal 200 -> rate 0.30 -> surcharge 60 -> 200 + 50 court fee + 60 = 310.00
    assert ledger["assessed_amount"] == 310.00
    assert ledger["status"] == "PROVISIONAL"


def test_final_assessment_on_grant(api):
    """PRD §3.5: "First, each charge's contribution to the subtotal is its
    base_fine_amount multiplied by the severity multiplier — 1.0 for an INFRACTION
    and 1.5 for a MISDEMEANOR."
    PRD §3.5: "Second, the agreement's program_fee is added to the final total."

    Design: Difficulty/dual_variant_calc/assessment_provisional_vs_final_on_ledger_account
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 10, "program_fee": 100},
    )
    ledger = ctx["ledger_account"]
    # subtotal 300 -> surcharge 90 -> 300 + 50 + 90 = 440 + program_fee 100 = 540.00
    assert ledger["assessed_amount"] == 540.00
    assert ledger["status"] == "ASSESSED"
    assert ledger["assessed_amount"] != 310.00


# ---------------------------------------------------------------------------
# Rule 2 — combinatorial: tiered surcharge with cap; installment rounding.
# ---------------------------------------------------------------------------

def test_surcharge_cap_applied_final_assessment(api):
    """PRD §3.4: "The surcharge is the rate multiplied by the subtotal, rounded
    half up to two decimal places, and then capped so it never exceeds 150
    dollars — the rounding happens first and the cap is applied to the rounded
    figure."

    Design: Difficulty/combinatorial_formula/assessment_tiered_surcharge_with_cap
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 400}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    ledger = ctx["ledger_account"]
    # subtotal 600 -> rate 0.35 -> 210 capped to 150 -> 600 + 50 + 150 + 100 = 900.00
    assert ledger["assessed_amount"] == 900.00


def test_surcharge_component_equals_cap(api):
    """PRD §3.5: "The surcharge tiering, the half-up rounding of the surcharge,
    and the 150-dollar cap are applied to this new subtotal exactly as before,
    and the flat court fee of 50 dollars is added."

    Design: Difficulty/combinatorial_formula/assessment_tiered_surcharge_with_cap
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 400}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    ledger = ctx["ledger_account"]
    # surcharge = assessed - subtotal(600) - court_fee(50) - program_fee(100)
    surcharge = round(ledger["assessed_amount"] - 600 - 50 - 100, 2)
    assert surcharge == SURCHARGE_CAP == 150.00


def _plan_for_540(api):
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    account = ctx["ledger_account"]
    acct = refetch_ledger(api, account["id"])
    plan = validate_success(
        api.create_installment_plan(
            account["id"], create_installment_plan_payload(7, acct["version"]),
            TEST_USERS[CASHIER]),
        201,
    )
    return plan


def test_installment_floor_and_final_remainder(api):
    """PRD §3.7: "That total is divided by the number of installments using floor
    division to give the per-installment cents; the installment_amount carried by
    each of the first installments is that floored figure expressed in dollars.
    The remainder ... is added onto the floored figure to form the
    final_installment_amount, so the last installment absorbs the entire rounding
    remainder rather than spreading it."

    Design: Difficulty/combinatorial_formula/installment_rounding_last_absorbs_remainder
    """
    plan = _plan_for_540(api)
    # 54000 cents / 7 -> floor 7714 (77.14); remainder 2 -> final 77.16
    assert plan["installment_amount"] == 77.14
    assert plan["final_installment_amount"] == 77.16


def test_installment_amounts_reconstruct_balance(api):
    """PRD §3.7: "The schedule is computed in whole cents to avoid rounding drift."
    PRD §3.7: "the last installment absorbs the entire rounding remainder rather
    than spreading it."

    Design: Difficulty/combinatorial_formula/installment_rounding_last_absorbs_remainder
    """
    plan = _plan_for_540(api)
    total = round(6 * plan["installment_amount"] + plan["final_installment_amount"], 2)
    assert total == 540.00


# ---------------------------------------------------------------------------
# Rule 9 — compensating invariant: payment reversal preserves ledger balance.
# ---------------------------------------------------------------------------

def _paid_then_reversible(api):
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    account = ctx["ledger_account"]
    payment = validate_success(
        api.create_payment(account["id"], create_payment_payload(200.00), TEST_USERS[CASHIER]), 201)
    return account, payment


def test_payment_reverse_restores_balance(api):
    """PRD §3.7: "Reversal sets the payment's reversed flag to true, which drops
    its amount out of collected_amount, and the account's balance is recomputed."

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_ledger_balance
    """
    account, payment = _paid_then_reversible(api)
    validate_success(api.reverse_payment(payment["id"], TEST_USERS[CASHIER]), 200)
    ledger = refetch_ledger(api, account["id"])
    assert ledger["balance"] == 540.00
    assert ledger["collected_amount"] == 0.00


def test_payment_reverse_balance_invariant(api):
    """PRD §2.10: "on a ledger account, collected_amount is the sum of amount over
    the account's payments whose reversed flag is false, and balance is
    assessed_amount minus collected_amount."

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_ledger_balance
    """
    account, payment = _paid_then_reversible(api)
    validate_success(api.reverse_payment(payment["id"], TEST_USERS[CASHIER]), 200)
    ledger = refetch_ledger(api, account["id"])
    # No non-reversed payments remain -> collected 0, balance == assessed.
    assert ledger["collected_amount"] == 0.00
    assert ledger["balance"] == ledger["assessed_amount"] - ledger["collected_amount"]


# ---------------------------------------------------------------------------
# Queue B — payment waterfall, overpayment, installment count/minimum, OCC.
# ---------------------------------------------------------------------------

def test_payment_waterfall_partial_allocation(api):
    """PRD §3.7: "the buckets are filled in the order fines first, then court fee,
    then state surcharge, then program fee. Starting from the full payment amount
    as the remaining pool, each bucket in turn absorbs the smaller of the
    remaining pool and that bucket's outstanding amount."

    Design: Corner/calculations/payment_waterfall_partial_allocation
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    account = ctx["ledger_account"]
    # fines bucket = 300; a 250 payment fills only fines.
    payment = validate_success(
        api.create_payment(account["id"], create_payment_payload(250.00), TEST_USERS[CASHIER]), 201)
    assert payment["allocated_fines"] == 250.00
    assert payment["allocated_court_fee"] == 0.00
    ledger = refetch_ledger(api, account["id"])
    assert ledger["balance"] == 290.00


def test_overpayment_rejected(api):
    """PRD §3.7: "If any pool remains after all four buckets are full — that is,
    if the amount exceeds the total outstanding balance — the payment is rejected
    with ERR_OVERPAYMENT and nothing is applied."

    Design: Corner/validations/overpayment_single_rejected
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    account = ctx["ledger_account"]  # balance 540, ASSESSED
    resp = api.create_payment(account["id"], create_payment_payload(600.00), TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT, 422)


def test_installment_count_out_of_range_rejected(api):
    """PRD §3.7: "The number of installments must be between 2 and 12 inclusive;
    a value outside that range is rejected with ERR_INVALID_INSTALLMENT_COUNT."

    Design: Corner/validations/installment_count_out_of_range_rejected
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    account = ctx["ledger_account"]
    acct = refetch_ledger(api, account["id"])
    resp = api.create_installment_plan(
        account["id"], create_installment_plan_payload(20, acct["version"]), TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_INVALID_INSTALLMENT_COUNT, 422)


def test_installment_minimum_balance_not_met_rejected(api):
    """PRD §3.7: "The account's balance must be at least 100 dollars to qualify
    for a plan; a balance below that minimum is rejected with
    ERR_INSTALLMENT_MINIMUM_NOT_MET."

    Design: Corner/validations/installment_minimum_not_met_rejected
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "INFRACTION", "base_fine_amount": 20}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 0},
    )
    account = ctx["ledger_account"]  # subtotal 20 -> surcharge 4 -> 20+50+4 = 74.00
    assert account["balance"] == 74.00
    acct = refetch_ledger(api, account["id"])
    resp = api.create_installment_plan(
        account["id"], create_installment_plan_payload(3, acct["version"]), TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_INSTALLMENT_MINIMUM_NOT_MET, 422)


def test_occ_stale_version_second_plan_rejected(api):
    """PRD §2.8: "Before the plan is created, the server compares this value to
    the account's current version; if they do not match, the request is rejected
    with ERR_STALE_VERSION (HTTP 412) and no plan is created."
    PRD §2.8: "creating a superseding plan each bump the account's version."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_installment_plan_rejected
    """
    ctx = setup_granted_diversion(
        api,
        charges=[{"severity": "MISDEMEANOR", "base_fine_amount": 200}],
        diversion_overrides={"mandated_service_hours": 0, "program_fee": 100},
    )
    account = ctx["ledger_account"]
    acct_v0 = refetch_ledger(api, account["id"])["version"]
    # First plan succeeds and bumps the account version.
    validate_success(
        api.create_installment_plan(
            account["id"], create_installment_plan_payload(4, acct_v0), TEST_USERS[CASHIER]), 201)
    # Second create carrying the stale (pre-bump) version is rejected.
    resp = api.create_installment_plan(
        account["id"], create_installment_plan_payload(6, acct_v0), TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
