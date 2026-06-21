"""Pricing engine and calculation tests: bill charges, PGA, conversion, budget installment,
low-income eligibility/credit, deposit requirement, ticket severity, payment timeliness,
and the dual-variant / combinatorial-formula depth instances."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    fixtures as fx,
    TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_actual_cost_bill_charges_full_cyclic_amount(api):
    """PRD 3.5: "when the account is not budget-enrolled at issue time, budget_billed_cents
    equals amount_due_cents and the customer pays the full computed cyclic amount".

    Design: Difficulty/dual_variant_calc/bill_actual_cost_vs_levelized_budget_billed
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    assert issued["amount_due_cents"] == 6326, f"got {issued['amount_due_cents']}"
    assert issued["budget_billed_cents"] == 6326, (
        f"actual-cost bill budget_billed must equal amount_due, got {issued['budget_billed_cents']}")


def test_levelized_budget_bill_charges_flat_installment(api):
    """PRD 3.5: "when the account is budget-enrolled (an ACTIVE budget plan exists) at issue
    time, budget_billed_cents is instead the plan's flat monthly_installment_cents, while
    amount_due_cents is still computed and accrued for the year-end true-up".

    Design: Difficulty/dual_variant_calc/bill_actual_cost_vs_levelized_budget_billed
    """
    # projected 96000 / 12 -> installment 8000
    acct, meter, plan, issued = fx.setup_budget_enrolled_issued_bill(projected_annual_cents=96000)
    assert plan["monthly_installment_cents"] == 8000, f"got {plan['monthly_installment_cents']}"
    assert issued["amount_due_cents"] == 6326, (
        f"amount_due still the computed cyclic amount, got {issued['amount_due_cents']}")
    assert issued["budget_billed_cents"] == 8000, (
        f"budget bill charges the flat installment, got {issued['budget_billed_cents']}")


