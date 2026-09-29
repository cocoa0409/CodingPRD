"""Attribution credit and incrementality lift on the same inputs under both models.

The two attribution tests share one shopper, one product and one pair of engagements — an
impression followed five minutes later by a click — and one 50,000-cent sale credited to
each of them in turn. Only the campaign's `attribution_model` differs, so the whole gap
between a winner-takes-all credit and a match-weighted split is attributable to that one
field.

The two measurement tests likewise share one cohort pair of 10,000 and 10,000 with the
same four outcome counters, and differ only in `design_method`. A geo holdout reads the
conversion-rate ratio; a user holdout rescales the control sales first. The PRD warns that
"the two variants can disagree sharply on the same inputs", and here they do: 1,000,000
cents of incremental sales against 1,100,000.
"""

from test_helpers import (
    AUCTION_SERVICE,
    MEASUREMENT_ANALYST,
    api_client,
    assert_decimal_places,
    build_awarded_auction,
    build_delivering_world,
    build_engagement_event,
    build_running_study,
    factories,
    reread_campaign,
    set_clock,
    validate_success,
)

FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-08-11T00:00:00Z"

STUDY_START = "2026-08-01T00:00:00Z"
STUDY_END = "2026-08-08T00:00:00Z"

# One shopper hash shared by both engagements: the candidate set for a sale is keyed on
# that hash together with the product, so both engagements compete for the same credit.
SHOPPER = "sh_attrib_1"
IMPRESSION_AT = "2026-08-01T12:05:00Z"
CLICK_AT = "2026-08-01T12:10:00Z"
SALE_AT = "2026-08-02T00:00:00Z"
SALE_CENTS = 50000

CLICK_ORDER_REF = "RO-1001"
VIEW_ORDER_REF = "RO-1002"


def _delivering_world(**campaign_overrides):
    """A delivering campaign whose flight and line item both span 2026-08-01 to 08-11."""
    campaign = {
        "flight_start_at": FLIGHT_START,
        "flight_end_at": FLIGHT_END,
        "allocated_budget_cents": 2000000,
        "daily_cap_cents": 200000,
        "attribution_window_days": 14,
    }
    campaign.update(campaign_overrides)
    return build_delivering_world(
        campaign=campaign,
        line_item={
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
        },
    )


def _two_engagement_world(attribution_model):
    """Settle one auction carrying an impression and a later click from one shopper."""
    world = _delivering_world(attribution_model=attribution_model)
    build_awarded_auction(world)
    build_engagement_event(
        world,
        event_type="IMPRESSION",
        occurred_at=IMPRESSION_AT,
        shopper_hash=SHOPPER,
    )
    impression = world["engagement"]
    build_engagement_event(
        world,
        event_type="CLICK",
        occurred_at=CLICK_AT,
        shopper_hash=SHOPPER,
    )
    click = world["engagement"]
    validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )
    return world, impression, click


def _record_sale(world, engagement, retail_order_ref, match_type):
    """Credit one 50,000-cent sale to the named engagement."""
    return validate_success(
        api_client.create_attributed_sale(
            factories.attributed_sale_payload(
                engagement["id"],
                world["product"]["id"],
                sale_cents=SALE_CENTS,
                occurred_at=SALE_AT,
                retail_order_ref=retail_order_ref,
                match_type=match_type,
            ),
            MEASUREMENT_ANALYST,
        ),
        expected_status=201,
    )


