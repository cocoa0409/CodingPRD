"""Tap-line lifecycle, vacuum leak cascade, repair hysteresis gate
(PRD §2.8, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_line,
    begin_tapping,
    create_bush,
    create_line,
    create_vacuum_reading_payload,
    setup_live_operation,
    setup_open_season,
    validate_error,
    validate_success,
)


def test_go_live_with_installing_line_rejected(api, manager_headers):
    """PRD §3.2: "It requires at least one tap line of the bush in a status
    other than `PULLED`, and every such non-`PULLED` line must be in `ACTIVE`
    (otherwise `ERR_TAP_LINES_NOT_READY`)"

    Design: Corner/state_machines/go_live_with_installing_line_rejected
    """
    season = setup_open_season()
    bush = create_bush(season["id"])
    begin_tapping(bush["id"])
    create_line(bush["id"])  # stays INSTALLING

    res = api.go_live(bush["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_TAP_LINES_NOT_READY)

    after = validate_success(api.get_sugarbush(bush["id"], manager_headers), 200)
    assert after["status"] == "TAPPING"


def test_vacuum_reading_below_threshold_leaks_line(api, manager_headers):
    """PRD §3.2: "When a reading lands on a line in `ACTIVE` and the observed
    `inhg` is strictly below the line's `vacuum_target_inhg` minus 2.0 inches —
    note that a reading exactly at the threshold does *not* constitute a leak —
    the line automatically moves `ACTIVE → LEAK`."
    PRD §2.8: "A sugarbush's `taps_set` is the sum of `tap_count` over its tap
    lines whose status is `ACTIVE` or `LEAK` (lines in `INSTALLING` or `PULLED`
    are never counted). A sugarbush's `taps_live` is the sum of `tap_count`
    over its tap lines whose status is `ACTIVE`."

    Design: Difficulty/transitive_cascade/vacuum_leak_cascade_depth4
    """
    ctx = setup_live_operation()  # one ACTIVE 100-tap line, target 25.0
    res = api.create_vacuum_reading(
        ctx["line"]["id"], create_vacuum_reading_payload(22.9), manager_headers)
    validate_success(res, 201)

    line = validate_success(api.get_tap_line(ctx["line"]["id"], manager_headers), 200)
    assert line["status"] == "LEAK"
    assert line["latest_vacuum_inhg"] == pytest.approx(22.9, abs=0.004)

    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["taps_set"] == 100, "LEAK lines still count toward taps_set"
    assert bush["taps_live"] == 0


def test_vacuum_leak_cascade_demotes_bush_and_season(api, manager_headers):
    """PRD §3.2: "That leak cascades: the bush's `taps_set` and `taps_live` are
    recomputed (the line's `tap_count` drops out of `taps_live`); if the bush
    was `LIVE` and its `taps_live` has fallen to zero, the bush automatically
    regresses `LIVE → TAPPING`; and the season's `taps_live` is recomputed."

    Design: Difficulty/transitive_cascade/vacuum_leak_cascade_depth4
    """
    ctx = setup_live_operation()
    season_before = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season_before["taps_live"] == 100

    validate_success(
        api.create_vacuum_reading(ctx["line"]["id"],
                                  create_vacuum_reading_payload(22.9),
                                  manager_headers),
        201)

    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["status"] == "TAPPING", "bush auto-regresses LIVE -> TAPPING at zero live taps"
    season = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season["taps_live"] == 0


def test_repair_vacuum_hysteresis_gate(api, manager_headers):
    """PRD §3.2: "Repairing a leaking line moves `LEAK → ACTIVE`. It is allowed
    only when the bush is in `TAPPING` or `LIVE`, and only when the line's
    latest vacuum reading shows an `inhg` of at least the line's
    `vacuum_target_inhg` minus 0.5 inches — the repair gate is inclusive, so a
    reading exactly at that floor passes; a lower reading is rejected with
    `ERR_VACUUM_STILL_LOW`."

    Design: Corner/state_machines/repair_vacuum_hysteresis_gate
    """
    ctx = setup_live_operation()
    # 22.0 < 25.0 - 2.0 -> LEAK
    validate_success(
        api.create_vacuum_reading(ctx["line"]["id"],
                                  create_vacuum_reading_payload(22.0),
                                  manager_headers),
        201)
    line = validate_success(api.get_tap_line(ctx["line"]["id"], manager_headers), 200)
    assert line["status"] == "LEAK"
    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["taps_set"] == 100, "LEAK lines still count toward taps_set"

    # Latest reading 24.4 < 25.0 - 0.5 -> repair rejected
    validate_success(
        api.create_vacuum_reading(ctx["line"]["id"],
                                  create_vacuum_reading_payload(24.4),
                                  manager_headers),
        201)
    res = api.repair_tap_line(ctx["line"]["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_VACUUM_STILL_LOW)

    # Latest reading 24.5 == 25.0 - 0.5 -> inclusive gate passes
    validate_success(
        api.create_vacuum_reading(ctx["line"]["id"],
                                  create_vacuum_reading_payload(24.5),
                                  manager_headers),
        201)
    repaired = validate_success(api.repair_tap_line(ctx["line"]["id"], manager_headers), 200)
    assert repaired["status"] == "ACTIVE"
