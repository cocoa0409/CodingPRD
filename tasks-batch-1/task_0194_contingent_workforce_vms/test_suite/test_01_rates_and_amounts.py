"""Rate derivation, markup ceiling, timesheet amounts, expense reimbursement.

Covers the money calculations: bill_rate_and_markup (§3.4), timesheet_amounts
(§3.8), expense_reimbursement (§3.9).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, setup_distributed_requisition, create_submittal,
    setup_active_assignment, setup_submitted_timesheet,
    setup_active_assignment_with_submitted_expense,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_headers"]


# ===========================================================================
# Queue A: dual_variant_calc / timesheet_pay_vs_bill_diverge_on_same_hours
# ===========================================================================

def test_timesheet_pay_and_bill_diverge_on_same_hours(api):
    """PRD §3.8: "the regular pay component is `regular_hours` times the
    assignment's `pay_rate_cents`, rounded half-up to whole cents; the overtime
    pay component is `overtime_hours` times the assignment's `pay_rate_cents`
    times 1.5, rounded half-up to whole cents; and `pay_amount_cents` is the sum
    of those two rounded components."
    PRD §3.8: "the regular bill component is `regular_hours` times the
    assignment's `bill_rate_cents`, rounded half-up; the overtime bill component
    is `overtime_hours` times the assignment's `bill_rate_cents` times 1.5,
    rounded half-up; and `bill_amount_cents` is the sum of those two rounded
    components."

    pay = rhu(40*8000) + rhu(5*8000*1.5) = 320000 + 60000 = 380000
    bill = rhu(40*11600) + rhu(5*11600*1.5) = 464000 + 87000 = 551000

    Design: Difficulty/dual_variant_calc/timesheet_pay_vs_bill_diverge_on_same_hours
    """
    base = setup_active_assignment(
        start_date="2026-01-01T00:00:00.000Z",
        planned_end_date="2026-06-01T00:00:00.000Z",
    )
    # Assignment pay 8000, default-markup bill 11600 (rhu(8000*1.45)).
    assert base["assignment"]["pay_rate_cents"] == 8000
    assert base["assignment"]["bill_rate_cents"] == 11600
    sh = base["supplier_headers"]
    ts = get_success_data(api.create_timesheet(
        F.create_timesheet_payload(base["assignment"]["id"],
                                   "2026-01-05T00:00:00.000Z",
                                   regular_hours=40, overtime_hours=5),
        sh,
    ))
    get_success_data(api.submit_timesheet(ts["id"], sh))
    data = validate_success(api.approve_timesheet(ts["id"], HM))
    assert data["pay_amount_cents"] == 380000, f"got {data['pay_amount_cents']}"
    assert data["bill_amount_cents"] == 551000, f"got {data['bill_amount_cents']}"
    assert data["bill_amount_cents"] != data["pay_amount_cents"]


def test_timesheet_amounts_only_regular_hours_pay_vs_bill(api):
    """PRD §3.8: "the regular pay component is `regular_hours` times the
    assignment's `pay_rate_cents`, rounded half-up to whole cents ... and
    `pay_amount_cents` is the sum of those two rounded components."
    PRD §3.8: "the regular bill component is `regular_hours` times the
    assignment's `bill_rate_cents`, rounded half-up ... and `bill_amount_cents`
    is the sum of those two rounded components."

    With overtime defaulting to 0: pay = 40*8000 = 320000, bill = 40*11600 = 464000.

    Design: Difficulty/dual_variant_calc/timesheet_pay_vs_bill_diverge_on_same_hours
    """
    base = setup_active_assignment(
        start_date="2026-01-01T00:00:00.000Z",
        planned_end_date="2026-06-01T00:00:00.000Z",
    )
    sh = base["supplier_headers"]
    ts = get_success_data(api.create_timesheet(
        F.create_timesheet_payload(base["assignment"]["id"],
                                   "2026-01-05T00:00:00.000Z", regular_hours=40),
        sh,
    ))
    get_success_data(api.submit_timesheet(ts["id"], sh))
    data = validate_success(api.approve_timesheet(ts["id"], HM))
    assert data["pay_amount_cents"] == 320000, f"got {data['pay_amount_cents']}"
    assert data["bill_amount_cents"] == 464000, f"got {data['bill_amount_cents']}"
    assert data["bill_amount_cents"] != data["pay_amount_cents"]


# ===========================================================================
# Queue A: dual_variant_calc / submittal_bill_rate_derived_vs_explicit_diverge
# ===========================================================================

def test_submittal_derived_bill_rate_uses_default_markup(api):
    """PRD §3.4: "otherwise the bill rate is derived as the worker's
    `pay_rate_cents` multiplied by one plus the program's `default_markup_pct`,
    with the product rounded half-up to whole cents."
    PRD §3.4: "the `effective_markup_pct` is computed as the bill rate divided
    by the pay rate, minus one."

    pay 10000, default_markup 0.45 -> bill rhu(10000*1.45) = 14500, markup 0.45.

    Design: Difficulty/dual_variant_calc/submittal_bill_rate_derived_vs_explicit_diverge
    """
    base = setup_distributed_requisition(req_overrides={"openings": 2})
    sub = create_submittal(base["requisition"]["id"], base["supplier"]["id"],
                           base["worker"]["id"], pay_rate_cents=10000)
    assert sub["bill_rate_cents"] == 14500, f"got {sub['bill_rate_cents']}"
    assert sub["effective_markup_pct"] == pytest.approx(0.45, abs=1e-9)


def test_submittal_explicit_bill_rate_yields_distinct_markup(api):
    """PRD §3.4: "if the request supplies `bill_rate_cents`, that value is used
    exactly as given"
    PRD §3.4: "the `effective_markup_pct` is computed as the bill rate divided
    by the pay rate, minus one."

    Explicit bill 16000 over pay 10000 -> markup 0.60, distinct from the derived
    14500/0.45 path on identical pay.

    Design: Difficulty/dual_variant_calc/submittal_bill_rate_derived_vs_explicit_diverge
    """
    base = setup_distributed_requisition(req_overrides={"openings": 2})
    worker_b = create_worker(base["program"]["id"], full_name="W B", national_id_hash="hb")
    sh = base["supplier_headers"]
    derived = create_submittal(base["requisition"]["id"], base["supplier"]["id"],
                               base["worker"]["id"], pay_rate_cents=10000)
    explicit = get_success_data(api.create_submittal(
        F.create_submittal_payload(base["requisition"]["id"], base["supplier"]["id"],
                                   worker_b["id"], pay_rate_cents=10000, bill_rate_cents=16000),
        sh,
    ))
    assert explicit["bill_rate_cents"] == 16000, f"got {explicit['bill_rate_cents']}"
    assert explicit["effective_markup_pct"] == pytest.approx(0.60, abs=1e-9)
    assert explicit["bill_rate_cents"] != derived["bill_rate_cents"]


# ===========================================================================
# Queue A: combinatorial_formula / timesheet_round_then_sum_differs_from_sum_then_round
# ===========================================================================

def test_timesheet_round_then_sum_pins_pay_amount(api):
    """PRD §3.8: "is computed component-by-component with rounding applied to
    each component before summing — the four money components are never summed
    before rounding, and hours are never summed before multiplying."

    pay 2501, reg 0.5, ot 0.5: rhu(1250.5)+rhu(1875.75) = 1251+1876 = 3127
    (round-then-sum), NOT rhu(3126.25)=3126.

    Design: Difficulty/combinatorial_formula/timesheet_round_then_sum_differs_from_sum_then_round
    """
    # Build an assignment with explicit pay 2501 / bill 3626 so the fractional
    # rounding is exercised.
    program = create_program()
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    req = create_requisition(program["id"], max_pay_rate_cents=20000)
    distribute(req["id"], [supplier["id"]])
    sh = make_supplier_headers(supplier["id"])
    sub = create_submittal(req["id"], supplier["id"], worker["id"],
                           pay_rate_cents=2501, bill_rate_cents=3626)
    get_success_data(api.shortlist_submittal(sub["id"], HM))
    get_success_data(api.start_interview(sub["id"], HM))
    get_success_data(api.propose_rate(sub["id"], {"pay_rate_cents": 2501, "bill_rate_cents": 3626}, sh))
    get_success_data(api.offer_submittal(sub["id"], HM))
    req2 = get_success_data(api.get_requisition(req["id"], PM))
    get_success_data(api.hire_submittal(sub["id"], F.hire_payload(
        req2["version"], "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    asg = get_success_data(api.list_assignments(PM, params={"worker_profile_id": worker["id"]}))[0]
    ts = get_success_data(api.create_timesheet(
        F.create_timesheet_payload(asg["id"], "2026-01-05T00:00:00.000Z",
                                   regular_hours=0.5, overtime_hours=0.5), sh))
    get_success_data(api.submit_timesheet(ts["id"], sh))
    data = validate_success(api.approve_timesheet(ts["id"], HM))
    assert data["pay_amount_cents"] == 3127, f"got {data['pay_amount_cents']}"


def test_timesheet_round_then_sum_pins_bill_amount(api):
    """PRD §3.8: "is computed component-by-component with rounding applied to
    each component before summing — the four money components are never summed
    before rounding, and hours are never summed before multiplying."

    bill 3626, reg 0.5, ot 0.5: rhu(1813.0)+rhu(2719.5) = 1813+2720 = 4533.

    Design: Difficulty/combinatorial_formula/timesheet_round_then_sum_differs_from_sum_then_round
    """
    program = create_program()
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    req = create_requisition(program["id"], max_pay_rate_cents=20000)
    distribute(req["id"], [supplier["id"]])
    sh = make_supplier_headers(supplier["id"])
    sub = create_submittal(req["id"], supplier["id"], worker["id"],
                           pay_rate_cents=2501, bill_rate_cents=3626)
    get_success_data(api.shortlist_submittal(sub["id"], HM))
    get_success_data(api.start_interview(sub["id"], HM))
    get_success_data(api.propose_rate(sub["id"], {"pay_rate_cents": 2501, "bill_rate_cents": 3626}, sh))
    get_success_data(api.offer_submittal(sub["id"], HM))
    req2 = get_success_data(api.get_requisition(req["id"], PM))
    get_success_data(api.hire_submittal(sub["id"], F.hire_payload(
        req2["version"], "2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"), PM))
    asg = get_success_data(api.list_assignments(PM, params={"worker_profile_id": worker["id"]}))[0]
    ts = get_success_data(api.create_timesheet(
        F.create_timesheet_payload(asg["id"], "2026-01-05T00:00:00.000Z",
                                   regular_hours=0.5, overtime_hours=0.5), sh))
    get_success_data(api.submit_timesheet(ts["id"], sh))
    data = validate_success(api.approve_timesheet(ts["id"], HM))
    assert data["bill_amount_cents"] == 4533, f"got {data['bill_amount_cents']}"


# ===========================================================================
# Queue A: boundary_precision_check / markup_exactly_at_max_is_accepted
# ===========================================================================

def test_markup_exactly_at_max_is_accepted(api):
    """PRD §3.4: "Both ceilings are inclusive: a pay rate exactly equal to
    `max_pay_rate_cents` is accepted, and an effective markup exactly equal to
    `max_markup_pct` is accepted — only values strictly above the ceiling are
    refused."

    pay 10000 bill 16000 -> markup exactly 0.60 == max_markup -> accepted.

    Design: Difficulty/boundary_precision_check/markup_exactly_at_max_is_accepted
    """
    base = setup_distributed_requisition(req_overrides={"openings": 2})
    sh = base["supplier_headers"]
    data = validate_success(api.create_submittal(
        F.create_submittal_payload(base["requisition"]["id"], base["supplier"]["id"],
                                   base["worker"]["id"], pay_rate_cents=10000,
                                   bill_rate_cents=16000),
        sh,
    ), expected_status=201)
    assert data["effective_markup_pct"] == pytest.approx(0.60, abs=1e-9)
    assert data["status"] == "SUBMITTED"


def test_markup_one_cent_above_max_is_rejected(api):
    """PRD §3.4: "The effective markup may not exceed the program's
    `max_markup_pct`; an `effective_markup_pct` greater than that ceiling is
    rejected with `ERR_MARKUP_EXCEEDS_MAX`."

    pay 10000 bill 16001 -> markup 0.6001 > 0.60 -> rejected.

    Design: Difficulty/boundary_precision_check/markup_exactly_at_max_is_accepted
    """
    base = setup_distributed_requisition(req_overrides={"openings": 2})
    sh = base["supplier_headers"]
    validate_error(
        api.create_submittal(
            F.create_submittal_payload(base["requisition"]["id"], base["supplier"]["id"],
                                       base["worker"]["id"], pay_rate_cents=10000,
                                       bill_rate_cents=16001),
            sh,
        ),
        ApiErrorId.ERR_MARKUP_EXCEEDS_MAX.value,
    )


# ===========================================================================
# Queue B: calculations / expense_reimbursement_cap_boundary_meals
# ===========================================================================

def test_expense_reimbursement_caps_at_meals_ceiling(api):
    """PRD §3.9: "Reimbursement applies a per-category cap and sets
    `reimbursable_amount_cents` to the smaller of the submitted `amount_cents`
    and the cap for that category. The caps, in cents, are 50000 for `TRAVEL`,
    30000 for `LODGING`, 7500 for `MEALS`, 100000 for `EQUIPMENT`, and 20000 for
    `OTHER`."

    Design: Corner/calculations/expense_reimbursement_cap_boundary_meals
    """
    base = setup_active_assignment_with_submitted_expense(category="MEALS", amount_cents=7501)
    data = validate_success(api.approve_expense(base["expense"]["id"], HM))
    assert data["reimbursable_amount_cents"] == 7500, f"got {data['reimbursable_amount_cents']}"


def test_expense_reimbursement_below_meals_cap_reimburses_full(api):
    """PRD §3.9: "The cap is inclusive: a submitted amount exactly equal to its
    category cap reimburses in full, while an amount one cent above the cap is
    reimbursed only up to the cap."

    MEALS amount 6000 (under cap 7500) -> reimbursable 6000 (min-of-cap).

    Design: Corner/calculations/expense_reimbursement_cap_boundary_meals
    """
    base = setup_active_assignment_with_submitted_expense(category="MEALS", amount_cents=6000)
    data = validate_success(api.approve_expense(base["expense"]["id"], HM))
    assert data["reimbursable_amount_cents"] == 6000, f"got {data['reimbursable_amount_cents']}"


# ===========================================================================
# Queue B: errors / pay_rate_exceeds_max_on_submittal_create
# ===========================================================================

def test_pay_rate_above_requisition_max_rejected(api):
    """PRD §3.4: "The pay rate may not exceed the requisition's
    `max_pay_rate_cents`; a `pay_rate_cents` greater than that ceiling is
    rejected with `ERR_PAY_RATE_EXCEEDS_MAX`."

    Design: Corner/errors/pay_rate_exceeds_max_on_submittal_create
    """
    base = setup_distributed_requisition(req_overrides={"max_pay_rate_cents": 20000})
    sh = base["supplier_headers"]
    validate_error(
        api.create_submittal(
            F.create_submittal_payload(base["requisition"]["id"], base["supplier"]["id"],
                                       base["worker"]["id"], pay_rate_cents=25000,
                                       bill_rate_cents=30000),
            sh,
        ),
        ApiErrorId.ERR_PAY_RATE_EXCEEDS_MAX.value,
    )
