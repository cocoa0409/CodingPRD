"""Irrigation overlap geometry, the water budget gate and ledger partition, and
the season water guards (PRD §3.9, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_water_partition,
    create_irrigation_schedule_payload,
    current_season_version,
    get_season_counters,
    make_admin_headers,
    make_irrigation_schedule,
    setup_season_planting,
    validate_error,
    validate_success,
)

W = {
    "a_start": "2026-08-20T10:00:00Z",
    "a_end": "2026-08-20T11:00:00Z",
}


def _create_attempt(api, season_id, zone, start, end, gallons):
    """An irrigation create with the season's live version threaded (OCC)."""
    return api.create_irrigation_schedule(
        create_irrigation_schedule_payload(
            season_id=season_id,
            zone=zone,
            planned_start_at=start,
            planned_end_at=end,
            planned_gallons=gallons,
            expected_season_version=current_season_version(season_id),
        ),
        make_admin_headers(),
    )


def test_irrigation_half_open_adjacency_allowed_overlap_rejected(api):
    """PRD §3.9: "The overlap rule treats windows as half-open intervals: a window
    ending at an instant T and another beginning at T do not conflict. Two
    schedules in the same season and same zone conflict exactly when both are in
    an occupied status — `SCHEDULED`, `DUE`, `MISSED`, `LOGGED`, or `RECONCILED` —
    and each window's start is before the other's end. `CANCELLED` windows never
    block anything."

    Design: Difficulty/resource_temporal_overlap/irrigation_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = setup_season_planting(water_budget_gallons=100000)
    season_id = ctx["season"]["id"]

    irr_a = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 100
    )
    assert irr_a["status"] == "SCHEDULED"

    # B starts exactly at A.end: half-open adjacency is legal.
    irr_b = validate_success(
        _create_attempt(api, season_id, "Z1", "2026-08-20T11:00:00Z",
                        "2026-08-20T12:00:00Z", 100),
        expected_status=201,
    )
    assert irr_b["status"] == "SCHEDULED"

    # C truly intersects A (10:30 < 11:00 and 10:00 < 11:30).
    err = validate_error(
        _create_attempt(api, season_id, "Z1", "2026-08-20T10:30:00Z",
                        "2026-08-20T11:30:00Z", 100),
        ApiErrorId.ERR_IRRIGATION_OVERLAP,
    )
    assert err["error_id"] == "ERR_IRRIGATION_OVERLAP"

    # D ends exactly at A.start: adjacency on the other side is also legal.
    irr_d = validate_success(
        _create_attempt(api, season_id, "Z1", "2026-08-20T09:00:00Z",
                        "2026-08-20T10:00:00Z", 100),
        expected_status=201,
    )
    assert irr_d["status"] == "SCHEDULED"

    # E overlaps A in time but lives in a different zone.
    irr_e = validate_success(
        _create_attempt(api, season_id, "Z2", "2026-08-20T10:30:00Z",
                        "2026-08-20T11:30:00Z", 100),
        expected_status=201,
    )
    assert irr_e["status"] == "SCHEDULED"

    counters = get_season_counters(season_id)
    assert counters["committed"] == 400, "A + B + D + E"
    assert_water_partition(
        {
            "water_committed_gallons": counters["committed"],
            "water_actual_gallons": counters["actual"],
            "water_remaining_gallons": counters["remaining"],
            "water_budget_gallons": 100000,
        }
    )


def test_irrigation_overlap_beats_water_budget(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed global order and reports the first failure
    encountered — first match wins."
    PRD §2.6: "13. **Temporal windows.** `ERR_OUTSIDE_SEASON_WINDOW`,
    `ERR_SLOT_LOCKED`, `ERR_OUTSIDE_CHECKIN_WINDOW`, `ERR_HARVEST_IN_FUTURE`,
    `ERR_IRRIGATION_OVERLAP`, `ERR_BED_OCCUPANCY_OVERLAP`, and
    `ERR_BED_REST_PERIOD_ACTIVE` (409)."
    PRD §2.6: "15. **Water budget.** `ERR_WATER_BUDGET_EXCEEDED` (409)."
    PRD §3.9: "the window must not collide with another schedule in the same
    season and the same `zone` (otherwise `ERR_IRRIGATION_OVERLAP`); and the water
    budget gate must pass (otherwise `ERR_WATER_BUDGET_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/irrigation_overlap_beats_water_budget
    """
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id = ctx["season"]["id"]
    make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 700
    )

    # Overlaps A in zone Z1 AND 700 + 900 = 1600 > 1000: the temporal tier wins.
    err = validate_error(
        _create_attempt(api, season_id, "Z1", "2026-08-20T10:30:00Z",
                        "2026-08-20T11:30:00Z", 900),
        ApiErrorId.ERR_IRRIGATION_OVERLAP,
    )
    assert err["error_id"] == "ERR_IRRIGATION_OVERLAP"


