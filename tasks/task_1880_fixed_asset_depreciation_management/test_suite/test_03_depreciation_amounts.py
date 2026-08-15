"""Book and tax depreciation amount calculations: dual-ledger divergence, bonus,
rounding order, method variants, and immediate post visibility."""
from test_helpers import (
    ACCT,
    book_entries,
    create_and_post_run,
    create_class,
    create_in_service_asset,
    setup_asset_with_posted_runs,
    tax_entries,
    validate_success,
)


def test_book_entry_straight_line_first_period(api):
    """PRD §3.3: "Under `STRAIGHT_LINE`, the amount is the remaining basis
    (depreciable basis minus `accumulated_book_cents`) divided evenly across the
    remaining months (`useful_life_months` minus the number of book entries
    already posted), rounded half-up to a whole cent."
    PRD §3.3: "Each created entry adds its `amount_cents` to the asset's
    `accumulated_book_cents` or `accumulated_tax_cents` (never negative amounts)
    and increments the asset's `version`."

    Design: Difficulty/dual_variant_calc/book_vs_tax_period_amount_divergence
    """
    cls = create_class(bonus_depreciation_allowed=True)
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01"], asset_class_id=cls["id"], asset_tag="A-100",
        description="Lathe", acquisition_cost_cents=600000, bonus_elected=True,
    )

    entries = book_entries(asset["id"])
    assert len(entries) == 1, "exactly one BOOK entry for period 2026-01"
    assert entries[0]["period"] == "2026-01"
    assert entries[0]["amount_cents"] == 10000, "600000 / 60 straight-line"
    assert asset["accumulated_book_cents"] == 10000


def test_tax_entry_macrs_bonus_first_period(api):
    """PRD §3.3: "The five-year table's annual rates, for tax years 1 through 6,
    are 20.00%, 32.00%, 19.20%, 11.52%, 11.52%, and 5.76%."
    PRD §3.3: "When `bonus_elected` is true, the year-1 annual amount is sixty
    percent of `acquisition_cost_cents` expensed immediately, plus the applicable
    year-1 table rate applied to the remaining forty percent."
    PRD §3.2: "`net_book_value_cents` is the acquisition cost minus
    `accumulated_book_cents` minus `impairment_total_cents`."

    Design: Difficulty/dual_variant_calc/book_vs_tax_period_amount_divergence
    """
    cls = create_class(bonus_depreciation_allowed=True)
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01"], asset_class_id=cls["id"], asset_tag="A-100",
        description="Lathe", acquisition_cost_cents=600000, bonus_elected=True,
    )

    entries = tax_entries(asset["id"])
    assert len(entries) == 1, "exactly one TAX entry for period 2026-01"
    assert entries[0]["period"] == "2026-01"
    # 600000*0.60 + 600000*0.40*0.20 = 408000 annual; 408000/12 = 34000.
    assert entries[0]["amount_cents"] == 34000
    assert asset["accumulated_tax_cents"] == 34000
    assert asset["net_book_value_cents"] == 590000, (
        "590000 = 600000 - 10000 book - 0 impairment; tax ledger never moves NBV"
    )


def test_bonus_elected_year1_tax_amount(api):
    """PRD §3.3: "When `bonus_elected` is true, the year-1 annual amount is sixty
    percent of `acquisition_cost_cents` expensed immediately, plus the applicable
    year-1 table rate applied to the remaining forty percent."
    PRD §3.3: "The five-year table's annual rates, for tax years 1 through 6,
    are 20.00%, 32.00%, 19.20%, 11.52%, 11.52%, and 5.76%."

    Design: Difficulty/combinatorial_formula/macrs_bonus_year1_combinatorial
    """
    cls = create_class(bonus_depreciation_allowed=True)
    bonus_asset = create_in_service_asset(
        cls["id"], asset_tag="B-1", description="Bonus asset",
        acquisition_cost_cents=600000, bonus_elected=True,
    )
    create_in_service_asset(
        cls["id"], asset_tag="B-2", description="Plain asset",
        acquisition_cost_cents=600000, bonus_elected=False,
    )
    create_and_post_run("2026-01")

    entries = tax_entries(bonus_asset["id"])
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 34000, (
        "bonus branch: 600000*0.60 + 600000*0.40*0.20 = 408000 annual, /12"
    )


