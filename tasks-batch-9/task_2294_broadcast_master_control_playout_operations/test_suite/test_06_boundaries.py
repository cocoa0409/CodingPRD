"""Inclusive boundaries: the last accepted value and the first refused one.

Three separate ceilings and floors are probed here, each through its own
endpoint — commercial seconds inside one clock hour on playlist ingest, live
encoder units of aggregate occupancy on feed-window planning, and quality points
on a QC waiver. Every pair pins the limit value as accepted and the value one
unit past it as refused, so an implementation using a strict comparison where the
PRD writes an inclusive one fails exactly one half of each pair.
"""
from test_helpers import (
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD §2.4: the logical clock only moves when a client asks it to; every
# scenario pins it before building anything.
_CLOCK = "2026-08-01T10:00:00Z"


# ===========================================================================
# Ceiling 1 — 960 commercial seconds in one clock hour
# ===========================================================================

def _inventory_bench():
    """A channel, a four-spot order and three graded masters of 840, 480 and 481 s.

    Hour zero of a day that starts at 12:00:00Z runs up to but not including
    13:00:00Z, so every element below lands in bucket "0".
    """
    plant = fx.setup_base_plant(with_subchannel=False, clock_utc=_CLOCK)
    order = fx.create_order(plant, ordered_spots=4, unit_duration_seconds=30,
                            priority_class="REMNANT",
                            makegood_deadline_utc="2026-08-20T00:00:00Z")
    return {
        "plant": plant,
        "order": order,
        "programme": fx.setup_qc_passed_asset(plant, 840),
        "spot480": fx.setup_qc_passed_asset(plant, 480),
        "spot481": fx.setup_qc_passed_asset(plant, 481),
    }


def _inventory_items(bench, third_asset_id, third_duration_seconds, day):
    """One programme plus two back-to-back commercials, all inside hour zero."""
    return [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": bench["programme"]["id"],
         "scheduled_start_utc": f"{day}T12:00:00Z",
         "scheduled_duration_seconds": 840, "max_trim_seconds": 0},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": bench["spot480"]["id"], "spot_order_id": bench["order"]["id"],
         "scheduled_start_utc": f"{day}T12:14:00Z",
         "scheduled_duration_seconds": 480, "max_trim_seconds": 0},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": third_asset_id, "spot_order_id": bench["order"]["id"],
         "scheduled_start_utc": f"{day}T12:22:00Z",
         "scheduled_duration_seconds": third_duration_seconds,
         "max_trim_seconds": 0},
    ]


def _first_day(bench):
    """The pinned 480 + 480 day on 2026-08-01, driven to VALIDATED."""
    playlist = fx.ingest(
        bench["plant"],
        _inventory_items(bench, bench["spot480"]["id"], 480, "2026-08-01"),
        broadcast_day="2026-08-01",
        schedule_start_utc="2026-08-01T12:00:00Z",
        window_duration_seconds=1800,
    )
    assert playlist["commercial_seconds_by_hour"] == {"0": 960}
    return playlist


def test_hour_holding_exactly_960_commercial_seconds_is_accepted(api):
    """Two 480-second spots in one hour sit exactly on the ceiling.

    PRD §3.5: "No hour may carry **more than 960 seconds — sixteen minutes — of
    commercial elements; exactly 960 is accepted and 961 is refused** with
    `ERR_COMMERCIAL_INVENTORY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/commercial_inventory_960_seconds_accepted_961_rejected
    """
    bench = _inventory_bench()
    plant = bench["plant"]

    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(
            plant["ch1"]["id"],
            _inventory_items(bench, bench["spot480"]["id"], 480, "2026-08-01"),
            broadcast_day="2026-08-01",
            schedule_start_utc="2026-08-01T12:00:00Z",
            window_duration_seconds=1800,
        ),
        plant["traffic_headers"],
    )
    playlist = validate_success(resp, 201)
    assert playlist["commercial_seconds_by_hour"] == {"0": 960}

    validated = fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    assert validated["status"] == "VALIDATED", \
        "the 960-second hour must clear the validation gate too"
    assert validated["commercial_seconds_by_hour"] == {"0": 960}


