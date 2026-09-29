"""Two machines that are not straight lines.

The document review machine is a cycle whose counter advances on only one of
its two edges, and the sub-certification SUBMIT action forks on the presence of
an exception severity into two arms with different side-effect sets.
"""

from prd_bench_local_runner.testing import validate_error
from test_helpers.assertions import assert_instant_equals, assert_money
from test_helpers.factories import action_payload
from test_helpers.fixtures import (
    assign_subcert,
    build_committee,
    refresh_cycle,
    refresh_document,
    request_changes,
    scenario_close_open,
    submit_for_review,
    submit_subcert,
)

PAIR_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
FIRST_NOTE = "Restate the segment margin table."
SECOND_NOTE = "Second pass: fix the cash-flow bridge."


def _loop_fixture(api):
    committee = build_committee(
        api,
        seats=PAIR_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Loop Charter",
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "EARNINGS_RELEASE", author_key="fin", title="Q2 FY2026 Earnings Release",
        safe_harbor_present=True,
    )
    return committee, document


def test_the_review_submission_edge_leaves_the_revision_counter_alone(api):
    """A fresh draft carries revision_round 0 and a null change_note; moving it
    to IN_REVIEW does not touch the counter, and only the entry into
    CHANGES_REQUESTED lifts it to 1 while storing the note.

    PRD 3.5: "Entry into `CHANGES_REQUESTED` is where `revision_round` increments by exactly 1, and the supplied `change_note` is stored on the document, overwriting whatever the previous round left there."

    Design: Difficulty/non_linear_state_machine/document_review_loop_increments_revision_round_only_on_entry_to_changes_requested
    """
    committee, document = _loop_fixture(api)
    assert document["status"] == "DRAFT"
    assert document["revision_round"] == 0
    assert document["change_note"] is None

    in_review = submit_for_review(api, committee, document["id"], "fin")
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["revision_round"] == 0
    assert in_review["change_note"] is None

    changes = request_changes(api, committee, document["id"], FIRST_NOTE)
    assert changes["status"] == "CHANGES_REQUESTED"
    assert changes["revision_round"] == 1
    assert changes["change_note"] == FIRST_NOTE


def test_the_second_lap_of_the_loop_reaches_round_two_and_overwrites_the_note(api):
    """Driving SUBMIT_REVIEW, REQUEST_CHANGES, SUBMIT_REVIEW, REQUEST_CHANGES
    ends at CHANGES_REQUESTED with revision_round 2 — not 3 from counting every
    edge and not 1 from refusing the second lap — and the change_note holds the
    second note.

    PRD 3.5: "The return edge back into `IN_REVIEW` does **not** increment `revision_round` a second time; the counter counts change requests, not review submissions."

    Design: Difficulty/non_linear_state_machine/document_review_loop_increments_revision_round_only_on_entry_to_changes_requested
    """
    committee, document = _loop_fixture(api)

    submit_for_review(api, committee, document["id"], "fin")
    request_changes(api, committee, document["id"], FIRST_NOTE)
    looped_back = submit_for_review(api, committee, document["id"], "fin")
    assert looped_back["status"] == "IN_REVIEW"
    assert looped_back["revision_round"] == 1
    assert looped_back["change_note"] == FIRST_NOTE

    second_round = request_changes(api, committee, document["id"], SECOND_NOTE)
    assert second_round["status"] == "CHANGES_REQUESTED"
    assert second_round["revision_round"] == 2

    stored = refresh_document(api, committee, document["id"])
    assert stored["status"] == "CHANGES_REQUESTED"
    assert stored["revision_round"] == 2
    assert stored["change_note"] == SECOND_NOTE


def _fork_fixture(api):
    committee = build_committee(
        api,
        seats=PAIR_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Fork Charter",
    )
    scenario = scenario_close_open(api, committee)
    plain = assign_subcert(
        api, committee, scenario.cycle_id, "fin", "OPERATIONS",
        due_utc="2026-08-04T12:00:00Z",
    )
    exceptional = assign_subcert(
        api, committee, scenario.cycle_id, "legal", "OPERATIONS",
        due_utc="2026-08-04T12:00:00Z",
    )
    return committee, scenario, plain, exceptional


def test_the_clean_arm_moves_only_the_coverage_numerator(api):
    """SUBMIT with no exception severity lands the row in SUBMITTED at its
    unchanged weight of 20.00, so the cycle total stays at 40.00 while coverage
    rises from 0.00 to exactly 50.00.

    PRD 3.4: "It stamps `submitted_utc` from the logical clock, leaves `exception_severity` at `NONE`, and leaves `scope_weight` untouched."

    Design: Difficulty/non_linear_state_machine/subcert_submit_forks_into_submitted_or_exception_noted_with_divergent_side_effects
    """
    committee, scenario, plain, _ = _fork_fixture(api)

    before = refresh_cycle(api, scenario.cycle_id)
    assert_money(before["total_assigned_scope_weight"], 40.00)
    assert_money(before["certification_coverage_pct"], 0.00)

    submitted = submit_subcert(api, committee, plain["id"], "fin")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["exception_severity"] == "NONE"
    assert submitted["exception_note"] is None
    assert_money(submitted["scope_weight"], 20.00)
    assert_instant_equals(submitted["submitted_utc"], "2026-08-01T00:00:00Z")

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["total_assigned_scope_weight"], 40.00)
    assert_money(after["certification_coverage_pct"], 50.00)


def test_the_exception_arm_reweights_the_row_and_moves_both_sides_of_the_ratio(api):
    """A MEDIUM exception needs a note, re-derives the weight to 20 * 1.4 =
    28.00 and pushes the cycle total to 48.00 while coverage still reaches
    100.00 because the increased weight enters numerator and denominator alike;
    the resulting EXCEPTION_NOTED row declares no second SUBMIT edge.

    PRD 3.4: "It stamps `submitted_utc`, records `exception_severity` and `exception_note`, and — this is what diverges from the clean branch — re-runs the weight derivation with the escalation factor now in play, so the row's `scope_weight` rises."

    Design: Difficulty/non_linear_state_machine/subcert_submit_forks_into_submitted_or_exception_noted_with_divergent_side_effects
    """
    committee, scenario, plain, exceptional = _fork_fixture(api)
    submit_subcert(api, committee, plain["id"], "fin")

    missing_note = api.transition_subcert(
        exceptional["id"],
        action_payload("SUBMIT", exception_severity="MEDIUM"),
        committee.leader("legal"),
    )
    validate_error(missing_note, "ERR_INVALID_REQUEST", 422)

    noted = submit_subcert(
        api, committee, exceptional["id"], "legal",
        exception_severity="MEDIUM",
        exception_note="Two plant locations closed late; compensating review performed.",
    )
    assert noted["status"] == "EXCEPTION_NOTED"
    assert noted["exception_severity"] == "MEDIUM"
    assert_money(noted["scope_weight"], 28.00)

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["total_assigned_scope_weight"], 48.00)
    assert_money(after["certification_coverage_pct"], 100.00)

    replay = api.transition_subcert(
        exceptional["id"],
        action_payload("SUBMIT", exception_severity="MEDIUM", exception_note="Again."),
        committee.leader("legal"),
    )
    validate_error(replay, "ERR_INVALID_STATE", 409)
