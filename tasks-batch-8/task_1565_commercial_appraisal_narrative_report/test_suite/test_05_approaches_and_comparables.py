"""Valuation approaches and comparable sales: per-type completion gates,
indicated values per approach rule, cap-rate support tolerance, comparable
lookback, and the exclude/include cycle (PRD §3.4, §3.5, §3.6)."""
from test_helpers import (
    TEST_USERS,
    add_approach,
    add_comparable,
    add_data_submission,
    add_income_approach,
    add_support_comparables,
    create_draft_report,
    create_in_progress_engagement,
    create_parties,
    make_staff_appraiser_headers,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]

STMT_2025 = dict(
    submission_type="OPERATING_STATEMENT",
    period_start="2025-01-01T00:00:00Z",
    period_end="2025-12-31T00:00:00Z",
    scheduled_gross_rent_cents=12000000,
    vacancy_loss_cents=600000,
    expense_reimbursements_cents=300000,
    operating_expenses_cents=4000000,
)

# The canonical evidence set yields supported cap rate 685 bps:
# Oak: round(650000*10000/10000000)=650, adjusted 650.
# Elm: round(600000*10000/8000000)=750, adjusted round(750*0.96)=720.
# supported = round(mean(650, 720)) = 685.
COMP_OAK = dict(address="200 Oak Ave", sale_date="2026-03-01T00:00:00Z",
                sale_price_cents=10000000, noi_at_sale_cents=650000,
                size_sf=5000, adjustment_pct=0, selected_for_support=True)
COMP_ELM = dict(address="300 Elm St", sale_date="2026-05-01T00:00:00Z",
                sale_price_cents=8000000, noi_at_sale_cents=600000,
                size_sf=4000, adjustment_pct=-4.00, selected_for_support=True)

DCF_FULL = dict(dcf_holding_period_years=5, dcf_discount_rate_bps=900,
                dcf_exit_cap_bps=750, revenue_growth_bps_annual=300)


def test_income_complete_requires_accepted_statement(api):
    """PRD §3.5: "For `INCOME`, in order: at least one `ACCEPTED` operating
    statement must exist on the engagement (`ERR_INCOME_DATA_MISSING`)". With
    the engagement's statement still standing `SUBMITTED`, completion fails.

    Design: Difficulty/cross_entity_state_dependency/income_complete_requires_accepted_statement
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, **STMT_2025)  # left SUBMITTED
    add_support_comparables(bundle)
    approach = add_income_approach(bundle, complete=False)
    res = api.complete_approach(approach["id"], bundle["author_headers"])
    validate_error(res, "ERR_INCOME_DATA_MISSING", expected_status=409)


def test_income_complete_after_statement_accepted(api):
    """PRD §3.5: "Completing an approach — `SELECTED` to `COMPLETE` — is
    gated per type", and once the operating statement stands `ACCEPTED` the
    INCOME gates pass; "When the DCF set is absent, direct capitalization
    applies: the selected statement's `noi_stabilized_cents` is multiplied by
    ten thousand and divided by the approach's `cap_rate_bps`, rounded
    half-up to whole cents" — 7,460,000 * 10,000 / 700 = 106,571,429.

    Design: Difficulty/cross_entity_state_dependency/income_complete_requires_accepted_statement
    """
    bundle = create_in_progress_engagement()
    sub = add_data_submission(bundle, **STMT_2025)
    add_support_comparables(bundle)
    approach = add_income_approach(bundle, complete=False)
    validate_success(
        api.accept_data_submission(sub["id"], bundle["author_headers"]), 200)
    completed = validate_success(
        api.complete_approach(approach["id"], bundle["author_headers"]), 200)
    assert completed["status"] == "COMPLETE"
    assert completed["indicated_value_cents"] == 106571429


def test_dcf_full_set_supersedes_direct_cap(api):
    """PRD §3.5: "When all four DCF fields are present, the discounted cash
    flow supersedes direct capitalization. It projects from trailing actuals
    — year one's net operating income is the selected statement's
    `noi_trailing_cents`" — and "The indicated value is the sum of the
    rounded annual present values plus the rounded terminal value." For
    trailing NOI 7,700,000 with growth 3%, discount 9%, five-year hold and a
    750 bps exit cap, the pinned per-year rounding yields 108,994,819.

    Design: Corner/calculations/dcf_full_set_value
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    approach = add_approach(bundle, complete=False, approach_type="INCOME",
                            weight_pct=100.00, cap_rate_bps=700, **DCF_FULL)
    completed = validate_success(
        api.complete_approach(approach["id"], bundle["author_headers"]), 200)
    assert completed["indicated_value_cents"] == 108994819, (
        f"DCF must supersede direct cap 106571429; expected 108994819, "
        f"got {completed['indicated_value_cents']}")


