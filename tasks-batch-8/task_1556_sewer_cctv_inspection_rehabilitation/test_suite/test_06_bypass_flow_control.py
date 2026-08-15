"""Bypass pumping: window overlap geometry, mobilization gate, stand-down cascade."""
from test_helpers import (
    ApiErrorId,
    approve_bypass_plan,
    begin_work,
    create_bypass_plan,
    create_work_order,
    get_plan,
    get_segment,
    get_success_data,
    make_crew_lead_headers,
    mobilize,
    set_clock,
    setup_plan_with_work_order,
    validate_error,
    validate_success,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]

# 300 mm segment -> ceil(300/25.4) = 12 inches -> 25 * 12 = 300 gpm required pump.
FULL_REPLACE_CERT = {
    "material": "RCP", "diameter_mm": 300, "length_m": 120, "install_year": 1965,
    "defects": [{"pacp_code": "B", "family": "STRUCTURAL", "grade": 4,
                 "distance_m": 60, "clock_position": 12}],
}


def _setup_full_replace_two_work_orders(api, district_name="D-TO"):
    """FULL_REPLACE plan approved (PRD §3.5 requires APPROVED before work orders),
    two ISSUED work orders on the same 300 mm segment."""
    ctx = setup_plan_with_work_order(method="FULL_REPLACE", lines=None, approve=True,
                                     cert_kwargs=dict(FULL_REPLACE_CERT))
    w2 = create_work_order(ctx["plan"]["id"], ctx["crew"]["id"])
    return ctx, ctx["work_order"], w2


