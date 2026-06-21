"""Award eligibility arithmetic: provisional vs final variants, the multi-input
non-linear formula, the cap-and-offset waterfall rounding order, and the cap
boundary. (Difficulty queue: dual_variant_calc, combinatorial_formula,
boundary_precision_check cap instance.)
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    api_client, TEST_USERS, make_inspector_headers, make_caseworker_headers,
    create_declaration_payload, create_inspector_payload, create_caseworker_payload,
    create_applicant_payload, create_assessment_payload, inspect_assessment_payload,
    create_ihp_case_payload,
    setup_pending_case, setup_approved_case, get_line_item,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ─── dual_variant_calc / provisional_vs_final_award_diverges ───────────────
def test_provisional_gross_at_create_uses_reported_amounts(api):
    """PRD §3.3: "The provisional variant feeds this formula from the applicant's
    self-reported numbers — `reported_repair_cost_cents` as the repair cost,
    `reported_personal_property_cents` as the personal-property loss, and
    `reported_rental_months` as the rental months."
    PRD §3.3: "If the home is `UNINHABITABLE`, the rental-assistance component is the
    monthly Fair Market Rent multiplied by the number of rental months, and the
    replacement component is the smaller of the applicable repair cost and a
    replacement cap of $41,500 (4,150,000 cents), but only when the applicable repair
    cost exceeds the $41,500 repair cap; otherwise the replacement component is zero."

    Reported repair 2,000,000 + personal 1,000,000 + rental (150,000 x 6 = 900,000)
    + replacement 0 (repair <= cap) = provisional gross 3,900,000.

    Design: Difficulty/dual_variant_calc/provisional_vs_final_award_diverges
    """
    ctx = setup_pending_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-A Storms"},
        inspector_badge="INS-A1",
        cw_employee_id="CW-A1",
        applicant_overrides={
            "household_name": "Alpha Household", "household_size": 3,
            "annual_income_cents": 4_000_000,
            "reported_repair_cost_cents": 2_000_000,
            "reported_personal_property_cents": 1_000_000,
            "reported_rental_months": 6,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_200_000,
            "verified_personal_property_cents": 800_000,
            "verified_rental_months": 4,
        },
        monthly_fmr_cents=150_000,
    )
    case = ctx["case"]
    assert case["gross_eligible_cents"] == 3_900_000, (
        f"Provisional gross should be 3,900,000, got {case['gross_eligible_cents']}"
    )


def test_final_gross_at_approve_uses_verified_amounts(api):
    """PRD §3.4: "The final variant runs the same component formula as §3.3 but draws
    its repair cost, personal-property loss, and rental months from the
    inspector-verified figures `verified_repair_cost_cents`,
    `verified_personal_property_cents`, and `verified_rental_months` rather than the
    self-reported ones; the result refreshes `gross_eligible_cents`."
    PRD §3.4: "On a successful approval, each `AwardLineItem` receives its
    `approved_amount_cents` through the cap-and-offset waterfall of §3.6, the line
    items advance to `APPROVED`, `total_approved_cents` is reconciled as the sum of
    approved line amounts, and the applicant advances `ELIGIBILITY_PENDING → ELIGIBLE`."

    Verified repair 1,200,000 + personal 800,000 + rental (150,000 x 4 = 600,000)
    + replacement 0 = final gross 2,600,000; no cap, no DOB => net & total 2,600,000.

    Design: Difficulty/dual_variant_calc/provisional_vs_final_award_diverges
    """
    ctx = setup_approved_case(
        clock="2026-02-01T00:00:00Z",
        decl_overrides={"title": "DR-A Storms"},
        inspector_badge="INS-A1b",
        cw_employee_id="CW-A1b",
        applicant_overrides={
            "household_name": "Alpha Household", "household_size": 3,
            "annual_income_cents": 4_000_000,
            "reported_repair_cost_cents": 2_000_000,
            "reported_personal_property_cents": 1_000_000,
            "reported_rental_months": 6,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_200_000,
            "verified_personal_property_cents": 800_000,
            "verified_rental_months": 4,
        },
        monthly_fmr_cents=150_000,
    )
    case = ctx["case"]
    assert case["gross_eligible_cents"] == 2_600_000, case["gross_eligible_cents"]
    assert case["total_approved_cents"] == 2_600_000, case["total_approved_cents"]
    assert case["net_eligible_cents"] == 2_600_000, case["net_eligible_cents"]


# ─── dual_variant_calc / dob_offset_at_award_vs_at_recoupment_diverges ──────
def test_dob_offset_at_award_counts_only_pre_approval_dob(api):
    """PRD §3.5: "The **at-award** variant, computed when a case is approved, sums the
    `amount_cents` of the applicant's `RECORDED` DOB records whose `received_at` is at
    or before the case's approval time — that is, only duplications already known at
    award time."
    PRD §3.4: "the net entitlement `net_eligible_cents` is the larger of zero and
    `capped_eligible_cents` minus `dob_offset_cents`."

    Gross 1,800,000; one INSURANCE DOB 400,000 received before approval => at-award
    offset 400,000, net 1,400,000.

    Design: Difficulty/dual_variant_calc/dob_offset_at_award_vs_at_recoupment_diverges
    """
    ctx = _approved_case_with_pre_approval_dob()
    case = ctx["case"]
    assert case["dob_offset_cents"] == 400_000, case["dob_offset_cents"]
    assert case["net_eligible_cents"] == 1_400_000, case["net_eligible_cents"]


def test_dob_offset_at_recoupment_includes_late_dob(api):
    """PRD §3.5: "The **at-recoupment** variant, computed after an SBA approval, after
    a late DOB record is added, or after a DOB reversal, sums the `amount_cents` of
    *all* of the applicant's `RECORDED` DOB records regardless of when they were
    received — so a benefit whose `received_at` is later than the case's approval time
    enters the offset only in the at-recoupment variant, and that difference is
    precisely what can drive a recoupment."
    PRD §3.5: "After `total_dob_cents` is recomputed, if the applicant's case is
    `AWARD_APPROVED` or `DISBURSING`, the case's `dob_offset_cents` and
    `net_eligible_cents` are recomputed using the at-recoupment variant."

    A LATE OTHER_FEDERAL DOB 600,000 (received after approve) raises offset to
    1,000,000 and lowers net to 800,000.

    Design: Difficulty/dual_variant_calc/dob_offset_at_award_vs_at_recoupment_diverges
    """
    ctx = _approved_case_with_pre_approval_dob()
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    case_id = ctx["case"]["id"]
    # Late DOB recorded with received_at after the approval time.
    get_success_data(api_client.create_dob_record(
        create_applicant_dob(app_id, "OTHER_FEDERAL", 600_000, "2026-04-01T00:00:00Z"), ADMIN
    ))
    case = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    assert case["dob_offset_cents"] == 1_000_000, case["dob_offset_cents"]
    assert case["net_eligible_cents"] == 800_000, case["net_eligible_cents"]


# ─── combinatorial_formula / award_formula_multi_input_nonlinear_mode_a ─────
def test_habitable_branch_zeroes_rental_and_replacement(api):
    """PRD §3.3: "If the home is `HABITABLE`, both the rental-assistance component and
    the replacement component are zero."
    PRD §3.3: "The repair component is the smaller of the applicable repair cost and a
    per-component repair cap of $41,500 (4,150,000 cents)."

    HABITABLE: verified repair 700,000 + personal 300,000 = gross 1,000,000; rental
    and replacement zeroed despite 5 reported rental months.

    Design: Difficulty/combinatorial_formula/award_formula_multi_input_nonlinear_mode_a
    """
    ctx = setup_approved_case(
        clock="2026-02-10T00:00:00Z",
        decl_overrides={"title": "DR-B2"},
        inspector_badge="INS-B2",
        cw_employee_id="CW-B2",
        applicant_overrides={
            "household_name": "Beta Household", "household_size": 1,
            "annual_income_cents": 2_000_000,
            "reported_repair_cost_cents": 700_000,
            "reported_personal_property_cents": 300_000,
            "reported_rental_months": 5,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 700_000,
            "verified_personal_property_cents": 300_000,
            "verified_rental_months": 5,
        },
        monthly_fmr_cents=150_000,
    )
    case = ctx["case"]
    assert case["gross_eligible_cents"] == 1_000_000, case["gross_eligible_cents"]
    assert case["net_eligible_cents"] == 1_000_000, case["net_eligible_cents"]


def test_habitable_branch_rental_line_item_zero(api):
    """PRD §3.3: "If the home is `HABITABLE`, both the rental-assistance component and
    the replacement component are zero."
    PRD §3.6: "The case's `total_approved_cents` is the sum of `approved_amount_cents`
    over the `APPROVED` lines."

    The RENTAL_ASSISTANCE award line item must have approved_amount_cents 0 under the
    HABITABLE branch.

    Design: Difficulty/combinatorial_formula/award_formula_multi_input_nonlinear_mode_a
    """
    ctx = setup_approved_case(
        clock="2026-02-10T00:00:00Z",
        decl_overrides={"title": "DR-B2"},
        inspector_badge="INS-B2b",
        cw_employee_id="CW-B2b",
        applicant_overrides={
            "household_name": "Beta Household", "household_size": 1,
            "annual_income_cents": 2_000_000,
            "reported_repair_cost_cents": 700_000,
            "reported_personal_property_cents": 300_000,
            "reported_rental_months": 5,
        },
        inspect_overrides={
            "habitability": "HABITABLE",
            "verified_repair_cost_cents": 700_000,
            "verified_personal_property_cents": 300_000,
            "verified_rental_months": 5,
        },
        monthly_fmr_cents=150_000,
    )
    cw_h = ctx["caseworker_headers"]
    rental = get_line_item(ctx["case"]["id"], "RENTAL_ASSISTANCE", cw_h)
    assert rental["approved_amount_cents"] == 0, rental["approved_amount_cents"]


# ─── combinatorial_formula / cap_waterfall_floor_then_remainder_mode_b ──────
def _cap_waterfall_ctx(badge, cw):
    return setup_approved_case(
        clock="2026-02-12T00:00:00Z",
        decl_overrides={"title": "DR-CAP"},
        inspector_badge=badge,
        cw_employee_id=cw,
        applicant_overrides={
            "household_name": "Cap Household", "household_size": 5,
            "annual_income_cents": 5_000_000,
            "reported_repair_cost_cents": 5_000_000,
            "reported_personal_property_cents": 4_150_000,
            "reported_rental_months": 7,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 5_000_000,
            "verified_personal_property_cents": 4_150_000,
            "verified_rental_months": 7,
        },
        monthly_fmr_cents=333_333,
    )


def test_cap_waterfall_floors_each_line_and_caps_total(api):
    """PRD §3.6: "Each line's capped amount is then the floor of its
    `gross_amount_cents` multiplied by that scale factor — every line is floored
    independently."
    PRD §3.4: "The per-household cap is then applied: `capped_eligible_cents` is the
    smaller of `gross_eligible_cents` and the declaration's `ihp_max_grant_cents`."

    gross 14,783,331 > cap 4,250,000 => capped_eligible 4,250,000, total_approved
    sums back to the cap exactly.

    Design: Difficulty/combinatorial_formula/cap_waterfall_floor_then_remainder_mode_b
    """
    ctx = _cap_waterfall_ctx("INS-CAP", "CW-CAP")
    case = ctx["case"]
    assert case["capped_eligible_cents"] == 4_250_000, case["capped_eligible_cents"]
    assert case["total_approved_cents"] == 4_250_000, case["total_approved_cents"]


def test_cap_waterfall_remainder_pennies_land_on_last_nonzero_line(api):
    """PRD §3.6: "the shortfall, computed as `ihp_max_grant_cents` minus the sum of the
    floored line amounts, is assigned in full to the last non-zero line in the fixed
    category order, so the capped lines sum back exactly to the cap."
    PRD §3.6: "each `AwardLineItem`'s `approved_amount_cents` is set by a two-step
    waterfall that runs over the line items in one fixed category order:
    `RENTAL_ASSISTANCE`, then `REPAIR_ASSISTANCE`, then `PERSONAL_PROPERTY`, then
    `REPLACEMENT`."

    Floored lines: RENTAL 670,799 / REPAIR 1,193,066 / PERSONAL 1,193,066 /
    REPLACEMENT 1,193,066 (sum 4,249,997); the 3-penny remainder lands on REPLACEMENT
    (the last non-zero line) => 1,193,069.

    Design: Difficulty/combinatorial_formula/cap_waterfall_floor_then_remainder_mode_b
    """
    ctx = _cap_waterfall_ctx("INS-CAPb", "CW-CAPb")
    cw_h = ctx["caseworker_headers"]
    case_id = ctx["case"]["id"]
    rental = get_line_item(case_id, "RENTAL_ASSISTANCE", cw_h)
    repair = get_line_item(case_id, "REPAIR_ASSISTANCE", cw_h)
    personal = get_line_item(case_id, "PERSONAL_PROPERTY", cw_h)
    replacement = get_line_item(case_id, "REPLACEMENT", cw_h)
    assert rental["approved_amount_cents"] == 670_799, rental["approved_amount_cents"]
    assert repair["approved_amount_cents"] == 1_193_066, repair["approved_amount_cents"]
    assert personal["approved_amount_cents"] == 1_193_066, personal["approved_amount_cents"]
    assert replacement["approved_amount_cents"] == 1_193_069, replacement["approved_amount_cents"]


# ─── boundary_precision_check / ihp_cap_at_exact_max_no_proration ──────────
def _cap_boundary_ctx(badge, cw):
    return setup_approved_case(
        clock="2026-02-24T00:00:00Z",
        decl_overrides={"title": "DR-CAPB"},
        inspector_badge=badge,
        cw_employee_id=cw,
        applicant_overrides={
            "household_name": "CapB Household", "household_size": 6,
            "annual_income_cents": 4_000_000,
            "reported_repair_cost_cents": 2_000_000,
            "reported_personal_property_cents": 1_000_000,
            "reported_rental_months": 10,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 2_000_000,
            "verified_personal_property_cents": 1_000_000,
            "verified_rental_months": 10,
        },
        monthly_fmr_cents=125_000,
    )


def test_cap_at_exact_max_no_proration(api):
    """PRD §3.6: "The first step applies the per-household cap proportionally, but only
    when the case's `gross_eligible_cents` exceeds the declaration's
    `ihp_max_grant_cents`."
    PRD §3.4: "The per-household cap is then applied: `capped_eligible_cents` is the
    smaller of `gross_eligible_cents` and the declaration's `ihp_max_grant_cents`."

    gross EXACTLY 4,250,000 == cap => capped equals gross, no proration (the cap
    proration is gated on a strict 'exceeds').

    Design: Difficulty/boundary_precision_check/ihp_cap_at_exact_max_no_proration
    """
    ctx = _cap_boundary_ctx("INS-CAPB", "CW-CAPB")
    case = ctx["case"]
    assert case["gross_eligible_cents"] == 4_250_000, case["gross_eligible_cents"]
    assert case["capped_eligible_cents"] == 4_250_000, case["capped_eligible_cents"]


def test_cap_at_exact_max_repair_line_untouched(api):
    """PRD §3.6: "When `gross_eligible_cents` does not exceed the cap, each line's
    capped amount is simply its own `gross_amount_cents`, with no scaling."
    PRD §3.6: "The second step subtracts the duplication offset across the capped
    lines, again in the same fixed category order."

    With gross == cap and no DOB, the REPAIR_ASSISTANCE line keeps its full
    gross 2,000,000 with no floor applied.

    Design: Difficulty/boundary_precision_check/ihp_cap_at_exact_max_no_proration
    """
    ctx = _cap_boundary_ctx("INS-CAPBb", "CW-CAPBb")
    cw_h = ctx["caseworker_headers"]
    repair = get_line_item(ctx["case"]["id"], "REPAIR_ASSISTANCE", cw_h)
    assert repair["approved_amount_cents"] == 2_000_000, repair["approved_amount_cents"]


# ─── local helpers ─────────────────────────────────────────────────────────
def create_applicant_dob(applicant_id, source_type, amount_cents, received_at):
    from test_helpers import create_dob_record_payload
    return create_dob_record_payload(
        applicant_id, source_type=source_type, amount_cents=amount_cents, received_at=received_at
    )


def _approved_case_with_pre_approval_dob():
    """Build an approved case (gross 1,800,000) with a single pre-approval INSURANCE
    DOB of 400,000, approving at a clock after the DOB's received_at.
    Mirrors the dual_variant_calc DOB instance setup.
    """
    from test_helpers import setup_verified_assessment
    ctx = setup_verified_assessment(
        clock="2026-02-05T00:00:00Z",
        decl_overrides={"title": "DR-C Floods"},
        inspector_badge="INS-C1",
        cw_employee_id="CW-C1",
        applicant_overrides={
            "household_name": "Gamma Household", "household_size": 2,
            "annual_income_cents": 3_000_000, "damage_date": "2026-01-20T00:00:00Z",
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000,
            "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000,
            "verified_rental_months": 3,
        },
        scheduled_start="2026-02-06T09:00:00Z",
        scheduled_end="2026-02-06T10:00:00Z",
    )
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    # Pre-approval INSURANCE DOB (received 2026-02-05).
    get_success_data(api_client.create_dob_record(
        create_applicant_dob(app_id, "INSURANCE", 400_000, "2026-02-05T00:00:00Z"), ADMIN
    ))
    case = get_success_data(api_client.create_ihp_case(
        create_ihp_case_payload(app_id, ctx["assessment"]["id"], monthly_fmr_cents=100_000), cw_h
    ))
    # Approve at a later clock so the INSURANCE DOB is at-or-before approval time.
    get_success_data(api_client.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, ADMIN))
    case = get_success_data(api_client.approve_ihp_case(case["id"], cw_h))
    ctx["case"] = case
    return ctx
