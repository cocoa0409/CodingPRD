"""The two multi-hop cascades: executing a shutoff order walks event, circuits and work
packages, and re-energizing the last circuit walks back out again through the event and
its resource centers."""

from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_4dp,
    assert_center_state,
    assert_circuit_state,
    assert_event_dimensions,
    assert_hardening_ledger,
    assert_instant,
    assert_integer,
    assert_net_benefit,
    assert_scope_row,
)
from test_helpers.fixtures import (
    DE_ENERGIZED_AT,
    RESTORE_ALPHA_AT,
    RESTORE_BRAVO_AT,
    RESTORE_CHARLIE_AT,
    activate_centers,
    book_project,
    build_active_event,
    build_advance_dispatched_event,
    build_armed_event,
    build_feeder_chain,
    build_imminent_dispatched_event,
    build_patrolled_event,
    build_scoped_event,
    declare_all_clear,
    move_clock,
    re_energize,
    read_center,
    read_circuit,
    read_event,
    read_patrol,
    read_project,
    read_scope_rows,
    register_center,
    review_project,
    record_completion,
    submit_project,
)
from test_helpers.types import ProgramType, ReviewDecision

FAST_TRIP_COMPLETION_DATE = "2026-07-15T00:00:00Z"
EVENT_ALL_CLEAR_AT = "2026-08-16T18:00:00Z"


def _chain_with_fast_trip_work_in_execution():
    """The feeder chain plus one FAST_TRIP_SETTING package on BRAVO that has already
    recorded a first mile, so it is IN_EXECUTION when the shutoff lands."""
    ctx = build_feeder_chain()
    project = book_project(
        ctx["bravo"]["id"],
        project_code="MP-FT-1",
        program_type=ProgramType.FAST_TRIP_SETTING.value,
        planned_miles=3.0,
        unit_cost_per_mile_cents=180000,
    )
    submit_project(project["id"])
    review_project(project["id"], ReviewDecision.APPROVE.value, "settings package accepted")
    bravo = read_circuit(ctx["bravo"]["id"])
    ctx["project"] = record_completion(
        project["id"], 1.0, FAST_TRIP_COMPLETION_DATE, bravo["version"]
    )
    assert ctx["project"]["status"] == "IN_EXECUTION"
    return ctx


def _executed_shutoff():
    """The chain driven all the way to ACTIVE with its work package in execution."""
    ctx = _chain_with_fast_trip_work_in_execution()
    ctx = build_scoped_event(ctx)
    ctx = build_advance_dispatched_event(ctx)
    ctx = build_armed_event(ctx)
    ctx = build_imminent_dispatched_event(ctx)
    return build_active_event(ctx)