def test_hour_holding_961_commercial_seconds_is_refused(api):
    """Stretching one spot by a single second breaks the same hour.

    PRD §3.5: "exactly 960 is accepted and 961 is refused" — the attribution is
    "**exactly one hour, chosen by its `scheduled_start_utc`, even when the
    element straddles the hour boundary**".

    Design: Difficulty/boundary_precision_check/commercial_inventory_960_seconds_accepted_961_rejected
    """
    bench = _inventory_bench()
    plant = bench["plant"]
    _first_day(bench)

    resp = api.ingest_playlist(
        factories.ingest_playlist_payload(
            plant["ch1"]["id"],
            _inventory_items(bench, bench["spot481"]["id"], 481, "2026-08-02"),
            broadcast_day="2026-08-02",
            schedule_start_utc="2026-08-02T12:00:00Z",
            window_duration_seconds=1801,
        ),
        plant["traffic_headers"],
    )
    validate_error(resp, "ERR_COMMERCIAL_INVENTORY_EXCEEDED")

    playlists, _meta = validate_paginated(
        api.list_channel_playlists(plant["ch1"]["id"], plant["mco_headers"],
                                   {"broadcast_day": "2026-08-02"})
    )
    assert playlists == [], "a refused ingest must leave no playlist behind"

    kept, _meta2 = validate_paginated(
        api.list_channel_playlists(plant["ch1"]["id"], plant["mco_headers"],
                                   {"broadcast_day": "2026-08-01"})
    )
    assert len(kept) == 1
    assert kept[0]["commercial_seconds_by_hour"] == {"0": 960}


# ===========================================================================
# Ceiling 2 — live encoder units of aggregate occupancy on the multiplex
# ===========================================================================

def _encoder_bench():
    """Two channels on one two-unit multiplex, each with an ARMED anchor day.

    Both days book a 1740-second programme from 12:00:00Z followed by a 60-second
    NETWORK_JOIN at 12:29:00Z, so sequence number 2 resolves as an anchor on
    either channel and the 1800-second total matches the window.
    """
    plant = fx.setup_base_plant(clock_utc=_CLOCK)
    assert plant["multiplex"]["live_encoder_units_total"] == 2
    asset = fx.setup_qc_passed_asset(plant, 1740)

    for channel_key in ("ch1", "ch2"):
        items = [
            {"sequence_number": 1, "element_kind": "PROGRAM", "asset_id": asset["id"],
             "scheduled_start_utc": "2026-08-01T12:00:00Z",
             "scheduled_duration_seconds": 1740, "max_trim_seconds": 0},
            {"sequence_number": 2, "element_kind": "NETWORK_JOIN",
             "scheduled_start_utc": "2026-08-01T12:29:00Z",
             "scheduled_duration_seconds": 60, "max_trim_seconds": 0},
        ]
        playlist = fx.ingest(plant, items, channel_id=plant[channel_key]["id"],
                             window_duration_seconds=1800)
        fx.drive_playlist(plant, playlist["id"], "VALIDATED")
        armed = fx.drive_playlist(plant, playlist["id"], "ARMED")
        assert armed["status"] == "ARMED"

    first = fx.create_window(plant, "2026-08-01T12:00:00Z", "2026-08-01T12:10:00Z",
                             channel_id=plant["ch1"]["id"], anchor_sequence_number=2,
                             backtiming_mode="STRICT", guard_seconds=2,
                             live_encoder_units=2)
    second = fx.create_window(plant, "2026-08-01T12:10:00Z", "2026-08-01T12:20:00Z",
                              channel_id=plant["ch2"]["id"], anchor_sequence_number=2,
                              feed_source="NETWORK_ALT", backtiming_mode="STRICT",
                              guard_seconds=2, live_encoder_units=2)
    return {"plant": plant, "first": first, "second": second}


