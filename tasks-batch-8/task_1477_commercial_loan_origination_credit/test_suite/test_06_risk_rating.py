"""Risk rating model: tiered factor lookups, PROVISIONAL weight renormalization,
and the FULL basis divergence at submit-to-committee (PRD sections 3.2, 3.5).
Default logical clock 2026-08-01T00:00:00Z unless set.
"""
from test_helpers import (
    ApiErrorId, attach_statement, create_appraiser, create_borrower, deal_underwritten,
    finalize_spreads, get_application, list_exceptions, loan_application_payload,
    order_and_accept_appraisal, setup_officers, spread_and_finalize, spread_statement,
    finalize_statement, submit_application, submit_to_committee, api_client,
    validate_success, waive_exception, clear_exceptions,
)


def _underwrite_pair(stmt2_liabilities):
    """Two BEACON-shaped deals differing only in the second statement's liabilities."""
    o = setup_officers(["rm", "an"])
    out = {}
    for key, legal, liabilities in (
            ("app1", "Leverage Exact LLC", 40_000_000),
            ("app2", "Leverage Over LLC", stmt2_liabilities)):
        bor = create_borrower(o, legal_name=legal, relationship_since="2018-01-01")
        app = validate_success(api_client.create_loan_application(
            loan_application_payload(bor["id"], requested_amount_cents=30_000_000, term_months=60),
            o["rm"]["headers"]), 201)
        stmt = attach_statement(o, app["id"], shape="BEACON",
                                total_liabilities_cents=liabilities)
        submit_application(o, app["id"])
        spread_and_finalize(o, stmt["id"])
        out[key] = finalize_spreads(o, app["id"])
    return o, out


def test_leverage_boundary_inclusive_side_lands_band_3():
    """PRD section 3.2: "The leverage factor uses the ratio of `total_liabilities_cents`
    to `total_assets_cents`, itself computed to four decimal places with round-half-up:
    100 points when the ratio is at most 0.50 ... with each boundary inclusive" and
    "the score is the sum of 0.40 times the debt-service-coverage points, 0.30 times
    the leverage points, and 0.10 times the tenure points, all divided by 0.80,
    rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/risk_rating_tiered_weight_renormalization
    """
    o, apps = _underwrite_pair(40_008_000)
    app1 = apps["app1"]
    # leverage 40,000,000 / 80,000,000 == 0.5000 exactly -> 100 points (inclusive)
    assert app1["dscr_standard"] == 1.2982, "leverage does not feed DSCR"
    # (0.4*60 + 0.3*100 + 0.1*75)/0.80 == 76.88 -> band 3
    assert app1["risk_rating"] == 3
    assert app1["rating_basis"] == "PROVISIONAL"


def test_leverage_one_ten_thousandth_over_lands_band_4():
    """PRD section 3.2: "100 points when the ratio is at most 0.50, 80 when at most
    0.65" — 0.5001 is not at most 0.50 — and the provisional score "divided by 0.80"
    renormalizes the excluded coverage factor.

    Design: Difficulty/combinatorial_formula/risk_rating_tiered_weight_renormalization
    """
    o, apps = _underwrite_pair(40_008_000)
    app2 = apps["app2"]
    # leverage 40,008,000 / 80,000,000 == 0.5001 -> 80 points (one step down)
    assert app2["dscr_standard"] == 1.2982
    # (0.4*60 + 0.3*80 + 0.1*75)/0.80 == 69.38 -> band 4
    assert app2["risk_rating"] == 4
    assert app2["rating_basis"] == "PROVISIONAL"


