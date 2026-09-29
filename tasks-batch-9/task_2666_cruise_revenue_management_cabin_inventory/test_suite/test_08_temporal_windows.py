"""
Two calendars on the same parent with opposite tolerances for adjacency.

Fare windows are half-open intervals over days-to-sail where touching is legal;
promotional campaigns are closed intervals over wall-clock dates that must be
separated by a gap. The same overlap machinery, inverted.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ERR_FARE_WINDOW_OVERLAP,
    ERR_PROMO_CADENCE_CONFLICT,
    REVENUE_MANAGER,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
)


def _sailing_with_the_far_window_only(api):
    """A PLANNED voyage whose only fare rule covers days-to-sail [120, 365)."""
    return fx.simple_world(
        api,
        voyage_code="FWO-2701",
        nights=7,
        total_lower_berths=20,
        physical_cabins=10,
        oversell_allowance=0,
        open_now=False,
    )


def _fare_window(api, world, window_open, window_close, base_fare_cents):
    return api.create_fare_rule(
        f.fare_rule_payload(
            world.sailing["id"],
            world.category["id"],
            window_open_days_to_sail=window_open,
            window_close_days_to_sail=window_close,
            base_lower_berth_fare_cents=base_fare_cents,
        ),
        REVENUE_MANAGER,
    )


def test_fare_windows_touching_at_a_shared_endpoint_are_accepted(api):
    """Sharing an endpoint is not sharing a day, on either side of the interval.

    PRD 3.2: "The window is half-open, measured in days to sail: it includes
    window_close_days_to_sail and excludes window_open_days_to_sail, so a
    booking's days-to-sail figure falls inside the window when it is at least
    window_close_days_to_sail and strictly less than window_open_days_to_sail."
    And: "Because the interval is half-open, windows that merely touch at a
    shared endpoint do not overlap and are accepted: a rule closing at 90 and a
    rule opening at 90 fit together exactly, and the day 90 belongs to the
    former."

    Design: Difficulty/resource_temporal_overlap/fare_windows_may_touch_but_not_overlap
    """
    world = _sailing_with_the_far_window_only(api)

    # Touching the existing window from below at 120.
    validate_success(_fare_window(api, world, 120, 60, 219995), 201)
    # Touching the new window from below at 60.
    validate_success(_fare_window(api, world, 60, 0, 259995), 201)
    # Touching the original window from above, on its open side at 365.
    validate_success(_fare_window(api, world, 400, 365, 179995), 201)

    rules, meta = validate_paginated(
        api.list_fare_rules(
            REVENUE_MANAGER,
            params={
                "sailing_id": world.sailing["id"],
                "cabin_category_id": world.category["id"],
            },
        )
    )
    assert meta["total_count"] == 4
    # PRD 3.2: bookings_pinned_count "starts at 0"; nothing has been sold.
    for rule in rules:
        assert rule["bookings_pinned_count"] == 0


def test_a_fare_window_sharing_interior_days_is_rejected(api):
    """[30, 90) shares days 60 to 89 with [60, 120), so it is an overlap.

    PRD 3.2: "Two fare rules for the same sailing and cabin category may not
    overlap; an overlapping window is rejected with ERR_FARE_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/fare_windows_may_touch_but_not_overlap
    """
    world = _sailing_with_the_far_window_only(api)
    validate_success(_fare_window(api, world, 120, 60, 219995), 201)

    response = _fare_window(api, world, 90, 30, 239995)
    validate_error(response, ERR_FARE_WINDOW_OVERLAP, 422)

    _, meta = validate_paginated(
        api.list_fare_rules(
            REVENUE_MANAGER,
            params={
                "sailing_id": world.sailing["id"],
                "cabin_category_id": world.category["id"],
            },
        )
    )
    assert meta["total_count"] == 2


def _sailing_with_one_scheduled_campaign(api):
    """A voyage carrying the EARLY campaign over the closed interval 09-01..09-10.

    ``sailing_version`` is re-read after that creation because creating a
    promotion increments the parent sailing's version.
    """
    world = fx.simple_world(
        api,
        voyage_code="PCD-2701",
        nights=7,
        total_lower_berths=20,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides={
            "window_open_days_to_sail": 730,
            "window_close_days_to_sail": 0,
            "base_lower_berth_fare_cents": 189995,
            "third_berth_fare_cents": 64997,
            "fourth_berth_fare_cents": 49997,
        },
    )
    world.early = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="EARLY",
        audience="GENERAL",
        discount_pct=0.1,
        starts_on="2026-09-01T00:00:00Z",
        ends_on="2026-09-10T00:00:00Z",
        max_redemptions=25,
    )
    world.sailing_version = fx.read_sailing(api, world.sailing["id"])["version"]
    return world


def _campaign_starting(api, world, code, starts_on, ends_on):
    return api.create_promotion(
        f.promotion_payload(
            world.sailing["id"],
            world.sailing_version,
            code=code,
            audience="GENERAL",
            discount_pct=0.12,
            starts_on=starts_on,
            ends_on=ends_on,
            max_redemptions=25,
        ),
        REVENUE_MANAGER,
    )


def test_campaigns_closer_than_seven_days_are_refused(api):
    """Gaps of 5 and 6 days after a campaign ending 09-10 both conflict.

    PRD 3.2: "A new campaign's closed interval must be separated from the closed
    interval of every existing non-WITHDRAWN campaign on the same sailing by at
    least 7 whole days; anything closer - including an outright overlap - is
    refused with ERR_PROMO_CADENCE_CONFLICT." Because no campaign is created, the
    sailing's version does not move: PRD 3.2 says only that "creating it
    increments the parent sailing's version by 1".

    Design: Difficulty/resource_temporal_overlap/promotion_cadence_requires_seven_day_separation
    """
    world = _sailing_with_one_scheduled_campaign(api)

    validate_error(
        _campaign_starting(
            api, world, "GAP5", "2026-09-15T00:00:00Z", "2026-09-20T00:00:00Z"
        ),
        ERR_PROMO_CADENCE_CONFLICT,
        422,
    )
    validate_error(
        _campaign_starting(
            api, world, "GAP6", "2026-09-16T00:00:00Z", "2026-09-21T00:00:00Z"
        ),
        ERR_PROMO_CADENCE_CONFLICT,
        422,
    )

    assert fx.read_sailing(api, world.sailing["id"])["version"] == world.sailing_version

    _, meta = validate_paginated(
        api.list_promotions(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert meta["total_count"] == 1


def test_a_seven_day_separation_clears_the_cadence_rule(api):
    """Exactly 7 whole days after the 09-10 close is far enough.

    PRD 3.2: the separation must be "at least 7 whole days", and the accepted
    campaign "is created in SCHEDULED with redemption_count at 0 and
    withdraw_reason null, and creating it increments the parent sailing's version
    by 1."

    Design: Difficulty/resource_temporal_overlap/promotion_cadence_requires_seven_day_separation
    """
    world = _sailing_with_one_scheduled_campaign(api)

    accepted = validate_success(
        _campaign_starting(
            api, world, "GAP7", "2026-09-17T00:00:00Z", "2026-09-22T00:00:00Z"
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["redemption_count"] == 0
    assert accepted["withdraw_reason"] is None

    assert (
        fx.read_sailing(api, world.sailing["id"])["version"]
        == world.sailing_version + 1
    )

    promotions, meta = validate_paginated(
        api.list_promotions(REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(promo["code"] for promo in promotions) == ["EARLY", "GAP7"]

    early = fx.read_promotion(api, world.early["id"])
    assert early["status"] == "SCHEDULED"
    assert_instant_equals(early["ends_on"], "2026-09-10T00:00:00Z", "ends_on")