def _mux_peak(plant):
    return fx.read_multiplex(plant["multiplex"]["id"],
                             plant["eng_headers"])["live_encoder_units_peak"]


def test_touching_windows_reach_a_peak_exactly_equal_to_the_total(api):
    """Two two-unit windows that touch at one instant occupy the pool exactly once.

    PRD §3.7: "Occupancy is measured on the **half-open** span from `join_utc` up
    to but not including `breakaway_utc`, so a window that ends at an instant
    frees its units for a window starting at that same instant."

    Design: Difficulty/boundary_precision_check/encoder_peak_equal_to_total_accepted_one_unit_over_rejected
    """
    bench = _encoder_bench()
    plant = bench["plant"]

    assert bench["first"]["state"] == "PLANNED"
    assert bench["first"]["live_encoder_units"] == 2
    assert bench["second"]["state"] == "PLANNED", \
        "at the shared instant the release is applied before the claim"
    assert bench["second"]["live_encoder_units"] == 2
    assert _mux_peak(plant) == 2, "the peak sits exactly on the two-unit total"


def test_one_unit_over_the_encoder_total_is_refused(api):
    """A single extra unit inside the second window pushes the pool past its total.

    PRD §3.7: "The proposed window is refused with
    `ERR_ENCODER_CAPACITY_EXCEEDED` when the resulting peak would **exceed**
    `live_encoder_units_total`; **a peak exactly equal to the total is
    accepted**, and a peak one unit above it is not."

    Design: Difficulty/boundary_precision_check/encoder_peak_equal_to_total_accepted_one_unit_over_rejected
    """
    bench = _encoder_bench()
    plant = bench["plant"]

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            plant["ch1"]["id"], 2, "2026-08-01T12:12:00Z", "2026-08-01T12:18:00Z",
            feed_source="SYNDICATED_LIVE", backtiming_mode="STRICT",
            guard_seconds=2, live_encoder_units=1,
        ),
        plant["mco_headers"],
    )
    error = validate_error(resp, "ERR_ENCODER_CAPACITY_EXCEEDED")
    assert error["error_id"] != "ERR_FEED_WINDOW_OVERLAP", \
        "the guarded span 12:11:58Z-12:18:02Z is clear of this channel's own window"

    assert _mux_peak(plant) == 2, "a refused plan must not move the recorded peak"
    ch1_windows, _m1 = validate_paginated(
        api.list_channel_feed_windows(plant["ch1"]["id"], plant["mco_headers"])
    )
    ch2_windows, _m2 = validate_paginated(
        api.list_channel_feed_windows(plant["ch2"]["id"], plant["mco_headers"])
    )
    assert [w["id"] for w in ch1_windows] == [bench["first"]["id"]]
    assert [w["id"] for w in ch2_windows] == [bench["second"]["id"]]


def test_one_unit_starting_when_the_pool_frees_is_accepted(api):
    """The same extra unit is legal the moment the earlier claim is released.

    PRD §3.7: "Because releases precede claims at equal instants, back-to-back
    windows are feasible even at full capacity."

    Design: Difficulty/boundary_precision_check/encoder_peak_equal_to_total_accepted_one_unit_over_rejected
    """
    bench = _encoder_bench()
    plant = bench["plant"]

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            plant["ch1"]["id"], 2, "2026-08-01T12:20:00Z", "2026-08-01T12:26:00Z",
            feed_source="SYNDICATED_LIVE", backtiming_mode="STRICT",
            guard_seconds=2, live_encoder_units=1,
        ),
        plant["mco_headers"],
    )
    created = validate_success(resp, 201)
    assert created["state"] == "PLANNED"
    assert created["live_encoder_units"] == 1
    assert _mux_peak(plant) == 2, "the third window never lifts the peak above two"


# ===========================================================================
# Floor 3 — the 40-point waiver floor on a failed asset
# ===========================================================================

