"""Three resources, three different interval semantics.

A channel's network feed path is occupied over a guard-expanded *closed* interval,
so guarded endpoints that merely touch collide. A playlist's own airtime timeline
is occupied over *half-open* spans, where touching endpoints are not merely
tolerated but mandatory and only a one-second back-lap collides. A channel's
single emergency-override slot is *open-ended*: it has a start instant and no end
instant at all, so it stays occupied until an explicit release.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx

SD_PLANT_MUX = {
    "total_capacity_kbps": 20000,
    "pilot_reserved_kbps": 500,
    "live_encoder_units_total": 2,
}
SD_PLANT_CH1 = {
    "resolution_class": "SD_480I",
    "requested_bitrate_kbps": 6000,
    "floor_bitrate_kbps": 2000,
    "priority_rank": 1,
}


def _sd_plant() -> dict:
    """One FULL_POWER transmitter, MUX-A (20000/500) and one ACTIVE SD channel 12.1."""
    return fx.setup_base_plant(
        with_subchannel=False,
        mux_overrides=dict(SD_PLANT_MUX),
        ch1_overrides=dict(SD_PLANT_CH1),
    )


def _sd_asset(plant: dict, duration_seconds: int) -> dict:
    """A QC_PASSED SD_480I asset scoring a clean 100."""
    return fx.setup_qc_passed_asset(
        plant,
        duration_seconds,
        asset_overrides={"required_resolution_class": "SD_480I"},
    )


# ===========================================================================
# The channel's network feed path: a guard-expanded CLOSED interval
# ===========================================================================

def _armed_day_with_one_planned_window() -> dict:
    """An armed day whose first two elements are network joins, plus window W1.

    Three adjacent 600 s elements starting at 12:00:00Z cover the declared 1800 s
    window exactly, so the day validates and arms. W1 spans 12:00:00Z to
    12:10:00Z with `guard_seconds` 2, so its guarded occupancy is
    11:59:58Z through 12:10:02Z. The clock stands at 11:00:00Z, before every
    window, so nothing has joined yet.
    """
    plant = _sd_plant()
    programme = _sd_asset(plant, 600)
    plant["playlist"] = fx.ingest(
        plant,
        [
            {"sequence_number": 1, "element_kind": "NETWORK_JOIN",
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 600, "max_trim_seconds": 0},
            {"sequence_number": 2, "element_kind": "NETWORK_JOIN",
             "scheduled_start_utc": "2026-08-01T12:10:00Z",
             "scheduled_duration_seconds": 600, "max_trim_seconds": 0},
            {"sequence_number": 3, "element_kind": "PROGRAM",
             "asset_id": programme["id"],
             "scheduled_start_utc": "2026-08-01T12:20:00Z",
             "scheduled_duration_seconds": 600, "max_trim_seconds": 0},
        ],
        window_duration_seconds=1800,
    )
    fx.drive_playlist(plant, plant["playlist"]["id"], "VALIDATED")
    fx.drive_playlist(plant, plant["playlist"]["id"], "ARMED")
    fx.set_clock("2026-08-01T11:00:00Z")
    plant["window1"] = fx.create_window(
        plant, "2026-08-01T12:00:00Z", "2026-08-01T12:10:00Z",
        anchor_sequence_number=1, feed_source="NETWORK_PRIMARY",
        backtiming_mode="STRICT", guard_seconds=2, live_encoder_units=1,
    )
    return plant


def _second_window_payload(plant: dict, join_utc: str) -> dict:
    return {
        "channel_id": plant["ch1"]["id"],
        "feed_source": "NETWORK_ALT",
        "anchor_sequence_number": 2,
        "join_utc": join_utc,
        "breakaway_utc": "2026-08-01T12:20:00Z",
        "backtiming_mode": "STRICT",
        "guard_seconds": 2,
        "live_encoder_units": 1,
    }


def test_touching_guard_bands_collide_on_the_channel_feed_path(api):
    """A guarded start instant exactly equal to the incumbent's guarded end instant collides.

    PRD §3.7: "**windows may not overlap on a channel, and the comparison is made on the guarded interval using closed semantics**: a new window's span from `join_utc` less `guard_seconds` through `breakaway_utc` plus `guard_seconds`, endpoints included, must not intersect the equally guarded span of any other window on the same channel whose `state` is `PLANNED` or `JOINED`."

    Design: Difficulty/resource_temporal_overlap/guarded_feed_windows_collide_when_their_guard_bands_merely_touch
    """
    plant = _armed_day_with_one_planned_window()

    resp = api.create_feed_window(
        _second_window_payload(plant, "2026-08-01T12:10:04Z"), plant["mco_headers"]
    )
    validate_error(resp, "ERR_FEED_WINDOW_OVERLAP")

    windows, meta = validate_paginated(
        api.list_channel_feed_windows(plant["ch1"]["id"], plant["mco_headers"])
    )
    assert meta["total_count"] == 1
    assert [w["id"] for w in windows] == [plant["window1"]["id"]]
    assert fx.read_feed_window(plant["window1"]["id"],
                               plant["mco_headers"])["state"] == "PLANNED"


def test_guarded_start_one_second_clear_of_the_incumbent_is_accepted(api):
    """One second of daylight between the guard bands is the whole difference.

    PRD §3.7: "Because the endpoints are included, **a new join placed exactly at another window's guarded breakaway instant is rejected, and one second later is accepted**; the refusal is `ERR_FEED_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/guarded_feed_windows_collide_when_their_guard_bands_merely_touch
    """
    plant = _armed_day_with_one_planned_window()

    refused = api.create_feed_window(
        _second_window_payload(plant, "2026-08-01T12:10:04Z"), plant["mco_headers"]
    )
    validate_error(refused, "ERR_FEED_WINDOW_OVERLAP")

    accepted = api.create_feed_window(
        _second_window_payload(plant, "2026-08-01T12:10:05Z"), plant["mco_headers"]
    )
    window2 = validate_success(accepted, 201)
    assert window2["state"] == "PLANNED"
    assert window2["guard_seconds"] == 2

    windows, meta = validate_paginated(
        api.list_channel_feed_windows(plant["ch1"]["id"], plant["mco_headers"])
    )
    assert meta["total_count"] == 2
    assert {w["id"] for w in windows} == {plant["window1"]["id"], window2["id"]}


# ===========================================================================
# The playlist's own airtime timeline: HALF-OPEN spans
# ===========================================================================

def _timeline_assets(plant: dict) -> dict:
    """Three programmes of 900, 901 and 902 seconds, all QC_PASSED."""
    return {
        "p900": _sd_asset(plant, 900),
        "p901": _sd_asset(plant, 901),
        "p902": _sd_asset(plant, 902),
    }


def _touching_day_items(assets: dict) -> list:
    """900 s from 12:00:00Z then 901 s from 12:15:00Z: the second starts exactly as the first ends."""
    return [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": assets["p900"]["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 900, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "PROGRAM",
         "asset_id": assets["p901"]["id"],
         "scheduled_start_utc": "2026-08-01T12:15:00Z",
         "scheduled_duration_seconds": 901, "max_trim_seconds": 0},
    ]


def _backlapped_day_payload(plant: dict, assets: dict) -> dict:
    """The same shape one day later, but element two starts one second before element one ends."""
    return {
        "channel_id": plant["ch1"]["id"],
        "broadcast_day": "2026-08-02",
        "schedule_start_utc": "2026-08-02T12:00:00Z",
        "window_duration_seconds": 1801,
        "items": [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": assets["p900"]["id"],
             "scheduled_start_utc": "2026-08-02T12:00:00Z",
             "scheduled_duration_seconds": 900, "max_trim_seconds": 0},
            {"sequence_number": 2, "element_kind": "PROGRAM",
             "asset_id": assets["p902"]["id"],
             "scheduled_start_utc": "2026-08-02T12:14:59Z",
             "scheduled_duration_seconds": 902, "max_trim_seconds": 0},
        ],
    }


def test_touching_elements_are_contiguous_and_the_day_is_accepted(api):
    """Element two booked at the exact instant element one's half-open span ends is legal.

    PRD §3.5: "The channel timeline uses **half-open intervals**: an element occupies the span from its `scheduled_start_utc` up to but not including that instant plus its `scheduled_duration_seconds`"

    PRD §3.5: "**A difference of exactly zero seconds is contiguous and legal**; touching elements are the normal case."

    Design: Difficulty/resource_temporal_overlap/half_open_timeline_accepts_touching_items_but_rejects_one_second_backlap
    """
    plant = _sd_plant()
    assets = _timeline_assets(plant)

    resp = api.ingest_playlist(
        {
            "channel_id": plant["ch1"]["id"],
            "broadcast_day": "2026-08-01",
            "schedule_start_utc": "2026-08-01T12:00:00Z",
            "window_duration_seconds": 1801,
            "items": _touching_day_items(assets),
        },
        plant["traffic_headers"],
    )
    playlist = validate_success(resp, 201)
    assert playlist["status"] == "IMPORTED"
    assert playlist["item_count"] == 2
    assert playlist["scheduled_total_seconds"] == 1801
    assert playlist["projected_end_variance_seconds"] == 0

    items = fx.list_items(playlist["id"], plant["traffic_headers"])
    assert [i["sequence_number"] for i in items] == [1, 2]
    assert items[1]["scheduled_start_utc"].startswith("2026-08-01T12:15:00")


def test_one_second_backlap_on_the_playlist_timeline_is_refused(api):
    """Pulling element two one second earlier makes the two half-open spans intersect.

    PRD §3.5: "if it is *before* that end the elements collide and the pass fails with `ERR_SCHEDULE_OVERLAP_DETECTED`"

    PRD §3.5: "The integrity pass is run on ingest, on every traffic revision, on every makegood placement, on every substitution, and again when the playlist is driven to `VALIDATED`."

    Design: Difficulty/resource_temporal_overlap/half_open_timeline_accepts_touching_items_but_rejects_one_second_backlap
    """
    plant = _sd_plant()
    assets = _timeline_assets(plant)
    accepted = fx.ingest(
        plant,
        _touching_day_items(assets),
        broadcast_day="2026-08-01",
        schedule_start_utc="2026-08-01T12:00:00Z",
        window_duration_seconds=1801,
    )

    resp = api.ingest_playlist(_backlapped_day_payload(plant, assets),
                               plant["traffic_headers"])
    validate_error(resp, "ERR_SCHEDULE_OVERLAP_DETECTED")

    playlists, meta = validate_paginated(
        api.list_channel_playlists(plant["ch1"]["id"], plant["traffic_headers"])
    )
    assert meta["total_count"] == 1, "the refused ingest leaves no playlist behind"
    assert [p["id"] for p in playlists] == [accepted["id"]]
    assert fx.read_playlist(accepted["id"])["scheduled_total_seconds"] == 1801


# ===========================================================================
# The channel's single override slot: an OPEN-ENDED occupancy
# ===========================================================================

def _channel_with_active_crawl() -> dict:
    """A severe-weather crawl requested at 12:05:00Z and authorized by the programme director.

    The crawl is planned to run 1800 seconds, but its effective occupancy has no
    end instant: it lasts until somebody releases it.
    """
    plant = _sd_plant()
    fx.set_clock("2026-08-01T12:05:00Z")
    requested = fx.request_override(
        plant, "CRAWL",
        alert_class="SEVERE_WEATHER",
        requested_start_utc="2026-08-01T12:05:00Z",
        expected_duration_seconds=1800,
        crawl_text="Severe thunderstorm warning for the viewing area.",
    )
    plant["override1"] = fx.activate_override(plant, requested["id"], "CRAWL")
    return plant


def _later_request_payload(plant: dict) -> dict:
    """A second request booked at 13:00:00Z, clear of the first override's planned span."""
    return {
        "channel_id": plant["ch1"]["id"],
        "requested_by_operator_id": plant["mco"]["id"],
        "alert_class": "BREAKING_NEWS",
        "override_mode": "CRAWL",
        "requested_start_utc": "2026-08-01T13:00:00Z",
        "expected_duration_seconds": 300,
        "crawl_text": "Breaking news: county courthouse evacuation under way.",
    }


