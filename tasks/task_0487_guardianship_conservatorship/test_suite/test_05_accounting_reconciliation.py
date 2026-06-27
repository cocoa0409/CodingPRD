"""Periodic accounting: dual-variant reconciliation, fiduciary fee, revision cycle.

Difficulty: chronological vs projected ledger, statutory vs public-agency fee,
per-band rounding order, the submit/return/resubmit revision cycle, and the
variance tolerance boundary on approval.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty: chronological ledger vs forward-looking projection (same period)
# ===========================================================================
def test_accounting_chronological_vs_projection(api):
    """PRD 3.7: "The chronological-actual figure, ledger_disbursed_cents, is the
    audited truth: it is the sum of the amount_cents of every expenditure on this
    case that is in DISBURSED status and whose disbursed_at falls in the report's
    period_year."

    Design: Difficulty/dual_variant_calc/dvc_accounting_chronological_vs_projection
    """
    ctx = fx.funded_conservatorship(
        funding_cents=5_000_000,
        care_cap_cents=2_000_000,
        medical_cap_cents=2_000_000,
        admin_cap_cents=1_000_000,
    )
    fid = ctx["fiduciary_id"]
    fx.create_and_disburse_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="CARE", amount_cents=800_000, payee_name="Caregiver A",
    )
    fx.create_and_disburse_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="CARE", amount_cents=1_000_000, payee_name="Caregiver B",
    )
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=5_000_000,
        reported_income_cents=0, reported_disbursed_cents=1_800_000,
    )
    assert ar["ledger_disbursed_cents"] == 1_800_000
    assert ar["variance_cents"] == 0


def test_accounting_projection_sums_approved_budget_caps(api):
    """PRD 3.7: "otherwise it is the sum of that single approved budget's
    care_cap_cents, medical_cap_cents, and admin_cap_cents."

    Design: Difficulty/dual_variant_calc/dvc_accounting_chronological_vs_projection
    """
    ctx = fx.funded_conservatorship(
        funding_cents=5_000_000,
        care_cap_cents=2_000_000,
        medical_cap_cents=2_000_000,
        admin_cap_cents=1_000_000,
    )
    fid = ctx["fiduciary_id"]
    fx.create_and_disburse_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="CARE", amount_cents=800_000, payee_name="Caregiver A",
    )
    fx.create_and_disburse_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="CARE", amount_cents=1_000_000, payee_name="Caregiver B",
    )
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=5_000_000,
        reported_income_cents=0, reported_disbursed_cents=1_800_000,
    )
    assert ar["projected_disbursed_cents"] == 5_000_000
    assert ar["ledger_disbursed_cents"] != ar["projected_disbursed_cents"]


def test_projected_disbursed_zero_when_no_approved_budget(api):
    """PRD 3.7: "it is zero when no APPROVED budget exists on the case for the
    report's period_year".

    Design: Corner/calculations/projected_disbursed_zero_when_no_approved_budget
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], ctx["fiduciary_id"],
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=0,
    )
    assert ar["projected_disbursed_cents"] == 0


# ===========================================================================
# Difficulty: fiduciary fee — statutory (PROFESSIONAL) vs public-agency cap
# ===========================================================================
def test_fiduciary_fee_statutory_for_professional(api):
    """PRD 3.7: "when the appointed fiduciary's fiduciary_kind is FAMILY or
    PROFESSIONAL, the fiduciary_fee_cents is exactly the statutory figure".

    Design: Difficulty/dual_variant_calc/dvc_fiduciary_fee_statutory_vs_public_agency_cap
    """
    ctx = fx.active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind="PROFESSIONAL",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], ctx["fiduciary_id"],
        period_year=2026, opening_balance_cents=20_000_000,
        reported_income_cents=5_000_000, reported_disbursed_cents=0,
    )
    # base 25,000,000: tier1 4,999,990*0.05=249,999.5->250,000;
    # tier2 (19,999,990-4,999,990)=15,000,000*0.04=600,000;
    # tier3 (25,000,000-19,999,990)=5,000,010*0.03=150,000.3->150,000 => 1,000,000
    assert ar["fiduciary_fee_cents"] == 1_000_000


def test_fiduciary_fee_public_agency_capped(api):
    """PRD 3.7: "when it is PUBLIC_AGENCY, the fiduciary_fee_cents is the lesser of
    the statutory figure and a public-agency cap of 300,000 cents, so a
    public-agency fee diverges from the statutory figure once the statutory figure
    exceeds the cap."

    Design: Difficulty/dual_variant_calc/dvc_fiduciary_fee_statutory_vs_public_agency_cap
    """
    ctx = fx.active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind="PUBLIC_AGENCY",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], ctx["fiduciary_id"],
        period_year=2026, opening_balance_cents=20_000_000,
        reported_income_cents=5_000_000, reported_disbursed_cents=0,
    )
    assert ar["fiduciary_fee_cents"] == 300_000


