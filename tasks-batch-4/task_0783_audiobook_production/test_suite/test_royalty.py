"""Royalty statement generation: split, rounding, tiered share, variants."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    admin_headers,
    assert_royalty_partition,
    setup_published_with_listing, setup_provisional_statement,
    finalize_statement,
)

# Shared sales set used by the PROVISIONAL/FINAL divergence + payout instances.
_DIVERGENCE_SALES = [
    {"units_sold": 100, "units_returned": 10, "unit_price_cents": 1500, "occurred_at": "2026-03-15T00:00:00Z"},
    {"units_sold": 50, "units_returned": 0, "unit_price_cents": 2000, "occurred_at": "2026-03-16T00:00:00Z"},
]


def test_provisional_statement_uses_units_sold(api):
    """PRD §3.7: "under the provisional variant the line quantity is `units_sold`".
    PRD §3.7: "The narrator's cut, `narrator_royalty_cents`, is `statement_net_cents`
    multiplied by `narrator_share_pct_applied`, rounded half up to whole cents. The
    author's cut, `author_royalty_cents`, is `statement_net_cents` minus
    `narrator_royalty_cents`, so the two cuts always partition the net exactly."

    Design: Difficulty/dual_variant_calc/royalty_statement_provisional_vs_final
    """
    ctx = setup_provisional_statement(
        api, sales=_DIVERGENCE_SALES, exclusivity="EXCLUSIVE",
        retailer_cut_pct=0.40, royalty_share_pct=0.40,
    )
    st = ctx["statement"]
    assert st["status"] == "PROVISIONAL"
    assert st["narrator_royalty_cents"] == 67500
    assert st["author_royalty_cents"] == 82500
    assert_royalty_partition(st)


def test_finalize_recomputes_final_variant_deducting_returns(api):
    """PRD §3.8: "Finalizing recomputes every monetary field under the **final
    variant**, in which each line quantity is `units_sold` minus `units_returned`
    — returns are now deducted — and sets `variant` to `FINAL`."

    Design: Difficulty/dual_variant_calc/royalty_statement_provisional_vs_final
    """
    ctx = setup_provisional_statement(
        api, sales=_DIVERGENCE_SALES, exclusivity="EXCLUSIVE",
        retailer_cut_pct=0.40, royalty_share_pct=0.40,
    )
    st = finalize_statement(api, ctx["statement"]["id"])
    assert st["status"] == "FINALIZED"
    assert st["variant"] == "FINAL"
    assert st["narrator_royalty_cents"] == 63450
    assert st["author_royalty_cents"] == 77550
    assert_royalty_partition(st)


def test_royalty_net_rounds_each_line_before_summing(api):
    """PRD §2.7: "Rounding is applied per line before summation, never after:
    when a royalty statement aggregates multiple sales lines, each line's net is
    rounded to whole cents first and only then are the rounded line nets summed
    (round-then-sum, not sum-then-round)."

    Design: Difficulty/combinatorial_formula/royalty_rounding_round_then_sum
    """
    sales = [
        {"units_sold": 4, "units_returned": 0, "unit_price_cents": 2683, "occurred_at": "2026-03-10T00:00:00Z"},
        {"units_sold": 2, "units_returned": 0, "unit_price_cents": 1001, "occurred_at": "2026-03-11T00:00:00Z"},
    ]
    ctx = setup_provisional_statement(
        api, sales=sales, exclusivity="NON_EXCLUSIVE",
        retailer_cut_pct=0.30, royalty_share_pct=0.40,
    )
    assert ctx["statement"]["statement_net_cents"] == 8913


def test_royalty_round_then_sum_partition(api):
    """PRD §3.7: "The narrator's cut, `narrator_royalty_cents`, is
    `statement_net_cents` multiplied by `narrator_share_pct_applied`, rounded half
    up to whole cents. The author's cut, `author_royalty_cents`, is
    `statement_net_cents` minus `narrator_royalty_cents`, so the two cuts always
    partition the net exactly."

    Design: Difficulty/combinatorial_formula/royalty_rounding_round_then_sum
    """
    sales = [
        {"units_sold": 4, "units_returned": 0, "unit_price_cents": 2683, "occurred_at": "2026-03-10T00:00:00Z"},
        {"units_sold": 2, "units_returned": 0, "unit_price_cents": 1001, "occurred_at": "2026-03-11T00:00:00Z"},
    ]
    ctx = setup_provisional_statement(
        api, sales=sales, exclusivity="NON_EXCLUSIVE",
        retailer_cut_pct=0.30, royalty_share_pct=0.40,
    )
    st = ctx["statement"]
    assert st["narrator_royalty_cents"] == 3565
    assert st["author_royalty_cents"] == 5348
    assert_royalty_partition(st)


def test_effective_share_capped_at_share_cap(api):
    """PRD §3.7: "The effective share is the base plus bonus, multiplied by the
    tier multiplier, but capped at `SHARE_CAP` of 0.50 — that is, the smaller of
    0.50 and the multiplied value."
    PRD §3.7: "the multiplier is ... 1.20 when cumulative units are 5,000 or more."

    Design: Difficulty/combinatorial_formula/effective_share_tiered_min_cap
    """
    sales = [
        {"units_sold": 6000, "units_returned": 0, "unit_price_cents": 1000, "occurred_at": "2026-03-12T00:00:00Z"},
    ]
    ctx = setup_provisional_statement(
        api, sales=sales, exclusivity="EXCLUSIVE",
        retailer_cut_pct=0.40, royalty_share_pct=0.40,
    )
    assert ctx["statement"]["narrator_share_pct_applied"] == 0.50


def test_tiered_share_royalty_amounts(api):
    """PRD §3.7: "The narrator's cut, `narrator_royalty_cents`, is
    `statement_net_cents` multiplied by `narrator_share_pct_applied`, rounded half
    up to whole cents. The author's cut, `author_royalty_cents`, is
    `statement_net_cents` minus `narrator_royalty_cents`, so the two cuts always
    partition the net exactly."

    Design: Difficulty/combinatorial_formula/effective_share_tiered_min_cap
    """
    sales = [
        {"units_sold": 6000, "units_returned": 0, "unit_price_cents": 1000, "occurred_at": "2026-03-12T00:00:00Z"},
    ]
    ctx = setup_provisional_statement(
        api, sales=sales, exclusivity="EXCLUSIVE",
        retailer_cut_pct=0.40, royalty_share_pct=0.40,
    )
    st = ctx["statement"]
    assert st["statement_net_cents"] == 3600000
    assert st["narrator_royalty_cents"] == 1800000
    assert st["author_royalty_cents"] == 1800000
    assert_royalty_partition(st)


def test_empty_sales_statement_zero_gross_net(api):
    """PRD §3.7: "The statement includes the sales events whose listing belongs to
    the title and whose `occurred_at` falls within the closed period window — at
    or after `period_start` and at or before `period_end`."

    Design: Difficulty/boundary_precision_check/royalty_statement_empty_sales_set
    """
    ctx = setup_provisional_statement(api, sales=[])
    st = ctx["statement"]
    assert st["gross_sales_cents"] == 0
    assert st["statement_net_cents"] == 0


def test_empty_sales_statement_zero_royalties(api):
    """PRD §3.7: "For each event, a line quantity is determined by the variant ...
    and these line grosses are summed into `gross_sales_cents`."
    PRD §3.7: "The author's cut, `author_royalty_cents`, is `statement_net_cents`
    minus `narrator_royalty_cents`, so the two cuts always partition the net exactly."

    Design: Difficulty/boundary_precision_check/royalty_statement_empty_sales_set
    """
    ctx = setup_provisional_statement(api, sales=[])
    st = ctx["statement"]
    assert st["narrator_royalty_cents"] == 0
    assert st["author_royalty_cents"] == 0
    assert st["status"] == "PROVISIONAL"


def test_sales_event_default_units_returned(api):
    """PRD §3.7: "the `units_returned` (which defaults to 0 and may not be negative
    nor exceed `units_sold`)".

    Design: Corner/entities/sales_event_defaults_zero_returns
    """
    ctx = setup_published_with_listing(api)
    payload = {
        "listing_id": ctx["listing"]["id"],
        "units_sold": 5,
        "unit_price_cents": 1000,
        "occurred_at": "2026-03-15T00:00:00Z",
    }
    data = validate_success(api.create_sales_event(payload, admin_headers()), 201)
    assert data["units_returned"] == 0


def test_finalize_finalized_statement_rejected(api):
    """PRD §3.8: "Finalization requires the statement to be in `PROVISIONAL`, or
    it is refused with `ERR_STATEMENT_NOT_PROVISIONAL`."

    Design: Corner/state_machines/finalize_non_provisional_statement_returns_invalid_state
    """
    ctx = setup_provisional_statement(api, sales=[])
    finalize_statement(api, ctx["statement"]["id"])  # PROVISIONAL -> FINALIZED
    resp = api.finalize_statement(ctx["statement"]["id"], admin_headers())
    validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_PROVISIONAL.value)
