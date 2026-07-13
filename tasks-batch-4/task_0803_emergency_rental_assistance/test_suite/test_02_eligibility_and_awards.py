"""Income eligibility and award-calculation depth tests.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml queue-A instances for dual-variant
calculations, combinatorial award formulas, and the income boundary.
"""
from test_helpers import (
    get_success_data, make_caseworker_headers,
    build_application, build_approved_application,
)


# =====================================================================
# Rule 1 — dual_variant_calc
# =====================================================================

def test_countable_income_excludes_non_countable_sources(api):
    """PRD §3.4: "The application's `countable_monthly_income_cents` is the sum of
    `monthly_amount_cents` across only those income sources whose `countable` flag is
    true — the non-countable public-benefit types (`SSI`, `TANF`, `CHILD_SUPPORT`)
    never enter this sum."

    Design: Difficulty/dual_variant_calc/income_countable_vs_gross_eligibility
    """
    ctx = build_approved_application(
        api,
        income_limits={"1": 500000, "2": 566667, "3": 641667, "4": 708334},
        household_size=2,
        income_sources=(("WAGES", 500000), ("SSI", 100000)),
        approver_id="cw-approver-1",
    )
    app = ctx["application"]
    assert app["countable_monthly_income_cents"] == 500000
    assert app["status"] == "APPROVED"


def test_countable_income_eligibility_flag_true(api):
    """PRD §3.4: "The household is income-eligible — `income_eligible` is true —
    exactly when `countable_monthly_income_cents` is less than or equal to that limit."

    Design: Difficulty/dual_variant_calc/income_countable_vs_gross_eligibility
    """
    ctx = build_approved_application(
        api,
        income_limits={"1": 500000, "2": 566667, "3": 641667, "4": 708334},
        household_size=2,
        income_sources=(("WAGES", 500000), ("SSI", 100000)),
        approver_id="cw-approver-1b",
    )
    assert ctx["application"]["income_eligible"] is True


def test_arrears_chronological_fifo_leaves_in_window_balance(api):
    """PRD §3.5: "After the whole ledger is processed, `arrears_owed_cents` is the sum
    of the still-outstanding balances on those `CHARGE` lines whose `month` falls within
    `arrears_start_month` and `arrears_end_month` inclusive; when the arrears window is
    null it is 0."

    Design: Difficulty/dual_variant_calc/arrears_chronological_vs_gross_window
    """
    lines = [
        {"month": "2025-11", "line_type": "CHARGE", "charge_cents": 200000},
        {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 200000},
        {"month": "2025-12", "line_type": "PAYMENT", "payment_cents": 100000},
        {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 200000},
    ]
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-2",
        income_sources=(("WAGES", 500000),),
        arrears_start_month="2025-12", arrears_end_month="2026-01",
        ledger_lines=lines,
    )
    app = ctx["application"]
    assert app["arrears_owed_cents"] == 400000
    assert app["status"] == "APPROVED"


def test_arrears_award_pins_fifo_reconciled_amount(api):
    """PRD §3.6: "The arrears award, `arrears_award_cents`, is the smaller of
    `arrears_owed_cents` (from §3.5) and the product of `arrears_covered_months` and
    the monthly award."

    Design: Difficulty/dual_variant_calc/arrears_chronological_vs_gross_window
    """
    lines = [
        {"month": "2025-11", "line_type": "CHARGE", "charge_cents": 200000},
        {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 200000},
        {"month": "2025-12", "line_type": "PAYMENT", "payment_cents": 100000},
        {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 200000},
    ]
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-2b",
        income_sources=(("WAGES", 500000),),
        arrears_start_month="2025-12", arrears_end_month="2026-01",
        ledger_lines=lines,
    )
    assert ctx["application"]["arrears_award_cents"] == 400000


# =====================================================================
# Rule 2 — combinatorial_formula
# =====================================================================

