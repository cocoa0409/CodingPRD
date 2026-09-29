"""Two shared resources with deliberately opposite interval semantics.

A legislator's calendar is half-open and widened by a travel buffer, so 15:29 is
still occupied and 15:30 is free. The send pipe for one campaign-and-channel
pairing is closed and unbuffered, so two waves that merely touch at 12:00 already
fill it, and only a wave starting a minute past the last close gets through.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CHANNEL_WINDOW_SATURATED,
    ERR_MEETING_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_count,
    assert_field,
    assert_instant_field,
    assert_page,
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_field_organizer_headers,
)
from test_helpers.types import (
    ACQUISITION_EVENT,
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    DELIVERY_SCHEDULED,
    LAWFUL_BASIS_EVENT_CARD,
    MEETING_CONFIRMED,
    MEETING_DECISION_CONFIRM,
    MEETING_REQUESTED,
    PUBLICATION_CONSENT_PUBLIC,
)


# --------------------------------------------------------------------------
# A legislator's calendar: half-open, buffered 30 minutes on both sides
# --------------------------------------------------------------------------

def _legislator_with_a_confirmed_two_oclock_meeting(api):
    """One confirmed hour on the calendar, ending at 15:00.

    With the travel buffer applied to both sides, that hour occupies the
    calendar right up to but not including 15:30.
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, world["campaign_id"], channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
        full_name="Tess Teller", email="tess@example.org",
        phone="+15551230022", acquisition_source=ACQUISITION_EVENT,
        lawful_basis=LAWFUL_BASIS_EVENT_CARD,
        consent_source_reference="townhall-card-7")
    profile = fx.create_certified_spokesperson(
        api, supporter["id"],
        story_summary="Lost her lease after a 40 percent rent increase.",
        publication_consent=PUBLICATION_CONSENT_PUBLIC)
    existing = fx.add_meeting(api, world["campaign_id"], world["legislator_id"],
                              profile["id"], "2026-08-10T14:00:00Z",
                              "2026-08-10T15:00:00Z")
    fx.respond_to_meeting(api, existing["id"], MEETING_DECISION_CONFIRM)
    world.update({"spokesperson_id": profile["id"],
                  "existing_meeting_id": existing["id"]})
    return world


def _attempt_meeting_at(api, world, window_start, window_end):
    payload = F.meeting_payload(world["campaign_id"], world["legislator_id"],
                               world["spokesperson_id"],
                               window_start, window_end)
    return api.create_meeting(payload, headers=make_field_organizer_headers())


def test_the_existing_hour_is_confirmed_and_therefore_occupies_the_calendar(api):
    """Only REQUESTED, CONFIRMED and HELD rows occupy the overlap input set.

    PRD: "Confirming moves the meeting from `REQUESTED` to `CONFIRMED` and has three preconditions: the meeting is currently `REQUESTED`; the lead spokesperson's `training_state` is `CERTIFIED`, otherwise `ERR_SPOKESPERSON_NOT_CERTIFIED`; and the campaign's `status` is `ACTIVE`, otherwise `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/meeting_half_open_interval_plus_thirty_minute_travel_buffer
    """
    world = _legislator_with_a_confirmed_two_oclock_meeting(api)

    assert_field(fx.read_meeting(api, world["existing_meeting_id"]),
                 "status", MEETING_CONFIRMED)


def test_a_meeting_starting_one_minute_inside_the_travel_buffer_is_refused(api):
    """15:29 is 29 minutes after a 15:00 close, so the buffer still bites.

    PRD: "Meeting windows are half-open — `window_start` included, `window_end` excluded — and overlap arithmetic is performed per legislator with a travel buffer of 30 minutes applied to **both sides** of each existing interval, so a request colliding with an existing `REQUESTED`, `CONFIRMED` or `HELD` meeting for the same legislator once that buffer is applied is refused with `ERR_MEETING_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/meeting_half_open_interval_plus_thirty_minute_travel_buffer
    """
    world = _legislator_with_a_confirmed_two_oclock_meeting(api)

    response = _attempt_meeting_at(api, world, "2026-08-10T15:29:00Z",
                                   "2026-08-10T16:29:00Z")

    validate_error(response, ERR_MEETING_WINDOW_CONFLICT, expected_status=409)


