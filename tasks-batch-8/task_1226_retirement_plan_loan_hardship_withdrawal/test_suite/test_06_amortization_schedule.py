"""Amortization schedule computations: dual day-count variants, pinned rounding
order, reconciliation to principal, cure-deadline quarter arithmetic, and the
fixed startup clock (PRD §3.5, §3.7, §2.6)."""
from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    approve_loan_fully,
    create_plan_payload,
    enroll_participant,
    list_loan_tasks,
    request_loan,
    set_clock,
    setup_disbursed_loan,
    setup_plan_and_participant,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: amortization_day_count_variants_diverge
# ---------------------------------------------------------------------------


def test_amortization_day_count_variants_diverge_first_installment(api):
    """PRD §3.5: "The period rate depends on the loan's day-count convention:
    under `THIRTY_360` every installment's period rate is the annual rate divided
    by twelve, while under `ACT_360` each installment's period rate is the annual
    rate multiplied by the actual number of days between the previous due date —
    the disbursement date for the first installment — and that installment's own
    due date, divided by 360. Identical inputs therefore yield different interest
    portions and a different final installment under the two conventions."

    Design: Difficulty/dual_variant_calc/amortization_day_count_variants_diverge
    """
    # Plan A: THIRTY_360; Plan B: ACT_360
    plan_a = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan A", day_count_convention="THIRTY_360"),
            ADMIN,
        ),
        201,
    )
    plan_b = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan B", day_count_convention="ACT_360"),
            ADMIN,
        ),
        201,
    )
    pa = enroll_participant(plan_a["id"], vested_balance_cents=10_000_000)
    pb = enroll_participant(plan_b["id"], vested_balance_cents=10_000_000)
    loan_a = request_loan(pa, principal_amount_cents=1_000_000, term_months=12)
    loan_b = request_loan(pb, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan_a["id"])
    approve_loan_fully(loan_b["id"])
    validate_success(api.disburse_loan(loan_a["id"], ADMIN), 200)
    validate_success(api.disburse_loan(loan_b["id"], ADMIN), 200)

    inst_a, _ = validate_paginated(
        api.list_loan_installments(loan_a["id"], ADMIN, params={"limit": 100})
    )
    inst_b, _ = validate_paginated(
        api.list_loan_installments(loan_b["id"], ADMIN, params={"limit": 100})
    )
    assert inst_a[0]["interest_portion_cents"] == 4_167
    assert inst_b[0]["interest_portion_cents"] == 4_306
    assert inst_a[0]["interest_portion_cents"] != inst_b[0]["interest_portion_cents"]


def test_amortization_day_count_variants_diverge_shared_level_payment(api):
    """PRD §3.5: "`scheduled_payment_cents` is that raw payment rounded half up
    to a whole cent." Both variants share the same level-payment formula — only
    the per-installment period rate differs.

    Design: Difficulty/dual_variant_calc/amortization_day_count_variants_diverge
    """
    plan_a = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan A2", day_count_convention="THIRTY_360"),
            ADMIN,
        ),
        201,
    )
    plan_b = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan B2", day_count_convention="ACT_360"),
            ADMIN,
        ),
        201,
    )
    pa = enroll_participant(plan_a["id"], vested_balance_cents=10_000_000)
    pb = enroll_participant(plan_b["id"], vested_balance_cents=10_000_000)
    loan_a = request_loan(pa, principal_amount_cents=1_000_000, term_months=12)
    loan_b = request_loan(pb, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan_a["id"])
    approve_loan_fully(loan_b["id"])
    disb_a = validate_success(api.disburse_loan(loan_a["id"], ADMIN), 200)
    disb_b = validate_success(api.disburse_loan(loan_b["id"], ADMIN), 200)
    assert disb_a["scheduled_payment_cents"] == 85_607
    assert disb_b["scheduled_payment_cents"] == 85_607


# ---------------------------------------------------------------------------
# Difficulty: amortization_final_installment_rounding_remainder
# ---------------------------------------------------------------------------