def test_total_award_double_clamp_sums_arrears_and_prospective(api):
    """PRD §3.6: "The pinned `total_award_cents` is `arrears_award_cents` plus
    `prospective_award_cents`, and `months_awarded` is `arrears_covered_months` plus
    `prospective_months_grantable`."

    Design: Difficulty/combinatorial_formula/total_award_nested_min_double_clamp
    """
    lines = [
        {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 350000},
        {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 350000},
    ]
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-3",
        per_month_max_cents=250000, unit_rent_cents=300000, app_rent_cents=300000,
        income_sources=(("WAGES", 400000),),
        arrears_start_month="2025-12", arrears_end_month="2026-01",
        prospective_start_date="2026-03-01", prospective_end_date="2026-05-31",
        requested_prospective_months=3,
        ledger_lines=lines,
    )
    app = ctx["application"]
    assert app["total_award_cents"] == 1250000
    assert app["months_awarded"] == 5


def test_total_award_arrears_and_prospective_components_clamped(api):
    """PRD §3.6: "The monthly award is the smaller of the application's
    `monthly_rent_cents` and the program's `per_month_max_cents`."

    Design: Difficulty/combinatorial_formula/total_award_nested_min_double_clamp
    """
    lines = [
        {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 350000},
        {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 350000},
    ]
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-3b",
        per_month_max_cents=250000, unit_rent_cents=300000, app_rent_cents=300000,
        income_sources=(("WAGES", 400000),),
        arrears_start_month="2025-12", arrears_end_month="2026-01",
        prospective_start_date="2026-03-01", prospective_end_date="2026-05-31",
        requested_prospective_months=3,
        ledger_lines=lines,
    )
    app = ctx["application"]
    assert app["arrears_award_cents"] == 500000
    assert app["prospective_award_cents"] == 750000


def test_prospective_proration_rounds_per_month_then_sums(api):
    """PRD §2.9: "that per-month prorated amount is rounded half up to the nearest whole
    cent, and the rounding is applied to each month individually before the months are
    summed (round-per-month-then-sum), never by summing unrounded amounts and rounding
    once."

    Design: Difficulty/combinatorial_formula/prospective_proration_round_per_month_then_sum
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-4",
        household_size=1, income_limits={"1": 500000, "2": 566667},
        per_month_max_cents=250000, unit_rent_cents=150000, app_rent_cents=150000,
        income_sources=(("WAGES", 300000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-02", prospective_end_date="2026-05-02",
        requested_prospective_months=3,
        ledger_lines=[],
    )
    assert ctx["application"]["prospective_award_cents"] == 304838


def test_prospective_proration_total_award_and_months(api):
    """PRD §3.6: "The pinned `total_award_cents` is `arrears_award_cents` plus
    `prospective_award_cents`, and `months_awarded` is `arrears_covered_months` plus
    `prospective_months_grantable`."

    Design: Difficulty/combinatorial_formula/prospective_proration_round_per_month_then_sum
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-4b",
        household_size=1, income_limits={"1": 500000, "2": 566667},
        per_month_max_cents=250000, unit_rent_cents=150000, app_rent_cents=150000,
        income_sources=(("WAGES", 300000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-02", prospective_end_date="2026-05-02",
        requested_prospective_months=3,
        ledger_lines=[],
    )
    app = ctx["application"]
    assert app["total_award_cents"] == 304838
    assert app["months_awarded"] == 3


# =====================================================================
# Rule 6 — boundary_precision_check (income boundary)
# =====================================================================

def test_income_exactly_at_ami_limit_is_eligible(api):
    """PRD §3.4: "The household is income-eligible — `income_eligible` is true —
    exactly when `countable_monthly_income_cents` is less than or equal to that limit."

    Design: Difficulty/boundary_precision_check/income_exactly_at_ami_limit_is_eligible
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-11",
        household_size=2, income_limits={"2": 566667},
        income_sources=(("WAGES", 566667),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    app = ctx["application"]
    assert app["income_eligible"] is True
    assert app["countable_monthly_income_cents"] == 566667


def test_income_exactly_at_ami_limit_approves(api):
    """PRD §3.4: "The household is income-eligible — `income_eligible` is true —
    exactly when `countable_monthly_income_cents` is less than or equal to that limit."

    Design: Difficulty/boundary_precision_check/income_exactly_at_ami_limit_is_eligible
    """
    ctx = build_application(
        api, approve=True, approver_id="cw-approver-11b",
        household_size=2, income_limits={"2": 566667},
        income_sources=(("WAGES", 566667),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    assert ctx["application"]["status"] == "APPROVED"
