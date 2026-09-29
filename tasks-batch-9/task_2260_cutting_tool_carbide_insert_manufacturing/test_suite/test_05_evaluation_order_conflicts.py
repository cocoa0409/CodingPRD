"""Requests that violate two rules at once, and cross-entity admission gates.

The evaluation ladder is fixed and ascending, so when a single request breaks
two rules only the earlier one is ever reported. These tests set up both
violations deliberately and pin which error id comes back. The last pair checks
an admission gate that reads a different entity entirely.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_no_row_with_code, assert_wheel_life_conserved
from test_helpers.fixtures import APP, MET, OPERATOR_ONE, PLAN
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Subject state before customer fiscal state ──────────────────────────────

def test_resubmitting_a_held_order_reports_the_state_guard_not_the_credit_hold(api):
    """An ON_HOLD order under a CREDIT_HOLD account breaks two rules; the state one wins.

    PRD §2.11: "12. **Subject state permits the transition.** The addressed
    entity is not in a state from which the requested transition is declared →
    the entity's own invalid-state code: `ERR_INVALID_GRADE_STATE`,
    `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_GEOMETRY_STATE`,
    `ERR_INVALID_COATING_RUN_STATE`, `ERR_INVALID_WHEEL_STATE`,
    `ERR_INVALID_GRINDING_RUN_STATE`, `ERR_INVALID_PRODUCT_STATE`,
    `ERR_INVALID_DOSSIER_STATE`, `ERR_INVALID_TRIAL_STATE`,
    `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_JOB_STATE` or
    `ERR_INVALID_CUSTOMER_STATE`. Applies to every action endpoint."

    PRD §2.11: "42. **Customer account orderable.** →
    `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402) when the account is on credit hold and
    `ERR_CUSTOMER_CLOSED` (HTTP 409) when it is closed, on order submission and
    reconditioning-job intake."

    PRD §2.11: "The system evaluates checks in a fixed ascending order and
    reports the **first** violation it finds; later checks are not evaluated and
    their codes are never returned for that request."

    Design: Difficulty/priority_pair_validation_conflict/order_state_beats_credit_hold
    """
    state = fx.submitted_order(api)
    validate_success(
        api.create_credit_adjustment(
            state["customer"]["id"], f.credit_adjustment_payload(-60000), PLAN
        )
    )

    response = api.submit_tool_order(state["order"]["id"], APP)

    body = validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE, 409)
    assert body["error_id"] != ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value, (
        "the fiscal check sits at priority 42 and must never be reached from an "
        "order that is not in a submittable state"
    )


def test_the_rejected_resubmission_leaves_the_order_and_the_account_untouched(api):
    """A rejected submission changes nothing on either row.

    PRD §3.8: "Both require the order to be `DRAFT` and the customer's
    `account_status` to be `ACTIVE` — a `CREDIT_HOLD` account is rejected with
    `ERR_CUSTOMER_CREDIT_HOLD` and a `CLOSED` one with `ERR_CUSTOMER_CLOSED`."

    PRD §3.8: "If the resulting balance is below 0 while the account is
    `ACTIVE`, `account_status` moves `ACTIVE` → `CREDIT_HOLD`, and because the
    account went on hold, every order of that customer in `SUBMITTED` or
    `ENGINEERING_REVIEW` moves to `ON_HOLD` with `hold_reason` set to
    `CREDIT_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/order_state_beats_credit_hold
    """
    state = fx.submitted_order(api)
    validate_success(
        api.create_credit_adjustment(
            state["customer"]["id"], f.credit_adjustment_payload(-60000), PLAN
        )
    )

    validate_error(
        api.submit_tool_order(state["order"]["id"], APP),
        ApiErrorId.ERR_INVALID_ORDER_STATE,
        409,
    )

    order = validate_success(api.get_tool_order(state["order"]["id"], APP))
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert order["status"] == "ON_HOLD", (
        f"the order stays parked, got {order['status']}"
    )
    assert customer["account_status"] == "CREDIT_HOLD", (
        f"the account stays on hold, got {customer['account_status']}"
    )


# ─── Wheel safety before the cell setup buffer ───────────────────────────────

def test_booking_a_worn_wheel_inside_the_setup_buffer_reports_the_wheel_check(api):
    """A run on a DRESSING wheel 44 minutes after its neighbour reports the wheel.

    PRD §2.11: "15. **Wheel not awaiting dressing.** →
    `ERR_WHEEL_REQUIRES_DRESSING`, on grinding-run creation and reconditioning
    refurbish."

    PRD §2.11: "29. **Cell setup buffer.** → `ERR_CELL_BUFFER_CONFLICT`, on
    grinding-run creation."

    PRD §3.4: "a wheel at `DRESSING` is rejected with
    `ERR_WHEEL_REQUIRES_DRESSING`, because it has fallen below its dressing
    threshold and has not yet been restored."

    Design: Difficulty/priority_pair_validation_conflict/wheel_safety_beats_cell_buffer
    """
    state = fx.completed_grinding_run(api)
    assert state["wheel"]["status"] == "DRESSING", "precondition: the wheel is worn"

    response = api.create_grinding_run(
        f.grinding_run_payload(
            state["wheel"]["id"],
            state["product"]["id"],
            window_start="2026-08-12T10:44:00Z",
            window_end="2026-08-12T12:00:00Z",
            planned_units=5,
        ),
        PLAN,
    )

    body = validate_error(response, ApiErrorId.ERR_WHEEL_REQUIRES_DRESSING, 409)
    assert body["error_id"] != ApiErrorId.ERR_CELL_BUFFER_CONFLICT.value, (
        "the 44-minute gap also breaks the 45-minute buffer, but that check "
        "sits at priority 29 and must never be reached"
    )


def test_the_rejected_booking_creates_no_run_and_leaves_the_wheel_and_grading_intact(api):
    """The wheel keeps its charged life and grading, and no second run row appears.

    PRD §3.4: "Then the wheel is charged: the run's own `consumed_life_units` is
    set to `produced_units` plus `scrap_units`, multiplied by the ground
    product's `grind_units_per_tool`, and that figure is added to the wheel's
    `consumed_life_units`."

    PRD §3.4: "Because the charge may push the wheel's `remaining_life_units`
    below the 150-unit dressing threshold, a wheel at `AVAILABLE` whose
    remaining life is now under 150 moves `AVAILABLE` → `DRESSING` in the same
    request."

    PRD §3.4: "The achieved `tolerance_class` is graded from the absolute value
    of `measured_diameter_dev_um`: at most 5.0 micrometres is `IT6`; otherwise
    at most 12.0 is `IT7`; otherwise at most 25.0 is `IT8`; anything larger is
    `OUT_OF_TOLERANCE`."

    Design: Difficulty/priority_pair_validation_conflict/wheel_safety_beats_cell_buffer
    """
    state = fx.completed_grinding_run(api)
    validate_error(
        api.create_grinding_run(
            f.grinding_run_payload(
                state["wheel"]["id"],
                state["product"]["id"],
                window_start="2026-08-12T10:44:00Z",
                window_end="2026-08-12T12:00:00Z",
                planned_units=5,
            ),
            PLAN,
        ),
        ApiErrorId.ERR_WHEEL_REQUIRES_DRESSING,
        409,
    )

    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["remaining_life_units"] == 140, (
        "1000 less a (40 + 3) x 20 charge leaves 140, got "
        f"{wheel['remaining_life_units']}"
    )
    assert wheel["status"] == "DRESSING", (
        f"140 is under the 150-unit threshold, got {wheel['status']}"
    )
    assert_wheel_life_conserved(wheel)
    run = validate_success(api.get_grinding_run(state["run"]["id"], PLAN))
    assert run["tolerance_class"] == "IT6", (
        f"a 4.5 um deviation is inside the 5.0 um IT6 band, got {run['tolerance_class']}"
    )
    rows, _meta = validate_paginated(api.list_grinding_runs(PLAN))
    assert len(rows) == 1, (
        f"the rejected booking must not have created a row, got {len(rows)} runs"
    )


# ─── Trial admission reads the supplying batch's QC dimension ────────────────

def test_trial_creation_against_a_failed_batch_is_rejected_and_draws_no_units(api):
    """The identical trial request is refused because the batch failed sintering QC.

    PRD §2.11: "16. **Trial material QC passed.** →
    `ERR_BATCH_QC_NOT_PASSED`, on trial creation."

    PRD §3.6: "The supplying batch must have `qc_status` `PASSED` and `stage`
    `SINTERED` or `CONSUMED`, otherwise `ERR_BATCH_QC_NOT_PASSED`, and
    `units_consumed` must not exceed the batch's `remaining_units`, otherwise
    `ERR_INSUFFICIENT_BATCH_UNITS`."

    Design: Difficulty/cross_entity_state_dependency/trial_create_requires_batch_qc_passed
    """
    state = fx.open_dossier(api, coated=False)
    failed = fx.failed_batch(api, state["grade"]["id"])
    assert failed["qc_status"] == "FAILED", "precondition: the batch failed QC"

    response = api.create_machining_trial(
        f.trial_payload(state["dossier"]["id"], failed["id"], trial_code="TRL-BAD"),
        OPERATOR_ONE,
    )

    validate_error(response, ApiErrorId.ERR_BATCH_QC_NOT_PASSED, 409)
    batch = validate_success(api.get_powder_blend_batch(failed["id"], MET))
    assert batch["remaining_units"] == 170, (
        "a rejected request draws no test tools, got "
        f"{batch['remaining_units']}"
    )
    rows, _meta = validate_paginated(api.list_machining_trials(APP))
    assert_no_row_with_code(rows, "trial_code", "TRL-BAD")


def test_trial_creation_against_the_passed_batch_succeeds_and_draws_its_units(api):
    """The same request against the PASSED batch opens a RUNNING trial.

    PRD §3.6: "On creation the trial opens at `status` `RUNNING`, records
    `operator_user_id` from the calling `X-User-ID`, reduces the batch's
    `remaining_units` by `units_consumed`, and — when that reduction brings
    `remaining_units` to 0 — advances the batch's `stage` to `CONSUMED`."

    PRD §3.6: "The dossier opens at `status` `OPEN` with
    `completed_trial_count` and `passed_trial_count` at 0 and `composite_score`
    null."

    Design: Difficulty/cross_entity_state_dependency/trial_create_requires_batch_qc_passed
    """
    state = fx.open_dossier(api, coated=False)
    fx.failed_batch(api, state["grade"]["id"])

    response = api.create_machining_trial(
        f.trial_payload(
            state["dossier"]["id"], state["batch"]["id"], trial_code="TRL-GOOD"
        ),
        OPERATOR_ONE,
    )

    trial = validate_success(response, 201)
    assert trial["status"] == "RUNNING", (
        f"an admitted trial opens at RUNNING, got {trial['status']}"
    )
    batch = validate_success(api.get_powder_blend_batch(state["batch"]["id"], MET))
    assert batch["remaining_units"] == 160, (
        f"180 less the 20 tools drawn is 160, got {batch['remaining_units']}"
    )
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["completed_trial_count"] == 0, (
        "a RUNNING trial has not been closed out, got "
        f"{dossier['completed_trial_count']}"
    )
