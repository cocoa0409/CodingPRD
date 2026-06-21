"""Indirect-cost recovery, reimbursement reconciliation, and the FFR lifecycle.

Sources: Difficulty queue (dual_variant_calc, combinatorial_formula,
non_linear_state_machine on FinancialReport, transitive_cascade on accept) and Corner
queue (calculations, endpoints computed-reads, validations duplicate label).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_financial_report,
    TEST_USERS,
)
import test_helpers.fixtures as fx

GW = TEST_USERS["grant_writer_headers"]
FO = TEST_USERS["finance_officer_headers"]
AO = TEST_USERS["agency_officer_headers"]


# Lines shared by the MTDC dual-variant / combinatorial instances:
# PERSONNEL 11990100 + EQUIPMENT 5000000 + TRAVEL 1000000 + SUPPLIES 1500000
# + SUBAWARD_PASS_THROUGH 8000000  => direct_total 27490100.
MTDC_LINES = [
    {"category": "PERSONNEL", "amount_cents": 11990100},
    {"category": "EQUIPMENT", "amount_cents": 5000000},
    {"category": "TRAVEL", "amount_cents": 1000000},
    {"category": "SUPPLIES", "amount_cents": 1500000},
    {"category": "SUBAWARD_PASS_THROUGH", "amount_cents": 8000000},
]


# ==========================================================================
# Dual-variant calculation (Difficulty Rule 1): indirect recovery
# ==========================================================================
def test_indirect_recovery_negotiated_rate_on_mtdc_base(api):
    """PRD §3.6: "If the award's ACTIVE rate uses the MTDC base, two exclusions are
    subtracted from that direct total: the full amount of every line whose category is
    EQUIPMENT, and, for every line whose category is SUBAWARD_PASS_THROUGH, the portion
    of that line's amount that exceeds twenty-five thousand dollars (that is, the line
    amount minus 2,500,000 cents when positive, otherwise nothing)."
    PRD §3.6: "The rate is applied exactly once to the whole computed base — never per
    line — and the single product is rounded half-up to whole cents to yield
    indirect_cost_cents."
    PRD §3.6: "The report's approved_direct_cents is set to the exact sum of the
    amount_cents across its direct_cost_lines."

    Design: Difficulty/dual_variant_calc/indirect_recovery_negotiated_vs_de_minimis_on_financial_report
    """
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "NEGOTIATED", "negotiated_rate": 0.345, "base_type": "MTDC"},
        nofo_number="NOFO-2026-A1", applicant_org_name="Org A",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=MTDC_LINES,
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A1")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["approved_direct_cents"] == 27_490_100
    assert accepted["indirect_cost_cents"] == 5_861_585


def test_indirect_recovery_de_minimis_diverges_from_negotiated(api):
    """PRD §3.6: "The applicable rate is the rate's negotiated_rate when its rate_type is
    NEGOTIATED, or the fixed ten-percent rate when its rate_type is DE_MINIMIS."
    PRD §3.6: "The rate is applied exactly once to the whole computed base — never per
    line — and the single product is rounded half-up to whole cents to yield
    indirect_cost_cents."

    Design: Difficulty/dual_variant_calc/indirect_recovery_negotiated_vs_de_minimis_on_financial_report
    """
    # Same MTDC base (16,990,100) under DE_MINIMIS 0.10 -> 1,699,010 (vs 5,861,585 negotiated).
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "DE_MINIMIS", "base_type": "MTDC"},
        nofo_number="NOFO-2026-A1d", applicant_org_name="Org Ad",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=MTDC_LINES,
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A1d")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["approved_direct_cents"] == 27_490_100
    assert accepted["indirect_cost_cents"] == 1_699_010


# ==========================================================================
# Dual-variant calculation (Difficulty Rule 1): reimbursement reconciliation
# ==========================================================================
def test_reimbursement_final_variant_cumulative_capped_netted(api):
    """PRD §3.6: "For a FINAL report (the closeout variant), the computation is
    cumulative and capped and netted: first take the cumulative approved direct costs
    across all of the award's ACCEPTED reports including this one... Multiply that
    cumulative figure by the award's federal_share_pct, round half-up to whole cents,
    and then subtract this report's disallowed_cents. Cap the result at the award's
    federal_ceiling_cents by taking the smaller of the two. Finally, subtract the award's
    current federal_drawn_cents."

    Design: Difficulty/dual_variant_calc/reimbursement_provisional_vs_final_on_award_ledger
    """
    # ceiling = 50000000 * 0.80 = 40000000; prior INTERIM approved 10000000; drawn 15000000.
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A2", applicant_org_name="Org B",
        requested_amount_cents=50_000_000, federal_share_pct=0.80,
    )
    fund = fx.create_restricted_fund(award["id"], category="PERSONNEL",
                                     budgeted_cents=20_000_000, priority_order=1)
    fx.create_disbursed_drawdown(
        award["id"], 15_000_000, fx.single_line_plan(fund["id"], 15_000_000),
        initiator_user_id="officer-draw-A2",
    )
    # Prior ACCEPTED INTERIM report.
    fx.create_accepted_interim_report(
        award["id"], [{"category": "PERSONNEL", "amount_cents": 10_000_000}],
        period_label="FY2026-Q1", certifier_user_id="officer-cert-A2",
    )
    final = fx.create_financial_report(
        award["id"], period_label="FY2026-FINAL", report_basis="FINAL",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 20_000_000}],
        disallowed_cents=2_000_000,
    )
    fx.certify_financial_report(final["id"], certifier_user_id="officer-cert-A2")
    accepted = validate_success(api.accept_financial_report(final["id"], AO))
    # cum_direct=30000000; *0.80=24000000; -disallowed 2000000=22000000; cap 40000000;
    # - drawn 15000000 = 7000000.
    assert accepted["reimbursable_cents"] == 7_000_000
    award_after = validate_success(api.get_award(award["id"], AO))
    assert award_after["federal_drawn_cents"] == 15_000_000


def test_reimbursement_interim_provisional_variant(api):
    """PRD §3.6: "For an INTERIM report (the provisional variant), the reimbursement is
    simply the award's federal_share_pct multiplied by this report's approved_direct_cents,
    rounded half-up to whole cents; there is no ceiling cap, no disallowance subtraction,
    and no netting against cash already drawn."

    Design: Difficulty/dual_variant_calc/reimbursement_provisional_vs_final_on_award_ledger
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A2i", applicant_org_name="Org Bi",
        requested_amount_cents=50_000_000, federal_share_pct=0.80,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A2i")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    # provisional: 0.80 * 10000000 = 8000000 (no cap/disallow/netting).
    assert accepted["reimbursable_cents"] == 8_000_000


