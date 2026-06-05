"""Difficulty rule 1 — dual-variant calculations (PRD §3.5, §3.8).

Lookback-on vs lookback-off pricing on Purchase, and qualifying vs disqualifying
ordinary income on Disposition.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    create_disposition_payload,
    setup_settled_purchase,
    make_participant_headers,
)


def test_lookback_on_price_uses_min_fmv(api, admin_headers):
    """PRD §3.5: "The applicable fair market value is the lower of the offering's
    grant_date_fmv_cents and the batch's purchase_date_fmv_cents when the plan's
    lookback_enabled is true; when lookback is disabled, only the
    purchase_date_fmv_cents is used and the grant-date figure is ignored for
    pricing. The price_per_share_cents is then the applicable fair market value
    multiplied by the quantity (100 minus the plan's discount_pct), divided by 100,
    and rounded half up to the nearest whole cent."

    Design: Difficulty/dual_variant_calc/lookback_price_min_vs_purchase_only_on_purchase
    """
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={"grant_date_fmv_cents": 1000},
        batch_overrides={"purchase_date_fmv_cents": 1200},
    )
    purchase = validate_success(api.get_purchase(ctx["purchase"]["id"], admin_headers))
    assert purchase["price_per_share_cents"] == 850, purchase


def test_lookback_off_price_uses_purchase_fmv(api, admin_headers):
    """PRD §3.5: "The applicable fair market value is the lower of the offering's
    grant_date_fmv_cents and the batch's purchase_date_fmv_cents when the plan's
    lookback_enabled is true; when lookback is disabled, only the
    purchase_date_fmv_cents is used and the grant-date figure is ignored for
    pricing. The price_per_share_cents is then the applicable fair market value
    multiplied by the quantity (100 minus the plan's discount_pct), divided by 100,
    and rounded half up to the nearest whole cent."

    Design: Difficulty/dual_variant_calc/lookback_price_min_vs_purchase_only_on_purchase
    """
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": False},
        offering_overrides={"grant_date_fmv_cents": 1000},
        batch_overrides={"purchase_date_fmv_cents": 1200},
    )
    purchase = validate_success(api.get_purchase(ctx["purchase"]["id"], admin_headers))
    assert purchase["price_per_share_cents"] == 1020, purchase


def _settled_2022_lot(rate_pct=15):
    """A purchased ShareLot of 100 shares at price 850c (grant_fmv 1000, purchase_fmv
    1200, discount 15), grant 2022-01-01, purchase 2022-06-30. gross 1000000 at 15%
    => 150000c contributions => 176 shares; we sell 100 of them."""
    return setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2022-01-01T00:00:00.000Z",
            "grant_date_fmv_cents": 1000,
            "duration_months": 12,
        },
        batch_overrides={
            "purchase_date": "2022-06-30T00:00:00.000Z",
            "purchase_date_fmv_cents": 1200,
        },
        rate_pct=rate_pct,
    )


def test_qualifying_ordinary_income_lesser_of(api):
    """PRD §3.8: "For a qualifying disposition, the ordinary_income_cents is the
    lesser of two quantities. The first is the actual economic gain: the sale
    proceeds (shares sold multiplied by sale_price_per_share_cents) minus the
    purchase cost (shares sold multiplied by the purchase's price_per_share_cents),
    with the result never allowed below 0. The second is the grant-date statutory
    discount: the shares sold multiplied by the amount, never allowed below 0, by
    which the offering's grant_date_fmv_cents exceeds the purchase's
    price_per_share_cents."

    Sale on 2024-06-30 is on/after grant+2y and purchase+1y => QUALIFYING. Sale 1500c,
    paid 850c: actual_gain=100*(1500-850)=65000; statutory_discount=100*(1000-850)=15000;
    lesser = 15000.

    Design: Difficulty/dual_variant_calc/qualifying_vs_disqualifying_ordinary_income_on_disposition
    """
    ctx = _settled_2022_lot()
    ph = make_participant_headers(ctx["participant"]["id"])
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                ctx["share_lot"]["id"], ctx["participant"]["id"],
                sale_date="2024-06-30T00:00:00.000Z", shares_sold=100,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "QUALIFYING", disp
    assert disp["ordinary_income_cents"] == 15000, disp


def test_disqualifying_ordinary_income_purchase_spread(api):
    """PRD §3.8: "For a disqualifying disposition, the ordinary_income_cents is fixed
    at the spread at purchase regardless of the sale price: the shares sold
    multiplied by the amount, never allowed below 0, by which the batch's
    purchase_date_fmv_cents exceeds the purchase's price_per_share_cents."

    Sale on 2022-12-31 is before purchase+1y => DISQUALIFYING. Spread =
    100*(1200-850)=35000, independent of the 1500c sale price.

    Design: Difficulty/dual_variant_calc/qualifying_vs_disqualifying_ordinary_income_on_disposition
    """
    ctx = _settled_2022_lot()
    ph = make_participant_headers(ctx["participant"]["id"])
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                ctx["share_lot"]["id"], ctx["participant"]["id"],
                sale_date="2022-12-31T00:00:00.000Z", shares_sold=100,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "DISQUALIFYING", disp
    assert disp["ordinary_income_cents"] == 35000, disp
