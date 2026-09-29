"""Quantities that must balance exactly across a forward act and its reversal.

Abrasive wheel life splits into a consumed part and a remaining part that must
always add back to the wheel's opening figure, and voiding a completed run has to
give back exactly what the completion charged. Customer reconditioning credit
splits into an available part and a reserved part that must always add back to
the opening balance, and scrapping a job has to release the reservation without
paying anything out.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_credit_conserved,
    assert_grinding_run,
    assert_grinding_wheel,
    assert_recondition_job,
    assert_wheel_life_conserved,
)
from test_helpers.fixtures import APPROVER, PLAN
from prd_bench_local_runner.testing import validate_success


# ─── Abrasive wheel life across a completion and its void ────────────────────

def test_completing_a_run_charges_the_wheel_and_keeps_the_life_split_balanced(api):
    """43 tools at 20 units each charge 860, leaving 140 of a 1000-unit wheel.

    PRD §3.4: "Then the wheel is charged: the run's own `consumed_life_units` is
    set to `produced_units` plus `scrap_units`, multiplied by the ground
    product's `grind_units_per_tool`, and that figure is added to the wheel's
    `consumed_life_units`."

    PRD §3.4: "Throughout the wheel's life, `remaining_life_units` is
    `initial_life_units` minus `consumed_life_units`, and `consumed_life_units`
    is the total charged to the wheel since its last dressing by completed
    grinding runs and by reconditioning refurbishments."

    PRD §3.4: "Because the charge may push the wheel's `remaining_life_units`
    below the 150-unit dressing threshold, a wheel at `AVAILABLE` whose remaining
    life is now under 150 moves `AVAILABLE` → `DRESSING` in the same request."

    PRD §3.4: "Note that the per-run charge is *retained* on the run rather than
    merely accumulated on the wheel, and the reason is the void path below."

    Design: Difficulty/compensating_invariant/wheel_life_conserved_across_complete_and_void
    """
    state = fx.completed_grinding_run(api)

    run = state["run"]
    wheel = state["wheel"]
    assert_grinding_run(run)
    assert_grinding_wheel(wheel)
    assert run["consumed_life_units"] == 860, (
        "40 good plus 3 scrapped tools at 20 units each is a charge of 860, "
        f"retained on the run, got {run['consumed_life_units']}"
    )
    assert run["tolerance_class"] == "IT6", (
        f"a 4.5 um deviation is inside the 5.0 um IT6 band, got {run['tolerance_class']}"
    )
    assert wheel["consumed_life_units"] == 860, (
        f"the run's charge lands on the wheel, got {wheel['consumed_life_units']}"
    )
    assert wheel["remaining_life_units"] == 140, (
        f"1000 less 860 leaves 140, got {wheel['remaining_life_units']}"
    )
    assert wheel["status"] == "DRESSING", (
        f"140 is under the 150-unit threshold, got {wheel['status']}"
    )
    assert_wheel_life_conserved(wheel)


def test_voiding_the_completed_run_gives_back_exactly_what_it_charged(api):
    """The void subtracts the stored 860 and zeroes the run's own figures.

    PRD §3.4: "Voiding a `COMPLETED` run — the move `COMPLETED` → `VOIDED` — is a
    compensating action: the run's stored `consumed_life_units` is subtracted back
    from the wheel's `consumed_life_units` and the run's own figure is then set to
    0, `produced_units` and `scrap_units` are reset to 0, and
    `measured_diameter_dev_um` and `tolerance_class` are set to null, leaving the
    wheel's remaining life exactly as it stood before the completion."

    Design: Difficulty/compensating_invariant/wheel_life_conserved_across_complete_and_void
    """
    state = fx.completed_grinding_run(api)

    response = api.void_grinding_run(
        state["run"]["id"], f.void_grinding_run_payload(), APPROVER
    )

    run = validate_success(response)
    assert run["status"] == "VOIDED", (
        f"a completed run voids to VOIDED, got {run['status']}"
    )
    assert run["consumed_life_units"] == 0, (
        f"the run's own charge is zeroed once it has been given back, got {run['consumed_life_units']}"
    )
    assert run["produced_units"] == 0, (
        f"the production counts are reset, got {run['produced_units']}"
    )
    assert run["scrap_units"] == 0, (
        f"the scrap count is reset, got {run['scrap_units']}"
    )
    assert run["tolerance_class"] is None, (
        f"the achieved grade is withdrawn with the measurement, got {run['tolerance_class']}"
    )


def test_the_void_restores_the_wheel_exactly_and_is_not_counted_as_a_dressing(api):
    """The wheel returns to 0 consumed and 1000 remaining, with dress_count still 0.

    PRD §3.4: "If the wheel had dropped to `DRESSING` and the reversal lifts
    `remaining_life_units` back to 150 or above, the wheel moves `DRESSING` →
    `AVAILABLE`, and — this is the important asymmetry — `dress_count` is *not*
    changed, because no abrasive was actually dressed."

    PRD §3.4: "A new wheel opens at `status` `AVAILABLE`, with
    `consumed_life_units` at 0, `remaining_life_units` equal to
    `initial_life_units`, and `dress_count` at 0."

    Design: Difficulty/compensating_invariant/wheel_life_conserved_across_complete_and_void
    """
    state = fx.completed_grinding_run(api)
    validate_success(
        api.void_grinding_run(
            state["run"]["id"], f.void_grinding_run_payload(), APPROVER
        )
    )

    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))

    assert wheel["consumed_life_units"] == 0, (
        f"the 860-unit charge is fully reversed, got {wheel['consumed_life_units']}"
    )
    assert wheel["remaining_life_units"] == 1000, (
        "the wheel stands exactly as it did before the completion, got "
        f"{wheel['remaining_life_units']}"
    )
    assert_wheel_life_conserved(wheel)
    assert wheel["status"] == "AVAILABLE", (
        f"the reversal lifts the wheel back over the threshold, got {wheel['status']}"
    )
    assert wheel["dress_count"] == 0, (
        f"no abrasive was dressed, so the counter must not move, got {wheel['dress_count']}"
    )


# ─── Reconditioning credit across an intake and its scrap ────────────────────

def _job_measured_below_the_regrind_floor(api) -> dict:
    """A first-pass job of 10 tools inspected at 68.0 mm, under the 70.0 mm floor."""
    return fx.inspected_recondition_job(
        api,
        inspect_overrides={"measured_length_mm": 68.0, "measured_corner_wear_um": 400},
    )


def test_inspection_below_the_regrind_floor_leaves_no_passes_and_recommends_scrap(api):
    """68.0 mm against a 70.0 mm floor floors the pass count at 0 and asks for scrap.

    PRD §3.9: "`remaining_regrinds` is the whole number of passes left, computed
    as `measured_length_mm` minus the product's `min_regrind_length_mm`, divided
    by the product's `regrind_step_mm`, rounded **down** to a whole number, and
    then floored at 0 so it is never negative."

    PRD §3.9: "And `scrap_recommended` is true exactly when `measured_length_mm`
    is strictly below the product's `min_regrind_length_mm`."

    PRD §3.9: "`warranted_life_extension_pct` is 35.0 multiplied by 0.7 raised to
    the power of `regrind_pass_no` minus one, rounded half up to one decimal
    place — 35.0 on the first pass, 24.5 on the second, 17.2 on the third, and so
    on."

    Design: Difficulty/compensating_invariant/regrind_credit_conserved_across_intake_and_scrap
    """
    state = _job_measured_below_the_regrind_floor(api)

    job = state["job"]
    assert_recondition_job(job)
    assert job["remaining_regrinds"] == 0, (
        "68.0 less 70.0 over 2.5 is negative and is floored at 0, got "
        f"{job['remaining_regrinds']}"
    )
    assert job["life_extension_pct"] == 0.0, (
        f"no remaining passes recovers no life, got {job['life_extension_pct']}"
    )
    assert job["scrap_recommended"] is True, (
        "68.0 mm is strictly below the 70.0 mm floor, got "
        f"{job['scrap_recommended']}"
    )
    assert job["warranted_life_extension_pct"] == 35.0, (
        "the contractual figure ignores the measurement and reads only the first "
        f"pass, got {job['warranted_life_extension_pct']}"
    )


def test_scrapping_the_job_refunds_the_reservation_and_restores_the_credit_split(api):
    """The 18500-cent reservation goes back to available, and the sum stays 50000.

    PRD §3.9: "On success the job opens at `status` `RECEIVED`, `regrind_pass_no`
    is set to the length of the `predecessor_job_id` chain plus one,
    `reserved_credit_cents` is set to `units_received` multiplied by 1850, the
    customer's `regrind_credit_cents` is reduced by that reservation while
    `reserved_credit_cents` rises by it, and the customer's `version` advances by
    1."

    PRD §3.9: "Its side-effect set is deliberately the mirror image of the return
    path: the intake reservation is **refunded in full** — the job's
    `reserved_credit_cents` is added back to the customer's
    `regrind_credit_cents`, the customer's `reserved_credit_cents` is reduced by
    it, and the job's `reserved_credit_cents` is set to 0 —"

    Design: Difficulty/compensating_invariant/regrind_credit_conserved_across_intake_and_scrap
    """
    state = _job_measured_below_the_regrind_floor(api)
    at_intake = state["customer"]
    assert at_intake["regrind_credit_cents"] == 31500, (
        "at intake 50000 less a 10 x 1850 reservation leaves 31500 available, got "
        f"{at_intake['regrind_credit_cents']}"
    )
    assert at_intake["reserved_credit_cents"] == 18500, (
        f"at intake 18500 is held in reserve, got {at_intake['reserved_credit_cents']}"
    )
    assert_credit_conserved(at_intake, 50000)

    validate_success(
        api.scrap_recondition_job(state["job"]["id"], f.scrap_job_payload(), APPROVER)
    )

    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["regrind_credit_cents"] == 50000, (
        f"the reservation is refunded in full, got {customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 0, (
        f"nothing is held in reserve any more, got {customer['reserved_credit_cents']}"
    )
    assert_credit_conserved(customer, 50000)


def test_the_scrap_refund_is_a_release_rather_than_a_rebate_payment(api):
    """Scrapping pays nothing out: the balance returns to 50000, not to 59000.

    PRD §3.9: "while `units_returned` and `rebate_cents` are both set to 0 and
    no rebate is paid."

    PRD §3.9: "Because a scrap refund merely returns money the customer had
    already paid in, it cannot by itself lift a credit hold that an adjustment
    created; only a credit adjustment or a job return restores an account to
    `ACTIVE`."

    Design: Difficulty/compensating_invariant/regrind_credit_conserved_across_intake_and_scrap
    """
    state = _job_measured_below_the_regrind_floor(api)

    response = api.scrap_recondition_job(
        state["job"]["id"], f.scrap_job_payload(), APPROVER
    )

    job = validate_success(response)
    assert job["status"] == "SCRAPPED", (
        f"an inspected job may be scrapped, got {job['status']}"
    )
    assert job["reserved_credit_cents"] == 0, (
        f"the job holds no reservation once it is refunded, got {job['reserved_credit_cents']}"
    )
    assert job["units_returned"] == 0, (
        f"nothing is handed back to the customer, got {job['units_returned']}"
    )
    assert job["rebate_cents"] == 0, (
        f"no rebate is paid on a scrapped job, got {job['rebate_cents']}"
    )
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["regrind_credit_cents"] != 59000, (
        "59000 is the balance produced by treating the release as a payment on "
        "top of the refund"
    )
