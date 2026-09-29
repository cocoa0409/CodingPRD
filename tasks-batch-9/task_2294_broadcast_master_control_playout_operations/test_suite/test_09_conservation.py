"""Conserved-quantity round trips: the spot/cents ledger and the kbps ledger.

PRD §2.11 pins three ledgers that must balance at all times, each with a
compensating action that returns it to its exact pre-action value. The tests in
this module drive a forward action and its compensating action through the §4
surface and assert the ledger identity before, between and after, with the
exact integer equality §2.10 demands ("Invariant assertions are exact integer
equalities with no tolerance whatsoever, in both kilobits and cents and
counts").
"""
from test_helpers import (
    assert_assigned_equals_channel_sum,
    assert_bandwidth_conservation,
    assert_spot_count_conservation,
    validate_success,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Private setup helpers (test_helpers is read-only, so these live here)
# ---------------------------------------------------------------------------

_SD = "SD_480I"
_ASSET_DEADLINE_UTC = "2026-08-05T00:00:00Z"


def _instant(timestamp: str) -> str:
    """Second-granularity form of a timestamp (PRD §2.10: whole seconds)."""
    return timestamp.replace("Z", "").split(".")[0]


def _sd_asset(plant: dict, seconds: int) -> dict:
    """One QC_PASSED SD_480I asset of the given length, scoring a clean 100."""
    return fx.setup_qc_passed_asset(
        plant,
        seconds,
        asset_overrides={
            "required_resolution_class": _SD,
            "delivery_deadline_utc": _ASSET_DEADLINE_UTC,
        },
    )


def _setup_on_air_day_with_three_spots(api) -> dict:
    """Plant + ORD-9A (3 spots, 1000 cents) + playlist P1 on air at 12:14:00Z.

    MUX-A carries 20000 kbps with 500 reserved for the pilot, so the pool is
    19500 and the single SD channel 12.1 (floor 2000, request 6000) is granted
    6000 kbps and can be lit. P1 books five gapless elements across exactly
    1800 seconds — PROG-A, the three 30-second spots of ORD-9A, then PROG-B —
    so the projected variance is 0 and the day arms and goes to air.
    """
    plant = fx.setup_base_plant(
        with_subchannel=False,
        clock_utc="2026-08-01T10:00:00Z",
        mux_overrides={"total_capacity_kbps": 20000, "pilot_reserved_kbps": 500},
        ch1_overrides={
            "channel_number": "12.1",
            "resolution_class": _SD,
            "requested_bitrate_kbps": 6000,
            "floor_bitrate_kbps": 2000,
            "priority_rank": 1,
        },
    )

    prog_a = _sd_asset(plant, 840)
    prog_b = _sd_asset(plant, 870)
    prog_c = _sd_asset(plant, 1770)
    spot_1 = _sd_asset(plant, 30)
    spot_2 = _sd_asset(plant, 30)
    spot_3 = _sd_asset(plant, 30)
    plant["prog_c"] = prog_c

    order = fx.create_order(
        plant,
        advertiser_name="Delta Dairy",
        order_reference="ORD-9A",
        ordered_spots=3,
        unit_duration_seconds=30,
        rate_cents_total=1000,
        daypart="DAYTIME",
        priority_class="PREEMPTIBLE",
        makegood_deadline_utc="2026-08-10T00:00:00Z",
    )
    plant["order"] = order
    plant["order_at_creation"] = order

    playlist = fx.ingest(
        plant,
        [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": prog_a["id"],
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 840, "max_trim_seconds": 0},
            {"sequence_number": 2, "element_kind": "COMMERCIAL",
             "asset_id": spot_1["id"], "spot_order_id": order["id"],
             "scheduled_start_utc": "2026-08-01T12:14:00Z",
             "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
            {"sequence_number": 3, "element_kind": "COMMERCIAL",
             "asset_id": spot_2["id"], "spot_order_id": order["id"],
             "scheduled_start_utc": "2026-08-01T12:14:30Z",
             "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
            {"sequence_number": 4, "element_kind": "COMMERCIAL",
             "asset_id": spot_3["id"], "spot_order_id": order["id"],
             "scheduled_start_utc": "2026-08-01T12:15:00Z",
             "scheduled_duration_seconds": 30, "max_trim_seconds": 0},
            {"sequence_number": 5, "element_kind": "PROGRAM",
             "asset_id": prog_b["id"],
             "scheduled_start_utc": "2026-08-01T12:15:30Z",
             "scheduled_duration_seconds": 870, "max_trim_seconds": 0},
        ],
        broadcast_day="2026-08-01",
        schedule_start_utc="2026-08-01T12:00:00Z",
        window_duration_seconds=1800,
    )
    plant["playlist"] = playlist

    items = fx.list_items(playlist["id"], plant["mco_headers"])
    plant["items"] = items
    plant["spot2_item"] = items[2]
    plant["order_before"] = fx.read_order(order["id"], plant["traffic_headers"])

    mco = plant["mco_headers"]
    fx.drive_playlist(plant, playlist["id"], "VALIDATED", headers=mco)
    fx.drive_playlist(plant, playlist["id"], "ARMED", headers=mco)
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ON_AIR", headers=mco)
    fx.set_clock("2026-08-01T12:14:00Z")
    return plant


def _ingest_next_day_playlist(plant: dict) -> dict:
    """Playlist P2: broadcast day 2026-08-02, one 1770 s programme in a 1800 s window."""
    return fx.ingest(
        plant,
        [
            {"sequence_number": 1, "element_kind": "PROGRAM",
             "asset_id": plant["prog_c"]["id"],
             "scheduled_start_utc": "2026-08-02T13:00:00Z",
             "scheduled_duration_seconds": 1770, "max_trim_seconds": 0},
        ],
        broadcast_day="2026-08-02",
        schedule_start_utc="2026-08-02T13:00:00Z",
        window_duration_seconds=1800,
    )


def _makegood_payload(playlist: dict) -> dict:
    return {
        "target_playlist_id": playlist["id"],
        "expected_playlist_version": playlist["version"],
        "sequence_number": 2,
        "scheduled_start_utc": "2026-08-02T13:29:30Z",
        "scheduled_duration_seconds": 30,
    }


# ---------------------------------------------------------------------------
# The spot-count and cents ledger: skip forward, makegood back
# ---------------------------------------------------------------------------

def test_skipping_one_of_three_spots_accrues_the_rounded_333_cent_credit(api):
    """The forward leg: skipping one spot of ORD-9A accrues the full per-spot credit.

    The order sells 3 spots for 1000 cents, so the per-spot rate is the exact
    rational 1000/3 and the credit attributable to the one skipped spot is
    round_half_up(333.333...) == 333 cents.

    PRD §3.6: "It appends a skip entry, and when the element carries a `spot_order_id` it moves that spot from `scheduled_spots` to `credited_spots` and accrues the **full** per-spot credit, then recomputes both of the playlist's variance figures."

    Design: Difficulty/compensating_invariant/makegood_restores_spot_count_and_returns_credit_to_exactly_zero_cents
    """
    scn = _setup_on_air_day_with_three_spots(api)

    before = scn["order_before"]
    assert before["scheduled_spots"] == 3
    assert before["credited_spots"] == 0
    assert before["credit_accrued_cents"] == 0

    resp = api.post_playout_event(
        scn["spot2_item"]["id"],
        {"event_kind": "SKIP", "event_utc": "2026-08-01T12:14:00Z",
         "source": "OPERATOR"},
        scn["mco_headers"],
    )
    validate_success(resp, 201)

    skipped = fx.read_item(scn["spot2_item"]["id"], scn["mco_headers"])
    assert skipped["playout_status"] == "SKIPPED"

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["scheduled_spots"] == 2
    assert order["aired_spots"] == 0
    assert order["short_aired_spots"] == 0
    assert order["credited_spots"] == 1
    assert order["unplaced_spots"] == 0
    assert order["credit_accrued_cents"] == 333, (
        "the accrued figure is round_half_up(1000/3) == 333, not 334"
    )
    assert order["status"] == "PARTIALLY_CREDITED"


def test_makegood_returns_the_accrued_credit_to_exactly_zero_cents(api):
    """The compensating leg: the makegood subtracts exactly the 333 cents the skip added.

    1000 is not divisible by 3, yet the round trip leaves no drift at all
    because the identical rounded per-spot figure is subtracted rather than
    recomputed, and the order falls back out of PARTIALLY_CREDITED.

    PRD §3.9: "It moves one spot from `credited_spots` back to `scheduled_spots` and subtracts **exactly the credit that spot had accrued** from `credit_accrued_cents`."

    Design: Difficulty/compensating_invariant/makegood_restores_spot_count_and_returns_credit_to_exactly_zero_cents
    """
    scn = _setup_on_air_day_with_three_spots(api)
    fx.skip_item(scn, scn["spot2_item"]["id"], "2026-08-01T12:14:00Z",
                 source="OPERATOR")
    mid = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert mid["credit_accrued_cents"] == 333
    assert mid["status"] == "PARTIALLY_CREDITED"

    playlist2 = _ingest_next_day_playlist(scn)
    resp = api.place_makegood(scn["order"]["id"], _makegood_payload(playlist2),
                              scn["traffic_headers"])
    validate_success(resp, 201)

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credit_accrued_cents"] == 0, (
        "the same rounded 333 that was added is subtracted, so neither +1 nor "
        "-1 of rounding drift survives the round trip"
    )
    assert order["credited_spots"] == 0
    assert order["scheduled_spots"] == 3
    assert order["status"] == "OPEN"


def test_spot_count_ledger_balances_before_between_and_after_the_makegood(api):
    """The count ledger holds at all three observation points, exactly.

    Three spots are sold: 3 == 3+0+0+0+0 before the skip, 3 == 2+0+0+1+0
    between the skip and the makegood, and 3 == 3+0+0+0+0 once the makegood is
    placed. The identity already holds at order creation, where all three spots
    are unplaced.

    PRD §2.11: "For every spot order, `ordered_spots` equals the sum of `scheduled_spots`, `aired_spots`, `short_aired_spots`, `credited_spots` and `unplaced_spots`."

    Design: Difficulty/compensating_invariant/makegood_restores_spot_count_and_returns_credit_to_exactly_zero_cents
    """
    scn = _setup_on_air_day_with_three_spots(api)

    at_creation = scn["order_at_creation"]
    assert at_creation["unplaced_spots"] == 3
    assert_spot_count_conservation(at_creation)

    before = scn["order_before"]
    assert [before["ordered_spots"], before["scheduled_spots"], before["aired_spots"],
            before["short_aired_spots"], before["credited_spots"],
            before["unplaced_spots"]] == [3, 3, 0, 0, 0, 0]
    assert_spot_count_conservation(before)

    fx.skip_item(scn, scn["spot2_item"]["id"], "2026-08-01T12:14:00Z",
                 source="OPERATOR")
    mid = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert [mid["ordered_spots"], mid["scheduled_spots"], mid["aired_spots"],
            mid["short_aired_spots"], mid["credited_spots"],
            mid["unplaced_spots"]] == [3, 2, 0, 0, 1, 0]
    assert_spot_count_conservation(mid)

    playlist2 = _ingest_next_day_playlist(scn)
    resp = api.place_makegood(scn["order"]["id"], _makegood_payload(playlist2),
                              scn["traffic_headers"])
    validate_success(resp, 201)

    after = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert [after["ordered_spots"], after["scheduled_spots"], after["aired_spots"],
            after["short_aired_spots"], after["credited_spots"],
            after["unplaced_spots"]] == [3, 3, 0, 0, 0, 0]
    assert_spot_count_conservation(after)


def test_makegood_element_supersedes_the_skipped_spot_without_double_counting(api):
    """The replacement element points back at the credited element it compensates.

    The skipped element keeps its own SKIPPED playout status forever, but once
    it is named as the makegood's `replaces_item_id` it no longer contributes to
    `credited_spots` — counting it as well would read 3 == 3+0+0+1+0 and break
    the identity.

    PRD §3.9: "A successful makegood creates a playlist element with `is_makegood` set to true, `element_kind` `COMMERCIAL`, and `replaces_item_id` pointing at the credited element, in `playout_status` `SCHEDULED`."

    Design: Difficulty/compensating_invariant/makegood_restores_spot_count_and_returns_credit_to_exactly_zero_cents
    """
    scn = _setup_on_air_day_with_three_spots(api)
    fx.skip_item(scn, scn["spot2_item"]["id"], "2026-08-01T12:14:00Z",
                 source="OPERATOR")
    playlist2 = _ingest_next_day_playlist(scn)

    resp = api.place_makegood(scn["order"]["id"], _makegood_payload(playlist2),
                              scn["traffic_headers"])
    created = validate_success(resp, 201)

    assert created["is_makegood"] is True
    assert created["element_kind"] == "COMMERCIAL"
    assert created["playout_status"] == "SCHEDULED"
    assert created["spot_order_id"] == scn["order"]["id"]
    assert created["replaces_item_id"] == scn["spot2_item"]["id"]

    superseded = fx.read_item(scn["spot2_item"]["id"], scn["mco_headers"])
    assert superseded["playout_status"] == "SKIPPED"

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credited_spots"] == 0, (
        "the superseded element no longer contributes to credited_spots"
    )
    assert_spot_count_conservation(order)


