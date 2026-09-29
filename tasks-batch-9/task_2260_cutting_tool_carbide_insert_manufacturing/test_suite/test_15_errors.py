"""Error identities, and the ordering that decides which of two codes is seen.

Two envelope errors sit above everything else and must pre-empt the checks
behind them. Two schema families — the coating layer stack and the flank-wear
curve — sit above the row lookups, so a malformed body on a request naming a row
that does not exist reports the malformed body. And two entities share the
state-transition priority while raising their own distinct codes.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_coating_recipe,
    assert_machining_trial,
    assert_no_row_with_code,
)
from test_helpers.fixtures import COAT, MET, OPERATOR_ONE, PLAN
from test_helpers.test_users import (
    headers_with_empty_user_id,
    headers_without_user_id,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_GRADE_ID = "11111111-1111-4111-8111-111111111121"
UNKNOWN_TRIAL_ID = "22222222-2222-4222-8222-222222222222"

_ONE_POINT_CURVE = [{"minutes": 0, "vb_um": 0}]
_DECREASING_CURVE = [
    {"minutes": 0, "vb_um": 0},
    {"minutes": 10, "vb_um": 200},
    {"minutes": 20, "vb_um": 180},
]
_FLAT_TAILED_CURVE = [
    {"minutes": 0, "vb_um": 0},
    {"minutes": 12, "vb_um": 225},
    {"minutes": 24, "vb_um": 320},
    {"minutes": 30, "vb_um": 320},
]


# ─── The two envelope errors pre-empt everything behind them ─────────────────

def test_an_unidentified_caller_is_refused_before_the_row_is_looked_up(api):
    """A GET for a grade that does not exist answers 401, never the 404.

    PRD §2.1: "A request whose `X-User-ID` header is absent or empty is rejected
    with `ERR_UNAUTHENTICATED`."

    PRD §2.11: "1. **Authentication.** `X-User-ID` absent or empty →
    `ERR_UNAUTHENTICATED`. Applies to every endpoint except the logical-clock
    capability."

    PRD §2.11: "7. **Path identifier existence.** The identifier in the URL
    matches no row → that entity's not-found code from §2.8. Applies to every
    endpoint with a path parameter."

    Design: Corner/errors/authentication_and_role_errors_short_circuit_deeper_checks
    """
    empty = api.get_carbide_grade(
        UNKNOWN_GRADE_ID, headers_with_empty_user_id("MetallurgyEngineer")
    )
    absent = api.get_carbide_grade(
        UNKNOWN_GRADE_ID, headers_without_user_id("MetallurgyEngineer")
    )

    error = validate_error(empty, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"the envelope carries a human-readable explanation, got {error['message']!r}"
    )
    validate_error(absent, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_a_forbidden_role_is_refused_before_its_incomplete_body_is_read(api):
    """The very same body answers 403 for the wrong role and 400 for the right one.

    PRD §2.11: "2. **Authorisation.** The caller's role is not authorised for the
    endpoint → `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."

    PRD §2.11: "3. **Body schema.** A required input field is missing, a field has
    the wrong JSON type, or an unknown field is supplied → `ERR_INVALID_REQUEST`.
    Applies to every endpoint with a request body."

    PRD §2.1: "`MetallurgyEngineer` owns carbide grade development and the powder
    blend, press and sinter route, including the sintering QC verdict."

    Design: Corner/errors/authentication_and_role_errors_short_circuit_deeper_checks
    """
    incomplete = {"grade_code": "WC-X"}

    wrong_role = api.create_carbide_grade(incomplete, COAT)
    right_role = api.create_carbide_grade(incomplete, MET)

    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(right_role, ApiErrorId.ERR_INVALID_REQUEST, 400)
    rows, meta = validate_paginated(api.list_carbide_grades(MET))
    assert meta["total_count"] == 0, (
        f"neither refused call created a grade, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "grade_code", "WC-X")


# ─── Layer-stack well-formedness ────────────────────────────────────────────

def test_three_malformed_layer_stacks_are_each_refused(api):
    """An empty stack, a sixth layer and an adjacent repeat all raise one code.

    PRD §3.3: "The stack must hold between 1 and 5 entries, each `material` must
    be one of `TiN`, `TiAlN`, `AlCrN`, `Al2O3` or `TiCN`, each `thickness_um` must
    be at least 0.10 and at most 8.00, and no two **adjacent** entries may name
    the same material — a TiN/TiN pair is a process impossibility. An empty stack,
    a stack longer than five entries, or an adjacent-material repetition is
    rejected with `ERR_INVALID_LAYER_STACK`."

    PRD §2.11: "6. **Layer-stack well-formedness.** Applies to coating-recipe
    creation and coating-recipe revision → `ERR_INVALID_LAYER_STACK`."

    Design: Corner/errors/layer_stack_schema_rejections_and_the_legal_non_adjacent_repeat
    """
    six_layers = [
        {"material": "TiN", "thickness_um": 0.5},
        {"material": "TiAlN", "thickness_um": 0.5},
        {"material": "TiN", "thickness_um": 0.5},
        {"material": "TiAlN", "thickness_um": 0.5},
        {"material": "TiN", "thickness_um": 0.5},
        {"material": "TiAlN", "thickness_um": 0.5},
    ]
    adjacent_repeat = [
        {"material": "TiAlN", "thickness_um": 1.0},
        {"material": "TiAlN", "thickness_um": 2.0},
    ]

    empty = api.create_coating_recipe(
        f.coating_recipe_payload(recipe_code="PVD-EMPTY", layers=[]), COAT
    )
    too_many = api.create_coating_recipe(
        f.coating_recipe_payload(recipe_code="PVD-SIX", layers=six_layers), COAT
    )
    repeated = api.create_coating_recipe(
        f.coating_recipe_payload(recipe_code="PVD-ADJ", layers=adjacent_repeat), COAT
    )

    validate_error(empty, ApiErrorId.ERR_INVALID_LAYER_STACK, 422)
    validate_error(too_many, ApiErrorId.ERR_INVALID_LAYER_STACK, 422)
    validate_error(repeated, ApiErrorId.ERR_INVALID_LAYER_STACK, 422)
    rows, meta = validate_paginated(api.list_coating_recipes(COAT))
    assert meta["total_count"] == 0, (
        f"no recipe survives the three refusals, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "recipe_code", "PVD-SIX")


def test_a_material_may_repeat_once_the_repetition_is_not_adjacent(api):
    """TiAlN/TiN/TiAlN is legal, so the rule is not a distinct-material check.

    PRD §3.3: "On acceptance, `total_thickness_um` is computed as the sum of the
    entries' `thickness_um` values carried to two decimal places, `revision` is 1,
    `adhesion_class` is null and `is_validated` is false. A recipe therefore starts
    life unproven: nothing in the recipe definition asserts that the stack will
    adhere."

    Design: Corner/errors/layer_stack_schema_rejections_and_the_legal_non_adjacent_repeat
    """
    sandwich = [
        {"material": "TiAlN", "thickness_um": 1.0},
        {"material": "TiN", "thickness_um": 0.5},
        {"material": "TiAlN", "thickness_um": 1.0},
    ]

    response = api.create_coating_recipe(
        f.coating_recipe_payload(recipe_code="PVD-ABA", layers=sandwich), COAT
    )

    recipe = validate_success(response, 201)
    assert_coating_recipe(recipe)
    assert recipe["total_thickness_um"] == 2.50, (
        f"1.0 plus 0.5 plus 1.0 is 2.50, got {recipe['total_thickness_um']}"
    )
    assert recipe["revision"] == 1, (
        f"a new recipe opens at revision 1, got {recipe['revision']}"
    )
    assert recipe["adhesion_class"] is None, (
        f"no chamber evidence exists yet, got {recipe['adhesion_class']}"
    )
    assert recipe["is_validated"] is False, (
        f"the stack is unproven at creation, got {recipe['is_validated']}"
    )
    _rows, meta = validate_paginated(api.list_coating_recipes(COAT))
    assert meta["total_count"] == 1, (
        f"exactly one recipe exists, got {meta['total_count']}"
    )


# ─── Wear-curve well-formedness sits above the trial lookup ─────────────────

def _running_trial(api) -> dict:
    """An OPEN dossier with one RUNNING trial that drew 20 of the batch's 180."""
    state = fx.open_dossier(api, coated=False)
    state["trial"] = validate_success(
        api.create_machining_trial(
            f.trial_payload(state["dossier"]["id"], state["batch"]["id"]), OPERATOR_ONE
        ),
        201,
    )
    return state


def test_a_malformed_curve_on_an_unknown_trial_reports_the_curve(api):
    """Priority 5 runs before the path lookup, so the 422 hides the 404.

    PRD §2.11: "5. **Wear-curve well-formedness.** Applies to trial completion →
    `ERR_INVALID_WEAR_CURVE`."

    PRD §3.6: "The curve must hold at least 2 entries, its `minutes` values must be
    strictly increasing, its `vb_um` values must be non-decreasing, and its last
    two `vb_um` values must not be equal; a curve that fails any of those is
    rejected with `ERR_INVALID_WEAR_CURVE`."

    Design: Corner/errors/wear_curve_schema_is_checked_before_the_trial_is_looked_up
    """
    response = api.complete_machining_trial(
        UNKNOWN_TRIAL_ID,
        f.complete_trial_payload(wear_measurements=_ONE_POINT_CURVE),
        OPERATOR_ONE,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WEAR_CURVE, 422)


def test_the_three_malformed_curve_shapes_leave_the_trial_running(api):
    """One point, a decreasing step and an equal final pair are each refused.

    PRD §3.6: "The curve must hold at least 2 entries, its `minutes` values must be
    strictly increasing, its `vb_um` values must be non-decreasing, and its last
    two `vb_um` values must not be equal; a curve that fails any of those is
    rejected with `ERR_INVALID_WEAR_CURVE`."

    PRD §3.6: "The rate is always strictly positive because a curve whose last two
    `vb_um` values are equal was already refused."

    Design: Corner/errors/wear_curve_schema_is_checked_before_the_trial_is_looked_up
    """
    state = _running_trial(api)
    trial_id = state["trial"]["id"]

    single = api.complete_machining_trial(
        trial_id, f.complete_trial_payload(wear_measurements=_ONE_POINT_CURVE), OPERATOR_ONE
    )
    decreasing = api.complete_machining_trial(
        trial_id, f.complete_trial_payload(wear_measurements=_DECREASING_CURVE), OPERATOR_ONE
    )
    flat_tailed = api.complete_machining_trial(
        trial_id, f.complete_trial_payload(wear_measurements=_FLAT_TAILED_CURVE), OPERATOR_ONE
    )

    validate_error(single, ApiErrorId.ERR_INVALID_WEAR_CURVE, 422)
    validate_error(decreasing, ApiErrorId.ERR_INVALID_WEAR_CURVE, 422)
    validate_error(flat_tailed, ApiErrorId.ERR_INVALID_WEAR_CURVE, 422)
    trial = validate_success(api.get_machining_trial(trial_id, OPERATOR_ONE))
    assert trial["status"] == "RUNNING", (
        f"a refused completion leaves the trial open, got {trial['status']}"
    )
    assert trial["rated_life_min"] is None, (
        f"no life figure has been established, got {trial['rated_life_min']}"
    )
    batch = validate_success(api.get_powder_blend_batch(state["batch"]["id"], MET))
    assert batch["remaining_units"] == 160, (
        "only the trial's own 20 units were ever drawn from the 180 sintered, got "
        f"{batch['remaining_units']}"
    )


def test_the_well_formed_curve_is_then_accepted_and_rates_twenty_minutes(api):
    """The crossing pair 290 → 320 puts the 300 um limit at exactly 20.0 minutes.

    PRD §3.6: "Walking consecutive pairs in ascending `minutes` order, the server
    takes the first pair whose earlier `vb_um` is strictly below the
    300-micrometre flank-wear limit and whose later `vb_um` is at or above it;
    within that pair the life is interpolated linearly, as the earlier entry's
    `minutes` plus the shortfall from the earlier `vb_um` to 300 divided by the
    wear increase across the pair and multiplied by the time increase across the
    pair, rounded half up to one decimal place, with `censored` set to false."

    PRD §3.6: "The `verdict` is `PASS` when all three of the following hold:
    `censored` is false, `rated_life_min` is at least the required life for the
    class, and `measured_surface_ra_um` is at most the maximum for the class."

    Design: Corner/errors/wear_curve_schema_is_checked_before_the_trial_is_looked_up
    """
    state = _running_trial(api)

    response = api.complete_machining_trial(
        state["trial"]["id"], f.complete_trial_payload(), OPERATOR_ONE
    )

    trial = validate_success(response)
    assert_machining_trial(trial)
    assert trial["status"] == "COMPLETED", (
        f"a well-formed curve closes the trial, got {trial['status']}"
    )
    assert trial["rated_life_min"] == 20.0, (
        "18 plus 6 times 10 over 30 is 20.0 minutes, got "
        f"{trial['rated_life_min']}"
    )
    assert trial["censored"] is False, (
        f"the curve crossed the limit, so nothing is censored, got {trial['censored']}"
    )
    assert trial["verdict"] == "PASS", (
        "20.0 clears the 18.0-minute MEDIUM requirement at Ra 1.20 against a 1.6 "
        f"ceiling, got {trial['verdict']}"
    )


# ─── Two entities, one priority, two state codes ────────────────────────────

def test_a_second_completion_of_a_coating_run_keeps_the_first_measurements(api):
    """The run is already COMPLETED, so its own state code answers the repeat.

    PRD §3.3: "Closing out a deposition run requires the run to be `SCHEDULED`,
    otherwise `ERR_INVALID_COATING_RUN_STATE`, and requires the current logical
    UTC time to have reached `window_end`; completing early is rejected with
    `ERR_WINDOW_NOT_ELAPSED`."

    PRD §2.11: "12. **Subject state permits the transition.** The addressed
    entity is not in a state from which the requested transition is declared →
    the entity's own invalid-state code"

    Design: Corner/errors/state_error_family_for_coating_runs_and_recondition_jobs
    """
    state = fx.validated_pvd_recipe(api)
    assert state["coating_run"]["status"] == "COMPLETED", (
        f"the run was closed out in the fixture, got {state['coating_run']['status']}"
    )

    response = api.complete_coating_run(
        state["coating_run"]["id"],
        f.complete_coating_run_payload(adhesion_hf_class=1, measured_thickness_um=3.05),
        COAT,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_COATING_RUN_STATE, 409)
    run = validate_success(api.get_coating_run(state["coating_run"]["id"], COAT))
    assert run["adhesion_hf_class"] == 2, (
        f"the first completion's adhesion class stands, got {run['adhesion_hf_class']}"
    )
    assert run["measured_thickness_um"] == 3.10, (
        f"the first completion's thickness stands, got {run['measured_thickness_um']}"
    )


def test_a_job_refuses_a_skipped_grind_and_a_jumped_return(api):
    """Refurbish is no exit from RECEIVED, and return is no exit from INSPECTED.

    PRD §3.9: "On success the job moves `INSPECTED` → `REFURBISHED`, `wheel_id` and
    `recoat_applied` are recorded, `units_inspected` multiplied by
    `grind_units_per_tool` is added to the wheel's `consumed_life_units`, and if
    that charge takes the wheel's `remaining_life_units` below 150 the wheel moves
    `AVAILABLE` → `DRESSING`."

    PRD §3.9: "Returning the tools settles the money and moves the job
    `REFURBISHED` → `RETURNED`."

    Design: Corner/errors/state_error_family_for_coating_runs_and_recondition_jobs
    """
    state = fx.received_recondition_job(
        api,
        customer_overrides={
            "customer_code": "CU-A",
            "name": "Kappa Cutters",
            "tier": "STANDARD",
        },
    )
    wheel = fx.grinding_wheel(api, wheel_code="WH-A", initial_life_units=100000)

    skipped = api.refurbish_recondition_job(
        state["job"]["id"], f.refurbish_job_payload(wheel["id"]), PLAN
    )
    validate_error(skipped, ApiErrorId.ERR_INVALID_JOB_STATE, 409)
    untouched = validate_success(api.get_grinding_wheel(wheel["id"], PLAN))
    assert untouched["consumed_life_units"] == 0, (
        f"the refused grind charged nothing to the wheel, got {untouched['consumed_life_units']}"
    )

    validate_success(
        api.inspect_recondition_job(
            state["job"]["id"],
            f.inspect_job_payload(measured_length_mm=90.0, measured_corner_wear_um=210.0),
            PLAN,
        )
    )
    jumped = api.return_recondition_job(
        state["job"]["id"], f.return_job_payload(), PLAN
    )

    validate_error(jumped, ApiErrorId.ERR_INVALID_JOB_STATE, 409)
    job = validate_success(api.get_recondition_job(state["job"]["id"], PLAN))
    assert job["status"] == "INSPECTED", (
        f"the job waits at INSPECTED for its grind, got {job['status']}"
    )
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["reserved_credit_cents"] == 18500, (
        "the intake reservation is neither consumed nor refunded by a refused "
        f"return, got {customer['reserved_credit_cents']}"
    )


def test_a_returned_job_is_terminal_and_refuses_a_late_scrap(api):
    """RETURNED is the end of the line, and the settled figures are untouched.

    PRD §3.9: "Scrapping is the alternative ending, open to a `ProductionPlanner`
    or a `QualityApprover`, admissible from either `RECEIVED` or `INSPECTED` as
    `RECEIVED` → `SCRAPPED` or `INSPECTED` → `SCRAPPED`, and recorded with a
    `scrap_reason`."

    PRD §3.9: "The `rebate_cents` is `life_extension_pct` divided by 100,
    multiplied by `units_returned`, multiplied by a rebate basis of 900 cents,
    rounded half up to whole cents — and it uses the residual-geometry figure only,
    never `warranted_life_extension_pct`."

    PRD §3.9: "The job's `version` and the customer's `version` each advance by 1,
    and `RETURNED` is terminal."

    Design: Corner/errors/state_error_family_for_coating_runs_and_recondition_jobs
    """
    state = fx.refurbished_recondition_job(
        api,
        wheel_overrides={"wheel_code": "WH-A"},
        inspect_overrides={
            "measured_length_mm": 90.0,
            "measured_corner_wear_um": 210.0,
        },
    )
    settled = validate_success(
        api.return_recondition_job(state["job"]["id"], f.return_job_payload(), PLAN)
    )
    assert settled["rebate_cents"] == 1800, (
        "20.0 % over 10 tools at a 900-cent basis is 1800 cents, got "
        f"{settled['rebate_cents']}"
    )

    response = api.scrap_recondition_job(
        state["job"]["id"], f.scrap_job_payload(), PLAN
    )

    validate_error(response, ApiErrorId.ERR_INVALID_JOB_STATE, 409)
    job = validate_success(api.get_recondition_job(state["job"]["id"], PLAN))
    assert job["status"] == "RETURNED", (
        f"the terminal state is unchanged, got {job['status']}"
    )
    assert job["rebate_cents"] == 1800, (
        f"the settled rebate is not reversed, got {job['rebate_cents']}"
    )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 200, (
        "10 tools at 20 units each is the only charge on the wheel, got "
        f"{wheel['consumed_life_units']}"
    )