def _failed_asset_scoring(plant, measured_duration_seconds, defect_codes,
                          expected_score, expected_penalties):
    """A QC_FAILED asset whose governing ingest report scores a pinned figure.

    The master is booked at 100 seconds and delivered at -30.0 LKFS, which is
    6.0 LKFS from the station target and therefore outside tolerance, so every
    report below carries the flat 12-point loudness penalty.
    """
    asset = fx.create_asset(plant, expected_duration_seconds=100)
    delivered = fx.deliver_asset(
        plant, asset["id"],
        measured_duration_seconds=measured_duration_seconds,
        audio_loudness_lkfs=-30.0,
    )
    report = fx.submit_qc(plant, asset["id"], delivered["version"],
                          defect_codes=defect_codes,
                          measured_duration_seconds=measured_duration_seconds)
    assert report["technical_score"] == expected_score
    assert report["verdict"] == "FAIL"
    assert report["defect_penalty_points"] == expected_penalties[0]
    assert report["duration_penalty_points"] == expected_penalties[1]
    assert report["loudness_penalty_points"] == expected_penalties[2]
    assert report["fault_penalty_points"] == 0

    graded = fx.read_asset(asset["id"])
    assert graded["status"] == "QC_FAILED"
    assert graded["technical_score_ingest"] == expected_score
    return graded


def test_waiver_of_an_asset_scoring_exactly_forty_is_granted(api):
    """A master sitting exactly on the floor is still waivable.

    PRD §3.4: "The governing non-superseded ingest score in
    `technical_score_ingest` must be at least 40 — **exactly 40 is waivable, 39
    is not** — otherwise `ERR_QC_WAIVER_SCORE_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/waiver_accepts_score_exactly_40_and_refuses_39
    """
    plant = fx.bootstrap_operators(clock_utc=_CLOCK)
    asset = _failed_asset_scoring(plant, 120, ["BLACK_FRAMES"], 40, (18, 30, 12))

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(
            plant["pd"]["id"],
            waiver_justification=(
                "Only usable master available; black frames trimmed in master control."
            ),
        ),
        plant["pd_headers"],
    )
    waived = validate_success(resp)
    assert waived["status"] == "QC_WAIVED"
    assert waived["waived_by_operator_id"] == plant["pd"]["id"]
    assert waived["technical_score_ingest"] == 40
    assert fx.read_asset(asset["id"])["status"] == "QC_WAIVED"


def test_waiver_of_an_asset_scoring_thirty_nine_is_refused(api):
    """One point below the floor the same signature is refused.

    PRD §3.4: "exactly 40 is waivable, 39 is not — otherwise
    `ERR_QC_WAIVER_SCORE_TOO_LOW`". The score follows PRD §3.4's arithmetic: a
    6-second discrepancy against a 100-second booking is "divided by two, that
    quotient is rounded *upward* to the next whole number, the result is
    multiplied by 3".

    Design: Difficulty/boundary_precision_check/waiver_accepts_score_exactly_40_and_refuses_39
    """
    plant = fx.bootstrap_operators(clock_utc=_CLOCK)
    asset = _failed_asset_scoring(
        plant, 106,
        ["LOUDNESS_OUT_OF_SPEC", "BLACK_FRAMES", "VIDEO_ARTIFACT"],
        39, (40, 9, 12),
    )

    resp = api.sign_qc_waiver(
        asset["id"],
        factories.qc_waiver_payload(
            plant["pd"]["id"],
            waiver_justification=(
                "Only usable master available; black frames trimmed in master control."
            ),
        ),
        plant["pd_headers"],
    )
    validate_error(resp, "ERR_QC_WAIVER_SCORE_TOO_LOW")

    after = fx.read_asset(asset["id"])
    assert after["status"] == "QC_FAILED", "a refused waiver leaves the failure standing"
    assert after.get("waived_by_operator_id") is None
    assert after.get("waiver_justification") is None
    assert after["technical_score_ingest"] == 39
