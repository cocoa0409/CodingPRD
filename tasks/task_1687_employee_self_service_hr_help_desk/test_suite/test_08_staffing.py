"""Seasonal staffing windows and shift planning (PRD §3.9): coverage posture
computation, interval overlap semantics, and shift/window state guards."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    make_team,
    make_agent,
    make_window,
    make_shift,
    get_window,
    create_staffing_window_payload,
    create_agent_shift_payload,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]


# ---------------------------------------------------------------------------
# Coverage posture (combinatorial formula / boundary)
# ---------------------------------------------------------------------------

def _coverage_window(api):
    """Window requiring 40 T1-hours and 10 T2-hours; 36 T1-hours and 8 T2-hours
    of SCHEDULED shifts."""
    team = make_team("Staffing Team")
    a1 = make_agent(team["id"], tier="T1", display_name="T1 Agent", email="t1@x.com")
    a2 = make_agent(team["id"], tier="T2", display_name="T2 Agent", email="t2@x.com")
    window = make_window(
        team["id"],
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        required_t1_hours=40,
        required_t2_hours=10,
        name="OE Week",
    )
    for day in ("03", "04", "05", "06"):
        make_shift(a1["id"], window["id"],
                   shift_start=f"2026-08-{day}T09:00:00Z", shift_end=f"2026-08-{day}T18:00:00Z")
    for day in ("03", "04"):
        make_shift(a2["id"], window["id"],
                   shift_start=f"2026-08-{day}T09:00:00Z", shift_end=f"2026-08-{day}T13:00:00Z")
    return window


def test_staffing_coverage_hours_accumulate_per_tier(api):
    """PRD §3.9: "For each tier, the covered hours are the sum — over the window's
    `SCHEDULED` shifts worked by agents of that tier — of the overlap in minutes
    between the half-open shift and the window's inclusive bounds, divided by sixty;
    shifts are clipped to the window, and a zero or negative clip contributes
    nothing. The results are exposed as `covered_t1_hours` and `covered_t2_hours`,
    each rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/staffing_coverage_min_ratio_multitier
    """
    window = _coverage_window(api)

    data = get_window(window["id"])
    assert data["covered_t1_hours"] == pytest.approx(36.0, abs=1e-6)
    assert data["covered_t2_hours"] == pytest.approx(8.0, abs=1e-6)


def test_staffing_coverage_posture_gated_by_weakest_tier(api):
    """PRD §3.9: "Each tier's coverage ratio is its covered hours divided by its
    required hours, with a tier requiring zero hours contributing a ratio of exactly
    1.0. The window's `coverage_posture` is gated by the weaker tier:
    `UNDER_STAFFED` when the smaller ratio is below 0.90, `ADEQUATE` when it is at
    least 0.90 and at most 1.10, and `SURPLUS` beyond 1.10 — so a window that
    requires nothing on either tier reads as `ADEQUATE`."

    Design: Difficulty/combinatorial_formula/staffing_coverage_min_ratio_multitier
    """
    window = _coverage_window(api)

    data = get_window(window["id"])
    # min(36/40, 8/10) = min(0.90, 0.80) = 0.80 < 0.90 — the weaker tier (T2) gates.
    assert data["coverage_posture"] == "UNDER_STAFFED", (
        f"the weakest tier must drive the posture, got {data['coverage_posture']}"
    )


def test_zero_required_window_reads_adequate(api):
    """PRD §3.9: "Each tier's coverage ratio is its covered hours divided by its
    required hours, with a tier requiring zero hours contributing a ratio of exactly
    1.0. The window's `coverage_posture` is gated by the weaker tier:
    `UNDER_STAFFED` when the smaller ratio is below 0.90, `ADEQUATE` when it is at
    least 0.90 and at most 1.10, and `SURPLUS` beyond 1.10 — so a window that
    requires nothing on either tier reads as `ADEQUATE`."

    Design: Difficulty/boundary_precision_check/staffing_posture_zero_required_hours_adequate
    """
    team = make_team("Zero Team")
    window = make_window(
        team["id"],
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        required_t1_hours=0,
        required_t2_hours=0,
        name="Zero Req",
    )

    data = get_window(window["id"])
    assert data["coverage_posture"] == "ADEQUATE", (
        "both tiers contribute ratio 1.0 when nothing is required"
    )


def test_zero_required_window_reports_zero_covered_hours(api):
    """PRD §3.9: "Coverage is recomputed whenever a window is read and after every
    shift creation or cancellation. For each tier, the covered hours are the sum —
    over the window's `SCHEDULED` shifts worked by agents of that tier — of the
    overlap in minutes between the half-open shift and the window's inclusive bounds,
    divided by sixty; shifts are clipped to the window, and a zero or negative clip
    contributes nothing."

    Design: Difficulty/boundary_precision_check/staffing_posture_zero_required_hours_adequate
    """
    team = make_team("Zero Team")
    window = make_window(
        team["id"],
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        required_t1_hours=0,
        required_t2_hours=0,
        name="Zero Req",
    )

    data = get_window(window["id"])
    assert data["covered_t1_hours"] == pytest.approx(0.0, abs=1e-6)
    assert data["covered_t2_hours"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Interval overlap semantics
# ---------------------------------------------------------------------------

def _shift_window_with_morning_shift(api):
    team = make_team("Shift Team")
    agent = make_agent(team["id"], tier="T1", display_name="Agent S", email="s@x.com")
    window = make_window(team["id"], window_start="2026-08-03T00:00:00Z",
                         window_end="2026-08-08T00:00:00Z",
                         required_t1_hours=10, required_t2_hours=0, name="Week1")
    make_shift(agent["id"], window["id"],
               shift_start="2026-08-03T09:00:00Z", shift_end="2026-08-03T17:00:00Z")
    return agent, window


def test_back_to_back_shifts_allowed(api):
    """PRD §3.9: "One agent cannot be in two places at once, but the overlap test is
    half-open: a new shift strictly overlapping another `SCHEDULED` shift of the same
    agent is rejected with `ERR_SHIFT_OVERLAP`, while back-to-back shifts that merely
    touch are allowed."

    Design: Difficulty/resource_temporal_overlap/agent_shift_half_open_back_to_back_allowed
    """
    agent, window = _shift_window_with_morning_shift(api)

    # 17:00-21:00 touches the existing 09:00-17:00 shift at the endpoint only.
    created = validate_success(
        api.create_agent_shift(
            create_agent_shift_payload(agent["id"], window["id"],
                                       shift_start="2026-08-03T17:00:00Z",
                                       shift_end="2026-08-03T21:00:00Z"),
            PLANNER,
        ),
        expected_status=201,
    )
    assert created["status"] == "SCHEDULED"

    _data, meta = validate_paginated(
        api.list_agent_shifts(PLANNER, params={"agent_id": agent["id"]})
    )
    assert meta["total_count"] == 2


def test_strictly_overlapping_shift_rejected(api):
    """PRD §3.9: "One agent cannot be in two places at once, but the overlap test is
    half-open: a new shift strictly overlapping another `SCHEDULED` shift of the same
    agent is rejected with `ERR_SHIFT_OVERLAP`, while back-to-back shifts that merely
    touch are allowed."

    Design: Difficulty/resource_temporal_overlap/agent_shift_half_open_back_to_back_allowed
    """
    agent, window = _shift_window_with_morning_shift(api)

    # 16:59-18:00 strictly overlaps the existing 09:00-17:00 shift.
    resp = api.create_agent_shift(
        create_agent_shift_payload(agent["id"], window["id"],
                                   shift_start="2026-08-03T16:59:00Z",
                                   shift_end="2026-08-03T18:00:00Z"),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)

    _data, meta = validate_paginated(
        api.list_agent_shifts(PLANNER, params={"agent_id": agent["id"]})
    )
    assert meta["total_count"] == 1, "the rejected shift must not be persisted"


def test_touching_windows_conflict(api):
    """PRD §3.9: "Windows of the same team may not overlap: because the bounds are
    inclusive, even two windows merely touching at an endpoint conflict, and a
    conflicting create is rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/staffing_window_touching_endpoints_conflict
    """
    team = make_team("Win Team")
    make_window(team["id"], window_start="2026-10-01T00:00:00Z",
                window_end="2026-11-30T00:00:00Z", required_t1_hours=100,
                required_t2_hours=20, name="OE Part 1")

    # window_start exactly equals the existing window's inclusive window_end.
    resp = api.create_staffing_window(
        create_staffing_window_payload(team["id"], name="OE Touching",
                                       window_start="2026-11-30T00:00:00Z",
                                       window_end="2026-12-31T00:00:00Z",
                                       required_t1_hours=50, required_t2_hours=10),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


def test_gapped_window_accepted(api):
    """PRD §3.9: "Windows of the same team may not overlap: because the bounds are
    inclusive, even two windows merely touching at an endpoint conflict, and a
    conflicting create is rejected with `ERR_WINDOW_OVERLAP`. This closed-interval
    rule is what guarantees at most one `ACTIVE` window per team at any instant."

    Design: Difficulty/resource_temporal_overlap/staffing_window_touching_endpoints_conflict
    """
    team = make_team("Win Team")
    make_window(team["id"], window_start="2026-10-01T00:00:00Z",
                window_end="2026-11-30T00:00:00Z", required_t1_hours=100,
                required_t2_hours=20, name="OE Part 1")

    # A one-day gap (start 12-01, after the inclusive 11-30 end) does not conflict.
    created = validate_success(
        api.create_staffing_window(
            create_staffing_window_payload(team["id"], name="OE Part 2",
                                           window_start="2026-12-01T00:00:00Z",
                                           window_end="2026-12-31T00:00:00Z",
                                           required_t1_hours=50, required_t2_hours=10),
            PLANNER,
        ),
        expected_status=201,
    )
    assert created["id"]

    _data, meta = validate_paginated(
        api.list_staffing_windows(PLANNER, params={"team_id": team["id"]})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Shift/window state guards and time ranges
# ---------------------------------------------------------------------------

def test_shift_double_cancel_rejected(api):
    """PRD §3.9: "A shift opens `SCHEDULED`; the planner may cancel it, and
    cancelling one that is not `SCHEDULED` fails with `ERR_SHIFT_INVALID_STATE`."

    Design: Corner/state_machines/shift_double_cancel_rejected
    """
    team = make_team("SH Team")
    agent = make_agent(team["id"], tier="T1", email="sh@x.com")
    window = make_window(team["id"], name="W")
    shift = make_shift(agent["id"], window["id"],
                       shift_start="2026-08-03T09:00:00Z", shift_end="2026-08-03T12:00:00Z")

    cancelled = validate_success(api.cancel_agent_shift(shift["id"], PLANNER))
    assert cancelled["status"] == "CANCELLED"

    resp = api.cancel_agent_shift(shift["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_STATE.value)


def test_shift_into_cancelled_window_rejected(api):
    """PRD §3.9: "The window must still be `PLANNED` or `ACTIVE` — scheduling into a
    completed or cancelled window fails with `ERR_WINDOW_INVALID_STATE`."

    Design: Corner/state_machines/shift_into_cancelled_window_rejected
    """
    team = make_team("CW Team")
    agent = make_agent(team["id"], tier="T1", email="cw@x.com")
    window = make_window(team["id"], name="W")
    validate_success(api.cancel_staffing_window(window["id"], PLANNER))

    resp = api.create_agent_shift(
        create_agent_shift_payload(agent["id"], window["id"],
                                   shift_start="2026-08-03T09:00:00Z",
                                   shift_end="2026-08-03T12:00:00Z"),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID_STATE.value)


def test_shift_outside_window_rejected(api):
    """PRD §3.9: "The span must lie inside the window: a `shift_start` before
    `window_start` or a `shift_end` after `window_end` fails with
    `ERR_SHIFT_OUTSIDE_WINDOW`, and an end that does not fall strictly after the
    start fails with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/shift_outside_window_rejected
    """
    team = make_team("OW Team")
    agent = make_agent(team["id"], tier="T1", email="ow@x.com")
    window = make_window(team["id"], name="W")  # 2026-08-03 .. 2026-08-08

    resp = api.create_agent_shift(
        create_agent_shift_payload(agent["id"], window["id"],
                                   shift_start="2026-08-02T20:00:00Z",
                                   shift_end="2026-08-03T02:00:00Z"),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OUTSIDE_WINDOW.value)


def test_invalid_time_ranges_rejected(api):
    """PRD §3.9: "The span must lie inside the window: a `shift_start` before
    `window_start` or a `shift_end` after `window_end` fails with
    `ERR_SHIFT_OUTSIDE_WINDOW`, and an end that does not fall strictly after the
    start fails with `ERR_INVALID_TIME_RANGE`."
    PRD §3.9: "A `WorkforcePlanner` creates one for a `team_id` with a `name`, an
    inclusive `window_start` and `window_end` (the end must not precede the start,
    otherwise `ERR_INVALID_TIME_RANGE`), the `required_t1_hours` and
    `required_t2_hours` the window must staff (each zero or more), and an optional
    `sla_multiplier` — defaulting to 1.0 and never below 1.0 — which stretches the
    base SLA minutes of tickets created in the team's categories while the window is
    `ACTIVE`, exactly as §3.4 describes."

    Design: Corner/validations/invalid_time_ranges_rejected
    """
    team1 = make_team("TR Team 1")
    team2 = make_team("TR Team 2")
    agent = make_agent(team1["id"], tier="T1", email="tr@x.com")
    window = make_window(team1["id"], name="GoodW")

    # Shift whose end does not fall strictly after its start.
    resp1 = api.create_agent_shift(
        create_agent_shift_payload(agent["id"], window["id"],
                                   shift_start="2026-08-03T10:00:00Z",
                                   shift_end="2026-08-03T09:00:00Z"),
        PLANNER,
    )
    validate_error(resp1, ApiErrorId.ERR_INVALID_TIME_RANGE.value)

    # Window whose end precedes its start (fresh team: no overlap in play).
    resp2 = api.create_staffing_window(
        create_staffing_window_payload(team2["id"], name="BadW",
                                       window_start="2026-08-08T00:00:00Z",
                                       window_end="2026-08-03T00:00:00Z",
                                       required_t1_hours=10, required_t2_hours=0),
        PLANNER,
    )
    validate_error(resp2, ApiErrorId.ERR_INVALID_TIME_RANGE.value)