def test_budget_trueup_residual_overpaid_negative_sign(api):
    """PRD 3.7: "At true-up, trueup_balance_cents is set to the plan's accrued_actual_cents
    minus its accrued_budget_cents, where those accruals sum, respectively, the
    amount_due_cents and the budget_billed_cents of the bills issued under the plan".

    Design: Difficulty/dual_variant_calc/budget_trueup_residual_sign_underpaid_vs_overpaid
    """
    acct, meter, plan, issued = fx.setup_budget_enrolled_issued_bill(projected_annual_cents=96000)
    resp = api.true_up_budget_plan(acct["id"], plan["id"], headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "TRUED_UP"
    assert data["accrued_actual_cents"] == 6326, f"got {data['accrued_actual_cents']}"
    assert data["accrued_budget_cents"] == 8000, f"got {data['accrued_budget_cents']}"
    # 6326 - 8000 = -1674 (customer overpaid)
    assert data["trueup_balance_cents"] == -1674, f"got {data['trueup_balance_cents']}"


def test_budget_trueup_status_transitions_to_trued_up(api):
    """PRD 3.7: "The annual true-up is run by a BillingAdmin and advances the plan
    ACTIVE -> TRUED_UP."

    Design: Difficulty/dual_variant_calc/budget_trueup_residual_sign_underpaid_vs_overpaid
    """
    acct, meter, plan, issued = fx.setup_budget_enrolled_issued_bill(projected_annual_cents=96000)
    resp = api.true_up_budget_plan(acct["id"], plan["id"], headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "TRUED_UP", f"got {data['status']}"


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_minimum_bill_floor_raises_gross(api):
    """PRD 3.5: "the gross is the sum of commodity_charge_cents, distribution_charge_cents,
    and fixed_charge_cents, then raised to the rate schedule's minimum_bill_cents if the sum
    falls below that floor."

    Design: Difficulty/combinatorial_formula/bill_charges_nonlinear_min_floor_and_credit_branch
    """
    # gross = 3588 + 1538 + 1200 = 6326; minimum_bill_cents 8000 raises it to 8000.
    rs, acct, meter, read, issued = fx.setup_issued_bill(minimum_bill_cents=8000)
    assert issued["commodity_charge_cents"] == 3588, f"got {issued['commodity_charge_cents']}"
    assert issued["distribution_charge_cents"] == 1538, f"got {issued['distribution_charge_cents']}"
    assert issued["fixed_charge_cents"] == 1200, f"got {issued['fixed_charge_cents']}"
    assert issued["low_income_credit_cents"] == 0, f"got {issued['low_income_credit_cents']}"
    assert issued["amount_due_cents"] == 8000, (
        f"minimum-bill floor must raise amount_due to 8000, got {issued['amount_due_cents']}")


def test_minimum_bill_floor_not_applied_when_gross_above(api):
    """PRD 3.5: "the gross is the sum of commodity_charge_cents, distribution_charge_cents,
    and fixed_charge_cents, then raised to the rate schedule's minimum_bill_cents if the sum
    falls below that floor."

    Design: Difficulty/combinatorial_formula/bill_charges_nonlinear_min_floor_and_credit_branch
    """
    # gross = 3588 + 1538 + 1200 = 6326; minimum_bill_cents 5000 < gross, so the floor does
    # NOT apply and amount_due stays 6326.
    rs, acct, meter, read, issued = fx.setup_issued_bill(minimum_bill_cents=5000)
    assert issued["low_income_credit_cents"] == 0, f"got {issued['low_income_credit_cents']}"
    assert issued["amount_due_cents"] == 6326, (
        f"floor below gross must not raise amount_due, got {issued['amount_due_cents']}")


def test_low_income_credit_rounds_before_cap(api):
    """PRD 3.8: "The discounted amount is computed as the creditable base multiplied by the
    tier percentage, rounded half up to whole cents, and then the lesser of that rounded
    amount and the tier's monthly cap is taken (the cap is applied after rounding)."

    Design: Difficulty/combinatorial_formula/low_income_credit_round_then_cap_order
    """
    # creditable = 3588 + 1538 = 5126; TIER_1 0.20 -> round(1025.2)=1025; min(1025, 4000)=1025.
    acct, meter, credit, issued = fx.setup_low_income_issued_bill(
        household_size=1, annual_income_cents=1400000)
    assert issued["low_income_credit_cents"] == 1025, (
        f"credit must round 1025.2 to 1025 before the 4000 cap, got {issued['low_income_credit_cents']}")
    # amount_due = 6326 - 1025 = 5301
    assert issued["amount_due_cents"] == 5301, f"got {issued['amount_due_cents']}"


def test_low_income_credit_only_on_commodity_and_distribution(api):
    """PRD 3.8: "The credit applies only to the sum of commodity_charge_cents and
    distribution_charge_cents — never to the fixed customer charge."

    Design: Difficulty/combinatorial_formula/low_income_credit_round_then_cap_order
    """
    acct, meter, credit, issued = fx.setup_low_income_issued_bill(
        household_size=1, annual_income_cents=1400000)
    # If the fixed 1200 were included, creditable would be 6326 -> credit 1265, not 1025.
    assert issued["low_income_credit_cents"] == 1025, (
        f"credit base excludes the fixed charge, got {issued['low_income_credit_cents']}")


# ===========================================================================
# Queue B — calculations
# ===========================================================================
def test_bill_charges_canonical_result(api):
    """PRD 3.5: "the effective per-therm PGA rate ... is computed first, then multiplied by
    therms_billed, and that single product is rounded half up to whole cents to give
    commodity_charge_cents — the rounding happens once, at the end, not on any intermediate."

    Design: Corner/calculations/bill_charges_correct_result_canonical
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    assert issued["commodity_charge_cents"] == 3588, f"got {issued['commodity_charge_cents']}"
    assert issued["distribution_charge_cents"] == 1538, f"got {issued['distribution_charge_cents']}"
    assert issued["fixed_charge_cents"] == 1200, f"got {issued['fixed_charge_cents']}"
    assert issued["amount_due_cents"] == 6326, f"got {issued['amount_due_cents']}"


def test_pga_supplier_refund_floors_effective_rate_at_zero(api):
    """PRD 3.1: "When a bill is priced, the effective commodity rate is the
    commodity_rate_cents_per_therm reduced by supplier_refund_cents_per_therm, floored at 0
    (the refund never drives the effective rate negative)."

    Design: Corner/calculations/pga_supplier_refund_floors_effective_rate_at_zero
    """
    # commodity 40, refund 50 -> eff 0 -> commodity_charge 0; amount_due = 0 + 1538 + 1200 = 2738
    rs, acct, meter, read, issued = fx.setup_issued_bill(pga_commodity=40, pga_refund=50)
    assert issued["commodity_charge_cents"] == 0, f"got {issued['commodity_charge_cents']}"
    assert issued["amount_due_cents"] == 2738, f"got {issued['amount_due_cents']}"


def test_therm_meter_no_btu_conversion(api):
    """PRD 3.4: "for a THERM meter, the register already reads in therms, so therms_consumed
    is the raw delta directly."

    Design: Corner/calculations/therm_meter_register_delta_no_btu_conversion
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], uom="THERM", install_index=0)
    fx.set_meter(acct["id"], meter["id"], completed_index=0)
    read = fx.post_read(meter["id"], 100, "2026-02-28T00:00:00.000Z")
    assert read["ccf_consumed"] == 100, f"got {read['ccf_consumed']}"
    assert read["therms_consumed"] == 100.0, f"got {read['therms_consumed']}"


