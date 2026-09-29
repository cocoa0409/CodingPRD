"""Transitive cascades: one write, many records the caller never mentioned.

Two entry points are exercised. A transmitter power reduction runs the whole of
Cascade A — regulatory filing, derated bit pool, the channel waterfall, channel
posture and air status, the playlist elements and finally the spot ledger. An
asset retraction runs Cascade B — the clearance axis of the unaired elements,
the owning playlist's arm state, and the credit on the order behind the
commercial.
"""
from test_helpers import fixtures as fx
from test_helpers import (
    assert_bandwidth_conservation,
    assert_spot_count_conservation,
    item_by_sequence,
    validate_paginated,
    validate_success,
)

_MUX_OVERRIDES = {
    "total_capacity_kbps": 20000,
    "pilot_reserved_kbps": 500,
    "live_encoder_units_total": 2,
}
_CH1_OVERRIDES = {
    "resolution_class": "SD_480I",
    "requested_bitrate_kbps": 6000,
    "floor_bitrate_kbps": 2000,
    "priority_rank": 1,
}


def _passed_asset(plant: dict, seconds: int, resolution_class: str) -> dict:
    return fx.setup_qc_passed_asset(
        plant, seconds,
        asset_overrides={"required_resolution_class": resolution_class},
    )


# ===========================================================================
# Cascade A — a power reduction from FULL_POWER to 40 percent.
# ===========================================================================

def _setup_three_channel_plant() -> dict:
    """FAC-1 at FULL_POWER carrying MUX-A and three ACTIVE channels.

    At derate 1.00 the pool is 19500 kbps: floors 2000 + 3000 + 5000 fit, the
    remainder of 9500 is shared by weight and channel 12.3 is carried at 8911.
    """
    plant = fx.setup_base_plant(
        with_subchannel=False,
        mux_overrides=dict(_MUX_OVERRIDES),
        ch1_overrides=dict(_CH1_OVERRIDES),
    )
    eng = plant["eng_headers"]
    mux = fx.read_multiplex(plant["multiplex"]["id"], eng)
    plant["ch2"] = fx.create_subchannel(
        eng, mux["id"], mux["version"], plant["ch1"]["id"],
        call_sign="WXYZ-DT2", channel_number="12.2", resolution_class="SD_480I",
        requested_bitrate_kbps=9000, floor_bitrate_kbps=3000, priority_rank=2,
    )
    mux = fx.read_multiplex(plant["multiplex"]["id"], eng)
    plant["ch3"] = fx.create_subchannel(
        eng, mux["id"], mux["version"], plant["ch1"]["id"],
        call_sign="WXYZ-DT3", channel_number="12.3", resolution_class="HD_720P",
        requested_bitrate_kbps=12000, floor_bitrate_kbps=5000, priority_rank=3,
    )
    return plant


def _setup_on_air_day_on_channel_three() -> dict:
    """The three-channel plant with 12.3 on air, element one PLAYING at 12:20.

    ORD-4A sells three spots for 1500 cents, so the per-spot rate is exactly 500
    cents. Two of those spots sit on the day at 12:29:00Z and 12:29:30Z.
    """
    plant = _setup_three_channel_plant()
    channel = plant["ch3"]
    order = fx.create_order(
        plant, channel_id=channel["id"], advertiser_name="Acme",
        order_reference="ORD-4A", ordered_spots=3, unit_duration_seconds=30,
        rate_cents_total=1500, daypart="DAYTIME", priority_class="PREEMPTIBLE",
        makegood_deadline_utc="2026-08-10T00:00:00Z",
    )
    programme = _passed_asset(plant, 1740, "HD_720P")
    spot = _passed_asset(plant, 30, "HD_720P")
    playlist = fx.ingest(plant, [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": programme["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1740, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:29:00Z",
         "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:29:30Z",
         "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
    ], channel_id=channel["id"], window_duration_seconds=1800)
    rows = fx.list_items(playlist["id"], plant["mco_headers"])

    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.set_air_status(plant, channel["id"], "ON_AIR")
    playlist = fx.drive_playlist(plant, playlist["id"], "ON_AIR")

    item1 = item_by_sequence(rows, 1)
    fx.cue_item(plant, item1["id"], "2026-08-01T12:00:00Z")
    fx.start_item(plant, item1["id"], "2026-08-01T12:00:00Z")
    fx.set_clock("2026-08-01T12:20:00Z")
    return {
        "plant": plant,
        "order": order,
        "playlist": playlist,
        "item1": item1,
        "item2": item_by_sequence(rows, 2),
        "item3": item_by_sequence(rows, 3),
    }