def test_bypass_window_overlap_buffered_half_open(api):
    """PRD §3.6: "Scheduling safety then widens each window by a thirty-minute setup
    buffer on both ends and checks the buffered half-open intervals of all other
    bypass plans — for work orders of the same segment — currently in `APPROVED` or
    `ACTIVE`; any intersection is rejected with `ERR_BYPASS_WINDOW_CONFLICT`."
    BP1 [08:00,12:00) approved (buffered [07:30,12:30)); BP2 [12:00,16:00) buffered
    to [11:30,16:30) intersects it over [11:30,12:30).

    Design: Difficulty/resource_temporal_overlap/bypass_window_overlap_buffered_half_open
    """
    ctx, w1, w2 = _setup_full_replace_two_work_orders(api)
    crew_id = ctx["crew"]["id"]
    bp1 = create_bypass_plan(w1["id"], crew_id, window_start="2026-08-12T08:00:00Z",
                             window_end="2026-08-12T12:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp1["id"])
    bp2 = create_bypass_plan(w2["id"], crew_id, window_start="2026-08-12T12:00:00Z",
                             window_end="2026-08-12T16:00:00Z", pump_capacity_gpm=300)
    resp = api.approve_bypass_plan(bp2["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_BYPASS_WINDOW_CONFLICT)


def test_bypass_non_overlapping_window_approved(api):
    """PRD §3.6: "Scheduling safety then widens each window by a thirty-minute setup
    buffer on both ends and checks the buffered half-open intervals of all other
    bypass plans — for work orders of the same segment — currently in `APPROVED` or
    `ACTIVE`; any intersection is rejected with `ERR_BYPASS_WINDOW_CONFLICT`."
    A same-crew plan on the following day shares no buffered instants with the
    approved one and is approved.

    Design: Difficulty/resource_temporal_overlap/bypass_window_overlap_buffered_half_open
    """
    ctx, w1, w2 = _setup_full_replace_two_work_orders(api)
    crew_id = ctx["crew"]["id"]
    bp1 = create_bypass_plan(w1["id"], crew_id, window_start="2026-08-12T08:00:00Z",
                             window_end="2026-08-12T12:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp1["id"])
    bp3 = create_bypass_plan(w2["id"], crew_id, window_start="2026-08-13T08:00:00Z",
                             window_end="2026-08-13T12:00:00Z", pump_capacity_gpm=300)
    data = validate_success(api.approve_bypass_plan(bp3["id"], ENGINEER), 200)
    assert data["status"] == "APPROVED"


def test_bypass_adjacency_exactly_at_buffered_end_accepted(api):
    """PRD §3.6: "Bypass windows use half-open interval semantics: the window covers
    every instant from its start up to but not including its end."
    PRD §3.6: "Scheduling safety then widens each window by a thirty-minute setup
    buffer on both ends and checks the buffered half-open intervals of all other
    bypass plans — for work orders of the same segment — currently in `APPROVED` or
    `ACTIVE`; any intersection is rejected with `ERR_BYPASS_WINDOW_CONFLICT`."
    BP1 buffered [07:30,12:30) vs BP2 buffered [12:30,16:30): half-open intervals that
    merely touch at 12:30 do not intersect, so the approval succeeds.

    Design: Difficulty/boundary_precision_check/bypass_window_adjacency_half_open_buffer_boundary
    """
    ctx, w1, w2 = _setup_full_replace_two_work_orders(api)
    crew_id = ctx["crew"]["id"]
    bp1 = create_bypass_plan(w1["id"], crew_id, window_start="2026-08-12T08:00:00Z",
                             window_end="2026-08-12T12:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp1["id"])
    bp2 = create_bypass_plan(w2["id"], crew_id, window_start="2026-08-12T13:00:00Z",
                             window_end="2026-08-12T16:00:00Z", pump_capacity_gpm=300)
    data = validate_success(api.approve_bypass_plan(bp2["id"], ENGINEER), 200)
    assert data["status"] == "APPROVED"


def test_bypass_one_minute_inside_buffered_end_rejected(api):
    """PRD §3.6: "Scheduling safety then widens each window by a thirty-minute setup
    buffer on both ends and checks the buffered half-open intervals of all other
    bypass plans — for work orders of the same segment — currently in `APPROVED` or
    `ACTIVE`; any intersection is rejected with `ERR_BYPASS_WINDOW_CONFLICT`."
    Starting BP3 at 12:29 buffers it to 11:59, which intersects BP1's buffered
    [07:30,12:30) — one minute inside the accepted boundary flips the outcome.

    Design: Difficulty/boundary_precision_check/bypass_window_adjacency_half_open_buffer_boundary
    """
    ctx, w1, w2 = _setup_full_replace_two_work_orders(api)
    crew_id = ctx["crew"]["id"]
    bp1 = create_bypass_plan(w1["id"], crew_id, window_start="2026-08-12T08:00:00Z",
                             window_end="2026-08-12T12:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp1["id"])
    bp3 = create_bypass_plan(w2["id"], crew_id, window_start="2026-08-12T12:29:00Z",
                             window_end="2026-08-12T16:00:00Z", pump_capacity_gpm=300)
    resp = api.approve_bypass_plan(bp3["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_BYPASS_WINDOW_CONFLICT)


def test_mobilize_full_replace_blocked_until_bypass_approved(api):
    """PRD §3.5: "For a `FULL_REPLACE` job, an approved bypass plan must already
    exist for the work order (`ERR_BYPASS_REQUIRED`), because open-cut excavation
    cannot proceed without flow control in place."
    The bypass plan exists but is still PROPOSED, so mobilization is rejected.

    Design: Difficulty/cross_entity_state_dependency/mobilize_gated_on_bypassplan_state_full_replace
    """
    ctx = setup_plan_with_work_order(method="FULL_REPLACE", lines=None, approve=True,
                                     cert_kwargs=dict(FULL_REPLACE_CERT))
    bp = create_bypass_plan(ctx["work_order"]["id"], ctx["crew"]["id"],
                            window_start="2026-08-11T08:00:00Z",
                            window_end="2026-08-11T18:00:00Z", pump_capacity_gpm=300)
    resp = api.mobilize_work_order(ctx["work_order"]["id"], make_crew_lead_headers(ctx["crew"]["id"]))
    validate_error(resp, ApiErrorId.ERR_BYPASS_REQUIRED)
    assert bp["status"] == "PROPOSED"


def test_mobilize_full_replace_succeeds_after_bypass_approved(api):
    """PRD §3.5: "For a `FULL_REPLACE` job, an approved bypass plan must already
    exist for the work order (`ERR_BYPASS_REQUIRED`), because open-cut excavation
    cannot proceed without flow control in place."
    PRD §3.5: "A successful mobilization bubbles upward: the parent plan moves
    `APPROVED` → `EXECUTING` automatically, and the segment's `rehab_status` becomes
    `IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/mobilize_gated_on_bypassplan_state_full_replace
    """
    ctx = setup_plan_with_work_order(method="FULL_REPLACE", lines=None, approve=True,
                                     cert_kwargs=dict(FULL_REPLACE_CERT))
    bp = create_bypass_plan(ctx["work_order"]["id"], ctx["crew"]["id"],
                            window_start="2026-08-11T08:00:00Z",
                            window_end="2026-08-11T18:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp["id"])
    data = validate_success(
        api.mobilize_work_order(ctx["work_order"]["id"], make_crew_lead_headers(ctx["crew"]["id"])),
        200,
    )
    assert data["execution_status"] == "MOBILIZED"
    assert get_plan(ctx["plan"]["id"])["status"] == "EXECUTING"
    assert get_segment(ctx["segment"]["id"])["rehab_status"] == "IN_PROGRESS"


def _setup_in_work_with_active_bypass(api):
    """FULL_REPLACE work order driven to IN_WORK with an ACTIVE bypass plan;
    logical clock is inside the bypass window."""
    set_clock("2026-08-10T10:00:00Z")
    ctx = setup_plan_with_work_order(method="FULL_REPLACE", lines=None, approve=True,
                                     cert_kwargs=dict(FULL_REPLACE_CERT, clock="2026-08-10T10:00:00Z"))
    crew_id = ctx["crew"]["id"]
    bp = create_bypass_plan(ctx["work_order"]["id"], crew_id,
                            window_start="2026-08-10T08:00:00Z",
                            window_end="2026-08-10T18:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp["id"])
    mobilize(ctx["work_order"]["id"], crew_id)
    validate_success(api.activate_bypass_plan(bp["id"], make_crew_lead_headers(crew_id)), 200)
    begin_work(ctx["work_order"]["id"], crew_id)
    return ctx, bp


def test_stand_down_returns_work_order_to_mobilized(api):
    """PRD §3.5: "Weather or a utility strike can force a stand-down, `IN_WORK` →
    `MOBILIZED`, which cascades downward: any `ACTIVE` bypass plan for the work order
    is demobilized with it."

    Design: Difficulty/transitive_cascade/bypass_stand_down_depth2_cascade
    """
    ctx, _ = _setup_in_work_with_active_bypass(api)
    data = validate_success(
        api.stand_down_work_order(ctx["work_order"]["id"],
                                  make_crew_lead_headers(ctx["crew"]["id"])),
        200,
    )
    assert data["execution_status"] == "MOBILIZED"


def test_stand_down_cascades_active_bypass_to_demobilized(api):
    """PRD §3.5: "Weather or a utility strike can force a stand-down, `IN_WORK` →
    `MOBILIZED`, which cascades downward: any `ACTIVE` bypass plan for the work order
    is demobilized with it."
    The bypass mutation is caused by the work-order transition, not invoked directly.

    Design: Difficulty/transitive_cascade/bypass_stand_down_depth2_cascade
    """
    ctx, bp = _setup_in_work_with_active_bypass(api)
    validate_success(
        api.stand_down_work_order(ctx["work_order"]["id"],
                                  make_crew_lead_headers(ctx["crew"]["id"])),
        200,
    )
    bp_after = get_success_data(api.get_bypass_plan(bp["id"], ENGINEER))
    assert bp_after["status"] == "DEMOBILIZED"


def test_bypass_approve_reject_action_endpoints(api):
    """PRD §3.6: "A `DistrictEngineer` may instead reject a proposed bypass outright,
    moving it `PROPOSED` → `REJECTED`."
    PRD §2.10: "4. **State eligibility** — the target resource sits in a from-state
    that lists the requested transition, otherwise `ERR_INVALID_STATE`."
    REJECTED lists no outgoing approve transition, so the later approve is rejected.

    Design: Corner/endpoints/bypass_approve_reject_action_endpoints
    """
    ctx = setup_plan_with_work_order(method="FULL_REPLACE", lines=None, approve=True,
                                     cert_kwargs=dict(FULL_REPLACE_CERT))
    bp = create_bypass_plan(ctx["work_order"]["id"], ctx["crew"]["id"],
                            window_start="2026-08-11T08:00:00Z",
                            window_end="2026-08-11T18:00:00Z", pump_capacity_gpm=300)
    rejected = validate_success(api.reject_bypass_plan(bp["id"], ENGINEER), 200)
    assert rejected["status"] == "REJECTED"
    resp = api.approve_bypass_plan(bp["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_activate_bypass_before_window_start_rejected(api):
    """PRD §3.6: "The `CrewLead` activates an approved plan — `APPROVED` → `ACTIVE` —
    only while the logical clock sits inside the window, meaning at or after
    `window_start` and strictly before `window_end` (`ERR_OUTSIDE_WINDOW`), and only
    while the parent work order is `MOBILIZED` or `IN_WORK` (`ERR_INVALID_STATE`)."

    Design: Corner/endpoints/activate_bypass_before_window_start_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    ctx = setup_plan_with_work_order(method="FULL_REPLACE", lines=None, approve=True,
                                     cert_kwargs=dict(FULL_REPLACE_CERT))
    crew_id = ctx["crew"]["id"]
    bp = create_bypass_plan(ctx["work_order"]["id"], crew_id,
                            window_start="2026-08-12T08:00:00Z",
                            window_end="2026-08-12T18:00:00Z", pump_capacity_gpm=300)
    approve_bypass_plan(bp["id"])
    mobilize(ctx["work_order"]["id"], crew_id)
    set_clock("2026-08-11T09:00:00Z")  # window starts 2026-08-12T08:00:00Z
    resp = api.activate_bypass_plan(bp["id"], make_crew_lead_headers(crew_id))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)
