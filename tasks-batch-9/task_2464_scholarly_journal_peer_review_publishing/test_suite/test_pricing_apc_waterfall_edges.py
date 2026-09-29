"""Edge cases of the article processing charge waterfall: half-cent rounding and write-off."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _setup_small_residual_invoice():
    """An invoice whose net charge lands between zero and the minimum billable.

    A list price of 2200 cents under `CC_BY_NC_ND` gives 2200 * 0.85 = 1870;
    a `HIGH` income band waives nothing; the institutional discount takes
    15 percent of the 1870-cent post-waiver remainder, 280.5 rounded half up
    to 281; the net is 1870 - 0 - 281 = 1589, which is above 0 and below 2000.
    """
    world = fx.setup_in_production(
        journal_overrides={"apc_base_cents": 2200},
        author_overrides={"country_income_band": "HIGH", "institutional_agreement": True},
        manuscript_overrides={"oa_license": "CC_BY_NC_ND"},
    )
    world["invoice"] = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=0, color_figure_count=0
    )
    return world


def _setup_half_cent_waiver_invoice():
    """An invoice whose income-band waiver falls exactly on a half cent.

    A list price of 90010 cents under `CC_BY` keeps a base of 90010; the
    `UPPER_MIDDLE` band waives 25 percent, that is 22502.5 cents exactly.
    """
    world = fx.setup_in_production(
        journal_overrides={"apc_base_cents": 90010},
        author_overrides={
            "country_income_band": "UPPER_MIDDLE",
            "institutional_agreement": False,
        },
        manuscript_overrides={"oa_license": "CC_BY"},
    )
    world["invoice"] = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=0, color_figure_count=0
    )
    return world


def test_residual_below_the_minimum_billable_is_written_off_to_zero():
    """A 1589-cent net sits inside the write-off band, so it is forced to zero.

    PRD: "**Step five** writes off small balances with a strict test: `auto_waived` starts false, and when `net_apc_cents` is greater than 0 **and** strictly below 2000 cents — the minimum billable amount, twenty currency units — `net_apc_cents` is forced to 0 and `auto_waived` becomes true."

    Design: Corner/calculations/apc_small_residual_auto_written_off_below_min_billable
    """
    world = _setup_small_residual_invoice()

    a.assert_invoice_amounts(
        world["invoice"],
        base_cents=1870,
        waiver_cents=0,
        institutional_cents=281,
        net_apc_cents=0,
        total_due_cents=0,
    )
    a.assert_fields(
        world["invoice"], waiver_pct=0, institutional_pct=15, auto_waived=True
    )


def test_automatic_write_off_leaves_both_fee_ledgers_at_zero():
    """A written-off invoice bills nothing and credits nothing to the waived ledger.

    PRD: "A journal's `apc_waived_cents` rises by `total_due_cents` only on a waiver, and is untouched by payment and by cancellation."

    Design: Corner/calculations/apc_small_residual_auto_written_off_below_min_billable
    """
    world = _setup_small_residual_invoice()

    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]),
        apc_receivable_cents=0,
        apc_waived_cents=0,
    )


def test_zero_total_invoice_clears_the_fee_dimension_at_issuance():
    """Nothing is left to settle, so issuance alone moves the clearance dimension.

    PRD: "An invoice whose `total_due_cents` computes to 0 — a green self-archived paper with no surcharges, or a fully waived one — needs no settlement at all, and its issuance immediately advances the manuscript's production job on the clearance dimension, `LICENSE_PENDING → FEE_CLEARED`."

    Design: Corner/calculations/apc_small_residual_auto_written_off_below_min_billable
    """
    world = _setup_small_residual_invoice()

    a.assert_fields(world["invoice"], status="ISSUED", total_due_cents=0)
    a.assert_fields(
        fx.get_production_job(world["job"]["id"]), clearance_stage="FEE_CLEARED"
    )


def test_income_band_waiver_rounds_a_half_cent_up():
    """22502.5 cents of waiver rounds half up to 22503, never down to 22502.

    PRD: "**Step two** applies the income-band waiver: `waiver_pct` is taken from the corresponding author's `country_income_band`, being 0 for `HIGH`, 25 for `UPPER_MIDDLE`, 50 for `LOWER_MIDDLE` and 100 for `LOW`, and `waiver_cents` is `base_cents` multiplied by `waiver_pct` divided by 100, rounded half up to a whole cent."

    Design: Corner/calculations/apc_waiver_half_cent_rounds_half_up
    """
    world = _setup_half_cent_waiver_invoice()

    a.assert_fields(world["invoice"], waiver_pct=25, auto_waived=False)
    a.assert_invoice_amounts(
        world["invoice"], base_cents=90010, waiver_cents=22503, institutional_cents=0
    )
    assert world["invoice"]["waiver_cents"] != 22502, (
        "half up must not truncate the half cent away"
    )


def test_half_cent_waiver_carries_through_to_the_net_and_the_receivable():
    """The rounded-up waiver is what the net charge and the ledger are built from.

    PRD: "**Step four** forms `net_apc_cents` as `base_cents` less `waiver_cents` less `institutional_cents`."

    Design: Corner/calculations/apc_waiver_half_cent_rounds_half_up
    """
    world = _setup_half_cent_waiver_invoice()

    a.assert_invoice_amounts(
        world["invoice"], net_apc_cents=67507, surcharge_cents=0, total_due_cents=67507
    )
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]),
        apc_receivable_cents=67507,
        apc_waived_cents=0,
    )