# ==========================================================================
# Combinatorial formula (Difficulty Rule 2)
# ==========================================================================
def test_indirect_mtdc_nonlinear_equipment_and_subaward_exclusions(api):
    """PRD §3.6: "the full amount of every line whose category is EQUIPMENT, and, for
    every line whose category is SUBAWARD_PASS_THROUGH, the portion of that line's amount
    that exceeds twenty-five thousand dollars (that is, the line amount minus 2,500,000
    cents when positive, otherwise nothing)."
    PRD §3.6: "The rate is applied exactly once to the whole computed base — never per
    line — and the single product is rounded half-up to whole cents to yield
    indirect_cost_cents."

    Design: Difficulty/combinatorial_formula/indirect_mtdc_base_nonlinear_exclusions_mode_a
    """
    # MTDC = 27490100 - 5000000(equipment) - (8000000-2500000)=5500000 -> 16990100; *0.345=5861584.5 -> 5861585.
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "NEGOTIATED", "negotiated_rate": 0.345, "base_type": "MTDC"},
        nofo_number="NOFO-2026-A3", applicant_org_name="Org C",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q2", report_basis="INTERIM",
        direct_cost_lines=MTDC_LINES,
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A3")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["indirect_cost_cents"] == 5_861_585
    assert accepted["approved_direct_cents"] == 27_490_100


