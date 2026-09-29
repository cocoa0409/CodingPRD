"""Composed-formula behaviour: backtiming plan selection, per-spot credit
rounding order, and the five-step bitrate waterfall.

Each test builds its own world from an empty database through PRD endpoints
only, so the pinned arithmetic below is reproducible from the logical clock's
default value.
"""
from test_helpers import (
    assert_bandwidth_conservation,
    assert_feed_window,
    assert_multiplex,
    assert_playlist_item,
    assert_spot_count_conservation,
    assert_spot_order,
    assert_tail_seconds_conservation,
    factories,
    item_by_sequence,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# Instance 1 scenario — the trim-tail broadcast day
#
# MUX-A total 20000 with pilot 500 at derate 1.00 gives an effective pool of
# 19500 kbps, so channel 12.1 (floor 2000, request 6000) is granted 6000 and
# can be lit. The day is 1690 + 10 + 60 + 40 == 1800 seconds against a 1800
# second window, so the projected end variance is 0 and the day arms.
# ---------------------------------------------------------------------------

_MUX_20000 = {"total_capacity_kbps": 20000, "pilot_reserved_kbps": 500,
              "live_encoder_units_total": 2}
_CH_SD = {"resolution_class": "SD_480I", "requested_bitrate_kbps": 6000,
          "floor_bitrate_kbps": 2000, "priority_rank": 1}

_JOIN_UTC = "2026-08-01T12:29:00Z"
_BREAKAWAY_UTC = "2026-08-01T12:45:00Z"
_PLAN_CLOCK_UTC = "2026-08-01T12:28:30Z"


def _setup_trim_tail_day():
    """Base plant + an ON_AIR day whose tail from sequence 2 is 110 seconds.

    Sequence 2 is the NETWORK_JOIN anchor (10 s, no trim), sequence 3 a PROMO
    of 60 s with max_trim_seconds 55 and sequence 4 an INTERSTITIAL of 40 s
    with max_trim_seconds 35. Nothing has been cued, so every element is still
    SCHEDULED and the whole 10 + 60 + 40 sits in the tail.
    """
    plant = fx.setup_base_plant(with_subchannel=False, mux_overrides=_MUX_20000,
                                ch1_overrides=_CH_SD)
    sd = {"required_resolution_class": "SD_480I"}
    asset_a = fx.setup_qc_passed_asset(plant, 1690, asset_overrides=sd)
    asset_p = fx.setup_qc_passed_asset(plant, 60, asset_overrides=sd)
    asset_i = fx.setup_qc_passed_asset(plant, 40, asset_overrides=sd)

    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": asset_a["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1690, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "NETWORK_JOIN",
         "scheduled_start_utc": "2026-08-01T12:28:10Z",
         "scheduled_duration_seconds": 10, "max_trim_seconds": 0},
        {"sequence_number": 3, "element_kind": "PROMO",
         "asset_id": asset_p["id"],
         "scheduled_start_utc": "2026-08-01T12:28:20Z",
         "scheduled_duration_seconds": 60, "max_trim_seconds": 55},
        {"sequence_number": 4, "element_kind": "INTERSTITIAL",
         "asset_id": asset_i["id"],
         "scheduled_start_utc": "2026-08-01T12:29:20Z",
         "scheduled_duration_seconds": 40, "max_trim_seconds": 35},
    ]
    playlist = fx.ingest(plant, items, window_duration_seconds=1800)
    plant["playlist"] = playlist

    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T11:55:00Z")
    fx.drive_playlist(plant, playlist["id"], "ON_AIR")
    fx.set_clock(_PLAN_CLOCK_UTC)
    plant["items"] = fx.list_items(playlist["id"], plant["mco_headers"])
    return plant


def _plan_window(api, plant, **overrides):
    payload = factories.create_feed_window_payload(
        plant["ch1"]["id"], 2, _JOIN_UTC, _BREAKAWAY_UTC,
        backtiming_mode="TOLERANT", guard_seconds=30, live_encoder_units=1,
        **overrides,
    )
    return api.create_feed_window(payload, plant["mco_headers"])


