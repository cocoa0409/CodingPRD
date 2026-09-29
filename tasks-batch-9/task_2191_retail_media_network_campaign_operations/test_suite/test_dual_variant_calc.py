"""One formula with two variants, fed byte-identical inputs.

Lift is computed one way under `GEO_HOLDOUT` and another way under `USER_HOLDOUT`. The
two studies below receive the same four cohort counters and the same two group sizes, so
every difference in their results is attributable to `design_method` alone — which is
exactly why the method is fixed when the study is designed and never amended afterwards.
"""

from test_helpers import (
    MEASUREMENT_ANALYST,
    SIGNIFICANCE_MIN,
    api_client,
    build_active_budget_plan,
    build_active_managed_advertiser,
    build_catalog_product,
    build_draft_campaign,
    build_placement_slot,
    build_scheduled_campaign,
    factories,
    reread_campaign,
    round_half_up,
    round_half_up_int,
    set_clock,
    validate_success,
)

# The two cohorts are deliberately unequal in size, which is what gives the two variants
# something to disagree about: the user-holdout variant rescales the control side to the
# exposed group's size, and the geo-holdout variant never does.
EXPOSED_GROUP_SIZE = 50000
CONTROL_GROUP_SIZE = 20000
EXPOSED_CONVERSIONS = 2500
CONTROL_CONVERSIONS = 600
EXPOSED_SALES_CENTS = 40000000
CONTROL_SALES_CENTS = 11000000

STUDY_WINDOW = ("2026-08-01T00:00:00Z", "2026-08-11T00:00:00Z")
GEO = "geo_campaign"
USER = "user_campaign"


def _two_measured_ready_campaigns():
    """Two scheduled campaigns on one plan, each carrying one running study.

    A study may only be started while its campaign is scheduled or delivering, so each
    campaign is carried through review approval to `SCHEDULED`. The studies sit on
    different campaigns, so the washout rule — which only ever compares studies of the
    same campaign — has nothing to say about their identical windows. No auction is run,
    so neither campaign has any delivered spend and nothing feeds back into the plan.

    The clock is left at the study windows' opening instant while the studies start, and
    then moved to their closing instant, which is the earliest moment either may be
    measured.
    """
    world = build_active_managed_advertiser()
    build_active_budget_plan(
        world,
        committed_total_cents=40000000,
        trade_fund_share_cents=0,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-10-01T00:00:00Z",
    )
    build_placement_slot(
        world, max_concurrent_line_items=3, floor_cpc_cents=1250
    )
    build_catalog_product(world, category_code="GROCERY", margin_pct=0.4)

    for key, design_method in ((GEO, "GEO_HOLDOUT"), (USER, "USER_HOLDOUT")):
        build_draft_campaign(
            world,
            key=key,
            flight_start_at=STUDY_WINDOW[0],
            flight_end_at=STUDY_WINDOW[1],
            allocated_budget_cents=5000000,
            daily_cap_cents=400000,
        )
        build_scheduled_campaign(
            world,
            key=key,
            bid_cents=3000,
            daily_budget_cents=200000,
            flight_start_at=STUDY_WINDOW[0],
            flight_end_at=STUDY_WINDOW[1],
            category_code="GROCERY",
            keyword_match_terms=["coffee"],
        )
        campaign = reread_campaign(world, key)
        assert campaign["delivery_status"] == "SCHEDULED"

        study = validate_success(
            api_client.create_incrementality_study(
                factories.incrementality_study_payload(
                    campaign["id"],
                    campaign["version"],
                    design_method=design_method,
                    holdout_pct=0.2,
                    window_start_at=STUDY_WINDOW[0],
                    window_end_at=STUDY_WINDOW[1],
                ),
                MEASUREMENT_ANALYST,
            ),
            201,
        )
        world[design_method] = validate_success(
            api_client.start_incrementality_study(
                study["id"],
                factories.study_start_payload(
                    EXPOSED_GROUP_SIZE, CONTROL_GROUP_SIZE
                ),
                MEASUREMENT_ANALYST,
            )
        )
        assert world[design_method]["study_status"] == "RUNNING"

    set_clock(world, STUDY_WINDOW[1])
    return world


def _measure(world, design_method):
    """Feed the shared cohort counters to one of the two studies."""
    return validate_success(
        api_client.measure_incrementality_study(
            world[design_method]["id"],
            factories.study_measure_payload(
                EXPOSED_CONVERSIONS,
                CONTROL_CONVERSIONS,
                EXPOSED_SALES_CENTS,
                CONTROL_SALES_CENTS,
            ),
            MEASUREMENT_ANALYST,
        )
    )


