"""Derived-figure calculations: the bitrate waterfall, floor feasibility, the
derate variants, the channel posture ladder, hourly commercial inventory, the two
timing-variance figures and the backtiming plan branches.

Every expected number here is fixed by PRD §2.10 (truncate bandwidth downward,
whole seconds for time, exact integer invariant equalities) together with the
per-feature arithmetic of §3.2, §3.3, §3.5 and §3.7.
"""
from test_helpers import (
    assert_assigned_equals_channel_sum,
    assert_bandwidth_conservation,
    factories as fac,
    fixtures as fx,
    item_by_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local setup helpers (private to this module)
# ---------------------------------------------------------------------------

def _plant_with_transmitter() -> dict:
    """The four operator identities plus one FULL_POWER transmitter."""
    plant = fx.bootstrap_operators()
    plant["transmitter"] = fx.create_transmitter(plant["eng_headers"])
    return plant


def _admit(plant: dict, multiplex_id: str, call_sign: str, channel_number: str,
           resolution_class: str, requested: int, floor: int, rank: int) -> dict:
    """Admit one PRIMARY channel, quoting the multiplex version just read."""
    eng = plant["eng_headers"]
    current = fx.read_multiplex(multiplex_id, eng)
    return fx.create_channel(
        eng, multiplex_id, current["version"],
        call_sign=call_sign,
        channel_number=channel_number,
        service_class="PRIMARY",
        resolution_class=resolution_class,
        requested_bitrate_kbps=requested,
        floor_bitrate_kbps=floor,
        priority_rank=rank,
    )


def _mux_c_graph(plant: dict):
    """A 20500/500 pool carrying four channels admitted in priority-rank order.

    Floors 8000 + 5000 + 2000 + 2000 = 17000 all fit inside the 20000 kbps pool;
    the weights are 4000 / 4000 / 2000 / 1000 over a remainder of 3000.
    """
    mux = fx.create_multiplex(plant["eng_headers"], plant["transmitter"]["id"],
                              name="MUX-C", total_capacity_kbps=20500,
                              pilot_reserved_kbps=500)
    channels = [
        _admit(plant, mux["id"], "WAAA-DT", "30.1", "HD_1080I", 12000, 8000, 1),
        _admit(plant, mux["id"], "WBBB-DT", "30.2", "HD_720P", 9000, 5000, 2),
        _admit(plant, mux["id"], "WCCC-DT", "30.3", "SD_480I", 4000, 2000, 3),
        _admit(plant, mux["id"], "WDDD-DT", "30.4", "SD_480I", 3000, 2000, 4),
    ]
    return mux, channels


def _mux_d_graph(plant: dict):
    """An 11500/500 pool carrying two all-or-nothing channels (request == floor)."""
    mux = fx.create_multiplex(plant["eng_headers"], plant["transmitter"]["id"],
                              name="MUX-D", total_capacity_kbps=11500,
                              pilot_reserved_kbps=500)
    channels = [
        _admit(plant, mux["id"], "WPPP-DT", "40.1", "HD_720P", 5000, 5000, 1),
        _admit(plant, mux["id"], "WQQQ-DT", "40.2", "SD_480I", 4000, 4000, 2),
    ]
    return mux, channels


# ===========================================================================
# The five-step bitrate waterfall
# ===========================================================================

def test_waterfall_grants_floors_then_weighted_shares_and_sweeps_the_leftover(api):
    """Floors first, then truncated proportional shares, then a rank-ordered 1 kbps sweep.

    PRD §3.2: "Otherwise each granted channel's share is the smaller of two figures:
    the remainder multiplied by that channel's weight and divided by the total weight
    with the quotient truncated downward, and the channel's own weight."

    PRD §3.2: "While leftover kilobits remain, the granted channels whose
    `allocated_bitrate_kbps` is still strictly below their `requested_bitrate_kbps` are
    gathered in the same deterministic order — `priority_rank` ascending, then
    `created_at` ascending — and each in turn receives one additional kilobit until
    either the leftover reaches zero or no under-served channel remains."

    Design: Corner/calculations/waterfall_grants_floors_then_proportional_shares_with_a_one_kbps_sweep
    """
    plant = _plant_with_transmitter()
    eng = plant["eng_headers"]
    mux, channels = _mux_c_graph(plant)
    ch_a, ch_b, ch_c, ch_d = channels

    multiplex = validate_success(api.get_multiplex(mux["id"], eng))
    assert multiplex["effective_capacity_kbps"] == 20000

    allocations = {}
    for channel in channels:
        row = validate_success(api.get_channel(channel["id"], eng))
        allocations[row["call_sign"]] = row
        assert row["allocation_state"] == "ACTIVE"
        assert row["allocated_bitrate_kbps"] <= row["requested_bitrate_kbps"]

    assert allocations["WAAA-DT"]["allocated_bitrate_kbps"] == 9091
    assert allocations["WBBB-DT"]["allocated_bitrate_kbps"] == 6091
    assert allocations["WCCC-DT"]["allocated_bitrate_kbps"] == 2546
    assert allocations["WDDD-DT"]["allocated_bitrate_kbps"] == 2272

    assert multiplex["assigned_kbps"] == 20000
    assert multiplex["available_kbps"] == 0
    assert multiplex["starved_channel_count"] == 0
    assert_bandwidth_conservation(multiplex)
    assert_assigned_equals_channel_sum(multiplex, list(allocations.values()))
    assert ch_a["id"] != ch_d["id"] and ch_b["id"] != ch_c["id"]


# ===========================================================================
# Floor feasibility over the prospective ACTIVE set
# ===========================================================================

def test_floor_sum_exactly_equal_to_the_effective_capacity_is_admitted(api):
    """A floor total of exactly 11000 against an 11000 kbps pool is feasible.

    PRD §3.2: "a floor sum exactly equal to the effective capacity is feasible, since
    every channel then gets precisely its floor and the remainder pool is zero."

    Design: Corner/calculations/floor_feasibility_is_checked_against_the_active_set_with_exact_equality_legal
    """
    plant = _plant_with_transmitter()
    eng = plant["eng_headers"]
    mux, (ch_p, ch_q) = _mux_d_graph(plant)

    current = fx.read_multiplex(mux["id"], eng)
    resp = api.create_channel(
        fac.create_channel_payload(
            mux["id"], current["version"],
            call_sign="WSSS-DT", channel_number="40.3", service_class="PRIMARY",
            resolution_class="SD_480I", requested_bitrate_kbps=2000,
            floor_bitrate_kbps=2000, priority_rank=3,
        ),
        eng,
    )
    admitted = validate_success(resp, 201)

    third = validate_success(api.get_channel(admitted["id"], eng))
    assert third["allocation_state"] == "ACTIVE"
    assert third["allocated_bitrate_kbps"] == 2000
    assert validate_success(api.get_channel(ch_p["id"], eng))["allocated_bitrate_kbps"] == 5000
    assert validate_success(api.get_channel(ch_q["id"], eng))["allocated_bitrate_kbps"] == 4000

    multiplex = validate_success(api.get_multiplex(mux["id"], eng))
    assert multiplex["effective_capacity_kbps"] == 11000
    assert multiplex["assigned_kbps"] == 11000
    assert multiplex["available_kbps"] == 0
    assert multiplex["starved_channel_count"] == 0
    assert_bandwidth_conservation(multiplex)


def test_floor_sum_above_the_effective_capacity_is_refused_at_admission(api):
    """A fourth 2000 kbps floor would need 13000 of an 11000 kbps pool and is refused.

    PRD §3.2: "If the sum of `floor_bitrate_kbps` over the channels that would have to
    be `ACTIVE` exceeds `effective_capacity_kbps`, no feasible allocation exists and the
    request is refused with `ERR_BITRATE_FLOOR_UNSATISFIABLE`"

    Design: Corner/calculations/floor_feasibility_is_checked_against_the_active_set_with_exact_equality_legal
    """
    plant = _plant_with_transmitter()
    eng = plant["eng_headers"]
    mux, _ = _mux_d_graph(plant)
    _admit(plant, mux["id"], "WSSS-DT", "40.3", "SD_480I", 2000, 2000, 3)

    before = fx.read_multiplex(mux["id"], eng)
    resp = api.create_channel(
        fac.create_channel_payload(
            mux["id"], before["version"],
            call_sign="WTTT-DT", channel_number="40.4", service_class="PRIMARY",
            resolution_class="SD_480I", requested_bitrate_kbps=2000,
            floor_bitrate_kbps=2000, priority_rank=4,
        ),
        eng,
    )
    validate_error(resp, "ERR_BITRATE_FLOOR_UNSATISFIABLE")

    listed, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux["id"]})
    )
    assert meta["total_count"] == 3
    assert all(row["allocation_state"] == "ACTIVE" for row in listed)

    after = validate_success(api.get_multiplex(mux["id"], eng))
    assert after["version"] == before["version"]
    assert after["assigned_kbps"] == 11000


