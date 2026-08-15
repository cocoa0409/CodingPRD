"""Flow monitoring and I/I reduction: variants, boundary, baseline selector, overlap."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_flow_period,
    analyze_flow_period,
    create_closed_period,
    create_district,
    create_flow_period,
    create_segment,
    set_clock,
    setup_completed_spot_repair,
    validate_error,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]


def test_dry_weather_and_storm_variants_computed(api):
    """PRD §3.9: "The analysis response carries `dry_weather_reduction_pct`,
    `storm_event_reduction_pct`, and `basin_target_met`, and the period itself
    advances `CLOSED` → `ANALYZED`."
    Baseline 100 dry / 500 storm vs post 60 dry / 425 storm: dry reduction
    100*(1-60/100) = 40.0; storm reduction 100*(1-425/500) = 15.0.

    Design: Difficulty/dual_variant_calc/infiltration_dry_vs_storm_variant_gate
    """
    ctx = setup_completed_spot_repair(cert_kwargs={"ii_reduction_target_pct": 30})
    d_id = ctx["district"]["id"]
    create_closed_period(d_id, basin_label="B1", phase="PRE_REHAB",
                         window_start="2026-03-01T00:00:00Z", window_end="2026-03-15T00:00:00Z",
                         dry_weather_avg_gpm=100, peak_storm_gpm=500)
    post = create_closed_period(d_id, basin_label="B1", phase="POST_REHAB",
                                window_start="2026-08-11T00:00:00Z", window_end="2026-08-25T00:00:00Z",
                                dry_weather_avg_gpm=60, peak_storm_gpm=425)
    result = analyze_flow_period(post["id"])
    assert result["dry_weather_reduction_pct"] == pytest.approx(40.0, abs=1e-9)
    assert result["storm_event_reduction_pct"] == pytest.approx(15.0, abs=1e-9)


def test_basin_target_gated_by_dry_variant_only(api):
    """PRD §3.9: "Only the dry-weather figure carries regulatory weight:
    `basin_target_met` is true exactly when the dry-weather reduction percentage is
    at least the district's `ii_reduction_target_pct` — the boundary is inclusive, so
    a measured reduction equal to the target passes. The storm-event figure is
    engineering context only and can never satisfy the basin target, even when it
    crosses the same threshold."
    Dry 40.0 >= target 30 passes; the storm variant's 15.0 plays no role.

    Design: Difficulty/dual_variant_calc/infiltration_dry_vs_storm_variant_gate
    """
    ctx = setup_completed_spot_repair(cert_kwargs={"ii_reduction_target_pct": 30})
    d_id = ctx["district"]["id"]
    create_closed_period(d_id, basin_label="B1", phase="PRE_REHAB",
                         window_start="2026-03-01T00:00:00Z", window_end="2026-03-15T00:00:00Z",
                         dry_weather_avg_gpm=100, peak_storm_gpm=500)
    post = create_closed_period(d_id, basin_label="B1", phase="POST_REHAB",
                                window_start="2026-08-11T00:00:00Z", window_end="2026-08-25T00:00:00Z",
                                dry_weather_avg_gpm=60, peak_storm_gpm=425)
    result = analyze_flow_period(post["id"])
    assert result["storm_event_reduction_pct"] == pytest.approx(15.0, abs=1e-9)
    assert result["basin_target_met"] is True


def test_basin_target_exactly_met_inclusive_boundary_value(api):
    """PRD §3.9: "Only the dry-weather figure carries regulatory weight:
    `basin_target_met` is true exactly when the dry-weather reduction percentage is
    at least the district's `ii_reduction_target_pct` — the boundary is inclusive, so
    a measured reduction equal to the target passes."
    Baseline 100 dry vs post 70 dry: 100*(1-70/100) = 30.0, exactly the target.

    Design: Difficulty/boundary_precision_check/basin_target_exactly_met_inclusive_boundary
    """
    ctx = setup_completed_spot_repair(cert_kwargs={"ii_reduction_target_pct": 30})
    d_id = ctx["district"]["id"]
    create_closed_period(d_id, basin_label="B2", phase="PRE_REHAB",
                         window_start="2026-03-01T00:00:00Z", window_end="2026-03-15T00:00:00Z",
                         dry_weather_avg_gpm=100, peak_storm_gpm=400)
    post = create_closed_period(d_id, basin_label="B2", phase="POST_REHAB",
                                window_start="2026-08-11T00:00:00Z", window_end="2026-08-25T00:00:00Z",
                                dry_weather_avg_gpm=70, peak_storm_gpm=400)
    result = analyze_flow_period(post["id"])
    assert result["dry_weather_reduction_pct"] == pytest.approx(30.0, abs=1e-9)


def test_basin_target_exactly_met_passes(api):
    """PRD §3.9: "Only the dry-weather figure carries regulatory weight:
    `basin_target_met` is true exactly when the dry-weather reduction percentage is
    at least the district's `ii_reduction_target_pct` — the boundary is inclusive, so
    a measured reduction equal to the target passes."
    A strictly-greater implementation fails here: exactly 30.0 against target 30
    must set `basin_target_met` true.

    Design: Difficulty/boundary_precision_check/basin_target_exactly_met_inclusive_boundary
    """
    ctx = setup_completed_spot_repair(cert_kwargs={"ii_reduction_target_pct": 30})
    d_id = ctx["district"]["id"]
    create_closed_period(d_id, basin_label="B2", phase="PRE_REHAB",
                         window_start="2026-03-01T00:00:00Z", window_end="2026-03-15T00:00:00Z",
                         dry_weather_avg_gpm=100, peak_storm_gpm=400)
    post = create_closed_period(d_id, basin_label="B2", phase="POST_REHAB",
                                window_start="2026-08-11T00:00:00Z", window_end="2026-08-25T00:00:00Z",
                                dry_weather_avg_gpm=70, peak_storm_gpm=400)
    result = analyze_flow_period(post["id"])
    assert result["dry_weather_reduction_pct"] == pytest.approx(30.0, abs=1e-9)
    assert result["basin_target_met"] is True


def test_i_i_baseline_selector_picks_latest_closed_pre_period(api):
    """PRD §3.9: "When several baselines qualify, the selector picks the one with
    the greatest `window_end`, breaking ties by the latest `created_at`."
    PRE-A ends 2026-03-15 with dry 200; PRE-B ends 2026-04-15 with dry 100. The
    selector must pick PRE-B: post dry 50 gives 100*(1-50/100) = 50.0, whereas the
    stale PRE-A would wrongly give 75.0.

    Design: Corner/calculations/i_i_baseline_selector_picks_latest_closed_pre_period
    """
    ctx = setup_completed_spot_repair(cert_kwargs={"ii_reduction_target_pct": 10})
    d_id = ctx["district"]["id"]
    create_closed_period(d_id, basin_label="B5", phase="PRE_REHAB",
                         window_start="2026-03-01T00:00:00Z", window_end="2026-03-15T00:00:00Z",
                         dry_weather_avg_gpm=200, peak_storm_gpm=900)
    create_closed_period(d_id, basin_label="B5", phase="PRE_REHAB",
                         window_start="2026-04-01T00:00:00Z", window_end="2026-04-15T00:00:00Z",
                         dry_weather_avg_gpm=100, peak_storm_gpm=400)
    post = create_closed_period(d_id, basin_label="B5", phase="POST_REHAB",
                                window_start="2026-08-11T00:00:00Z", window_end="2026-08-25T00:00:00Z",
                                dry_weather_avg_gpm=50, peak_storm_gpm=100)
    result = analyze_flow_period(post["id"])
    assert result["dry_weather_reduction_pct"] == pytest.approx(50.0, abs=1e-9)


def test_flow_period_overlap_closed_interval_inclusive(api):
    """PRD §3.9: "Exclusion: no other period for the same district and `basin_label`
    may be `ACTIVE` over an intersecting closed interval, and because the intervals
    are inclusive, two periods that merely share an endpoint still conflict
    (`ERR_FLOW_WINDOW_CONFLICT`)."
    F2's window_start equals the ACTIVE F1's window_end — a shared endpoint, which
    counts as a conflict under closed-interval semantics.

    Design: Difficulty/resource_temporal_overlap/flow_period_overlap_closed_interval_inclusive
    """
    ctx = setup_completed_spot_repair()
    d_id = ctx["district"]["id"]
    f1 = create_flow_period(d_id, basin_label="B4", phase="POST_REHAB",
                            window_start="2026-08-01T00:00:00Z", window_end="2026-08-15T00:00:00Z")
    activate_flow_period(f1["id"])
    f2 = create_flow_period(d_id, basin_label="B4", phase="POST_REHAB",
                            window_start="2026-08-15T00:00:00Z", window_end="2026-08-29T00:00:00Z")
    resp = api.activate_flow_period(f2["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_FLOW_WINDOW_CONFLICT)


def test_flow_period_disjoint_windows_coexist(api):
    """PRD §3.9: "Exclusion: no other period for the same district and `basin_label`
    may be `ACTIVE` over an intersecting closed interval, and because the intervals
    are inclusive, two periods that merely share an endpoint still conflict
    (`ERR_FLOW_WINDOW_CONFLICT`)."
    A third window that begins the day after F1's inclusive end shares no instant
    with it and activates cleanly.

    Design: Difficulty/resource_temporal_overlap/flow_period_overlap_closed_interval_inclusive
    """
    ctx = setup_completed_spot_repair()
    d_id = ctx["district"]["id"]
    f1 = create_flow_period(d_id, basin_label="B4", phase="POST_REHAB",
                            window_start="2026-08-01T00:00:00Z", window_end="2026-08-15T00:00:00Z")
    activate_flow_period(f1["id"])
    f3 = create_flow_period(d_id, basin_label="B4", phase="POST_REHAB",
                            window_start="2026-08-16T00:00:00Z", window_end="2026-08-29T00:00:00Z")
    data = validate_success(api.activate_flow_period(f3["id"], ENGINEER), 200)
    assert data["status"] == "ACTIVE"


def test_post_rehab_flow_activation_gated_on_segment_rehab_status(api):
    """PRD §3.9: "Sequencing: a `POST_REHAB` period may activate only after at least
    one district segment has reached `REHABILITATED` or `WARRANTY`
    (`ERR_NO_REHAB_YET`) — there must be something rehabilitated to measure."
    The district's only segment still has rehab_status NONE.

    Design: Difficulty/cross_entity_state_dependency/post_rehab_flow_activation_gated_on_segment_rehab_status
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-XD3", ii_reduction_target_pct=25, budget_cents=100000000)
    create_segment(district["id"], segment_ref="MH-33->MH-34")
    period = create_flow_period(district["id"], basin_label="B3", phase="POST_REHAB",
                                window_start="2026-08-11T00:00:00Z",
                                window_end="2026-08-25T00:00:00Z")
    resp = api.activate_flow_period(period["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_NO_REHAB_YET)


def test_pre_rehab_flow_activation_not_gated_on_rehab(api):
    """PRD §3.9: "Sequencing: a `POST_REHAB` period may activate only after at least
    one district segment has reached `REHABILITATED` or `WARRANTY`
    (`ERR_NO_REHAB_YET`) — there must be something rehabilitated to measure."
    The sequencing gate names POST_REHAB only; a PRE_REHAB period on the same
    unrehabilitated district activates.

    Design: Difficulty/cross_entity_state_dependency/post_rehab_flow_activation_gated_on_segment_rehab_status
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-XD3B", ii_reduction_target_pct=25, budget_cents=100000000)
    create_segment(district["id"], segment_ref="MH-33->MH-34")
    period = create_flow_period(district["id"], basin_label="B3", phase="PRE_REHAB",
                                window_start="2026-08-11T00:00:00Z",
                                window_end="2026-08-25T00:00:00Z")
    data = validate_success(api.activate_flow_period(period["id"], ENGINEER), 200)
    assert data["status"] == "ACTIVE"