def test_indirect_mtdc_approved_direct_is_full_direct_total(api):
    """PRD §3.6: "The report's approved_direct_cents is set to the exact sum of the
    amount_cents across its direct_cost_lines."
    PRD §3.6: "Begin with the direct total — the sum of every direct_cost_lines entry's
    amount_cents."

    Design: Difficulty/combinatorial_formula/indirect_mtdc_base_nonlinear_exclusions_mode_a
    """
    # approved_direct_cents is the FULL direct total (27490100), independent of the MTDC
    # exclusions that only narrow the indirect base.
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "NEGOTIATED", "negotiated_rate": 0.345, "base_type": "MTDC"},
        nofo_number="NOFO-2026-A3b", applicant_org_name="Org C2",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q2", report_basis="INTERIM",
        direct_cost_lines=MTDC_LINES,
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A3b")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["approved_direct_cents"] == 27_490_100
    assert accepted["indirect_cost_cents"] == 5_861_585


def test_indirect_rounding_is_sum_then_round_not_per_line(api):
    """PRD §2.5: "Where a calculation specifies that a rate is applied once to a summed
    base, the rounding occurs once on that single product — never per line item."
    PRD §3.6: "The rate is applied exactly once to the whole computed base — never per
    line — and the single product is rounded half-up to whole cents to yield
    indirect_cost_cents."

    Design: Difficulty/combinatorial_formula/indirect_rounding_order_pinned_sum_then_round_mode_b
    """
    # base = 100100+102100+105100 = 307300; *0.345 = 106018.5 -> 106019 (sum-then-round),
    # NOT 106020 (round-per-line-then-sum).
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "NEGOTIATED", "negotiated_rate": 0.345, "base_type": "MTDC"},
        nofo_number="NOFO-2026-A4", applicant_org_name="Org D",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q3", report_basis="INTERIM",
        direct_cost_lines=[
            {"category": "PERSONNEL", "amount_cents": 100100},
            {"category": "TRAVEL", "amount_cents": 102100},
            {"category": "SUPPLIES", "amount_cents": 105100},
        ],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A4")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["indirect_cost_cents"] == 106_019
    assert accepted["approved_direct_cents"] == 307_300


def test_indirect_single_product_rounds_half_up_to_next_cent(api):
    """PRD §2.5: "the result is rounded to the nearest whole cent using round-half-up (a
    value ending in exactly half a cent rounds up to the next cent)."
    PRD §3.6: "The rate is applied exactly once to the whole computed base — never per
    line — and the single product is rounded half-up to whole cents to yield
    indirect_cost_cents."

    Design: Difficulty/combinatorial_formula/indirect_rounding_order_pinned_sum_then_round_mode_b
    """
    # base 307300 * 0.345 = 106018.5 exactly; round-half-up of the single product -> 106019.
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "NEGOTIATED", "negotiated_rate": 0.345, "base_type": "MTDC"},
        nofo_number="NOFO-2026-A4b", applicant_org_name="Org D2",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q3", report_basis="INTERIM",
        direct_cost_lines=[
            {"category": "PERSONNEL", "amount_cents": 100100},
            {"category": "TRAVEL", "amount_cents": 102100},
            {"category": "SUPPLIES", "amount_cents": 105100},
        ],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A4b")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["indirect_cost_cents"] == 106_019


# ==========================================================================
# Non-linear state machine (Difficulty Rule 3): FFR reject/revise cycle
# ==========================================================================
def test_financial_report_reject_revise_recertify_cycle(api):
    """PRD §3.6: "The AgencyOfficer may reject a SUBMITTED report, moving it to REJECTED."
    PRD §3.6: "The FinanceOfficer may then revise a REJECTED report, returning it to DRAFT
    so the cycle REJECTED → DRAFT → SUBMITTED may repeat."
    PRD §3.6: "The FinanceOfficer certifies a DRAFT report, moving it to SUBMITTED and
    recording the acting operator on certified_by_user_id."

    Design: Difficulty/non_linear_state_machine/financial_report_reject_revise_cycle_back_to_draft
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A6", applicant_org_name="Org F",
        requested_amount_cents=30_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A6")
    validate_success(api.reject_financial_report(report["id"], AO))
    validate_success(api.revise_financial_report(report["id"], FO))
    recertified = validate_success(
        api.certify_financial_report(report["id"], fx.make_finance_officer_headers("officer-cert-A6"))
    )
    assert recertified["status"] == "SUBMITTED"
    assert recertified["certified_by_user_id"] == "officer-cert-A6"


def test_financial_report_revise_returns_to_draft(api):
    """PRD §3.6: "The FinanceOfficer may then revise a REJECTED report, returning it to
    DRAFT so the cycle REJECTED → DRAFT → SUBMITTED may repeat."

    Design: Difficulty/non_linear_state_machine/financial_report_reject_revise_cycle_back_to_draft
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A6b", applicant_org_name="Org F2",
        requested_amount_cents=30_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A6b")
    api.reject_financial_report(report["id"], AO)
    revised = validate_success(api.revise_financial_report(report["id"], FO))
    assert revised["status"] == "DRAFT"