def test_resolution_minimum_outranks_the_floor_feasibility_gate(api):
    """A 1999 kbps SD_480I floor is refused on the resolution minimum, not on feasibility.

    PRD §3.2: "`floor_bitrate_kbps` must be at least the minimum for its
    `resolution_class` — 8000 for `HD_1080I`, 5000 for `HD_720P`, 2000 for `SD_480I` —
    where exactly the minimum is legal and one kilobit below it is not, yielding
    `ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM`."

    Design: Corner/calculations/floor_feasibility_is_checked_against_the_active_set_with_exact_equality_legal
    """
    plant = _plant_with_transmitter()
    eng = plant["eng_headers"]
    mux, (ch_p, _) = _mux_d_graph(plant)
    _admit(plant, mux["id"], "WSSS-DT", "40.3", "SD_480I", 2000, 2000, 3)

    current = fx.read_multiplex(mux["id"], eng)
    resp = api.create_channel(
        fac.create_subchannel_payload(
            mux["id"], current["version"], ch_p["id"],
            call_sign="WUUU-DT", channel_number="40.5",
            resolution_class="SD_480I", requested_bitrate_kbps=3000,
            floor_bitrate_kbps=1999, priority_rank=5,
        ),
        eng,
    )
    validate_error(resp, "ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM")

    _, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux["id"]})
    )
    assert meta["total_count"] == 3


