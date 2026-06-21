"""Benefit-fraction variants, COLA-compounded gross, the net-benefit waterfall,
offset summation, the residual zero-benefit boundary, and immediate consistency.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, get_success_data, validate_paginated,
    assert_benefit_period,
    create_policy_payload, create_claim_payload, create_income_report_payload,
    create_disability_proof_payload,
    TEST_USERS, make_policyholder_headers,
    setup_book, setup_active_policy,
    setup_approved_total_with_periods,
    setup_approved_residual_with_report,
    setup_total_claim_with_period_and_estimated_offset,
    create_insurer, advance_clock, create_occupation_class, create_policyholder,
    create_policy, file_claim, add_income_report, accrue_benefit_period,
    add_offset_award, finalize_offset,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]


# ─── Difficulty / dual_variant_calc ───────────────────

def test_residual_factor_proportionate_vs_presumptive_total(api):
    """PRD §3.9: "Under the proportionate variant — which governs a RESIDUAL claim
    on an ANY_OCC policy, or a RESIDUAL claim whose coverage month is at or after
    the own-occupation expiry month — the fraction is 0.0 when R is below the
    minimum loss ratio of 0.20, is 1.0 (a presumptive total) when R is at or above
    the presumed-total ratio of 0.80, and otherwise equals R itself rounded to
    four decimal places."
    PRD §3.9: "Under the presumptive-total variant — which governs a RESIDUAL claim
    on an OWN_OCC policy while the coverage month is strictly before the
    own-occupation expiry month — any qualifying loss pays in full: the fraction is
    1.0 when R is at or above the minimum loss ratio of 0.20, and 0.0 otherwise".

    Design: Difficulty/dual_variant_calc/residual_factor_proportionate_vs_presumptive_total
    """
    insurer = create_insurer()
    advance_clock(insurer["id"], 5)
    occ = create_occupation_class(insurer["id"], code="MED", risk_tier="MEDIUM",
                                  max_benefit_months=120, min_elimination_days=0,
                                  own_occ_window_months_cap=60)
    ph = create_policyholder(insurer["id"], pre_disability_monthly_income_cents=1000000)
    ph_id = ph["id"]

    p_any = create_policy(insurer["id"], ph_id, occ["id"], monthly_benefit_cents=500000,
                          benefit_period_months=12, elimination_period_days=90,
                          occupation_definition="ANY_OCC", cola_rider=False, cola_annual_rate=0)
    get_success_data(api.activate_policy(p_any["id"], UW))
    p_own = create_policy(insurer["id"], ph_id, occ["id"], monthly_benefit_cents=500000,
                          benefit_period_months=12, elimination_period_days=90,
                          occupation_definition="OWN_OCC", own_occ_window_months=24,
                          cola_rider=False, cola_annual_rate=0)
    get_success_data(api.activate_policy(p_own["id"], UW))

    def approved_residual(policy_id):
        claim = file_claim(insurer["id"], policy_id, ph_id, disability_onset_month=0,
                           claimed_disability_type="RESIDUAL")
        add_income_report(claim["id"], ph_id, 3, 500000, claim["version"])  # R=0.50
        get_success_data(api.submit_claim(claim["id"], make_policyholder_headers(ph_id)))
        get_success_data(api.begin_review(claim["id"], ADJ))
        get_success_data(api.approve_claim(claim["id"], ADJ))
        return claim["id"]

    c_any = approved_residual(p_any["id"])
    c_own = approved_residual(p_own["id"])

    bp_any = validate_success(api.create_benefit_period(c_any, {"coverage_month": 3}, ADJ), 201)
    bp_own = validate_success(api.create_benefit_period(c_own, {"coverage_month": 3}, ADJ), 201)

    assert bp_any["benefit_fraction"] == 0.5
    assert bp_any["gross_benefit_cents"] == 250000
    assert bp_own["benefit_fraction"] == 1.0
    assert bp_own["gross_benefit_cents"] == 500000


def test_net_benefit_provisional_vs_final_offset(api):
    """PRD §3.10: "Whether an award's effective offset is its estimated or its
    reconciled figure depends on the award's status ... an ESTIMATED award
    contributes a provisional offset and a FINALIZED award contributes the
    reconciled offset".
    PRD §3.11: "the positive delta — the reconciled monthly offset minus the
    estimated snapshot, taken as zero when that difference is negative — accrues to
    the ledger's overpayment_balance_cents for each covered ACCRUED month."

    Design: Difficulty/dual_variant_calc/net_benefit_provisional_vs_final_offset
    """
    book = setup_total_claim_with_period_and_estimated_offset(
        offset_source="SSDI", monthly_offset_cents=120000, offset_window=(3, 5),
        coverage_month=3, clock_months=5,
    )
    bp_id = book["benefit_period"]["id"]
    oa_id = book["offset_award"]["id"]
    # Provisional (ESTIMATED 120000): net = 500000 - 120000.
    bp_before = validate_success(api.get_benefit_period(bp_id, ADJ), 200)
    assert bp_before["net_benefit_cents"] == 380000

    finalized = validate_success(
        api.finalize_offset_award(oa_id, {"final_monthly_offset_cents": 200000}, ADJ), 200
    )
    assert finalized["status"] == "FINALIZED"
    bp_after = validate_success(api.get_benefit_period(bp_id, ADJ), 200)
    assert bp_after["net_benefit_cents"] == 300000  # 500000 - 200000
    ledger, _ = validate_paginated(api.get_claim_ledger(book["claim"]["id"], ADJ))
    assert ledger[0]["overpayment_balance_cents"] == 80000  # 200000 - 120000


# ─── Difficulty / combinatorial_formula ───────────────

def test_cola_compound_capped_gross_benefit(api):
    """PRD §3.10: "Otherwise the multiplier compounds the annual rate over the
    elapsed years — one plus the policy's cola_annual_rate, raised to the power of
    the elapsed years — and is then capped at the maximum COLA multiplier of 2.0".
    PRD §3.10: "The COLA-adjusted cents are the policy's monthly_benefit_cents
    multiplied by that multiplier, rounded half-up to the nearest cent. The
    gross_benefit_cents is then that COLA-adjusted figure multiplied by the
    period's benefit_fraction, again rounded half-up to the nearest cent."

    Design: Difficulty/combinatorial_formula/cola_compound_capped_gross_benefit
    """
    insurer = create_insurer()
    advance_clock(insurer["id"], 30)
    occ = create_occupation_class(insurer["id"], code="MED", risk_tier="MEDIUM",
                                  max_benefit_months=240, min_elimination_days=0,
                                  own_occ_window_months_cap=0)
    ph = create_policyholder(insurer["id"], pre_disability_monthly_income_cents=1000000)
    ph_id = ph["id"]
    policy = create_policy(insurer["id"], ph_id, occ["id"], monthly_benefit_cents=500000,
                           benefit_period_months=120, elimination_period_days=90,
                           occupation_definition="ANY_OCC", cola_rider=True,
                           cola_annual_rate=0.03)
    get_success_data(api.activate_policy(policy["id"], UW))
    claim = file_claim(insurer["id"], policy["id"], ph_id, claimed_disability_type="TOTAL")
    get_success_data(api.submit_claim(claim["id"], make_policyholder_headers(ph_id)))
    get_success_data(api.begin_review(claim["id"], ADJ))
    get_success_data(api.approve_claim(claim["id"], ADJ))
    # Keep proofs current up to month 27 (next_proof_due starts at 6, +3 each accept).
    for m in (6, 9, 12, 15, 18, 21, 24, 27):
        get_success_data(api.create_disability_proof(
            claim["id"], create_disability_proof_payload(m, True),
            make_policyholder_headers(ph_id),
        ))
    bp = validate_success(api.create_benefit_period(claim["id"], {"coverage_month": 27}, ADJ), 201)
    # years_elapsed = floor((27-3)/12) = 2 ; 1.03^2 = 1.0609 ; 500000*1.0609 = 530450.
    assert bp["gross_benefit_cents"] == 530450


def test_net_benefit_pinned_evaluation_order_floors_at_zero(api):
    """PRD §3.10: "the evaluation order is fixed: the benefit fraction is settled
    first, then the gross benefit, then the offset applied, then the net benefit."
    PRD §3.10: "The net_benefit_cents is then the gross benefit minus the offset
    applied, floored at the offset floor of 0 so that a net benefit never goes
    negative."

    Design: Difficulty/combinatorial_formula/net_benefit_pinned_evaluation_order_waterfall
    """
    book = setup_approved_residual_with_report(
        effective_month=3, current_monthly_income_cents=500000, clock_months=5,
        occ_overrides={"own_occ_window_months_cap": 0},
    )  # R=0.50 -> fraction 0.5, gross 250000
    cid = book["claim"]["id"]
    add_offset_award(cid, "SSDI", 300000, 3, 5)
    bp = validate_success(api.create_benefit_period(cid, {"coverage_month": 3}, ADJ), 201)
    assert bp["benefit_fraction"] == 0.5
    assert bp["gross_benefit_cents"] == 250000
    assert bp["offset_applied_cents"] == 300000
    assert bp["net_benefit_cents"] == 0  # floored, not -50000


# ─── Difficulty / boundary_precision_check (residual) ─

def test_residual_min_loss_ratio_zero_benefit_boundary(api):
    """PRD §3.9: "the fraction is 0.0 when R is below the minimum loss ratio of
    0.20".
    PRD §3.8: "The system computes the report's income_loss_ratio as the
    pre-disability monthly income minus the current monthly income, divided by the
    pre-disability monthly income, with any negative result floored at 0 and the
    quotient rounded to four decimal places."

    Design: Difficulty/boundary_precision_check/residual_min_loss_ratio_zero_benefit_boundary
    """
    book = setup_approved_residual_with_report(
        effective_month=3, current_monthly_income_cents=850000, clock_months=5,
        occ_overrides={"own_occ_window_months_cap": 0},
    )  # R = (1000000-850000)/1000000 = 0.15 < 0.20
    cid = book["claim"]["id"]
    reports, _ = validate_paginated(api.list_income_reports(cid, ADJ))
    assert reports[0]["income_loss_ratio"] == 0.15
    bp = validate_success(api.create_benefit_period(cid, {"coverage_month": 3}, ADJ), 201)
    assert bp["benefit_fraction"] == 0.0
    assert bp["gross_benefit_cents"] == 0


# ─── Corner / calculations ────────────────────────────

def test_cola_disabled_gross_equals_base_total(api):
    """PRD §3.10: "When the policy carries no COLA rider, or when zero or fewer full
    years have elapsed, the cost-of-living multiplier is 1.0."
    PRD §3.9: "For a TOTAL claim it is always 1.0."

    Design: Corner/calculations/cola_disabled_gross_equals_base_total
    """
    book = setup_approved_total_with_periods([3], clock_months=5,
                                             policy_overrides={"cola_rider": False,
                                                               "cola_annual_rate": 0})
    bp = book["benefit_periods"][0]
    assert_benefit_period(bp)
    assert bp["gross_benefit_cents"] == 500000
    assert bp["benefit_fraction"] == 1.0
    assert bp["net_benefit_cents"] == 500000


def test_residual_presumed_total_at_or_above_080(api):
    """PRD §3.9: "is 1.0 (a presumptive total) when R is at or above the
    presumed-total ratio of 0.80".

    Design: Corner/calculations/residual_presumed_total_at_or_above_080
    """
    book = setup_approved_residual_with_report(
        effective_month=3, current_monthly_income_cents=100000, clock_months=5,
        occ_overrides={"own_occ_window_months_cap": 0},
    )  # R = 0.90
    cid = book["claim"]["id"]
    reports, _ = validate_paginated(api.list_income_reports(cid, ADJ))
    assert reports[0]["income_loss_ratio"] == 0.9
    bp = validate_success(api.create_benefit_period(cid, {"coverage_month": 3}, ADJ), 201)
    assert bp["benefit_fraction"] == 1.0
    assert bp["gross_benefit_cents"] == 500000


def test_workers_comp_and_ssdi_offsets_sum_on_same_month(api):
    """PRD §3.10: "The offset_applied_cents for a coverage month is the sum, over
    every non-VOID offset award on the claim whose closed window contains the
    coverage month, of each award's effective offset; for determinism the running
    sum adds WORKERS_COMP awards before SSDI awards, though the final total is
    independent of order."

    Design: Corner/calculations/workers_comp_and_ssdi_offsets_sum_on_same_month
    """
    book = setup_approved_total_with_periods([], clock_months=5)
    cid = book["claim"]["id"]
    add_offset_award(cid, "WORKERS_COMP", 100000, 3, 4)
    add_offset_award(cid, "SSDI", 150000, 3, 4)
    bp = validate_success(api.create_benefit_period(cid, {"coverage_month": 3}, ADJ), 201)
    assert bp["offset_applied_cents"] == 250000  # 100000 + 150000
    assert bp["net_benefit_cents"] == 250000  # 500000 - 250000


# ─── Corner / consistency_model ───────────────────────

def test_offset_create_immediately_recomputes_net(api):
    """PRD §3.11: "Creating the award also recomputes offset_applied_cents and
    net_benefit_cents on every ACCRUED benefit period whose coverage month falls in
    the award's window, and recomputes the claim ledger's total_net_paid_cents."

    Design: Corner/consistency_model/offset_create_immediately_recomputes_net_in_same_session
    """
    book = setup_approved_total_with_periods([3], clock_months=5)
    cid = book["claim"]["id"]
    bp_id = book["benefit_periods"][0]["id"]
    add_offset_award(cid, "SSDI", 120000, 3, 5)
    bp_after = validate_success(api.get_benefit_period(bp_id, ADJ), 200)
    assert bp_after["net_benefit_cents"] == 380000  # 500000 - 120000, immediately