def test_amortization_final_installment_rounding_remainder_amount(api):
    """PRD §3.5: "The final installment takes the entire remaining balance as its
    principal portion, and its scheduled amount is that principal plus its own
    interest portion — the final row thereby absorbs the accumulated rounding
    remainder".

    Design: Difficulty/combinatorial_formula/amortization_final_installment_rounding_remainder
    """
    _, _, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN, params={"limit": 100})
    )
    assert len(inst) == 12
    # First installment carries the level payment; final absorbs the remainder.
    assert inst[0]["scheduled_amount_cents"] == 85_607
    assert inst[11]["scheduled_amount_cents"] == 85_612
    assert inst[11]["principal_portion_cents"] == 85_257
    assert inst[11]["interest_portion_cents"] == 355
    assert inst[11]["scheduled_amount_cents"] != inst[0]["scheduled_amount_cents"]


def test_amortization_final_installment_rounding_remainder_sums(api):
    """PRD §3.5: "the principal portions across the schedule sum to the original
    principal exactly."

    Design: Difficulty/combinatorial_formula/amortization_final_installment_rounding_remainder
    """
    _, _, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN, params={"limit": 100})
    )
    total_principal = sum(r["principal_portion_cents"] for r in inst)
    total_scheduled = sum(r["scheduled_amount_cents"] for r in inst)
    assert total_principal == 1_000_000
    assert total_scheduled == 1_027_289


# ---------------------------------------------------------------------------
# Corner: computed_amortization_schedule_reconciles_to_principal
# ---------------------------------------------------------------------------


def test_computed_amortization_schedule_reconciles_to_principal(api):
    """PRD §3.5: "Installment rows carry a 1-based `installment_number`, a
    `due_date` falling monthly on the disbursement day-of-month with the first
    installment due one month after `disbursed_on`". PRD §3.5: "the principal
    portions across the schedule sum to the original principal exactly."

    Design: Corner/endpoints/computed_amortization_schedule_reconciles_to_principal
    """
    _, _, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    loan_now = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_now["scheduled_payment_cents"] == 85_607
    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN, params={"limit": 100})
    )
    assert len(inst) == 12
    assert inst[0]["installment_number"] == 1
    assert inst[0]["status"] == "PENDING"
    assert inst[0]["due_date"] == "2026-06-01T00:00:00Z"
    assert inst[11]["due_date"] == "2027-05-01T00:00:00Z"
    assert sum(r["principal_portion_cents"] for r in inst) == 1_000_000


# ---------------------------------------------------------------------------
# Corner: cure_deadline_quarter_arithmetic
# ---------------------------------------------------------------------------


def test_cure_deadline_quarter_arithmetic_q2_due(api):
    """PRD §3.7: "take the earliest still-unpaid `MISSED` installment's
    `due_date`, find the calendar quarter containing it — quarters run January
    through March, April through June, July through September, and October
    through December — and set the deadline to the last day of the calendar
    quarter immediately following that quarter."

    Design: Corner/calculations/cure_deadline_quarter_arithmetic
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    # Disburse at 2026-05-30 so installment 1 is due 2026-06-30 (Q2)
    set_clock("2026-05-30T00:00:00Z")
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    approve_loan_fully(loan["id"])
    validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    # Advance past 2026-06-30 without paying installment 1
    set_clock("2026-07-02T00:00:00Z")
    loan_now = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_now["delinquency_status"] == "DELINQUENT"
    assert loan_now["cure_deadline_on"] == "2026-09-30T00:00:00Z"


def test_cure_deadline_quarter_arithmetic_q3_due(api):
    """PRD §3.7: "take the earliest still-unpaid `MISSED` installment's
    `due_date`, find the calendar quarter containing it ... and set the deadline
    to the last day of the calendar quarter immediately following that quarter."
    An installment due 2026-07-01 (Q3) yields cure deadline 2026-12-31.

    Design: Corner/calculations/cure_deadline_quarter_arithmetic
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    # Disburse at 2026-06-01 so installment 1 is due 2026-07-01 (Q3)
    set_clock("2026-06-01T00:00:00Z")
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    approve_loan_fully(loan["id"])
    validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    # Advance past 2026-07-01 without paying installment 1
    set_clock("2026-07-02T00:00:00Z")
    loan_now = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_now["delinquency_status"] == "DELINQUENT"
    assert loan_now["cure_deadline_on"] == "2026-12-31T00:00:00Z"