def test_makegood_restores_the_target_playlist_seconds_ledger_and_bumps_its_version(api):
    """The same call that repays the advertiser closes the 30-second hole in P2.

    P2 books a single 1770-second programme against a 1800-second window, so its
    projected variance reads -30 before the placement and exactly 0 once the
    30-second replacement spot is added.

    PRD §3.5: "sum `scheduled_duration_seconds` over every item of the playlist whose `playout_status` is not `SKIPPED` and not `PREEMPTED`, then subtract `window_duration_seconds`."

    PRD §3.9: "It increments both the order's `version` and the playlist's `version`."

    Design: Difficulty/compensating_invariant/makegood_restores_spot_count_and_returns_credit_to_exactly_zero_cents
    """
    scn = _setup_on_air_day_with_three_spots(api)
    fx.skip_item(scn, scn["spot2_item"]["id"], "2026-08-01T12:14:00Z",
                 source="OPERATOR")

    playlist2 = _ingest_next_day_playlist(scn)
    assert playlist2["projected_end_variance_seconds"] == -30

    resp = api.place_makegood(scn["order"]["id"], _makegood_payload(playlist2),
                              scn["traffic_headers"])
    validate_success(resp, 201)

    after = fx.read_playlist(playlist2["id"], scn["traffic_headers"])
    assert after["projected_end_variance_seconds"] == 0, "1770 + 30 == 1800"
    assert after["version"] > playlist2["version"]


