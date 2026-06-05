"""Eligibility determination math: MAGI income test, the non-MAGI asset test,
the FPL-percentage decision, and their boundary behavior.

All literal expected values are copied from the design indices, which pre-computed
them from the pinned round-then-sum MAGI algorithm and the inclusive thresholds.
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    get_success_data, validate_success,
    setup_application_under_review,
    setup_config, open_application, add_member, add_income, add_asset,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]


def _run_det(app_id):
    return validate_success(api.run_determination(app_id, CW), 201)


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_magi_point_in_time_vs_projected_annual_diverge():
    """PRD §3.4: "Under the `POINT_IN_TIME` variant, the member's annual figure
    is the sum of the `monthly_amount_cents` across those countable sources
    multiplied by twelve, then rounded half-up to whole cents. Under the
    `PROJECTED_ANNUAL` variant, the member's annual figure is instead the sum of
    the `projected_annual_cents` across those countable sources, rounded half-up
    to whole cents; because projected figures need not equal twelve times the
    monthly amounts, the same household can yield a different total under each
    variant."

    Design: Difficulty/dual_variant_calc/magi_point_in_time_vs_projected_annual_diverge
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Ana Diaz"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Ana Diaz", "age": 30, "relationship": "SELF"}, CW))
    api.add_member(hh["id"], {"full_name": "Bo Diaz", "age": 28, "relationship": "SPOUSE"}, CW)
    api.add_income_source(
        mem["id"],
        {"income_type": "WAGES", "monthly_amount_cents": 120000, "projected_annual_cents": 1500000},
        CW)

    app_pit = get_success_data(api.create_application(
        hh["id"], {"pathway": "MAGI", "magi_variant": "POINT_IN_TIME"}, CW))
    api.submit_application(app_pit["id"], APP)
    api.claim_review(app_pit["id"], CW)

    app_proj = get_success_data(api.create_application(
        hh["id"], {"pathway": "MAGI", "magi_variant": "PROJECTED_ANNUAL"}, CW))
    api.submit_application(app_proj["id"], APP)
    api.claim_review(app_proj["id"], CW)

    det_pit = _run_det(app_pit["id"])
    det_proj = _run_det(app_proj["id"])

    assert det_pit["magi_annual_cents"] == 1339000
    assert det_pit["fpl_percentage"] == 66
    assert det_proj["magi_annual_cents"] == 1399000
    assert det_proj["fpl_percentage"] == 69
    assert det_pit["magi_annual_cents"] != det_proj["magi_annual_cents"]


