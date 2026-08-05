"""Delinquency materialization (penalty + whole-month interest) and payoff quotes."""
from test_helpers import (
    validate_success,
    setup_delinquent_second_installment, setup_first_installment_paid,
    installments_by_bill, installment_seq, set_clock,
    TEST_USERS,
)

TREASURER = TEST_USERS["treasurer_headers"]


# ---- Difficulty: delinquency_penalty_plus_interest_capped (test 1 of 2) ----
def test_delinquency_penalty_and_whole_month_interest(api):
    """PRD 3.5: "The penalty is charged exactly once and equals the installment's
    `principal_due_cents` multiplied by the penalty rate `PENALTY_RATE` of
    five percent (0.05), rounded half-up to a whole cent, and posted as a
    `PENALTY` ledger entry."
    PRD 3.5: "The interest for the installment is its `principal_due_cents` multiplied
    by the monthly interest rate `INTEREST_RATE_MONTHLY` of one percent
    (0.01), rounded half-up to a whole cent, then multiplied by the number
    of elapsed months, and posted as `INTEREST` ledger entries."

    Design: Difficulty/combinatorial_formula/delinquency_penalty_plus_interest_capped
    """
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents=20000000, clock="2026-11-20")
    inst2 = installment_seq(api, bill["id"], 2)
    assert inst2["penalty_cents"] == 10000
    assert inst2["interest_cents"] == 4000


# ---- Difficulty: delinquency_penalty_plus_interest_capped (test 2 of 2) ----
def test_delinquent_installment_balance_and_status(api):
    """PRD 3.2: "its own `balance_cents`, which is its `principal_due_cents` plus
    `penalty_cents` plus `interest_cents` minus `paid_cents`."
    PRD 2.8: "the installment moves from `PENDING` to `DELINQUENT`, the one-time penalty
    is posted, whole-month interest is posted for each newly crossed
    monthly anniversary, and the parent bill's collection posture bubbles
    up to `DELINQUENT`."

    Design: Difficulty/combinatorial_formula/delinquency_penalty_plus_interest_capped
    """
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents=20000000, clock="2026-11-20")
    inst2 = installment_seq(api, bill["id"], 2)
    assert inst2["balance_cents"] == 214000
    assert inst2["status"] == "DELINQUENT"


# ---- Difficulty: payoff_ledger_as_of_vs_quote (test 1 of 2) ----
def test_payoff_ledger_as_of_uses_whole_month_interest(api):
    """PRD 3.5: "In the default `LEDGER_AS_OF` mode the supplied `as_of_date` is ignored
    and the interest component is the whole-month interest already
    materialized to the ledger through the current clock, matching the
    delinquency figures."
    PRD 3.5: "the `payoff_total_cents`, which is the principal balance plus the penalty
    total plus the interest component."

    Design: Difficulty/dual_variant_calc/payoff_ledger_as_of_vs_quote
    """
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents=20000000, clock="2026-11-20")
    data = validate_success(api.get_payoff(bill["id"], TREASURER, params={"mode": "LEDGER_AS_OF"}))
    assert data["interest_cents"] == 4000
    assert data["payoff_total_cents"] == 214000


# ---- Difficulty: payoff_ledger_as_of_vs_quote (test 2 of 2) ----
def test_payoff_quote_uses_per_diem_projection(api):
    """PRD 3.5: "In `PAYOFF_QUOTE` mode with a future `as_of_date`, the interest component
    is a forward per-diem projection rather than whole-month: it is the
    `principal_balance_cents` multiplied by the monthly rate of one
    percent, annualized by multiplying by twelve, divided by
    `DAYS_PER_YEAR` of 365 to yield a daily rate, then multiplied by the
    number of days from the due date to the `as_of_date`, and rounded
    half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/payoff_ledger_as_of_vs_quote
    """
    ty, parcel, bill = setup_delinquent_second_installment(
        api, assessed_value_cents=20000000, clock="2026-11-20")
    data = validate_success(api.get_payoff(
        bill["id"], TREASURER,
        params={"mode": "PAYOFF_QUOTE", "as_of_date": "2026-12-15T00:00:00Z"}))
    assert data["interest_cents"] == 5984
    assert data["payoff_total_cents"] == 215984


# ---- Difficulty: delinquency_date_strictly_after_due (test 1 of 2) ----
def test_installment_on_due_date_stays_pending(api):
    """PRD 3.5: "An installment is delinquent when the current clock calendar date is
    strictly after its `due_date` and its unpaid principal is still
    positive."

    Design: Difficulty/boundary_precision_check/delinquency_date_strictly_after_due
    """
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents=20000000)
    set_clock(api, "2026-09-15T00:00:00Z")
    inst2 = installment_seq(api, bill["id"], 2)
    assert inst2["status"] == "PENDING"
    assert inst2["penalty_cents"] == 0


# ---- Difficulty: delinquency_date_strictly_after_due (test 2 of 2) ----
def test_installment_day_after_due_becomes_delinquent(api):
    """PRD 2.8: "For each installment that is now past due — meaning the current clock
    calendar date is strictly after the installment's `due_date` while its
    balance remains positive — the installment moves from `PENDING` to
    `DELINQUENT`, the one-time penalty is posted"

    Design: Difficulty/boundary_precision_check/delinquency_date_strictly_after_due
    """
    ty, parcel, bill = setup_first_installment_paid(api, assessed_value_cents=20000000)
    set_clock(api, "2026-09-15T00:00:00Z")
    set_clock(api, "2026-09-16T00:00:00Z")
    inst2 = installment_seq(api, bill["id"], 2)
    assert inst2["status"] == "DELINQUENT"
    assert inst2["penalty_cents"] == 10000