def test_water_gate_evaluation_order_excludes_candidate(api):
    """PRD §3.9: "First, committed water is the sum of `planned_gallons` over the
    season's schedules in `SCHEDULED`, `DUE`, or `MISSED`, excluding the candidate
    itself, which is not yet persisted. Second, actual water is the sum of
    `gallons_actual` over the season's schedules in `LOGGED` or `RECONCILED`.
    Third, the projection is committed plus actual plus the candidate's
    `planned_gallons`. The gate passes exactly when the projection does not exceed
    the season's `water_budget_gallons` — exact equality is allowed."

    Design: Difficulty/combinatorial_formula/water_gate_evaluation_order_excludes_candidate
    """
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id = ctx["season"]["id"]

    make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 700
    )

    # 700 + 0 + 300 == 1000 <= 1000: exact fit allowed. If the candidate were
    # double-counted the gate would see 700 + 300 + 300 = 1300 and refuse.
    irr_b = validate_success(
        _create_attempt(api, season_id, "Z2", "2026-08-21T10:00:00Z",
                        "2026-08-21T11:00:00Z", 300),
        expected_status=201,
    )
    assert irr_b["status"] == "SCHEDULED"

    counters = get_season_counters(season_id)
    assert counters["committed"] == 1000
    assert counters["remaining"] == 0

    err = validate_error(
        _create_attempt(api, season_id, "Z3", "2026-08-22T10:00:00Z",
                        "2026-08-22T11:00:00Z", 1),
        ApiErrorId.ERR_WATER_BUDGET_EXCEEDED,
    )
    assert err["error_id"] == "ERR_WATER_BUDGET_EXCEEDED", "1000 + 1 > 1000"


def test_water_projected_vs_reconciled_divergence(api):
    """PRD §3.3: "`water_committed_gallons` is the sum of `planned_gallons` over
    the season's irrigation schedules in `SCHEDULED`, `DUE`, or `MISSED` — water
    promised but not yet metered. `water_actual_gallons` is the sum of
    `gallons_actual` over schedules in `LOGGED` or `RECONCILED` — water the meter
    has confirmed. `water_remaining_gallons` is the budget minus committed minus
    actual."
    PRD §3.3: "while the season runs, committed water counts unlogged plans, but
    once the season enters `RECONCILIATION` every still-open schedule is
    cascade-cancelled, committed collapses to zero, and final usage is read from
    `water_actual_gallons` alone".

    Design: Difficulty/dual_variant_calc/water_projected_vs_reconciled_divergence
    """
    admin = make_admin_headers()
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id, bed, plan = ctx["season"]["id"], ctx["bed"], ctx["plan"]

    irr_a = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 700
    )
    irr_b = make_irrigation_schedule(
        season_id, "Z2", "2026-08-21T10:00:00Z", "2026-08-21T11:00:00Z", 200
    )
    logged_b = validate_success(api.log_meter(irr_b["id"], {"gallons_actual": 260}, admin))
    assert logged_b["status"] == "LOGGED"

    # Walk the season to HARVESTING (bed RESERVED -> PLANTED, plan PLANTED).
    validate_success(api.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin))
    validate_success(api.transition_crop_plan(plan["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_bed(bed["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "GROWING"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "HARVESTING"}, admin))

    mid = get_season_counters(season_id)
    assert mid["committed"] == 700, "only SCHEDULED A counts; B left the set when LOGGED"
    assert mid["actual"] == 260
    assert mid["remaining"] == 40, "1000 - 700 - 260"

    validate_success(api.transition_season(season_id, {"to_state": "RECONCILIATION"}, admin))

    fin = get_season_counters(season_id)
    assert fin["committed"] == 0, "RECONCILIATION cascade-cancelled the open schedule"
    assert fin["actual"] == 260
    assert fin["remaining"] == 740
    assert mid["committed"] + mid["actual"] != fin["actual"], (
        "the forward-looking projection (960) diverges from settled usage (260) "
        "on identical ledger data"
    )
    irr_a_now = validate_success(api.get_irrigation_schedule(irr_a["id"], admin))
    assert irr_a_now["status"] == "CANCELLED"