def test_tolerant_plan_over_a_long_tail_selects_trim_tail_for_the_whole_deficit(api):
    """The nested tolerance loses to the guard band, and the 80-second deficit fits the trimmable pool.

    PRD §3.7: "If the trimmable pool covers the deficit, the action is `TRIM_TAIL` with the trim equal to the whole deficit and no skips; the trim is consumed in ascending `sequence_number` order, each element giving the smaller of the remaining need and its own trimmable allowance."

    Design: Difficulty/combinatorial_formula/backtime_plan_trim_tail_selected_by_nested_min_max_over_five_inputs
    """
    plant = _setup_trim_tail_day()

    resp = _plan_window(api, plant)
    window = validate_success(resp, 201)
    assert_feed_window(window)

    assert window["plan_action"] == "TRIM_TAIL", (
        "remaining 30 less pending tail 110 is a slack of -80, more negative "
        "than the tolerance max(30, min(2, 15)) == 30, and the trimmable pool "
        "55 + 35 == 90 covers it"
    )
    assert window["state"] == "PLANNED"
    assert window["backtime_trim_seconds"] == 80
    assert window["backtime_pad_seconds"] == 0
    assert window["residual_dead_air_seconds"] == 0
    assert window["late_join_seconds"] == 0
    assert window["skipped_item_sequences"] == []
    assert window["plan_computed_utc"].startswith("2026-08-01T12:28:30"), (
        f"plan_computed_utc is written at the current logical time, got "
        f"{window['plan_computed_utc']!r}"
    )


def test_trim_tail_join_consumes_the_deficit_in_ascending_sequence_order(api):
    """The 80 seconds come 55 from sequence 3 and only the remaining 25 from sequence 4.

    PRD §3.7: "A `TRIM_TAIL` join reduces `scheduled_duration_seconds` and sets `trim_applied_seconds` on the trimmable tail elements in ascending `sequence_number` order, **never taking an element below its `scheduled_duration_seconds` less its `max_trim_seconds`**."

    Design: Difficulty/combinatorial_formula/backtime_plan_trim_tail_selected_by_nested_min_max_over_five_inputs
    """
    plant = _setup_trim_tail_day()
    window = validate_success(_plan_window(api, plant), 201)

    joined = validate_success(
        api.join_feed_window(window["id"], {}, plant["mco_headers"])
    )
    assert_feed_window(joined)
    assert joined["state"] == "JOINED"
    assert joined["plan_action"] == "TRIM_TAIL"
    assert joined["backtime_trim_seconds"] == 80

    items = fx.list_items(plant["playlist"]["id"], plant["mco_headers"])
    anchor = item_by_sequence(items, 2)
    promo = item_by_sequence(items, 3)
    interstitial = item_by_sequence(items, 4)
    for item in (anchor, promo, interstitial):
        assert_playlist_item(item)

    assert promo["trim_applied_seconds"] == 55, (
        "sequence 3 gives the smaller of the remaining need 80 and its own "
        "trimmable allowance min(60 - 1, 55) == 55"
    )
    assert promo["scheduled_duration_seconds"] == 5
    assert interstitial["trim_applied_seconds"] == 25, (
        "sequence 4 gives only the 25 seconds still needed, not an even split"
    )
    assert interstitial["scheduled_duration_seconds"] == 15
    assert anchor["trim_applied_seconds"] == 0, (
        "a NETWORK_JOIN element is neither trimmable nor skippable"
    )
    assert promo["playout_status"] == "SCHEDULED"
    assert interstitial["playout_status"] == "SCHEDULED"


def test_trim_tail_join_neither_destroys_nor_invents_scheduled_tail_seconds(api):
    """The pre-plan tail of 110 seconds reappears as 30 still scheduled plus the 80 trimmed.

    PRD §2.11: "For every executed backtiming plan, the pre-plan tail length — the sum of `scheduled_duration_seconds` over items at or after `anchor_sequence_number` whose `playout_status` is `SCHEDULED` or `CUED` at plan time — equals the tail seconds still scheduled after the plan, plus `backtime_trim_seconds`, plus the summed `scheduled_duration_seconds` of the items whose sequence numbers appear in `skipped_item_sequences`."

    Design: Difficulty/combinatorial_formula/backtime_plan_trim_tail_selected_by_nested_min_max_over_five_inputs
    """
    plant = _setup_trim_tail_day()
    pre_plan_tail = sum(
        item["scheduled_duration_seconds"] for item in plant["items"]
        if item["sequence_number"] >= 2
        and item["playout_status"] in ("SCHEDULED", "CUED")
    )
    assert pre_plan_tail == 110

    window = validate_success(_plan_window(api, plant), 201)
    joined = validate_success(
        api.join_feed_window(window["id"], {}, plant["mco_headers"])
    )

    items = fx.list_items(plant["playlist"]["id"], plant["mco_headers"])
    post_plan_tail = sum(
        item["scheduled_duration_seconds"] for item in items
        if item["sequence_number"] >= 2
        and item["playout_status"] in ("SCHEDULED", "CUED")
    )
    skipped_seconds = sum(
        item["scheduled_duration_seconds"] for item in items
        if item["sequence_number"] in joined["skipped_item_sequences"]
    )
    assert post_plan_tail == 30
    assert skipped_seconds == 0
    assert_tail_seconds_conservation(pre_plan_tail, post_plan_tail,
                                    joined["backtime_trim_seconds"],
                                    skipped_seconds)


