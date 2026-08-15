"""Repair-completion cascade (work order -> break -> isolation/valves ->
restoration job) and the restoration deadline / permit expiry ops sweeps."""
from test_helpers import (
    TEST_USERS,
    complete_work_order,
    create_approved_permit,
    create_crew,
    create_isolation_plan,
    find_restoration_job_for_work_order,
    get_break,
    get_restoration_job,
    list_break_advisories,
    list_break_isolations,
    list_segment_valves,
    make_crew_lead_headers,
    run_ops,
    set_clock,
    setup_confirmed_break,
    setup_on_site_work_order,
    setup_repaired_break,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import schedule_restoration_job_payload

DISPATCHER = TEST_USERS["dispatcher_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _cedar_on_site_with_auto_advisory():
    """Diameter-8 segment with Z1/300 + Z2/250 (extent 550 -> auto advisory);
    break confirmed, isolation executed, crew dispatched and on site."""
    return setup_on_site_work_order(
        segment_ref="MAIN-8-CEDAR", diameter_inches=8, install_year=1970,
        valve_specs=[
            {"valve_code": "V-CED-1", "coverage_zone": "Z1", "customers_served": 300},
            {"valve_code": "V-CED-2", "coverage_zone": "Z2", "customers_served": 250},
        ],
        break_type="CIRCUMFERENTIAL", severity="HIGH",
        location_description="5 Cedar Rd", source="SENSOR_SCADA",
        crew_name="Crew Cedar", crew_size=4, crew_rate=6000,
        est_pipe_length_ft=4,
    )


# ---------------------------------------------------------------------------
# Difficulty: repair_complete_cascade_depth3 (2 tests)
# ---------------------------------------------------------------------------

def test_repair_complete_moves_break_and_rolls_up_cost(api):
    """PRD §3.4: "The crew returns to `AVAILABLE` and its
    `completed_job_count` increases by 1, the break's `total_repair_cost_cents`
    grows by the actual cost, and the cascade runs in order: the break moves
    `IN_REPAIR` → `REPAIRED` with `repaired_at` stamped at the clock now; the
    break's `EXECUTED` isolation is restored (valves reopen,
    `customers_out_of_service` returns to 0); the advisory sampling window
    opens (§3.5); and a restoration job is auto-created in `PENDING` status
    against the completed work order (§3.6)."

    Design: Difficulty/transitive_cascade/repair_complete_cascade_depth3
    """
    ctx = _cedar_on_site_with_auto_advisory()
    wo, crew, br = ctx["work_order"], ctx["crew"], ctx["break"]
    done = complete_work_order(wo["id"], crew["id"], actual_pipe_length_ft=4,
                               labor_hours=1, materials_used=[])
    assert done["work_status"] == "REPAIR_COMPLETE"

    br_after = get_break(br["id"])
    assert br_after["break_status"] == "REPAIRED", (
        f"break must move IN_REPAIR -> REPAIRED, got {br_after['break_status']!r}"
    )
    assert br_after["repaired_at"] is not None
    assert br_after["customers_out_of_service"] == 0
    # actual = round(1*6000) + no materials = 6000
    assert br_after["total_repair_cost_cents"] == 6000, (
        f"repair rollup must grow by the actual cost 6000, got "
        f"{br_after['total_repair_cost_cents']}"
    )


def test_repair_complete_restores_isolation_and_spawns_restoration(api):
    """PRD §3.3: "When a repair completes (§3.4), the executed plan for the
    break is restored: `isolation_status` moves from `EXECUTED` to `RESTORED`,
    every listed valve returns to `OPEN`, `restored_at` is stamped, and the
    break's `customers_out_of_service` returns to 0."
    PRD §3.6: "When a repair completes, a restoration job is auto-created
    against the finished work order with `restoration_status` `PENDING`, linked
    by its `work_order_id`, with `scheduled_start`, `scheduled_end`,
    `traffic_permit_id`, `patch_cost_cents`, and `completed_at` all null."

    Design: Difficulty/transitive_cascade/repair_complete_cascade_depth3
    """
    ctx = _cedar_on_site_with_auto_advisory()
    wo, crew, br, seg = (ctx["work_order"], ctx["crew"], ctx["break"],
                         ctx["segment"])
    complete_work_order(wo["id"], crew["id"], actual_pipe_length_ft=4,
                        labor_hours=1, materials_used=[])

    plans = list_break_isolations(br["id"])
    assert len(plans) == 1
    assert plans[0]["isolation_status"] == "RESTORED"
    assert plans[0]["restored_at"] is not None

    valves = {v["valve_code"]: v for v in list_segment_valves(seg["id"])}
    assert valves["V-CED-1"]["valve_status"] == "OPEN"
    assert valves["V-CED-2"]["valve_status"] == "OPEN"

    rj = find_restoration_job_for_work_order(wo["id"])
    assert rj["restoration_status"] == "PENDING"
    assert rj["work_order_id"] == wo["id"]
    assert rj["scheduled_start"] is None and rj["scheduled_end"] is None
    assert rj["traffic_permit_id"] is None and rj["patch_cost_cents"] is None
    assert rj["completed_at"] is None

    advisories = list_break_advisories(br["id"])
    assert len(advisories) == 1
    assert advisories[0]["advisory_status"] == "ISSUED", (
        "repair completion must not auto-lift the advisory"
    )


# ---------------------------------------------------------------------------
# Difficulty: execute_restore_conserves_open_valves (2 tests)
# ---------------------------------------------------------------------------

def _cedar_confirmed_with_draft_order():
    """Segment with v1/Z1/300 + v2/Z2/250, break confirmed, isolation plan
    created (not executed), crew + DRAFT work order."""
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-CEDAR", diameter_inches=8, install_year=1970,
        valve_specs=[
            {"valve_code": "V-CED-1", "coverage_zone": "Z1", "customers_served": 300},
            {"valve_code": "V-CED-2", "coverage_zone": "Z2", "customers_served": 250},
        ],
        break_type="CIRCUMFERENTIAL", severity="HIGH",
        location_description="5 Cedar Rd", source="SENSOR_SCADA",
    )
    crew = create_crew(crew_name="Crew Cedar", crew_size=4,
                       equipment_class="LIGHT", hourly_rate_cents=6000)
    plan = create_isolation_plan(
        ctx["break"]["id"], [v["id"] for v in ctx["valves"]],
        ctx["break"]["version"],
    )
    wo = validate_success(
        _api.create_work_order(
            {"break_report_id": ctx["break"]["id"], "est_pipe_length_ft": 4},
            DISPATCHER,
        ),
        201,
    )
    ctx.update({"crew": crew, "plan": plan, "work_order": wo})
    return ctx


def test_execute_closes_valves_and_sets_outage(api):
    """PRD §3.3: "On execution all listed valves flip to `CLOSED`, `executed_at`
    is stamped, and the outage extent is computed by zone deduplication: the
    closed valves are grouped by `coverage_zone`, and `outage_extent_customers`
    is the sum over distinct zones of the largest `customers_served` among the
    closed valves in that zone — the largest valve in a zone is taken to cover
    the others' customers."
    PRD §3.3: "The computed extent is copied onto the break's
    `customers_out_of_service`, and the break itself moves from `CONFIRMED` (or
    `REPAIRED`, in the rework loop) to `ISOLATED`."

    Design: Difficulty/compensating_invariant/execute_restore_conserves_open_valves
    """
    ctx = _cedar_confirmed_with_draft_order()
    seg = ctx["segment"]
    before = list_segment_valves(seg["id"])
    assert all(v["valve_status"] == "OPEN" for v in before), (
        "both valves are OPEN before execution"
    )

    iso = validate_success(
        _api.execute_isolation_event(ctx["plan"]["id"], DISPATCHER), 200
    )
    assert iso["outage_extent_customers"] == 550
    br_mid = get_break(ctx["break"]["id"])
    assert br_mid["customers_out_of_service"] == 550
    assert br_mid["break_status"] == "ISOLATED"
    during = {v["valve_code"]: v for v in list_segment_valves(seg["id"])}
    assert during["V-CED-1"]["valve_status"] == "CLOSED"
    assert during["V-CED-2"]["valve_status"] == "CLOSED"


def test_restore_returns_open_valve_count_and_zeroes_outage(api):
    """PRD §3.3: "When a repair completes (§3.4), the executed plan for the
    break is restored: `isolation_status` moves from `EXECUTED` to `RESTORED`,
    every listed valve returns to `OPEN`, `restored_at` is stamped, and the
    break's `customers_out_of_service` returns to 0."

    Design: Difficulty/compensating_invariant/execute_restore_conserves_open_valves
    """
    ctx = _cedar_confirmed_with_draft_order()
    seg, br = ctx["segment"], ctx["break"]
    validate_success(_api.execute_isolation_event(ctx["plan"]["id"], DISPATCHER), 200)
    # Drive the work order to completion (the compensating action).
    validate_success(
        _api.dispatch_work_order(
            ctx["work_order"]["id"], {"crew_id": ctx["crew"]["id"]}, DISPATCHER
        ),
        200,
    )
    validate_success(
        _api.arrive_work_order(
            ctx["work_order"]["id"], make_crew_lead_headers(ctx["crew"]["id"])
        ),
        200,
    )
    complete_work_order(ctx["work_order"]["id"], ctx["crew"]["id"],
                        actual_pipe_length_ft=4, labor_hours=1, materials_used=[])

    after = {v["valve_code"]: v for v in list_segment_valves(seg["id"])}
    open_count = sum(1 for v in after.values() if v["valve_status"] == "OPEN")
    assert open_count == 2, (
        f"open-valve count must be restored to its pre-execute value 2, got {open_count}"
    )
    br_end = get_break(br["id"])
    assert br_end["customers_out_of_service"] == 0
    plans = list_break_isolations(br["id"])
    assert plans[0]["isolation_status"] == "RESTORED"


# ---------------------------------------------------------------------------
# Corner: permit_auto_expires_at_ops_run
# ---------------------------------------------------------------------------

def test_permit_auto_expires_at_ops_run(api):
    """PRD §3.8: "First, every traffic permit in `APPLIED` or `APPROVED` status
    whose `valid_to` is at or before the clock now moves to `EXPIRED`
    (terminal)."

    Design: Corner/state_machines/permit_auto_expires_at_ops_run
    """
    ctx = setup_confirmed_break(break_type="CIRCUMFERENTIAL", severity="LOW",
                                material="PVC", install_year=1999)
    perm = create_approved_permit(
        ctx["break"]["id"], street_block="OAK-100-BLK",
        valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-12T00:00:00Z",
    )
    assert perm["permit_status"] == "APPROVED"
    set_clock("2026-08-12T00:00:00Z")  # exactly valid_to
    run_ops()
    permits, _meta = validate_paginated(
        _api.list_break_traffic_permits(ctx["break"]["id"], DISPATCHER)
    )
    listed = {p["id"]: p for p in permits}
    assert listed[perm["id"]]["permit_status"] == "EXPIRED", (
        "permit whose valid_to equals the clock now must flip to EXPIRED"
    )


# ---------------------------------------------------------------------------
# Corner: restoration_flagged_overdue_and_reschedulable
# ---------------------------------------------------------------------------

def test_restoration_flagged_overdue_and_reschedulable(api):
    """PRD §3.6: "The operations checkpoint (§3.8) flags any job still
    `PENDING` or `SCHEDULED` whose parent break's `repaired_at` is more than 14
    days in the past as `OVERDUE`; an overdue job can still be scheduled or
    completed normally."
    PRD §3.6: "A `Dispatcher` schedules a `PENDING` or `OVERDUE` job by
    supplying `scheduled_start`, `scheduled_end`, and a `traffic_permit_id`."

    Design: Corner/state_machines/restoration_flagged_overdue_and_reschedulable
    """
    ctx = setup_repaired_break(
        segment_ref="MAIN-8-ELM", material="CAST_IRON", diameter_inches=8,
        install_year=1962, break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="100 Elm St",
        crew_name="Crew Beta", crew_rate=6000,
    )
    rj = ctx["restoration_job"]
    # Repaired at 2026-08-01T00:00:00Z; +14 days is 2026-08-15; now is past it.
    set_clock("2026-08-16T00:00:00Z")
    run_ops()
    overdue = get_restoration_job(rj["id"])
    assert overdue["restoration_status"] == "OVERDUE", (
        f"job past repaired_at + 14d must be OVERDUE, got {overdue['restoration_status']!r}"
    )

    perm = create_approved_permit(
        ctx["break"]["id"], street_block="ELM-100-BLK",
        valid_from="2026-08-16T00:00:00Z", valid_to="2026-08-20T00:00:00Z",
        control_plan="FLAGGING",
    )
    scheduled = validate_success(
        _api.schedule_restoration_job(
            rj["id"],
            schedule_restoration_job_payload(
                scheduled_start="2026-08-17T08:00:00Z",
                scheduled_end="2026-08-17T16:00:00Z",
                traffic_permit_id=perm["id"],
            ),
            DISPATCHER,
        ),
        200,
    )
    assert scheduled["restoration_status"] == "SCHEDULED", (
        "an OVERDUE job must still be schedulable"
    )