# ===========================================================================
# The full pool and the derated pool
# ===========================================================================

def test_derated_pool_starves_the_priority_tail_and_reweights_the_remainder(api):
    """At 60 percent power the 20000 kbps pool shrinks to 14875 and ranks 3 and 4 starve.

    PRD §3.2: "take `total_capacity_kbps`, multiply by the parent transmitter's current
    `derate_factor`, truncate the product downward to a whole kilobit, subtract
    `pilot_reserved_kbps`, and floor the result at 0."

    PRD §3.2: "If the floor does not fit, the channel's `allocation_state` becomes
    `STARVED`, its `allocated_bitrate_kbps` is set to 0, and it is excluded from steps
    three through five entirely."

    Design: Corner/calculations/full_pool_and_derated_pool_variants_diverge_and_recovery_is_exact
    """
    plant = _plant_with_transmitter()
    eng = plant["eng_headers"]
    mux, channels = _mux_c_graph(plant)
    ch_a, ch_b, ch_c, ch_d = channels

    fx.change_power_state(plant, "REDUCED_POWER", power_pct=60,
                          reason="utility brownout")

    multiplex = validate_success(api.get_multiplex(mux["id"], eng))
    assert multiplex["effective_capacity_kbps"] == 14875

    rows = {c["call_sign"]: validate_success(api.get_channel(c["id"], eng))
            for c in channels}
    assert rows["WAAA-DT"]["allocated_bitrate_kbps"] == 8938
    assert rows["WBBB-DT"]["allocated_bitrate_kbps"] == 5937
    assert rows["WCCC-DT"]["allocated_bitrate_kbps"] == 0
    assert rows["WDDD-DT"]["allocated_bitrate_kbps"] == 0
    assert rows["WAAA-DT"]["allocation_state"] == "ACTIVE"
    assert rows["WBBB-DT"]["allocation_state"] == "ACTIVE"
    assert rows["WCCC-DT"]["allocation_state"] == "STARVED"
    assert rows["WDDD-DT"]["allocation_state"] == "STARVED"

    assert multiplex["assigned_kbps"] == 14875
    assert multiplex["available_kbps"] == 0
    assert multiplex["starved_channel_count"] == 2
    assert_bandwidth_conservation(multiplex)

    assert rows["WAAA-DT"]["posture"] == "DEGRADED"
    assert rows["WBBB-DT"]["posture"] == "DEGRADED"
    assert rows["WCCC-DT"]["posture"] == "SUSPENDED"
    assert rows["WDDD-DT"]["posture"] == "SUSPENDED"
    assert ch_a["id"] in {r["id"] for r in rows.values()}
    assert {ch_b["id"], ch_c["id"], ch_d["id"]} <= {r["id"] for r in rows.values()}