def _reduce_to_forty_percent(api, plant: dict) -> dict:
    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "REDUCED_POWER", "power_pct": 40,
         "reason": "transmission line arc detected"},
        plant["eng_headers"],
    )
    return validate_success(resp)


def test_power_reduction_publishes_the_low_derate_and_raises_a_pending_filing(api):
    """A reduction to 40 percent republishes derate 0.50 and files a POWER_REDUCTION obligation.

    PRD §3.1: "Reducing power writes `current_power_pct` from the supplied `power_pct` and publishes a new `derate_factor`, which is 0.75 when `power_pct` is at least 50 and 0.50 when it is below 50."

    PRD §3.1: "a reduction to below 80 percent of licensed power creates a `POWER_REDUCTION` notification in status `PENDING`, with `triggering_utc` set to the logical clock instant of the change, `due_utc` set to 24 hours after that instant, and `observed_power_pct` recording the percentage observed at the triggering event; the transmitter's `notification_pending_count` rises by one."

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    transmitter = _reduce_to_forty_percent(api, plant)
    assert transmitter["operational_state"] == "REDUCED_POWER"
    assert transmitter["current_power_pct"] == 40
    assert float(transmitter["derate_factor"]) == 0.50
    assert transmitter["notification_pending_count"] == 1

    resp = api.list_transmitter_notifications(
        plant["transmitter"]["id"], plant["compliance_headers"],
        params={"status": "PENDING"},
    )
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert len(rows) == 1
    filing = rows[0]
    assert filing["kind"] == "POWER_REDUCTION"
    assert filing["status"] == "PENDING"
    assert filing["observed_power_pct"] == 40
    assert filing["triggering_utc"].startswith("2026-08-01T12:20:00")
    assert filing["due_utc"].startswith("2026-08-02T12:20:00")


def test_the_derated_pool_starves_the_lowest_priority_channel_and_reslices_the_rest(api):
    """The 9500 kbps pool grants two floors, starves the third and re-slices the remainder.

    PRD §3.2: "take `total_capacity_kbps`, multiply by the parent transmitter's current `derate_factor`, truncate the product downward to a whole kilobit, subtract `pilot_reserved_kbps`, and floor the result at 0."

    PRD §3.2: "If the floor does not fit, the channel's `allocation_state` becomes `STARVED`, its `allocated_bitrate_kbps` is set to 0, and it is excluded from steps three through five entirely."

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    _reduce_to_forty_percent(api, plant)

    multiplex = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert multiplex["effective_capacity_kbps"] == 9500
    assert multiplex["assigned_kbps"] == 9500
    assert multiplex["available_kbps"] == 0
    assert multiplex["starved_channel_count"] == 1
    assert_bandwidth_conservation(multiplex)

    ch1 = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    ch2 = fx.read_channel(plant["ch2"]["id"], plant["eng_headers"])
    ch3 = fx.read_channel(plant["ch3"]["id"], plant["eng_headers"])
    assert ch1["allocated_bitrate_kbps"] == 3800
    assert ch2["allocated_bitrate_kbps"] == 5700
    assert ch3["allocated_bitrate_kbps"] == 0
    assert ch3["allocation_state"] == "STARVED"


def test_the_starved_channel_drops_to_bars_and_tone_while_its_siblings_only_degrade(api):
    """Starvation suspends the channel it hits; reduced power degrades the two that survive.

    PRD §3.3: "First, `posture` is `SUSPENDED` if the channel's `allocation_state` is `STARVED` or its transmitter's `operational_state` is `OFF_AIR`."

    PRD §3.3: "Otherwise, fourth, it is `DEGRADED` if the number of open faults with `severity` `MAJOR` is at least two, or if the transmitter's `operational_state` is `REDUCED_POWER`; **exactly two major faults already degrade the channel**, one does not, and reduced transmitter power degrades every channel it carries on its own with no faults at all."

    PRD §3.1: "Channels leaving `SUSPENDED` posture have `air_status` restored from `BARS_AND_TONE` to `ON_AIR`, but only when the channel's playlist is itself `ON_AIR`"

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    _reduce_to_forty_percent(api, plant)

    ch3 = fx.read_channel(plant["ch3"]["id"], plant["mco_headers"])
    assert ch3["posture"] == "SUSPENDED"
    assert ch3["air_status"] == "BARS_AND_TONE"

    for surviving in ("ch1", "ch2"):
        channel = fx.read_channel(plant[surviving]["id"], plant["mco_headers"])
        assert channel["posture"] == "DEGRADED"


def test_the_derate_truncates_the_playing_element_and_preempts_the_two_spots(api):
    """The element on air since 12:00 is cut at 12:20; both booked spots never air.

    PRD §3.6: "Truncation also arrives without a direct call — as hop three of the override cut-in cascade, as hop five of the transmitter cascade, and as the consequence of a hard-cut backtiming plan."

    PRD §3.6: "Its `measured_duration_seconds` is written as the whole seconds between `actual_start_utc` and the event instant"

    PRD §3.6: "**Preemption** is never requested directly; it arrives from hop five of the transmitter cascade, from hop three of the override cut-in cascade, or from a channel being taken from `ON_AIR` to `DARK`, and it applies to elements in `SCHEDULED` or `CUED` while the owning playlist is `ON_AIR`."

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    _reduce_to_forty_percent(api, plant)

    item1 = fx.read_item(scn["item1"]["id"], plant["mco_headers"])
    assert item1["playout_status"] == "TRUNCATED"
    assert item1["measured_duration_seconds"] == 1200

    for key in ("item2", "item3"):
        spot_element = fx.read_item(scn[key]["id"], plant["mco_headers"])
        assert spot_element["playout_status"] == "PREEMPTED"


