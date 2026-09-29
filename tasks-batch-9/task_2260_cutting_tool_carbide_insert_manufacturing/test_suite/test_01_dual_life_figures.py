"""Two life figures computed from one set of measurements.

Machining trials persist an interpolated `rated_life_min` beside a projected
`projected_life_min`, and reconditioning jobs persist a measured
`life_extension_pct` beside a contractual `warranted_life_extension_pct`. In
both pairs the two numbers answer different questions and are expected to
disagree on identical inputs.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_credit_conserved,
    assert_machining_trial,
    assert_recondition_job,
)
from test_helpers.fixtures import OPERATOR_ONE, APP, PLAN
from prd_bench_local_runner.testing import validate_success


# ─── The trial wear curve: interpolated versus projected ─────────────────────

def test_trial_completion_persists_interpolated_and_projected_life_figures(api):
    """One wear curve yields two different persisted tool-life numbers.

    PRD §3.6: "Two tool-life figures are then computed from that single curve,
    and both are persisted, because the two disciplines that consume them ask
    different questions."

    PRD §3.6: "Walking consecutive pairs in ascending `minutes` order, the
    server takes the first pair whose earlier `vb_um` is strictly below the
    300-micrometre flank-wear limit and whose later `vb_um` is at or above it;
    within that pair the life is interpolated linearly, as the earlier entry's
    `minutes` plus the shortfall from the earlier `vb_um` to 300 divided by the
    wear increase across the pair and multiplied by the time increase across
    the pair, rounded half up to one decimal place, with `censored` set to
    false."

    PRD §3.6: "It uses only the last two entries of the curve, regardless of
    where the crossing occurred: the wear rate in micrometres per minute is the
    increase in `vb_um` across the final pair divided by the increase in
    `minutes` across it, and `projected_life_min` is the last entry's `minutes`
    plus the remaining wear allowance from the last `vb_um` to 300 divided by
    that rate, rounded half up to one decimal place."

    Design: Difficulty/dual_variant_calc/trial_life_rating_variant_divergence
    """
    state = fx.open_dossier(api, coated=False)
    trial = validate_success(
        api.create_machining_trial(
            f.trial_payload(state["dossier"]["id"], state["batch"]["id"]),
            OPERATOR_ONE,
        ),
        201,
    )

    response = api.complete_machining_trial(
        trial["id"], f.complete_trial_payload(), OPERATOR_ONE
    )

    completed = validate_success(response)
    assert_machining_trial(completed)
    assert completed["rated_life_min"] == 20.0, (
        "the crossing pair is 18 min at 290 um to 24 min at 320 um, so the "
        f"interpolated rating is 20.0, got {completed['rated_life_min']}"
    )
    assert completed["projected_life_min"] == 18.0, (
        "the final pair rises 20 um over 6 min, so the projection walks back "
        f"from 30 min to 18.0, got {completed['projected_life_min']}"
    )
    assert completed["rated_life_min"] - completed["projected_life_min"] == 2.0, (
        "the two figures must diverge by 2.0 minutes on this curve, got "
        f"{completed['rated_life_min']} and {completed['projected_life_min']}"
    )
    assert completed["censored"] is False, (
        "a curve that brackets the 300 um limit is not censored, got "
        f"{completed['censored']}"
    )


def test_trial_verdict_reads_the_interpolated_rating_and_not_the_projection(api):
    """The verdict passes on the rating even though the projection is at the floor.

    PRD §3.6: "The `verdict` is `PASS` when all three of the following hold:
    `censored` is false, `rated_life_min` is at least the required life for the
    class, and `measured_surface_ra_um` is at most the maximum for the class."

    PRD §3.6: "Only `rated_life_min` enters the verdict; `projected_life_min`
    never does."

    Design: Difficulty/dual_variant_calc/trial_life_rating_variant_divergence
    """
    state = fx.open_dossier(api, coated=False)
    trial = validate_success(
        api.create_machining_trial(
            f.trial_payload(state["dossier"]["id"], state["batch"]["id"]),
            OPERATOR_ONE,
        ),
        201,
    )

    response = api.complete_machining_trial(
        trial["id"], f.complete_trial_payload(), OPERATOR_ONE
    )

    completed = validate_success(response)
    assert completed["verdict"] == "PASS", (
        "a MEDIUM geometry requires 18.0 min and at most 1.6 um Ra; the trial "
        f"delivered 20.0 min at 1.20 um, so the verdict is PASS, got {completed['verdict']}"
    )
    assert completed["status"] == "COMPLETED", (
        f"closing out a RUNNING trial moves it to COMPLETED, got {completed['status']}"
    )


def test_dossier_composite_score_after_one_completed_trial(api):
    """The dossier aggregates rebuild from the single completed trial.

    PRD §3.6: "`completed_trial_count` becomes the number of trials on the
    dossier whose `status` is `COMPLETED`, of any verdict, and
    `passed_trial_count` the number of those whose `verdict` is `PASS`."

    PRD §3.6: "For each such trial, taken in ascending `created_at` order, a
    life ratio is formed as `rated_life_min` divided by the class's required
    life, capped at 2.0; a finish ratio is formed as the class's maximum
    roughness divided by `measured_surface_ra_um`, also capped at 2.0; and a
    per-trial subscore is 0.6 multiplied by the life ratio plus 0.4 multiplied
    by the finish ratio, **rounded half up to two decimal places at that
    point**."

    Design: Difficulty/dual_variant_calc/trial_life_rating_variant_divergence
    """
    state = fx.open_dossier(api, coated=False)
    dossier_id = state["dossier"]["id"]
    trial = validate_success(
        api.create_machining_trial(
            f.trial_payload(dossier_id, state["batch"]["id"]), OPERATOR_ONE
        ),
        201,
    )
    validate_success(
        api.complete_machining_trial(trial["id"], f.complete_trial_payload(), OPERATOR_ONE)
    )

    dossier = validate_success(api.get_qualification_dossier(dossier_id, APP))

    assert dossier["composite_score"] == 1.20, (
        "0.6 x (20.0 / 18.0) plus 0.4 x (1.6 / 1.20) rounds to 1.20, got "
        f"{dossier['composite_score']}"
    )
    assert dossier["completed_trial_count"] == 1, (
        f"one trial has been closed out, got {dossier['completed_trial_count']}"
    )
    assert dossier["passed_trial_count"] == 1, (
        f"that one trial passed, got {dossier['passed_trial_count']}"
    )


# ─── The reconditioning job: residual geometry versus pass history ───────────

def test_inspection_persists_residual_geometry_and_warranted_life_extension(api):
    """A measured 82.5 mm end mill carries 12.5 % measured beside 35.0 % warranted.

    PRD §3.9: "`remaining_regrinds` is the whole number of passes left,
    computed as `measured_length_mm` minus the product's
    `min_regrind_length_mm`, divided by the product's `regrind_step_mm`,
    rounded **down** to a whole number, and then floored at 0 so it is never
    negative."

    PRD §3.9: "`life_extension_pct` is 100 multiplied by `remaining_regrinds`,
    multiplied by the product's `regrind_step_mm`, divided by the product's
    `nominal_length_mm`, rounded half up to one decimal place."

    PRD §3.9: "`warranted_life_extension_pct` is 35.0 multiplied by 0.7 raised
    to the power of `regrind_pass_no` minus one, rounded half up to one decimal
    place — 35.0 on the first pass, 24.5 on the second, 17.2 on the third, and
    so on."

    PRD §3.9: "Because one figure reads the length and the other reads only the
    pass number, they disagree on identical inputs, and only the
    residual-geometry figure enters the money path or gates the
    refurbishment."

    Design: Difficulty/dual_variant_calc/recondition_life_extension_variant_divergence
    """
    state = fx.received_recondition_job(api)

    response = api.inspect_recondition_job(
        state["job"]["id"], f.inspect_job_payload(), PLAN
    )

    job = validate_success(response)
    assert_recondition_job(job)
    assert job["remaining_regrinds"] == 5, (
        "(82.5 - 70.0) / 2.5 floors to 5 remaining passes, got "
        f"{job['remaining_regrinds']}"
    )
    assert job["life_extension_pct"] == 12.5, (
        "100 x 5 x 2.5 / 100.0 is 12.5 percent, got " f"{job['life_extension_pct']}"
    )
    assert job["warranted_life_extension_pct"] == 35.0, (
        "35.0 x 0.7 ** 0 is 35.0 percent on the first pass, got "
        f"{job['warranted_life_extension_pct']}"
    )
    assert job["life_extension_pct"] != job["warranted_life_extension_pct"], (
        "the measured and contractual figures must disagree on this job, both "
        f"read {job['life_extension_pct']}"
    )
    assert job["scrap_recommended"] is False, (
        "82.5 mm is above the 70.0 mm floor, so no scrap is recommended, got "
        f"{job['scrap_recommended']}"
    )
    assert job["regrind_pass_no"] == 1, (
        f"a job with no predecessor is the first pass, got {job['regrind_pass_no']}"
    )
    assert job["status"] == "INSPECTED", (
        f"inspection moves the job RECEIVED to INSPECTED, got {job['status']}"
    )


def test_intake_reservation_moves_customer_credit_into_reserve(api):
    """Ten tools reserve 18500 cents out of a 50000-cent opening balance.

    PRD §3.9: "On success the job opens at `status` `RECEIVED`,
    `regrind_pass_no` is set to the length of the `predecessor_job_id` chain
    plus one, `reserved_credit_cents` is set to `units_received` multiplied by
    1850, the customer's `regrind_credit_cents` is reduced by that reservation
    while `reserved_credit_cents` rises by it, and the customer's `version`
    advances by 1."

    Design: Difficulty/dual_variant_calc/recondition_life_extension_variant_divergence
    """
    state = fx.received_recondition_job(api)
    validate_success(
        api.inspect_recondition_job(state["job"]["id"], f.inspect_job_payload(), PLAN)
    )

    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))

    assert customer["regrind_credit_cents"] == 31500, (
        "50000 less a 10 x 1850 reservation leaves 31500 available, got "
        f"{customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 18500, (
        f"10 x 1850 is held in reserve, got {customer['reserved_credit_cents']}"
    )
    assert_credit_conserved(customer, 50000)
