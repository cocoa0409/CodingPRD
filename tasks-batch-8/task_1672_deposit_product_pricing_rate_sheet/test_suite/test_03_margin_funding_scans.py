"""Margin analysis, funding-curve interpolation, and competitor scan
benchmarks (PRD §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_competitor_rate_scan,
    create_draft_sheet,
    create_effective_sheet,
    create_funding_curve,
    create_product,
    create_rate_sheet_payload,
    create_scan,
    open_account,
    scan_entry,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
)

# The standard tiers of the forward-vs-realized scenario: projected balances
# deliberately differ from the actual book opened below.
MARGIN_TIERS = [tier(0, 0, 10_000_000, 110, 5_000_000_000),
                tier(1, 10_000_000, -1, 160, 15_000_000_000)]


def _margin_scenario(api):
    """EFFECTIVE sheet (US-EAST) over MARGIN_TIERS, curve (0m -> 210 bp), and
    two OPEN accounts: 1,000,000 cents at 110 bp and 15,000,000 at 160 bp."""
    setup = create_effective_sheet(
        market_code="US-EAST", effective_date="2026-08-15", tiers=MARGIN_TIERS,
        product_overrides={"product_code": "SAV2", "product_class": "SAVINGS",
                           "term_months": 0, "tier_application": "WHOLE_BALANCE",
                           "rate_cap_bp": 500})
    create_funding_curve(curve_date="2026-08-01",
                         points=[{"tenor_months": 0, "cost_bp": 210}])
    open_account(setup["product_id"], market_code="US-EAST",
                 opening_balance_cents=1_000_000, customer_ref="C1", channel="BRANCH")
    open_account(setup["product_id"], market_code="US-EAST",
                 opening_balance_cents=15_000_000, customer_ref="C2", channel="BRANCH")
    return setup


def test_margin_forward_looking_uses_projected_balances(api, treasury_headers):
    """PRD §3.4: "The default, `FORWARD_LOOKING`, works from the sheet itself:
    `weighted_rate_bp` is the sum over tiers of each tier's `rate_bp`
    multiplied by its `projected_balance_cents`, divided by the sum of the
    projected balances, rounded half up to a whole basis point;
    `funding_cost_bp` comes from the operative curve at the product's tenor;
    and `margin_bp` is the weighted rate minus the funding cost."

    Design: Difficulty/dual_variant_calc/sheet_margin_forward_vs_realized_book
    """
    setup = _margin_scenario(api)
    sheet_id = setup["sheet"]["id"]
    data = validate_success(api.get_margin_analysis(
        sheet_id, treasury_headers, params={"variant": "FORWARD_LOOKING"}))
    # (110*5e9 + 160*15e9) / 2e10 = 147.5 -> 148 half up.
    assert data["weighted_rate_bp"] == 148
    assert data["funding_cost_bp"] == 210
    assert data["margin_bp"] == -62
    assert data["variant"] == "FORWARD_LOOKING"


def test_margin_realized_book_uses_actual_accounts(api, treasury_headers):
    """PRD §3.4: "The `REALIZED_BOOK` variant instead weights reality: the
    `OPEN` accounts of the sheet's product and market whose `rate_source` is
    `SHEET`, `PROMO`, or `EXCEPTION`, each contributing its `balance_cents` at
    its `current_rate_bp`."

    Design: Difficulty/dual_variant_calc/sheet_margin_forward_vs_realized_book
    """
    setup = _margin_scenario(api)
    sheet_id = setup["sheet"]["id"]
    data = validate_success(api.get_margin_analysis(
        sheet_id, treasury_headers, params={"variant": "REALIZED_BOOK"}))
    # (110*1e6 + 160*15e6) / 16e6 = 156.875 -> 157 half up.
    assert data["weighted_rate_bp"] == 157
    assert data["funding_cost_bp"] == 210
    assert data["margin_bp"] == -53

    # The two variants legitimately diverge on the same sheet at the same
    # instant: projected mix and realized mix differ.
    fwd = validate_success(api.get_margin_analysis(
        sheet_id, treasury_headers, params={"variant": "FORWARD_LOOKING"}))
    assert fwd["margin_bp"] != data["margin_bp"]


def test_competitor_benchmark_weighted_vs_simple(api, analyst_headers):
    """PRD §3.3: "The official benchmark, stored as `benchmark_weighted_bp`,
    weights each competitor entry's rate by its tier balance: the sum, over
    the class's entries, of each `rate_bp` multiplied by its
    `tier_balance_cents`, divided by the sum of the `tier_balance_cents`,
    rounded half up to a whole basis point. The reference benchmark, stored as
    `benchmark_simple_bp`, is the unweighted mean: the sum of the entries'
    rates divided by the number of entries, rounded half up; it diverges from
    the weighted figure whenever competitor balances are unequal."

    Design: Difficulty/dual_variant_calc/competitor_benchmark_weighted_vs_simple
    """
    scan = create_scan(entries=[
        scan_entry("Alpha", "MONEY_MARKET", 300, 400_000_000),
        scan_entry("Beta", "MONEY_MARKET", 250, 600_000_000),
    ])
    resp = api.analyze_competitor_rate_scan(scan["id"], analyst_headers)
    analyzed = validate_success(resp, 200)
    assert_competitor_rate_scan(analyzed)
    assert analyzed["status"] == "ANALYZED"
    # (300*400M + 250*600M) / 1000M = 270 exactly.
    assert analyzed["benchmark_weighted_bp"] == 270
    # (300 + 250) / 2 = 275.
    assert analyzed["benchmark_simple_bp"] == 275
    assert analyzed["benchmark_weighted_bp"] != analyzed["benchmark_simple_bp"]


def test_competitor_benchmark_values_persist_on_read(api, analyst_headers):
    """PRD §3.3: "Analysis, again by a `PricingAnalyst`, moves the scan from
    `SUBMITTED` to `ANALYZED` — requesting analysis in any other state is
    rejected with `ERR_SCAN_INVALID_STATE` — and computes two benchmark rates."
    The benchmarks are stored on the scan, so a later read returns the same
    figures.

    Design: Difficulty/dual_variant_calc/competitor_benchmark_weighted_vs_simple
    """
    scan = create_scan(entries=[
        scan_entry("Alpha", "MONEY_MARKET", 300, 400_000_000),
        scan_entry("Beta", "MONEY_MARKET", 250, 600_000_000),
    ])
    validate_success(api.analyze_competitor_rate_scan(scan["id"], analyst_headers))
    reread = validate_success(api.get_competitor_rate_scan(scan["id"], analyst_headers))
    assert reread["status"] == "ANALYZED"
    assert reread["benchmark_weighted_bp"] == 270
    assert reread["benchmark_simple_bp"] == 275


def test_scan_analyze_empty_entries_null_benchmarks(api, analyst_headers):
    """PRD §3.3: "When no entries match, both fields remain null."

    Design: Corner/calculations/scan_analyze_empty_entries_null_benchmarks
    """
    scan = create_scan(entries=[])
    analyzed = validate_success(api.analyze_competitor_rate_scan(scan["id"], analyst_headers), 200)
    assert analyzed["status"] == "ANALYZED"
    assert analyzed["benchmark_weighted_bp"] is None
    assert analyzed["benchmark_simple_bp"] is None


def test_scan_double_analyze_returns_scan_invalid_state(api, analyst_headers):
    """PRD §3.3: "Analysis, again by a `PricingAnalyst`, moves the scan from
    `SUBMITTED` to `ANALYZED` — requesting analysis in any other state is
    rejected with `ERR_SCAN_INVALID_STATE` — and computes two benchmark rates."

    Design: Corner/state_machines/scan_double_analyze_returns_scan_invalid_state
    """
    scan = create_scan(entries=[scan_entry("Alpha", "SAVINGS", 200, 1_000_000)])
    validate_success(api.analyze_competitor_rate_scan(scan["id"], analyst_headers))
    resp = api.analyze_competitor_rate_scan(scan["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SCAN_INVALID_STATE, 409)


def test_funding_cost_interpolates_between_tenors(api, treasury_headers):
    """PRD §3.4: "An exact tenor match on a curve point yields that point's
    `cost_bp` with no interpolation — a variable-rate product (tenor zero)
    therefore prices its funding at the zero-tenor point. Otherwise the cost
    is linearly interpolated between the two bracketing points: the lower
    point's cost, plus the fraction of the tenor distance between the two
    points' tenors that the product's tenor represents, multiplied by the
    difference between the two points' costs, with the result rounded half up
    to a whole basis point. A tenor beyond the curve's maximum point is
    rejected with `ERR_NO_FUNDING_CURVE`."

    Design: Corner/calculations/funding_cost_interpolates_between_tenors
    """
    create_funding_curve(curve_date="2026-08-01", points=[
        {"tenor_months": 0, "cost_bp": 210},
        {"tenor_months": 3, "cost_bp": 235},
        {"tenor_months": 6, "cost_bp": 255},
        {"tenor_months": 12, "cost_bp": 270},
    ])
    products = {}
    for code, term in [("F9", 9), ("F12", 12), ("F18", 18)]:
        products[term] = create_product(
            product_code=code, product_class="CD", term_months=term,
            rate_cap_bp=900, allows_promos=False, allows_exceptions=False)
    sheets = {}
    for term, market in [(9, "US-W9"), (12, "US-W12"), (18, "US-W18")]:
        sheets[term] = create_draft_sheet(products[term]["id"], market_code=market,
                                          tiers=single_tier(300))
    set_clock("2026-08-15")

    # Term 9 interpolates: 255 + (9-6)/(12-6) * (270-255) = 262.5 -> 263.
    data9 = validate_success(api.get_margin_analysis(
        sheets[9]["id"], treasury_headers, params={"variant": "FORWARD_LOOKING"}))
    assert data9["funding_cost_bp"] == 263
    assert data9["margin_bp"] == 300 - 263

    # Term 12 is an exact point match: 270, no interpolation.
    data12 = validate_success(api.get_margin_analysis(
        sheets[12]["id"], treasury_headers, params={"variant": "FORWARD_LOOKING"}))
    assert data12["funding_cost_bp"] == 270

    # Term 18 is beyond the curve's maximum point (12).
    resp = api.get_margin_analysis(sheets[18]["id"], treasury_headers,
                                   params={"variant": "FORWARD_LOOKING"})
    validate_error(resp, ApiErrorId.ERR_NO_FUNDING_CURVE, 422)


def test_margin_floor_boundary_equality_passes(api, analyst_headers):
    """PRD §3.2: "When the sheet's `margin_floor_bp` is greater than zero, the
    server computes the forward-looking margin (§3.4): an operative funding
    curve covering the product's tenor must exist (`ERR_NO_FUNDING_CURVE`),
    and the margin must be at least the floor — equality passes — else
    submission is rejected with `ERR_MARGIN_BELOW_FLOOR`."

    Design: Corner/calculations/margin_floor_boundary_equality_passes
    """
    create_funding_curve(curve_date="2026-08-01",
                         points=[{"tenor_months": 0, "cost_bp": 210}])
    product = create_product(product_code="FL")
    sheet_a = create_draft_sheet(product["id"], market_code="US-WA",
                                 margin_floor_bp=20, tiers=single_tier(230))
    sheet_b = create_draft_sheet(product["id"], market_code="US-WB",
                                 margin_floor_bp=20, tiers=single_tier(229))
    set_clock("2026-08-15")

    # Margin 230 - 210 = 20 equals the floor: the boundary is inclusive.
    submitted = validate_success(api.submit_rate_sheet(sheet_a["id"], analyst_headers))
    assert submitted["status"] == "COMMITTEE_REVIEW"

    # Margin 229 - 210 = 19 is one basis point below the floor.
    resp = api.submit_rate_sheet(sheet_b["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_FLOOR, 422)


def test_margin_realized_book_empty_book_not_computable(api, treasury_headers):
    """PRD §3.4: "With no qualifying account, the variant fails with
    `ERR_MARGIN_NOT_COMPUTABLE`."
    PRD §3.4: "Because it uses projected balances, the forward-looking variant
    is computable before any account exists — but if the sheet's projected
    balances sum to zero, the read fails with `ERR_MARGIN_NOT_COMPUTABLE`."

    Design: Corner/calculations/margin_realized_book_empty_book_not_computable
    """
    create_funding_curve(curve_date="2026-08-01",
                         points=[{"tenor_months": 0, "cost_bp": 210}])
    product = create_product(product_code="EM")
    sheet = create_draft_sheet(product["id"], tiers=single_tier(230))
    set_clock("2026-08-15")

    resp = api.get_margin_analysis(sheet["id"], treasury_headers,
                                   params={"variant": "REALIZED_BOOK"})
    validate_error(resp, ApiErrorId.ERR_MARGIN_NOT_COMPUTABLE, 422)

    fwd = validate_success(api.get_margin_analysis(
        sheet["id"], treasury_headers, params={"variant": "FORWARD_LOOKING"}))
    assert fwd["margin_bp"] == 20


def test_no_funding_curve_blocks_margin_gate(api, analyst_headers):
    """PRD §3.2: "When the sheet's `margin_floor_bp` is greater than zero, the
    server computes the forward-looking margin (§3.4): an operative funding
    curve covering the product's tenor must exist (`ERR_NO_FUNDING_CURVE`),
    and the margin must be at least the floor — equality passes — else
    submission is rejected with `ERR_MARGIN_BELOW_FLOOR`."

    Design: Corner/validations/no_funding_curve_blocks_margin_gate
    """
    product = create_product(product_code="NC")
    sheet = create_draft_sheet(product["id"], margin_floor_bp=10,
                               tiers=single_tier(300))
    resp = api.submit_rate_sheet(sheet["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_NO_FUNDING_CURVE, 422)
