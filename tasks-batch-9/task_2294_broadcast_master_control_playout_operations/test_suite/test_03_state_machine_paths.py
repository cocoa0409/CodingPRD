"""Non-linear state-machine paths through the Broadcast Master Control API.

Two independent state graphs are exercised here. A playlist element carries two
orthogonal axes — the automation axis (`playout_status`) and the content axis
(`clearance_status`) — and an element is driven to a coordinate that only a
two-dimensional model can hold. An emergency override carries a genuine
two-node cycle, `ACTIVE_CRAWL` <-> `ACTIVE_CUTIN`, whose second visit to the
crawl state must not undo the irreversible cut-in side effects.
"""
from test_helpers import fixtures as fx
from test_helpers import item_by_sequence, validate_success

_MUX_OVERRIDES = {
    "total_capacity_kbps": 20000,
    "pilot_reserved_kbps": 500,
    "live_encoder_units_total": 2,
}
_CH_OVERRIDES = {
    "resolution_class": "SD_480I",
    "requested_bitrate_kbps": 6000,
    "floor_bitrate_kbps": 2000,
    "priority_rank": 1,
}
_CRAWL_TEXT = "Severe thunderstorm warning in effect for the viewing area."


def _plant_with_sd_channel() -> dict:
    """One FULL_POWER transmitter, one 20000 kbps multiplex, one ACTIVE SD channel."""
    return fx.setup_base_plant(
        with_subchannel=False,
        mux_overrides=dict(_MUX_OVERRIDES),
        ch1_overrides=dict(_CH_OVERRIDES),
    )


def _passed_sd_asset(plant: dict, seconds: int) -> dict:
    """An SD_480I asset delivered clean and graded PASS on an ingest report."""
    return fx.setup_qc_passed_asset(
        plant, seconds, asset_overrides={"required_resolution_class": "SD_480I"}
    )


def _program_item(sequence_number: int, asset_id: str, start_utc: str,
                  seconds: int) -> dict:
    return {
        "sequence_number": sequence_number,
        "element_kind": "PROGRAM",
        "asset_id": asset_id,
        "scheduled_start_utc": start_utc,
        "scheduled_duration_seconds": seconds,
        "max_trim_seconds": 0,
    }


def _ingest_half_hour_day(plant: dict, items: list) -> tuple:
    playlist = fx.ingest(plant, items, channel_id=plant["ch1"]["id"],
                         window_duration_seconds=1800)
    return playlist, fx.list_items(playlist["id"], plant["mco_headers"])


def _take_day_to_air(plant: dict, playlist_id: str) -> dict:
    """Validate, arm, light the channel at 12:00:00Z and hand the day to automation."""
    fx.drive_playlist(plant, playlist_id, "VALIDATED")
    fx.drive_playlist(plant, playlist_id, "ARMED")
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    return fx.drive_playlist(plant, playlist_id, "ON_AIR")


# ===========================================================================
# A playlist element holding CUED on the automation axis and BLOCKED on the
# clearance axis at the same time.
# ===========================================================================

def _setup_cued_second_element() -> dict:
    """An on-air two-programme day whose second element is CUED out of order."""
    plant = _plant_with_sd_channel()
    asset_a = _passed_sd_asset(plant, 900)
    asset_b = _passed_sd_asset(plant, 900)
    playlist, rows = _ingest_half_hour_day(plant, [
        _program_item(1, asset_a["id"], "2026-08-01T12:00:00Z", 900),
        _program_item(2, asset_b["id"], "2026-08-01T12:15:00Z", 900),
    ])
    playlist = _take_day_to_air(plant, playlist["id"])
    item1 = item_by_sequence(rows, 1)
    item2 = item_by_sequence(rows, 2)
    fx.cue_item(plant, item2["id"], "2026-08-01T12:00:00Z")
    return {
        "plant": plant,
        "asset_b": asset_b,
        "playlist": playlist,
        "item1": item1,
        "item2": item2,
    }