# ==========================================================================
# Transitive cascade (Difficulty Rule 4): accept -> approved totals -> award ledger
# ==========================================================================
def test_accept_report_cascades_to_award_expenditure_ledger(api):
    """PRD §3.6: "The report's approved_direct_cents is set to the exact sum of the
    amount_cents across its direct_cost_lines."
    PRD §3.6: "Finally, the award's federal_approved_expenditures_cents is recomputed as
    the award's federal_share_pct multiplied by the sum of approved_direct_cents over all
    of that award's ACCEPTED reports (including the one just accepted), rounded half-up to
    whole cents."

    Design: Difficulty/transitive_cascade/accept_report_cascade_approved_totals_then_award_expenditures
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A8", applicant_org_name="Org H",
        requested_amount_cents=50_000_000, federal_share_pct=0.80,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A8")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert accepted["approved_direct_cents"] == 10_000_000
    award_after = validate_success(api.get_award(award["id"], AO))
    assert award_after["federal_approved_expenditures_cents"] == 8_000_000


def test_accept_report_sets_approved_direct_cents(api):
    """PRD §3.6: "The report's approved_direct_cents is set to the exact sum of the
    amount_cents across its direct_cost_lines."

    Design: Difficulty/transitive_cascade/accept_report_cascade_approved_totals_then_award_expenditures
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-A8b", applicant_org_name="Org H2",
        requested_amount_cents=50_000_000, federal_share_pct=0.80,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-A8b")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    assert_financial_report(accepted)
    assert accepted["approved_direct_cents"] == 10_000_000


# ==========================================================================
# Corner: DE_MINIMIS ignores negotiated_rate field; TDC variant; computed read
# ==========================================================================
def test_de_minimis_rate_ignores_supplied_negotiated_rate(api):
    """PRD §3.6: "The applicable rate is the rate's negotiated_rate when its rate_type is
    NEGOTIATED, or the fixed ten-percent rate when its rate_type is DE_MINIMIS."
    PRD §3.3: "When the rate type is DE_MINIMIS, the system applies the fixed ten-percent
    rate and ignores negotiated_rate even if it is present."

    Design: Corner/entities/indirect_rate_de_minimis_ignores_negotiated_rate_field
    """
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "DE_MINIMIS", "negotiated_rate": 0.50, "base_type": "MTDC"},
        nofo_number="NOFO-2026-C6", applicant_org_name="Corner Org 6",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-C6")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    # 0.10 * 10000000 = 1000000 (negotiated_rate 0.50 is ignored).
    assert accepted["indirect_cost_cents"] == 1_000_000
    assert accepted["approved_direct_cents"] == 10_000_000


def test_indirect_tdc_base_includes_equipment(api):
    """PRD §3.3: "The officer may also specify base_type — either MTDC (Modified Total
    Direct Cost) or TDC (Total Direct Cost)."
    PRD §3.6: "If instead the rate uses the TDC base, the base is simply the direct total
    with no exclusions."

    Design: Corner/calculations/indirect_tdc_base_includes_equipment_no_exclusions
    """
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "NEGOTIATED", "negotiated_rate": 0.20, "base_type": "TDC"},
        nofo_number="NOFO-2026-C22", applicant_org_name="Corner Org 22",
        requested_amount_cents=50_000_000,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[
            {"category": "PERSONNEL", "amount_cents": 10_000_000},
            {"category": "EQUIPMENT", "amount_cents": 5_000_000},
        ],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-C22")
    accepted = validate_success(api.accept_financial_report(report["id"], AO))
    # TDC: 0.20 * 15000000 = 3000000 (equipment NOT excluded).
    assert accepted["indirect_cost_cents"] == 3_000_000
    assert accepted["approved_direct_cents"] == 15_000_000


