"""The two conserved quantities and the compensating actions that must return them to
exactly their prior values: the served-customer population across arm-then-cancel, and the
hardened-mileage ledger across record-completion-then-withdraw."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_1dp,
    assert_4dp,
    assert_circuit_state,
    assert_hardening_ledger,
    assert_integer,
    assert_population_counters,
    assert_scope_counts,
    assert_scope_row,
    energized_customer_total,
)
from test_helpers.constants import EVENT_CANCELLED_JUSTIFICATION
from test_helpers.fixtures import (
    arm_event,
    build_advance_dispatched_event,
    build_approved_project,
    cancel_event,
    list_circuits,
    read_circuit,
    read_event,
    read_project,
    read_scope_rows,
    record_completion,
    register_circuit,
    review_project,
)
from test_helpers.test_users import PLANNER_HEADERS
from test_helpers.types import ProgramType, ReviewDecision

DISSIPATED = "offshore wind event dissipated"
COMPLETION_DATE = "2026-07-20T00:00:00Z"


def _armed_chain():
    """The chain with its advance warning delivered and the shutoff staged, so all three
    circuits sit at DE_ENERGIZATION_PENDING."""
    ctx = build_advance_dispatched_event()
    ctx["event"] = arm_event(ctx["event_id"])
    return ctx


def _executed_covered_conductor_project():
    """ALPHA with 4.0 of its 7.0 overhead miles covered by a completed package."""
    alpha = register_circuit(circuit_code="ALPHA")
    project = build_approved_project(
        alpha["id"],
        project_code="MP-CC-1",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )
    project = record_completion(
        project["id"], 4.0, COMPLETION_DATE, read_circuit(alpha["id"])["version"]
    )
    return alpha, project


# --------------------------------------------------------------------------
# The served-customer population across arm-then-cancel
# --------------------------------------------------------------------------
def test_arming_removes_the_whole_chain_from_the_served_population():
    """Five accounts are served before the order is staged and none afterwards, with all
    five accounted for on the three pending circuits.

    "The **energized-customer total** is the sum of `customer_count` over every circuit
    whose `energization_state` is `ENERGIZED`."

    "Arming an event removes the confirmed circuits from that sum; cancelling the event
    from an armed state returns them."

    Design: Difficulty/compensating_invariant/arm_then_cancel_conserves_energized_customer_total
    """
    ctx = build_advance_dispatched_event()

    before, before_meta = list_circuits(energization_state="ENERGIZED")
    assert_integer(before_meta["total_count"], 3)
    assert energized_customer_total(before) == 5

    arm_event(ctx["event_id"])

    still_served, served_meta = list_circuits(energization_state="ENERGIZED")
    assert_integer(served_meta["total_count"], 0)
    assert energized_customer_total(still_served) == 0
    staged, staged_meta = list_circuits(energization_state="DE_ENERGIZATION_PENDING")
    assert_integer(staged_meta["total_count"], 3)
    assert sum(row["customer_count"] for row in staged) == 5


def test_cancelling_from_armed_returns_the_population_without_drift():
    """The compensation puts exactly five accounts back into service, circuit by circuit,
    and takes ALPHA's posture back out of LOCKED.

    "After such a pair, the energized-customer total must equal its value before the pair,
    to the integer."

    Design: Difficulty/compensating_invariant/arm_then_cancel_conserves_energized_customer_total
    """
    ctx = _armed_chain()

    cancel_event(ctx["event_id"], DISSIPATED)

    after, after_meta = list_circuits(energization_state="ENERGIZED")
    assert_integer(after_meta["total_count"], 3)
    assert energized_customer_total(after) == 5
    assert_population_counters(
        read_circuit(ctx["alpha"]["id"]),
        customer_count=3,
        medical_baseline_count=1,
        critical_facility_count=1,
    )
    assert_population_counters(
        read_circuit(ctx["bravo"]["id"]),
        customer_count=1,
        medical_baseline_count=0,
        critical_facility_count=0,
    )
    assert_population_counters(
        read_circuit(ctx["charlie"]["id"]),
        customer_count=1,
        medical_baseline_count=0,
        critical_facility_count=0,
    )
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="ENERGIZED",
        risk_posture="EXTREME",
    )


def test_the_compensation_excludes_the_scope_rows_rather_than_deleting_them():
    """All three rows survive the cancellation carrying the reserved justification, so the
    record of what was nearly de-energized is still auditable.

    "Cancelling from `SCOPED` additionally sets every `CONFIRMED` scope row of the event to
    `EXCLUDED` with `exclusion_justification` set to the literal string `EVENT_CANCELLED`."

    "Cancelling from `ARMED` does all of that **and** performs the compensation proper:
    every circuit sitting at `DE_ENERGIZATION_PENDING` for this event reverts to
    `ENERGIZED` with its `risk_posture` recomputed out of `LOCKED`, which must restore the
    energized-customer total of §2.11 to exactly its pre-arm value; every resource center
    already `ACTIVATED` for the event is demobilized; and any patrol assignment on the
    event still at `SCHEDULED` or `IN_PROGRESS` moves to `ABORTED`."

    Design: Difficulty/compensating_invariant/arm_then_cancel_conserves_energized_customer_total
    """
    ctx = _armed_chain()

    cancelled = cancel_event(ctx["event_id"], DISSIPATED)

    assert cancelled["scope_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == DISSIPATED
    assert cancelled["actual_de_energized_at"] is None
    assert_scope_counts(read_event(ctx["event_id"]), confirmed=0, excluded=3)

    rows = read_scope_rows(ctx["event_id"])
    assert len(rows) == 3, "the cancellation must not delete the scope rows"
    for key, count in (("alpha", 3), ("bravo", 1), ("charlie", 1)):
        assert_scope_row(
            rows,
            ctx[key]["id"],
            scope_status="EXCLUDED",
            customer_count_snapshot=count,
            exclusion_justification=EVENT_CANCELLED_JUSTIFICATION,
        )


# --------------------------------------------------------------------------
# The hardened-mileage ledger across record-completion-then-withdraw
# --------------------------------------------------------------------------
def test_recorded_covered_conductor_miles_land_in_the_credited_ledger():
    """Four covered miles on seven overhead miles earn 0.3429 of credited hardening and
    close the package out.

    "Covered conductor earns partial credit and undergrounding earns full credit: the
    numerator is `covered_conductor_miles` multiplied by 0.6 plus `underground_miles`
    multiplied by 1.0, and the denominator is the circuit's immutable `overhead_miles`."

    "The first record advances the project from `APPROVED` to `IN_EXECUTION`; further
    records that leave the cumulative total strictly below `planned_miles` keep it in
    `IN_EXECUTION`; and the record whose cumulative total lands exactly on `planned_miles`
    advances it to `COMPLETED`."

    Design: Difficulty/compensating_invariant/record_completion_then_withdraw_conserves_hardened_mileage_ledger
    """
    alpha, project = _executed_covered_conductor_project()

    assert project["status"] == "COMPLETED"
    assert_1dp(project["completed_miles"], 4.0)
    assert_hardening_ledger(
        read_circuit(alpha["id"]),
        covered_conductor_miles=4.0,
        underground_miles=0.0,
        hardened_fraction=0.3429,
    )


def test_withdrawal_reverses_exactly_those_miles():
    """The withdrawal subtracts the executed mileage and zeroes the project's own tally, so
    the ledger and the credited fraction are back where they started.

    "Withdrawal subtracts the project's `completed_miles` from the circuit's
    `covered_conductor_miles` when the `program_type` is `COVERED_CONDUCTOR` or from
    `underground_miles` when it is `UNDERGROUNDING`, then sets the project's
    `completed_miles` back to zero, then recomputes the circuit's `hardened_fraction` and
    `risk_posture`, and increments both the circuit's `version` and the project's `version`
    by one each."

    Design: Difficulty/compensating_invariant/record_completion_then_withdraw_conserves_hardened_mileage_ledger
    """
    alpha, project = _executed_covered_conductor_project()

    withdrawn = review_project(
        project["id"], ReviewDecision.WITHDRAW.value, "programme descoped"
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert_1dp(withdrawn["completed_miles"], 0.0)
    restored = read_circuit(alpha["id"])
    assert_hardening_ledger(
        restored,
        covered_conductor_miles=0.0,
        underground_miles=0.0,
        hardened_fraction=0.0000,
    )
    assert_4dp(restored["hardened_fraction"], 0.0000)
    assert_circuit_state(
        restored, energization_state="ENERGIZED", risk_posture="NORMAL"
    )


def test_the_reversal_touches_executed_mileage_and_not_the_plan_of_record():
    """The package keeps its four planned miles and its five-million-cent budget while
    contributing nothing at all to the circuit ledger.

    "The two mileage accumulators themselves count only work that has actually begun: a
    project contributes its `completed_miles` only while its `status` is `IN_EXECUTION`,
    `SUSPENDED`, or `COMPLETED`."

    "The result must restore the per-circuit hardened-mileage ledger and
    `hardened_fraction` to precisely their pre-completion values, as §2.11 requires."

    Design: Difficulty/compensating_invariant/record_completion_then_withdraw_conserves_hardened_mileage_ledger
    """
    alpha, project = _executed_covered_conductor_project()

    review_project(project["id"], ReviewDecision.WITHDRAW.value, "programme descoped")

    plan_of_record = read_project(project["id"])
    assert_1dp(plan_of_record["planned_miles"], 4.0)
    assert_integer(plan_of_record["budget_cents"], 5000000)

    rows, meta = validate_paginated(
        api_client.list_circuit_mitigation_projects(alpha["id"], PLANNER_HEADERS)
    )
    assert_integer(meta["total_count"], 1)
    assert rows[0]["status"] == "WITHDRAWN"
    assert_1dp(rows[0]["completed_miles"], 0.0)
    ledger_bearing = sum(
        row["completed_miles"]
        for row in rows
        if row["status"] in ("IN_EXECUTION", "SUSPENDED", "COMPLETED")
    )
    assert ledger_bearing == 0.0
    assert_1dp(read_circuit(alpha["id"])["covered_conductor_miles"], 0.0)