def test_retracting_an_asset_blocks_a_cued_element_without_resetting_its_playout_axis(api):
    """A CUED element keeps its automation axis while its clearance axis is blocked.

    PRD §3.4: "Retraction is the entry point of a three-hop cascade. First, every playlist item referencing the asset whose `playout_status` is `SCHEDULED` or `CUED` has its `clearance_status` flipped to `BLOCKED`."

    PRD §3.6: "`playout_status` is the automation axis, driven only by playout events and cascades. `clearance_status` is the content axis, driven only by asset lifecycle events and waivers and **never by automation events**."

    Design: Difficulty/non_linear_state_machine/playlist_item_holds_cued_playout_and_blocked_clearance_simultaneously
    """
    scn = _setup_cued_second_element()
    plant = scn["plant"]

    resp = api.retract_asset(
        scn["asset_b"]["id"],
        {"reason": "rights window withdrawn by the distributor"},
        plant["pd_headers"],
    )
    asset = validate_success(resp)
    assert asset["status"] == "RETRACTED"

    cued = fx.read_item(scn["item2"]["id"], plant["mco_headers"])
    assert cued["playout_status"] == "CUED"
    assert cued["clearance_status"] == "BLOCKED"

    untouched = fx.read_item(scn["item1"]["id"], plant["mco_headers"])
    assert untouched["playout_status"] == "SCHEDULED"
    assert untouched["clearance_status"] == "CLEARED"


def test_retraction_of_a_cued_element_leaves_the_on_air_playlist_on_air(api):
    """Only a VALIDATED or ARMED playlist reverts; an ON_AIR day keeps its state.

    PRD §3.4: "Second, caused by that flip, each owning playlist increments `blocked_item_count` and, when its `status` is `VALIDATED` or `ARMED`, reverts to `IMPORTED` with `armed_at_utc` cleared."

    Design: Difficulty/non_linear_state_machine/playlist_item_holds_cued_playout_and_blocked_clearance_simultaneously
    """
    scn = _setup_cued_second_element()
    plant = scn["plant"]
    assert scn["playlist"]["status"] == "ON_AIR"

    resp = api.retract_asset(
        scn["asset_b"]["id"],
        {"reason": "rights window withdrawn by the distributor"},
        plant["pd_headers"],
    )
    validate_success(resp)

    playlist = fx.read_playlist(scn["playlist"]["id"], plant["mco_headers"])
    assert playlist["blocked_item_count"] == 1
    assert playlist["status"] == "ON_AIR"
    assert playlist["armed_at_utc"] is not None

    channel = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])
    assert channel["air_status"] == "ON_AIR"
    assert channel["posture"] == "NORMAL"


# ===========================================================================
# The override cycle CRAWL -> CUT_IN -> CRAWL -> RELEASED on one channel.
# ===========================================================================

def _setup_pending_severe_weather_override() -> dict:
    """An on-air day with element one PLAYING and a PENDING crawl request at 12:05.

    Element one is booked 12:00:00Z-12:20:00Z and element two 12:20:00Z-12:30:00Z,
    so element two's booked span lies wholly inside the override's expected span
    of 1800 seconds measured from 12:05:00Z.
    """
    plant = _plant_with_sd_channel()
    asset_a = _passed_sd_asset(plant, 1200)
    asset_b = _passed_sd_asset(plant, 600)
    playlist, rows = _ingest_half_hour_day(plant, [
        _program_item(1, asset_a["id"], "2026-08-01T12:00:00Z", 1200),
        _program_item(2, asset_b["id"], "2026-08-01T12:20:00Z", 600),
    ])
    playlist = _take_day_to_air(plant, playlist["id"])
    item1 = item_by_sequence(rows, 1)
    item2 = item_by_sequence(rows, 2)
    fx.cue_item(plant, item1["id"], "2026-08-01T12:00:00Z")
    fx.start_item(plant, item1["id"], "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:05:00Z")
    override = fx.request_override(
        plant, "CRAWL", channel_id=plant["ch1"]["id"],
        requested_start_utc="2026-08-01T12:05:00Z",
        expected_duration_seconds=1800,
        crawl_text=_CRAWL_TEXT,
    )
    return {
        "plant": plant,
        "playlist": playlist,
        "item1": item1,
        "item2": item2,
        "override": override,
    }