def test_tenure_and_leverage_tier_boundaries_drive_rating():
    """PRD section 3.2: "The tenure factor counts whole years elapsed between the
    borrower's `relationship_since` and the logical clock's current date, discarding
    any fractional year: 100 points at ten years or more, 75 at five or more, 50 at
    two or more, and 25 otherwise." and "The leverage factor ... 100 points when the
    ratio is at most 0.50, 80 when at most 0.65, 60 when at most 0.75 ... with each
    boundary inclusive."

    Design: Corner/calculations/tenure_and_leverage_tier_boundaries_drive_rating
    """
    o = setup_officers(["rm", "an"])
    results = {}
    for key, legal, since in (("app1", "Tenure Exact LLC", "2021-08-01"),
                              ("app2", "Tenure Short LLC", "2021-08-02")):
        bor = create_borrower(o, legal_name=legal, relationship_since=since)
        app = validate_success(api_client.create_loan_application(
            loan_application_payload(bor["id"], requested_amount_cents=30_000_000, term_months=60),
            o["rm"]["headers"]), 201)
        stmt = attach_statement(o, app["id"], shape="TENURE")
        submit_application(o, app["id"])
        spread_and_finalize(o, stmt["id"])
        results[key] = finalize_spreads(o, app["id"])

    # Both: dscr 13,479,805 / 9,628,432 == 1.4000 -> 80 pts; leverage 0.7500 -> 60 pts.
    assert results["app1"]["dscr_standard"] == 1.4000
    assert results["app2"]["dscr_standard"] == 1.4000

    # 2021-08-01 -> 2026-08-01 is exactly 5 years -> 75 tenure points.
    # (0.4*80 + 0.3*60 + 0.1*75)/0.80 == 71.88 -> band 3
    assert results["app1"]["risk_rating"] == 3
    assert results["app1"]["status"] == "APPRAISAL_REVIEW"

    # 2021-08-02 -> 2026-08-01 is 4 years 364 days -> floor 4 -> 50 tenure points.
    # (0.4*80 + 0.3*60 + 0.1*50)/0.80 == 68.75 -> band 4
    assert results["app2"]["risk_rating"] == 4
    assert results["app2"]["status"] == "APPRAISAL_REVIEW"


def test_full_vs_provisional_basis_diverges_on_coverage():
    """PRD section 3.5: "submission recomputes the `risk_rating` on the `FULL` basis:
    the collateral-coverage factor now contributes its tier — 100 points when the
    ratio of `total_eligible_collateral_cents` to `requested_amount_cents` is at
    least 1.25, 75 when at least 1.00, 50 when at least 0.75, and 25 otherwise —
    and the score is 0.40 times the debt-service-coverage points, plus 0.30 times
    the leverage points, plus 0.20 times the collateral-coverage points, plus 0.10
    times the tenure points, rounded half-up to two decimal places and banded as in
    section 3.2, with `rating_basis` recorded as `FULL`."

    Design: Corner/calculations/full_vs_provisional_basis_diverges_on_coverage
    """
    # BEACON deal: provisional 76.88 -> band 3; appraisal 28,000,000/26,000,000.
    ctx = deal_underwritten(officer_keys=("rm", "an", "po", "apm"))
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    assert ctx["underwriting"]["risk_rating"] == 3
    assert ctx["underwriting"]["rating_basis"] == "PROVISIONAL"

    waive_all = list_exceptions(o, app_id, status="OPEN")
    for exc in waive_all:
        waive_exception(o, exc["id"], "Stress shortfall accepted by credit policy desk")
    clear_exceptions(o, app_id)

    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, app_id, appraiser["id"], 28_000_000, 26_000_000)

    sized = submit_to_committee(o, app_id)
    # coverage = 21,000,000 / 30,000,000 == 0.7000 -> 25 pts
    # FULL score = 0.4*60 + 0.3*100 + 0.2*25 + 0.1*75 == 66.50 -> band 4
    assert sized["risk_rating"] == 4
    assert sized["rating_basis"] == "FULL"
    # LTV cap floor(28,000,000 x 0.80) == 22,400,000 binds the sizing.
    assert sized["proposed_amount_cents"] == 22_400_000

    open_exc = list_exceptions(o, app_id, status="OPEN")
    open_codes = {e["rule_code"] for e in open_exc}
    assert "LTV_MAXIMUM" in open_codes, "30,000,000 / 28,000,000 == 1.0714 > 0.8000"
    assert "COLLATERAL_COVERAGE_MIN" in open_codes, "21,000,000 < 30,000,000"
    for e in open_exc:
        assert e["severity"] == "HIGH"