def test_standard_macrs_year1_tax_amount_and_run_totals(api):
    """PRD §3.3: "When bonus is not elected (or the class disallows it), the base
    is the full `acquisition_cost_cents` in every year."
    PRD §3.3: "The run itself records the sweep's summary:
    `entries_created_count`, `total_book_amount_cents` (the sum of `BOOK` entry
    amounts in the run), and `total_tax_amount_cents` (the sum of `TAX`
    amounts)."

    Design: Difficulty/combinatorial_formula/macrs_bonus_year1_combinatorial
    """
    cls = create_class(bonus_depreciation_allowed=True)
    bonus_asset = create_in_service_asset(
        cls["id"], asset_tag="B-1", description="Bonus asset",
        acquisition_cost_cents=600000, bonus_elected=True,
    )
    plain_asset = create_in_service_asset(
        cls["id"], asset_tag="B-2", description="Plain asset",
        acquisition_cost_cents=600000, bonus_elected=False,
    )
    run = create_and_post_run("2026-01")

    plain_tax = tax_entries(plain_asset["id"])
    assert len(plain_tax) == 1
    assert plain_tax[0]["amount_cents"] == 10000, (
        "standard branch: 600000*0.20 = 120000 annual, /12"
    )

    # The bonus branch touches only the TAX ledger: both BOOK entries are 10000.
    assert book_entries(bonus_asset["id"])[0]["amount_cents"] == 10000
    assert book_entries(plain_asset["id"])[0]["amount_cents"] == 10000

    assert run["entries_created_count"] == 4, "2 assets x 2 ledgers"
    assert run["total_book_amount_cents"] == 20000
    assert run["total_tax_amount_cents"] == 44000


def test_straight_line_per_month_rounding_sequence(api):
    """PRD §2.5: "Rounding is applied **per posting period independently**: each
    month's depreciation is computed and rounded on its own, and the final month
    of a schedule takes the remaining un-depreciated balance as a remainder plug.
    A sum-then-round approach across multiple months is not permitted, because
    the per-month rounding decisions are pinned by this document."

    Design: Difficulty/combinatorial_formula/per_month_rounding_final_plug
    """
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02", "2026-03"], asset_class_id=cls["id"],
        asset_tag="R-1", description="Rounding asset",
        acquisition_cost_cents=100000, useful_life_months=3,
    )

    by_period = {e["period"]: e["amount_cents"] for e in book_entries(asset["id"])}
    assert by_period["2026-01"] == 33333, "round_half_up(100000/3)"
    assert by_period["2026-02"] == 33334, "round_half_up(66667/2)"
    assert by_period["2026-03"] == 33333, "final-month plug: 100000 - 66667"


def test_final_month_plug_sums_to_basis_exactly(api):
    """PRD §3.3: "In the **final month** of the schedule under either method —
    when the number of book entries already posted equals `useful_life_months`
    minus one — the amount is the remainder plug: the depreciable basis minus
    `accumulated_book_cents`, whatever that residue is after prior months'
    rounding."
    PRD §3.3: "After an asset's entries are applied, if its
    `accumulated_book_cents` has reached the depreciable basis — acquisition cost
    minus salvage minus impairment — the asset automatically transitions from
    `IN_SERVICE` to `FULLY_DEPRECIATED`; the tax ledger never triggers this
    transition."

    Design: Difficulty/combinatorial_formula/per_month_rounding_final_plug
    """
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02", "2026-03"], asset_class_id=cls["id"],
        asset_tag="R-1", description="Rounding asset",
        acquisition_cost_cents=100000, useful_life_months=3,
    )

    assert asset["accumulated_book_cents"] == 100000, (
        "per-month rounding sums exactly to the basis — no drift"
    )
    assert asset["status"] == "FULLY_DEPRECIATED"


def test_double_declining_book_amounts(api):
    """PRD §3.3: "Under `DOUBLE_DECLINING`, the amount is the current
    `net_book_value_cents` multiplied by two and divided by `useful_life_months`,
    rounded half-up to a whole cent — an accelerated charge on a declining
    balance. If adding that amount would push `accumulated_book_cents` past the
    depreciable basis, the amount is capped at exactly the remaining basis, so
    the ledger never over-depreciates."

    Design: Corner/calculations/double_declining_book_amounts
    """
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02"], asset_class_id=cls["id"], asset_tag="DDB-1",
        description="DDB asset", acquisition_cost_cents=600000,
        book_method="DOUBLE_DECLINING",
    )

    by_period = {e["period"]: e["amount_cents"] for e in book_entries(asset["id"])}
    assert by_period["2026-01"] == 20000, "round_half_up(600000*2/60)"
    assert by_period["2026-02"] == 19333, (
        "round_half_up(580000*2/60) — declining, not level"
    )
    assert asset["accumulated_book_cents"] == 39333