def test_restoring_full_power_reproduces_the_full_pool_allocations_exactly(api):
    """The starved channels re-enter the waterfall and every allocation returns exactly.

    PRD §3.1: "A clean restoration writes `current_power_pct` to 100 and `derate_factor`
    to 1.00 and re-runs the bitrate waterfall across every child multiplex: channels that
    had been `STARVED` and can now be granted their floor return to `allocation_state`
    `ACTIVE`, channels that had been held as `STANDBY` return to `STANDBY`, and every
    affected channel's `posture` is recomputed."

    Design: Corner/calculations/full_pool_and_derated_pool_variants_diverge_and_recovery_is_exact
    """
    plant = _plant_with_transmitter()
    eng = plant["eng_headers"]
    mux, channels = _mux_c_graph(plant)

    fx.change_power_state(plant, "REDUCED_POWER", power_pct=60,
                          reason="utility brownout")
    fx.change_power_state(plant, "FULL_POWER")

    multiplex = validate_success(api.get_multiplex(mux["id"], eng))
    assert multiplex["effective_capacity_kbps"] == 20000
    assert multiplex["assigned_kbps"] == 20000
    assert multiplex["available_kbps"] == 0
    assert multiplex["starved_channel_count"] == 0

    expected = {"WAAA-DT": 9091, "WBBB-DT": 6091, "WCCC-DT": 2546, "WDDD-DT": 2272}
    demand_before = {c["call_sign"]: (c["requested_bitrate_kbps"],
                                      c["floor_bitrate_kbps"], c["priority_rank"])
                     for c in channels}
    for channel in channels:
        row = validate_success(api.get_channel(channel["id"], eng))
        assert row["allocated_bitrate_kbps"] == expected[row["call_sign"]]
        assert row["allocation_state"] == "ACTIVE"
        assert (row["requested_bitrate_kbps"], row["floor_bitrate_kbps"],
                row["priority_rank"]) == demand_before[row["call_sign"]]

    _, meta = validate_paginated(
        api.list_channels(eng, params={"multiplex_id": mux["id"], "posture": "NORMAL"})
    )
    assert meta["total_count"] == 4


# ===========================================================================
# The channel posture ladder
# ===========================================================================

def test_posture_ladder_takes_the_first_matching_clause_at_every_step(api):
    """One major fault leaves NORMAL; two degrade; a critical, an override and an
    off-air transmitter each outrank what came before.

    PRD §3.3: "The five clauses are evaluated in a fixed order and **the first one that
    matches wins**, so a channel that satisfies several of them takes the earliest."

    PRD §3.3: "**exactly two major faults already degrade the channel**, one does not,
    and reduced transmitter power degrades every channel it carries on its own with no
    faults at all."

    Design: Corner/calculations/channel_posture_ladder_resolves_five_clauses_in_pinned_order
    """
    plant = fx.setup_base_plant()
    mco = plant["mco_headers"]
    channel_id = plant["ch1"]["id"]
    detected = "2026-08-01T09:00:00Z"

    fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR", detected)
    after_first = validate_success(api.get_channel(channel_id, mco))
    assert after_first["posture"] == "NORMAL"
    assert after_first["open_fault_count"] == 1

    fx.report_channel_fault(plant, "BLACK_FRAME", "MAJOR", detected)
    after_second = validate_success(api.get_channel(channel_id, mco))
    assert after_second["posture"] == "DEGRADED"
    assert after_second["open_fault_count"] == 2

    fx.report_channel_fault(plant, "ENCODER_FAILURE", "CRITICAL", detected)
    after_critical = validate_success(api.get_channel(channel_id, mco))
    assert after_critical["posture"] == "DEGRADED_CRITICAL"
    assert after_critical["open_fault_count"] == 3
    air_status_before_override = after_critical["air_status"]

    fx.setup_active_override(plant, "CRAWL")
    with_override = validate_success(api.get_channel(channel_id, mco))
    assert with_override["posture"] == "EMERGENCY"
    assert with_override["open_fault_count"] == 3
    assert with_override["air_status"] == air_status_before_override

    fx.change_power_state(plant, "OFF_AIR", reason="tower crew on site")
    dark = validate_success(api.get_channel(channel_id, mco))
    assert dark["allocation_state"] == "STARVED"
    assert dark["posture"] == "SUSPENDED"
    multiplex = validate_success(api.get_multiplex(plant["multiplex"]["id"],
                                                  plant["eng_headers"]))
    assert multiplex["effective_capacity_kbps"] == 0