def test_last_touch_credits_the_click_in_full_and_the_impression_not_at_all():
    """The later click takes all 50,000 cents; the impression's row is credited 0.

    PRD 3.7: "Under `LAST_TOUCH` the credit goes entirely to one engagement: the candidate
    with the greatest `occurred_at`, with ties broken by `event_type` in the fixed
    precedence `CLICK` first, then `OFFSITE_VIEW`, then `IMPRESSION`, and any remaining tie
    broken by ascending `created_at`."

    PRD 3.7: "The credited engagement's row receives `attribution_weight` 1.0 and every
    other candidate's row receives 0.0."

    PRD 3.7: "In both variants `attributed_credit_cents` is `sale_cents` multiplied by the
    row's `attribution_weight`, rounded half-up to whole cents."

    PRD 3.7: "`match_type` must be supplied but the persisted value is always derived: it
    is `CLICK_THROUGH` when the credited engagement's `event_type` is `CLICK` and
    `VIEW_THROUGH` for an `IMPRESSION` or `OFFSITE_VIEW`."

    Design: Corner/calculations/last_touch_attribution_gives_whole_sale_to_the_click_and_zero_to_the_impression
    """
    world, impression, click = _two_engagement_world("LAST_TOUCH")
    click_sale = _record_sale(world, click, CLICK_ORDER_REF, "CLICK_THROUGH")

    view_sale = _record_sale(world, impression, VIEW_ORDER_REF, "VIEW_THROUGH")

    assert view_sale["within_window"] is True
    assert view_sale["attribution_model_applied"] == "LAST_TOUCH"
    # The impression is a candidate but not the last touch, so its row carries no credit.
    assert view_sale["attribution_weight"] == 0.0
    assert view_sale["attributed_credit_cents"] == 0
    assert view_sale["match_type"] == "VIEW_THROUGH"
    assert view_sale["restated"] is False

    credited = validate_success(
        api_client.get_attributed_sale(click_sale["id"], MEASUREMENT_ANALYST)
    )
    assert credited["within_window"] is True
    assert credited["attribution_weight"] == 1.0
    assert credited["attributed_credit_cents"] == 50000
    assert credited["match_type"] == "CLICK_THROUGH"

    # 50000 + 0: the campaign total is the sum of the two already-rounded parts.
    assert reread_campaign(world)["attributed_revenue_cents"] == 50000


def test_fractional_splits_the_sale_by_match_weight_and_rounds_each_row_first():
    """Weights 0.8333 and 0.1667 yield 41,665 and 8,335 cents, summing to 50,000.

    PRD 3.7: "Under `FRACTIONAL` the credit is split by match weight: `CLICK` carries a
    weight of 1.0, `OFFSITE_VIEW` 0.4 and `IMPRESSION` 0.2, and each candidate's
    `attribution_weight` is its own match weight divided by the sum of match weights across
    all in-window candidates, rounded half-up to four decimal places."

    PRD 3.7: "In both variants `attributed_credit_cents` is `sale_cents` multiplied by the
    row's `attribution_weight`, rounded half-up to whole cents."

    PRD 3.7: "The per-row rounding happens first and the summation second, so the campaign
    total is the sum of rounded parts and not the rounding of a summed product; rows with
    `restated` true are excluded from the total but retain their own stored credit."

    Design: Corner/calculations/fractional_attribution_splits_by_match_weight_and_rounds_per_row
    """
    world, impression, click = _two_engagement_world("FRACTIONAL")
    click_sale = _record_sale(world, click, CLICK_ORDER_REF, "CLICK_THROUGH")

    view_sale = _record_sale(world, impression, VIEW_ORDER_REF, "VIEW_THROUGH")

    assert view_sale["attribution_model_applied"] == "FRACTIONAL"
    # 0.2 over the 1.2 total weight of the two in-window candidates.
    assert view_sale["attribution_weight"] == 0.1667
    assert_decimal_places(view_sale["attribution_weight"], 4, "view attribution_weight")
    assert view_sale["attributed_credit_cents"] == 8335
    assert view_sale["match_type"] == "VIEW_THROUGH"

    credited = validate_success(
        api_client.get_attributed_sale(click_sale["id"], MEASUREMENT_ANALYST)
    )
    # 1.0 over the same 1.2 total.
    assert credited["attribution_weight"] == 0.8333
    assert_decimal_places(credited["attribution_weight"], 4, "click attribution_weight")
    assert credited["attributed_credit_cents"] == 41665
    assert credited["match_type"] == "CLICK_THROUGH"

    # 41665 + 8335 — the rounded parts happen to close exactly on the whole sale here.
    assert reread_campaign(world)["attributed_revenue_cents"] == 50000