def _activate(api, scn: dict, override_mode: str, activated_utc: str) -> dict:
    """Authorize the override in the given mode; the director is not the requester."""
    plant = scn["plant"]
    payload = {
        "authorized_by_operator_id": plant["pd"]["id"],
        "override_mode": override_mode,
        "activated_utc": activated_utc,
    }
    if override_mode == "CRAWL":
        payload["crawl_text"] = _CRAWL_TEXT
    resp = api.activate_override(scn["override"]["id"], payload, plant["pd_headers"])
    return validate_success(resp)


def test_escalating_a_crawl_to_a_cutin_truncates_the_playing_element_and_preempts_the_next(api):
    """The crawl overlays nothing away; the escalation to a cut-in rewrites the playlist.

    PRD §3.8: "An override-in entry sourced `OPERATOR` is appended against the currently playing element of the channel's on-air playlist when one exists. No element is truncated and no element is preempted."

    PRD §3.8: "Hop three, caused by hop two, rewrites the playlist: the element that was `PLAYING` on the channel's on-air playlist flips to `TRUNCATED` with its `measured_duration_seconds` set to the whole seconds from its `actual_start_utc` to the current logical time; and **every element whose own booked span, from its `scheduled_start_utc` up to but not including that instant plus its `scheduled_duration_seconds`, lies entirely inside the override's expected span, from the current logical time up to but not including that instant plus `expected_duration_seconds`, and whose `playout_status` is `SCHEDULED` or `CUED`, flips to `PREEMPTED`**."

    Design: Difficulty/non_linear_state_machine/emergency_override_crawl_cutin_crawl_cycle_does_not_resurrect_items
    """
    scn = _setup_pending_severe_weather_override()
    plant = scn["plant"]

    crawl = _activate(api, scn, "CRAWL", "2026-08-01T12:05:00Z")
    assert crawl["state"] == "ACTIVE_CRAWL"
    assert crawl["active_mode"] == "CRAWL"
    assert crawl["truncated_item_count"] == 0
    assert crawl["preempted_item_count"] == 0

    cutin = _activate(api, scn, "CUT_IN", "2026-08-01T12:05:00Z")
    assert cutin["state"] == "ACTIVE_CUTIN"
    assert cutin["active_mode"] == "CUT_IN"
    assert cutin["truncated_item_count"] == 1
    assert cutin["preempted_item_count"] == 1

    channel = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])
    assert channel["air_status"] == "EAS_OVERRIDE"
    assert channel["posture"] == "EMERGENCY"

    item1 = fx.read_item(scn["item1"]["id"], plant["mco_headers"])
    assert item1["playout_status"] == "TRUNCATED"
    assert item1["measured_duration_seconds"] == 300
    item2 = fx.read_item(scn["item2"]["id"], plant["mco_headers"])
    assert item2["playout_status"] == "PREEMPTED"


def test_relaxing_the_cutin_back_to_a_crawl_keeps_the_truncation_and_the_preemption(api):
    """The second visit to ACTIVE_CRAWL flips active_mode back and restores nothing else.

    PRD §3.8: "**De-escalating** a cut-in back to a crawl sets `active_mode` to `CRAWL` and returns the channel's `air_status` from `EAS_OVERRIDE` to `ON_AIR` while `posture` stays `EMERGENCY`; it requires a non-null `crawl_text`"

    PRD §3.8: "**Elements already truncated or preempted are not restored**: there is no compensation on de-escalation."

    Design: Difficulty/non_linear_state_machine/emergency_override_crawl_cutin_crawl_cycle_does_not_resurrect_items
    """
    scn = _setup_pending_severe_weather_override()
    plant = scn["plant"]
    _activate(api, scn, "CRAWL", "2026-08-01T12:05:00Z")
    _activate(api, scn, "CUT_IN", "2026-08-01T12:05:00Z")

    fx.set_clock("2026-08-01T12:08:00Z")
    relaxed = _activate(api, scn, "CRAWL", "2026-08-01T12:08:00Z")
    assert relaxed["state"] == "ACTIVE_CRAWL"
    assert relaxed["active_mode"] == "CRAWL"
    assert relaxed["truncated_item_count"] == 1
    assert relaxed["preempted_item_count"] == 1

    channel = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])
    assert channel["air_status"] == "ON_AIR"
    assert channel["posture"] == "EMERGENCY"

    item1 = fx.read_item(scn["item1"]["id"], plant["mco_headers"])
    assert item1["playout_status"] == "TRUNCATED"
    assert item1["measured_duration_seconds"] == 300
    item2 = fx.read_item(scn["item2"]["id"], plant["mco_headers"])
    assert item2["playout_status"] == "PREEMPTED"