def test_sibling_channel_is_suspended_by_the_shared_transmitter_without_faults(api):
    """Clause one reads the transmitter, so the fault-free sibling is SUSPENDED too.

    PRD §3.3: "First, `posture` is `SUSPENDED` if the channel's `allocation_state` is
    `STARVED` or its transmitter's `operational_state` is `OFF_AIR`."

    PRD §3.3: "In the same pass, `open_fault_count` is written as the total number of
    open faults on the channel regardless of severity."

    Design: Corner/calculations/channel_posture_ladder_resolves_five_clauses_in_pinned_order
    """
    plant = fx.setup_base_plant()
    mco = plant["mco_headers"]
    fx.report_channel_fault(plant, "AUDIO_LOSS", "MAJOR", "2026-08-01T09:00:00Z")
    fx.report_channel_fault(plant, "BLACK_FRAME", "MAJOR", "2026-08-01T09:00:00Z")

    fx.change_power_state(plant, "OFF_AIR", reason="tower crew on site")

    sibling = validate_success(api.get_channel(plant["ch2"]["id"], mco))
    assert sibling["posture"] == "SUSPENDED"
    assert sibling["open_fault_count"] == 0
    assert sibling["allocation_state"] == "STARVED"

    faulted = validate_success(api.get_channel(plant["ch1"]["id"], mco))
    assert faulted["posture"] == "SUSPENDED"
    assert faulted["open_fault_count"] == 2


# ===========================================================================
# Hourly commercial inventory
# ===========================================================================

def _inventory_assets(plant: dict) -> dict:
    """One passed programme asset and one passed spot asset."""
    return {
        "prog": fx.setup_qc_passed_asset(plant, 1800),
        "spot": fx.setup_qc_passed_asset(plant, 30),
    }


def _ingest_day(api, plant: dict, broadcast_day: str, schedule_start_utc: str,
                window_duration_seconds: int, items: list):
    """Book one day of elements on the primary channel as traffic."""
    return api.ingest_playlist(
        fac.ingest_playlist_payload(
            plant["ch1"]["id"], items,
            broadcast_day=broadcast_day,
            schedule_start_utc=schedule_start_utc,
            window_duration_seconds=window_duration_seconds,
        ),
        plant["traffic_headers"],
    )


def test_hour_carrying_exactly_960_commercial_seconds_validates(api):
    """Two 480-second commercials in hour zero make exactly the inclusive ceiling.

    PRD §3.5: "No hour may carry **more than 960 seconds — sixteen minutes — of
    commercial elements; exactly 960 is accepted and 961 is refused** with
    `ERR_COMMERCIAL_INVENTORY_EXCEEDED`."

    Design: Corner/calculations/commercial_inventory_buckets_by_start_hour_with_960_inclusive
    """
    plant = fx.setup_base_plant()
    assets = _inventory_assets(plant)
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": assets["prog"]["id"],
         "scheduled_start_utc": "2026-08-06T15:00:00Z",
         "scheduled_duration_seconds": 2640},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"],
         "scheduled_start_utc": "2026-08-06T15:44:00Z",
         "scheduled_duration_seconds": 480},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"],
         "scheduled_start_utc": "2026-08-06T15:52:00Z",
         "scheduled_duration_seconds": 480},
    ]
    playlist = validate_success(
        _ingest_day(api, plant, "2026-08-06", "2026-08-06T15:00:00Z", 3600, items), 201
    )
    assert playlist["commercial_seconds_by_hour"] == {"0": 960}

    validated = validate_success(
        api.change_playlist_state(playlist["id"],
                                  fac.playlist_state_payload("VALIDATED"),
                                  plant["pd_headers"])
    )
    assert validated["status"] == "VALIDATED"
    assert validated["commercial_seconds_by_hour"] == {"0": 960}


