"""Syndication clearances and barter avails: overlap geometry, clearance
status gate, avail OCC, window half-open bounds, disaffirm cascade
(PRD §3.1, §3.2, §3.9, §2.7)."""
from test_helpers import (
    PD,
    TD,
    ApiErrorId,
    create_active_clock,
    create_clearance,
    create_clock,
    create_clock_payload,
    create_locked_log,
    create_rate_card,
    create_station,
    get_success_data,
    make_headers,
    schedule_barter_avail,
    schedule_barter_avail_ok,
    set_clock,
    setup_bookable_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_clock_weekday_overlap_blocks_second_activate(api):
    """PRD §3.1: "Activating a clock (a `DRAFT → ACTIVE` transition by a
    `ProgramDirector`) enforces weekday-set disjointness against the station's
    other `ACTIVE` clocks: if any existing `ACTIVE` clock's `applies_weekdays`
    intersects the candidate's, the activation is rejected with
    `ERR_CLOCK_WEEKDAY_OVERLAP`."

    Design: Corner/validations/clock_weekday_overlap_blocks_second_activate
    """
    station = create_station()
    c1 = create_clock(station["id"], applies_weekdays=["MON"], slots=[])
    get_success_data(api.activate_clock(c1["id"], PD))
    c2 = create_clock(station["id"], applies_weekdays=["MON", "WED"], slots=[])
    c3 = create_clock(station["id"], applies_weekdays=["TUE"], slots=[])

    resp = api.activate_clock(c2["id"], PD)
    validate_error(resp, ApiErrorId.ERR_CLOCK_WEEKDAY_OVERLAP)

    activated = get_success_data(api.activate_clock(c3["id"], PD))
    assert activated["status"] == "ACTIVE", "disjoint weekday set activates fine"


def test_rate_window_overlap_rejected_but_adjacent_allowed(api):
    """PRD §3.2: "Creating an entry whose (`station_id`, `daypart`) pair,
    weekday set, and effective window all intersect an existing `ACTIVE` entry
    is rejected with `ERR_RATE_WINDOW_OVERLAP`." Entries carry "an effective
    window from `effective_from` through `effective_to` (inclusive both ends)",
    so back-to-back windows do not intersect.

    Design: Corner/validations/rate_window_overlap_rejected_but_adjacent_allowed
    """
    station = create_station()
    create_rate_card(station["id"], effective_from="2026-01-01", effective_to="2026-06-30")

    resp = api.create_rate_card_entry(
        {
            "station_id": station["id"], "daypart": "MORNING_DRIVE",
            "weekday_set": ["MON"], "base_rate_cents": 1200, "min_rate_cents": 100,
            "effective_from": "2026-05-01", "effective_to": "2026-12-31",
        },
        make_headers("SalesManager", "mgr-1"),
    )
    validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)

    adjacent = get_success_data(
        api.create_rate_card_entry(
            {
                "station_id": station["id"], "daypart": "MORNING_DRIVE",
                "weekday_set": ["MON"], "base_rate_cents": 1200, "min_rate_cents": 100,
                "effective_from": "2026-07-01", "effective_to": "2026-12-31",
            },
            make_headers("SalesManager", "mgr-1"),
        )
    )
    assert adjacent["status"] == "ACTIVE", "2026-07-01 starts the day after 2026-06-30 ends"


# ---------------------------------------------------------------------------
# Clearance overlap: half-open hour windows, adjacency allowed
# ---------------------------------------------------------------------------

def _setup_clearance_overlap_env(api):
    station = create_station()
    c1 = create_clearance(station["id"], start_hour=10, duration_hours=4,
                          effective_from="2026-01-01", effective_to="2026-12-31")
    get_success_data(api.clear_clearance(c1["id"], PD))
    c2 = create_clearance(station["id"], start_hour=13, duration_hours=2,
                          effective_from="2026-06-01", effective_to="2026-12-31")
    c3 = create_clearance(station["id"], start_hour=14, duration_hours=2,
                          effective_from="2026-01-01", effective_to="2026-12-31")
    return {"station": station, "c1": c1, "c2": c2, "c3": c3}


