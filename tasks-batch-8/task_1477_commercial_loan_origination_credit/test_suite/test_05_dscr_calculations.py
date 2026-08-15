"""Dual-variant DSCR computation and the inclusive 1.2500 policy floor
(PRD section 3.2). Default logical clock 2026-08-01T00:00:00Z throughout.
"""
from test_helpers import (
    attach_statement, create_borrower, deal_underwritten, finalize_spreads,
    get_application, list_exceptions, loan_application_payload, setup_officers,
    spread_and_finalize, submit_application, validate_success, api_client,
)


def _underwrite_beacon():
    """One BEACON-shaped deal driven through finalize-spreads."""
    return deal_underwritten(
        borrower_kw={"legal_name": "Beacon Holdings LLC", "naics_code": "332710",
                     "relationship_since": "2018-01-01"},
        app_kw={"requested_amount_cents": 30_000_000, "term_months": 60},
        statement_shape="BEACON")


def test_dscr_variants_diverge_on_same_statement():
    """PRD section 3.2: "The `BANK_STANDARD` variant then permits addbacks up to a
    cap — the permitted addback is the lesser of `addbacks_cents` and one quarter of
    `ebitda_cents` floored to whole cents — so standard cash flow equals
    `ebitda_cents` plus the permitted addback, minus `distributions_cents`, minus
    `maintenance_capex_cents`" and "The `REGULATORY_STRESS` variant instead applies
    a revenue haircut and forbids addbacks: stressed EBITDA equals `ebitda_cents`
    minus fifteen percent of `revenue_cents` (the haircut itself rounded half-up to
    whole cents)".

    Design: Difficulty/dual_variant_calc/dscr_standard_vs_stress_same_statement_diverge
    """
    ctx = _underwrite_beacon()
    uw = ctx["underwriting"]
    # cf_standard = 11,000,000 + min(3,000,000, 2,750,000) - 800,000 - 450,000 = 12,500,000
    # annual debt service = 594,036*12 + 2,500,000 = 9,628,432
    assert uw["dscr_standard"] == 1.2982, "12,500,000 / 9,628,432 with capped addbacks"
    # cf_stress = 11,000,000 - 3,000,000 - 800,000 - 450,000 = 6,750,000
    assert uw["dscr_stress"] == 0.7010, "6,750,000 / 9,628,432 with haircut, no addbacks"
    assert round(uw["dscr_standard"] - uw["dscr_stress"], 4) == 0.5972, (
        "identical inputs, divergent variants")


def test_stress_only_exception_and_exception_review_branch():
    """PRD section 3.2: "finalizing spreads auto-creates policy exceptions for any
    triggered rule: `DSCR_MINIMUM` when `dscr_standard` is below 1.2500,
    `STRESS_DSCR_MINIMUM` when `dscr_stress` is below 1.0000 ... The branch then
    forks: if any exception stands `OPEN`, the application moves `SPREADING` →
    `EXCEPTION_REVIEW`". PRD section 3.3: "`STRESS_DSCR_MINIMUM`, `REG_O_INSIDER`,
    and `REQUIRED_DOC_WAIVER` are always `LOW`."

    Design: Difficulty/dual_variant_calc/dscr_standard_vs_stress_same_statement_diverge
    """
    ctx = _underwrite_beacon()
    o = ctx["o"]
    uw = ctx["underwriting"]
    assert uw["status"] == "EXCEPTION_REVIEW", "the LOW stress exception is OPEN"

    all_exc = list_exceptions(o, uw["id"])
    assert len(all_exc) == 1
    assert all_exc[0]["rule_code"] == "STRESS_DSCR_MINIMUM"
    assert all_exc[0]["severity"] == "LOW"
    assert all_exc[0]["status"] == "OPEN"
    assert not any(e["rule_code"] == "DSCR_MINIMUM" for e in all_exc), (
        "1.2982 >= 1.2500 so no DSCR_MINIMUM")

    # Provisional rating: (0.4*60 + 0.3*100 + 0.1*75)/0.80 == 76.88 -> band 3.
    assert uw["risk_rating"] == 3
    assert uw["rating_basis"] == "PROVISIONAL"


def _underwrite_boundary(statement_shape, legal_name):
    return deal_underwritten(
        borrower_kw={"legal_name": legal_name, "naics_code": "332710",
                     "relationship_since": "2018-01-01"},
        app_kw={"requested_amount_cents": 30_000_000, "term_months": 60},
        statement_shape=statement_shape)


def test_exactly_at_dscr_floor_passes():
    """PRD section 3.2: "`DSCR_MINIMUM` when `dscr_standard` is below 1.2500" — so a
    ratio of exactly 1.2500 is not below the floor — and "if none does, it moves
    `SPREADING` → `APPRAISAL_REVIEW` directly."

    Design: Difficulty/boundary_precision_check/dscr_policy_floor_inclusive_boundary
    """
    ctx = _underwrite_boundary("BOUNDARY_PASS", "Boundary Pass LLC")
    o = ctx["o"]
    uw = ctx["underwriting"]
    # cf = 12,035,540; 12,035,540 / 9,628,432 == 1.25 exactly
    assert uw["dscr_standard"] == 1.2500
    # stress: (12,035,540 - 2,400,000) / 9,628,432 == 1.0007 >= 1.0000
    assert uw["dscr_stress"] == 1.0007
    assert list_exceptions(o, uw["id"]) == [], "no exceptions fire at the floor"
    assert uw["status"] == "APPRAISAL_REVIEW"
    # (0.4*60 + 0.3*100 + 0.1*75)/0.80 == 76.88 -> band 3
    assert uw["risk_rating"] == 3
    assert uw["rating_basis"] == "PROVISIONAL"


def test_one_cent_below_dscr_floor_fails():
    """PRD section 3.2: "`DSCR_MINIMUM` when `dscr_standard` is below 1.2500" and
    "if any exception stands `OPEN`, the application moves `SPREADING` →
    `EXCEPTION_REVIEW`". PRD section 3.3: "`DSCR_MINIMUM` ... are always `HIGH`
    severity".

    Design: Difficulty/boundary_precision_check/dscr_policy_floor_inclusive_boundary
    """
    ctx = _underwrite_boundary("BOUNDARY_FAIL", "Boundary Fail LLC")
    o = ctx["o"]
    uw = ctx["underwriting"]
    # cf = 12,035,058; 12,035,058 / 9,628,432 == 1.24994966 -> rounds to 1.2499
    assert uw["dscr_standard"] == 1.2499
    assert uw["dscr_stress"] == 1.0007, "stress side unaffected by the standard-side gap"

    all_exc = list_exceptions(o, uw["id"])
    assert len(all_exc) == 1
    assert all_exc[0]["rule_code"] == "DSCR_MINIMUM"
    assert all_exc[0]["severity"] == "HIGH"
    assert all_exc[0]["status"] == "OPEN"
    assert not any(e["rule_code"] == "STRESS_DSCR_MINIMUM" for e in all_exc)
    assert uw["status"] == "EXCEPTION_REVIEW"
    # (0.4*40 + 0.3*100 + 0.1*75)/0.80 == 66.88 -> band 4
    assert uw["risk_rating"] == 4
    assert uw["rating_basis"] == "PROVISIONAL"