def test_the_as_run_log_marks_the_cascade_rows_as_system_written(api):
    """One truncation row and two preemption rows arrive with source SYSTEM, not AUTOMATION.

    PRD §3.7: "the sources are `AUTOMATION`, `OPERATOR` and `SYSTEM`, where `SYSTEM` marks entries written by a cascade rather than by a direct call."

    PRD §3.6: "It appends a preemption entry with `source` `SYSTEM`"

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    _reduce_to_forty_percent(api, plant)

    rows = fx.list_as_run(scn["playlist"]["id"], plant["compliance_headers"])
    truncations = [r for r in rows if r["event_kind"] == "TRUNCATION"]
    preemptions = [r for r in rows if r["event_kind"] == "PREEMPTION"]
    assert len(truncations) == 1
    assert len(preemptions) == 2
    for row in truncations + preemptions:
        assert row["source"] == "SYSTEM"


def test_the_derate_leaves_the_two_variance_figures_disagreeing(api):
    """The booked tail is gone from both figures, but only the as-run one sees the short air.

    PRD §3.5: "`projected_end_variance_seconds` is the forward-looking figure: sum `scheduled_duration_seconds` over every item of the playlist whose `playout_status` is not `SKIPPED` and not `PREEMPTED`, then subtract `window_duration_seconds`."

    PRD §3.5: "`asrun_end_variance_seconds` is the chronological figure: walk the items in `sequence_number` ascending order accumulating, for each, its `measured_duration_seconds` when its `playout_status` is `PLAYED` or `TRUNCATED`, zero when its `playout_status` is `SKIPPED` or `PREEMPTED`, and its `scheduled_duration_seconds` in every other case; then subtract `window_duration_seconds`."

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    _reduce_to_forty_percent(api, plant)

    playlist = fx.read_playlist(scn["playlist"]["id"], plant["mco_headers"])
    assert playlist["projected_end_variance_seconds"] == -60
    assert playlist["asrun_end_variance_seconds"] == -600


def test_the_last_hop_credits_both_preempted_spots_at_the_exact_per_spot_rate(api):
    """1500 cents over three spots is exactly 500 each, so two preemptions accrue 1000.

    PRD §2.11: "When a cut-in or a capacity derate preempts one scheduled spot, `scheduled_spots` falls by one, `credited_spots` rises by one, and `credit_accrued_cents` rises by the rounded per-spot figure."

    PRD §3.9: "It leaves `OPEN` for `PARTIALLY_CREDITED` on any credit accrual — an element preempted, skipped or truncated, the transmitter cascade's spot hop, the asset retraction cascade's spot hop, the override cut-in cascade's spot hop, or the close settlement — whenever the sum of `credited_spots` and `short_aired_spots` is strictly greater than zero and strictly less than `ordered_spots`."

    Design: Difficulty/transitive_cascade/power_derate_cascades_six_hops_to_spot_credit
    """
    scn = _setup_on_air_day_on_channel_three()
    plant = scn["plant"]

    _reduce_to_forty_percent(api, plant)

    order = fx.read_order(scn["order"]["id"], plant["traffic_headers"])
    assert order["credited_spots"] == 2
    assert order["scheduled_spots"] == 0
    assert order["aired_spots"] == 0
    assert order["short_aired_spots"] == 0
    assert order["unplaced_spots"] == 1
    assert order["credit_accrued_cents"] == 1000
    assert order["status"] == "PARTIALLY_CREDITED"
    assert_spot_count_conservation(order)


# ===========================================================================
# Cascade B — an advertiser pulls the creative behind an armed commercial.
# ===========================================================================