def _restored_shutoff():
    """The executed shutoff with a resource center opened, the weather declared over,
    every circuit patrolled, and all three circuits returned to service."""
    ctx = _executed_shutoff()
    ctx["center"] = register_center(
        resource_center_code="CRC-N1",
        district_code="D-NORTH",
        site_capacity=150,
        accessibility_certified=True,
    )
    activate_centers(ctx["event_id"])
    declare_all_clear(ctx["event_id"])
    ctx = build_patrolled_event(ctx)
    move_clock(RESTORE_ALPHA_AT)
    re_energize(ctx["alpha"]["id"])
    move_clock(RESTORE_BRAVO_AT)
    re_energize(ctx["bravo"]["id"])
    move_clock(RESTORE_CHARLIE_AT)
    re_energize(ctx["charlie"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Hop one and hop two: the event and its circuits
# --------------------------------------------------------------------------
def test_executing_the_order_de_energizes_every_confirmed_circuit():
    """The order stamps the event at 19:00Z and takes all three staged circuits from
    DE_ENERGIZATION_PENDING to DE_ENERGIZED without unlocking any of them.

    "Every `CONFIRMED`-scoped circuit moves from `DE_ENERGIZATION_PENDING` to
    `DE_ENERGIZED`, keeping its `risk_posture` at `LOCKED`."

    Design: Difficulty/transitive_cascade/deenergize_locks_posture_and_suspends_mitigation_execution
    """
    ctx = _executed_shutoff()

    event = read_event(ctx["event_id"])
    assert_event_dimensions(
        event, scope_status="ACTIVE", notification_status="IMMINENT_SENT"
    )
    assert_instant(event["actual_de_energized_at"], DE_ENERGIZED_AT)

    for key in ("alpha", "bravo", "charlie"):
        assert_circuit_state(
            read_circuit(ctx[key]["id"]),
            energization_state="DE_ENERGIZED",
            risk_posture="LOCKED",
        )


# --------------------------------------------------------------------------
# Hop three: the in-flight work packages
# --------------------------------------------------------------------------
def test_the_third_hop_suspends_the_work_in_execution_on_those_circuits():
    """BRAVO's package is suspended by the shutoff alone, with the mile it had already
    recorded left untouched.

    "And because each posture is `LOCKED`, every mitigation project on those circuits
    whose `status` is `IN_EXECUTION` moves to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/deenergize_locks_posture_and_suspends_mitigation_execution
    """
    ctx = _executed_shutoff()

    suspended = read_project(ctx["project"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert_1dp(suspended["completed_miles"], 1.0)
    assert_integer(suspended["budget_cents"], 540000)
    assert_2dp(suspended["risk_reduction_score"], 1.62)


def test_suspended_fast_trip_mileage_never_reaches_the_hardening_ledger():
    """One recorded fast-trip mile leaves BRAVO's ledger and hardened fraction at zero
    both before and after the shutoff suspends the package.

    "Neither `FAST_TRIP_SETTING` nor `INSPECTION_CYCLE` ever contributes mileage to the
    hardening ledger."

    Design: Difficulty/transitive_cascade/deenergize_locks_posture_and_suspends_mitigation_execution
    """
    ctx = _chain_with_fast_trip_work_in_execution()

    before = read_circuit(ctx["bravo"]["id"])
    assert_hardening_ledger(
        before, covered_conductor_miles=0.0, underground_miles=0.0, hardened_fraction=0.0000
    )

    ctx = build_scoped_event(ctx)
    ctx = build_advance_dispatched_event(ctx)
    ctx = build_armed_event(ctx)
    ctx = build_imminent_dispatched_event(ctx)
    build_active_event(ctx)

    after = read_circuit(ctx["bravo"]["id"])
    assert read_project(ctx["project"]["id"])["status"] == "SUSPENDED"
    assert_hardening_ledger(
        after, covered_conductor_miles=0.0, underground_miles=0.0, hardened_fraction=0.0000
    )
    assert_4dp(after["hardened_fraction"], 0.0000)


# --------------------------------------------------------------------------
# The cascade back out: resume, stamp, rescore, demobilize
# --------------------------------------------------------------------------
def test_re_energizing_resumes_the_suspended_work_and_stamps_each_scope_row():
    """Every circuit comes back with its posture read from the forecast again, BRAVO's
    package returns to execution, and each scope row carries the instant its own circuit
    was restored.

    "Because the posture left `LOCKED`, every mitigation project on the circuit whose
    `status` is `SUSPENDED` returns to `IN_EXECUTION`."

    Design: Difficulty/transitive_cascade/reenergize_resumes_mitigation_then_stamps_restore_then_demobilizes_centers
    """
    ctx = _restored_shutoff()

    assert read_project(ctx["project"]["id"])["status"] == "IN_EXECUTION"
    assert_circuit_state(
        read_circuit(ctx["charlie"]["id"]),
        energization_state="ENERGIZED",
        risk_posture="NORMAL",
    )
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="ENERGIZED",
        risk_posture="EXTREME",
    )

    rows = read_scope_rows(ctx["event_id"])
    assert_scope_row(rows, ctx["alpha"]["id"], restored_at=RESTORE_ALPHA_AT)
    assert_scope_row(rows, ctx["bravo"]["id"], restored_at=RESTORE_BRAVO_AT)
    assert_scope_row(rows, ctx["charlie"]["id"], restored_at=RESTORE_CHARLIE_AT)
    assert read_patrol(ctx["patrol_charlie"]["id"])["status"] == "COMPLETED"


def test_the_last_restoration_rescores_the_event_and_demobilizes_its_centers():
    """Stamping the realised restoration re-runs the accounting over 34 hours and stands
    the shelter down, so the credit it was earning disappears from the ratio.

    "Because `actual_restored_at` has become non-null, every resource center whose
    `psps_event_id` is that event and whose `status` is `ACTIVATED` moves to
    `DEMOBILIZED` with `demobilized_at` stamped."

    Design: Difficulty/transitive_cascade/reenergize_resumes_mitigation_then_stamps_restore_then_demobilizes_centers
    """
    ctx = _restored_shutoff()

    event = read_event(ctx["event_id"])
    assert_instant(event["actual_restored_at"], RESTORE_CHARLIE_AT)
    assert_net_benefit(
        event,
        variant="POST_EVENT",
        duration_hours=34,
        customer_impact_score=64.60,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=64.60,
        ignition_risk_avoided_score=15.48,
        net_benefit_ratio=0.2396,
    )
    assert_integer(event["crc_capacity_served"], 0)

    center = read_center(ctx["center"]["id"])
    assert_center_state(
        center,
        "DEMOBILIZED",
        psps_event_id=ctx["event_id"],
        last_served_all_clear_at=EVENT_ALL_CLEAR_AT,
    )
    assert_instant(center["demobilized_at"], RESTORE_CHARLIE_AT)