def test_budget_installment_round_half_up_division(api):
    """PRD 3.7: "The plan's flat monthly_installment_cents is set at enrollment to
    projected_annual_cents divided by twelve, rounded half up to whole cents."

    Design: Corner/calculations/budget_installment_round_half_up_division
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    plan = fx.enroll_budget_plan(acct["id"], anchor_month="2026-02", projected_annual_cents=100000)
    # 100000 / 12 = 8333.33.. -> 8333
    assert plan["monthly_installment_cents"] == 8333, f"got {plan['monthly_installment_cents']}"


def test_low_income_tier2_boundary_at_1_5_fpl(api):
    """PRD 3.8: "otherwise if the ratio is at or below 1.50 it is TIER_2 (moderate need);
    otherwise the tier is NONE. Both boundaries are inclusive."

    Design: Corner/calculations/low_income_tier2_boundary_at_1_5_fpl
    """
    # FPL household-1 = 1509000; 1.5x = 2263500 -> ratio exactly 1.50 -> TIER_2
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    credit = fx.submit_low_income_credit(acct["id"], household_size=1, annual_income_cents=2263500)
    assert credit["tier"] == "TIER_2", f"got {credit['tier']}"


def test_deposit_commercial_delinquency_multiplier(api):
    """PRD 3.11: "the base is 15,000 cents for a RESIDENTIAL account and 40,000 cents for a
    COMMERCIAL account; and when the reason is DELINQUENCY, that base is multiplied by 1.5
    and rounded half up to whole cents."

    Design: Corner/calculations/deposit_requirement_commercial_base_and_delinquency_multiplier
    """
    rs = fx.create_rate_schedule(customer_class="COMMERCIAL", fixed_customer_charge_cents=4000,
                                 distribution_rate_cents_per_therm=20)
    acct = fx.create_account(rs["id"])
    resp = api.create_deposit(acct["id"], {"reason": "DELINQUENCY"}, headers=CS)
    data = validate_success(resp, 201)
    assert data["amount_cents"] == 60000, f"got {data['amount_cents']}"
    assert data["status"] == "REQUIRED", f"got {data['status']}"


def test_deposit_waived_by_good_payment_history(api):
    """PRD 3.11: "The required amount is 0 — and the deposit is therefore created already
    WAIVED rather than REQUIRED — when either the account is enrolled in low-income assistance
    ... or the account has accumulated at least twelve consecutive on-time payments".

    Design: Corner/calculations/deposit_requirement_waived_by_good_payment_history
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.inject_ontime_count(acct["id"], 12)
    resp = api.create_deposit(acct["id"], {"reason": "NEW_SERVICE"}, headers=CS)
    data = validate_success(resp, 201)
    assert data["amount_cents"] == 0, f"got {data['amount_cents']}"
    assert data["status"] == "WAIVED", f"got {data['status']}"


def test_ticket_severity_grade2_odor_indoors(api):
    """PRD 3.13: "an outdoor leak or an indoor odor is GRADE_2 with a two-hundred-forty-minute
    target".

    Design: Corner/calculations/ticket_severity_grade2_odor_indoors_sla
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    ticket = fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=True)
    assert ticket["severity"] == "GRADE_2", f"got {ticket['severity']}"
    assert ticket["response_due_minutes"] == 240, f"got {ticket['response_due_minutes']}"


def test_ticket_severity_carbon_monoxide_grade1(api):
    """PRD 3.13: "An indoor leak, and any carbon-monoxide report, is GRADE_1 with a
    sixty-minute response target".

    Design: Corner/calculations/ticket_severity_carbon_monoxide_grade1
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    ticket = fx.open_ticket(meter["id"], account_id=acct["id"], kind="CARBON_MONOXIDE",
                            reported_indoors=False)
    assert ticket["severity"] == "GRADE_1", f"got {ticket['severity']}"
    assert ticket["response_due_minutes"] == 60, f"got {ticket['response_due_minutes']}"


def test_payment_on_time_inclusive_of_due_date(api):
    """PRD 3.12: "A payment is considered on-time when its posted_date is on or before the
    target bill's due_date — paying on the due date itself counts as on-time — and this is
    recorded on the payment's on_time flag."

    Design: Corner/calculations/payment_on_time_inclusive_of_due_date
    """
    # issue clock 2026-02-15 + 21 days -> due 2026-03-08; pay exactly on 2026-03-08.
    rs, acct, meter, read, issued = fx.setup_issued_bill(read_date="2026-02-14T00:00:00.000Z")
    pay = fx.pay_off_bill(acct["id"], issued["id"], amount_cents=6326,
                          posted_date="2026-03-08T00:00:00.000Z")
    assert pay["on_time"] is True, f"got {pay['on_time']}"
    bill = get_success_data(api.get_bill(issued["id"], headers=ADMIN))
    assert bill["status"] == "PAID", f"got {bill['status']}"
    acct_after = fx.get_account(acct["id"])
    assert acct_after["consecutive_ontime_payments"] == 1, (
        f"got {acct_after['consecutive_ontime_payments']}")