def test_get_financial_report_surfaces_computed_fields(api):
    """PRD §3.6: "Reports may be listed by award_id or status and individually retrieved
    to inspect their computed approved_direct_cents, indirect_cost_cents, and
    reimbursable_cents."

    Design: Corner/endpoints/get_financial_report_surfaces_computed_fields
    """
    award, _rate = fx.create_active_award_with_rate(
        rate_overrides={"rate_type": "DE_MINIMIS", "base_type": "MTDC"},
        nofo_number="NOFO-2026-C33", applicant_org_name="Corner Org 33",
        requested_amount_cents=50_000_000, federal_share_pct=0.80,
    )
    report = fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000}],
    )
    fx.certify_financial_report(report["id"], certifier_user_id="officer-cert-C33")
    fx.accept_financial_report(report["id"])
    fetched = validate_success(api.get_financial_report(report["id"], FO))
    assert fetched["approved_direct_cents"] == 10_000_000
    assert fetched["indirect_cost_cents"] == 1_000_000
    assert fetched["reimbursable_cents"] == 8_000_000


def test_duplicate_period_label_per_award_returns_duplicate(api):
    """PRD §3.6: "A report's period_label must be unique per award among reports that are
    not REJECTED; a clashing label is rejected with ERR_DUPLICATE."

    Design: Corner/validations/duplicate_period_label_per_award_returns_duplicate
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C27", applicant_org_name="Corner Org 27",
        requested_amount_cents=50_000_000,
    )
    fx.create_financial_report(
        award["id"], period_label="FY2026-Q1", report_basis="INTERIM",
        direct_cost_lines=[{"category": "PERSONNEL", "amount_cents": 1_000_000}],
    )
    resp = api.create_financial_report({
        "award_id": award["id"], "period_label": "FY2026-Q1", "report_basis": "INTERIM",
        "direct_cost_lines": [{"category": "TRAVEL", "amount_cents": 500_000}],
    }, FO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value, expected_status=409)


def test_missing_negotiated_rate_when_negotiated_returns_invalid_request(api):
    """PRD §3.3: "When the rate type is NEGOTIATED, the officer must supply negotiated_rate
    as a decimal fraction greater than 0 and at most 1; that contextual requirement is
    enforced, and a NEGOTIATED rate missing its negotiated_rate is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/validations/missing_negotiated_rate_when_negotiated_returns_invalid_request
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C29", applicant_org_name="Corner Org 29",
        requested_amount_cents=50_000_000,
    )
    resp = api.create_indirect_cost_rate({
        "award_id": award["id"], "rate_type": "NEGOTIATED", "base_type": "MTDC",
        "expected_award_version": award["version"],
    }, FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_rate_supersede_retires_prior_to_superseded(api):
    """PRD §3.3: "A newly created rate is born ACTIVE, and creating it retires whatever
    rate was previously ACTIVE for that award by moving the prior rate to SUPERSEDED."

    Design: Corner/state_machines/rate_supersede_retires_prior_active_rate_to_superseded
    """
    award = fx.create_active_award(
        nofo_number="NOFO-2026-C20", applicant_org_name="Corner Org 20",
        requested_amount_cents=50_000_000,
    )
    rate1 = fx.set_indirect_cost_rate(
        award["id"], award["version"],
        rate_type="NEGOTIATED", negotiated_rate=0.30, base_type="MTDC",
    )
    award_v1 = validate_success(api.get_award(award["id"], FO))
    rate2 = fx.set_indirect_cost_rate(
        award["id"], award_v1["version"], rate_type="DE_MINIMIS", base_type="MTDC",
    )
    rate1_after = validate_success(api.get_indirect_cost_rate(rate1["id"], FO))
    rate2_after = validate_success(api.get_indirect_cost_rate(rate2["id"], FO))
    assert rate1_after["status"] == "SUPERSEDED"
    assert rate2_after["status"] == "ACTIVE"
