"""Machines that are not a straight line: parallel dimensions and a counted cycle.

A block's mechanical and electrical dimensions advance from unrelated operations
and meet only at the derived `mc_ready` flag, so the electrical side can walk
out to rework and back while the mechanical side never moves. A punch-list item
travels its submit-and-reject loop as many times as the owner insists, counting
the trips, before either terminal hop finally lands.
"""

from test_helpers.assertions import (
    assert_block_counters,
    assert_project_state,
    assert_string_test_failure,
    assert_version_is,
)
from test_helpers.fixtures import (
    create_project,
    create_punch_item,
    decide_closure,
    read_block,
    read_circuit,
    read_project,
    read_punch_item,
    ready_project,
    record_string_test,
    set_clock,
    submit_closure,
)
from test_helpers.test_users import INSTALLATION_FOREMAN, OWNER_ENGINEER

# The retest that fails all three checks at once. Insulation is the pinned first
# check, so it names the reason even though the voltage deviation of 111.32 V
# and the reversed polarity are equally present.
TRIPLE_FAILURE = {
    "insulation_resistance_mohm": 12.5,
    "measured_voc_v": 600.00,
    "ambient_c": 40,
    "polarity_ok": False,
}
CLEAN_TEST = {
    "insulation_resistance_mohm": 55.0,
    "measured_voc_v": 705.00,
    "ambient_c": 40,
    "polarity_ok": True,
}