def test_water_budget_partition_conserved_across_commit_cancel_log(api):
    """PRD §3.3: "`water_remaining_gallons` is the budget minus committed minus
    actual. Schedules in `CANCELLED` contribute to neither bucket."
    PRD §3.9: "Cancellation subtracts the schedule's `planned_gallons` from the
    season's `water_committed_gallons`, recomputes `water_remaining_gallons`".
    PRD §3.9: "rebalances the season's ledger: `water_committed_gallons` falls by
    the schedule's `planned_gallons`, `water_actual_gallons` rises by
    `gallons_actual`, and `water_remaining_gallons` is recomputed."
    PRD §3.9: "recomputes the schedule's `variance_flag` — true exactly when
    `gallons_actual` exceeds `planned_gallons` multiplied by 1.10 and rounded down
    to a whole gallon".

    Design: Difficulty/compensating_invariant/water_budget_partition_conserved_across_commit_cancel_log
    """
    admin = make_admin_headers()
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id = ctx["season"]["id"]

    irr_a = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 700
    )
    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"], counters["remaining"]) == (700, 0, 300)

    validate_success(
        api.transition_irrigation_schedule(irr_a["id"], {"to_state": "CANCELLED"}, admin)
    )
    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"], counters["remaining"]) == (0, 0, 1000), (
        "cancel fully compensates"
    )

    irr_b = make_irrigation_schedule(
        season_id, "Z2", "2026-08-21T10:00:00Z", "2026-08-21T11:00:00Z", 400
    )
    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"], counters["remaining"]) == (400, 0, 600)

    logged = validate_success(api.log_meter(irr_b["id"], {"gallons_actual": 380}, admin))
    assert logged["status"] == "LOGGED"
    assert logged["variance_flag"] is False, "380 <= floor(400 * 1.10) == 440"

    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"], counters["remaining"]) == (0, 380, 620), (
        "the 20-gallon shortfall accrues to remaining; the partition still sums to 1000"
    )


