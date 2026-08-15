"""Production batch lifecycle: walk, invalid transitions, terminal states
(PRD §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_batch,
    create_production_batch,
    get_batch,
    setup_batch_in_state,
    setup_locked_formula,
    validate_error,
    validate_success,
)


def test_batch_hold_resume_cycle_and_initial_state(
    api, production_planner_headers, line_operator_headers, quality_analyst_headers
):
    """PRD §3.5: "A new batch starts in `SCHEDULED` with `actual_kg` at zero."
    PRD §3.5: "On the floor, a `LineOperator` starts the run, moving the batch from
    `RELEASED_FOR_PRODUCTION` to `IN_PROCESS`. A `QualityAnalyst` may place a
    running batch on hold (`IN_PROCESS` to `ON_HOLD`) and later resume it
    (`ON_HOLD` back to `IN_PROCESS`)."

    Design: Corner/state_machines/batch_hold_resume_cycle_and_initial_state
    """
    ctx = setup_locked_formula()
    batch = create_production_batch(
        ctx["formula"]["id"], planned_kg=600.0, line_id="LINE-H1",
        scheduled_start="2026-08-20T08:00:00Z",
    )
    assert_batch(batch)
    assert batch["status"] == "SCHEDULED"

    released = validate_success(api.release_batch(batch["id"], production_planner_headers))
    assert released["status"] == "RELEASED_FOR_PRODUCTION"
    started = validate_success(api.start_run(batch["id"], line_operator_headers))
    assert started["status"] == "IN_PROCESS"
    held = validate_success(api.hold_batch(batch["id"], quality_analyst_headers))
    assert held["status"] == "ON_HOLD"
    resumed = validate_success(api.resume_batch(batch["id"], quality_analyst_headers))
    assert resumed["status"] == "IN_PROCESS"


def test_batch_start_run_from_scheduled_fails(api, line_operator_headers):
    """PRD §3.5: "On the floor, a `LineOperator` starts the run, moving the batch
    from `RELEASED_FOR_PRODUCTION` to `IN_PROCESS`."
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/batch_start_run_from_scheduled_fails
    """
    ctx = setup_locked_formula()
    batch = create_production_batch(ctx["formula"]["id"], line_id="LINE-S1")
    assert batch["status"] == "SCHEDULED"
    resp = api.start_run(batch["id"], line_operator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_batch(batch["id"])["status"] == "SCHEDULED"


def test_batch_reject_from_on_hold_then_terminal(
    api, quality_analyst_headers, line_operator_headers
):
    """PRD §3.5: "Rejection is the terminal quality action on a held batch: moving
    from `ON_HOLD` to `REJECTED` cascades to the batch's lots, pushing every lot
    in `ACTIVE` to `QUARANTINED`."
    PRD §3.5: "`COMPLETED`, `REJECTED`, and `RECALLED` are the batch's terminal
    states."
    PRD §2.10: "a resource already in a terminal state accepts no further
    transitions at all and rejects them with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/batch_reject_from_on_hold_then_terminal
    """
    ctx = setup_batch_in_state("ON_HOLD", planned_kg=700.0, line_id="LINE-R1")
    assert ctx["batch"]["status"] == "ON_HOLD"

    rejected = validate_success(api.reject_batch(ctx["batch"]["id"], quality_analyst_headers))
    assert rejected["status"] == "REJECTED"

    resp = api.start_run(ctx["batch"]["id"], line_operator_headers)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)