def test_clearance_overlap_rejected(api):
    """PRD §3.9: "Clearing one (`PENDING → CLEARED`) is blocked when another
    `CLEARED` clearance on the same station intersects on all three axes —
    weekday set, half-open hour window, and effective date range — and is
    rejected with `ERR_CLEARANCE_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/clearance_half_open_window_overlap_with_adjacency_allowed
    """
    env = _setup_clearance_overlap_env(api)
    resp = api.clear_clearance(env["c2"]["id"], PD)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_WINDOW_OVERLAP)
    # [13,15) intersects [10,14); weekday sets and date ranges also intersect.
    c2 = get_success_data(api.get_clearance(env["c2"]["id"], PD))
    assert c2["status"] == "PENDING"


def test_clearance_adjacency_allowed(api):
    """PRD §3.9: "mere adjacency where one window's end equals the other's
    start is allowed."

    Design: Difficulty/resource_temporal_overlap/clearance_half_open_window_overlap_with_adjacency_allowed
    """
    env = _setup_clearance_overlap_env(api)
    cleared = get_success_data(api.clear_clearance(env["c3"]["id"], PD))
    assert cleared["status"] == "CLEARED", "[14,16) adjacent to [10,14): 14 == 14 does not intersect"

    c1 = get_success_data(api.get_clearance(env["c1"]["id"], PD))
    assert c1["status"] == "CLEARED", "C1 remains CLEARED throughout"


# ---------------------------------------------------------------------------
# Barter avail gating and OCC
# ---------------------------------------------------------------------------

def _setup_pending_clearance_env():
    """Station + MON clock (SPOT_BREAK hour 10, 4/240) + PENDING clearance
    (MON [10,12)) + LOCKED log 2026-05-04."""
    env = setup_bookable_station(
        weekday="MON", hour=10, capacity_units=4, capacity_seconds=240,
        base_rate_cents=1000, min_rate_cents=100,
    )
    clearance = create_clearance(env["station"]["id"], start_hour=10, duration_hours=2)
    log = create_locked_log(env["station"]["id"], log_date="2026-05-04")
    env.update({"clearance": clearance, "log": log})
    return env


def test_barter_avail_gated_by_clearance_status_pending_rejected(api):
    """PRD §3.9: "Scheduling a barter avail is a `TrafficDirector` operation
    requiring `clearance_id`, `log_id`, `hour`, `duration_sec`, and
    `expected_clearance_version` matching the clearance's current `version`
    (mismatch yields `ERR_STALE_VERSION`, HTTP 412). The clearance must be
    `CLEARED` (`ERR_CLEARANCE_NOT_CLEARED` otherwise)".

    Design: Difficulty/cross_entity_state_dependency/barter_avail_gated_by_clearance_status
    """
    env = _setup_pending_clearance_env()
    resp = schedule_barter_avail(env["clearance"]["id"], env["log"]["id"], hour=10)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)
    assert resp.status_code == 409

    avails, _meta = validate_paginated(api.list_barter_avails(TD))
    assert avails == [], "no avail created while PENDING"


def test_barter_avail_gated_by_clearance_status_cleared_ok(api):
    """PRD §3.9: "On success the avail consumes sellable spot-pool inventory of
    the hour and the clearance's `version` increments as an OCC write."

    Design: Difficulty/cross_entity_state_dependency/barter_avail_gated_by_clearance_status
    """
    env = _setup_pending_clearance_env()
    cleared = get_success_data(api.clear_clearance(env["clearance"]["id"], PD))

    avail = schedule_barter_avail_ok(cleared["id"], env["log"]["id"], hour=10)
    assert avail["status"] == "SCHEDULED"

    after = get_success_data(api.get_clearance(cleared["id"], TD))
    assert after["version"] == cleared["version"] + 1, (
        "clearance version advanced by the successful scheduling (OCC write)"
    )


def test_occ_stale_clearance_version_returns_412(api):
    """PRD §2.7: "Scheduling a barter avail requires
    `expected_clearance_version` matching the target SyndicationClearance's
    current `version`." and "is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_clearance_version_returns_412
    """
    env = _setup_pending_clearance_env()
    stale_version = env["clearance"]["version"]
    get_success_data(api.clear_clearance(env["clearance"]["id"], PD))

    resp = schedule_barter_avail(
        env["clearance"]["id"], env["log"]["id"],
        hour=10, expected_clearance_version=stale_version,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_avail_outside_clearance_window_end_hour_excluded(api):
    """PRD §3.9: "the half-open window from `start_hour` up to but not
    including `start_hour` plus `duration_hours`" and "the `hour` must satisfy
    the half-open window from `start_hour`, and `air_date` must lie inside the
    effective range — violations yield `ERR_CLEARANCE_WINDOW_VIOLATION`."

    Design: Corner/validations/avail_outside_clearance_window_end_hour_excluded
    """
    env = setup_bookable_station(
        weekday="MON", hour=12, capacity_units=4, capacity_seconds=240
    )
    clearance = create_clearance(env["station"]["id"], start_hour=10, duration_hours=2)
    get_success_data(api.clear_clearance(clearance["id"], PD))
    log = create_locked_log(env["station"]["id"], log_date="2026-05-04")

    resp = schedule_barter_avail(clearance["id"], log["id"], hour=12)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_WINDOW_VIOLATION)