def test_tax_straight_line_method_amounts(api):
    """PRD §3.3: "Under `TAX_STRAIGHT_LINE`, each period's amount is
    `acquisition_cost_cents` divided by `useful_life_months`, rounded half-up to
    a whole cent, and the final tax month takes the plug of
    `acquisition_cost_cents` minus `accumulated_tax_cents` so the tax ledger
    lands exactly on cost."

    Design: Corner/calculations/tax_straight_line_method_amounts
    """
    cls = create_class(
        class_code="FURN", name="Furniture",
        capitalization_threshold_cents=100000, default_useful_life_months=12,
        tax_method="TAX_STRAIGHT_LINE",
    )
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01"], asset_class_id=cls["id"], asset_tag="TSL-1",
        description="Tax SL asset", acquisition_cost_cents=120000,
    )

    entries = tax_entries(asset["id"])
    assert len(entries) == 1
    assert entries[0]["period"] == "2026-01"
    assert entries[0]["amount_cents"] == 10000, "round_half_up(120000/12)"


def test_macrs_year_transition_at_calendar_boundary(api):
    """PRD §3.3: "The tax year index of a run period is the run period's calendar
    year minus the in-service year plus one; tax years are calendar years, year 1
    begins at the in-service year, and all twelve monthly entries of year 1 are
    posted regardless of the in-service month, because the first-year convention
    is already baked into the year-1 rate."
    PRD §3.3: "The five-year table's annual rates, for tax years 1 through 6,
    are 20.00%, 32.00%, 19.20%, 11.52%, 11.52%, and 5.76%."

    Design: Corner/calculations/macrs_year_transition_at_calendar_boundary
    """
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2025-12", "2026-01"], asset_class_id=cls["id"],
        in_service_date="2025-12-10", asset_tag="YB-1",
        description="Year boundary", acquisition_cost_cents=600000,
    )

    tax_by_period = {e["period"]: e["amount_cents"]
                     for e in tax_entries(asset["id"])}
    # 2025-12 is a December entry: it takes the annual amount minus the sum of
    # the prior eleven monthly amounts (none exist — the asset entered service
    # in December), so the full year-1 annual amount 600000*0.20 = 120000 lands
    # in the single December entry and the year reconciles exactly.
    assert tax_by_period["2025-12"] == 120000, (
        "year index 1 December plug: 600000*0.20 - 0 prior monthly amounts"
    )
    assert tax_by_period["2026-01"] == 16000, "year index 2: 600000*0.32/12"

    book_by_period = {e["period"]: e["amount_cents"]
                      for e in book_entries(asset["id"])}
    assert book_by_period["2025-12"] == 10000
    assert book_by_period["2026-01"] == 10000, (
        "the tax year boundary does not move the book ledger"
    )


def test_immediate_visibility_after_run_post(api):
    """PRD §3.3: "Posting is atomic and cascading."
    PRD §3.3: "The run itself records the sweep's summary:
    `entries_created_count`, `total_book_amount_cents` (the sum of `BOOK` entry
    amounts in the run), and `total_tax_amount_cents` (the sum of `TAX`
    amounts)."
    PRD §3.3: "Each created entry adds its `amount_cents` to the asset's
    `accumulated_book_cents` or `accumulated_tax_cents` (never negative amounts)
    and increments the asset's `version`."

    Design: Corner/consistency_model/immediate_visibility_after_run_post
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-090", description="Immediate read",
        acquisition_cost_cents=600000,
    )
    run = validate_success(api.create_depreciation_run({"period": "2026-01"},
                                                       ACCT), 201)

    posted = validate_success(api.post_depreciation_run(run["id"], ACCT), 200)
    assert posted["status"] == "POSTED"
    assert posted["entries_created_count"] == 2
    assert posted["total_book_amount_cents"] == 10000
    assert posted["total_tax_amount_cents"] == 10000, "MACRS-5 year 1: 600000*0.20/12"

    after = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert after["accumulated_book_cents"] == 10000
    assert after["accumulated_tax_cents"] == 10000
    assert after["net_book_value_cents"] == 590000