def _tested_plant(api):
    """A one-block plant sitting at MECH_COMPLETE / TESTED with the project READY."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rows = ready_project(api, name="Sage Draw")
    assert_project_state(
        read_project(api, rows["project"]["id"]),
        mc_readiness="READY",
        blocks_mc_ready_count=1,
    )
    return rows


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/block_parallel_dimensions_move_independently_through_rework
# ---------------------------------------------------------------------------
def test_a_failing_retest_names_the_first_check_in_the_pinned_order(api):
    """Wet insulation reports INSULATION even alongside deviation and polarity faults.

    PRD 3.5: "The order matters because a string can violate two or three
    conditions at once; a circuit with wet insulation *and* reversed polarity
    reports `INSULATION`, never `POLARITY`."

    Design: Difficulty/non_linear_state_machine/block_parallel_dimensions_move_independently_through_rework
    """
    rows = _tested_plant(api)

    failed = record_string_test(api, rows["circuit"]["id"], **TRIPLE_FAILURE)

    assert_string_test_failure(failed, "INSULATION")


def test_the_electrical_dimension_goes_to_rework_while_mechanical_holds_still(api):
    """The block keeps MECH_COMPLETE while its electrical side falls to REWORK.

    PRD 3.4: "The two advance from entirely different operations and never
    constrain each other's values: a block may sit at `MECH_COMPLETE` while its
    electrical dimension is in `REWORK`, and it may sit at `TESTED` electrically
    while its mechanical dimension is on `HOLD`."

    Design: Difficulty/non_linear_state_machine/block_parallel_dimensions_move_independently_through_rework
    """
    rows = _tested_plant(api)

    record_string_test(api, rows["circuit"]["id"], **TRIPLE_FAILURE)

    mid = read_block(api, rows["block"]["id"])
    assert_block_counters(
        mid,
        mechanical_status="MECH_COMPLETE",
        electrical_status="REWORK",
        mc_ready=False,
        circuits_failed_count=1,
    )


def test_a_clean_retest_walks_rework_back_to_tested_and_clears_the_reason(api):
    """The unbounded fail-and-retest cycle returns the circuit to TESTED.

    PRD 3.5: "The same landing applies to a clean retest out of rework: a
    `REWORK` block whose `circuits_failed_count` returns to 0 while
    `circuits_tested_count` is at least `planned_string_count` advances `REWORK →
    TESTED`, with the identical `mc_ready` and project-readiness recomputation."

    Design: Difficulty/non_linear_state_machine/block_parallel_dimensions_move_independently_through_rework
    """
    rows = _tested_plant(api)
    record_string_test(api, rows["circuit"]["id"], **TRIPLE_FAILURE)

    passed = record_string_test(api, rows["circuit"]["id"], **CLEAN_TEST)

    assert passed["status"] == "TESTED"
    assert read_circuit(api, rows["circuit"]["id"])["test_failure_reason"] is None
    assert_block_counters(
        read_block(api, rows["block"]["id"]),
        mechanical_status="MECH_COMPLETE",
        electrical_status="TESTED",
        mc_ready=True,
        circuits_failed_count=0,
        circuits_tested_count=1,
    )


def test_readiness_collapses_and_recovers_without_a_mechanical_transition(api):
    """The joined flag flips false and true again on electrical movement alone.

    PRD 3.4: "They are joined at exactly one point — the derived boolean
    `mc_ready`, which is true if and only if `mechanical_status` is
    `MECH_COMPLETE` **and** `electrical_status` is `TESTED`, and false in every
    other combination."

    Design: Difficulty/non_linear_state_machine/block_parallel_dimensions_move_independently_through_rework
    """
    rows = _tested_plant(api)
    project_id = rows["project"]["id"]

    record_string_test(api, rows["circuit"]["id"], **TRIPLE_FAILURE)
    assert_project_state(
        read_project(api, project_id), mc_readiness="BLOCKED", blocks_mc_ready_count=0
    )

    record_string_test(api, rows["circuit"]["id"], **CLEAN_TEST)
    assert_project_state(
        read_project(api, project_id), mc_readiness="READY", blocks_mc_ready_count=1
    )
    assert read_block(api, rows["block"]["id"])["mechanical_status"] == "MECH_COMPLETE"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/punch_item_closure_cycle_repeats_before_terminal_close
# ---------------------------------------------------------------------------
def _critical_item(api):
    """A project carrying exactly one open critical defect."""
    project = create_project(api, name="Alkali Rim")
    item = create_punch_item(
        api,
        project["id"],
        title="Combiner box missing arc-flash label",
        category="ELECTRICAL",
        severity="CRITICAL",
        estimated_cost_cents=40000,
    )
    return project, item


def test_each_rejection_returns_the_item_to_open_and_counts_the_trip(api):
    """Two rejections send the item back to OPEN and leave rejection_count at 2.

    PRD 3.9: "This cycle — `OPEN → CLOSURE_SUBMITTED → OPEN` — is unbounded, and
    `rejection_count` is the running record of how many times the loop has been
    travelled."

    Design: Difficulty/non_linear_state_machine/punch_item_closure_cycle_repeats_before_terminal_close
    """
    _project, item = _critical_item(api)

    submit_closure(api, item["id"], closure_evidence_ref="PHOTO-1")
    first = decide_closure(api, item["id"], "REJECT", note="label illegible")
    assert first["status"] == "OPEN"
    assert first["rejection_count"] == 1

    submit_closure(api, item["id"], closure_evidence_ref="PHOTO-2")
    second = decide_closure(api, item["id"], "REJECT", note="wrong panel")
    assert second["status"] == "OPEN"
    assert second["rejection_count"] == 2


def test_the_terminal_approval_closes_the_item_without_touching_the_counter(api):
    """The third submission is approved, and the loop counter stays where it stopped.

    PRD 3.9: "`APPROVE` drives `CLOSURE_SUBMITTED → CLOSED` and `WAIVE` drives
    `CLOSURE_SUBMITTED → WAIVED`; both are terminal, and both recompute the
    project's `open_punch_item_count` and `open_critical_punch_count` with the
    project's `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/punch_item_closure_cycle_repeats_before_terminal_close
    """
    _project, item = _critical_item(api)

    for ref, decision in (("PHOTO-1", "REJECT"), ("PHOTO-2", "REJECT"), ("PHOTO-3", "APPROVE")):
        submit_closure(api, item["id"], closure_evidence_ref=ref)
        final = decide_closure(api, item["id"], decision, note="verified")

    assert final["status"] == "CLOSED"
    assert final["rejection_count"] == 2
    assert final["submitted_by_user_id"] == INSTALLATION_FOREMAN["X-User-ID"]
    assert final["decided_by_user_id"] == OWNER_ENGINEER["X-User-ID"]


def test_the_project_counters_stay_up_for_the_whole_loop_and_drop_only_at_the_end(api):
    """A submitted item is still open for milestone purposes until it is decided.

    PRD 3.9: "An item awaiting an owner decision is therefore still open for
    milestone purposes; submitting evidence does not relieve the gate."

    Design: Difficulty/non_linear_state_machine/punch_item_closure_cycle_repeats_before_terminal_close
    """
    project, item = _critical_item(api)
    project_id = project["id"]

    for ref in ("PHOTO-1", "PHOTO-2"):
        submitted = submit_closure(api, item["id"], closure_evidence_ref=ref)
        assert submitted["status"] == "CLOSURE_SUBMITTED"
        during = read_project(api, project_id)
        assert during["open_punch_item_count"] == 1
        assert during["open_critical_punch_count"] == 1

        decide_closure(api, item["id"], "REJECT", note="not yet")
        after = read_project(api, project_id)
        assert after["open_punch_item_count"] == 1
        assert after["open_critical_punch_count"] == 1

    submit_closure(api, item["id"], closure_evidence_ref="PHOTO-3")
    decide_closure(api, item["id"], "APPROVE", note="verified")

    closed = read_project(api, project_id)
    assert closed["open_punch_item_count"] == 0
    assert closed["open_critical_punch_count"] == 0


def test_every_accepted_transition_leaves_its_mark_on_the_item_version(api):
    """Six accepted hops on top of creation put the item at version 7.

    PRD 3.9: "All three decisions store `decided_by_user_id` and increment the
    item's `version` by 1, and there the three diverge."

    Design: Difficulty/non_linear_state_machine/punch_item_closure_cycle_repeats_before_terminal_close
    """
    _project, item = _critical_item(api)
    assert_version_is(item, 1)

    for ref, decision in (("PHOTO-1", "REJECT"), ("PHOTO-2", "REJECT"), ("PHOTO-3", "APPROVE")):
        submit_closure(api, item["id"], closure_evidence_ref=ref)
        decide_closure(api, item["id"], decision)

    assert_version_is(read_punch_item(api, item["id"]), 7)