# ---------------------------------------------------------------------------
# The transport-stream bandwidth ledger: OFF_AIR forward, FULL_POWER back
# ---------------------------------------------------------------------------

def _setup_three_channel_mux(api) -> dict:
    """MUX-A (20000 total, 500 pilot) with three channels at ranks 1, 2 and 3.

    The pool is 19500. Floors 2000 + 3000 + 5000 leave a remainder of 9500 and
    weights of 4000 / 6000 / 7000 against a total weight of 17000, so the
    truncated shares are 2235 / 3352 / 3911 and the two kilobits truncation left
    behind are swept to priority ranks 1 and 2.
    """
    plant = fx.bootstrap_operators()
    eng = plant["eng_headers"]
    plant["transmitter"] = fx.create_transmitter(eng)
    plant["multiplex"] = fx.create_multiplex(
        eng, plant["transmitter"]["id"],
        total_capacity_kbps=20000, pilot_reserved_kbps=500,
        live_encoder_units_total=2,
    )
    mux_id = plant["multiplex"]["id"]

    plant["ch1"] = fx.create_channel(
        eng, mux_id, plant["multiplex"]["version"],
        call_sign="WXYZ-DT1", channel_number="12.1", service_class="PRIMARY",
        resolution_class=_SD, requested_bitrate_kbps=6000,
        floor_bitrate_kbps=2000, priority_rank=1,
    )
    plant["ch2"] = fx.create_subchannel(
        eng, mux_id, fx.read_multiplex(mux_id, eng)["version"], plant["ch1"]["id"],
        call_sign="WXYZ-DT2", channel_number="12.2", resolution_class=_SD,
        requested_bitrate_kbps=9000, floor_bitrate_kbps=3000, priority_rank=2,
    )
    plant["ch3"] = fx.create_subchannel(
        eng, mux_id, fx.read_multiplex(mux_id, eng)["version"], plant["ch1"]["id"],
        call_sign="WXYZ-DT3", channel_number="12.3", resolution_class="HD_720P",
        requested_bitrate_kbps=12000, floor_bitrate_kbps=5000, priority_rank=3,
    )
    plant["multiplex"] = fx.read_multiplex(mux_id, eng)
    return plant


