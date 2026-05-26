"""Tests covering the tier-determination calculation: direct-certification vs
application-based variants, rounding-order at exact boundaries, and the
inclusive `<=` boundary at the free-tier ceiling.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_clean_world,
    setup_approved_application,
    setup_direct_cert_household,
    create_household,
    create_student,
    create_application,
    submit_application,
    start_review,
    approve_application,
    create_menu_item,
    create_service_transaction,
    create_direct_cert_eligibility,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Difficulty rule 1 / instance 1 — paid_charge variants: DIRECT_CERTIFICATION
# vs APPLICATION-sourced eligibility at the SAME income/MenuItem produces
# different paid_charge_cents.
# ---------------------------------------------------------------------

def test_paid_charge_zero_under_direct_certification_at_paid_eligible_income(api):
    """PRD §3.5: "If `applied_tier` is `FREE`, the per-tier amount is zero;
    the calculation short-circuits and `paid_charge_cents` is zero."
    PRD §3.5: "a `DIRECT_CERTIFICATION` determination's `tier` is pinned to
    `FREE`, so the per-tier amount is always zero and the allergen surcharge
    never applies."

    Design: Difficulty/dual_variant_calc/paid_charge_variants_application_vs_direct_certification
    """
    set_clock("2026-01-15T12:00:00.000Z")
    # Household A: direct certification — gets FREE regardless of income.
    hh_a = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu_a = create_student(hh_a["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh_a["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=300,
        federal_reimbursement_free_cents=470,
        federal_reimbursement_reduced_cents=430,
        federal_reimbursement_paid_cents=70,
        allergens_present=["MILK"],
    )
    res = api.create_service_transaction(
        {"student_id": stu_a["id"], "menu_item_id": menu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    tx = validate_success(res, 201)
    assert tx["applied_tier"] == "FREE", (
        f"DIRECT_CERTIFICATION household must price at FREE; got {tx['applied_tier']!r}"
    )
    assert tx["paid_charge_cents"] == 0, (
        f"FREE-tier paid_charge_cents must be 0; got {tx['paid_charge_cents']}"
    )


def test_paid_charge_reduced_amount_under_approved_application_at_same_income(api):
    """PRD §3.5: "If `applied_tier` is `REDUCED`, the per-tier amount is the
    smaller of (a) the constant `REDUCED_PRICE_CAP_CENTS` of 40 cents and
    (b) the list price multiplied by `REDUCED_DISCOUNT_FACTOR` of 0.10 — that
    is, 10 percent of list price — with the multiplication rounded half-up to
    the nearest whole cent."

    Design: Difficulty/dual_variant_calc/paid_charge_variants_application_vs_direct_certification
    """
    # Household B: NOT direct-cert; income $45,000/yr family of 4 in CA →
    # monthly = 375000 cents; CA fam=4: FPL_monthly = 260000c, thr_free = 338000c,
    # thr_red = 481000c. 375000 between 338000 and 481000 → REDUCED.
    _hh, _stu, approved_app = setup_approved_application(
        clock_iso="2026-01-15T12:00:00.000Z",
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", school_code="ELEM-101",
        decision_reason="verified",
        direct_certification_flag=False,
    )
    assert approved_app["status"] == "APPROVED"
    student = _stu
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=300,
        federal_reimbursement_free_cents=470,
        federal_reimbursement_reduced_cents=430,
        federal_reimbursement_paid_cents=70,
        allergens_present=["MILK"],
    )
    res = api.create_service_transaction(
        {"student_id": student["id"], "menu_item_id": menu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    tx = validate_success(res, 201)
    assert tx["applied_tier"] == "REDUCED", (
        f"$45k/yr family-of-4 CA must price at REDUCED; got {tx['applied_tier']!r}"
    )
    # 10% of 300 = 30, min(40, 30) = 30
    assert tx["paid_charge_cents"] == 30, (
        f"REDUCED tier 300c list_price → 30c (min(40, 10%*300)); got {tx['paid_charge_cents']}"
    )


# ---------------------------------------------------------------------
# Difficulty rule 2 / instance 2 — tier_determination rounding order (mode b)
# round_half_up(annual/12) BEFORE compare. Boundary at annual=4,056,006 cents
# yields monthly = round_half_up(338000.5) = 338001 > thr_free=338000 → REDUCED.
# ---------------------------------------------------------------------

def test_tier_determination_rounds_annual_division_half_up_before_compare(api):
    """PRD §3.3: "Otherwise the server computes the household's monthly income
    in cents by taking `snapshot_annual_income_cents`, dividing by 12, and
    rounding half-up to the nearest whole cent; this rounding step happens
    before any comparison, so a household at an exact annual boundary may land
    on a different tier than the same household evaluated by a sum-then-round
    procedure."

    Design: Difficulty/combinatorial_formula/tier_determination_rounding_order_mode_b
    """
    _hh, _stu, approved_app = setup_approved_application(
        clock_iso="2026-01-15T12:00:00.000Z",
        family_size=4, annual_income_cents=4_056_006,  # round_half_up(4056006/12)=338001
        address_state="CA",
        decision_reason="boundary test",
        direct_certification_flag=False,
    )
    assert approved_app["status"] == "APPROVED"
    # The created EligibilityDetermination must have tier == REDUCED
    # (NOT FREE — the +6 cents pushes round_half_up over the 338000 threshold).
    res = api.list_household_eligibility_determinations(
        _hh["id"], TEST_USERS["district_reviewer_headers"]
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    assert len(rows) >= 1
    active = [r for r in rows if r["lifecycle_status"] == "ACTIVE"]
    assert len(active) == 1, f"expected exactly one ACTIVE determination, got {len(active)}"
    assert active[0]["tier"] == "REDUCED", (
        f"annual=4,056,006 must round to monthly=338001 > 338000 → REDUCED; "
        f"got tier={active[0]['tier']!r}"
    )


def test_tier_determination_at_below_round_boundary_yields_free_tier(api):
    """PRD §3.3: "the server computes the household's monthly income in cents
    by taking `snapshot_annual_income_cents`, dividing by 12, and rounding
    half-up to the nearest whole cent; this rounding step happens before any
    comparison".

    Design: Difficulty/combinatorial_formula/tier_determination_rounding_order_mode_b
    """
    # Boundary - 6 cents: annual=4055994 → 4055994/12 = 337999.5 → round_half_up = 338000.
    # 338000 <= thr_free 338000 → FREE.
    _hh, _stu, approved_app = setup_approved_application(
        clock_iso="2026-01-15T12:00:00.000Z",
        family_size=4, annual_income_cents=4_055_994,
        address_state="CA",
        decision_reason="boundary minus six",
        direct_certification_flag=False,
    )
    res = api.list_household_eligibility_determinations(
        _hh["id"], TEST_USERS["district_reviewer_headers"]
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    active = [r for r in rows if r["lifecycle_status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["tier"] == "FREE", (
        f"annual=4,055,994 must round to monthly=338000 <= 338000 → FREE; "
        f"got tier={active[0]['tier']!r}"
    )


# ---------------------------------------------------------------------
# Difficulty rule 6 / instance 1 — FPL boundary at exact threshold.
# household_monthly <= threshold_free uses INCLUSIVE `<=`.
# ---------------------------------------------------------------------

def test_free_tier_boundary_inclusive_at_exact_threshold(api):
    """PRD §3.3: "if household monthly cents is at most the free-tier ceiling,
    the tier is `FREE`; otherwise if it is at most the reduced-tier ceiling,
    the tier is `REDUCED`; otherwise the tier is `PAID`. Both inequalities are
    inclusive at the upper boundary, so a household landing exactly on the
    free-tier ceiling is `FREE`."

    Design: Difficulty/boundary_precision_check/fpl_free_tier_boundary_at_exact_threshold
    """
    # annual=4056000 → monthly = 4056000/12 = 338000 exactly.
    # CA fam=4: FPL_monthly=260000c → thr_free = floor(260000*1.30) = 338000.
    # 338000 <= 338000 → FREE (inclusive).
    _hh, _stu, approved_app = setup_approved_application(
        clock_iso="2026-04-10T09:00:00.000Z",
        family_size=4, annual_income_cents=4_056_000,
        address_state="CA",
        decision_reason="exact-boundary",
        direct_certification_flag=False,
    )
    res = api.list_household_eligibility_determinations(
        _hh["id"], TEST_USERS["district_reviewer_headers"]
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    active = [r for r in rows if r["lifecycle_status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["tier"] == "FREE", (
        "at exact free-tier ceiling household_monthly==threshold_free must be FREE "
        f"(inclusive `<=`); got tier={active[0]['tier']!r}"
    )


def test_free_tier_boundary_one_cent_above_yields_reduced(api):
    """PRD §3.3: "if household monthly cents is at most the free-tier ceiling,
    the tier is `FREE`; otherwise if it is at most the reduced-tier ceiling,
    the tier is `REDUCED`".

    Design: Difficulty/boundary_precision_check/fpl_free_tier_boundary_at_exact_threshold
    """
    # annual=4056012 → monthly = 4056012/12 = 338001 exactly (no rounding needed).
    # CA fam=4: thr_free=338000. 338001 > 338000 → REDUCED.
    _hh, _stu, approved_app = setup_approved_application(
        clock_iso="2026-04-10T09:00:00.000Z",
        family_size=4, annual_income_cents=4_056_012,
        address_state="CA",
        decision_reason="one-cent-above-boundary",
        direct_certification_flag=False,
    )
    res = api.list_household_eligibility_determinations(
        _hh["id"], TEST_USERS["district_reviewer_headers"]
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    active = [r for r in rows if r["lifecycle_status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["tier"] == "REDUCED", (
        "one cent over free-tier ceiling must yield REDUCED, not FREE; "
        f"got tier={active[0]['tier']!r}"
    )
