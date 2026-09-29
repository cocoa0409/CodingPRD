"""Driving a residency's lifecycle against the state of its lesson plans."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    align_lesson_plan,
    api_client,
    create_residency_status_payload,
    create_standard,
    read_lesson_plan,
    read_residency,
    set_clock_to_default,
    setup_approved_residency,
    submit_lesson_plan,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]


def _approved_residency_with_creating_only_plan() -> dict:
    """Approved residency requiring CREATING and RESPONDING, with a single
    submitted plan that covers only CREATING."""
    set_clock_to_default()
    scenario = setup_approved_residency(
        residency_overrides={"required_strands": ["CREATING", "RESPONDING"]}
    )
    create_standard("DA:Cr1.1.4", "CREATING", discipline="DANCE", grade_band="G3_5")
    create_standard("DA:Re7.1.4", "RESPONDING", discipline="DANCE", grade_band="G3_5")
    plan_a = submit_lesson_plan(
        scenario["residency"]["id"],
        ["DA:Cr1.1.4"],
        1,
        title="Creating Only",
        materials_list="scarves",
    )
    scenario["plan_a"] = plan_a
    return scenario


def test_activation_without_any_aligned_plan_is_refused(api):
    """PRD §3.4: "`APPROVED → ACTIVE` is gated on curriculum readiness and is
    described from the curriculum side in §3.5: at least one lesson plan of this
    residency must be `ALIGNED`, or the transition is refused with
    `ERR_NO_ALIGNED_LESSON_PLAN`; and the union of `covered_strands` across all
    of this residency's `ALIGNED` plans must include every entry of
    `required_strands`, or the refusal is `ERR_STANDARDS_COVERAGE_INCOMPLETE`."
    PRD §3.5: "A new plan starts with a `status` of `SUBMITTED` and a
    `revision_round` of zero, and the server derives `covered_strands` as the
    distinct set of `strand` values on the standards resolved from
    `standard_codes`."

    Design: Difficulty/cross_entity_state_dependency/residency_activation_gated_by_aligned_lesson_plan_strand_union
    """
    scenario = _approved_residency_with_creating_only_plan()
    plan_a = scenario["plan_a"]
    assert plan_a["status"] == "SUBMITTED"
    assert plan_a["covered_strands"] == ["CREATING"], (
        f"expected covered_strands [CREATING], got {plan_a['covered_strands']}"
    )
    assert plan_a["revision_round"] == 0

    res = api_client.set_residency_status(
        scenario["residency"]["id"], create_residency_status_payload("ACTIVE"), PD
    )
    validate_error(
        res, ApiErrorId.ERR_NO_ALIGNED_LESSON_PLAN.value, expected_status=409
    )
    assert read_residency(scenario["residency"]["id"])["status"] == "APPROVED"


def test_activation_with_only_partial_strand_coverage_is_refused(api):
    """PRD §3.4: "`APPROVED → ACTIVE` is gated on curriculum readiness and is
    described from the curriculum side in §3.5: at least one lesson plan of this
    residency must be `ALIGNED`, or the transition is refused with
    `ERR_NO_ALIGNED_LESSON_PLAN`; and the union of `covered_strands` across all
    of this residency's `ALIGNED` plans must include every entry of
    `required_strands`, or the refusal is `ERR_STANDARDS_COVERAGE_INCOMPLETE`."
    PRD §3.5: "Strand completeness is a residency-level question, evaluated at
    activation over the union of all the residency's aligned plans."

    Design: Difficulty/cross_entity_state_dependency/residency_activation_gated_by_aligned_lesson_plan_strand_union
    """
    scenario = _approved_residency_with_creating_only_plan()
    aligned = align_lesson_plan(scenario["plan_a"]["id"])
    assert aligned["status"] == "ALIGNED", (
        "a plan need not cover every required strand to align, got "
        f"{aligned['status']}"
    )

    res = api_client.set_residency_status(
        scenario["residency"]["id"], create_residency_status_payload("ACTIVE"), PD
    )
    validate_error(
        res, ApiErrorId.ERR_STANDARDS_COVERAGE_INCOMPLETE.value, expected_status=409
    )
    assert read_residency(scenario["residency"]["id"])["status"] == "APPROVED"


def test_activation_succeeds_once_the_union_of_aligned_plans_covers_the_strands(api):
    """PRD §3.4: "`APPROVED → ACTIVE` is gated on curriculum readiness and is
    described from the curriculum side in §3.5: at least one lesson plan of this
    residency must be `ALIGNED`, or the transition is refused with
    `ERR_NO_ALIGNED_LESSON_PLAN`; and the union of `covered_strands` across all
    of this residency's `ALIGNED` plans must include every entry of
    `required_strands`, or the refusal is `ERR_STANDARDS_COVERAGE_INCOMPLETE`."
    PRD §3.4: "Approval initializes the allotment by setting
    `sessions_unscheduled_count` to `contracted_session_count`, and initializes
    the money ledger by setting `available_cents` to `budget_cents` with
    `encumbered_cents` and `disbursed_cents` both at zero."

    Design: Difficulty/cross_entity_state_dependency/residency_activation_gated_by_aligned_lesson_plan_strand_union
    """
    scenario = _approved_residency_with_creating_only_plan()
    residency_id = scenario["residency"]["id"]
    align_lesson_plan(scenario["plan_a"]["id"])

    plan_b = submit_lesson_plan(
        residency_id,
        ["DA:Re7.1.4"],
        2,
        title="Responding Companion",
        materials_list="video excerpts",
    )
    aligned_b = align_lesson_plan(plan_b["id"])
    assert aligned_b["status"] == "ALIGNED"
    assert aligned_b["covered_strands"] == ["RESPONDING"], (
        f"expected covered_strands [RESPONDING], got {aligned_b['covered_strands']}"
    )

    activated = validate_success(
        api_client.set_residency_status(
            residency_id, create_residency_status_payload("ACTIVE"), PD
        )
    )
    assert activated["status"] == "ACTIVE", (
        f"the strand union now covers the requirement, got {activated['status']}"
    )
    assert activated["sessions_unscheduled_count"] == 10, (
        "activation must not disturb the allotment initialized at approval, got "
        f"{activated['sessions_unscheduled_count']}"
    )
    assert read_lesson_plan(scenario["plan_a"]["id"])["revision_round"] == 0