# ---------------------------------------------------------------------------
# Instance 2 scenario — three spots against a rate that does not divide evenly
#
# ORD-2B sells 3 spots of 30 seconds for 1000 cents, so the per-spot rate is the
# exact rational 1000/3 cents. The day is 1710 + 30 + 30 + 30 == 1800 seconds
# against a 1800 second window, and hour 0 carries 90 seconds of commercials.
# ---------------------------------------------------------------------------

def _setup_three_spot_day():
    """Base plant + an ON_AIR day carrying three commercials on one order."""
    plant = fx.setup_base_plant(with_subchannel=False, mux_overrides=_MUX_20000,
                                ch1_overrides=_CH_SD)
    sd = {"required_resolution_class": "SD_480I"}
    asset_a = fx.setup_qc_passed_asset(plant, 1710, asset_overrides=sd)
    asset_b = fx.setup_qc_passed_asset(plant, 30, asset_overrides=sd)

    order = fx.create_order(
        plant, order_reference="ORD-2B", ordered_spots=3,
        unit_duration_seconds=30, rate_cents_total=1000, daypart="DAYTIME",
        priority_class="PREEMPTIBLE",
        makegood_deadline_utc="2026-08-10T00:00:00Z",
    )
    plant["order"] = order

    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": asset_a["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1710},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": asset_b["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:28:30Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": asset_b["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:29:00Z",
         "scheduled_duration_seconds": 30},
        {"sequence_number": 4, "element_kind": "COMMERCIAL",
         "asset_id": asset_b["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T12:29:30Z",
         "scheduled_duration_seconds": 30},
    ]
    playlist = fx.ingest(plant, items, window_duration_seconds=1800)
    plant["playlist"] = playlist

    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T11:55:00Z")
    fx.drive_playlist(plant, playlist["id"], "ON_AIR")
    plant["items"] = fx.list_items(playlist["id"], plant["mco_headers"])
    return plant


def _air_first_two_and_truncate_the_third(plant):
    """Sequence 2 airs in full, sequence 3 is truncated after 10 of its 30 seconds."""
    items = plant["items"]
    it1 = item_by_sequence(items, 1)
    it2 = item_by_sequence(items, 2)
    it3 = item_by_sequence(items, 3)

    fx.air_item(plant, it1, "2026-08-01T12:00:00Z", "2026-08-01T12:28:30Z", 1710)
    fx.cue_item(plant, it2["id"], "2026-08-01T12:28:30Z")
    fx.start_item(plant, it2["id"], "2026-08-01T12:28:30Z")
    fx.set_clock("2026-08-01T12:29:00Z")
    fx.end_item(plant, it2["id"], "2026-08-01T12:29:00Z", 30)
    fx.cue_item(plant, it3["id"], "2026-08-01T12:29:00Z")
    fx.start_item(plant, it3["id"], "2026-08-01T12:29:00Z")
    fx.set_clock("2026-08-01T12:29:10Z")
    fx.truncate_item(plant, it3["id"], "2026-08-01T12:29:10Z",
                     measured_duration_seconds=10)
    return item_by_sequence(items, 4)


def test_short_air_credit_is_rounded_to_a_whole_cent_on_its_own(api):
    """A twenty-second shortfall on an exact 1000/3 rate accrues 222 cents, not 222.22.

    PRD §3.9: "Each per-element credit is rounded to whole cents on its own, half-cent values rounding upward, and only then are the rounded figures summed."

    Design: Difficulty/combinatorial_formula/spot_credit_rounds_each_item_then_sums_555_not_556
    """
    plant = _setup_three_spot_day()
    _air_first_two_and_truncate_the_third(plant)

    order = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert_spot_order(order)
    assert order["credit_accrued_cents"] == 222, (
        "the truncated spot's credit is (1000/3) * 20 / 30 == 222.22..., "
        "rounded half up to 222 on its own"
    )
    assert order["aired_spots"] == 1, "a 30-second spot that ran 30 seconds aired in full"
    assert order["short_aired_spots"] == 1


