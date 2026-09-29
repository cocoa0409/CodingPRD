"""Catalogue uniqueness and the yield floor: the two guards that read the whole table.

Neither refusal here can be decided from the request body alone -- one reads every stored
code, the other reads a number the request never carries -- and both must leave the stored
row they collided with exactly as it was.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_DUPLICATE_MARKET_CODE,
    ERR_DUPLICATE_SCOPE_TEMPLATE_CODE,
    ERR_YIELD_BELOW_FLOOR,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    assert_page_meta,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    ASSET_PIPELINE,
    CASE_DRAFT,
    CASE_SUBMITTED,
    CASE_SUPERSEDED,
    CLOCK_AUG_01,
    OCC_VACANT,
)


def test_replaying_a_market_code_and_a_template_code_creates_no_second_row(api):
    """Uniqueness is operator-wide, so every other field differing changes nothing.

    PRD SS3.1 on the market: "A second registration reusing an existing `code` is refused
    with `ERR_DUPLICATE_MARKET_CODE`."  PRD SS3.1 on the catalogue: "Each template carries a
    `code` such as `PAINT_INT` or `HVAC_REPLACE` that must be unique across the catalogue --
    a duplicate is refused with `ERR_DUPLICATE_SCOPE_TEMPLATE_CODE`", and "Scope templates
    are immutable once published: there is no update capability, and correcting a benchmark
    means publishing a new template."  PRD SS2.9 fixes what a refusal may write: "if a guard
    rejects the operation, nothing at all is written, including the cascade targets."  The
    count comes from the listing envelope -- PRD SS2.3: "The four pagination fields reported
    in `meta` are `limit` (the effective page size actually applied), `offset` (the effective
    offset actually applied), `total_count` (the number of rows matching the filters before
    pagination) and `has_more` (true when rows remain beyond this page)."

    Design: Corner/validations/duplicate_market_and_scope_template_codes_are_rejected
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())

    failed(
        api.create_market(
            f.market_payload(
                code="ATL",
                name="Atlanta Metro Second Entry",
                tax_jurisdiction_code="GA-DEKALB",
                millage_bps=140,
                rent_index_cents=205000,
                cost_index_bps=10100,
                make_ready_target_days=28,
                max_pets=1,
                standard_lease_term_months=24,
            ),
            x.ADMIN,
        ),
        ERR_DUPLICATE_MARKET_CODE,
    )
    failed(
        api.create_scope_template(
            f.scope_template_paint(
                code="PAINT_INT",
                name="Interior Paint Deluxe",
                unit="SQFT",
                benchmark_unit_cost_cents=300000,
                default_crew_size=4,
                default_crew_days=4,
                safety_critical=True,
            ),
            x.ADMIN,
        ),
        ERR_DUPLICATE_SCOPE_TEMPLATE_CODE,
    )

    rows, meta = page(api.list_markets(x.ADMIN))
    assert_page_meta(meta, total_count=1)
    assert len(rows) == 1

    stored_market = ok(api.get_market(market["id"], x.ADMIN))
    assert_fields(stored_market, code="ATL", name="Atlanta", millage_bps=125)
    assert_money_group(stored_market, rent_index_cents=210000)

    stored_template = ok(api.get_scope_template(paint["id"], x.ADMIN))
    assert_fields(
        stored_template,
        code="PAINT_INT",
        name="Interior Paint",
        unit="HOME",
        safety_critical=False,
    )
    assert_money_group(stored_template, benchmark_unit_cost_cents=285050)


def test_the_floor_bites_on_submit_and_the_replacement_case_supersedes_the_draft(api):
    """470 basis points is created happily and only refused at the gate that checks it.

    PRD SS3.2: "A case sits in `DRAFT` until its analyst submits it ... Submission recomputes
    `planned_renovation_budget_cents` and the whole underwritten group *before* checking the
    yield floor, so a stale draft is never approved on stale numbers. If the recomputed
    `underwritten_yield_on_cost_bps` falls below the market's `underwriting_yield_floor_bps`,
    submission is refused with `ERR_YIELD_BELOW_FLOOR`. Continuing the example above, moving
    the purchase price to 30000000 and closing costs to 900000 against the same scope and rent
    gives a basis of 32379843 and a yield of 470 basis points, below a floor of 500, so the
    submission is refused."  The winning case is the PRD's own worked one: "Rounding per line
    gives 559906, 627761 and 292176 for a total of 1479843", which "yields a basis of
    27229843 ... net operating income of 1521184 and an underwritten yield of 559 basis
    points."  PRD SS3.2 on the supersede point: "Every prior underwriting case on the same
    home whose `status` is `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED` is moved to
    `SUPERSEDED` ... so a home has at most one live case at a time", and only the committee's
    approval moves the asset dimension.

    Design: Corner/validations/yield_floor_blocks_submit_until_a_better_case_supersedes_it
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    templates = x.three_trade_catalogue(api)
    home = x.create_home(api, market["id"])
    lines = [
        f.scope_line(templates.paint["id"], 1),
        f.scope_line(templates.hvac["id"], 1),
        f.scope_line(templates.floor["id"], 1150),
    ]

    thin = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"],
                home["version"],
                lines,
                purchase_price_cents=30000000,
                acquisition_closing_costs_cents=900000,
            ),
            x.ANALYST,
        )
    )
    assert_fields(thin, status=CASE_DRAFT, underwritten_yield_on_cost_bps=470)
    assert_money_group(
        thin,
        planned_renovation_budget_cents=1479843,
        underwritten_all_in_basis_cents=32379843,
    )

    failed(api.submit_underwriting_case(thin["id"], {}, x.ANALYST), ERR_YIELD_BELOW_FLOOR)
    still_draft = ok(api.get_underwriting_case(thin["id"], x.ANALYST))
    assert_fields(still_draft, status=CASE_DRAFT)
    assert_absent_or_empty(still_draft, "submitted_by_user_id")

    replacement = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(home["id"], home["version"], lines), x.ANALYST
        )
    )
    assert_fields(
        ok(api.get_underwriting_case(thin["id"], x.ANALYST)), status=CASE_SUPERSEDED
    )

    submitted = ok(api.submit_underwriting_case(replacement["id"], {}, x.ANALYST))
    assert_fields(
        submitted,
        status=CASE_SUBMITTED,
        submitted_by_user_id="analyst-1",
        underwritten_yield_on_cost_bps=559,
    )
    assert_money_group(
        submitted,
        planned_renovation_budget_cents=1479843,
        underwritten_all_in_basis_cents=27229843,
        underwritten_noi_cents=1521184,
    )
    assert_home_dimensions(
        ok(api.get_home(home["id"], x.ANALYST)), ASSET_PIPELINE, OCC_VACANT
    )
