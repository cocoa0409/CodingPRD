"""Derived figures at their pinned constants, boundaries and rounding order.

The sintering window, the tolerance ladder and the volume-discount tiers are all
inclusive at their edges, so each is exercised one step either side of the edge.
The lead time reads current status rather than pinned revisions, the two tool-life
figures diverge on a censored curve, and both the composite score and the order
price fix the point at which rounding happens.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_units_conserved,
    assert_coating_recipe,
    assert_credit_conserved,
    assert_machining_trial,
    assert_recondition_job,
    assert_tool_order,
    assert_total_is_per_unit_times_quantity,
    assert_wheel_life_conserved,
)
from test_helpers.fixtures import APP, COAT, GEO, MET, OPERATOR_ONE, OPERATOR_TWO, PLAN
from prd_bench_local_runner.testing import validate_success


# ─── The sintering QC window ────────────────────────────────────────────────

def _two_pressed_batches(api) -> dict:
    """One grade targeting 1600 HV with two batches of 200 green compacts each."""
    grade = fx.carbide_grade(api)
    batches = {}
    for key, code in (("a", "BLD-A"), ("b", "BLD-B")):
        batch = validate_success(
            api.create_powder_blend_batch(
                f.powder_blend_batch_payload(grade["id"], batch_code=code), MET
            ),
            201,
        )
        validate_success(
            api.press_powder_blend_batch(batch["id"], f.press_payload(), MET)
        )
        batches[key] = batch
    return {"grade": grade, **batches}


def test_a_hardness_deviation_of_exactly_seventy_five_still_passes_qc(api):
    """1525 HV against a 1600 HV target is 75 out, which is inside the window.

    PRD §3.1: "First, `yield_pct` is computed as 100 multiplied by
    `sintered_units` divided by `pressed_units`, rounded half up to two decimal
    places."

    PRD §3.1: "The batch's `qc_status` then moves from `PENDING` to `PASSED` when
    all three of the following hold: `measured_density_gcc` is at least 14.35; the
    absolute difference between `measured_hardness_hv` and the `hardness_hv` target
    of the batch's grade, read at the revision the batch pinned, is at most 75; and
    `yield_pct` is at least 85.00."

    PRD §3.1: "In both outcomes `remaining_units` is set to `sintered_units`."

    Design: Corner/calculations/sinter_hardness_window_is_symmetric_around_the_grade_target
    """
    state = _two_pressed_batches(api)

    response = api.sinter_powder_blend_batch(
        state["a"]["id"],
        f.sinter_payload(measured_density_gcc=14.50, measured_hardness_hv=1525),
        MET,
    )

    batch = validate_success(response)
    assert batch["qc_status"] == "PASSED", (
        "the deviation is exactly the permitted 75 HV and the other two gates "
        f"clear comfortably, got {batch['qc_status']}"
    )
    assert batch["yield_pct"] == 90.00, (
        f"180 good out of 200 pressed is 90.00 percent, got {batch['yield_pct']}"
    )
    assert batch["stage"] == "SINTERED", (
        f"the process dimension advances regardless of QC, got {batch['stage']}"
    )
    assert batch["remaining_units"] == 180, (
        f"the good units are what remains, got {batch['remaining_units']}"
    )
    assert_batch_units_conserved(batch)


def test_a_hardness_deviation_of_seventy_six_fails_qc_on_that_gate_alone(api):
    """1524 HV is 76 out, and the identical density and yield make hardness the cause.

    PRD §3.1: "All three comparisons are inclusive at the boundary, so a density
    of exactly 14.35, a hardness deviation of exactly 75 and a yield of exactly
    85.00 all pass. If any one of the three fails, `qc_status` moves from
    `PENDING` to `FAILED` instead, and the batch is permanently ineligible as a
    source of trial tools — there is no re-test path out of `FAILED`."

    PRD §3.1: "In both outcomes `remaining_units` is set to `sintered_units`."

    Design: Corner/calculations/sinter_hardness_window_is_symmetric_around_the_grade_target
    """
    state = _two_pressed_batches(api)
    passing = validate_success(
        api.sinter_powder_blend_batch(
            state["a"]["id"],
            f.sinter_payload(measured_density_gcc=14.50, measured_hardness_hv=1525),
            MET,
        )
    )

    response = api.sinter_powder_blend_batch(
        state["b"]["id"],
        f.sinter_payload(measured_density_gcc=14.50, measured_hardness_hv=1524),
        MET,
    )

    batch = validate_success(response)
    assert batch["qc_status"] == "FAILED", (
        "one HV further from the target than the window allows fails the batch, "
        f"got {batch['qc_status']}"
    )
    assert batch["yield_pct"] == passing["yield_pct"] == 90.00, (
        "the two batches share an identical yield, so only the hardness can "
        f"explain the difference, got {batch['yield_pct']}"
    )
    assert batch["stage"] == "SINTERED", (
        f"a failed batch still reached the far side of the furnace, got {batch['stage']}"
    )
    assert batch["remaining_units"] == 180, (
        f"the good units are recorded on either outcome, got {batch['remaining_units']}"
    )


# ─── The coating evidence pool and its revision key ─────────────────────────

def test_revising_the_layer_stack_empties_the_recipe_evidence_pool(api):
    """A proven recipe returns to unproven the moment its stack advances a revision.

    PRD §3.3: "That pool consists of the recipe's completed runs whose
    `pinned_recipe_revision` equals the recipe's current `revision` — no other run
    counts."

    PRD §3.3: "Revising a recipe replaces `layers` and records a `revision_note`.
    Because `revision` advances, the completed-run pool is emptied at a stroke:
    `total_thickness_um` is recomputed from the new stack, `adhesion_class` returns
    to null and `is_validated` returns to false, and the recipe must be proven
    again in the chamber."

    Design: Corner/calculations/recipe_validation_state_resets_when_the_layer_stack_is_revised
    """
    proven = fx.validated_pvd_recipe(api)
    before = proven["recipe"]
    assert before["is_validated"] is True, "precondition: the recipe is proven"
    assert before["adhesion_class"] == 2, "precondition: the pool's best class is 2"
    assert before["total_thickness_um"] == 3.00, "precondition: a 3.00 um stack"

    response = api.revise_coating_recipe(
        before["id"], f.revise_recipe_payload(), COAT
    )

    recipe = validate_success(response)
    assert_coating_recipe(recipe)
    assert recipe["revision"] == 2, (
        f"the revision advances by 1, got {recipe['revision']}"
    )
    assert recipe["total_thickness_um"] == 3.50, (
        f"2.5 plus 1.0 is a 3.50 um stack, got {recipe['total_thickness_um']}"
    )
    assert len(recipe["layers"]) == 2, (
        f"the new stack holds two entries, got {len(recipe['layers'])}"
    )
    assert recipe["is_validated"] is False, (
        "the completed run was proof of the old stack only, got "
        f"{recipe['is_validated']}"
    )
    assert recipe["adhesion_class"] is None, (
        f"an empty pool leaves the class null, got {recipe['adhesion_class']}"
    )


def test_the_orphaned_run_is_untouched_and_still_pinned_to_the_old_revision(api):
    """The evidence is not deleted; it simply no longer answers for the new stack.

    PRD §3.3: "The run opens at `status` `SCHEDULED` and captures
    `pinned_recipe_revision` from the recipe's current `revision`, which is what
    later ties the run's measurements to a specific layer stack rather than to
    whatever the recipe has since become."

    PRD §3.3: "That pool consists of the recipe's completed runs whose
    `pinned_recipe_revision` equals the recipe's current `revision` — no other run
    counts."

    Design: Corner/calculations/recipe_validation_state_resets_when_the_layer_stack_is_revised
    """
    proven = fx.validated_pvd_recipe(api)
    validate_success(
        api.revise_coating_recipe(proven["recipe"]["id"], f.revise_recipe_payload(), COAT)
    )

    run = validate_success(api.get_coating_run(proven["coating_run"]["id"], COAT))

    assert run["status"] == "COMPLETED", (
        f"the run itself is not rolled back, got {run['status']}"
    )
    assert run["pinned_recipe_revision"] == 1, (
        "the run answers for the stack it was deposited under, got "
        f"{run['pinned_recipe_revision']}"
    )
    assert run["adhesion_hf_class"] == 2, (
        f"its measurement stands as recorded, got {run['adhesion_hf_class']}"
    )


# ─── The tolerance ladder ───────────────────────────────────────────────────

def _four_completed_runs_at_the_band_edges(api) -> dict:
    """Four one-tool runs closed out at 5.0, 5.1, 12.0 and 25.1 um of deviation.

    The four bookings are spread over the two cells and two hour-long windows an
    hour apart, so neither exclusive occupancy nor the 45-minute setup buffer
    interferes with the classification under test.
    """
    state = fx.endmill_product(api)
    state["wheel"] = fx.grinding_wheel(api, wheel_code="WH-3", initial_life_units=100000)
    windows = {
        "it6": ("CELL_A", "06:00:00", "07:00:00"),
        "it7_low": ("CELL_B", "06:00:00", "07:00:00"),
        "it7_high": ("CELL_A", "08:00:00", "09:00:00"),
        "out": ("CELL_B", "08:00:00", "09:00:00"),
    }
    booked = {}
    for key, (cell, start, end) in windows.items():
        booked[key] = validate_success(
            api.create_grinding_run(
                f.grinding_run_payload(
                    state["wheel"]["id"],
                    state["product"]["id"],
                    cell_id=cell,
                    window_start=f"2026-08-14T{start}Z",
                    window_end=f"2026-08-14T{end}Z",
                    planned_units=1,
                ),
                PLAN,
            ),
            201,
        )
    fx.advance_clock(api, "2026-08-14T09:00:00Z")
    deviations = {"it6": 5.0, "it7_low": 5.1, "it7_high": 12.0, "out": 25.1}
    state["runs"] = {
        key: validate_success(
            api.complete_grinding_run(
                run["id"],
                f.complete_grinding_run_payload(
                    produced_units=1,
                    scrap_units=0,
                    measured_diameter_dev_um=deviations[key],
                ),
                PLAN,
            )
        )
        for key, run in booked.items()
    }
    return state


def test_the_tolerance_bands_are_inclusive_at_each_upper_bound(api):
    """5.0 is still IT6, 5.1 has fallen to IT7, 12.0 is the last IT7 and 25.1 is out.

    PRD §3.4: "The achieved `tolerance_class` is graded from the absolute value of
    `measured_diameter_dev_um`: at most 5.0 micrometres is `IT6`; otherwise at most
    12.0 is `IT7`; otherwise at most 25.0 is `IT8`; anything larger is
    `OUT_OF_TOLERANCE`. Every band is inclusive at its upper bound, so a deviation
    of exactly 5.0 grades as `IT6`."

    Design: Corner/calculations/tolerance_class_walks_every_band_boundary
    """
    state = _four_completed_runs_at_the_band_edges(api)

    runs = state["runs"]
    assert runs["it6"]["tolerance_class"] == "IT6", (
        f"exactly 5.0 um is inside the IT6 band, got {runs['it6']['tolerance_class']}"
    )
    assert runs["it7_low"]["tolerance_class"] == "IT7", (
        f"one tenth beyond 5.0 falls to IT7, got {runs['it7_low']['tolerance_class']}"
    )
    assert runs["it7_high"]["tolerance_class"] == "IT7", (
        f"exactly 12.0 um is the last IT7 value, got {runs['it7_high']['tolerance_class']}"
    )
    assert runs["out"]["tolerance_class"] == "OUT_OF_TOLERANCE", (
        f"25.1 um is beyond every band, got {runs['out']['tolerance_class']}"
    )
    for key, run in runs.items():
        assert run["status"] == "COMPLETED", (
            "an out-of-tolerance result classifies the run rather than refusing "
            f"the call, so {key} is closed out, got {run['status']}"
        )


def test_every_closed_out_run_charges_the_same_twenty_units_whatever_its_class(api):
    """Four one-tool runs at 20 units each charge 80, however they graded.

    PRD §3.4: "Then the wheel is charged: the run's own `consumed_life_units` is
    set to `produced_units` plus `scrap_units`, multiplied by the ground product's
    `grind_units_per_tool`, and that figure is added to the wheel's
    `consumed_life_units`."

    PRD §3.4: "Throughout the wheel's life, `remaining_life_units` is
    `initial_life_units` minus `consumed_life_units`, and `consumed_life_units` is
    the total charged to the wheel since its last dressing by completed grinding
    runs and by reconditioning refurbishments."

    Design: Corner/calculations/tolerance_class_walks_every_band_boundary
    """
    state = _four_completed_runs_at_the_band_edges(api)

    for key, run in state["runs"].items():
        assert run["consumed_life_units"] == 20, (
            f"one tool at 20 units each is a charge of 20 on {key}, got "
            f"{run['consumed_life_units']}"
        )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 80, (
        f"four charges of 20 accumulate to 80, got {wheel['consumed_life_units']}"
    )
    assert wheel["remaining_life_units"] == 99920, (
        f"100000 less 80 leaves 99920, got {wheel['remaining_life_units']}"
    )
    assert wheel["status"] == "AVAILABLE", (
        f"the wheel is nowhere near its dressing threshold, got {wheel['status']}"
    )
    assert_wheel_life_conserved(wheel)


# ─── Engineering lead time reads current status ─────────────────────────────

def _catalogue_and_special_on_a_draft_geometry(api) -> dict:
    """A PILOT grade, a DRAFT geometry, and one uncoated product of each class."""
    pilot = fx.pilot_grade_with_passed_batch(api)
    geometry = fx.insert_geometry(api)
    catalog = validate_success(
        api.create_tool_product(
            f.tool_product_payload(pilot["grade"]["id"], geometry["id"]), GEO
        ),
        201,
    )
    special = validate_success(
        api.create_tool_product(
            f.special_product_payload(
                pilot["grade"]["id"],
                geometry["id"],
                None,
                catalog["id"],
                sku="SPC-INS-1",
                list_price_cents=6100,
            ),
            APP,
        ),
        201,
    )
    return {
        "grade": pilot["grade"],
        "geometry": geometry,
        "catalog": catalog,
        "special": special,
    }


def test_the_expedite_shave_is_decided_on_the_raw_total_and_never_revisited(api):
    """A raw 19 is shaved to 16 while a raw 29 keeps every one of its days.

    PRD §3.5: "The base contribution is 5 days for a `CATALOG` product and 15 days
    for a `SPECIAL` one. The geometry contributes nothing when the geometry's
    `status` is `RELEASED` and 8 days otherwise. The coating contributes nothing
    when `coating_recipe_id` is null, 4 days when the recipe's `deposition_type` is
    `PVD`, and 7 days when it is `CVD`. The grade contributes nothing when the
    grade's `status` is `QUALIFIED` and 6 days otherwise."

    PRD §3.5: "`expedite_eligible` is decided on the **raw** total, being true
    when the raw total is at most 21 days, and is never revisited afterwards. Only
    if the product is expedite eligible is 3 days shaved off the raw total."

    Design: Corner/calculations/product_lead_time_recomputes_when_its_geometry_is_released
    """
    state = _catalogue_and_special_on_a_draft_geometry(api)

    catalog = state["catalog"]
    special = state["special"]
    assert catalog["engineering_lead_time_days"] == 16, (
        "5 base plus 8 for the unreleased geometry plus 6 for the unqualified "
        f"grade is a raw 19, shaved by 3, got {catalog['engineering_lead_time_days']}"
    )
    assert catalog["expedite_eligible"] is True, (
        f"a raw 19 is at most 21, got {catalog['expedite_eligible']}"
    )
    assert special["engineering_lead_time_days"] == 29, (
        "15 base plus 8 plus 6 is a raw 29, and an ineligible product is never "
        f"shaved, got {special['engineering_lead_time_days']}"
    )
    assert special["expedite_eligible"] is False, (
        f"a raw 29 is beyond the 21-day limit, got {special['expedite_eligible']}"
    )


def test_releasing_the_geometry_drops_the_adder_on_every_product_that_names_it(api):
    """Both products lose 8 days at once, and the special lands exactly on the limit.

    PRD §3.2: "The release has a side effect that reaches beyond the geometry
    itself: because an unreleased geometry contributes eight days of engineering
    lead time and a released one contributes none, every tool product referencing
    this `geometry_id` has `engineering_lead_time_days` and `expedite_eligible`
    recomputed, and each such product has its own `version` incremented alongside
    the geometry's."

    PRD §3.5: "It reads the **current** status of the referenced rows, not the
    pinned revisions."

    PRD §3.5: "The grade contributes nothing when the grade's `status` is
    `QUALIFIED` and 6 days otherwise."

    Design: Corner/calculations/product_lead_time_recomputes_when_its_geometry_is_released
    """
    state = _catalogue_and_special_on_a_draft_geometry(api)

    validate_success(api.release_insert_geometry(state["geometry"]["id"], GEO))

    catalog = validate_success(api.get_tool_product(state["catalog"]["id"], APP))
    special = validate_success(api.get_tool_product(state["special"]["id"], APP))
    assert catalog["engineering_lead_time_days"] == 8, (
        "5 base plus 6 for the unqualified grade is a raw 11, shaved by 3, got "
        f"{catalog['engineering_lead_time_days']}"
    )
    assert special["engineering_lead_time_days"] == 18, (
        "15 plus 6 is a raw 21, which lands exactly on the eligibility limit, so "
        f"the shave now applies, got {special['engineering_lead_time_days']}"
    )
    assert special["expedite_eligible"] is True, (
        f"a raw 21 is at most 21, got {special['expedite_eligible']}"
    )
    grade = validate_success(api.get_carbide_grade(state["grade"]["id"], MET))
    assert grade["status"] == "PILOT", (
        "the grade is still only in pilot, so both products still carry its "
        f"6-day adder, got {grade['status']}"
    )


# ─── The two tool-life figures on one curve ─────────────────────────────────

def _trial_on_a_censored_curve(api) -> dict:
    """A trial whose wear curve stops at 245 um, short of the 300 um limit."""
    state = fx.open_dossier(api, coated=False)
    trial = validate_success(
        api.create_machining_trial(
            f.trial_payload(state["dossier"]["id"], state["batch"]["id"], trial_code="TRL-C"),
            OPERATOR_ONE,
        ),
        201,
    )
    state["trial"] = validate_success(
        api.complete_machining_trial(
            trial["id"],
            f.complete_trial_payload(
                wear_measurements=[
                    {"minutes": 0, "vb_um": 0},
                    {"minutes": 5, "vb_um": 90},
                    {"minutes": 10, "vb_um": 150},
                    {"minutes": 15, "vb_um": 200},
                    {"minutes": 20, "vb_um": 245},
                ],
                measured_surface_ra_um=1.00,
            ),
            OPERATOR_ONE,
        )
    )
    return state


def test_a_censored_curve_rates_to_its_last_minute_but_still_projects_forward(api):
    """The measured figure stops at 20.0 while the projection extrapolates to 26.1.

    PRD §3.6: "If no pair brackets the limit — the curve never reaches 300
    micrometres — `rated_life_min` is instead the `minutes` value of the **last**
    entry, rounded half up to one decimal place, and `censored` is set to true."

    PRD §3.6: "It uses only the last two entries of the curve, regardless of where
    the crossing occurred: the wear rate in micrometres per minute is the increase
    in `vb_um` across the final pair divided by the increase in `minutes` across
    it, and `projected_life_min` is the last entry's `minutes` plus the remaining
    wear allowance from the last `vb_um` to 300 divided by that rate, rounded half
    up to one decimal place."

    PRD §3.6: "note that a censored curve is always `FAIL`, however long the tool
    actually ran, because the measurement never demonstrated the wear criterion."

    Design: Corner/calculations/censored_wear_curve_rates_to_the_last_observed_minute
    """
    state = _trial_on_a_censored_curve(api)

    trial = state["trial"]
    assert_machining_trial(trial)
    assert trial["censored"] is True, (
        f"245 um never reaches the 300 um limit, got {trial['censored']}"
    )
    assert trial["rated_life_min"] == 20.0, (
        f"the last observed minute is 20, got {trial['rated_life_min']}"
    )
    assert trial["projected_life_min"] == 26.1, (
        "the final pair wears at 9.0 um per minute, so 20 plus 55 over 9.0 is "
        f"26.1, got {trial['projected_life_min']}"
    )
    assert trial["verdict"] == "FAIL", (
        "20.0 minutes would clear the 18.0 minute minimum, so only the censoring "
        f"can explain the verdict, got {trial['verdict']}"
    )


def test_a_failed_trial_still_enters_the_dossier_average(api):
    """The FAIL trial's own subscore of 1.31 becomes the dossier's composite score.

    PRD §3.6: "The `composite_score` is computed over the dossier's `COMPLETED`
    trials only — `RUNNING` and `INVALIDATED` trials are excluded — and is null
    when that set is empty."

    PRD §3.6: "For each such trial, taken in ascending `created_at` order, a life
    ratio is formed as `rated_life_min` divided by the class's required life,
    capped at 2.0; a finish ratio is formed as the class's maximum roughness
    divided by `measured_surface_ra_um`, also capped at 2.0; and a per-trial
    subscore is 0.6 multiplied by the life ratio plus 0.4 multiplied by the finish
    ratio, **rounded half up to two decimal places at that point**."

    PRD §3.6: "Trials with a `FAIL` verdict are included in the average — a
    failure drags the score down rather than being ignored."

    Design: Corner/calculations/censored_wear_curve_rates_to_the_last_observed_minute
    """
    state = _trial_on_a_censored_curve(api)

    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )

    assert dossier["completed_trial_count"] == 1, (
        f"the trial is closed out whatever its verdict, got {dossier['completed_trial_count']}"
    )
    assert dossier["passed_trial_count"] == 0, (
        f"nothing passed, got {dossier['passed_trial_count']}"
    )
    assert dossier["composite_score"] == 1.31, (
        "0.6 times 20.0 over 18.0 plus 0.4 times 1.6 over 1.00 is 1.30666, which "
        f"rounds half up to 1.31, got {dossier['composite_score']}"
    )


# ─── The pinned rounding order of the composite score ──────────────────────

def _two_trials_at_identical_lives_and_unlike_finishes(api) -> dict:
    """Two 18.0-minute trials on the same P material, finished at 0.20 and 1.74 um."""
    state = fx.open_dossier(api, coated=False)
    for key, code, headers in (
        ("fine", "TRL-A", OPERATOR_ONE),
        ("coarse", "TRL-B", OPERATOR_TWO),
    ):
        trial = validate_success(
            api.create_machining_trial(
                f.trial_payload(
                    state["dossier"]["id"], state["batch"]["id"], trial_code=code
                ),
                headers,
            ),
            201,
        )
        state[key] = trial
    return state


def test_the_crossing_pair_is_inclusive_at_the_three_hundred_micrometre_limit(api):
    """A curve whose final point is exactly 300 um is bracketed, not censored.

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

    Design: Corner/calculations/composite_score_rounds_each_subscore_before_averaging
    """
    state = _two_trials_at_identical_lives_and_unlike_finishes(api)
    curve = [
        {"minutes": 0, "vb_um": 0},
        {"minutes": 9, "vb_um": 200},
        {"minutes": 18, "vb_um": 300},
    ]

    fine = validate_success(
        api.complete_machining_trial(
            state["fine"]["id"],
            f.complete_trial_payload(wear_measurements=curve, measured_surface_ra_um=0.20),
            OPERATOR_ONE,
        )
    )
    coarse = validate_success(
        api.complete_machining_trial(
            state["coarse"]["id"],
            f.complete_trial_payload(wear_measurements=curve, measured_surface_ra_um=1.74),
            OPERATOR_TWO,
        )
    )

    for label, trial in (("fine", fine), ("coarse", coarse)):
        assert trial["censored"] is False, (
            f"the final pair reaches the limit exactly on {label}, got {trial['censored']}"
        )
        assert trial["rated_life_min"] == 18.0, (
            "the shortfall of 100 over an increase of 100 places the crossing at "
            f"the pair's far end on {label}, got {trial['rated_life_min']}"
        )
    assert fine["verdict"] == "PASS", (
        f"18.0 minutes and 0.20 um clear both MEDIUM limits, got {fine['verdict']}"
    )
    assert coarse["verdict"] == "FAIL", (
        f"1.74 um is beyond the 1.6 um MEDIUM maximum, got {coarse['verdict']}"
    )


def test_each_subscore_is_rounded_before_the_average_is_taken(api):
    """Rounding first gives 1.19; averaging the raw subscores would give 1.18.

    PRD §3.6: "The `composite_score` is then the sum of those rounded subscores
    divided by the number of considered trials, rounded half up to two decimal
    places. The rounding order is pinned: each subscore is rounded before the
    average is taken, and averaging unrounded subscores with a single rounding at
    the end is a different and incorrect answer."

    PRD §3.6: "a finish ratio is formed as the class's maximum roughness divided
    by `measured_surface_ra_um`, also capped at 2.0"

    Design: Corner/calculations/composite_score_rounds_each_subscore_before_averaging
    """
    state = _two_trials_at_identical_lives_and_unlike_finishes(api)
    curve = [
        {"minutes": 0, "vb_um": 0},
        {"minutes": 9, "vb_um": 200},
        {"minutes": 18, "vb_um": 300},
    ]
    validate_success(
        api.complete_machining_trial(
            state["fine"]["id"],
            f.complete_trial_payload(wear_measurements=curve, measured_surface_ra_um=0.20),
            OPERATOR_ONE,
        )
    )

    after_one = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    validate_success(
        api.complete_machining_trial(
            state["coarse"]["id"],
            f.complete_trial_payload(wear_measurements=curve, measured_surface_ra_um=1.74),
            OPERATOR_TWO,
        )
    )
    after_two = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )

    assert after_one["composite_score"] == 1.40, (
        "0.6 times 1.0 plus 0.4 times the capped 2.0 is 1.40, got "
        f"{after_one['composite_score']}"
    )
    assert after_two["composite_score"] == 1.19, (
        "1.40 and a subscore of 0.967816 rounded to 0.97 average to 1.185, which "
        f"rounds half up to 1.19, got {after_two['composite_score']}"
    )
    assert after_two["composite_score"] != 1.18, (
        "1.18 is the answer produced by averaging the unrounded subscores and "
        "rounding once at the end"
    )


# ─── The volume tier boundary and the per-unit rounding order ──────────────

def _two_orders_across_the_top_tier_boundary(api) -> dict:
    """One 500-piece order and one 499-piece order on the same released insert."""
    state = fx.released_product_with_customer(api)
    for key, code, quantity in (("top", "SO-500", 500), ("below", "SO-499", 499)):
        order = validate_success(
            api.create_tool_order(
                f.tool_order_payload(
                    state["customer"]["id"],
                    state["product"]["id"],
                    fx.current_product_version(api, state["product"]["id"]),
                    order_code=code,
                    quantity=quantity,
                ),
                APP,
            ),
            201,
        )
        state[key] = validate_success(api.submit_tool_order(order["id"], APP))
    return state


def test_five_hundred_pieces_reach_the_top_volume_tier(api):
    """The 12 percent tier opens at exactly 500 and bills 2122000 cents.

    PRD §3.8: "The volume discount is 0.12 when `quantity` is at least 500,
    otherwise 0.07 when it is at least 100, otherwise 0.03 when it is at least 25,
    otherwise nothing."

    PRD §3.8: "The gross per-unit price is `list_price_cents` multiplied by the
    quantity one plus the sum of the three surcharge fractions;
    `per_unit_net_cents` is that gross figure multiplied by the quantity one minus
    the volume discount fraction, **rounded half up to whole cents at that
    point**; and `total_price_cents` is `per_unit_net_cents` multiplied by
    `quantity`."

    PRD §3.8: "The rounding order is pinned to the unit: rounding once on the
    multiplied-out total instead differs by tens of cents on a large order and is
    incorrect."

    Design: Corner/calculations/order_price_at_the_top_volume_tier_boundary
    """
    state = _two_orders_across_the_top_tier_boundary(api)

    order = state["top"]
    assert_tool_order(order)
    assert order["status"] == "SUBMITTED", (
        f"a catalogue order on a released product is submitted, got {order['status']}"
    )
    assert order["per_unit_net_cents"] == 4244, (
        "4550 with the 6 percent PVD surcharge is 4823, less 12 percent is "
        f"4244.24, which rounds half up to 4244, got {order['per_unit_net_cents']}"
    )
    assert order["total_price_cents"] == 2122000, (
        "4244 times 500 is 2122000, not the 2122120 that rounding the total once "
        f"produces, got {order['total_price_cents']}"
    )
    assert_total_is_per_unit_times_quantity(order)


def test_four_hundred_and_ninety_nine_pieces_fall_back_to_the_hundred_tier(api):
    """One piece short of the tier, the discount is 7 percent and the unit price rises.

    PRD §3.8: "The volume discount is 0.12 when `quantity` is at least 500,
    otherwise 0.07 when it is at least 100, otherwise 0.03 when it is at least 25,
    otherwise nothing."

    PRD §3.8: "The coating surcharge is nothing for an uncoated product, 0.06 for
    a `PVD` recipe and 0.10 for a `CVD` one."

    Design: Corner/calculations/order_price_at_the_top_volume_tier_boundary
    """
    state = _two_orders_across_the_top_tier_boundary(api)

    order = state["below"]
    assert order["status"] == "SUBMITTED", (
        f"the smaller order is priced and routed alike, got {order['status']}"
    )
    assert order["per_unit_net_cents"] == 4485, (
        "4823 less 7 percent is 4485.39, which rounds half up to 4485, got "
        f"{order['per_unit_net_cents']}"
    )
    assert order["total_price_cents"] == 2238015, (
        f"4485 times 499 is 2238015, got {order['total_price_cents']}"
    )
    assert_total_is_per_unit_times_quantity(order)
    assert order["per_unit_net_cents"] > state["top"]["per_unit_net_cents"], (
        "one piece short of the tier costs more per piece, got "
        f"{order['per_unit_net_cents']} against {state['top']['per_unit_net_cents']}"
    )


# ─── The reconditioning money path ─────────────────────────────────────────

def _twelve_tool_job_measured_at_ninety_millimetres(api) -> dict:
    """A 12-tool first-pass job inspected at 90.0 mm and ground on a fresh wheel."""
    return fx.refurbished_recondition_job(
        api,
        customer_overrides={
            "customer_code": "CU-4",
            "name": "Delta Cutter Service",
            "tier": "STANDARD",
            "regrind_credit_cents": 50000,
        },
        job_overrides={"job_code": "RJ-1", "units_received": 12},
        inspect_overrides={
            "units_inspected": 12,
            "measured_length_mm": 90.0,
            "measured_corner_wear_um": 120.0,
        },
    )


def test_the_residual_geometry_figures_are_computed_from_the_measured_length(api):
    """90.0 mm leaves 8 passes and recovers 20.0 percent, while the warrant reads 35.0.

    PRD §3.9: "`remaining_regrinds` is the whole number of passes left, computed
    as `measured_length_mm` minus the product's `min_regrind_length_mm`, divided by
    the product's `regrind_step_mm`, rounded **down** to a whole number, and then
    floored at 0 so it is never negative."

    PRD §3.9: "`life_extension_pct` is 100 multiplied by `remaining_regrinds`,
    multiplied by the product's `regrind_step_mm`, divided by the product's
    `nominal_length_mm`, rounded half up to one decimal place."

    PRD §3.9: "`warranted_life_extension_pct` is 35.0 multiplied by 0.7 raised to
    the power of `regrind_pass_no` minus one, rounded half up to one decimal place
    — 35.0 on the first pass, 24.5 on the second, 17.2 on the third, and so on."

    PRD §3.9: "the reservation of `units_received` multiplied by 1850 cents must
    not exceed the customer's `regrind_credit_cents`, otherwise
    `ERR_INSUFFICIENT_REGRIND_CREDIT`."

    Design: Corner/calculations/recondition_rebate_is_paid_once_on_return_and_consumes_the_reservation
    """
    state = _twelve_tool_job_measured_at_ninety_millimetres(api)

    job = state["job"]
    assert_recondition_job(job)
    assert job["remaining_regrinds"] == 8, (
        "90.0 less 70.0 over 2.5 is exactly 8 passes, got "
        f"{job['remaining_regrinds']}"
    )
    assert job["life_extension_pct"] == 20.0, (
        "8 passes of 2.5 mm against a 100.0 mm tool recovers 20.0 percent, got "
        f"{job['life_extension_pct']}"
    )
    assert job["warranted_life_extension_pct"] == 35.0, (
        f"the first pass is warranted at 35.0 percent, got {job['warranted_life_extension_pct']}"
    )
    assert job["scrap_recommended"] is False, (
        f"90.0 mm is well above the 70.0 mm floor, got {job['scrap_recommended']}"
    )
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["regrind_credit_cents"] == 27800, (
        "50000 less a 12 by 1850 reservation leaves 27800 unreserved, got "
        f"{customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 22200, (
        f"12 tools at 1850 cents reserve 22200, got {customer['reserved_credit_cents']}"
    )
    assert_credit_conserved(customer, 50000)


def test_the_return_pays_the_residual_rebate_and_consumes_the_reservation(api):
    """A 20.0 percent recovery on 12 tools pays 2160 cents and the 22200 is not refunded.

    PRD §3.9: "`units_inspected` multiplied by `grind_units_per_tool` is added to
    the wheel's `consumed_life_units`"

    PRD §3.9: "The `rebate_cents` is `life_extension_pct` divided by 100,
    multiplied by `units_returned`, multiplied by a rebate basis of 900 cents,
    rounded half up to whole cents — and it uses the residual-geometry figure only,
    never `warranted_life_extension_pct`."

    PRD §3.9: "That rebate is added to the customer's `regrind_credit_cents`, and
    the intake reservation is **consumed rather than refunded**: the job's
    `reserved_credit_cents` is set to 0 and the customer's `reserved_credit_cents`
    is reduced by it, with no corresponding credit back to the balance."

    Design: Corner/calculations/recondition_rebate_is_paid_once_on_return_and_consumes_the_reservation
    """
    state = _twelve_tool_job_measured_at_ninety_millimetres(api)
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 240, (
        f"12 tools at 20 units each charge 240, got {wheel['consumed_life_units']}"
    )
    assert wheel["status"] == "AVAILABLE", (
        f"99760 units remain, far above the threshold, got {wheel['status']}"
    )

    response = api.return_recondition_job(
        state["job"]["id"], f.return_job_payload(units_returned=12), PLAN
    )

    job = validate_success(response)
    assert job["status"] == "RETURNED", (
        f"a refurbished job may be returned, got {job['status']}"
    )
    assert job["units_returned"] == 12, (
        f"every inspected tool goes back, got {job['units_returned']}"
    )
    assert job["rebate_cents"] == 2160, (
        "20.0 percent of 12 tools at a 900-cent basis is 2160 cents, got "
        f"{job['rebate_cents']}"
    )
    assert job["reserved_credit_cents"] == 0, (
        f"the job holds no reservation once it is settled, got {job['reserved_credit_cents']}"
    )
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["regrind_credit_cents"] == 29960, (
        "27800 plus the 2160 rebate is 29960, so the 22200 reservation was "
        f"consumed rather than refunded, got {customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 0, (
        f"nothing is held any more, got {customer['reserved_credit_cents']}"
    )
