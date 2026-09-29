"""The rework loop back through DRAFT and the gates guarding submission."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    CITRUS_LINE_WEIGHTS,
    add_material_line,
    approve_formula,
    build_formula_with_lines,
    citrus_costed_formula,
    citrus_materials,
    citrus_submitted_brief,
    components_of,
    cost_formula,
    delete_component,
    error_id_of,
    read_brief,
    read_formula,
    reprice_material,
    rework_formula,
    submit_formula,
)
from test_helpers.test_users import FLAVORIST_SUBMITTER


def _rejected_citrus_formula(api, **brief_overrides):
    """The citrus formula costed, submitted and rejected back to REWORK_REQUIRED."""
    scenario = citrus_costed_formula(api, **brief_overrides)
    submit_formula(api, scenario["formula"]["id"])
    scenario["formula"] = rework_formula(
        api, scenario["formula"]["id"])
    return scenario


def test_a_director_rejection_records_the_rework_reason(api):
    """The rejection lands in REWORK_REQUIRED with DIRECTOR_REJECTION.

    The PRD says "a `decision` of `REWORK_REQUIRED` drives `SUBMITTED →
    REWORK_REQUIRED`, sets `rework_reason` to `DIRECTOR_REJECTION`, and
    increments `version`".

    Design: Difficulty/non_linear_state_machine/formula_rework_loop_reenters_draft_and_reaches_approved_again
    """
    scenario = _rejected_citrus_formula(api)

    assert scenario["formula"]["status"] == "REWORK_REQUIRED"
    assert scenario["formula"]["rework_reason"] == "DIRECTOR_REJECTION"


def test_removing_a_line_pulls_the_reworked_formula_back_into_draft(api):
    """The delete drives REWORK_REQUIRED to DRAFT and clears the cost fields.

    The PRD says that on deletion "`component_count` and `total_weight_pct`
    are recomputed, and the same `COSTED → DRAFT` or `REWORK_REQUIRED → DRAFT`
    fallback fires with the same field clearing".  Dropping the 1.2500 line
    leaves 98.7500 and a null bench cost.

    Design: Difficulty/non_linear_state_machine/formula_rework_loop_reenters_draft_and_reaches_approved_again
    """
    scenario = _rejected_citrus_formula(api)
    second_line = scenario["components"][1]

    delete_component(api, second_line["id"])

    formula = read_formula(api, scenario["formula"]["id"])
    assert formula["status"] == "DRAFT"
    assert float(formula["total_weight_pct"]) == 98.75
    assert formula["bench_cost_per_kg_cents"] is None


def test_the_replacement_line_takes_the_next_sequence_number(api):
    """Re-adding the removed line lands at sequence_no 3, not back at 2.

    The PRD says a new line's `sequence_no` is "one more than the number of
    lines already on that formula with an earlier creation timestamp", so after the survivors are renumbered 1 and 2 the replacement
    is 3.

    Design: Difficulty/non_linear_state_machine/formula_rework_loop_reenters_draft_and_reaches_approved_again
    """
    scenario = _rejected_citrus_formula(api)
    second_line = scenario["components"][1]

    delete_component(api, second_line["id"])
    replacement = add_material_line(api, scenario["formula"]["id"],
                                    scenario["m2"]["id"], CITRUS_LINE_WEIGHTS[1])

    assert replacement["sequence_no"] == 3
    assert len(components_of(api, scenario["formula"]["id"])) == 3


def test_the_second_costing_pass_reproduces_the_same_bench_cost(api):
    """The loop returns to APPROVED at the identical 2977 and iteration 1.

    The PRD's roll-up depends only on the current line set, so re-costing the
    same three weights gives the same "plain sum of those already-rounded
    per-line contributions", and `iteration_no` only advances through a
    revision, which "is derived at creation" and is untouched by a rework loop.

    Design: Difficulty/non_linear_state_machine/formula_rework_loop_reenters_draft_and_reaches_approved_again
    """
    scenario = _rejected_citrus_formula(api)
    formula_id = scenario["formula"]["id"]
    bench_first = 2977

    delete_component(api, scenario["components"][1]["id"])
    add_material_line(api, formula_id, scenario["m2"]["id"], CITRUS_LINE_WEIGHTS[1])
    recosted = cost_formula(api, formula_id)

    assert recosted["bench_cost_per_kg_cents"] == bench_first == 2977

    submit_formula(api, formula_id)
    approved = approve_formula(api, formula_id)

    assert approved["status"] == "APPROVED"
    assert approved["iteration_no"] == 1
    assert approved["parent_formula_id"] is None


def test_submission_is_refused_while_the_brief_is_only_submitted(api):
    """A perfectly costed formula cannot be submitted under an undecided brief.

    The PRD requires at submission that "The owning brief must be in
    `ACCEPTED`; otherwise the submission is refused with
    `ERR_BRIEF_NOT_ACCEPTED`", and §2.11 places that
    cross-entity guard ahead of the fiscal cap rule.

    Design: Difficulty/cross_entity_state_dependency/formula_submit_requires_its_brief_to_be_accepted
    """
    materials = citrus_materials(api)
    brief = citrus_submitted_brief(api)
    built = build_formula_with_lines(
        api, brief["id"],
        [(materials["m1"]["id"], CITRUS_LINE_WEIGHTS[0]),
         (materials["m2"]["id"], CITRUS_LINE_WEIGHTS[1]),
         (materials["m3"]["id"], CITRUS_LINE_WEIGHTS[2])],
        name="Citrus Top Note F1")
    costed = cost_formula(api, built["formula"]["id"])

    assert brief["status"] == "SUBMITTED"
    assert costed["status"] == "COSTED"
    assert costed["bench_cost_per_kg_cents"] == 2977

    response = api.submit_formula(built["formula"]["id"], FLAVORIST_SUBMITTER)
    validate_error(response, ApiErrorId.ERR_BRIEF_NOT_ACCEPTED.value)


def test_the_refused_submission_leaves_both_records_untouched(api):
    """No submitter is stamped and neither status moves.

    The PRD stamps "the caller's `X-User-ID` into `submitted_by_user_id`" only
    on a successful submission, and a new formula starts with
    `submitted_by_user_id` null.

    Design: Difficulty/cross_entity_state_dependency/formula_submit_requires_its_brief_to_be_accepted
    """
    materials = citrus_materials(api)
    brief = citrus_submitted_brief(api)
    built = build_formula_with_lines(
        api, brief["id"],
        [(materials["m1"]["id"], CITRUS_LINE_WEIGHTS[0]),
         (materials["m2"]["id"], CITRUS_LINE_WEIGHTS[1]),
         (materials["m3"]["id"], CITRUS_LINE_WEIGHTS[2])],
        name="Citrus Top Note F1")
    cost_formula(api, built["formula"]["id"])

    validate_error(api.submit_formula(built["formula"]["id"], FLAVORIST_SUBMITTER),
                   ApiErrorId.ERR_BRIEF_NOT_ACCEPTED.value)

    formula = read_formula(api, built["formula"]["id"])
    assert formula["status"] == "COSTED"
    assert formula["submitted_by_user_id"] is None
    assert read_brief(api, brief["id"])["status"] == "SUBMITTED"


def test_repricing_leaves_the_approved_formula_stale_but_approved(api):
    """The reprice recosts the APPROVED formula to 3248 and flags it stale.

    The PRD says "a formula in `APPROVED` stays `APPROVED`, but its
    `cost_stale` flag is set to true ... and its `version` is incremented",
    with the roll-up "re-running both the bench cost roll-up and the
    cost-in-use derivation of §3.4 against the new price".  At 1500 cents for
    the solvent the lines give 1700 + 123 + 1425 = 3248 and 81200 per tonne.

    Design: Difficulty/priority_pair_validation_conflict/submit_state_check_outranks_cost_in_use_cap_breach
    """
    scenario = citrus_costed_formula(api)
    formula_id = scenario["formula"]["id"]
    assert scenario["formula"]["bench_cost_in_use_cents_per_tonne"] == 74425

    submit_formula(api, formula_id)
    approve_formula(api, formula_id)
    reprice_material(api, scenario["m3"]["id"], 1500)

    formula = read_formula(api, formula_id)
    assert formula["status"] == "APPROVED"
    assert formula["bench_cost_per_kg_cents"] == 3248
    assert formula["bench_cost_in_use_cents_per_tonne"] == 81200
    assert formula["cost_stale"] is True


def test_the_state_guard_outranks_the_breached_cost_in_use_cap(api):
    """Re-submitting the stale APPROVED formula gives the state error, not the cap error.

    Both rules are live: the formula is `APPROVED` rather than `COSTED`, and
    81200 exceeds the 74425 cap.  The PRD orders the checks so that "own-state
    outranks every business rule below it, an already-approved formula asked to
    submit reports a state error rather than a cost-cap error", so the response
    is `ERR_FORMULA_STATE_INVALID` at HTTP 409 rather
    than `ERR_COST_IN_USE_CAP_EXCEEDED` at 422.

    Design: Difficulty/priority_pair_validation_conflict/submit_state_check_outranks_cost_in_use_cap_breach
    """
    scenario = citrus_costed_formula(api)
    formula_id = scenario["formula"]["id"]
    submit_formula(api, formula_id)
    approve_formula(api, formula_id)
    reprice_material(api, scenario["m3"]["id"], 1500)

    response = api.submit_formula(formula_id, FLAVORIST_SUBMITTER)
    validate_error(response, ApiErrorId.ERR_FORMULA_STATE_INVALID.value)
    assert error_id_of(response) != "ERR_COST_IN_USE_CAP_EXCEEDED"

    formula = read_formula(api, formula_id)
    assert formula["status"] == "APPROVED"
    assert formula["bench_cost_per_kg_cents"] == 3248