def test_dcf_partial_set_returns_409(api):
    """PRD §3.5: "the DCF set is all-or-none, so exactly some of the four DCF
    fields present is rejected with `ERR_DCF_ASSUMPTIONS_INCOMPLETE`".

    Design: Corner/calculations/dcf_partial_set_returns_409
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    approach = add_approach(
        bundle, complete=False, approach_type="INCOME", weight_pct=100.00,
        cap_rate_bps=700, dcf_holding_period_years=5, dcf_discount_rate_bps=900,
        dcf_exit_cap_bps=750)  # revenue_growth_bps_annual omitted
    res = api.complete_approach(approach["id"], bundle["author_headers"])
    validate_error(res, "ERR_DCF_ASSUMPTIONS_INCOMPLETE", expected_status=409)


def _setup_engagement_with_cap(parties, author, cap_rate_bps):
    """IN_PROGRESS engagement for `author` with accepted statement and the
    canonical comparable set; returns (bundle, approach) with the INCOME
    approach at `cap_rate_bps` still SELECTED."""
    author_headers = make_staff_appraiser_headers(author["id"])
    parties_local = dict(parties)
    parties_local["author"] = author
    parties_local["author_headers"] = author_headers
    bundle = create_in_progress_engagement(parties_local)
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_comparable(bundle, **COMP_OAK)
    add_comparable(bundle, **COMP_ELM)
    approach = add_income_approach(bundle, complete=False,
                                   cap_rate_bps=cap_rate_bps)
    return bundle, approach


def test_cap_rate_tolerance_exactly_25_allowed(api):
    """PRD §3.4: "The income approach may not stray from that market
    evidence: at income-approach completion (§3.5), the approach's own rate
    must sit within twenty-five basis points of the supported rate, inclusive
    — a gap of exactly twenty-five basis points is allowed." Supported rate
    685 bps; the approach at 710 bps completes.

    Design: Corner/calculations/cap_rate_tolerance_boundary
    """
    parties = create_parties()
    bundle_a, approach_a = _setup_engagement_with_cap(
        parties, parties["author"], 710)
    completed = validate_success(
        api.complete_approach(approach_a["id"], bundle_a["author_headers"]), 200)
    assert completed["status"] == "COMPLETE", (
        "a cap rate exactly 25 bps from the supported rate must be allowed")


def test_cap_rate_tolerance_26_rejected(api):
    """PRD §3.5: "the approach's `cap_rate_bps` must lie within the
    twenty-five-basis-point tolerance of the supported rate from §3.4
    (`ERR_CAP_RATE_UNSUPPORTED`)" — at 711 bps against the 685 bps supported
    rate the 26 bps gap exceeds the tolerance.

    Design: Corner/calculations/cap_rate_tolerance_boundary
    """
    parties = create_parties()
    bundle_b, approach_b = _setup_engagement_with_cap(
        parties, parties["author"], 711)
    res = api.complete_approach(approach_b["id"], bundle_b["author_headers"])
    validate_error(res, "ERR_CAP_RATE_UNSUPPORTED", expected_status=409)


def test_sales_comparison_indicated_value(api):
    """PRD §3.5: "For each comparable marked `selected_for_support`, the
    adjusted unit value is the sale price adjusted by its `adjustment_pct`
    and divided by its `size_sf`, rounded half-up to whole cents; the
    indicated value is the mean of those unit values multiplied by the
    subject's `building_sf`, again rounded half-up to whole cents." Units
    2,000 and 1,920 cents/sf average 1,960; times 30,000 sf = 58,800,000.

    Design: Corner/calculations/sales_comparison_indicated_value
    """
    bundle = create_in_progress_engagement()
    add_comparable(bundle, **COMP_OAK)
    add_comparable(bundle, **COMP_ELM)
    approach = add_approach(bundle, complete=True,
                            approach_type="SALES_COMPARISON", weight_pct=100.00)
    assert approach["indicated_value_cents"] == 58800000, (
        f"expected 58800000, got {approach['indicated_value_cents']}")


def test_cost_approach_indicated_value(api):
    """PRD §3.5: "the indicated value is `land_value_cents` plus the
    depreciated replacement cost — `replacement_cost_cents` reduced by
    `depreciation_pct` percent, rounded half-up to whole cents."
    5,000,000 + 20,000,000 * (1 - 0.20) = 21,000,000.

    Design: Corner/calculations/cost_approach_indicated_value
    """
    bundle = create_in_progress_engagement()
    approach = add_approach(
        bundle, complete=True, approach_type="COST", weight_pct=100.00,
        land_value_cents=5000000, replacement_cost_cents=20000000,
        depreciation_pct=20.00)
    assert approach["indicated_value_cents"] == 21000000, (
        f"expected 21000000, got {approach['indicated_value_cents']}")


def test_duplicate_approach_type_returns_409(api):
    """PRD §3.5: "a given type may appear only once per engagement, a second
    approach of the same type being rejected with
    `ERR_DUPLICATE_APPROACH_TYPE`."

    Design: Corner/errors/duplicate_approach_type_returns_409
    """
    bundle = create_in_progress_engagement()
    add_income_approach(bundle, complete=False)
    res = api.create_approach(
        bundle["engagement"]["id"],
        dict(approach_type="INCOME", weight_pct=50.00, cap_rate_bps=725),
        bundle["author_headers"])
    validate_error(res, "ERR_DUPLICATE_APPROACH_TYPE", expected_status=409)


def test_sales_complete_without_comps_returns_409(api):
    """PRD §3.5: "For `SALES_COMPARISON`: at least one selected comparable
    must exist (`ERR_COMPARABLES_INSUFFICIENT`)."

    Design: Corner/errors/sales_complete_without_comps_returns_409
    """
    bundle = create_in_progress_engagement()
    approach = add_approach(bundle, complete=False,
                            approach_type="SALES_COMPARISON", weight_pct=100.00)
    res = api.complete_approach(approach["id"], bundle["author_headers"])
    validate_error(res, "ERR_COMPARABLES_INSUFFICIENT", expected_status=409)


def test_cost_complete_without_inputs_returns_409(api):
    """PRD §3.5: "For `COST`: land value, replacement cost, and depreciation
    must all be present (`ERR_COST_INPUTS_INCOMPLETE`)."

    Design: Corner/errors/cost_complete_without_inputs_returns_409
    """
    bundle = create_in_progress_engagement()
    approach = add_approach(bundle, complete=False, approach_type="COST",
                            weight_pct=100.00)
    res = api.complete_approach(approach["id"], bundle["author_headers"])
    validate_error(res, "ERR_COST_INPUTS_INCOMPLETE", expected_status=409)


def test_approach_complete_twice_returns_409(api):
    """PRD §3.5: "Completing an approach — `SELECTED` to `COMPLETE`" — the
    only entry transition; repeating it from `COMPLETE` fails state validity
    with `ERR_INVALID_STATE_TRANSITION` (§2.9).

    Design: Corner/state_machines/approach_complete_twice_returns_409
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    approach = add_income_approach(bundle, complete=True)
    assert approach["status"] == "COMPLETE"
    res = api.complete_approach(approach["id"], bundle["author_headers"])
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_comparable_age_boundary(api):
    """PRD §3.4: "A comparable's `sale_date` may not lie in the future, and
    it may not fall earlier than twenty-four months before the engagement's
    `accepted_at`; a sale breaching that lookback is rejected with
    `ERR_COMPARABLE_TOO_OLD`." Against an acceptance at 2026-08-01, a
    2024-07-31 sale breaches the lookback while 2024-08-01 is exactly
    twenty-four months back and enters the file; its implied rate is
    round_half_up(600,000 * 10,000 / 9,000,000) = 667 bps ("`implied_cap_rate_bps`
    is the sale's NOI multiplied by ten thousand and divided by its sale
    price", §3.4).

    Design: Corner/calculations/comparable_age_boundary
    """
    bundle = create_in_progress_engagement()
    res_old = api.create_comparable(
        bundle["engagement"]["id"],
        dict(address="400 Boundary Rd", sale_date="2024-07-31T00:00:00Z",
             sale_price_cents=9000000, noi_at_sale_cents=600000,
             size_sf=4500, adjustment_pct=0, selected_for_support=True),
        bundle["author_headers"])
    validate_error(res_old, "ERR_COMPARABLE_TOO_OLD", expected_status=409)

    comp = validate_success(api.create_comparable(
        bundle["engagement"]["id"],
        dict(address="401 Boundary Rd", sale_date="2024-08-01T00:00:00Z",
             sale_price_cents=9000000, noi_at_sale_cents=600000,
             size_sf=4500, adjustment_pct=0, selected_for_support=True),
        bundle["author_headers"]), 201)
    assert comp["implied_cap_rate_bps"] == 667