# ===========================================================================
# Difficulty: per-band rounding order (round-per-band-then-sum)
# ===========================================================================
def test_fiduciary_fee_round_per_band_then_sum(api):
    """PRD 3.7: "each band's charge is rounded half up to a whole number of cents
    individually, and only then are the three rounded band charges summed — the
    rounding happens per band, before the summation, not on the grand total."

    Design: Difficulty/combinatorial_formula/cf_fiduciary_fee_round_per_band_then_sum
    """
    ctx = fx.active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind="PROFESSIONAL",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], ctx["fiduciary_id"],
        period_year=2026, opening_balance_cents=20_000_000,
        reported_income_cents=7, reported_disbursed_cents=0,
    )
    # base 20,000,007: b1 4,999,990*0.05=249,999.5->250,000;
    # b2 15,000,000*0.04=600,000; b3 17*0.03=0.51->1 => 850,001 (not 850,000)
    assert ar["fiduciary_fee_cents"] == 850_001


def test_fiduciary_fee_per_band_rounding_in_two_bands(api):
    """PRD 3.7: "each band's charge is rounded half up to a whole number of cents
    individually, and only then are the three rounded band charges summed — the
    rounding happens per band, before the summation, not on the grand total."

    Design: Difficulty/combinatorial_formula/cf_fiduciary_fee_round_per_band_then_sum
    """
    ctx = fx.active_case(
        case_type="CONSERVATORSHIP",
        fiduciary_kind="PROFESSIONAL",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], ctx["fiduciary_id"],
        period_year=2026, opening_balance_cents=10_000_003,
        reported_income_cents=0, reported_disbursed_cents=0,
    )
    # base 10,000,003: b1 4,999,990*0.05=249,999.5->250,000;
    # b2 5,000,013*0.04=200,000.52->200,001 => per-band sum 450,001
    # (sum-then-round would give 450,000 — the orders diverge by 1 cent).
    assert ar["fiduciary_fee_cents"] == 450_001


# ===========================================================================
# Difficulty: revision cycle SUBMITTED <-> RETURNED_FOR_CORRECTION
# ===========================================================================
def test_accounting_revision_cycle_then_approve(api):
    """PRD 3.7: "the fiduciary resubmits a RETURNED_FOR_CORRECTION report, which
    may carry corrected reported_disbursed_cents, reported_income_cents, or
    opening_balance_cents, moves it back to SUBMITTED, and recomputes the ledger,
    projection, variance, and fee."

    Design: Difficulty/non_linear_state_machine/nlsm_accounting_revision_cycle
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=1_000,
    )
    assert ar["variance_cents"] == 1_000  # ledger 0, reported 1,000
    api.return_accounting(ar["id"], fx.JUDGE)
    resubmitted = validate_success(
        api.resubmit_accounting(
            ar["id"], {"reported_disbursed_cents": 0}, fx.make_fiduciary_headers(fid)
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["variance_cents"] == 0
    approved = validate_success(api.approve_accounting(ar["id"], fx.JUDGE))
    assert approved["status"] == "APPROVED"


def test_returned_report_status_then_resubmit_status(api):
    """PRD 3.7: "A judge may return a SUBMITTED report for correction, moving it to
    RETURNED_FOR_CORRECTION".

    Design: Difficulty/non_linear_state_machine/nlsm_accounting_revision_cycle
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=1_000,
    )
    returned = validate_success(api.return_accounting(ar["id"], fx.JUDGE))
    assert returned["status"] == "RETURNED_FOR_CORRECTION"


# ===========================================================================
# Difficulty: variance tolerance boundary on approval (abs <= 500)
# ===========================================================================
def test_variance_exactly_at_tolerance_approvable(api):
    """PRD 3.7: "A judge approves a SUBMITTED report only when the absolute value
    of its variance_cents is within the variance tolerance of 500 cents — that is,
    the variance's magnitude must be at most 500 cents, and a magnitude beyond
    that is rejected with ERR_ACCOUNTING_VARIANCE."

    Design: Difficulty/boundary_precision_check/bpc_variance_tolerance_boundary
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=500,
    )
    assert ar["variance_cents"] == 500
    approved = validate_success(api.approve_accounting(ar["id"], fx.JUDGE))
    assert approved["status"] == "APPROVED"


def test_variance_one_over_tolerance_rejected(api):
    """PRD 3.7: "the variance's magnitude must be at most 500 cents, and a
    magnitude beyond that is rejected with ERR_ACCOUNTING_VARIANCE."

    Design: Difficulty/boundary_precision_check/bpc_variance_tolerance_boundary
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP", person_overrides={"liquid_estate_cents": 8_000_000})
    fid = ctx["fiduciary_id"]
    ar = fx.create_and_submit_accounting(
        ctx["case_id"], fid,
        period_year=2026, opening_balance_cents=0,
        reported_income_cents=0, reported_disbursed_cents=501,
    )
    assert ar["variance_cents"] == 501
    validate_error(
        api.approve_accounting(ar["id"], fx.JUDGE), ApiErrorId.ERR_ACCOUNTING_VARIANCE
    )