def test_season_harvesting_blocked_by_missed_irrigation(api):
    """PRD §3.9: "a schedule in `SCHEDULED` or `DUE` whose window has closed — the
    clock strictly past `planned_end_at` — with no meter reading logged becomes
    `MISSED`."
    PRD §3.3: "`GROWING → HARVESTING` requires zero irrigation schedules for the
    season in `DUE` or `MISSED`, otherwise `ERR_IRRIGATION_UNRESOLVED`."
    PRD §3.9: "a `GardenAdmin` or `Coordinator` logs the meter for a schedule in
    `SCHEDULED`, `DUE`, or `MISSED` (otherwise `ERR_INVALID_IRRIGATION_STATE`)".

    Design: Corner/state_machines/season_harvesting_blocked_by_missed_irrigation
    """
    admin = make_admin_headers()
    ctx = setup_season_planting()
    season_id, bed, plan = ctx["season"]["id"], ctx["bed"], ctx["plan"]
    validate_success(api.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin))
    validate_success(api.transition_crop_plan(plan["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "GROWING"}, admin))

    irr = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 50
    )
    validate_success(api.set_clock({"to_iso8601": "2026-08-20T12:00:00Z"}, admin))
    validate_success(api.run_epoch(admin))

    irr_now = validate_success(api.get_irrigation_schedule(irr["id"], admin))
    assert irr_now["status"] == "MISSED", "window closed at the epoch with no meter log"

    err = validate_error(
        api.transition_season(season_id, {"to_state": "HARVESTING"}, admin),
        ApiErrorId.ERR_IRRIGATION_UNRESOLVED,
    )
    assert err["error_id"] == "ERR_IRRIGATION_UNRESOLVED"

    logged = validate_success(api.log_meter(irr["id"], {"gallons_actual": 45}, admin))
    assert logged["status"] == "LOGGED", "a late log from MISSED is allowed"

    harvested = validate_success(
        api.transition_season(season_id, {"to_state": "HARVESTING"}, admin)
    )
    assert harvested["status"] == "HARVESTING"


def test_season_close_requires_reconciled_irrigation(api):
    """PRD §3.3: "`RECONCILIATION → CLOSED` requires zero irrigation schedules
    for the season in `SCHEDULED`, `DUE`, `MISSED`, or `LOGGED`, otherwise
    `ERR_IRRIGATION_UNRESOLVED`".
    PRD §3.9: "A `GardenAdmin` alone may then move a `LOGGED` schedule to
    `RECONCILED`, marking the reading as audited."
    PRD §3.3: "Any transition attempted from a from-state it does not allow is
    rejected with `ERR_INVALID_SEASON_STATE`. `CLOSED` and `CANCELLED` are
    terminal."

    Design: Corner/state_machines/season_close_requires_reconciled_irrigation
    """
    admin = make_admin_headers()
    ctx = setup_season_planting()
    season_id, bed, plan = ctx["season"]["id"], ctx["bed"], ctx["plan"]

    irr = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 50
    )
    validate_success(api.log_meter(irr["id"], {"gallons_actual": 45}, admin))

    validate_success(api.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin))
    validate_success(api.transition_crop_plan(plan["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_bed(bed["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "GROWING"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "HARVESTING"}, admin))
    reconciled = validate_success(
        api.transition_season(season_id, {"to_state": "RECONCILIATION"}, admin)
    )
    assert reconciled["status"] == "RECONCILIATION"

    err = validate_error(
        api.transition_season(season_id, {"to_state": "CLOSED"}, admin),
        ApiErrorId.ERR_IRRIGATION_UNRESOLVED,
    )
    assert err["error_id"] == "ERR_IRRIGATION_UNRESOLVED", "LOGGED but not RECONCILED"

    irr_now = validate_success(
        api.transition_irrigation_schedule(irr["id"], {"to_state": "RECONCILED"}, admin)
    )
    assert irr_now["status"] == "RECONCILED"

    closed = validate_success(
        api.transition_season(season_id, {"to_state": "CLOSED"}, admin)
    )
    assert closed["status"] == "CLOSED"

    err = validate_error(
        api.transition_season(season_id, {"to_state": "OPEN_ENROLLMENT"}, admin),
        ApiErrorId.ERR_INVALID_SEASON_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_SEASON_STATE", "CLOSED is terminal"


def test_water_projection_diverges_with_under_delivery(api):
    """PRD §3.3: "`water_committed_gallons` is the sum of `planned_gallons` over
    the season's irrigation schedules in `SCHEDULED`, `DUE`, or `MISSED` — water
    promised but not yet metered. `water_actual_gallons` is the sum of
    `gallons_actual` over schedules in `LOGGED` or `RECONCILED` — water the meter
    has confirmed. `water_remaining_gallons` is the budget minus committed minus
    actual."
    PRD §3.3: "once the season enters `RECONCILIATION` every still-open schedule
    is cascade-cancelled, committed collapses to zero, and final usage is read
    from `water_actual_gallons` alone — a number that diverges from the earlier
    projection whenever actual meter readings differ from plans."

    Design: Difficulty/dual_variant_calc/water_projected_vs_reconciled_divergence
    """
    admin = make_admin_headers()
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id, bed, plan = ctx["season"]["id"], ctx["bed"], ctx["plan"]

    irr_a = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 400
    )
    validate_success(api.log_meter(irr_a["id"], {"gallons_actual": 300}, admin))
    irr_b = make_irrigation_schedule(
        season_id, "Z2", "2026-08-21T10:00:00Z", "2026-08-21T11:00:00Z", 600
    )

    validate_success(api.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin))
    validate_success(api.transition_crop_plan(plan["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_bed(bed["id"], {"to_state": "PLANTED"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "GROWING"}, admin))
    validate_success(api.transition_season(season_id, {"to_state": "HARVESTING"}, admin))

    mid = get_season_counters(season_id)
    assert (mid["committed"], mid["actual"], mid["remaining"]) == (600, 300, 100), (
        "forward-looking projection reads committed + actual = 900"
    )

    validate_success(api.transition_season(season_id, {"to_state": "RECONCILIATION"}, admin))
    fin = get_season_counters(season_id)
    assert (fin["committed"], fin["actual"], fin["remaining"]) == (0, 300, 700), (
        "settled usage reads actual alone"
    )
    assert mid["committed"] + mid["actual"] != fin["actual"]
    irr_b_now = validate_success(api.get_irrigation_schedule(irr_b["id"], admin))
    assert irr_b_now["status"] == "CANCELLED"


def test_water_gate_counts_logged_actual_only(api):
    """PRD §3.9: "First, committed water is the sum of `planned_gallons` over the
    season's schedules in `SCHEDULED`, `DUE`, or `MISSED`, excluding the candidate
    itself, which is not yet persisted. Second, actual water is the sum of
    `gallons_actual` over the season's schedules in `LOGGED` or `RECONCILED`.
    Third, the projection is committed plus actual plus the candidate's
    `planned_gallons`. The gate passes exactly when the projection does not exceed
    the season's `water_budget_gallons` — exact equality is allowed."

    Design: Difficulty/combinatorial_formula/water_gate_evaluation_order_excludes_candidate
    """
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id = ctx["season"]["id"]
    admin = make_admin_headers()

    irr_a = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 600
    )
    validate_success(api.log_meter(irr_a["id"], {"gallons_actual": 150}, admin))
    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"]) == (0, 150), (
        "a LOGGED schedule has left the committed set"
    )

    # 0 + 150 + 850 == 1000: exact fit allowed against the budget.
    irr_b = validate_success(
        _create_attempt(api, season_id, "Z2", "2026-08-21T10:00:00Z",
                        "2026-08-21T11:00:00Z", 850),
        expected_status=201,
    )
    assert irr_b["status"] == "SCHEDULED"

    err = validate_error(
        _create_attempt(api, season_id, "Z3", "2026-08-22T10:00:00Z",
                        "2026-08-22T11:00:00Z", 1),
        ApiErrorId.ERR_WATER_BUDGET_EXCEEDED,
    )
    assert err["error_id"] == "ERR_WATER_BUDGET_EXCEEDED"


def test_water_budget_error_when_no_overlap(api):
    """PRD §3.9: "the window must not collide with another schedule in the same
    season and the same `zone` (otherwise `ERR_IRRIGATION_OVERLAP`); and the water
    budget gate must pass (otherwise `ERR_WATER_BUDGET_EXCEEDED`)".
    PRD §3.9: "The gate passes exactly when the projection does not exceed the
    season's `water_budget_gallons` — exact equality is allowed."

    Design: Difficulty/priority_pair_validation_conflict/irrigation_overlap_beats_water_budget
    """
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id = ctx["season"]["id"]
    make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 700
    )

    # A different zone at a disjoint time: only the budget gate can fail.
    err = validate_error(
        _create_attempt(api, season_id, "Z2", "2026-08-21T10:00:00Z",
                        "2026-08-21T11:00:00Z", 400),
        ApiErrorId.ERR_WATER_BUDGET_EXCEEDED,
    )
    assert err["error_id"] == "ERR_WATER_BUDGET_EXCEEDED", "700 + 400 > 1000"