def test_straddling_commercial_is_booked_whole_into_its_start_hour(api):
    """A commercial starting 30 seconds before the hour boundary counts wholly in hour zero.

    PRD §3.5: "Each qualifying element is attributed to **exactly one hour, chosen by its
    `scheduled_start_utc`, even when the element straddles the hour boundary**: subtract
    the playlist's `schedule_start_utc` from the element's `scheduled_start_utc`, divide
    the resulting seconds by 3600 and truncate downward to get the zero-based hour index,
    then add that element's `scheduled_duration_seconds` to that hour's total."

    Design: Corner/calculations/commercial_inventory_buckets_by_start_hour_with_960_inclusive
    """
    plant = fx.setup_base_plant()
    assets = _inventory_assets(plant)
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": assets["prog"]["id"],
         "scheduled_start_utc": "2026-08-07T15:00:00Z",
         "scheduled_duration_seconds": 3570},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"],
         "scheduled_start_utc": "2026-08-07T15:59:30Z",
         "scheduled_duration_seconds": 480},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": assets["spot"]["id"],
         "scheduled_start_utc": "2026-08-07T16:07:30Z",
         "scheduled_duration_seconds": 480},
    ]
    playlist = validate_success(
        _ingest_day(api, plant, "2026-08-07", "2026-08-07T15:00:00Z", 4530, items), 201
    )
    assert playlist["commercial_seconds_by_hour"] == {"0": 480, "1": 480}

    reread = validate_success(api.get_playlist(playlist["id"], plant["traffic_headers"]))
    assert reread["commercial_seconds_by_hour"] == {"0": 480, "1": 480}


def test_promo_and_interstitial_seconds_never_enter_the_inventory_map(api):
    """The reference day books 60 commercial seconds in hour zero and nothing else.

    PRD §3.5: "Only items whose `element_kind` is `COMMERCIAL` count — **`PROMO` and
    `INTERSTITIAL` elements are not commercial inventory** — and items already `SKIPPED`
    or `PREEMPTED` are excluded, so a preemption frees inventory for a makegood in the
    same hour."

    Design: Corner/calculations/commercial_inventory_buckets_by_start_hour_with_960_inclusive
    """
    scenario = fx.setup_playlist_scenario()
    playlist = validate_success(
        api.get_playlist(scenario["playlist"]["id"], scenario["traffic_headers"])
    )
    assert playlist["commercial_seconds_by_hour"] == {"0": 60}
    kinds = {item["element_kind"] for item in scenario["items"]}
    assert {"PROMO", "INTERSTITIAL"} <= kinds


# ===========================================================================
# The two timing-variance figures
# ===========================================================================

def _variance_day(api, plant: dict):
    """Two 300-second programmes booked across a 600-second window.

    Booked seconds equal the window exactly, so both variance figures start at 0.
    """
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": fx.setup_qc_passed_asset(plant, 300)["id"],
         "scheduled_start_utc": "2026-08-01T14:00:00Z",
         "scheduled_duration_seconds": 300},
        {"sequence_number": 2, "element_kind": "PROGRAM",
         "asset_id": fx.setup_qc_passed_asset(plant, 300)["id"],
         "scheduled_start_utc": "2026-08-01T14:05:00Z",
         "scheduled_duration_seconds": 300},
    ]
    return api.ingest_playlist(
        fac.ingest_playlist_payload(
            plant["ch1"]["id"], items,
            schedule_start_utc="2026-08-01T14:00:00Z",
            window_duration_seconds=600,
        ),
        plant["traffic_headers"],
    )


