"""Two valuation bases and two loss-rate bases, read side by side.

Each scenario builds one set of preconditions and then reads the same quantity
under both variants the contract offers, so the divergence between them is the
observable under test.
"""

from test_helpers import api_client, fixtures, get_success_data
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
    TEST_USERS,
    THIRD_ANALYST_USER_ID,
    make_analyst_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}


def _two_kegs_priced_under_both_bases():
    """Two identical kegs at the brewer, each with 24 lifetime fills, one
    assessed on each valuation basis for the same physical cause."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={
            "per_fill_rate_cents": 2200,
            "replenishment_threshold_pct": 20,
        },
        keg_specs=[
            {"asset_tag": "K-0001", "fill_count": 24, "fills_at_last_pressure_test": 0},
            {"asset_tag": "K-0002", "fill_count": 24, "fills_at_last_pressure_test": 0},
        ],
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    order = fixtures.create_order(ctx["agreement"]["id"], 2)
    fixtures.allocate_order(order["id"], ctx["agreement"]["id"])

    first_keg_id = ctx["kegs"][0]["id"]
    second_keg_id = ctx["kegs"][1]["id"]
    ctx["first_keg"] = fixtures.read_keg(first_keg_id)
    ctx["second_keg"] = fixtures.read_keg(second_keg_id)
    ctx["replacement_cost_assessment"] = fixtures.open_loss_assessment(
        first_keg_id,
        "DAMAGED_BEYOND_REPAIR",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    ctx["depreciated_book_assessment"] = fixtures.open_loss_assessment(
        second_keg_id,
        "DAMAGED_BEYOND_REPAIR",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="DEPRECIATED_BOOK",
    )
    return ctx


def test_replacement_cost_gross_value_ignores_the_fill_count():
    """A 24-fill keg assessed on the market basis is valued at the pool's full
    replacement cost, with the in-hand shell credited back at scrap.

    PRD: "Under **`REPLACEMENT_COST`**, `gross_value_cents` is simply the
    pool's `replacement_cost_cents`, and `fill_count` is ignored entirely."

    Design: Difficulty/dual_variant_calc/keg_loss_value_replacement_cost_versus_depreciated_book_divergence
    """
    ctx = _two_kegs_priced_under_both_bases()
    keg = ctx["first_keg"]
    assessment = ctx["replacement_cost_assessment"]

    assert keg["fill_count"] == 24
    assert keg["stainless_scrap_value_cents"] == 3900

    assert assessment["assessment_basis"] == "REPLACEMENT_COST"
    assert assessment["gross_value_cents"] == 23500
    assert assessment["scrap_credit_cents"] == 3900
    assert assessment["assessed_value_cents"] == 19600
    assert assessment["brewer_liability_pct_bp"] == 10000
    assert assessment["net_chargeback_cents"] == 19600


def test_depreciated_book_writes_the_shell_down_by_45_bp_per_fill():
    """The same cause on an identical keg, read on the book basis, writes the
    replacement cost down 1080 basis points for its 24 fills and stays well
    above the 30 percent floor.

    PRD: "A candidate book value is the `replacement_cost_cents` multiplied by
    10000 less that depreciation, divided by 10000, rounded half up; a floor
    value is 30 percent of `replacement_cost_cents`, rounded half up; and
    `gross_value_cents` is the greater of the two."

    Design: Difficulty/dual_variant_calc/keg_loss_value_replacement_cost_versus_depreciated_book_divergence
    """
    ctx = _two_kegs_priced_under_both_bases()
    assessment = ctx["depreciated_book_assessment"]

    assert ctx["second_keg"]["fill_count"] == 24
    assert assessment["assessment_basis"] == "DEPRECIATED_BOOK"
    assert assessment["gross_value_cents"] == 20962
    assert assessment["scrap_credit_cents"] == 3900
    assert assessment["assessed_value_cents"] == 17062
    assert assessment["brewer_liability_pct_bp"] == 10000
    assert assessment["net_chargeback_cents"] == 17062


def test_the_book_basis_is_strictly_cheaper_than_the_market_basis():
    """Both assessments name the same brewer and the same stainless reading, and
    neither has been resolved, so the only difference between the two rows is
    the 2538-cent gap the basis itself creates.

    PRD: "Once `fill_count` is at least 1 and the cause permits it,
    `DEPRECIATED_BOOK` always yields a strictly lower gross value than
    `REPLACEMENT_COST`, so reading the wrong basis is observable in the money."

    Design: Difficulty/dual_variant_calc/keg_loss_value_replacement_cost_versus_depreciated_book_divergence
    """
    ctx = _two_kegs_priced_under_both_bases()
    market = ctx["replacement_cost_assessment"]
    book = ctx["depreciated_book_assessment"]

    assert book["gross_value_cents"] < market["gross_value_cents"]
    assert market["net_chargeback_cents"] - book["net_chargeback_cents"] == 2538

    assert market["commodity_index_id"] == ctx["index"]["id"]
    assert book["commodity_index_id"] == ctx["index"]["id"]
    assert market["brewer_id"] == ctx["brewer"]["id"]
    assert book["brewer_id"] == ctx["brewer"]["id"]
    assert market["chargeback_status"] == "NONE"
    assert book["chargeback_status"] == "NONE"

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 0


def _brewer_with_two_upheld_losses_across_two_quarters():
    """Five fills and two upheld losses spread over six months, so the trailing
    window keeps one loss over three fills while the lifetime figures keep two
    losses over five fills."""
    # The clock has to stand at or past every instant this block supplies --
    # PRD refuses a `dispatched_at` or `scanned_at` ahead of the logical clock
    # with `ERR_SCAN_TIMESTAMP_FUTURE` -- so park it on the last of them.
    fixtures.pin_clock("2026-02-01T02:00:00Z")
    index = fixtures.post_index("2026-01-01", 480)
    brewer = fixtures.create_brewer(credit_limit_cents=400000)
    pool = fixtures.create_pool(
        replacement_cost_cents=18000,
        restrict_threshold_pct=25,
        freeze_threshold_pct=10,
        restricted_max_kegs_per_order=2,
    )
    fixtures.import_kegs(pool["id"], [f"K-{n:04d}" for n in range(1, 9)])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"],
        pool["id"],
        10,
        effective_date="2026-02-01",
        per_fill_rate_cents=2200,
        replenishment_threshold_pct=20,
    )
    order = fixtures.order_allocated_and_dispatched(
        agreement["id"], 5, "2026-02-01T01:00:00Z"
    )
    issued = order["allocated_keg_ids"]

    for keg_id in issued[:2]:
        fixtures.fill_scan(keg_id, brewer["id"], "2026-02-01T02:00:00Z", "RDG")
    first = fixtures.open_loss_assessment(
        issued[0],
        "LOST_IN_TRADE",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    first = fixtures.resolve_assessment(
        first["id"], "UPHELD", analyst_id=SECOND_ANALYST_USER_ID
    )
    _restore_active_standing(brewer["id"], "loss review closed, float restored")

    fixtures.pin_clock("2026-06-15T00:00:00Z")
    for keg_id in issued[2:5]:
        fixtures.fill_scan(keg_id, brewer["id"], "2026-06-15T00:00:00Z", "RDG")
    second = fixtures.open_loss_assessment(
        issued[2],
        "LOST_IN_TRADE",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    second = fixtures.resolve_assessment(
        second["id"], "UPHELD", analyst_id=SECOND_ANALYST_USER_ID
    )
    _restore_active_standing(brewer["id"], "Review closed")

    fixtures.pin_clock("2026-08-01T00:00:00Z")
    return {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "issued_keg_ids": issued,
        "first_assessment": first,
        "second_assessment": second,
    }


def _restore_active_standing(brewer_id, status_reason):
    return get_success_data(
        api_client.set_brewer_status(
            brewer_id,
            {"status": "ACTIVE", "status_reason": status_reason},
            OPERATOR,
        )
    )


def _read_loss_rate(brewer_id, basis):
    return get_success_data(
        api_client.get_brewer_loss_rate(
            brewer_id,
            make_analyst_headers(THIRD_ANALYST_USER_ID),
            params={"basis": basis},
        )
    )


def test_trailing_loss_rate_counts_only_the_ninety_day_window():
    """Read on the trailing basis, one upheld loss over three in-window fills
    reports 3333 basis points and names the inclusive window ends.

    PRD: "The trailing variant counts, inside a window running from 90 days
    before the logical clock through the clock itself with both ends inclusive,
    the brewer's `UPHELD` assessments by `created_at` as the numerator and the
    brewer's fill scans by `scanned_at` as the denominator."

    Design: Difficulty/dual_variant_calc/brewer_loss_rate_trailing_window_versus_lifetime_divergence
    """
    ctx = _brewer_with_two_upheld_losses_across_two_quarters()
    trailing = _read_loss_rate(ctx["brewer"]["id"], "TRAILING_90D")

    assert trailing["basis"] == "TRAILING_90D"
    assert trailing["upheld_loss_count"] == 1
    assert trailing["fill_count"] == 3
    assert trailing["loss_rate_bp"] == 3333
    assert trailing["basis_insufficient"] is False
    assert trailing["window_start"] == "2026-05-03T00:00:00Z"
    assert trailing["window_end"] == "2026-08-01T00:00:00Z"


def test_lifetime_loss_rate_uses_the_unwindowed_counters():
    """Read on the lifetime basis, the same brewer reports both losses over all
    five fills, which is 4000 basis points.

    PRD: "The lifetime variant uses the unwindowed `upheld_loss_count` over
    `lifetime_fill_count`."

    Design: Difficulty/dual_variant_calc/brewer_loss_rate_trailing_window_versus_lifetime_divergence
    """
    ctx = _brewer_with_two_upheld_losses_across_two_quarters()
    lifetime = _read_loss_rate(ctx["brewer"]["id"], "LIFETIME")

    assert lifetime["basis"] == "LIFETIME"
    assert lifetime["upheld_loss_count"] == 2
    assert lifetime["fill_count"] == 5
    assert lifetime["loss_rate_bp"] == 4000

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["lifetime_fill_count"] == 5
    assert brewer["upheld_loss_count"] == 2


def test_the_two_loss_rate_bases_diverge_by_667_basis_points():
    """One upheld loss over three fills rounds down to 3333 while two over five
    is an exact 4000, so the windowed and unwindowed reads differ by 667 basis
    points over identical stored history.

    PRD: "In both cases, a zero denominator reports a rate of 0 and marks the
    basis insufficient; otherwise the rate is 10000 multiplied by the numerator,
    divided by the denominator, rounded half up — one upheld loss over three
    fills is 3333 basis points, not 3334."

    Design: Difficulty/dual_variant_calc/brewer_loss_rate_trailing_window_versus_lifetime_divergence
    """
    ctx = _brewer_with_two_upheld_losses_across_two_quarters()
    trailing = _read_loss_rate(ctx["brewer"]["id"], "TRAILING_90D")
    lifetime = _read_loss_rate(ctx["brewer"]["id"], "LIFETIME")

    assert trailing["loss_rate_bp"] == 3333
    assert trailing["loss_rate_bp"] != 3334
    assert lifetime["loss_rate_bp"] - trailing["loss_rate_bp"] == 667

    assert ctx["first_assessment"]["net_chargeback_cents"] == 10800
    assert ctx["second_assessment"]["net_chargeback_cents"] == 10800

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 21600
    assert brewer["status"] == "ACTIVE"