def test_magi_variant_divergence_same_household():
    """PRD §3.4: "because projected figures need not equal twelve times the
    monthly amounts, the same household can yield a different total under each
    variant."

    Design: Difficulty/dual_variant_calc/magi_point_in_time_vs_projected_annual_diverge
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Ana Diaz"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Ana Diaz", "age": 30, "relationship": "SELF"}, CW))
    api.add_member(hh["id"], {"full_name": "Bo Diaz", "age": 28, "relationship": "SPOUSE"}, CW)
    api.add_income_source(
        mem["id"],
        {"income_type": "WAGES", "monthly_amount_cents": 120000, "projected_annual_cents": 1500000},
        CW)

    app_pit = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app_pit["id"], APP)
    api.claim_review(app_pit["id"], CW)
    app_proj = open_application(hh["id"], magi_variant="PROJECTED_ANNUAL")
    api.submit_application(app_proj["id"], APP)
    api.claim_review(app_proj["id"], CW)

    det_pit = _run_det(app_pit["id"])
    det_proj = _run_det(app_proj["id"])
    # POINT_IN_TIME annualizes 120000*12 = 1440000; PROJECTED uses 1500000 directly.
    assert det_pit["magi_annual_cents"] == 1339000
    assert det_proj["magi_annual_cents"] == 1399000


def test_asset_test_abd_vs_standard_limit_diverge():
    """PRD §3.6: "If any counted member has `is_disabled` set to true, the
    ceiling is the state rule's `abd_asset_limit_cents` (the typically lower
    aged-blind-disabled limit, for example $2000); if no counted member is
    disabled, the ceiling is the `standard_asset_limit_cents`."
    PRD §3.6: "The household passes the asset test when its
    `countable_assets_cents` is less than or equal to the chosen ceiling — the
    boundary is inclusive, so a total exactly equal to the limit is eligible."

    Design: Difficulty/dual_variant_calc/asset_test_abd_vs_standard_limit_diverge
    """
    setup_config(state="CA")

    def build_assets_household(name, disabled):
        hh = get_success_data(api.create_household(
            {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": name}, CW))
        api.add_member(hh["id"],
                       {"full_name": name, "age": 67 if disabled else 40,
                        "relationship": "SELF", "is_disabled": disabled}, CW)
        for atype, val in [("CASH", 250000), ("HOME", 5000000),
                           ("VEHICLE", 800000), ("BURIAL_FUND", 200000)]:
            api.add_asset(hh["id"], {"asset_type": atype, "value_cents": val}, CW)
        app = get_success_data(api.create_application(hh["id"], {"pathway": "NON_MAGI"}, CW))
        api.submit_application(app["id"], APP)
        api.claim_review(app["id"], CW)
        return app

    app_abd = build_assets_household("Abe Disabled", True)
    app_std = build_assets_household("Stan Standard", False)

    det_abd = _run_det(app_abd["id"])
    det_std = _run_det(app_std["id"])

    # countable = 250000 + 0 (home) + 0 (one vehicle) + 50000 (burial above 150000 cap) = 300000
    assert det_abd["countable_assets_cents"] == 300000
    assert det_abd["decision"] == "INELIGIBLE"
    assert det_abd["decision_reason"] == "ASSETS_OVER_LIMIT"
    assert det_std["countable_assets_cents"] == 300000
    assert det_std["decision"] == "ELIGIBLE"
    assert det_std["decision_reason"] == "ASSETS_UNDER_LIMIT"


def test_asset_test_disability_flips_outcome():
    """PRD §3.6: "Because identical assets can clear one limit and fail the
    other, the disability status alone can flip the outcome."

    Design: Difficulty/dual_variant_calc/asset_test_abd_vs_standard_limit_diverge
    """
    setup_config(state="CA")

    def build(name, disabled):
        hh = get_success_data(api.create_household(
            {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": name}, CW))
        api.add_member(hh["id"],
                       {"full_name": name, "age": 50, "relationship": "SELF",
                        "is_disabled": disabled}, CW)
        for atype, val in [("CASH", 250000), ("HOME", 5000000),
                           ("VEHICLE", 800000), ("BURIAL_FUND", 200000)]:
            api.add_asset(hh["id"], {"asset_type": atype, "value_cents": val}, CW)
        app = get_success_data(api.create_application(hh["id"], {"pathway": "NON_MAGI"}, CW))
        api.submit_application(app["id"], APP)
        api.claim_review(app["id"], CW)
        return _run_det(app["id"])

    det_disabled = build("Dis D", True)
    det_not = build("Not N", False)
    assert det_disabled["decision"] == "INELIGIBLE"
    assert det_not["decision"] == "ELIGIBLE"


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_magi_multi_input_nonlinear_aggregation():
    """PRD §3.4: "The per-member rounded figures are then summed across all
    counted members to give the household's gross annual income — the rounding
    happens per member before this summation, never after."
    PRD §3.2: "the server derives the `is_magi_countable` flag from the
    `income_type`, treating `CHILD_SUPPORT`, `TANF`, and `GIFT` as non-countable
    and every other type as countable."

    Design: Difficulty/combinatorial_formula/magi_multi_input_nonlinear_aggregation_mode_a
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Adult A"}, CW))
    mem_a = get_success_data(api.add_member(
        hh["id"], {"full_name": "Adult A", "age": 35, "relationship": "SELF"}, CW))
    mem_b = get_success_data(api.add_member(
        hh["id"], {"full_name": "Adult B", "age": 33, "relationship": "SPOUSE"}, CW))
    api.add_member(hh["id"], {"full_name": "Child C", "age": 7, "relationship": "CHILD"}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "WAGES", "monthly_amount_cents": 90000}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "CHILD_SUPPORT", "monthly_amount_cents": 50000}, CW)
    api.add_income_source(mem_b["id"], {"income_type": "WAGES", "monthly_amount_cents": 70000}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["magi_annual_cents"] == 1793000
    assert det["fpl_percentage"] == 70
    assert det["applicable_threshold_pct"] == 138
    assert det["decision"] == "ELIGIBLE"


def test_magi_round_per_member_then_sum_order():
    """PRD §2.7: "each member's income is annualized and rounded to whole cents
    first, on a per-member basis, and only then are the rounded per-member
    amounts summed for the household — this is round-then-sum, never
    sum-then-round. The 5% federal-poverty-level income disregard is rounded
    half-up exactly once, applied to the household total at the very end."

    Design: Difficulty/combinatorial_formula/magi_round_per_member_then_sum_mode_b
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Adult A"}, CW))
    mem_a = get_success_data(api.add_member(
        hh["id"], {"full_name": "Adult A", "age": 35, "relationship": "SELF"}, CW))
    mem_b = get_success_data(api.add_member(
        hh["id"], {"full_name": "Adult B", "age": 33, "relationship": "SPOUSE"}, CW))
    api.add_member(hh["id"], {"full_name": "Child C", "age": 7, "relationship": "CHILD"}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "WAGES", "monthly_amount_cents": 45000, "projected_annual_cents": 540000}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "SELF_EMPLOYMENT", "monthly_amount_cents": 45000, "projected_annual_cents": 540000}, CW)
    api.add_income_source(mem_b["id"], {"income_type": "WAGES", "monthly_amount_cents": 70000, "projected_annual_cents": 840000}, CW)
    app = open_application(hh["id"], magi_variant="PROJECTED_ANNUAL")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    # gross = 1080000 + 840000 = 1920000; disregard 5% of fpl_base(3)=2540000 → 127000;
    # magi = 1793000
    assert det["magi_annual_cents"] == 1793000
    assert det["fpl_percentage"] == 70


def test_magi_combinatorial_child_support_excluded_from_aggregation():
    """PRD §3.4: "the system gathers that member's income sources whose
    `is_magi_countable` is true and computes that member's annualized income."
    PRD §3.2: "treating `CHILD_SUPPORT`, `TANF`, and `GIFT` as non-countable and
    every other type as countable."

    The 50000/mo CHILD_SUPPORT on adult A must NOT enter the aggregation: the
    household magi stays 1793000, exactly as if the non-countable source were
    absent.

    Design: Difficulty/combinatorial_formula/magi_multi_input_nonlinear_aggregation_mode_a
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Adult A"}, CW))
    mem_a = get_success_data(api.add_member(
        hh["id"], {"full_name": "Adult A", "age": 35, "relationship": "SELF"}, CW))
    mem_b = get_success_data(api.add_member(
        hh["id"], {"full_name": "Adult B", "age": 33, "relationship": "SPOUSE"}, CW))
    api.add_member(hh["id"], {"full_name": "Child C", "age": 7, "relationship": "CHILD"}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "WAGES", "monthly_amount_cents": 90000}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "CHILD_SUPPORT", "monthly_amount_cents": 50000}, CW)
    api.add_income_source(mem_b["id"], {"income_type": "WAGES", "monthly_amount_cents": 70000}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    # (90000+70000 are the only countable monthlies): per-member annualize then sum,
    # minus the 5% disregard on fpl_base(3)=2540000 (127000) → 1793000.
    assert det["magi_annual_cents"] == 1793000


def test_magi_projected_annual_disregard_applied_once_at_end():
    """PRD §2.7: "The 5% federal-poverty-level income disregard is rounded half-up
    exactly once, applied to the household total at the very end."
    PRD §3.4: "The disregard amount is five percent of the household's 100%-FPL
    base income for its size ... and that five-percent product is rounded half-up
    to whole cents. The household's annual MAGI is the gross annual income minus
    this rounded disregard".

    A single household-level disregard (127000) — not a per-member split — yields
    magi 1793000 from gross 1920000.

    Design: Difficulty/combinatorial_formula/magi_round_per_member_then_sum_mode_b
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Once O"}, CW))
    mem_a = get_success_data(api.add_member(
        hh["id"], {"full_name": "Once O", "age": 35, "relationship": "SELF"}, CW))
    mem_b = get_success_data(api.add_member(
        hh["id"], {"full_name": "Twice T", "age": 33, "relationship": "SPOUSE"}, CW))
    api.add_member(hh["id"], {"full_name": "Kid K", "age": 7, "relationship": "CHILD"}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "WAGES", "monthly_amount_cents": 45000, "projected_annual_cents": 540000}, CW)
    api.add_income_source(mem_a["id"], {"income_type": "SELF_EMPLOYMENT", "monthly_amount_cents": 45000, "projected_annual_cents": 540000}, CW)
    api.add_income_source(mem_b["id"], {"income_type": "WAGES", "monthly_amount_cents": 70000, "projected_annual_cents": 840000}, CW)
    app = open_application(hh["id"], magi_variant="PROJECTED_ANNUAL")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    # gross 1920000 - single disregard 127000 = 1793000 (a per-member split would differ).
    assert det["magi_annual_cents"] == 1793000


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================
def test_fpl_percentage_inclusive_at_exact_threshold():
    """PRD §3.5: "The household is eligible on income when its `fpl_percentage`
    is less than or equal to the `applicable_threshold_pct` — the boundary is
    inclusive, so a percentage exactly equal to the ceiling is eligible. When
    eligible, `decision` is `ELIGIBLE` and `decision_reason` is
    `INCOME_UNDER_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/fpl_percentage_inclusive_at_exact_threshold
    """
    setup_config(state="TX")
    hh = get_success_data(api.create_household(
        {"state_code": "TX", "fpl_year": 2026, "primary_applicant_name": "Boundary B"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Boundary B", "age": 40, "relationship": "SELF"}, CW))
    api.add_income_source(mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 131250}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["fpl_percentage"] == 100
    assert det["applicable_threshold_pct"] == 100
    assert det["decision"] == "ELIGIBLE"
    assert det["decision_reason"] == "INCOME_UNDER_THRESHOLD"


def test_fpl_percentage_one_over_threshold_ineligible():
    """PRD §3.5: "otherwise `decision` is `INELIGIBLE` and `decision_reason` is
    `INCOME_OVER_THRESHOLD`."

    Boundary X+1: TX adult threshold 100, fpl% 101 → INELIGIBLE.

    Design: Difficulty/boundary_precision_check/fpl_percentage_inclusive_at_exact_threshold
    """
    setup_config(state="TX")
    hh = get_success_data(api.create_household(
        {"state_code": "TX", "fpl_year": 2026, "primary_applicant_name": "Over O"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Over O", "age": 45, "relationship": "SELF"}, CW))
    api.add_income_source(mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 132500}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["fpl_percentage"] == 101
    assert det["decision"] == "INELIGIBLE"
    assert det["decision_reason"] == "INCOME_OVER_THRESHOLD"


def test_zero_countable_income_empty_set_eligible():
    """PRD §3.4: "The household's annual MAGI is the gross annual income minus
    this rounded disregard; if that subtraction would go below zero, the annual
    MAGI is held at zero."
    PRD §3.2: "treating `CHILD_SUPPORT`, `TANF`, and `GIFT` as non-countable and
    every other type as countable."

    Design: Difficulty/boundary_precision_check/zero_countable_income_empty_set_eligible
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Zero Z"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Zero Z", "age": 40, "relationship": "SELF"}, CW))
    api.add_income_source(mem["id"], {"income_type": "CHILD_SUPPORT", "monthly_amount_cents": 200000}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["magi_annual_cents"] == 0
    assert det["fpl_percentage"] == 0
    assert det["decision"] == "ELIGIBLE"


def test_zero_countable_income_under_threshold_reason():
    """PRD §3.5: "When eligible, `decision` is `ELIGIBLE` and `decision_reason`
    is `INCOME_UNDER_THRESHOLD`."

    With an empty countable-income set the floored fpl_percentage is 0, which is
    inclusively under the adult ceiling 138 → INCOME_UNDER_THRESHOLD.

    Design: Difficulty/boundary_precision_check/zero_countable_income_empty_set_eligible
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Empty Inc"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Empty Inc", "age": 40, "relationship": "SELF"}, CW))
    # GIFT is also non-countable, so the countable set is empty here too.
    api.add_income_source(mem["id"], {"income_type": "GIFT", "monthly_amount_cents": 300000}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["magi_annual_cents"] == 0
    assert det["decision"] == "ELIGIBLE"
    assert det["decision_reason"] == "INCOME_UNDER_THRESHOLD"


# ===========================================================================
# Queue B — calculations corner
# ===========================================================================
def test_child_household_uses_child_threshold():
    """PRD §3.5: "A household is treated as an **adult** household — and
    therefore measured against `magi_adult_threshold_pct` — when at least one of
    its counted members has a `relationship` of `SELF`, `SPOUSE`, `OTHER`, or
    `DEPENDENT` and an `age` of at least 19. A household with no such member is
    an all-child household and is measured against `magi_child_threshold_pct`."

    Design: Corner/calculations/child_household_uses_child_threshold
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Childy C"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Childy C", "age": 10, "relationship": "CHILD"}, CW))
    api.add_income_source(mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 120000}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["applicable_threshold_pct"] == 200
    assert det["fpl_percentage"] == 91
    assert det["decision"] == "ELIGIBLE"


def test_income_over_threshold_ineligible_reason():
    """PRD §3.5: "otherwise `decision` is `INELIGIBLE` and `decision_reason` is
    `INCOME_OVER_THRESHOLD`."

    Design: Corner/calculations/income_over_threshold_ineligible_reason
    """
    setup_config(state="TX")
    hh = get_success_data(api.create_household(
        {"state_code": "TX", "fpl_year": 2026, "primary_applicant_name": "Over O"}, CW))
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Over O", "age": 45, "relationship": "SELF"}, CW))
    api.add_income_source(mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 132500}, CW)
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    api.claim_review(app["id"], CW)

    det = _run_det(app["id"])
    assert det["fpl_percentage"] == 101
    assert det["decision"] == "INELIGIBLE"
    assert det["decision_reason"] == "INCOME_OVER_THRESHOLD"