def _measure(world, design_method):
    """Run one study of the named design over identical cohorts and outcome counters."""
    build_running_study(
        world,
        exposed_group_size=10000,
        control_group_size=10000,
        design_method=design_method,
        holdout_pct=0.2,
        window_start_at=STUDY_START,
        window_end_at=STUDY_END,
    )
    set_clock(world, STUDY_END)
    return validate_success(
        api_client.measure_incrementality_study(
            world["study"]["id"],
            factories.study_measure_payload(1000, 500, 2000000, 900000),
            MEASUREMENT_ANALYST,
        )
    )


def test_geo_holdout_lift_comes_from_the_conversion_rate_ratio():
    """A 0.10 exposed rate against a 0.05 control rate lifts 1.0000 and yields 1,000,000.

    PRD 3.7: "Under `GEO_HOLDOUT`, `lift_pct` is 1.0000 when the control rate is 0, and
    otherwise the exposed rate divided by the control rate less 1.0, rounded half-up to
    four decimal places; `incremental_sales_cents` is `exposed_sales_cents` multiplied by
    `lift_pct` divided by the quantity one plus `lift_pct`, rounded half-up to whole cents,
    when `lift_pct` is greater than 0, and exactly 0 otherwise."

    PRD 3.7: "`significance_score` is the absolute difference between the exposed rate and
    the control rate, multiplied by the square root of the smaller of the two group sizes,
    rounded half-up to four decimal places."

    PRD 3.7: "`significance_flag` is true when `significance_score` is at or above 1.96 and
    false below it, so a score of exactly 1.9600 is significant."

    Design: Corner/calculations/geo_holdout_measurement_derives_lift_from_the_conversion_rate_ratio
    """
    world = _delivering_world()

    measured = _measure(world, "GEO_HOLDOUT")

    assert measured["study_status"] == "MEASURING"
    # 0.10 / 0.05 - 1.0 exactly.
    assert measured["lift_pct"] == 1.0000
    assert_decimal_places(measured["lift_pct"], 4, "lift_pct")
    # 2,000,000 * 1.0 / 2.0 — half the exposed sales, not all of them.
    assert measured["incremental_sales_cents"] == 1000000
    # |0.10 - 0.05| * sqrt(10000) = 0.05 * 100.
    assert measured["significance_score"] == 5.0000
    assert measured["significance_flag"] is True

    # Measuring writes nothing onto the campaign; only publication does.
    assert reread_campaign(world)["incremental_revenue_cents"] == 0


def test_user_holdout_diverges_because_it_rescales_the_control_sales():
    """The same counters give 1,100,000 incremental cents and a 1.2222 lift.

    PRD 3.7: "Under `USER_HOLDOUT` the control side is first rescaled to the exposed
    group's size: the scaled control sales are `control_sales_cents` multiplied by
    `exposed_group_size` divided by `control_group_size`; `incremental_sales_cents` is
    `exposed_sales_cents` less the scaled control sales, floored at 0, rounded half-up to
    whole cents; and `lift_pct` is 1.0000 when the scaled control sales are 0, and
    otherwise `exposed_sales_cents` less the scaled control sales, divided by the scaled
    control sales, rounded half-up to four decimal places."

    PRD 3.7: "`significance_score` is the absolute difference between the exposed rate and
    the control rate, multiplied by the square root of the smaller of the two group sizes,
    rounded half-up to four decimal places."

    Design: Corner/calculations/user_holdout_measurement_diverges_on_scaled_control_sales
    """
    world = _delivering_world()

    measured = _measure(world, "USER_HOLDOUT")

    assert measured["study_status"] == "MEASURING"
    # Equal cohorts leave the scaled control sales at 900,000; 2,000,000 - 900,000.
    assert measured["incremental_sales_cents"] == 1100000
    # 1,100,000 / 900,000 = 1.22222..., which rounds half-up to 1.2222.
    assert measured["lift_pct"] == 1.2222
    assert_decimal_places(measured["lift_pct"], 4, "lift_pct")
    # Significance reads the rates, not the sales, so it matches the geo variant exactly.
    assert measured["significance_score"] == 5.0000
    assert measured["significance_flag"] is True