# ---------------------------------------------------------------------------
# Disaffirm cascade
# ---------------------------------------------------------------------------

def test_clearance_disaffirm_twice_returns_invalid_state(api):
    """PRD §3.9: "Disaffirming (`PENDING → DISAFFIRMED` or `CLEARED →
    DISAFFIRMED`)" is declared only from PENDING and CLEARED; PRD §2.8:
    "then generic from-state legality (`ERR_INVALID_STATE`)". A second
    disaffirm on a DISAFFIRMED clearance is not a declared transition.

    Design: Corner/state_machines/clearance_disaffirm_twice_returns_invalid_state
    """
    station = create_station()
    clearance = create_clearance(station["id"])
    get_success_data(api.disaffirm_clearance(clearance["id"], PD))

    resp = api.disaffirm_clearance(clearance["id"], PD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_clearance_with_future_avails(api):
    """CLEARED clearance (MON [10,12), 1 avail/hr) with two avails scheduled on
    the LOCKED 2026-05-04 log at hours 10 and 11; logical clock at 2026-05-03
    so the air date is strictly in the future."""
    env = setup_bookable_station(
        weekday="MON", hour=10, capacity_units=4, capacity_seconds=240,
        extra_slots=[{
            "slot_type": "SPOT_BREAK", "hour": 11,
            "capacity_units": 4, "capacity_seconds": 240,
        }],
    )
    clearance = create_clearance(env["station"]["id"], start_hour=10, duration_hours=2)
    get_success_data(api.clear_clearance(clearance["id"], PD))
    log = create_locked_log(env["station"]["id"], log_date="2026-05-04")
    a1 = schedule_barter_avail_ok(clearance["id"], log["id"], hour=10)
    a2 = schedule_barter_avail_ok(clearance["id"], log["id"], hour=11)
    set_clock("2026-05-03T00:00:00Z")
    env.update({"clearance": clearance, "log": log, "a1": a1, "a2": a2})
    return env


def test_clearance_disaffirm_cascade_cancels_future_avails(api):
    """PRD §3.9: "Disaffirming (`PENDING → DISAFFIRMED` or `CLEARED →
    DISAFFIRMED`) cascades: every BarterAvail of this clearance in `SCHEDULED`
    status whose `air_date` is strictly after the logical clock's current date
    transitions to `CANCELLED`".

    Design: Difficulty/transitive_cascade/clearance_disaffirm_cascade_avails_log_counters
    """
    env = _setup_clearance_with_future_avails(api)
    disaffirmed = get_success_data(api.disaffirm_clearance(env["clearance"]["id"], PD))
    assert disaffirmed["status"] == "DISAFFIRMED"

    for avail in (env["a1"], env["a2"]):
        after = get_success_data(api.get_barter_avail(avail["id"], TD))
        assert after["status"] == "CANCELLED", "hop 1: future SCHEDULED avails cancelled"

    listed, _meta = validate_paginated(
        api.list_barter_avails(TD, params={"clearance_id": env["clearance"]["id"]})
    )
    assert len(listed) == 2, "avails remain queryable (CANCELLED, not deleted)"


def test_clearance_disaffirm_cascade_bumps_log_version(api):
    """PRD §3.9: "each such cancellation recomputes its owning log's spot-pool
    occupancy counters and bumps the log's `version`."

    Design: Difficulty/transitive_cascade/clearance_disaffirm_cascade_avails_log_counters
    """
    env = _setup_clearance_with_future_avails(api)
    before = get_success_data(api.get_log(env["log"]["id"], TD))

    get_success_data(api.disaffirm_clearance(env["clearance"]["id"], PD))

    after = get_success_data(api.get_log(env["log"]["id"], TD))
    assert after["version"] > before["version"], (
        "hop 2: occupancy recompute bumps the log's version"
    )
