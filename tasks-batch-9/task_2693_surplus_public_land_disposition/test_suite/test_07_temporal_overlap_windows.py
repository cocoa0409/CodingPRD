"""Two contended resources whose intervals are read with opposite conventions.

An appraiser's capacity is booked over closed intervals, so a shared endpoint day
is a collision and a window has to be shrunk a day at each end to fit between two
neighbours. A parcel's disposition timeline is booked over half-open intervals,
so a new offering may open on the exact instant the previous one closes.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error


def _appraiser_between_two_engagements(api):
    """One appraiser already booked on either side of a five-day gap.

    Engagement A runs the closed interval [2026-08-02, 2026-08-20] on the first
    parcel and engagement B runs [2026-08-25, 2026-09-05] on the second. They do
    not touch each other, so both were admissible, and both are `ORDERED` and
    therefore in flight. A third parcel is recorded to carry its own concurrency
    token for the contested order.
    """
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["appraiser"] = fx.make_appraiser(api)
    ctx["parcels"] = [
        fx.make_parcel(
            api,
            ctx["agency"]["id"],
            apn=f"APN-2693-02{number}",
            address=f"{number} Canal Street",
            acreage=1.0,
            zoning_code="M-1",
            book_value_cents=39000000 + number * 1000000,
        )
        for number in (1, 2, 3)
    ]
    ctx["engagement_a"] = fx.order_appraisal(
        api,
        ctx["parcels"][0]["id"],
        ctx["appraiser"]["id"],
        engagement_start_on="2026-08-02T00:00:00Z",
        engagement_end_on="2026-08-20T00:00:00Z",
    )
    ctx["engagement_b"] = fx.order_appraisal(
        api,
        ctx["parcels"][1]["id"],
        ctx["appraiser"]["id"],
        engagement_start_on="2026-08-25T00:00:00Z",
        engagement_end_on="2026-09-05T00:00:00Z",
    )
    ctx["third_parcel_version"] = fx.parcel_version(api, ctx["parcels"][2]["id"])
    return ctx


def _order_over(api, ctx, start_on, end_on):
    """Order the third engagement over the given closed interval and token."""
    return api.create_appraisal(
        f.appraisal_order_payload(
            ctx["parcels"][2]["id"],
            ctx["appraiser"]["id"],
            ctx["third_parcel_version"],
            method="COST",
            engagement_start_on=start_on,
            engagement_end_on=end_on,
        ),
        fx.OFFICER_HEADERS,
    )


def _appraisals_of(api, ctx):
    """Every appraisal booked against this appraiser."""
    return get_success_data(
        api.list_appraisals(
            fx.OFFICER_HEADERS,
            {"appraiser_id": ctx["appraiser"]["id"], "limit": 100},
        )
    )


def _authorized_declaration_with_a_december_offering(api):
    """An authorized disposition already holding the window [2026-12-01, 2026-12-31).

    The parcel carries no title curative item, the valuation runs to 2027-08-01,
    and the first offering sits in `DRAFT`, which is one of the four live statuses
    that block a colliding window. The clock never leaves the default instant.
    """
    ctx = fx.build_valued_parcel(api, appraised_value_cents=100000000)
    ctx = fx.build_authorized_declaration(api, ctx)
    ctx["first_offering"] = fx.make_offering(
        api,
        ctx["declaration"]["id"],
        bid_open_at="2026-12-01T00:00:00Z",
        bid_close_at="2026-12-31T00:00:00Z",
    )
    ctx["version_before_trigger"] = fx.declaration_version(
        api, ctx["declaration"]["id"]
    )
    return ctx


def _second_offering_over(api, ctx, bid_open_at, bid_close_at):
    """Create a second offering on the same parcel over the given window."""
    return api.create_offering(
        f.offering_payload(
            ctx["declaration"]["id"],
            ctx["version_before_trigger"],
            offering_type="COMPETITIVE_SALE",
            bid_open_at=bid_open_at,
            bid_close_at=bid_close_at,
        ),
        fx.OFFICER_HEADERS,
    )


def _offerings_on(api, ctx):
    """Every offering standing against this declaration."""
    return get_success_data(
        api.list_offerings(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )


def test_01_an_engagement_touching_both_neighbours_endpoint_days_is_refused(api):
    """Sharing one calendar day at each end collides with two engagements at once.

    "Because both intervals are closed, sharing a single endpoint day counts as an
    intersection: a requested start equal to an existing engagement's end
    overlaps, while a requested start one day after that end does not." "If the
    count of intersecting in-flight engagements is already two or more, the order
    is refused with `ERR_APPRAISER_CAPACITY_EXCEEDED` (HTTP 409); at most one such
    engagement may already exist for the order to succeed."

    Design: Difficulty/resource_temporal_overlap/appraiser_engagement_closed_interval_endpoint_day_counts_as_overlap
    """
    ctx = _appraiser_between_two_engagements(api)

    response = _order_over(api, ctx, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z")
    validate_error(response, ApiErrorId.ERR_APPRAISER_CAPACITY_EXCEEDED.value, 409)


def test_02_the_refused_order_books_nothing_and_spends_no_token(api):
    """The count stays at two and the third parcel's token is still current.

    "On success the appraisal is created in `ORDERED`, the parcel's `version` rises
    by 1, and the appraiser's `active_engagement_count` is recomputed." "An
    appraiser's `active_engagement_count` counts that appraiser's appraisals in
    `ORDERED`, `REPORTED` or `CHALLENGED`."

    Design: Difficulty/resource_temporal_overlap/appraiser_engagement_closed_interval_endpoint_day_counts_as_overlap
    """
    ctx = _appraiser_between_two_engagements(api)
    _order_over(api, ctx, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z")

    rows = _appraisals_of(api, ctx)
    assert len(rows) == 2, (
        f"the refused order books no third engagement, got {len(rows)}"
    )
    appraiser = get_success_data(
        api.get_appraiser(ctx["appraiser"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraiser["active_engagement_count"] == 2, (
        "so the appraiser is still carrying exactly two, got "
        f"{appraiser['active_engagement_count']}"
    )
    parcel = get_success_data(
        api.get_parcel(ctx["parcels"][2]["id"], fx.OFFICER_HEADERS)
    )
    assert parcel["version"] == ctx["third_parcel_version"], (
        "and the token the caller spent on the refused order is still current: "
        f"{parcel['version']} against {ctx['third_parcel_version']}"
    )


def test_03_shrinking_the_window_one_day_at_each_end_fits_between_the_two(api):
    """A start one day after the earlier end and an end one day before the later start.

    "Because both intervals are closed, sharing a single endpoint day counts as an
    intersection: a requested start equal to an existing engagement's end
    overlaps, while a requested start one day after that end does not." "On
    success the appraisal is created in `ORDERED`, the parcel's `version` rises by
    1, and the appraiser's `active_engagement_count` is recomputed."

    Design: Difficulty/resource_temporal_overlap/appraiser_engagement_closed_interval_endpoint_day_counts_as_overlap
    """
    ctx = _appraiser_between_two_engagements(api)
    _order_over(api, ctx, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z")

    third = get_success_data(
        _order_over(api, ctx, "2026-08-21T00:00:00Z", "2026-08-24T00:00:00Z")
    )
    assert third["status"] == "ORDERED", (
        "a window strictly between the two neighbours is admissible, got "
        f"{third['status']!r}"
    )
    assert third["engagement_start_on"] == "2026-08-21T00:00:00Z", (
        f"starting the day after engagement A ends, got {third['engagement_start_on']!r}"
    )
    assert third["engagement_end_on"] == "2026-08-24T00:00:00Z", (
        f"and ending the day before engagement B begins, got {third['engagement_end_on']!r}"
    )

    rows = _appraisals_of(api, ctx)
    assert len(rows) == 3, f"three engagements now stand on the record, got {len(rows)}"
    appraiser = get_success_data(
        api.get_appraiser(ctx["appraiser"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraiser["active_engagement_count"] == 3, (
        "all three are in flight, got " f"{appraiser['active_engagement_count']}"
    )
    parcel = get_success_data(
        api.get_parcel(ctx["parcels"][2]["id"], fx.OFFICER_HEADERS)
    )
    assert parcel["version"] == ctx["third_parcel_version"] + 1, (
        "and the successful create is what advanced the parcel, got "
        f"{parcel['version']}"
    )
    for label, booking in (("A", ctx["engagement_a"]), ("B", ctx["engagement_b"])):
        row = get_success_data(api.get_appraisal(booking["id"], fx.OFFICER_HEADERS))
        assert row["status"] == "ORDERED", (
            f"engagement {label} is untouched by either attempt, got {row['status']!r}"
        )


def test_04_a_window_overlapping_the_live_offering_by_one_day_is_refused(api):
    """Opening a day before the standing window closes is a genuine collision.

    "Two offerings on the same parcel therefore conflict when, and only when, the
    new offering's `bid_open_at` falls strictly before the other's `bid_close_at`
    and the other's `bid_open_at` falls strictly before the new offering's
    `bid_close_at`." "Next the window must not collide with another live offering
    on the same parcel, as set out below, on pain of
    `ERR_OFFERING_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/offering_bidding_window_half_open_adjacency_is_legal
    """
    ctx = _authorized_declaration_with_a_december_offering(api)
    assert ctx["first_offering"]["status"] == "DRAFT", (
        "a draft offering is one of the four live statuses that block a window, "
        f"got {ctx['first_offering']['status']!r}"
    )

    response = _second_offering_over(
        api, ctx, "2026-12-30T00:00:00Z", "2027-01-15T00:00:00Z"
    )
    validate_error(response, ApiErrorId.ERR_OFFERING_WINDOW_CONFLICT.value, 409)


def test_05_the_refused_window_leaves_the_timeline_and_the_token_intact(api):
    """One offering still holds the parcel's timeline and the token is unspent.

    "On success the offering is created in `DRAFT` with three computed values
    frozen onto it and never recomputed thereafter: `minimum_price_cents` from the
    minimum-price rules of §3.7, `minimum_price_variant` recording which variant
    produced it, and `required_deposit_cents`." "The declaration's `version` rises
    by 1."

    Design: Difficulty/resource_temporal_overlap/offering_bidding_window_half_open_adjacency_is_legal
    """
    ctx = _authorized_declaration_with_a_december_offering(api)
    _second_offering_over(api, ctx, "2026-12-30T00:00:00Z", "2027-01-15T00:00:00Z")

    offerings = _offerings_on(api, ctx)
    assert len(offerings) == 1, (
        "the refused create books no second window on the parcel, got "
        f"{len(offerings)}"
    )
    assert offerings[0]["id"] == ctx["first_offering"]["id"], (
        "and the survivor is the December offering that was already standing"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["version"] == ctx["version_before_trigger"], (
        "the declaration's concurrency token is not spent by the refusal: "
        f"{declaration['version']} against {ctx['version_before_trigger']}"
    )


def test_06_a_window_opening_on_the_exclusive_upper_bound_is_accepted(api):
    """Adjacency at the shared instant is legal and both windows coexist.

    "Adjacency is legal: a new window whose `bid_open_at` is exactly another
    window's `bid_close_at` does not conflict, and neither does the mirror case."
    "This half-open treatment is deliberately unlike the closed intervals that
    govern appraiser engagements and environmental circulation, where sharing a
    single endpoint is an overlap."

    Design: Difficulty/resource_temporal_overlap/offering_bidding_window_half_open_adjacency_is_legal
    """
    ctx = _authorized_declaration_with_a_december_offering(api)
    _second_offering_over(api, ctx, "2026-12-30T00:00:00Z", "2027-01-15T00:00:00Z")

    second = get_success_data(
        _second_offering_over(api, ctx, "2026-12-31T00:00:00Z", "2027-01-15T00:00:00Z")
    )
    assert second["bid_open_at"] == "2026-12-31T00:00:00Z", (
        "the replayed token opens the January window, got "
        f"{second['bid_open_at']!r}"
    )
    assert second["bid_open_at"] == ctx["first_offering"]["bid_close_at"], (
        "which is exactly the instant the December window gives up: "
        f"{second['bid_open_at']!r} against "
        f"{ctx['first_offering']['bid_close_at']!r}"
    )
    assert second["status"] == "DRAFT", (
        f"the second offering opens in draft as well, got {second['status']!r}"
    )

    offerings = _offerings_on(api, ctx)
    assert len(offerings) == 2, (
        f"both adjacent windows coexist on the parcel, got {len(offerings)}"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["version"] == ctx["version_before_trigger"] + 1, (
        "and only the successful create advanced the declaration, got "
        f"{declaration['version']}"
    )