def test_per_spot_credits_are_rounded_before_summing_to_555_not_556(api):
    """Rounding each of 0, 222.22 and 333.33 first gives 555; summing first would give 556.

    PRD §2.10: "The order is pinned: round each item, then sum. Summing exact rationals and rounding the total once at the end is wrong and can differ from the specified result by as much as one cent less than the number of spots involved."

    Design: Difficulty/combinatorial_formula/spot_credit_rounds_each_item_then_sums_555_not_556
    """
    plant = _setup_three_spot_day()
    it4 = _air_first_two_and_truncate_the_third(plant)

    fx.set_clock("2026-08-01T12:29:20Z")
    entry = validate_success(
        api.post_playout_event(
            it4["id"],
            factories.playout_event_payload("SKIP", "2026-08-01T12:29:20Z"),
            plant["mco_headers"],
        ),
        201,
    )
    assert entry["event_kind"] == "SKIP"

    item = fx.read_item(it4["id"], plant["mco_headers"])
    assert item["playout_status"] == "SKIPPED"

    order = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert order["credit_accrued_cents"] == 555, (
        "0 + 222 + 333 == 555 once each per-spot figure is rounded before the sum"
    )
    assert order["credit_accrued_cents"] != 556, (
        "556 is what summing the exact rationals 0 + 2000/9 + 1000/3 and "
        "rounding once at the end would produce"
    )


def test_spot_counter_identity_holds_after_the_per_item_credit_settlement(api):
    """One aired, one short-aired and one credited spot exhaust the order of three.

    PRD §2.11: "For every spot order, `ordered_spots` equals the sum of `scheduled_spots`, `aired_spots`, `short_aired_spots`, `credited_spots` and `unplaced_spots`."

    Design: Difficulty/combinatorial_formula/spot_credit_rounds_each_item_then_sums_555_not_556
    """
    plant = _setup_three_spot_day()
    it4 = _air_first_two_and_truncate_the_third(plant)

    fx.set_clock("2026-08-01T12:29:20Z")
    fx.skip_item(plant, it4["id"], "2026-08-01T12:29:20Z")

    order = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert_spot_order(order)
    assert order["aired_spots"] == 1
    assert order["short_aired_spots"] == 1
    assert order["credited_spots"] == 1
    assert order["scheduled_spots"] == 0
    assert order["unplaced_spots"] == 0
    assert order["status"] == "PARTIALLY_CREDITED", (
        "credited_spots + short_aired_spots == 2 is strictly greater than zero "
        "and strictly less than ordered_spots 3"
    )
    assert_spot_count_conservation(order)


# ---------------------------------------------------------------------------
# Instance 3 scenario — the five-step waterfall over a generous pool
#
# MUX-A total 30000 with pilot 500 at derate 1.00 gives an effective pool of
# 29500 kbps. Step two grants the three floors 2000 / 3000 / 5000 in priority
# order, leaving a remainder of 19500 against a total weight of only
# 500 + 3000 + 4000 == 7500.
# ---------------------------------------------------------------------------

_MUX_30000 = {"total_capacity_kbps": 30000, "pilot_reserved_kbps": 500,
              "live_encoder_units_total": 2}


def _setup_three_channel_pool():
    """Three ACTIVE SD_480I channels whose requests all sit below the remainder."""
    plant = fx.setup_base_plant(
        with_subchannel=False, mux_overrides=_MUX_30000,
        ch1_overrides={"resolution_class": "SD_480I",
                       "requested_bitrate_kbps": 2500,
                       "floor_bitrate_kbps": 2000, "priority_rank": 1},
    )
    eng = plant["eng_headers"]
    mux_id = plant["multiplex"]["id"]

    mux = fx.read_multiplex(mux_id, eng)
    plant["ch2"] = fx.create_subchannel(
        eng, mux_id, mux["version"], plant["ch1"]["id"],
        resolution_class="SD_480I", requested_bitrate_kbps=6000,
        floor_bitrate_kbps=3000, priority_rank=2,
    )
    mux = fx.read_multiplex(mux_id, eng)
    plant["ch3"] = fx.create_subchannel(
        eng, mux_id, mux["version"], plant["ch1"]["id"],
        call_sign="WXYZ-DT3", channel_number="12.3",
        resolution_class="SD_480I", requested_bitrate_kbps=9000,
        floor_bitrate_kbps=5000, priority_rank=3,
    )
    plant["multiplex"] = fx.read_multiplex(mux_id, eng)
    return plant