def _channel_allocations(plant: dict) -> list:
    eng = plant["eng_headers"]
    return [fx.read_channel(plant[key]["id"], eng) for key in ("ch1", "ch2", "ch3")]


def _take_off_air(plant: dict) -> None:
    fx.set_clock("2026-08-01T12:00:00Z")
    fx.change_power_state(plant, "OFF_AIR",
                          reason="emergency generator transfer at the site")


def test_taking_the_transmitter_off_air_clamps_the_pool_to_zero_not_minus_500(api):
    """The forward leg: a zero derate drives the pool to 0 and starves all three channels.

    20000 scaled by a derate of 0.00 is 0, and subtracting the 500 kbps pilot
    reservation would give -500 were the result not floored, so the pool reads 0
    and the ledger still balances at 0 + 0 == 0.

    PRD §3.2: "take `total_capacity_kbps`, multiply by the parent transmitter's current `derate_factor`, truncate the product downward to a whole kilobit, subtract `pilot_reserved_kbps`, and floor the result at 0."

    Design: Difficulty/compensating_invariant/off_air_round_trip_restores_every_kbps_with_no_drift_and_clamps_the_pool_at_zero
    """
    plant = _setup_three_channel_mux(api)
    assert plant["multiplex"]["effective_capacity_kbps"] == 19500

    _take_off_air(plant)

    mux = fx.read_multiplex(plant["multiplex"]["id"], plant["eng_headers"])
    assert mux["effective_capacity_kbps"] == 0
    assert mux["assigned_kbps"] == 0
    assert mux["available_kbps"] == 0
    assert mux["starved_channel_count"] == 3
    assert_bandwidth_conservation(mux)

    for channel in _channel_allocations(plant):
        assert channel["allocation_state"] == "STARVED"
        assert channel["allocated_bitrate_kbps"] == 0


