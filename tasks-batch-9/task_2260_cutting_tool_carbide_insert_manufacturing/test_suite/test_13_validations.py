"""Field, arithmetic and cross-entity validations, and the order they fire in.

Several of these rules are reachable only in combination: a booking window can be
both reversed and in the past, an account can be both on hold and short of
credit, and a dossier can be both under-scored and under-covered. In every such
pair the ladder in §2.11 decides which code the client actually sees, so the
tests below deliberately breach two rules at once and pin the reported one.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_credit_conserved,
    assert_insert_geometry,
    assert_machining_trial,
    assert_no_row_with_code,
    assert_powder_blend_batch,
    assert_recondition_job,
    assert_tool_product,
)
from test_helpers.fixtures import (
    APP,
    APPROVER,
    COAT,
    GEO,
    MET,
    OPERATOR_ONE,
    OPERATOR_TWO,
    PLAN,
    SUBMITTER,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Window bounds before the past-window rule ───────────────────────────────

def test_a_window_that_is_both_reversed_and_in_the_past_reports_the_ordering_error(api):
    """A 12:00-to-06:00 window on 30 July breaches rules 25 and 26 together.

    PRD §2.11: "The system evaluates checks in a fixed ascending order and
    reports the **first** violation it finds; later checks are not evaluated and
    their codes are never returned for that request."

    PRD §2.11: "25. **Window bounds ordered.** → `ERR_INVALID_WINDOW`, on
    coating-run creation and grinding-run creation."

    PRD §2.11: "26. **Window not in the past.** → `ERR_WINDOW_IN_PAST`, on
    coating-run creation and grinding-run creation."

    PRD §3.3: "`window_start` must be strictly earlier than `window_end`, or the
    booking is rejected with `ERR_INVALID_WINDOW`; and `window_start` must not be
    strictly earlier than the current logical UTC time, or the booking is
    rejected with `ERR_WINDOW_IN_PAST`."

    Design: Corner/validations/window_ordering_is_checked_before_the_past_window_rule
    """
    fx.advance_clock(api, "2026-08-01T00:00:00Z")
    recipe = fx.coating_recipe(api)

    both_wrong = api.create_coating_run(
        f.coating_run_payload(
            recipe["id"],
            window_start="2026-07-30T12:00:00Z",
            window_end="2026-07-30T06:00:00Z",
            loaded_area_cm2=1000.00,
        ),
        COAT,
    )
    merely_past = api.create_coating_run(
        f.coating_run_payload(
            recipe["id"],
            window_start="2026-07-31T23:59:59Z",
            window_end="2026-08-02T06:00:00Z",
            loaded_area_cm2=1000.00,
        ),
        COAT,
    )

    validate_error(both_wrong, ApiErrorId.ERR_INVALID_WINDOW, 422)
    validate_error(merely_past, ApiErrorId.ERR_WINDOW_IN_PAST, 422)
    rows, _meta = validate_paginated(api.list_coating_runs(COAT))
    assert len(rows) == 0, (
        f"neither rejected booking may leave a run behind, got {len(rows)} runs"
    )


def test_a_window_opening_exactly_at_the_current_instant_is_not_in_the_past(api):
    """A window starting at the clock itself books, while a zero-length one does not.

    PRD §3.3: "`window_start` must be strictly earlier than `window_end`, or the
    booking is rejected with `ERR_INVALID_WINDOW`; and `window_start` must not be
    strictly earlier than the current logical UTC time, or the booking is
    rejected with `ERR_WINDOW_IN_PAST`."

    PRD §3.3: "The run opens at `status` `SCHEDULED` and captures
    `pinned_recipe_revision` from the recipe's current `revision`, which is what
    later ties the run's measurements to a specific layer stack rather than to
    whatever the recipe has since become."

    Design: Corner/validations/window_ordering_is_checked_before_the_past_window_rule
    """
    fx.advance_clock(api, "2026-08-01T00:00:00Z")
    recipe = fx.coating_recipe(api)

    at_the_clock = api.create_coating_run(
        f.coating_run_payload(
            recipe["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-01T06:00:00Z",
            loaded_area_cm2=1000.00,
        ),
        COAT,
    )
    zero_length = api.create_coating_run(
        f.coating_run_payload(
            recipe["id"],
            window_start="2026-08-03T06:00:00Z",
            window_end="2026-08-03T06:00:00Z",
            loaded_area_cm2=1000.00,
        ),
        COAT,
    )

    run = validate_success(at_the_clock, 201)
    assert run["status"] == "SCHEDULED", (
        "a window opening at the current instant is not strictly earlier than "
        f"the clock, so it is accepted, got {run['status']}"
    )
    assert run["pinned_recipe_revision"] == 1, (
        f"the booking pins the recipe's current revision, got {run['pinned_recipe_revision']}"
    )
    validate_error(zero_length, ApiErrorId.ERR_INVALID_WINDOW, 422)


# ─── Business code uniqueness, scoped per collection ─────────────────────────

def test_a_duplicate_grade_code_is_refused_while_a_geometry_may_reuse_the_string(api):
    """WC-P25 is taken among grades and simultaneously free among geometries.

    PRD §2.11: "11. **Business code uniqueness.** → `ERR_DUPLICATE_CODE`, on
    every entity-creating request."

    PRD §2.4: "Business codes are separate from `id` and are supplied by the
    caller: `grade_code`, `batch_code`, `geometry_code`, `recipe_code`,
    `wheel_code`, `sku`, `dossier_code`, `trial_code`, `customer_code`,
    `order_code` and `job_code` must each be unique across their own collection,
    and a duplicate is rejected with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/business_codes_are_unique_per_collection
    """
    first = fx.carbide_grade(api)

    duplicate = api.create_carbide_grade(
        f.carbide_grade_payload(
            grade_code="WC-P25",
            target_workpiece_group="M",
            co_binder_pct=10.0,
            wc_grain_um=1.5,
            hardness_hv=1450,
            trs_mpa=2600,
        ),
        MET,
    )
    borrowed = api.create_insert_geometry(
        f.insert_geometry_payload(geometry_code="WC-P25"), GEO
    )

    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CODE, 409)
    grades, _meta = validate_paginated(api.list_carbide_grades(MET))
    assert len(grades) == 1, (
        f"the duplicate must not have created a second grade, got {len(grades)}"
    )
    standing = validate_success(api.get_carbide_grade(first["id"], MET))
    assert standing["target_workpiece_group"] == "P", (
        "the rejected request must not have overwritten the standing grade, got "
        f"{standing['target_workpiece_group']}"
    )
    geometry = validate_success(borrowed, 201)
    assert_insert_geometry(geometry)
    assert geometry["geometry_code"] == "WC-P25", (
        "uniqueness is scoped to a collection, so a geometry may carry the "
        f"string a grade already uses, got {geometry['geometry_code']}"
    )


# ─── Special product derivation, exactly one hop deep ────────────────────────

def _catalogue_and_special_pair(api) -> dict:
    """A CATALOG insert and one valid SPECIAL derived from it, both uncoated."""
    grade = fx.carbide_grade(api)
    geometry = fx.insert_geometry(api)
    catalogue = validate_success(
        api.create_tool_product(
            f.tool_product_payload(grade["id"], geometry["id"]), GEO
        ),
        201,
    )
    special = validate_success(
        api.create_tool_product(
            f.special_product_payload(
                grade["id"],
                geometry["id"],
                None,
                catalogue["id"],
                sku="SPC-INS-1",
                list_price_cents=6100,
            ),
            APP,
        ),
        201,
    )
    return {
        "grade": grade,
        "geometry": geometry,
        "catalogue": catalogue,
        "special": special,
    }


def test_a_special_needs_a_catalogue_parent_and_may_not_descend_from_another_special(api):
    """Both an absent parent and a SPECIAL parent are the same derivation failure.

    PRD §2.11: "22. **Special product derivation.** →
    `ERR_INVALID_PRODUCT_DERIVATION`, on product creation."

    PRD §3.5: "A `SPECIAL` product must supply `base_catalog_product_id`, that
    identifier must not be the product's own, and the product it names must
    itself be `CATALOG` — a special derived from another special is refused."

    PRD §3.5: "Every one of those failures is reported as
    `ERR_INVALID_PRODUCT_DERIVATION`."

    Design: Corner/validations/special_product_derivation_rules
    """
    state = _catalogue_and_special_pair(api)

    parentless = api.create_tool_product(
        f.tool_product_payload(
            state["grade"]["id"],
            state["geometry"]["id"],
            sku="SPC-NOBASE",
            order_class="SPECIAL",
            list_price_cents=6100,
            min_order_qty=5,
        ),
        APP,
    )
    chained = api.create_tool_product(
        f.special_product_payload(
            state["grade"]["id"],
            state["geometry"]["id"],
            None,
            state["special"]["id"],
            sku="SPC-CHAIN",
            list_price_cents=6400,
        ),
        APP,
    )

    validate_error(parentless, ApiErrorId.ERR_INVALID_PRODUCT_DERIVATION, 422)
    validate_error(chained, ApiErrorId.ERR_INVALID_PRODUCT_DERIVATION, 422)
    products, _meta = validate_paginated(api.list_tool_products(APP))
    assert_no_row_with_code(products, "sku", "SPC-NOBASE")
    assert_no_row_with_code(products, "sku", "SPC-CHAIN")
    assert len(products) == 2, (
        f"only the two legitimate products may stand, got {len(products)}"
    )


def test_a_catalogue_product_omits_the_parent_and_opens_with_it_null(api):
    """The derivation rule binds SPECIAL products only.

    PRD §3.5: "A `CATALOG` product must not supply `base_catalog_product_id` at
    all."

    PRD §3.5: "A new product opens at `release_status` `DEVELOPMENT` and
    `supply_status` `UNAVAILABLE`, captures the three pinned revisions from its
    referenced grade, geometry and recipe, computes `engineering_lead_time_days`
    and `expedite_eligible`, and sets `tool_life_index` to null,
    `qualified_workpiece_groups` to the empty list and `open_order_units` to 0."

    Design: Corner/validations/special_product_derivation_rules
    """
    state = _catalogue_and_special_pair(api)

    response = api.create_tool_product(
        f.tool_product_payload(
            state["grade"]["id"],
            state["geometry"]["id"],
            sku="CAT-INS-2",
            list_price_cents=4600,
        ),
        GEO,
    )

    product = validate_success(response, 201)
    assert_tool_product(product)
    assert product["order_class"] == "CATALOG", (
        f"the second catalogue product is created as asked, got {product['order_class']}"
    )
    assert product["base_catalog_product_id"] is None, (
        "a catalogue product carries no parent at all, got "
        f"{product['base_catalog_product_id']}"
    )
    assert product["release_status"] == "DEVELOPMENT", (
        f"a new product opens in development, got {product['release_status']}"
    )


# ─── Unit conservation on three different counting endpoints ─────────────────

def test_sintering_that_does_not_reconcile_with_the_pressed_count_is_refused(api):
    """170 good plus 20 scrapped is 190 against 200 pressed, so nothing moves.

    PRD §2.11: "33. **Unit conservation.** → `ERR_UNIT_COUNT_MISMATCH`, on batch
    sintering, grinding-run completion, reconditioning inspection and
    reconditioning return."

    PRD §3.1: "Units must be conserved: `sintered_units` plus `scrap_units` must
    equal `pressed_units` exactly, and any other total is rejected with
    `ERR_UNIT_COUNT_MISMATCH`."

    Design: Corner/validations/unit_counts_must_reconcile_on_every_counting_endpoint
    """
    grade = fx.carbide_grade(api)
    batch = validate_success(
        api.create_powder_blend_batch(f.powder_blend_batch_payload(grade["id"]), MET),
        201,
    )
    validate_success(
        api.press_powder_blend_batch(batch["id"], f.press_payload(), MET)
    )

    response = api.sinter_powder_blend_batch(
        batch["id"], f.sinter_payload(sintered_units=170, scrap_units=20), MET
    )

    validate_error(response, ApiErrorId.ERR_UNIT_COUNT_MISMATCH, 422)
    standing = validate_success(api.get_powder_blend_batch(batch["id"], MET))
    assert_powder_blend_batch(standing)
    assert standing["stage"] == "PRESSED", (
        f"the refused sinter leaves the batch pressed, got {standing['stage']}"
    )
    assert standing["qc_status"] == "PENDING", (
        f"the quality dimension is untouched as well, got {standing['qc_status']}"
    )
    assert standing["sintered_units"] == 0, (
        f"no good units were recorded, got {standing['sintered_units']}"
    )


def test_closing_a_grinding_run_that_does_not_reconcile_charges_nothing(api):
    """3 produced plus 1 scrapped is 4 against 5 planned, so the wheel is spared.

    PRD §3.4: "Closing out a grinding run requires the run to be `SCHEDULED`,
    requires the logical clock to have reached `window_end` (otherwise
    `ERR_WINDOW_NOT_ELAPSED`), and requires `produced_units` plus `scrap_units`
    to equal `planned_units` exactly (otherwise `ERR_UNIT_COUNT_MISMATCH`)."

    Design: Corner/validations/unit_counts_must_reconcile_on_every_counting_endpoint
    """
    state = fx.scheduled_grinding_run(
        api, wheel_overrides={"initial_life_units": 100000}, planned_units=5
    )
    fx.advance_clock(api, state["run"]["window_end"])

    response = api.complete_grinding_run(
        state["run"]["id"],
        f.complete_grinding_run_payload(
            produced_units=3, scrap_units=1, measured_diameter_dev_um=4.0
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_COUNT_MISMATCH, 422)
    run = validate_success(api.get_grinding_run(state["run"]["id"], PLAN))
    assert run["status"] == "SCHEDULED", (
        f"the refused completion leaves the run scheduled, got {run['status']}"
    )
    assert run["consumed_life_units"] == 0, (
        f"the run retains no charge, got {run['consumed_life_units']}"
    )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 0, (
        f"the wheel carries no charge either, got {wheel['consumed_life_units']}"
    )


def test_inspecting_more_tools_than_were_received_is_refused(api):
    """11 inspected against 10 received is the same conservation failure.

    PRD §3.9: "It requires the job to be `RECEIVED` and carries
    `units_inspected`, which must equal `units_received` — any other figure is
    `ERR_UNIT_COUNT_MISMATCH` — together with `measured_length_mm`, the mean
    remaining usable length at one decimal place, and `measured_corner_wear_um`,
    the mean corner wear at one decimal place."

    Design: Corner/validations/unit_counts_must_reconcile_on_every_counting_endpoint
    """
    state = fx.received_recondition_job(api)

    response = api.inspect_recondition_job(
        state["job"]["id"],
        f.inspect_job_payload(
            units_inspected=11, measured_length_mm=90.0, measured_corner_wear_um=120.0
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_COUNT_MISMATCH, 422)
    job = validate_success(api.get_recondition_job(state["job"]["id"], PLAN))
    assert_recondition_job(job)
    assert job["status"] == "RECEIVED", (
        f"the refused inspection leaves the job at intake, got {job['status']}"
    )
    assert job["units_inspected"] is None, (
        f"no inspected count was recorded, got {job['units_inspected']}"
    )


# ─── The dossier gates, in their fixed order ─────────────────────────────────

_WEAK_CURVE = [
    {"minutes": 0, "vb_um": 0},
    {"minutes": 5, "vb_um": 140},
    {"minutes": 10, "vb_um": 230},
    {"minutes": 15, "vb_um": 300},
]


def _submitted_dossier_of_three_weak_trials(api) -> dict:
    """Three FAIL trials rating 15.0 minutes at Ra 3.00, so the score is 0.71."""
    state = fx.product_in_qualification(api, coated=False)
    dossier = validate_success(
        api.create_qualification_dossier(
            f.dossier_payload(
                state["product"]["id"], dossier_code="DOS-A", required_trial_count=3
            ),
            APP,
        ),
        201,
    )
    trials = []
    for code, payload in (
        ("A-P", f.trial_payload(dossier["id"], state["batch"]["id"], trial_code="A-P")),
        (
            "A-M",
            f.second_trial_payload(
                dossier["id"], state["batch"]["id"], trial_code="A-M"
            ),
        ),
        (
            "A-K",
            f.trial_payload(
                dossier["id"],
                state["batch"]["id"],
                trial_code="A-K",
                workpiece_material_code="GG25",
                workpiece_group="K",
                cutting_speed_vc=160.0,
                feed_fz=0.20,
            ),
        ),
    ):
        trial = validate_success(api.create_machining_trial(payload, OPERATOR_ONE), 201)
        trials.append(
            validate_success(
                api.complete_machining_trial(
                    trial["id"],
                    f.complete_trial_payload(
                        wear_measurements=_WEAK_CURVE, measured_surface_ra_um=3.00
                    ),
                    OPERATOR_ONE,
                )
            )
        )
        assert trials[-1]["trial_code"] == code
    state["dossier"] = validate_success(
        api.submit_qualification_dossier(dossier["id"], SUBMITTER)
    )
    state["trials"] = trials
    return state


def _submitted_dossier_of_two_passes_on_one_group(api) -> dict:
    """Two PASS trials, both on group P, each scoring 1.20."""
    state = fx.product_in_qualification(api, coated=False)
    dossier = validate_success(
        api.create_qualification_dossier(
            f.dossier_payload(state["product"]["id"], dossier_code="DOS-B"), APP
        ),
        201,
    )
    for code, material in (("B-P1", "C45E"), ("B-P2", "42CrMo4")):
        trial = validate_success(
            api.create_machining_trial(
                f.trial_payload(
                    dossier["id"],
                    state["batch"]["id"],
                    trial_code=code,
                    workpiece_material_code=material,
                ),
                OPERATOR_TWO,
            ),
            201,
        )
        validate_success(
            api.complete_machining_trial(
                trial["id"], f.complete_trial_payload(), OPERATOR_TWO
            )
        )
    state["dossier"] = validate_success(
        api.submit_qualification_dossier(dossier["id"], SUBMITTER)
    )
    return state


def test_a_dossier_with_no_trials_at_all_cannot_be_submitted(api):
    """Zero completed trials against a required two is a shortfall at submission.

    PRD §2.11: "35. **Dossier trial count met.** → `ERR_INSUFFICIENT_TRIALS`, on
    dossier submission."

    PRD §3.7: "It requires the dossier to be `OPEN`, the product's
    `release_status` to still be `QUALIFICATION`, and `completed_trial_count` to
    be at least `required_trial_count` — a shortfall is
    `ERR_INSUFFICIENT_TRIALS`, and note that this gate counts *completed* trials
    of any verdict, not passed ones."

    Design: Corner/validations/dossier_submission_and_approval_gates_fire_in_priority_order
    """
    state = fx.open_dossier(api, coated=False)

    response = api.submit_qualification_dossier(state["dossier"]["id"], SUBMITTER)

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_TRIALS, 409)
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["status"] == "OPEN", (
        f"the refused submission leaves the dossier open, got {dossier['status']}"
    )
    assert dossier["completed_trial_count"] == 0, (
        f"no trial has been closed out, got {dossier['completed_trial_count']}"
    )
    assert dossier["composite_score"] is None, (
        f"an empty dossier has no score, got {dossier['composite_score']}"
    )


def test_a_submitted_dossier_refuses_a_further_trial(api):
    """Once the folder is closed, a fourth trial cannot be filed into it.

    PRD §3.6: "Trials may be opened only while the dossier is `OPEN`; once it has
    been submitted, no further trial may be added, and the attempt is rejected
    with `ERR_INVALID_DOSSIER_STATE`."

    Design: Corner/validations/dossier_submission_and_approval_gates_fire_in_priority_order
    """
    state = _submitted_dossier_of_three_weak_trials(api)
    assert state["dossier"]["status"] == "SUBMITTED", (
        f"three completed trials meet a required three, got {state['dossier']['status']}"
    )

    response = api.create_machining_trial(
        f.trial_payload(
            state["dossier"]["id"], state["batch"]["id"], trial_code="A-LATE"
        ),
        OPERATOR_ONE,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_DOSSIER_STATE, 409)
    trials, _meta = validate_paginated(api.list_machining_trials(APP))
    assert_no_row_with_code(trials, "trial_code", "A-LATE")
    assert len(trials) == 3, (
        f"the dossier still carries exactly its three trials, got {len(trials)}"
    )


def test_an_under_scored_dossier_is_told_about_the_score_and_not_the_coverage(api):
    """Three FAIL trials score 0.71 and prove no group, and 36 fires before 37.

    PRD §2.11: "36. **Dossier composite score met.** →
    `ERR_COMPOSITE_SCORE_BELOW_MINIMUM`, on dossier approval."

    PRD §3.7: "First the score: if `composite_score` is null, or is strictly less
    than 1.00, the request is rejected with
    `ERR_COMPOSITE_SCORE_BELOW_MINIMUM`."

    PRD §3.6: "The `verdict` is `PASS` when all three of the following hold:
    `censored` is false, `rated_life_min` is at least the required life for the
    class, and `measured_surface_ra_um` is at most the maximum for the class."

    PRD §3.6: "For each such trial, taken in ascending `created_at` order, a life
    ratio is formed as `rated_life_min` divided by the class's required life,
    capped at 2.0; a finish ratio is formed as the class's maximum roughness
    divided by `measured_surface_ra_um`, also capped at 2.0; and a per-trial
    subscore is 0.6 multiplied by the life ratio plus 0.4 multiplied by the
    finish ratio, **rounded half up to two decimal places at that point**."

    Design: Corner/validations/dossier_submission_and_approval_gates_fire_in_priority_order
    """
    state = _submitted_dossier_of_three_weak_trials(api)

    for trial in state["trials"]:
        assert_machining_trial(trial)
        assert trial["rated_life_min"] == 15.0, (
            "the curve reaches 300 um exactly at 15 minutes, got "
            f"{trial['rated_life_min']}"
        )
        assert trial["censored"] is False, (
            f"the curve does reach the wear limit, got {trial['censored']}"
        )
        assert trial["verdict"] == "FAIL", (
            "15.0 minutes is short of the 18.0 required for MEDIUM and Ra 3.00 "
            f"is over its 1.6 maximum, got {trial['verdict']}"
        )
    assert state["dossier"]["composite_score"] == 0.71, (
        "0.6 x 15.0/18.0 plus 0.4 x 1.6/3.00 rounds to 0.71 per trial, got "
        f"{state['dossier']['composite_score']}"
    )

    response = api.approve_qualification_dossier(
        state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
    )

    validate_error(response, ApiErrorId.ERR_COMPOSITE_SCORE_BELOW_MINIMUM, 409)
    dossier = validate_success(
        api.get_qualification_dossier(state["dossier"]["id"], APP)
    )
    assert dossier["status"] == "SUBMITTED", (
        f"the refused approval leaves the dossier submitted, got {dossier['status']}"
    )
    assert dossier["passed_trial_count"] == 0, (
        f"none of the three trials passed, got {dossier['passed_trial_count']}"
    )


def test_a_dossier_proving_one_group_clears_the_score_and_fails_the_coverage(api):
    """Two PASS trials on group P score 1.20 yet leave a single qualified group.

    PRD §2.11: "37. **Workpiece coverage met.** →
    `ERR_INSUFFICIENT_WORKPIECE_COVERAGE`, on dossier approval."

    PRD §3.7: "Second the coverage: if the number of distinct `workpiece_group`
    values across the dossier's `COMPLETED` trials with a `PASS` verdict is fewer
    than 2, the request is rejected with `ERR_INSUFFICIENT_WORKPIECE_COVERAGE` —
    one material, however well it performed, does not qualify a grade."

    Design: Corner/validations/dossier_submission_and_approval_gates_fire_in_priority_order
    """
    state = _submitted_dossier_of_two_passes_on_one_group(api)
    assert state["dossier"]["composite_score"] == 1.20, (
        "two trials rating 20.0 minutes at Ra 1.20 each score 1.20, got "
        f"{state['dossier']['composite_score']}"
    )
    assert state["dossier"]["passed_trial_count"] == 2, (
        f"both trials passed on their own merits, got {state['dossier']['passed_trial_count']}"
    )

    response = api.approve_qualification_dossier(
        state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_WORKPIECE_COVERAGE, 409)
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["release_status"] == "QUALIFICATION", (
        f"the product is not promoted by a refused approval, got {product['release_status']}"
    )
    assert product["tool_life_index"] is None, (
        f"no tool life index is written, got {product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == [], (
        f"no group is recorded as qualified, got {product['qualified_workpiece_groups']}"
    )


# ─── Batch units as an aggregate over the trials already drawn ───────────────

def test_a_trial_may_not_draw_more_tools_than_the_batch_holds(api):
    """50 requested against 40 remaining is refused and consumes nothing.

    PRD §2.11: "34. **Batch units available.** → `ERR_INSUFFICIENT_BATCH_UNITS`,
    on trial creation."

    PRD §3.6: "The supplying batch must have `qc_status` `PASSED` and `stage`
    `SINTERED` or `CONSUMED`, otherwise `ERR_BATCH_QC_NOT_PASSED`, and
    `units_consumed` must not exceed the batch's `remaining_units`, otherwise
    `ERR_INSUFFICIENT_BATCH_UNITS`."

    Design: Corner/validations/trial_creation_cannot_draw_more_tools_than_the_batch_holds
    """
    state = fx.open_dossier(api, coated=False)
    small = fx.small_passed_batch(api, state["grade"]["id"], 40, batch_code="BLD-S1")

    response = api.create_machining_trial(
        f.trial_payload(
            state["dossier"]["id"],
            small["id"],
            trial_code="TRL-BIG",
            units_consumed=50,
        ),
        OPERATOR_ONE,
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_BATCH_UNITS, 409)
    trials, _meta = validate_paginated(api.list_machining_trials(APP))
    assert_no_row_with_code(trials, "trial_code", "TRL-BIG")
    batch = validate_success(api.get_powder_blend_batch(small["id"], MET))
    assert batch["remaining_units"] == 40, (
        f"the refused trial drew nothing from the batch, got {batch['remaining_units']}"
    )


def test_a_trial_may_draw_the_entire_remaining_balance_and_exhaust_the_batch(api):
    """40 requested against 40 remaining is accepted and consumes the batch.

    PRD §3.6: "On creation the trial opens at `status` `RUNNING`, records
    `operator_user_id` from the calling `X-User-ID`, reduces the batch's
    `remaining_units` by `units_consumed`, and — when that reduction brings
    `remaining_units` to 0 — advances the batch's `stage` to `CONSUMED`."

    Design: Corner/validations/trial_creation_cannot_draw_more_tools_than_the_batch_holds
    """
    state = fx.open_dossier(api, coated=False)
    small = fx.small_passed_batch(api, state["grade"]["id"], 40, batch_code="BLD-S2")

    response = api.create_machining_trial(
        f.trial_payload(
            state["dossier"]["id"],
            small["id"],
            trial_code="TRL-ALL",
            units_consumed=40,
        ),
        OPERATOR_ONE,
    )

    trial = validate_success(response, 201)
    assert_machining_trial(trial)
    assert trial["status"] == "RUNNING", (
        f"a trial drawing the whole balance is legitimate, got {trial['status']}"
    )
    assert trial["units_consumed"] == 40, (
        f"the whole remaining balance is drawn, got {trial['units_consumed']}"
    )
    batch = validate_success(api.get_powder_blend_batch(small["id"], MET))
    assert batch["remaining_units"] == 0, (
        f"nothing is left in the batch, got {batch['remaining_units']}"
    )
    assert batch["stage"] == "CONSUMED", (
        f"a batch drawn to zero advances to consumed, got {batch['stage']}"
    )


def test_an_exhausted_batch_cannot_supply_even_one_tool(api):
    """With remaining_units at 0 a single-tool request is refused as well.

    PRD §3.6: "The supplying batch must have `qc_status` `PASSED` and `stage`
    `SINTERED` or `CONSUMED`, otherwise `ERR_BATCH_QC_NOT_PASSED`, and
    `units_consumed` must not exceed the batch's `remaining_units`, otherwise
    `ERR_INSUFFICIENT_BATCH_UNITS`."

    Design: Corner/validations/trial_creation_cannot_draw_more_tools_than_the_batch_holds
    """
    state = fx.open_dossier(api, coated=False)
    small = fx.small_passed_batch(api, state["grade"]["id"], 40, batch_code="BLD-S3")
    validate_success(
        api.create_machining_trial(
            f.trial_payload(
                state["dossier"]["id"],
                small["id"],
                trial_code="TRL-ALL",
                units_consumed=40,
            ),
            OPERATOR_ONE,
        ),
        201,
    )

    response = api.create_machining_trial(
        f.second_trial_payload(
            state["dossier"]["id"],
            small["id"],
            trial_code="TRL-ONE",
            units_consumed=1,
        ),
        OPERATOR_TWO,
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_BATCH_UNITS, 409)
    trials, _meta = validate_paginated(api.list_machining_trials(APP))
    assert_no_row_with_code(trials, "trial_code", "TRL-ONE")
    assert len(trials) == 1, (
        f"only the exhausting trial stands, got {len(trials)} trials"
    )


# ─── The account gate before the money gate at intake ────────────────────────

def test_an_account_on_credit_hold_is_refused_before_its_balance_is_examined(api):
    """A balance of -10000 is both a hold and a shortfall, and 42 precedes 43.

    PRD §2.11: "42. **Customer account orderable.** → `ERR_CUSTOMER_CREDIT_HOLD`
    (HTTP 402) when the account is on credit hold and `ERR_CUSTOMER_CLOSED` (HTTP
    409) when it is closed, on order submission and reconditioning-job intake."

    PRD §3.8: "If the resulting balance is below 0 while the account is
    `ACTIVE`, `account_status` moves `ACTIVE` → `CREDIT_HOLD`"

    Design: Corner/validations/customer_account_state_gates_recondition_intake_before_credit
    """
    state = fx.endmill_product(api)
    held = fx.customer(
        api, customer_code="CU-H", name="Held Tooling", tier="STANDARD"
    )
    validate_success(
        api.create_credit_adjustment(
            held["id"],
            f.credit_adjustment_payload(
                -60000, reason="Charge-back on an unpaid reconditioning invoice"
            ),
            PLAN,
        )
    )
    held = validate_success(api.get_customer(held["id"], PLAN))
    assert held["regrind_credit_cents"] == -10000, (
        f"50000 less 60000 leaves the balance at -10000, got {held['regrind_credit_cents']}"
    )
    assert held["account_status"] == "CREDIT_HOLD", (
        f"a negative balance puts the account on hold, got {held['account_status']}"
    )

    response = api.create_recondition_job(
        f.recondition_job_payload(
            held["id"], state["product"]["id"], held["version"], job_code="RJ-H"
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD, 402)
    jobs, _meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert len(jobs) == 0, (
        f"the refused intake must not have opened a job, got {len(jobs)}"
    )
    after = validate_success(api.get_customer(held["id"], PLAN))
    assert after["reserved_credit_cents"] == 0, (
        f"no credit was reserved, got {after['reserved_credit_cents']}"
    )
    assert after["regrind_credit_cents"] == -10000, (
        f"the balance is untouched by the refusal, got {after['regrind_credit_cents']}"
    )


def test_an_active_account_with_too_little_credit_is_refused_on_the_money_gate(api):
    """10 tools reserve 18500 cents, which a 10000-cent balance cannot cover.

    PRD §2.11: "43. **Regrind credit sufficient.** →
    `ERR_INSUFFICIENT_REGRIND_CREDIT` (HTTP 402), on reconditioning-job intake."

    PRD §3.9: "And the intake must be prepaid: the reservation of
    `units_received` multiplied by 1850 cents must not exceed the customer's
    `regrind_credit_cents`, otherwise `ERR_INSUFFICIENT_REGRIND_CREDIT`."

    Design: Corner/validations/customer_account_state_gates_recondition_intake_before_credit
    """
    state = fx.endmill_product(api)
    lean = fx.customer(
        api,
        customer_code="CU-L",
        name="Lean Tooling",
        tier="STANDARD",
        regrind_credit_cents=10000,
    )

    response = api.create_recondition_job(
        f.recondition_job_payload(
            lean["id"], state["product"]["id"], lean["version"], job_code="RJ-L"
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_REGRIND_CREDIT, 402)
    customer = validate_success(api.get_customer(lean["id"], PLAN))
    assert customer["account_status"] == "ACTIVE", (
        "the account is solvent enough to stay active, it is merely too thin "
        f"for this job, got {customer['account_status']}"
    )
    assert customer["regrind_credit_cents"] == 10000, (
        f"the balance is untouched, got {customer['regrind_credit_cents']}"
    )
    assert_credit_conserved(customer, 10000)
    jobs, _meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert len(jobs) == 0, (
        f"the refused intake must not have opened a job, got {len(jobs)}"
    )


def test_a_closed_account_is_refused_outright_however_well_funded(api):
    """50000 cents of credit does not reopen a closed account for intake.

    PRD §2.11: "42. **Customer account orderable.** → `ERR_CUSTOMER_CREDIT_HOLD`
    (HTTP 402) when the account is on credit hold and `ERR_CUSTOMER_CLOSED` (HTTP
    409) when it is closed, on order submission and reconditioning-job intake."

    PRD §3.8: "`CLOSED` is terminal and advances the customer's `version` by 1."

    Design: Corner/validations/customer_account_state_gates_recondition_intake_before_credit
    """
    state = fx.endmill_product(api)
    exited = fx.customer(
        api, customer_code="CU-X", name="Exited Tooling", tier="STANDARD"
    )
    exited = validate_success(
        api.close_customer(
            exited["id"],
            f.close_customer_payload(close_reason="Customer left the programme"),
            PLAN,
        )
    )
    assert exited["account_status"] == "CLOSED", (
        f"the account is closed before the intake attempt, got {exited['account_status']}"
    )

    response = api.create_recondition_job(
        f.recondition_job_payload(
            exited["id"], state["product"]["id"], exited["version"], job_code="RJ-X"
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_CLOSED, 409)
    customer = validate_success(api.get_customer(exited["id"], PLAN))
    assert customer["regrind_credit_cents"] == 50000, (
        f"the funded balance is untouched, got {customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 0, (
        f"nothing was reserved against a closed account, got {customer['reserved_credit_cents']}"
    )


# ─── Reconditioning eligibility, gate by gate and stage by stage ─────────────

def _mill_job_and_a_matching_insert(api) -> dict:
    """A RECEIVED job on the end mill, plus an INSERT product on the same rows."""
    state = fx.received_recondition_job(api)
    state["insert"] = validate_success(
        api.create_tool_product(
            f.tool_product_payload(state["grade"]["id"], state["geometry"]["id"]), GEO
        ),
        201,
    )
    return state


def test_an_insert_can_never_be_taken_in_for_reconditioning(api):
    """Regrindability is decided at intake from the product's own tool type.

    PRD §2.11: "23. **Product regrindable.** → `ERR_PRODUCT_NOT_REGRINDABLE`, on
    reconditioning-job intake."

    PRD §3.9: "The product must be regrindable: a job on a product whose
    `tool_type` is `INSERT`, or whose `min_regrind_length_mm` is not strictly
    below its `nominal_length_mm`, is rejected with
    `ERR_PRODUCT_NOT_REGRINDABLE`."

    Design: Corner/validations/recondition_eligibility_conditions_are_checked_per_stage
    """
    state = _mill_job_and_a_matching_insert(api)

    response = api.create_recondition_job(
        f.recondition_job_payload(
            state["customer"]["id"],
            state["insert"]["id"],
            fx.current_customer_version(api, state["customer"]["id"]),
            job_code="RJ-INS",
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_REGRINDABLE, 409)
    jobs, _meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert_no_row_with_code(jobs, "job_code", "RJ-INS")
    assert len(jobs) == 1, (
        f"only the end-mill job stands, got {len(jobs)} jobs"
    )


def test_a_predecessor_that_has_not_been_returned_breaks_the_chain(api):
    """A second pass may only follow a pass that has actually been handed back.

    PRD §2.11: "24. **Predecessor chain valid.** →
    `ERR_INVALID_PREDECESSOR_CHAIN`, on reconditioning-job intake."

    PRD §3.9: "A supplied `predecessor_job_id` must name a job that is in
    `RETURNED`, belongs to the same `customer_id` and the same `product_id`, and
    is not already the predecessor of some other job — one pass may have only one
    successor — and any of those failures is `ERR_INVALID_PREDECESSOR_CHAIN`."

    Design: Corner/validations/recondition_eligibility_conditions_are_checked_per_stage
    """
    state = fx.received_recondition_job(api)
    assert state["job"]["status"] == "RECEIVED", (
        f"the predecessor is still at intake, got {state['job']['status']}"
    )

    response = api.create_recondition_job(
        f.recondition_job_payload(
            state["customer"]["id"],
            state["product"]["id"],
            fx.current_customer_version(api, state["customer"]["id"]),
            predecessor_job_id=state["job"]["id"],
            job_code="RJ-2",
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_PREDECESSOR_CHAIN, 409)
    jobs, _meta = validate_paginated(api.list_recondition_jobs(PLAN))
    assert_no_row_with_code(jobs, "job_code", "RJ-2")
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["reserved_credit_cents"] == 18500, (
        "only the standing job's reservation is held, got "
        f"{customer['reserved_credit_cents']}"
    )


def test_a_tool_measured_just_above_the_floor_has_no_passes_left_to_grind(api):
    """71.0 mm leaves 0 whole passes yet is not scrap, and refurbish is refused.

    PRD §2.11: "40. **Refurbish requires remaining regrinds.** →
    `ERR_NO_REGRINDS_REMAINING`, on reconditioning refurbish."

    PRD §3.9: "`remaining_regrinds` is the whole number of passes left, computed
    as `measured_length_mm` minus the product's `min_regrind_length_mm`, divided
    by the product's `regrind_step_mm`, rounded **down** to a whole number, and
    then floored at 0 so it is never negative."

    PRD §3.9: "And `scrap_recommended` is true exactly when `measured_length_mm`
    is strictly below the product's `min_regrind_length_mm`."

    PRD §3.9: "The job must be `INSPECTED`, `scrap_recommended` must be false and
    `remaining_regrinds` must be at least 1 — a failure of either is
    `ERR_NO_REGRINDS_REMAINING`."

    Design: Corner/validations/recondition_eligibility_conditions_are_checked_per_stage
    """
    state = fx.inspected_recondition_job(
        api,
        inspect_overrides={
            "measured_length_mm": 71.0,
            "measured_corner_wear_um": 260.0,
        },
    )
    wheel = fx.grinding_wheel(api, wheel_code="WH-6", initial_life_units=100000)

    job = state["job"]
    assert_recondition_job(job)
    assert job["remaining_regrinds"] == 0, (
        "71.0 less 70.0 over 2.5 is 0.4, which rounds down to no pass at all, "
        f"got {job['remaining_regrinds']}"
    )
    assert job["life_extension_pct"] == 0.0, (
        f"no remaining pass recovers no life, got {job['life_extension_pct']}"
    )
    assert job["scrap_recommended"] is False, (
        "71.0 mm is not strictly below the 70.0 mm floor, so the tool is not "
        f"scrap, got {job['scrap_recommended']}"
    )
    assert job["warranted_life_extension_pct"] == 35.0, (
        "the contractual figure reads only the first pass, got "
        f"{job['warranted_life_extension_pct']}"
    )

    response = api.refurbish_recondition_job(
        job["id"], f.refurbish_job_payload(wheel["id"]), PLAN
    )

    validate_error(response, ApiErrorId.ERR_NO_REGRINDS_REMAINING, 409)
    standing = validate_success(api.get_recondition_job(job["id"], PLAN))
    assert standing["status"] == "INSPECTED", (
        f"the refused refurbishment leaves the job inspected, got {standing['status']}"
    )
    assert standing["wheel_id"] is None, (
        f"no wheel was mounted for the refused job, got {standing['wheel_id']}"
    )
    ground = validate_success(api.get_grinding_wheel(wheel["id"], PLAN))
    assert ground["consumed_life_units"] == 0, (
        f"the refused refurbishment charged nothing, got {ground['consumed_life_units']}"
    )