def test_approach_exclude_blocks_submit_review(api):
    """PRD §3.5: "Excluded approaches are omitted from reconciliation
    entirely (§3.6)" and PRD §3.6: "at least one approach must stand
    `COMPLETE` and not `EXCLUDED` (`ERR_NO_COMPLETED_APPROACH`)". Excluding
    the engagement's only approach therefore blocks submit_review.

    Design: Difficulty/non_linear_state_machine/approach_exclude_include_cycle
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    approach = add_income_approach(bundle, complete=True)
    report = create_draft_report(bundle)

    excluded = validate_success(
        api.exclude_approach(approach["id"], bundle["author_headers"]), 200)
    assert excluded["status"] == "EXCLUDED"
    res = api.submit_review(report["id"], bundle["author_headers"])
    validate_error(res, "ERR_NO_COMPLETED_APPROACH", expected_status=409)


def test_approach_include_restores_submit_review(api):
    """PRD §3.5: "An approach the author no longer wishes to rely on can be
    excluded — `COMPLETE` to `EXCLUDED` — and later re-included, returning
    `EXCLUDED` to `COMPLETE`; both actions require the author and an
    `IN_PROGRESS` engagement, and the cycle is unrestricted while the
    engagement is in progress." After re-inclusion the draft submits to
    `INTERNAL_REVIEW`.

    Design: Difficulty/non_linear_state_machine/approach_exclude_include_cycle
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    approach = add_income_approach(bundle, complete=True)
    report = create_draft_report(bundle)

    validate_success(
        api.exclude_approach(approach["id"], bundle["author_headers"]), 200)
    included = validate_success(
        api.include_approach(approach["id"], bundle["author_headers"]), 200)
    assert included["status"] == "COMPLETE"
    submitted = validate_success(
        api.submit_review(report["id"], bundle["author_headers"]), 200)
    assert submitted["status"] == "INTERNAL_REVIEW"