def test_restoring_full_power_reproduces_every_kbps_of_the_pre_outage_allocation(api):
    """The compensating leg: the restore re-runs the waterfall and lands on the same figures.

    Starved channels re-enter the waterfall from their unchanged floor and
    request, so the allocation comes back as 4236 / 6353 / 8911 — byte for byte
    the pre-outage set — and every channel is ACTIVE again.

    PRD §3.1: "A clean restoration writes `current_power_pct` to 100 and `derate_factor` to 1.00 and re-runs the bitrate waterfall across every child multiplex: channels that had been `STARVED` and can now be granted their floor return to `allocation_state` `ACTIVE`"

    Design: Difficulty/compensating_invariant/off_air_round_trip_restores_every_kbps_with_no_drift_and_clamps_the_pool_at_zero
    """
    plant = _setup_three_channel_mux(api)
    pre_outage = [c["allocated_bitrate_kbps"] for c in _channel_allocations(plant)]
    assert pre_outage == [4236, 6353, 8911]

    _take_off_air(plant)
    fx.set_clock("2026-08-01T12:10:00Z")

    resp = api.change_transmitter_power_state(
        plant["transmitter"]["id"],
        {"target_state": "FULL_POWER", "reason": "site power restored"},
        plant["eng_headers"],
    )
    transmitter = validate_success(resp)
    assert transmitter["operational_state"] == "FULL_POWER"
    assert transmitter["current_power_pct"] == 100
    assert float(transmitter["derate_factor"]) == 1.00

    restored = _channel_allocations(plant)
    assert [c["allocated_bitrate_kbps"] for c in restored] == [4236, 6353, 8911]
    for channel in restored:
        assert channel["allocation_state"] == "ACTIVE"


def test_bandwidth_ledger_balances_before_during_and_after_the_off_air_round_trip(api):
    """The kbps identity holds at all three observation points with no drift.

    0 + 19500 == 19500 while the plant is lit, 0 + 0 == 0 with the transmitter
    dark, and 0 + 19500 == 19500 once power is back — the same values, not merely
    a balanced sum.

    PRD §2.11: "Admitting a channel as `ACTIVE` and later moving it to `STANDBY` and back, or reversing a power-state change and rebalancing, leaves the identity holding with identical values before and after."

    Design: Difficulty/compensating_invariant/off_air_round_trip_restores_every_kbps_with_no_drift_and_clamps_the_pool_at_zero
    """
    plant = _setup_three_channel_mux(api)
    eng = plant["eng_headers"]
    mux_id = plant["multiplex"]["id"]

    before = fx.read_multiplex(mux_id, eng)
    assert (before["available_kbps"], before["assigned_kbps"],
            before["effective_capacity_kbps"]) == (0, 19500, 19500)
    assert_bandwidth_conservation(before)
    assert_assigned_equals_channel_sum(before, _channel_allocations(plant))

    _take_off_air(plant)

    during = fx.read_multiplex(mux_id, eng)
    assert (during["available_kbps"], during["assigned_kbps"],
            during["effective_capacity_kbps"]) == (0, 0, 0)
    assert_bandwidth_conservation(during)
    assert_assigned_equals_channel_sum(during, _channel_allocations(plant))

    fx.set_clock("2026-08-01T12:10:00Z")
    fx.change_power_state(plant, "FULL_POWER", reason="site power restored")

    after = fx.read_multiplex(mux_id, eng)
    assert (after["available_kbps"], after["assigned_kbps"],
            after["effective_capacity_kbps"]) == (0, 19500, 19500)
    assert_bandwidth_conservation(after)
    assert_assigned_equals_channel_sum(after, _channel_allocations(plant))