def test_active_crawl_blocks_a_later_request_that_does_not_overlap_its_planned_span(api):
    """The incumbent's planned end is irrelevant: an unreleased override occupies the slot outright.

    PRD §3.8: "Because an override's effective interval runs from activation until release with no predetermined end, any override on the channel whose `state` is `PENDING`, `ACTIVE_CRAWL` or `ACTIVE_CUTIN` blocks a new request with `ERR_OVERRIDE_WINDOW_OVERLAP`; only `RELEASED` and `REJECTED` overrides, which are terminal, leave the channel free."

    PRD §3.8: "The channel's `posture` recomputes to `EMERGENCY`, but **`air_status` is unchanged because a crawl is an overlay rather than a substitution**"

    Design: Difficulty/resource_temporal_overlap/open_ended_override_slot_blocks_a_later_non_overlapping_request_until_released
    """
    plant = _channel_with_active_crawl()
    assert plant["override1"]["state"] == "ACTIVE_CRAWL"

    resp = api.create_override(_later_request_payload(plant), plant["mco_headers"])
    validate_error(resp, "ERR_OVERRIDE_WINDOW_OVERLAP")

    incumbent = fx.read_override(plant["override1"]["id"], plant["mco_headers"])
    assert incumbent["state"] == "ACTIVE_CRAWL"
    assert incumbent["active_mode"] == "CRAWL"
    assert incumbent["released_utc"] is None
    assert fx.read_channel(plant["ch1"]["id"])["posture"] == "EMERGENCY"

    overrides, meta = validate_paginated(
        api.list_overrides(plant["mco_headers"],
                           params={"channel_id": plant["ch1"]["id"]})
    )
    assert meta["total_count"] == 1, "the refused request creates nothing"
    assert [o["id"] for o in overrides] == [plant["override1"]["id"]]