def test_waterfall_share_is_capped_at_each_channels_own_weight(api):
    """With a remainder of 19500 over a total weight of 7500 every channel lands on its request.

    PRD §3.2: "Otherwise each granted channel's share is the smaller of two figures: the remainder multiplied by that channel's weight and divided by the total weight with the quotient truncated downward, and the channel's own weight."

    Design: Difficulty/combinatorial_formula/waterfall_allocation_pinned_five_step_order_caps_shares_at_weight
    """
    plant = _setup_three_channel_pool()
    mux_version = plant["multiplex"]["version"]

    mux = validate_success(
        api.rebalance_multiplex(
            plant["multiplex"]["id"],
            {"expected_multiplex_version": mux_version, "clear_pins": True},
            plant["eng_headers"],
        )
    )
    assert_multiplex(mux)
    assert mux["effective_capacity_kbps"] == 29500, (
        "floor(30000 * 1.00) less the 500 kbps pilot reservation"
    )

    ch1 = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    ch2 = fx.read_channel(plant["ch2"]["id"], plant["eng_headers"])
    ch3 = fx.read_channel(plant["ch3"]["id"], plant["eng_headers"])

    assert ch1["allocated_bitrate_kbps"] == 2500
    assert ch2["allocated_bitrate_kbps"] == 6000
    assert ch3["allocated_bitrate_kbps"] == 9000
    assert ch1["allocated_bitrate_kbps"] != 4214, (
        "4214 is what a single-pass pro-rata split of the whole 29500 pool over "
        "the requests would hand channel 12.1"
    )
    assert ch1["allocation_state"] == "ACTIVE"
    assert ch2["allocation_state"] == "ACTIVE"
    assert ch3["allocation_state"] == "ACTIVE"


def test_waterfall_leaves_the_unclaimed_kilobits_in_available_kbps(api):
    """No channel is still under its request, so 12000 kbps stay unassigned.

    PRD §3.2: "If no channel is still under its request, the sweep stops and the residual kilobits remain unassigned, surfacing in `available_kbps`."

    Design: Difficulty/combinatorial_formula/waterfall_allocation_pinned_five_step_order_caps_shares_at_weight
    """
    plant = _setup_three_channel_pool()

    mux = validate_success(
        api.rebalance_multiplex(
            plant["multiplex"]["id"],
            {"expected_multiplex_version": plant["multiplex"]["version"],
             "clear_pins": True},
            plant["eng_headers"],
        )
    )
    assert mux["assigned_kbps"] == 17500, "2500 + 6000 + 9000"
    assert mux["available_kbps"] == 12000, "29500 less the 17500 assigned"
    assert mux["starved_channel_count"] == 0
    assert_bandwidth_conservation(mux)


def test_stale_multiplex_version_on_a_second_rebalance_changes_no_allocation(api):
    """The version the first rebalance superseded is refused before anything is re-sliced.

    PRD §2.6: "Re-running the bitrate waterfall across a multiplex requires `expected_multiplex_version` to equal that multiplex's current `version`. A rebalance legitimately supersedes the standing allocation set, so a stale-view writer would confirm an allocation it never observed. A mismatch is rejected with `ERR_STALE_MULTIPLEX_VERSION` and HTTP 412."

    Design: Difficulty/combinatorial_formula/waterfall_allocation_pinned_five_step_order_caps_shares_at_weight
    """
    plant = _setup_three_channel_pool()
    stale_version = plant["multiplex"]["version"]

    validate_success(
        api.rebalance_multiplex(
            plant["multiplex"]["id"],
            {"expected_multiplex_version": stale_version, "clear_pins": True},
            plant["eng_headers"],
        )
    )

    resp = api.rebalance_multiplex(
        plant["multiplex"]["id"],
        {"expected_multiplex_version": stale_version, "clear_pins": True},
        plant["eng_headers"],
    )
    validate_error(resp, "ERR_STALE_MULTIPLEX_VERSION")

    ch1 = fx.read_channel(plant["ch1"]["id"], plant["eng_headers"])
    ch2 = fx.read_channel(plant["ch2"]["id"], plant["eng_headers"])
    ch3 = fx.read_channel(plant["ch3"]["id"], plant["eng_headers"])
    assert ch1["allocated_bitrate_kbps"] == 2500
    assert ch2["allocated_bitrate_kbps"] == 6000
    assert ch3["allocated_bitrate_kbps"] == 9000