def test_a_meeting_starting_exactly_at_the_buffer_edge_is_accepted(api):
    """15:30 is the first free minute, because the buffered end is excluded.

    PRD: "A new meeting lands in `status` `REQUESTED` with `pressure_credit` of 0.00 and `decline_reason` null."

    Design: Difficulty/resource_temporal_overlap/meeting_half_open_interval_plus_thirty_minute_travel_buffer
    """
    world = _legislator_with_a_confirmed_two_oclock_meeting(api)
    _attempt_meeting_at(api, world, "2026-08-10T15:29:00Z",
                        "2026-08-10T16:29:00Z")

    accepted = validate_success(
        _attempt_meeting_at(api, world, "2026-08-10T15:30:00Z",
                            "2026-08-10T16:30:00Z"),
        expected_status=201)

    assert_instant_field(accepted, "window_start", "2026-08-10T15:30:00Z")
    assert_field(accepted, "status", MEETING_REQUESTED)


def test_the_calendar_holds_two_meetings_of_which_one_is_confirmed(api):
    """The refused request left no row, and nothing has been held yet.

    PRD: "Meetings can be listed filtered by `campaign_id`, `legislator_id`, `lead_spokesperson_id`, `location_district_code` and `status`."

    Design: Difficulty/resource_temporal_overlap/meeting_half_open_interval_plus_thirty_minute_travel_buffer
    """
    world = _legislator_with_a_confirmed_two_oclock_meeting(api)
    _attempt_meeting_at(api, world, "2026-08-10T15:29:00Z",
                        "2026-08-10T16:29:00Z")
    _attempt_meeting_at(api, world, "2026-08-10T15:30:00Z",
                        "2026-08-10T16:30:00Z")

    headers = make_field_organizer_headers()
    assert_page(api.list_meetings(
        headers=headers,
        params={"legislator_id": world["legislator_id"]}), expected_total=2)
    assert_page(api.list_meetings(
        headers=headers,
        params={"legislator_id": world["legislator_id"],
                "status": MEETING_CONFIRMED}), expected_total=1)
    assert_count(fx.read_legislator(api, world["legislator_id"])
                 ["meeting_held_count"], 0)


# --------------------------------------------------------------------------
# The send pipe: closed intervals, capacity two, no buffer
# --------------------------------------------------------------------------

def _email_pipe_saturated_by_two_waves_touching_at_noon(api):
    """Two scheduled email waves, one ending exactly where the next begins.

    Because a send window is a closed interval, the shared noon boundary counts
    as an overlap and the pipe is already at its capacity of two.
    """
    world = fx.create_sendable_world(api, supporter_count=1, channel=CHANNEL_EMAIL)
    first = fx.add_activation(api, world["campaign_id"], world["segment_id"],
                              world["variant_id"], "2026-08-08T09:00:00Z",
                              "2026-08-08T12:00:00Z", channel=CHANNEL_EMAIL)
    second = fx.add_activation(api, world["campaign_id"], world["segment_id"],
                               world["variant_id"], "2026-08-08T12:00:00Z",
                               "2026-08-08T15:00:00Z", channel=CHANNEL_EMAIL)
    world.update({"first_id": first["id"], "second_id": second["id"]})
    return world


def _attempt_wave_over(api, world, window_start, window_end):
    payload = F.activation_payload(
        world["campaign_id"], world["segment_id"], world["variant_id"],
        window_start, window_end,
        fx.read_segment(api, world["segment_id"])["version"],
        channel=CHANNEL_EMAIL, min_viable_reach=1)
    return api.create_activation(payload,
                                 headers=make_campaign_director_headers())


