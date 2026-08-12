"""Resource temporal overlap rules (PRD §3.7, §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_active_program_with_group, setup_active_program_with_plan_coordinating,
    create_engagement, schedule_engagement, create_move_in_wave,
    pm_headers, ApiErrorId,
)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / dock_wave_half_open_buffer_overlap
# ---------------------------------------------------------------------------

def test_wave_start_exactly_at_buffered_end_allowed(api):
    """PRD §3.8: "The boundary is strict: a candidate starting exactly at the
    prior wave's buffered end is allowed, while starting one minute earlier
    conflicts."

    Design: Difficulty/resource_temporal_overlap/dock_wave_half_open_buffer_overlap
    """
    pid, g1, pl = setup_active_program_with_plan_coordinating(
        budget=1_000_000, contingency=100_000, name="P-DOCK")
    # W1 occupies [08:00, 12:00) + 2h buffer -> [08:00, 14:00)
    create_move_in_wave(pl["id"], g1["id"], wave_name="W1", dock_resource="DOCK_A",
                         move_start="2026-10-01T08:00:00Z",
                         move_end="2026-10-01T12:00:00Z", criticality_weight=1)
    # W2 starts exactly at buffered end 14:00 -> allowed
    w2 = create_move_in_wave(pl["id"], g1["id"], wave_name="W2", dock_resource="DOCK_A",
                              move_start="2026-10-01T14:00:00Z",
                              move_end="2026-10-01T16:00:00Z", criticality_weight=1)
    assert w2["status"] == "SCHEDULED"


def test_wave_one_minute_before_buffered_end_conflicts(api):
    """PRD §3.8: "Each occupying wave blocks the interval from its move_start
    up to its move_end extended by a two-hour turnover buffer, with the
    buffered end itself excluded."

    Design: Difficulty/resource_temporal_overlap/dock_wave_half_open_buffer_overlap
    """
    pid, g1, pl = setup_active_program_with_plan_coordinating(
        budget=1_000_000, contingency=100_000, name="P-DOCK2")
    create_move_in_wave(pl["id"], g1["id"], wave_name="W1", dock_resource="DOCK_A",
                         move_start="2026-10-01T08:00:00Z",
                         move_end="2026-10-01T12:00:00Z", criticality_weight=1)
    resp = api_client.create_move_in_wave(
        {
            "occupancy_plan_id": pl["id"],
            "stakeholder_group_id": g1["id"],
            "wave_name": "W3",
            "dock_resource": "DOCK_A",
            "move_start": "2026-10-01T13:59:00Z",
            "move_end": "2026-10-01T15:00:00Z",
            "criticality_weight": 1,
        },
        pm_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DOCK_OVERLAP)


def test_overlapping_window_on_different_dock_allowed(api):
    """PRD §3.8: "Only waves in SCHEDULED or CONFIRMED on the same
    dock_resource within the same program occupy a dock".

    Design: Difficulty/resource_temporal_overlap/dock_wave_half_open_buffer_overlap
    """
    pid, g1, pl = setup_active_program_with_plan_coordinating(
        budget=1_000_000, contingency=100_000, name="P-DOCK3")
    create_move_in_wave(pl["id"], g1["id"], wave_name="W1", dock_resource="DOCK_A",
                         move_start="2026-10-01T08:00:00Z",
                         move_end="2026-10-01T12:00:00Z", criticality_weight=1)
    # Same wall-clock window but DOCK_B: no conflict
    w4 = create_move_in_wave(pl["id"], g1["id"], wave_name="W4", dock_resource="DOCK_B",
                              move_start="2026-10-01T09:00:00Z",
                              move_end="2026-10-01T11:00:00Z", criticality_weight=1)
    assert w4["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / engagement_closed_interval_adjacency_and_daily_cap
# ---------------------------------------------------------------------------

def test_engagement_daily_cap_inclusive_at_360(api):
    """PRD §3.7: "the daily cap apply: summing duration_minutes over the
    group's SCHEDULED engagements whose scheduled_start falls on the same UTC
    calendar date as the candidate's, then adding the candidate's own
    duration_minutes, the total must not exceed 360 minutes (six hours) per
    group per UTC date. The cap is inclusive — a day landing on exactly 360
    minutes is allowed".

    Design: Difficulty/resource_temporal_overlap/engagement_closed_interval_adjacency_and_daily_cap
    """
    pid, g1 = setup_active_program_with_group(
        budget=1_000_000, contingency=100_000, name="P-ENG")
    e1 = create_engagement(g1["id"], title="E1",
                            scheduled_start="2026-09-02T09:00:00Z",
                            scheduled_end="2026-09-02T12:00:00Z")  # 180 min
    e1s = schedule_engagement(e1["id"])
    assert e1s["status"] == "SCHEDULED"
    e2 = create_engagement(g1["id"], title="E2",
                            scheduled_start="2026-09-02T13:00:00Z",
                            scheduled_end="2026-09-02T16:00:00Z")  # 180 min
    e2s = schedule_engagement(e2["id"])
    # 180 + 180 = 360 exactly: allowed by inclusive cap
    assert e2s["status"] == "SCHEDULED"


def test_engagement_361st_minute_breaches_daily_cap(api):
    """PRD §3.7: "a breach is rejected with ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED
    (409)" — 360 + 1 > 360.

    Design: Difficulty/resource_temporal_overlap/engagement_closed_interval_adjacency_and_daily_cap
    """
    pid, g1 = setup_active_program_with_group(
        budget=1_000_000, contingency=100_000, name="P-ENG2")
    e1 = create_engagement(g1["id"], title="E1",
                            scheduled_start="2026-09-02T09:00:00Z",
                            scheduled_end="2026-09-02T12:00:00Z")
    schedule_engagement(e1["id"])
    e2 = create_engagement(g1["id"], title="E2",
                            scheduled_start="2026-09-02T13:00:00Z",
                            scheduled_end="2026-09-02T16:00:00Z")
    schedule_engagement(e2["id"])
    # 361st minute
    e3 = create_engagement(g1["id"], title="E3",
                            scheduled_start="2026-09-02T16:30:00Z",
                            scheduled_end="2026-09-02T16:31:00Z")
    resp = api_client.schedule_engagement(e3["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED)


def test_engagement_closed_interval_touching_endpoints_conflict(api):
    """PRD §3.7: "Moving PROPOSED → SCHEDULED first enforces a closed-interval
    overlap rule against every other SCHEDULED engagement of the same group:
    touching endpoints count as overlap, so an engagement starting at the exact
    moment another ends still conflicts — any such collision is rejected with
    ERR_ENGAGEMENT_OVERLAP (409)."

    Design: Difficulty/resource_temporal_overlap/engagement_closed_interval_adjacency_and_daily_cap
    """
    pid, g1 = setup_active_program_with_group(
        budget=1_000_000, contingency=100_000, name="P-ENG3")
    e1 = create_engagement(g1["id"], title="E1",
                            scheduled_start="2026-09-02T09:00:00Z",
                            scheduled_end="2026-09-02T12:00:00Z")
    schedule_engagement(e1["id"])
    # E4 starts exactly when E1 ends -> closed-interval touch -> conflict
    e4 = create_engagement(g1["id"], title="E4",
                            scheduled_start="2026-09-02T12:00:00Z",
                            scheduled_end="2026-09-02T12:30:00Z")
    resp = api_client.schedule_engagement(e4["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)