def test_releasing_the_override_after_the_crawl_cutin_crawl_cycle_restores_the_channel(api):
    """The terminal release clears EMERGENCY but keeps every irreversible count.

    PRD §3.8: "A release writes `released_utc` at the current logical time and sets `active_mode` to null. Releasing a crawl recomputes `posture`, which clears `EMERGENCY` and falls back to `DEGRADED_CRITICAL`, `DEGRADED` or `NORMAL` according to the channel's open faults and its transmitter's state."

    PRD §2.12: "Releasing an override hands the channel back to its playlist, but truncated and preempted elements stay truncated and preempted, and the credits they accrued stay accrued"

    Design: Difficulty/non_linear_state_machine/emergency_override_crawl_cutin_crawl_cycle_does_not_resurrect_items
    """
    scn = _setup_pending_severe_weather_override()
    plant = scn["plant"]
    _activate(api, scn, "CRAWL", "2026-08-01T12:05:00Z")
    _activate(api, scn, "CUT_IN", "2026-08-01T12:05:00Z")
    fx.set_clock("2026-08-01T12:08:00Z")
    _activate(api, scn, "CRAWL", "2026-08-01T12:08:00Z")

    fx.set_clock("2026-08-01T12:10:00Z")
    resp = api.release_override(
        scn["override"]["id"],
        {"released_utc": "2026-08-01T12:10:00Z"},
        plant["pd_headers"],
    )
    released = validate_success(resp)
    assert released["state"] == "RELEASED"
    assert released["active_mode"] is None
    assert released["released_utc"].startswith("2026-08-01T12:10:00")
    assert released["truncated_item_count"] == 1
    assert released["preempted_item_count"] == 1

    channel = fx.read_channel(plant["ch1"]["id"], plant["mco_headers"])
    assert channel["air_status"] == "ON_AIR"
    assert channel["posture"] == "NORMAL"

    item1 = fx.read_item(scn["item1"]["id"], plant["mco_headers"])
    assert item1["playout_status"] == "TRUNCATED"
    item2 = fx.read_item(scn["item2"]["id"], plant["mco_headers"])
    assert item2["playout_status"] == "PREEMPTED"


def test_the_two_variance_figures_disagree_after_the_override_cycle(api):
    """The projected figure trusts the booked tail; the as-run figure sees 300 aired seconds.

    PRD §3.5: "`projected_end_variance_seconds` is the forward-looking figure: sum `scheduled_duration_seconds` over every item of the playlist whose `playout_status` is not `SKIPPED` and not `PREEMPTED`, then subtract `window_duration_seconds`."

    PRD §3.5: "`asrun_end_variance_seconds` is the chronological figure: walk the items in `sequence_number` ascending order accumulating, for each, its `measured_duration_seconds` when its `playout_status` is `PLAYED` or `TRUNCATED`, zero when its `playout_status` is `SKIPPED` or `PREEMPTED`, and its `scheduled_duration_seconds` in every other case; then subtract `window_duration_seconds`."

    Design: Difficulty/non_linear_state_machine/emergency_override_crawl_cutin_crawl_cycle_does_not_resurrect_items
    """
    scn = _setup_pending_severe_weather_override()
    plant = scn["plant"]
    _activate(api, scn, "CRAWL", "2026-08-01T12:05:00Z")
    _activate(api, scn, "CUT_IN", "2026-08-01T12:05:00Z")
    fx.set_clock("2026-08-01T12:08:00Z")
    _activate(api, scn, "CRAWL", "2026-08-01T12:08:00Z")
    fx.set_clock("2026-08-01T12:10:00Z")
    resp = api.release_override(
        scn["override"]["id"],
        {"released_utc": "2026-08-01T12:10:00Z"},
        plant["pd_headers"],
    )
    validate_success(resp)

    playlist = fx.read_playlist(scn["playlist"]["id"], plant["mco_headers"])
    assert playlist["projected_end_variance_seconds"] == -600
    assert playlist["asrun_end_variance_seconds"] == -1500