def test_geo_holdout_reads_lift_as_a_ratio_of_conversion_rates():
    """The geo variant divides the exposed rate by the control rate and never rescales.

    PRD 3.7: "The exposed rate is `exposed_conversions` divided by `exposed_group_size`
    and the control rate is `control_conversions` divided by `control_group_size`. Under
    `GEO_HOLDOUT`, `lift_pct` is 1.0000 when the control rate is 0, and otherwise the
    exposed rate divided by the control rate less 1.0, rounded half-up to four decimal
    places; `incremental_sales_cents` is `exposed_sales_cents` multiplied by `lift_pct`
    divided by the quantity one plus `lift_pct`, rounded half-up to whole cents, when
    `lift_pct` is greater than 0, and exactly 0 otherwise."

    Design: Difficulty/dual_variant_calc/dvc_geo_vs_user_holdout_lift_divergence
    """
    world = _two_measured_ready_campaigns()
    measured = _measure(world, "GEO_HOLDOUT")

    exposed_rate = EXPOSED_CONVERSIONS / EXPOSED_GROUP_SIZE
    control_rate = CONTROL_CONVERSIONS / CONTROL_GROUP_SIZE
    expected_lift = round_half_up(exposed_rate / control_rate - 1.0, 4)
    assert expected_lift == 0.6667
    assert measured["study_status"] == "MEASURING"
    assert measured["design_method"] == "GEO_HOLDOUT"
    assert measured["lift_pct"] == expected_lift

    # The stored four-decimal lift is what the incremental figure consumes, so the
    # incremental cents are not those of an unrounded ratio.
    expected_incremental = round_half_up_int(
        EXPOSED_SALES_CENTS * expected_lift / (1.0 + expected_lift)
    )
    assert expected_incremental == 16000480
    assert measured["incremental_sales_cents"] == expected_incremental
    assert measured["incremental_sales_cents"] != 16000000


def test_user_holdout_reads_lift_from_a_control_side_rescaled_to_the_exposed_group():
    """The user variant rescales control sales first, then subtracts, and disagrees.

    PRD 3.7: "Under `USER_HOLDOUT` the control side is first rescaled to the exposed
    group's size: the scaled control sales are `control_sales_cents` multiplied by
    `exposed_group_size` divided by `control_group_size`; `incremental_sales_cents` is
    `exposed_sales_cents` less the scaled control sales, floored at 0, rounded half-up to
    whole cents; and `lift_pct` is 1.0000 when the scaled control sales are 0, and
    otherwise `exposed_sales_cents` less the scaled control sales, divided by the scaled
    control sales, rounded half-up to four decimal places."

    PRD 3.7: "The two variants can disagree sharply on the same inputs, which is why
    `design_method` is fixed at design time and never amended."

    Design: Difficulty/dual_variant_calc/dvc_geo_vs_user_holdout_lift_divergence
    """
    world = _two_measured_ready_campaigns()
    geo = _measure(world, "GEO_HOLDOUT")
    user = _measure(world, "USER_HOLDOUT")

    scaled_control_sales = (
        CONTROL_SALES_CENTS * EXPOSED_GROUP_SIZE / CONTROL_GROUP_SIZE
    )
    assert scaled_control_sales == 27500000
    expected_incremental = round_half_up_int(
        max(EXPOSED_SALES_CENTS - scaled_control_sales, 0)
    )
    expected_lift = round_half_up(
        (EXPOSED_SALES_CENTS - scaled_control_sales) / scaled_control_sales, 4
    )

    assert user["design_method"] == "USER_HOLDOUT"
    assert user["study_status"] == "MEASURING"
    assert user["lift_pct"] == expected_lift == 0.4545
    assert user["incremental_sales_cents"] == expected_incremental == 12500000

    # Identical inputs, opposite bases, a divergence of 3,500,480 cents.
    assert geo["incremental_sales_cents"] != user["incremental_sales_cents"]
    assert geo["incremental_sales_cents"] - user["incremental_sales_cents"] == 3500480
    assert geo["lift_pct"] != user["lift_pct"]


def test_the_two_variants_share_a_significance_score_and_neither_feeds_its_campaign_yet():
    """Significance is variant-independent, and only publication reaches the campaign.

    PRD 3.7: "`significance_score` is the absolute difference between the exposed rate and
    the control rate, multiplied by the square root of the smaller of the two group sizes,
    rounded half-up to four decimal places. `significance_flag` is true when
    `significance_score` is at or above 1.96 and false below it, so a score of exactly
    1.9600 is significant."

    PRD 3.7: "Publication moves a `MEASURING` study to `PUBLISHED`, accepts an optional
    `publication_note`, and requires `significance_flag` to be true and no other study on
    the same campaign to be `PUBLISHED` with an overlapping window. It stamps
    `published_by_user_id` with the acting `X-User-ID`, writes the study's
    `incremental_sales_cents` onto the campaign's `incremental_revenue_cents` and
    recomputes `iroas`."

    Design: Difficulty/dual_variant_calc/dvc_geo_vs_user_holdout_lift_divergence
    """
    world = _two_measured_ready_campaigns()
    geo = _measure(world, "GEO_HOLDOUT")
    user = _measure(world, "USER_HOLDOUT")

    exposed_rate = EXPOSED_CONVERSIONS / EXPOSED_GROUP_SIZE
    control_rate = CONTROL_CONVERSIONS / CONTROL_GROUP_SIZE
    smaller_group = min(EXPOSED_GROUP_SIZE, CONTROL_GROUP_SIZE)
    expected_score = round_half_up(
        abs(exposed_rate - control_rate) * smaller_group**0.5, 4
    )
    assert expected_score == 2.8284
    assert geo["significance_score"] == expected_score
    assert user["significance_score"] == expected_score
    assert geo["significance_score"] >= SIGNIFICANCE_MIN
    assert geo["significance_flag"] is True
    assert user["significance_flag"] is True

    # Measurement alone writes nothing back: only publication does.
    assert reread_campaign(world, GEO)["incremental_revenue_cents"] == 0
    assert reread_campaign(world, USER)["incremental_revenue_cents"] == 0
