"""Compensating actions that must restore their aggregates exactly.

Withdrawal reverses an assignment across two roll-ups at once, and rescission
reverses a four-hop assessment cascade without reversing the filing that
provoked it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import assert_money
from test_helpers.factories import action_payload, subcert_payload
from test_helpers.fixtures import (
    assess_correction,
    assign_subcert,
    build_committee,
    deficiencies_of,
    refresh_cycle,
    rescind_correction,
    scenario_close_open,
    submit_subcert,
    withdraw_subcert,
)
from test_helpers.test_users import admin_headers

DRIFT_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
OPERATIONS_DUE = "2026-08-05T12:00:00Z"


def _two_row_cycle(api):
    """One SUBMITTED revenue row weighted 30.00 and one PENDING legal row weighted
    25.00, so the cycle reads 55.00 assigned and 54.55 covered."""
    committee = build_committee(
        api,
        seats=DRIFT_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Drift Charter",
    )
    scenario = scenario_close_open(api, committee)
    revenue = assign_subcert(
        api, committee, scenario.cycle_id, "fin", "REVENUE",
        due_utc="2026-08-04T18:00:00Z",
    )
    revenue = submit_subcert(api, committee, revenue["id"], "fin")
    legal = assign_subcert(
        api, committee, scenario.cycle_id, "legal", "LEGAL_CONTINGENCY",
        due_utc="2026-08-04T18:00:00Z",
    )
    assert revenue["status"] == "SUBMITTED"
    assert legal["status"] == "PENDING"
    assert_money(revenue["scope_weight"], 30.00)
    assert_money(legal["scope_weight"], 25.00)
    before = refresh_cycle(api, scenario.cycle_id)
    assert_money(before["total_assigned_scope_weight"], 55.00)
    assert_money(before["certification_coverage_pct"], 54.55)
    return committee, scenario, revenue, legal


def _assign_operations(api, committee, cycle_id):
    return validate_success(
        api.create_subcert(
            subcert_payload(cycle_id, committee.mid("fin"), "OPERATIONS", OPERATIONS_DUE),
            committee.chair("legal"),
        ),
        201,
    )


def test_withdrawal_restores_the_sum_and_the_ratio_whose_denominator_it_shrinks(api):
    """A third row dilutes coverage from 54.55 to 40.00 without any submission
    changing, and withdrawing it returns both the conserved sum and the ratio to
    exactly their earlier values, leaving the two untouched rows in the states
    they held throughout.

    PRD 2.12: "This is what guarantees that assigning a sub-certification and then withdrawing it, or assessing a correction and then rescinding it, returns the roll-up to precisely its earlier value with no accumulated drift."

    Design: Difficulty/compensating_invariant/subcertification_withdrawal_restores_both_conserved_cycle_aggregates_with_zero_drift
    """
    committee, scenario, revenue, legal = _two_row_cycle(api)

    third = _assign_operations(api, committee, scenario.cycle_id)
    assert_money(third["scope_weight"], 20.00)
    diluted = refresh_cycle(api, scenario.cycle_id)
    assert_money(diluted["total_assigned_scope_weight"], 75.00)
    assert_money(diluted["certification_coverage_pct"], 40.00)

    withdrawn = withdraw_subcert(api, committee, third["id"])
    assert withdrawn["status"] == "WITHDRAWN"

    restored = refresh_cycle(api, scenario.cycle_id)
    assert_money(restored["total_assigned_scope_weight"], 55.00)
    assert_money(restored["certification_coverage_pct"], 54.55)

    assert validate_success(api.get_subcert(revenue["id"], admin_headers()))["status"] == (
        "SUBMITTED"
    )
    assert validate_success(api.get_subcert(legal["id"], admin_headers()))["status"] == (
        "PENDING"
    )


def test_a_second_add_and_withdraw_lap_reproduces_the_identical_four_numbers(api):
    """The recoverable value 30/55 is not exactly representable, so a second
    add-and-withdraw lap is the test for accumulated residue: re-creating the row
    is accepted because the duplicate guard only sees non-terminal rows, and both
    aggregates land on the same numbers as the first lap.

    PRD 2.12: "Two roll-ups on a reporting cycle are **conserved quantities**, meaning they are always recomputed in full from their source rows and never adjusted by an increment or a decrement."

    Design: Difficulty/compensating_invariant/subcertification_withdrawal_restores_both_conserved_cycle_aggregates_with_zero_drift
    """
    committee, scenario, _, _ = _two_row_cycle(api)
    first_lap = _assign_operations(api, committee, scenario.cycle_id)
    withdraw_subcert(api, committee, first_lap["id"])

    second_lap = _assign_operations(api, committee, scenario.cycle_id)
    assert second_lap["id"] != first_lap["id"]
    assert second_lap["status"] == "PENDING"
    mid = refresh_cycle(api, scenario.cycle_id)
    assert_money(mid["total_assigned_scope_weight"], 75.00)
    assert_money(mid["certification_coverage_pct"], 40.00)

    assert withdraw_subcert(api, committee, second_lap["id"])["status"] == "WITHDRAWN"
    back = refresh_cycle(api, scenario.cycle_id)
    assert_money(back["total_assigned_scope_weight"], 55.00)
    assert_money(back["certification_coverage_pct"], 54.55)


def _assessed_correction(api, scenario):
    """The draft correction assessed under the iron-curtain method, which lands on
    RESTATEMENT and raises exactly one open deficiency."""
    return assess_correction(
        api,
        scenario.correction["id"],
        method="IRON_CURTAIN",
        likelihood_pct=40,
        magnitude_amount=700000,
        compensating_control_present=False,
    )


def test_the_assessment_cascade_declares_a_restatement_and_carries_the_weight_up(
    draft_correction_cycle,
):
    """The iron-curtain reading of the same stored row is 5.83, which classifies as
    a RESTATEMENT, raises one OPEN deficiency scored 5.83 and weighted 23.32, and
    walks the remediation axis to RESTATEMENT_DECLARED while the workflow axis
    stays FILED.

    PRD 3.9: "Hop four, caused by that weight rising above 0.00 while the classification is `RESTATEMENT`, moves the cycle's `restatement_stage` from `UNDER_EVALUATION` to `RESTATEMENT_DECLARED`."

    Design: Difficulty/compensating_invariant/correction_rescission_reverses_the_deficiency_weight_and_the_restatement_stage_but_not_the_filing
    """
    scenario = draft_correction_cycle
    api = scenario.api

    before = refresh_cycle(api, scenario.cycle_id)
    assert before["restatement_stage"] == "UNDER_EVALUATION"
    assert_money(before["unresolved_deficiency_weight"], 0.00)
    assert before["status"] == "FILED"

    assessed = _assessed_correction(api, scenario)
    assert assessed["status"] == "ASSESSED"
    assert_money(assessed["materiality_pct"], 5.83)
    assert assessed["classification"] == "RESTATEMENT"
    assert assessed["method"] == "IRON_CURTAIN"

    rows = deficiencies_of(api, scenario.correction["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "OPEN"
    assert_money(rows[0]["severity_score"], 5.83)
    assert rows[0]["severity"] == "MATERIAL_WEAKNESS"
    assert_money(rows[0]["deficiency_weight"], 23.32)

    mid = refresh_cycle(api, scenario.cycle_id)
    assert_money(mid["unresolved_deficiency_weight"], 23.32)
    assert mid["restatement_stage"] == "RESTATEMENT_DECLARED"
    assert mid["status"] == "FILED"


def test_rescission_reverses_the_assessment_and_the_axis_but_never_the_filing(
    draft_correction_cycle,
):
    """Rescinding clears the correction's three derived fields, reverses the
    deficiency rather than deleting it, brings the weight back to exactly 0.00 and
    stands the declared restatement down to NONE — while the cycle stays FILED and
    the filing stays SUBMITTED, and a replay is refused because RESCINDED is
    terminal.

    PRD 3.9: "Hop one moves the correction to the terminal `RESCINDED` and clears `method`, `materiality_pct` and `classification` back to null."

    Design: Difficulty/compensating_invariant/correction_rescission_reverses_the_deficiency_weight_and_the_restatement_stage_but_not_the_filing
    """
    scenario = draft_correction_cycle
    api = scenario.api
    _assessed_correction(api, scenario)

    rescinded = rescind_correction(api, scenario.correction["id"])
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["method"] is None
    assert rescinded["materiality_pct"] is None
    assert rescinded["classification"] is None

    reversed_rows = deficiencies_of(api, scenario.correction["id"])
    assert len(reversed_rows) == 1
    assert reversed_rows[0]["status"] == "REVERSED"
    assert_money(reversed_rows[0]["deficiency_weight"], 23.32)

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["unresolved_deficiency_weight"], 0.00)
    assert after["restatement_stage"] == "NONE"
    assert after["status"] == "FILED"
    filing = validate_success(api.get_filing(scenario.filing["id"], admin_headers()))
    assert filing["status"] == "SUBMITTED"

    replayed = api.transition_correction(
        scenario.correction["id"], action_payload("RESCIND"), admin_headers()
    )
    validate_error(replayed, "ERR_ENTITY_TERMINAL", 409)
