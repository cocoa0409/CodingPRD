"""Rows that carry two independent state dimensions, and states revisited twice.

A blend batch tracks a physical `stage` beside a metallurgical `qc_status`, and
quarantine moves one while provably leaving the other alone. A tool order can be
driven backwards out of `CONFIRMED` into `ENGINEERING_REVIEW` by the product's
supply dimension alone, and then confirmed a second time.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_units_conserved,
    assert_powder_blend_batch,
    assert_tool_order,
)
from test_helpers.fixtures import APP, APPROVER, PLAN
from prd_bench_local_runner.testing import validate_success


# ─── The blend batch: stage against qc_status ────────────────────────────────

def test_quarantine_moves_qc_status_and_leaves_the_stage_dimension_untouched(api):
    """A SINTERED, PASSED batch becomes SINTERED, QUARANTINED — the stage does not move.

    PRD §2.6: "Quarantining a batch moves `qc_status` from `PASSED` to
    `QUARANTINED` and deliberately leaves `stage` untouched — a `SINTERED` batch
    remains `SINTERED`."

    PRD §3.1: "The `qc_status` dimension moves `PASSED` → `QUARANTINED` while
    `stage` stays exactly where it was, and a four-hop cascade follows."

    PRD §3.1: "because the batch is quarantined, `remaining_units` is then
    driven to 0, so the value observable after the request is 0 regardless of
    how many trials were reversed."

    Design: Difficulty/non_linear_state_machine/batch_parallel_stage_and_qc_dimensions
    """
    state = fx.submitted_dossier(api, coated=False)

    response = api.quarantine_powder_blend_batch(
        state["batch"]["id"], f.quarantine_payload(), APPROVER
    )

    batch = validate_success(response)
    assert_powder_blend_batch(batch)
    assert batch["qc_status"] == "QUARANTINED", (
        f"the acceptance dimension moves to QUARANTINED, got {batch['qc_status']}"
    )
    assert batch["stage"] == "SINTERED", (
        f"the process dimension must stay at SINTERED, got {batch['stage']}"
    )
    assert batch["remaining_units"] == 0, (
        f"a quarantined batch has no issuable units left, got {batch['remaining_units']}"
    )
    assert batch["yield_pct"] == 90.00, (
        "100 x 180 / 200 is 90.00 and quarantine does not restate it, got "
        f"{batch['yield_pct']}"
    )
    assert batch["sintered_units"] == 180, (
        f"the furnace counts are unchanged, got {batch['sintered_units']}"
    )
    assert batch["pressed_units"] == 200, (
        f"the press count is unchanged, got {batch['pressed_units']}"
    )
    assert_batch_units_conserved(batch)


def test_quarantine_invalidates_every_trial_fed_by_the_batch(api):
    """Both completed trials drawn from the batch move to INVALIDATED.

    PRD §3.1: "Every machining trial fed by the batch whose `status` is
    `RUNNING` or `COMPLETED` moves to `INVALIDATED`, each returning its
    `units_consumed` to the batch; because the batch is quarantined,
    `remaining_units` is then driven to 0, so the value observable after the
    request is 0 regardless of how many trials were reversed."

    Design: Difficulty/non_linear_state_machine/batch_parallel_stage_and_qc_dimensions
    """
    state = fx.submitted_dossier(api, coated=False)
    validate_success(
        api.quarantine_powder_blend_batch(
            state["batch"]["id"], f.quarantine_payload(), APPROVER
        )
    )

    trial_one = validate_success(
        api.get_machining_trial(state["trial_one"]["id"], APP)
    )
    trial_two = validate_success(
        api.get_machining_trial(state["trial_two"]["id"], APP)
    )

    assert trial_one["status"] == "INVALIDATED", (
        f"the first trial's evidence is withdrawn, got {trial_one['status']}"
    )
    assert trial_two["status"] == "INVALIDATED", (
        f"the second trial's evidence is withdrawn, got {trial_two['status']}"
    )


def test_quarantine_returns_a_submitted_dossier_to_open(api):
    """The dossier reopens and loses its submitter, so a fresh submission is required.

    PRD §3.1: "And because the recomputed `passed_trial_count` may now sit
    below `required_trial_count`, any affected dossier whose `status` was
    `SUBMITTED` moves `SUBMITTED` → `OPEN` and has `submitted_by_user_id` set
    back to null, so a fresh submitter must own the resubmission."

    Design: Difficulty/non_linear_state_machine/batch_parallel_stage_and_qc_dimensions
    """
    state = fx.submitted_dossier(api, coated=False)
    assert state["dossier"]["status"] == "SUBMITTED", "precondition: dossier submitted"

    validate_success(
        api.quarantine_powder_blend_batch(
            state["batch"]["id"], f.quarantine_payload(), APPROVER
        )
    )

    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["status"] == "OPEN", (
        f"the dossier falls back out of SUBMITTED into OPEN, got {dossier['status']}"
    )
    assert dossier["submitted_by_user_id"] is None, (
        "the submitter is cleared so a fresh submitter must own the "
        f"resubmission, got {dossier['submitted_by_user_id']}"
    )


# ─── The tool order: CONFIRMED visited twice ─────────────────────────────────

def test_supply_status_move_drives_a_confirmed_order_back_to_engineering_review(api):
    """Moving STOCKED to MAKE_TO_ORDER reverses a confirmation the order already had.

    PRD §3.5: "One of these moves carries a cascade: `STOCKED` →
    `MAKE_TO_ORDER`, whether requested directly or triggered as hop 3 of an
    upstream revision, moves every `CONFIRMED` order on the product to
    `ENGINEERING_REVIEW` with `requires_reconfirmation` set to true."

    PRD §3.5: "Every supply move advances the product's `version` by 1, and
    none of them touches `release_status`."

    Design: Difficulty/non_linear_state_machine/order_confirmed_returns_to_engineering_review_cycle
    """
    state = fx.confirmed_order(api)
    assert state["order"]["status"] == "CONFIRMED", "precondition: order confirmed"

    response = api.set_product_supply_status(
        state["product"]["id"], f.set_supply_status_payload("MAKE_TO_ORDER"), PLAN
    )

    product = validate_success(response)
    assert product["supply_status"] == "MAKE_TO_ORDER", (
        f"the requested supply dimension is set, got {product['supply_status']}"
    )
    assert product["release_status"] == "RELEASED", (
        f"the release dimension is untouched by a supply move, got {product['release_status']}"
    )
    order = validate_success(api.get_tool_order(state["order"]["id"], APP))
    assert order["status"] == "ENGINEERING_REVIEW", (
        "a CONFIRMED order is pushed back into a state it already passed "
        f"through, got {order['status']}"
    )
    assert order["requires_reconfirmation"] is True, (
        f"the order is flagged for reconfirmation, got {order['requires_reconfirmation']}"
    )


def test_order_confirms_a_second_time_and_clears_the_reconfirmation_flag(api):
    """The order reaches CONFIRMED twice, and re-confirmation does not re-price it.

    PRD §3.8: "On success the order moves to `CONFIRMED`,
    `requires_reconfirmation` is set to false, and the order's `version`
    advances by 1."

    PRD §3.8: "An order pushed back to `ENGINEERING_REVIEW` by an upstream
    revision therefore cannot be re-confirmed until the product has been
    repinned and released again — the cycle `CONFIRMED` → `ENGINEERING_REVIEW` →
    `CONFIRMED` closes only when the engineering chain is whole."

    Design: Difficulty/non_linear_state_machine/order_confirmed_returns_to_engineering_review_cycle
    """
    state = fx.confirmed_order(api)
    validate_success(
        api.set_product_supply_status(
            state["product"]["id"], f.set_supply_status_payload("MAKE_TO_ORDER"), PLAN
        )
    )

    response = api.confirm_tool_order(state["order"]["id"], PLAN)

    order = validate_success(response)
    assert_tool_order(order)
    assert order["status"] == "CONFIRMED", (
        f"the engineering chain is whole, so the order re-confirms, got {order['status']}"
    )
    assert order["requires_reconfirmation"] is False, (
        f"confirmation clears the flag, got {order['requires_reconfirmation']}"
    )
    assert order["total_price_cents"] == 448500, (
        "pricing happens at submission, so re-confirmation leaves the total "
        f"alone, got {order['total_price_cents']}"
    )