def test_the_two_swept_kilobits_land_on_ranks_one_and_two_again_after_the_restore(api):
    """The kilobits truncation forgoes are swept the same way on both passes.

    The weighted shares truncate to 2235 / 3352 / 3911 and leave 2 kbps unspent,
    so rank 1 and rank 2 each take one extra kilobit above floor-plus-share while
    rank 3 takes none — before the outage and identically after it.

    PRD §3.2: "While leftover kilobits remain, the granted channels whose `allocated_bitrate_kbps` is still strictly below their `requested_bitrate_kbps` are gathered in the same deterministic order — `priority_rank` ascending, then `created_at` ascending — and each in turn receives one additional kilobit until either the leftover reaches zero or no under-served channel remains."

    Design: Difficulty/compensating_invariant/off_air_round_trip_restores_every_kbps_with_no_drift_and_clamps_the_pool_at_zero
    """
    plant = _setup_three_channel_mux(api)
    floors_plus_shares = [2000 + 2235, 3000 + 3352, 5000 + 3911]

    before = [c["allocated_bitrate_kbps"] for c in _channel_allocations(plant)]
    assert [before[i] - floors_plus_shares[i] for i in range(3)] == [1, 1, 0]
    assert before == [4236, 6353, 8911]
    assert sum(before) == 19500

    _take_off_air(plant)
    fx.set_clock("2026-08-01T12:10:00Z")
    fx.change_power_state(plant, "FULL_POWER", reason="site power restored")

    after = [c["allocated_bitrate_kbps"] for c in _channel_allocations(plant)]
    assert [after[i] - floors_plus_shares[i] for i in range(3)] == [1, 1, 0]
    assert after == before
    assert sum(after) == 19500


def test_the_ten_minute_outage_epoch_closes_at_600_seconds_and_files_only_a_resumption(api):
    """The neighbouring outage-seconds counters are accumulated, not conserved.

    The epoch opens at 12:00:00Z and closes at 12:10:00Z, so 600 seconds are
    written to `last_outage_seconds` and added to a `cumulative_outage_seconds`
    that started at 0, while the epoch pointer is cleared. 600 seconds is below
    the 30-minute threshold, so the restoration files a RESUMPTION and no OUTAGE.

    PRD §3.1: "`last_outage_seconds` is written as the whole number of seconds between `outage_started_utc` and the current logical instant, that figure is added to `cumulative_outage_seconds` — which is the running sum over every closed outage epoch on the transmitter — and `outage_started_utc` is cleared to null."
    PRD §3.1: "Independently, every restoration from `OFF_AIR` creates a `RESUMPTION` notification in status `PENDING` with `triggering_utc` at the restoration instant and `due_utc` 24 hours later."

    Design: Difficulty/compensating_invariant/off_air_round_trip_restores_every_kbps_with_no_drift_and_clamps_the_pool_at_zero
    """
    plant = _setup_three_channel_mux(api)
    tx_id = plant["transmitter"]["id"]
    eng = plant["eng_headers"]

    _take_off_air(plant)
    dark = fx.read_transmitter(tx_id, eng)
    assert _instant(dark["outage_started_utc"]) == _instant("2026-08-01T12:00:00Z")

    fx.set_clock("2026-08-01T12:10:00Z")
    fx.change_power_state(plant, "FULL_POWER", reason="site power restored")

    transmitter = fx.read_transmitter(tx_id, eng)
    assert transmitter["last_outage_seconds"] == 600
    assert transmitter["cumulative_outage_seconds"] == 600
    assert transmitter["outage_started_utc"] is None
    assert transmitter["notification_pending_count"] == 1

    notifications = fx.list_notifications(tx_id, plant["compliance_headers"])
    assert [n["kind"] for n in notifications] == ["RESUMPTION"]
    resumption = notifications[0]
    assert resumption["status"] == "PENDING"
    assert _instant(resumption["triggering_utc"]) == _instant("2026-08-01T12:10:00Z")
    assert _instant(resumption["due_utc"]) == _instant("2026-08-02T12:10:00Z")
