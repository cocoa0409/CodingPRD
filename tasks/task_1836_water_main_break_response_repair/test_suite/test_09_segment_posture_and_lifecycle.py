"""Segment repeat-break posture (provisional vs official variants, cyclic
WATCH/CANDIDATE regression, replacement) and the BreakReport fork/loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_work_order,
    confirm_break,
    create_break,
    create_crew,
    create_segment,
    create_valve,
    get_break,
    get_segment,
    isolate_break,
    make_crew_lead_headers,
    run_ops,
    set_clock,
    setup_confirmed_break,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import (
    confirm_break_report_payload,
    create_work_order_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _repair_break_full_cycle(break_id, valve_ids, crew_id):
    """Isolate -> work order -> dispatch -> arrive -> complete (break REPAIRED)."""
    isolate_break(break_id, valve_ids)
    wo = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=break_id, est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    validate_success(
        _api.dispatch_work_order(wo["id"], {"crew_id": crew_id}, DISPATCHER), 200
    )
    validate_success(
        _api.arrive_work_order(wo["id"], make_crew_lead_headers(crew_id)), 200
    )
    return complete_work_order(wo["id"], crew_id, actual_pipe_length_ft=4,
                               labor_hours=1, materials_used=[])


def _elm_segment_with_crew():
    seg = create_segment(segment_ref="MAIN-8-ELM", material="CAST_IRON",
                         diameter_inches=8, install_year=1962)
    valve = create_valve(seg["id"], "V-ELM-1", coverage_zone="Z1",
                         customers_served=100)
    crew = create_crew(crew_name="Crew Beta", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    return seg, valve, crew


# ---------------------------------------------------------------------------
# Difficulty: segment_repeat_break_provisional_vs_official (2 tests)
# ---------------------------------------------------------------------------

def _elm_two_repaired_one_confirmed():
    """B1, B2 fully repaired; B3 confirmed only — all within the trailing
    36 months of the ops run at the default clock."""
    seg, valve, crew = _elm_segment_with_crew()

    b1 = create_break(location_description="100 Elm St", source="CUSTOMER_CALL")
    b1 = confirm_break(b1["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                       severity="MEDIUM")
    _repair_break_full_cycle(b1["id"], [valve["id"]], crew["id"])

    set_clock("2026-08-01T06:00:00Z")
    b2 = create_break(location_description="240 Elm St", source="SENSOR_SCADA")
    b2 = confirm_break(b2["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                       severity="LOW")
    _repair_break_full_cycle(b2["id"], [valve["id"]], crew["id"])

    b3 = create_break(location_description="310 Elm St", source="CREW_OBSERVATION")
    b3 = confirm_break(b3["id"], seg["id"], break_type="SPLIT", severity="MEDIUM")
    return {"segment": seg, "valve": valve, "crew": crew,
            "b1": b1, "b2": b2, "b3": b3}


def test_official_count_excludes_in_progress_breaks(api):
    """PRD §3.8: "The official count, `repeat_break_count_36mo`, counts this
    segment's breaks currently in `REPAIRED`, `RESTORED`, or `CLOSED` status.
    The provisional count, `provisional_break_count_36mo`, counts this
    segment's breaks in `CONFIRMED`, `ISOLATED`, `IN_REPAIR`, `REPAIRED`,
    `RESTORED`, or `CLOSED` — it adds in-progress breaks, so it is at least the
    official count whenever a confirmed-but-unfinished break exists. Breaks
    still `REPORTED` and breaks marked `FALSE_ALARM` are excluded from both
    variants."

    Design: Difficulty/dual_variant_calc/segment_repeat_break_provisional_vs_official
    """
    ctx = _elm_two_repaired_one_confirmed()
    run_ops()
    seg = get_segment(ctx["segment"]["id"])
    assert seg["repeat_break_count_36mo"] == 2, (
        f"official counts only the two REPAIRED breaks, got "
        f"{seg['repeat_break_count_36mo']}"
    )


def test_provisional_count_includes_confirmed_and_drives_nothing(api):
    """PRD §3.8: "The provisional count, `provisional_break_count_36mo`, counts
    this segment's breaks in `CONFIRMED`, `ISOLATED`, `IN_REPAIR`, `REPAIRED`,
    `RESTORED`, or `CLOSED` — it adds in-progress breaks, so it is at least the
    official count whenever a confirmed-but-unfinished break exists."
    PRD §3.8: "The condition posture derives from the official count: an
    official count of 3 or more puts the segment at `CANDIDATE`; exactly 2 puts
    it at `WATCH`; and 1 or fewer puts it at `NONE`."

    Design: Difficulty/dual_variant_calc/segment_repeat_break_provisional_vs_official
    """
    ctx = _elm_two_repaired_one_confirmed()
    run_ops()
    seg = get_segment(ctx["segment"]["id"])
    assert seg["provisional_break_count_36mo"] == 3, (
        f"provisional adds the in-progress CONFIRMED break, got "
        f"{seg['provisional_break_count_36mo']}"
    )
    assert seg["condition_status"] == "WATCH", (
        f"condition derives from the official count (2 -> WATCH), got "
        f"{seg['condition_status']!r}"
    )


# ---------------------------------------------------------------------------
# Difficulty: pipe_segment_watch_candidate_cycle (2 tests)
# ---------------------------------------------------------------------------

def _birch_three_repaired_at_dates():
    """Segment MAIN-12-BIRCH; B1 repaired at 2023-01-15, B2 at 2023-06-15,
    B3 at 2023-06-16; ops run at 2023-07-01."""
    seg = create_segment(segment_ref="MAIN-12-BIRCH", material="CAST_IRON",
                         diameter_inches=12, install_year=1958)
    valve = create_valve(seg["id"], "V-BIRCH-1", coverage_zone="Z1",
                         customers_served=100)
    crew = create_crew(crew_name="Crew Birch", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    for when, loc, src in (
        ("2023-01-15T00:00:00Z", "10 Birch Ln", "CUSTOMER_CALL"),
        ("2023-06-15T00:00:00Z", "22 Birch Ln", "CUSTOMER_CALL"),
        ("2023-06-16T00:00:00Z", "30 Birch Ln", "SENSOR_SCADA"),
    ):
        set_clock(when)
        b = create_break(location_description=loc, source=src)
        sev = "HIGH" if loc == "30 Birch Ln" else "MEDIUM"
        b = confirm_break(b["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                          severity=sev)
        _repair_break_full_cycle(b["id"], [valve["id"]], crew["id"])
    set_clock("2023-07-01T00:00:00Z")
    run_ops()
    return seg


def test_candidate_after_three_breaks_in_window(api):
    """PRD §3.8: "The condition posture derives from the official count: an
    official count of 3 or more puts the segment at `CANDIDATE`; exactly 2 puts
    it at `WATCH`; and 1 or fewer puts it at `NONE`."

    Design: Difficulty/non_linear_state_machine/pipe_segment_watch_candidate_cycle
    """
    seg = _birch_three_repaired_at_dates()
    after = get_segment(seg["id"])
    assert after["repeat_break_count_36mo"] == 3
    assert after["condition_status"] == "CANDIDATE", (
        f"official count 3 must derive CANDIDATE, got {after['condition_status']!r}"
    )


def test_candidate_regresses_to_watch_as_breaks_age_out(api):
    """PRD §3.8: "The repeat-break counts use a 36-month trailing window:
    breaks whose `confirmed_at` falls within the window from 36 months before
    the clock now through the clock now, inclusive of the start boundary."
    PRD §3.8: "Because the derivation is re-run at every checkpoint, regression
    is cyclic — a `CANDIDATE` segment whose older breaks age out of the
    36-month window falls back to `WATCH` when the count drops to exactly 2,
    and `WATCH` or `CANDIDATE` segments fall back to `NONE` when the count
    drops to 1 or fewer."

    Design: Difficulty/non_linear_state_machine/pipe_segment_watch_candidate_cycle
    """
    seg = _birch_three_repaired_at_dates()
    assert get_segment(seg["id"])["condition_status"] == "CANDIDATE"
    # At 2026-04-01 the window is [2023-04-01, 2026-04-01]: B1 (2023-01-15)
    # has aged out; B2/B3 remain.
    set_clock("2026-04-01T00:00:00Z")
    run_ops()
    after = get_segment(seg["id"])
    assert after["repeat_break_count_36mo"] == 2, (
        f"B1 must age out of the trailing 36-month window, got "
        f"{after['repeat_break_count_36mo']}"
    )
    assert after["condition_status"] == "WATCH", (
        f"cyclic regression CANDIDATE -> WATCH when the count drops to 2, got "
        f"{after['condition_status']!r}"
    )


# ---------------------------------------------------------------------------
# Difficulty: break_report_branch_and_rework_loop (2 tests)
# ---------------------------------------------------------------------------

def _oak_repaired_break_and_false_alarm_sibling():
    """Break A fully repaired on MAIN-8-OAK; break B marked FALSE_ALARM."""
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", diameter_inches=8, install_year=1978,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="400 Oak St",
    )
    crew = create_crew(crew_name="Crew Oak", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    _repair_break_full_cycle(ctx["break"]["id"], [ctx["valves"][0]["id"]],
                             crew["id"])
    ctx["crew"] = crew
    ctx["break"] = get_break(ctx["break"]["id"])

    br_b = create_break(location_description="401 Oak St (puddle)",
                        source="CUSTOMER_CALL")
    br_b = validate_success(
        _api.false_alarm_break_report(br_b["id"], DISPATCHER), 200
    )
    ctx["break_b"] = br_b
    return ctx


def test_confirm_on_false_alarm_break_rejected(api):
    """PRD §3.2: "If the report turns out to be unfounded, the `Dispatcher`
    instead marks it a false alarm, moving `REPORTED` to `FALSE_ALARM`; a false
    alarm is terminal and excluded from every count and every downstream
    workflow."

    Design: Difficulty/non_linear_state_machine/break_report_branch_and_rework_loop
    """
    ctx = _oak_repaired_break_and_false_alarm_sibling()
    br_b, seg = ctx["break_b"], ctx["segment"]
    assert br_b["break_status"] == "FALSE_ALARM"
    resp = _api.confirm_break_report(
        br_b["id"],
        confirm_break_report_payload(
            pipe_segment_id=seg["id"], break_type="SPLIT", severity="LOW"
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_repaired_break_reenters_in_repair_via_rework_isolation(api):
    """PRD §3.3: "The parent break must be in `CONFIRMED` or `REPAIRED` status
    — the latter covers rework re-isolation after a failed repair — and any
    other state yields `ERR_INVALID_STATE`."
    PRD §3.4: "Arrival cascades the break from `ISOLATED` to `IN_REPAIR` — on
    rework, the break re-enters `IN_REPAIR` only after a fresh isolation has
    moved it `REPAIRED` → `ISOLATED` first."

    Design: Difficulty/non_linear_state_machine/break_report_branch_and_rework_loop
    """
    ctx = _oak_repaired_break_and_false_alarm_sibling()
    br_a, crew = ctx["break"], ctx["crew"]
    valve = ctx["valves"][0]
    assert br_a["break_status"] == "REPAIRED"

    # Rework: fresh isolation moves REPAIRED -> ISOLATED.
    isolate_break(br_a["id"], [valve["id"]])
    assert get_break(br_a["id"])["break_status"] == "ISOLATED"

    wo2 = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br_a["id"],
                                      est_pipe_length_ft=4),
            DISPATCHER,
        ),
        201,
    )
    validate_success(
        _api.dispatch_work_order(wo2["id"], {"crew_id": crew["id"]}, DISPATCHER),
        200,
    )
    validate_success(
        _api.arrive_work_order(wo2["id"], make_crew_lead_headers(crew["id"])), 200
    )
    assert get_break(br_a["id"])["break_status"] == "IN_REPAIR", (
        "the rework loop must carry the break REPAIRED -> ISOLATED -> IN_REPAIR"
    )


# ---------------------------------------------------------------------------
# Corner: confirm_on_replaced_segment_rejected
# ---------------------------------------------------------------------------

def test_confirm_on_replaced_segment_rejected(api):
    """PRD §3.8: "Marking replaced stamps `replaced_at` with the clock now and
    freezes both repeat-break counts at their last computed values; from that
    moment, any attempt to confirm a new break against the segment is rejected
    with `ERR_SEGMENT_REPLACED`."
    PRD §3.2: "Confirmation against a segment whose `condition_status` is
    `REPLACED` is rejected with `ERR_SEGMENT_REPLACED`, because a replaced main
    cannot legitimately break again."

    Design: Corner/validations/confirm_on_replaced_segment_rejected
    """
    seg = create_segment(segment_ref="MAIN-12-BIRCH", material="CAST_IRON",
                         diameter_inches=12, install_year=1958)
    valve = create_valve(seg["id"], "V-BIRCH-1", coverage_zone="Z1",
                         customers_served=100)
    crew = create_crew(crew_name="Crew Birch", crew_size=3,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    # Three repaired breaks within the window -> CANDIDATE at the ops run.
    for when, loc, src, sev in (
        (None, "10 Birch Ln", "CUSTOMER_CALL", "MEDIUM"),
        ("2026-08-01T06:00:00Z", "22 Birch Ln", "CUSTOMER_CALL", "MEDIUM"),
        ("2026-08-01T12:00:00Z", "30 Birch Ln", "SENSOR_SCADA", "HIGH"),
    ):
        if when:
            set_clock(when)
        b = create_break(location_description=loc, source=src)
        b = confirm_break(b["id"], seg["id"], break_type="CIRCUMFERENTIAL",
                          severity=sev)
        _repair_break_full_cycle(b["id"], [valve["id"]], crew["id"])
    run_ops()
    assert get_segment(seg["id"])["condition_status"] == "CANDIDATE"

    programmed = validate_success(
        _api.program_replacement(seg["id"], ENGINEER), 200
    )
    assert programmed["condition_status"] == "PROGRAMMED"
    replaced = validate_success(_api.mark_replaced(seg["id"], ENGINEER), 200)
    assert replaced["condition_status"] == "REPLACED"
    assert replaced["replaced_at"] is not None

    b4 = create_break(location_description="44 Birch Ln", source="CUSTOMER_CALL")
    resp = _api.confirm_break_report(
        b4["id"],
        confirm_break_report_payload(
            pipe_segment_id=seg["id"], break_type="SPLIT", severity="MEDIUM"
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_SEGMENT_REPLACED)
    assert get_break(b4["id"])["break_status"] == "REPORTED", (
        "the rejected confirm must leave the report REPORTED"
    )