def test_releasing_the_override_frees_the_channel_for_the_identical_request(api):
    """RELEASED is terminal, so the slot reopens and the previously refused request is accepted.

    PRD §3.8: "A release writes `released_utc` at the current logical time and sets `active_mode` to null."

    PRD §3.8: "only `RELEASED` and `REJECTED` overrides, which are terminal, leave the channel free."

    Design: Difficulty/resource_temporal_overlap/open_ended_override_slot_blocks_a_later_non_overlapping_request_until_released
    """
    plant = _channel_with_active_crawl()
    refused = api.create_override(_later_request_payload(plant), plant["mco_headers"])
    validate_error(refused, "ERR_OVERRIDE_WINDOW_OVERLAP")

    fx.set_clock("2026-08-01T12:06:00Z")
    released = fx.release_override(plant, plant["override1"]["id"],
                                  released_utc="2026-08-01T12:06:00Z")
    assert released["state"] == "RELEASED"
    assert released["active_mode"] is None
    assert released["released_utc"].startswith("2026-08-01T12:06:00")

    accepted = api.create_override(_later_request_payload(plant), plant["mco_headers"])
    second = validate_success(accepted, 201)
    assert second["state"] == "PENDING"
    assert second["active_mode"] is None
    assert second["authorized_by_operator_id"] is None

    overrides, meta = validate_paginated(
        api.list_overrides(plant["mco_headers"],
                           params={"channel_id": plant["ch1"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {o["id"] for o in overrides} == {plant["override1"]["id"], second["id"]}