def test_two_waves_touching_at_a_shared_boundary_both_stay_scheduled(api):
    """The closed interval is what makes the shared noon minute an overlap.

    PRD: "Unlike milestone windows, an activation's send window is a **closed** interval: both `window_start` and `window_end` are included, and channel-saturation arithmetic treats it that way."

    Design: Difficulty/resource_temporal_overlap/channel_closed_window_saturation_at_cap_two_then_gap_reopens
    """
    world = _email_pipe_saturated_by_two_waves_touching_at_noon(api)

    assert_field(fx.read_activation(api, world["first_id"]),
                 "delivery_state", DELIVERY_SCHEDULED)
    second = fx.read_activation(api, world["second_id"])
    assert_field(second, "delivery_state", DELIVERY_SCHEDULED)
    assert_count(second["projected_reach"], 1)


def test_a_third_overlapping_wave_on_the_same_pipe_is_refused(api):
    """Noon to six overlaps both existing waves, so the pipe is saturated.

    PRD: "No more than two activations on the same campaign-and-channel pairing hold overlapping closed send windows while in delivery state `SCHEDULED` or `SENDING` — a third such wave is refused with `ERR_CHANNEL_WINDOW_SATURATED`."

    Design: Difficulty/resource_temporal_overlap/channel_closed_window_saturation_at_cap_two_then_gap_reopens
    """
    world = _email_pipe_saturated_by_two_waves_touching_at_noon(api)

    response = _attempt_wave_over(api, world, "2026-08-08T12:00:00Z",
                                  "2026-08-08T18:00:00Z")

    validate_error(response, ERR_CHANNEL_WINDOW_SATURATED, expected_status=409)


def test_a_wave_starting_one_minute_after_the_last_close_gets_through(api):
    """No buffer applies here, so 15:01 clears a window that closed at 15:00.

    PRD: "**Step three**: `effective_touch_cap` is the base allowance of 3 touches per supporter plus that surge grant, and it is persisted on the wave as an audit snapshot."

    Design: Difficulty/resource_temporal_overlap/channel_closed_window_saturation_at_cap_two_then_gap_reopens
    """
    world = _email_pipe_saturated_by_two_waves_touching_at_noon(api)
    _attempt_wave_over(api, world, "2026-08-08T12:00:00Z",
                       "2026-08-08T18:00:00Z")

    accepted = validate_success(
        _attempt_wave_over(api, world, "2026-08-08T15:01:00Z",
                           "2026-08-08T18:00:00Z"), expected_status=201)

    assert_instant_field(accepted, "window_start", "2026-08-08T15:01:00Z")
    assert_count(accepted["projected_reach"], 1)
    assert_count(accepted["effective_touch_cap"], 3)


def test_the_pipe_ends_up_with_three_waves_and_three_reservations(api):
    """Every accepted wave took one reservation and none has delivered yet.

    PRD: "`touches_reserved` counts outstanding reservations — the number of activations in delivery state `SCHEDULED` or `SENDING` that list this supporter in their `target_supporter_ids`."

    Design: Difficulty/resource_temporal_overlap/channel_closed_window_saturation_at_cap_two_then_gap_reopens
    """
    world = _email_pipe_saturated_by_two_waves_touching_at_noon(api)
    _attempt_wave_over(api, world, "2026-08-08T12:00:00Z",
                       "2026-08-08T18:00:00Z")
    _attempt_wave_over(api, world, "2026-08-08T15:01:00Z",
                       "2026-08-08T18:00:00Z")

    assert_page(api.list_activations(
        headers=make_campaign_director_headers(),
        params={"campaign_id": world["campaign_id"],
                "channel": CHANNEL_EMAIL}), expected_total=3)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 3)
    assert_count(supporter["touches_consumed"], 0)