def _setup_armed_day_with_one_sold_spot() -> dict:
    """An armed half-hour day on a dark channel: one programme plus one sold spot.

    ORD-4B sells three spots for 1000 cents, so the per-spot rate is the exact
    third of that figure and only one of the three spots is placed on the day.
    """
    plant = fx.setup_base_plant(
        with_subchannel=False,
        mux_overrides=dict(_MUX_OVERRIDES),
        ch1_overrides=dict(_CH1_OVERRIDES),
    )
    channel = plant["ch1"]
    order = fx.create_order(
        plant, channel_id=channel["id"], advertiser_name="Beta Motors",
        order_reference="ORD-4B", ordered_spots=3, unit_duration_seconds=30,
        rate_cents_total=1000, daypart="PRIME", priority_class="PREEMPTIBLE",
        makegood_deadline_utc="2026-08-10T00:00:00Z",
    )
    programme = _passed_asset(plant, 1770, "SD_480I")
    creative = _passed_asset(plant, 30, "SD_480I")
    playlist = fx.ingest(plant, [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": programme["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1770, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": creative["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:29:30Z",
         "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
    ], channel_id=channel["id"], window_duration_seconds=1800)
    rows = fx.list_items(playlist["id"], plant["mco_headers"])

    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    playlist = fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T10:00:00Z")
    return {
        "plant": plant,
        "order": order,
        "creative": creative,
        "playlist": playlist,
        "item1": item_by_sequence(rows, 1),
        "item2": item_by_sequence(rows, 2),
    }


def _retract_the_creative(api, scn: dict) -> dict:
    plant = scn["plant"]
    resp = api.retract_asset(
        scn["creative"]["id"],
        {"reason": "advertiser pulled the creative"},
        plant["pd_headers"],
    )
    return validate_success(resp)


def test_retracting_the_creative_blocks_the_spot_and_disarms_the_whole_day(api):
    """One blocked element is enough to hand an armed day back to traffic.

    PRD §3.4: "Retraction is the entry point of a three-hop cascade. First, every playlist item referencing the asset whose `playout_status` is `SCHEDULED` or `CUED` has its `clearance_status` flipped to `BLOCKED`."

    PRD §3.4: "Second, caused by that flip, each owning playlist increments `blocked_item_count` and, when its `status` is `VALIDATED` or `ARMED`, reverts to `IMPORTED` with `armed_at_utc` cleared."

    Design: Difficulty/transitive_cascade/asset_retract_cascades_three_hops_and_disarms_playlist
    """
    scn = _setup_armed_day_with_one_sold_spot()
    plant = scn["plant"]
    assert scn["playlist"]["status"] == "ARMED"

    asset = _retract_the_creative(api, scn)
    assert asset["status"] == "RETRACTED"

    spot_element = fx.read_item(scn["item2"]["id"], plant["mco_headers"])
    assert spot_element["clearance_status"] == "BLOCKED"
    assert spot_element["playout_status"] == "SCHEDULED"

    programme_element = fx.read_item(scn["item1"]["id"], plant["mco_headers"])
    assert programme_element["clearance_status"] == "CLEARED"

    playlist = fx.read_playlist(scn["playlist"]["id"], plant["mco_headers"])
    assert playlist["status"] == "IMPORTED"
    assert playlist["armed_at_utc"] is None
    assert playlist["blocked_item_count"] == 1


def test_the_blocked_spot_accrues_a_rounded_third_of_the_order_value(api):
    """1000 cents over three spots rounds half up to 333 cents for the one blocked spot.

    PRD §3.4: "Third, also caused by that flip, every newly blocked item that carries a `spot_order_id` moves one spot on that order from `scheduled_spots` to `credited_spots`, adds the full per-spot credit to `credit_accrued_cents`, and refreshes the order's `status` to `PARTIALLY_CREDITED` or `CLOSED_WITH_CREDIT` as described in §3.9."

    PRD §3.9: "The per-spot rate is the order's `rate_cents_total` divided by its `ordered_spots`, and **that quotient is kept as an exact value and is deliberately not rounded at this stage**."

    PRD §2.11: "`unplaced_spots` absorbs the difference between `ordered_spots` and the number of playlist items linked to the order"

    Design: Difficulty/transitive_cascade/asset_retract_cascades_three_hops_and_disarms_playlist
    """
    scn = _setup_armed_day_with_one_sold_spot()
    plant = scn["plant"]

    _retract_the_creative(api, scn)

    order = fx.read_order(scn["order"]["id"], plant["traffic_headers"])
    assert order["credited_spots"] == 1
    assert order["scheduled_spots"] == 0
    assert order["unplaced_spots"] == 2
    assert order["credit_accrued_cents"] == 333
    assert order["status"] == "PARTIALLY_CREDITED"
    assert_spot_count_conservation(order)
