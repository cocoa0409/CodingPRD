"""Premium, proration, and subsidy arithmetic on the premium invoice.

Covers difficulty instances first_month_full_vs_prorated_premium_diverge,
gross_premium_tiered_standard_vs_disability_branch, and corner calculation
instances (rounding precision, full subsidy, coverage-interval filtering,
proration restriction, disability recompute).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_invoice, assert_enrollment, date_equals,
    create_invoice_payload, set_clock_payload,
    apply_disability_extension_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

_ADMIN = TEST_USERS["plan_administrator_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_first_month_full_month_bills_full_gross(api):
    """PRD §3.5: "For a FULL_MONTH invoice the amount due equals the gross
    premium, charging the entire month even though COBRA coverage may have begun
    mid-month — the standard administrator convention."
    PRD §3.5: "Each invoice computes its gross_premium_cents as the round-half-up
    of the plan's applicable_premium_cents multiplied by one plus a fee
    percentage."

    Design: Difficulty/dual_variant_calc/first_month_full_vs_prorated_premium_diverge
    """
    ctx = fx.setup_elected_enrollment(coverage_loss_date="2026-04-16T00:00:00.000Z")
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-04", proration_mode="FULL_MONTH"), _BILLING)
    inv = validate_success(resp, 201)
    assert_invoice(inv)
    assert inv["gross_premium_cents"] == 61200, f"gross {inv['gross_premium_cents']}"
    assert inv["amount_due_cents"] == 61200, f"FULL_MONTH amount_due {inv['amount_due_cents']}"
    assert inv["proration_mode"] == "FULL_MONTH"


def test_first_month_daily_prorated_bills_partial_gross(api):
    """PRD §3.5: "For the DAILY_PRORATED first month, the system counts the
    calendar days in the coverage-start month, then counts the days covered as
    the days-in-month minus the day-of-month of coverage_start_date plus one
    (i.e. from the start date through month end inclusive), and sets the amount
    due to the round-half-up of the gross premium multiplied by the days covered,
    divided by the days in the month."

    Design: Difficulty/dual_variant_calc/first_month_full_vs_prorated_premium_diverge
    """
    # coverage_loss 2026-04-16 -> April has 30 days, days_covered = 30-16+1 = 15.
    # amount_due = round_half_up(61200 * 15 / 30) = 30600.
    ctx = fx.setup_elected_enrollment(coverage_loss_date="2026-04-16T00:00:00.000Z")
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-04", proration_mode="DAILY_PRORATED"), _BILLING)
    inv = validate_success(resp, 201)
    assert_invoice(inv)
    assert inv["gross_premium_cents"] == 61200, f"gross {inv['gross_premium_cents']}"
    assert inv["amount_due_cents"] == 30600, f"DAILY_PRORATED amount_due {inv['amount_due_cents']}"
    assert inv["proration_mode"] == "DAILY_PRORATED"


def test_subsidy_paid_invoice_locked_after_revoke(api):
    """PRD §3.7: "Invoices that are already PAID keep their applied subsidy, a
    chronological lock that prevents retroactively clawing back coverage that has
    already been settled."

    Design: Difficulty/dual_variant_calc/subsidy_chronological_lock_vs_forward_recompute_diverge
    """
    ctx = fx.setup_active_enrollment()  # April invoiced + paid 61200
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    sub = fx.grant_subsidy(enr_id, 0.65, "2026-05", "2026-12")
    may_inv = fx.create_invoice(acct_id, "2026-05")  # subsidy 39780, owed 21420
    fx.post_payment(acct_id, 21420, "2026-05")        # May fully paid -> PAID
    fx.create_invoice(acct_id, "2026-06")             # June OPEN
    # Revoke the grant after both invoices exist.
    api.revoke_subsidy(sub["id"], _ADMIN)
    may = validate_success(api.get_invoice(may_inv["id"], _ADMIN))
    assert may["status"] == "PAID", f"May status {may['status']}"
    assert may["subsidy_applied_cents"] == 39780, f"May subsidy {may['subsidy_applied_cents']}"


def test_subsidy_future_open_invoice_recomputes_to_zero_after_revoke(api):
    """PRD §3.7: "When an administrator revokes a grant, it moves to REVOKED and
    the system recomputes subsidy on future invoices only — those whose
    coverage_month is later than the current clock's month — reassigning each to
    the next matching ACTIVE grant in chronological order, or to 0 if none
    remains."

    Design: Difficulty/dual_variant_calc/subsidy_chronological_lock_vs_forward_recompute_diverge
    """
    ctx = fx.setup_active_enrollment()  # clock at 2026-04-10
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    sub = fx.grant_subsidy(enr_id, 0.65, "2026-05", "2026-12")
    fx.create_invoice(acct_id, "2026-05")
    fx.post_payment(acct_id, 21420, "2026-05")
    jun_inv = fx.create_invoice(acct_id, "2026-06")  # June is future (> April clock month)
    api.revoke_subsidy(sub["id"], _ADMIN)
    jun = validate_success(api.get_invoice(jun_inv["id"], _ADMIN))
    assert jun["subsidy_applied_cents"] == 0, f"June subsidy {jun['subsidy_applied_cents']}"
    assert jun["beneficiary_owed_cents"] == 61200, f"June owed {jun['beneficiary_owed_cents']}"


def test_disability_month_19_bills_at_150_percent_tier(api):
    """PRD §3.5: "for a disability-extended enrollment it becomes
    disability_admin_fee_pct for the months whose coverage_month_index falls in
    the inclusive range from 19 through 29 — the 150-percent disability tier."

    Design: Difficulty/combinatorial_formula/gross_premium_tiered_standard_vs_disability_branch
    """
    ctx = fx.setup_active_enrollment()  # April paid, ACTIVE, 18-month TERMINATION
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    fx.set_clock("2026-05-01T00:00:00.000Z")
    fx.apply_disability_extension(enr_id, "2026-05-01T00:00:00.000Z")
    fx.set_clock("2027-10-01T00:00:00.000Z")
    resp = api.create_invoice(acct_id, create_invoice_payload("2027-10"), _BILLING)  # month index 19
    inv = validate_success(resp, 201)
    assert inv["coverage_month_index"] == 19, f"index {inv['coverage_month_index']}"
    assert inv["gross_premium_cents"] == 90000, f"disability gross {inv['gross_premium_cents']}"
    assert inv["amount_due_cents"] == 90000, f"disability amount_due {inv['amount_due_cents']}"


def test_standard_month_bills_at_102_percent_tier(api):
    """PRD §3.5: "Ordinary months — index 1 through 18 (or 1 through 36 for a
    36-month event), and any month of a non-extended enrollment — apply the
    standard load, charging 102 percent of the applicable premium; the
    disability-extension months 19 through 29 of a disability-extended enrollment
    apply the heavier load, charging 150 percent."

    Design: Difficulty/combinatorial_formula/gross_premium_tiered_standard_vs_disability_branch
    """
    ctx = fx.setup_elected_enrollment()  # 60000 applicable, no extension
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-04"), _BILLING)  # index 1, standard
    inv = validate_success(resp, 201)
    assert inv["coverage_month_index"] == 1
    assert inv["gross_premium_cents"] == 61200, f"standard gross {inv['gross_premium_cents']}"
    assert inv["amount_due_cents"] == 61200, f"standard amount_due {inv['amount_due_cents']}"


def test_gross_premium_rounds_half_up_on_odd_cents(api):
    """PRD §2.6: "Wherever a calculation produces a fractional cent (applying an
    administrative load, prorating a partial first month, applying a subsidy
    percentage, or computing a shortfall allowance), the result is rounded to the
    nearest whole cent using the round-half-up method: a value whose fractional
    part is exactly one-half rounds up to the next whole cent."

    Design: Corner/calculations/gross_premium_rounds_half_up_odd_cents
    """
    # applicable 49999 @2% = 50998.98 -> round_half_up -> 50999
    ctx = fx.setup_elected_enrollment(applicable_premium_cents=49999)
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-04"), _BILLING)
    inv = validate_success(resp, 201)
    assert inv["gross_premium_cents"] == 50999, f"rounded gross {inv['gross_premium_cents']}"


def test_full_subsidy_zeroes_beneficiary_owed(api):
    """PRD §3.7: "If a grant matches, the invoice's subsidy_applied_cents is the
    round-half-up of its amount_due_cents multiplied by that grant's subsidy_pct;
    if none matches, the subsidy applied is 0. Either way, beneficiary_owed_cents
    is amount_due_cents minus the subsidy applied."

    Design: Corner/calculations/subsidy_full_100pct_zeroes_beneficiary_owed
    """
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    fx.grant_subsidy(enr_id, 1.0, "2026-05", "2026-05")
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-05"), _BILLING)
    inv = validate_success(resp, 201)
    assert inv["subsidy_applied_cents"] == 61200, f"subsidy {inv['subsidy_applied_cents']}"
    assert inv["beneficiary_owed_cents"] == 0, f"owed {inv['beneficiary_owed_cents']}"


def test_invoice_before_coverage_start_month_rejected(api):
    """PRD §3.5: "The coverage_month must fall within the enrollment's coverage
    interval — from the coverage-start month through the scheduled_end_date month
    — and an invoice for a month outside that interval is rejected with
    ERR_INVALID_COVERAGE_MONTH."

    Design: Corner/calculations/invoice_outside_coverage_interval_returns_invalid_coverage_month
    """
    ctx = fx.setup_elected_enrollment()  # coverage_start 2026-04
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-03"), _BILLING)
    validate_error(resp, "ERR_INVALID_COVERAGE_MONTH")


def test_daily_proration_on_non_first_month_rejected(api):
    """PRD §3.5: "proration_mode is one of FULL_MONTH (the default) or
    DAILY_PRORATED, and only the first coverage month may be DAILY_PRORATED;
    requesting daily proration for any month other than month 1 is also rejected
    with ERR_INVALID_COVERAGE_MONTH."

    Design: Corner/calculations/prorated_requested_for_non_first_month_rejected
    """
    ctx = fx.setup_active_enrollment()  # April invoiced+paid; May is index 2
    acct_id = ctx["account"]["id"]
    resp = api.create_invoice(acct_id, create_invoice_payload("2026-05", proration_mode="DAILY_PRORATED"), _BILLING)
    validate_error(resp, "ERR_INVALID_COVERAGE_MONTH")


def test_disability_extension_recomputes_scheduled_end_to_29_months(api):
    """PRD §3.8: "On success, extension_months is set to 11, disability_extension
    becomes true, and scheduled_end_date is recomputed as the coverage_start_date
    advanced by 29 months and stepped back by one day."

    Design: Corner/calculations/disability_extension_recomputes_scheduled_end_to_29mo
    """
    ctx = fx.setup_active_enrollment()  # coverage_start 2026-04-01
    enr_id = ctx["enrollment"]["id"]
    fx.set_clock("2026-05-15T00:00:00.000Z")
    resp = api.apply_disability_extension(
        enr_id, apply_disability_extension_payload("2026-05-01T00:00:00.000Z"), _ADMIN
    )
    enr = validate_success(resp, 200)
    assert_enrollment(enr)
    assert enr["extension_months"] == 11, f"extension_months {enr['extension_months']}"
    assert enr["disability_extension"] is True
    # coverage_start 2026-04-01 + 29 months - 1 day = 2028-08-31
    assert date_equals(enr["scheduled_end_date"], "2028-08-31"), (
        f"scheduled_end_date {enr['scheduled_end_date']}"
    )