def test_cancelled_irrigation_window_never_blocks(api):
    """PRD §3.9: "Two schedules in the same season and same zone conflict exactly
    when both are in an occupied status — `SCHEDULED`, `DUE`, `MISSED`, `LOGGED`,
    or `RECONCILED` — and each window's start is before the other's end.
    `CANCELLED` windows never block anything."

    Design: Difficulty/resource_temporal_overlap/irrigation_half_open_adjacency_allowed_overlap_rejected
    """
    admin = make_admin_headers()
    ctx = setup_season_planting(water_budget_gallons=100000)
    season_id = ctx["season"]["id"]

    irr_a = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 100
    )
    validate_success(
        api.transition_irrigation_schedule(irr_a["id"], {"to_state": "CANCELLED"}, admin)
    )

    # This window intersects the cancelled one; the cancelled window never blocks.
    irr_b = validate_success(
        _create_attempt(api, season_id, "Z1", "2026-08-20T10:30:00Z",
                        "2026-08-20T11:30:00Z", 100),
        expected_status=201,
    )
    assert irr_b["status"] == "SCHEDULED"
    counters = get_season_counters(season_id)
    assert counters["committed"] == 100, "only the live schedule commits water"


def test_water_partition_variance_flag_true_branch(api):
    """PRD §3.9: "Logging records the reading, recomputes the schedule's
    `variance_flag` — true exactly when `gallons_actual` exceeds `planned_gallons`
    multiplied by 1.10 and rounded down to a whole gallon, and false until any
    reading exists — and rebalances the season's ledger: `water_committed_gallons`
    falls by the schedule's `planned_gallons`, `water_actual_gallons` rises by
    `gallons_actual`, and `water_remaining_gallons` is recomputed."
    PRD §3.3: "`water_remaining_gallons` is the budget minus committed minus
    actual."

    Design: Difficulty/compensating_invariant/water_budget_partition_conserved_across_commit_cancel_log
    """
    admin = make_admin_headers()
    ctx = setup_season_planting(water_budget_gallons=1000)
    season_id = ctx["season"]["id"]

    irr = make_irrigation_schedule(
        season_id, "Z1", "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", 400
    )
    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"], counters["remaining"]) == (400, 0, 600)

    # 500 > floor(400 * 1.10) == 440: the variance flag flips true.
    logged = validate_success(api.log_meter(irr["id"], {"gallons_actual": 500}, admin))
    assert logged["status"] == "LOGGED"
    assert logged["variance_flag"] is True

    counters = get_season_counters(season_id)
    assert (counters["committed"], counters["actual"], counters["remaining"]) == (0, 500, 500), (
        "the overrun leaves the partition conserved at 1000"
    )
