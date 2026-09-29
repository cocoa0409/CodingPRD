"""Line occupation geometry and the permit's per-calendar-day buckets."""
from test_helpers import (
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _line_at_one_hundred_kg_per_hour(api, **overrides):
    ctx = fx.bootstrap_network(api, quotes=None)
    ctx["line"] = fx.create_line(
        api, ctx["facility"]["id"], throughput_kg_per_hour=100.0, **overrides
    )
    return ctx


# --------------------------------------------------------------------------
# Half-open windows: adjacency touches, overlap conflicts
# --------------------------------------------------------------------------

def test_campaign_window_starting_exactly_where_the_incumbent_ends_is_accepted(api):
    """The occupation interval excludes its end instant, so back-to-back campaigns on
    one line touch without overlapping.

    PRD §3.6: "exact adjacency, where the candidate starts at precisely the instant an
    incumbent ends, touches without overlapping and is accepted."

    Design: Difficulty/resource_temporal_overlap/line_campaign_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = _line_at_one_hundred_kg_per_hour(api)

    first = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    second = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-02T00:00:00.000Z",
        window_end="2026-08-03T00:00:00.000Z",
        planned_input_kg=1000.0,
    )

    assert first["status"] == "SCHEDULED"
    assert second["status"] == "SCHEDULED"
    assert second["window_start"] == first["window_end"]


def test_campaign_window_overlapping_an_incumbent_by_one_millisecond_conflicts(api):
    """A candidate whose start falls one millisecond before an incumbent's end
    overlaps and is refused, while the adjacent alternative is accepted.

    PRD §3.6: "An incumbent conflicts when the candidate's start falls strictly before
    the incumbent's end **and** the incumbent's start falls strictly before the
    candidate's end, which is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`"

    Design: Difficulty/resource_temporal_overlap/line_campaign_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = _line_at_one_hundred_kg_per_hour(api)
    line_id = ctx["line"]["id"]
    for start, end in (
        ("2026-08-01T00:00:00.000Z", "2026-08-02T00:00:00.000Z"),
        ("2026-08-02T00:00:00.000Z", "2026-08-03T00:00:00.000Z"),
    ):
        fx.create_campaign(
            api, line_id, window_start=start, window_end=end, planned_input_kg=1000.0
        )

    response = api.create_campaign(
        f.create_campaign_payload(
            line_id,
            window_start="2026-08-02T23:59:59.999Z",
            window_end="2026-08-04T00:00:00.000Z",
            planned_input_kg=1000.0,
        ),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_CAMPAIGN_WINDOW_CONFLICT", 409)

    accepted = fx.create_campaign(
        api,
        line_id,
        window_start="2026-08-03T00:00:00.000Z",
        window_end="2026-08-04T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    assert accepted["status"] == "SCHEDULED"

    campaigns, meta = validate_paginated(
        api.list_campaigns(fx.OPERATOR, params={"line_id": line_id})
    )
    assert meta["total_count"] == 3
    assert len(campaigns) == 3


# --------------------------------------------------------------------------
# Changeover buffer between neighbours of different chemistry families
# --------------------------------------------------------------------------

def _replumbed_line_with_a_nickel_rich_incumbent(api):
    """A line whose scheduled nickel-rich campaign keeps its family after the line is
    re-plumbed to iron phosphate."""
    ctx = _line_at_one_hundred_kg_per_hour(api)
    ctx["incumbent"] = fx.create_campaign(
        api,
        ctx["line"]["id"],
        chemistry_family="NICKEL_RICH",
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    ctx["line"] = validate_success(
        api.replumb_processing_line(
            ctx["line"]["id"], f.replumb_payload("IRON_PHOSPHATE"), fx.ADMIN
        )
    )
    return ctx


def test_changeover_gap_shorter_than_the_buffer_is_refused(api):
    """Five idle hours between neighbours of different chemistry families is fewer
    than the line's six-hour buffer.

    PRD §3.6: "a gap of fewer hours than the line's `changeover_buffer_hours` is
    refused with `ERR_CHANGEOVER_BUFFER_VIOLATION`"

    Design: Difficulty/resource_temporal_overlap/line_changeover_buffer_requires_positive_gap_between_families
    """
    ctx = _replumbed_line_with_a_nickel_rich_incumbent(api)
    assert ctx["line"]["changeover_buffer_hours"] == 6

    response = api.create_campaign(
        f.create_campaign_payload(
            ctx["line"]["id"],
            chemistry_family="IRON_PHOSPHATE",
            window_start="2026-08-02T05:00:00.000Z",
            window_end="2026-08-03T00:00:00.000Z",
            planned_input_kg=1000.0,
        ),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_CHANGEOVER_BUFFER_VIOLATION", 422)

    campaigns, meta = validate_paginated(
        api.list_campaigns(fx.OPERATOR, params={"line_id": ctx["line"]["id"]})
    )
    assert meta["total_count"] == 1


def test_changeover_gap_exactly_equal_to_the_buffer_is_accepted(api):
    """Six idle hours is not fewer than the buffer, so the different-family campaign
    is scheduled and the incumbent keeps the family it was booked with.

    PRD §3.1: "Re-plumbing deliberately does **not** rewrite the family recorded on
    campaigns that are already scheduled — those campaigns keep the family they were
    scheduled with"

    Design: Difficulty/resource_temporal_overlap/line_changeover_buffer_requires_positive_gap_between_families
    """
    ctx = _replumbed_line_with_a_nickel_rich_incumbent(api)

    accepted = fx.create_campaign(
        api,
        ctx["line"]["id"],
        chemistry_family="IRON_PHOSPHATE",
        window_start="2026-08-02T06:00:00.000Z",
        window_end="2026-08-03T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["chemistry_family"] == "IRON_PHOSPHATE"

    campaigns, meta = validate_paginated(
        api.list_campaigns(fx.OPERATOR, params={"line_id": ctx["line"]["id"]})
    )
    assert meta["total_count"] == 2

    incumbent = validate_success(
        api.get_campaign(ctx["incumbent"]["id"], fx.OPERATOR)
    )
    assert incumbent["chemistry_family"] == "NICKEL_RICH"


# --------------------------------------------------------------------------
# The permit bucket key is the UTC calendar date alone
# --------------------------------------------------------------------------

def _allotment_with_a_lot(api):
    ctx = fx.bootstrap_network(api, quotes=None)
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"])
    ctx["campaign"] = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-25T00:00:00.000Z",
        window_end="2026-09-30T00:00:00.000Z",
    )
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"])
    ctx["allotment"] = fx.create_allotment(api, ctx["facility"]["id"])
    return ctx


def test_the_last_millisecond_of_a_day_and_the_first_of_the_next_are_separate_buckets(api):
    """Two full daily caps a millisecond apart both post, and only a further gramme on
    the second day breaches its bucket.

    PRD §3.8: "Because the bucket key is the UTC date alone, a discharge at the last
    millisecond of one day and one at the first millisecond of the next fall into
    different buckets."

    Design: Difficulty/resource_temporal_overlap/permit_daily_bucket_aggregate_capacity_per_utc_calendar_day
    """
    ctx = _allotment_with_a_lot(api)
    allotment_id = ctx["allotment"]["id"]

    for event_date in ("2026-08-20T23:59:59.999Z", "2026-08-21T00:00:00.000Z"):
        event = validate_success(
            api.create_discharge_event(
                ctx["lot"]["id"],
                f.create_discharge_event_payload(allotment_id, event_date, 500.0),
                fx.SUBMITTER,
            ),
            expected_status=201,
        )
        assert event["status"] == "POSTED"

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 1000.0

    response = api.create_discharge_event(
        ctx["lot"]["id"],
        f.create_discharge_event_payload(allotment_id, "2026-08-21T12:00:00.000Z", 0.001),
        fx.SUBMITTER,
    )
    validate_error(response, "ERR_DISCHARGE_DAILY_CAP_EXCEEDED", 422)


def test_permit_validity_is_a_closed_interval_and_each_day_gets_its_own_cap(api):
    """A discharge beyond the permit's last covered instant is excluded, while a third
    calendar day inside the interval carries its own full cap.

    PRD §3.8: "The window gate is a **closed** interval with both ends inclusive: the
    `event_date` must fall at or after `valid_from` and at or before `valid_to`, and
    falling outside is refused with `ERR_PERMIT_WINDOW_EXCLUDED`."

    Design: Difficulty/resource_temporal_overlap/permit_daily_bucket_aggregate_capacity_per_utc_calendar_day
    """
    ctx = _allotment_with_a_lot(api)
    allotment_id = ctx["allotment"]["id"]
    for event_date in ("2026-08-20T23:59:59.999Z", "2026-08-21T00:00:00.000Z"):
        fx.book_discharge_event(api, ctx["lot"]["id"], allotment_id, event_date, 500.0)

    outside = api.create_discharge_event(
        ctx["lot"]["id"],
        f.create_discharge_event_payload(allotment_id, "2026-09-01T00:00:00.000Z", 1.0),
        fx.SUBMITTER,
    )
    validate_error(outside, "ERR_PERMIT_WINDOW_EXCLUDED", 422)
    assert fx.read_allotment(api, allotment_id)["status"] == "ACTIVE"

    third_day = fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-01T00:00:00.000Z", 500.0
    )
    assert third_day["status"] == "POSTED"

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 1500.0

    events, meta = validate_paginated(
        api.list_discharge_events(fx.SUBMITTER, params={"allotment_id": allotment_id})
    )
    assert meta["total_count"] == 3
    assert all(event["status"] == "POSTED" for event in events)