def _air_element_one_short(plant: dict, playlist_id: str):
    """Take the window to air and play element one 60 seconds short."""
    fx.drive_playlist(plant, playlist_id, "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist_id, "ARMED")
    fx.set_clock("2026-08-01T13:55:00Z")
    fx.drive_playlist(plant, playlist_id, "ON_AIR")
    items = fx.list_items(playlist_id, plant["traffic_headers"])
    fx.air_item(plant, item_by_sequence(items, 1),
                "2026-08-01T14:00:00Z", "2026-08-01T14:04:00Z", 240)
    return fx.list_items(playlist_id, plant["traffic_headers"])


def test_short_air_moves_the_asrun_figure_while_the_projected_figure_holds(api):
    """A 240-second air of a 300-second booking leaves projected at 0 and as-run at -60.

    PRD §3.5: "`projected_end_variance_seconds` is the forward-looking figure: sum
    `scheduled_duration_seconds` over every item of the playlist whose `playout_status`
    is not `SKIPPED` and not `PREEMPTED`, then subtract `window_duration_seconds`. It
    trusts the booked schedule for everything that has not been dropped, **including
    items that already aired short**."

    PRD §3.5: "`asrun_end_variance_seconds` is the chronological figure: walk the items
    in `sequence_number` ascending order accumulating, for each, its
    `measured_duration_seconds` when its `playout_status` is `PLAYED` or `TRUNCATED`,
    zero when its `playout_status` is `SKIPPED` or `PREEMPTED`, and its
    `scheduled_duration_seconds` in every other case; then subtract
    `window_duration_seconds`."

    Design: Corner/calculations/projected_and_as_run_variance_variants_diverge_on_the_same_rows
    """
    plant = fx.setup_base_plant()
    booked = validate_success(_variance_day(api, plant), 201)
    assert booked["projected_end_variance_seconds"] == 0
    assert booked["asrun_end_variance_seconds"] == 0

    items = _air_element_one_short(plant, booked["id"])
    first = item_by_sequence(items, 1)
    second = item_by_sequence(items, 2)
    assert first["playout_status"] == "PLAYED"
    assert first["measured_duration_seconds"] == 240
    assert second["playout_status"] == "SCHEDULED"

    aired = validate_success(api.get_playlist(booked["id"], plant["traffic_headers"]))
    assert aired["projected_end_variance_seconds"] == 0
    assert aired["asrun_end_variance_seconds"] == -60


def test_close_skips_the_tail_and_moves_both_variance_figures_apart(api):
    """Skipping the 300-second tail drives projected to -300 and as-run to -360.

    PRD §3.5: "The close writes `closed_at_utc` at the current logical time, flips every
    item still in `SCHEDULED` or `CUED` to `SKIPPED` with a system-sourced skip row
    appended to the as-run log for each".

    PRD §3.5: "A truncated element therefore shortens the as-run day while the projected
    figure still counts its full booked length."

    Design: Corner/calculations/projected_and_as_run_variance_variants_diverge_on_the_same_rows
    """
    plant = fx.setup_base_plant()
    booked = validate_success(_variance_day(api, plant), 201)
    _air_element_one_short(plant, booked["id"])

    fx.set_clock("2026-08-01T14:10:00Z")
    closed = validate_success(
        api.change_playlist_state(booked["id"],
                                  fac.playlist_state_payload("CLOSED"),
                                  plant["pd_headers"])
    )
    assert closed["status"] == "CLOSED"
    assert closed["projected_end_variance_seconds"] == -300
    assert closed["asrun_end_variance_seconds"] == -360

    items = fx.list_items(booked["id"], plant["traffic_headers"])
    assert item_by_sequence(items, 1)["playout_status"] == "PLAYED"
    assert item_by_sequence(items, 2)["playout_status"] == "SKIPPED"


# ===========================================================================
# The backtiming plan branches
# ===========================================================================

def _plan_window(api, scn: dict, join_utc: str, breakaway_utc: str):
    """Plan one TOLERANT window anchored on the network join of the reference day."""
    return api.create_feed_window(
        fac.create_feed_window_payload(
            scn["ch1"]["id"], 4, join_utc, breakaway_utc,
            backtiming_mode="TOLERANT", guard_seconds=2, live_encoder_units=1,
        ),
        scn["mco_headers"],
    )


def test_slack_beyond_tolerance_pads_to_the_filler_ceiling_and_records_dead_air(api):
    """A 180-second hole yields 120 seconds of filler and 60 seconds of dead air.

    PRD §3.7: "Otherwise, if the **slack exceeds tolerance** — the local tail is too
    short and there is dead time to fill — the action is `PAD_WITH_FILLER`. The pad is
    the smaller of the slack and a ceiling of 120 seconds, and any slack the pad cannot
    absorb is recorded as `residual_dead_air_seconds`."

    Design: Corner/calculations/backtime_plan_selects_all_four_branches_at_pinned_boundaries
    """
    scn = fx.setup_on_air_playlist()
    window = validate_success(
        _plan_window(api, scn, "2026-08-01T12:31:00Z", "2026-08-01T12:31:30Z"), 201
    )
    assert window["state"] == "PLANNED"
    assert window["plan_computed_utc"] == "2026-08-01T11:59:00Z"
    assert window["plan_action"] == "PAD_WITH_FILLER"
    assert window["backtime_pad_seconds"] == 120
    assert window["residual_dead_air_seconds"] == 60
    assert window["backtime_trim_seconds"] == 0
    assert window["skipped_item_sequences"] == []
    assert window["late_join_seconds"] == 0


def test_deficit_inside_the_trimmable_pool_trims_the_tail(api):
    """A 30-second overrun is absorbed by trimming, since the pool of 50 covers it.

    PRD §3.7: "If the trimmable pool covers the deficit, the action is `TRIM_TAIL` with
    the trim equal to the whole deficit and no skips; the trim is consumed in ascending
    `sequence_number` order, each element giving the smaller of the remaining need and
    its own trimmable allowance."

    Design: Corner/calculations/backtime_plan_selects_all_four_branches_at_pinned_boundaries
    """
    scn = fx.setup_on_air_playlist()
    window = validate_success(
        _plan_window(api, scn, "2026-08-01T12:27:30Z", "2026-08-01T12:28:00Z"), 201
    )
    assert window["plan_action"] == "TRIM_TAIL"
    assert window["backtime_trim_seconds"] == 30
    assert window["backtime_pad_seconds"] == 0
    assert window["residual_dead_air_seconds"] == 0
    assert window["skipped_item_sequences"] == []
    assert window["late_join_seconds"] == 0


def test_slack_exactly_equal_to_the_tolerance_is_a_hard_cut(api):
    """Fifteen seconds of slack against a tolerance of 15 cuts hard rather than trims.

    PRD §3.7: "Otherwise, if the **absolute value of the slack is within tolerance**, the
    action is `HARD_CUT` with no pad, no trim, no skips and no late-join seconds. **A
    slack exactly equal to the tolerance is a hard cut**, not a pad and not a trim."

    PRD §3.7: "In `TOLERANT` mode it is the larger of `guard_seconds` and a proportional
    allowance, where that allowance is the smaller of two percent of the pending tail —
    the pending tail multiplied by 0.02 and truncated downward to whole seconds — and a
    hard cap of 15 seconds."

    Design: Corner/calculations/backtime_plan_selects_all_four_branches_at_pinned_boundaries
    """
    scn = fx.setup_on_air_playlist()
    window = validate_success(
        _plan_window(api, scn, "2026-08-01T12:28:15Z", "2026-08-01T12:28:45Z"), 201
    )
    assert window["plan_action"] == "HARD_CUT"
    assert window["backtime_pad_seconds"] == 0
    assert window["backtime_trim_seconds"] == 0
    assert window["residual_dead_air_seconds"] == 0
    assert window["late_join_seconds"] == 0
    assert window["skipped_item_sequences"] == []


def test_deficit_beyond_the_trimmable_pool_skips_only_what_the_need_requires(api):
    """A 60-second overrun takes the whole 50-second pool then drops the promo alone.

    PRD §3.7: "If the trimmable pool does not cover the deficit, the trim takes the
    entire pool and the remaining need is met by dropping whole elements: walking the
    tail in ascending `sequence_number` order, each element whose `element_kind` is
    `PROMO`, `INTERSTITIAL` or `FILLER` is added to `skipped_item_sequences` and the need
    is reduced by that element's `scheduled_duration_seconds` less whatever trim was
    already taken from it, stopping as soon as the need is met."

    PRD §3.7: "Computing a plan writes `plan_computed_utc` at the current logical time."

    Design: Corner/calculations/backtime_plan_selects_all_four_branches_at_pinned_boundaries
    """
    scn = fx.setup_on_air_playlist()
    window = validate_success(
        _plan_window(api, scn, "2026-08-01T12:27:00Z", "2026-08-01T12:27:20Z"), 201
    )
    assert window["plan_action"] == "SKIP_ELEMENTS"
    assert window["backtime_trim_seconds"] == 50
    assert window["skipped_item_sequences"] == [5]
    assert window["backtime_pad_seconds"] == 0
    assert window["late_join_seconds"] == 0

    items, _meta = validate_paginated(
        api.list_playlist_items(scn["playlist"]["id"], scn["traffic_headers"])
    )
    for sequence, booked in ((2, 30), (3, 30), (5, 60), (6, 60), (7, 1320)):
        element = item_by_sequence(items, sequence)
        assert element["playout_status"] == "SCHEDULED"
        assert element["scheduled_duration_seconds"] == booked
        assert element["trim_applied_seconds"] == 0
