"""Composite state builders.

Every builder drives the public API only — there is no direct database access
— and each one returns the rows it created so a test can assert against them.
The builders compose: ``released_product`` calls ``product_in_qualification``,
which calls ``pilot_grade_with_passed_batch`` and ``released_geometry``.

Two spines run through this module. The **insert spine** walks the whole
qualification route (grade, blend batch, geometry, coating recipe and proven
chamber run, product, dossier, two trials, approval, release) and ends in a
priced order. The **end-mill spine** builds a regrindable solid-carbide tool
with its grinding wheel and reconditioning job, and needs no qualification at
all.

Identity matters in the dossier chain: the two trials are run by ``op-1`` and
``op-2``, the dossier is submitted by ``ae-7`` and decided by ``qa-3``, so the
decider is independent of the submitter and of every trial operator.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    DOSSIER_SUBMITTER,
    INDEPENDENT_APPROVER,
    TRIAL_OPERATOR_ONE,
    TRIAL_OPERATOR_TWO,
)
from .test_users import (
    TEST_USERS,
    make_application_engineer_headers,
    make_quality_approver_headers,
)

MET = TEST_USERS["metallurgy_engineer_headers"]
GEO = TEST_USERS["geometry_engineer_headers"]
COAT = TEST_USERS["coating_engineer_headers"]
APP = TEST_USERS["application_engineer_headers"]
QUAL = TEST_USERS["quality_approver_headers"]
PLAN = TEST_USERS["production_planner_headers"]

OPERATOR_ONE = make_application_engineer_headers(TRIAL_OPERATOR_ONE)
OPERATOR_TWO = make_application_engineer_headers(TRIAL_OPERATOR_TWO)
SUBMITTER = make_application_engineer_headers(DOSSIER_SUBMITTER)
APPROVER = make_quality_approver_headers(INDEPENDENT_APPROVER)


# ─── Clock and version helpers ──────────────────────────────────────────────

def advance_clock(api, current_utc: str) -> dict:
    """Reposition the logical shop clock to an explicit UTC instant."""
    return get_success_data(api.set_current_utc(current_utc, PLAN))


def current_product_version(api, product_id: str) -> int:
    """Re-read a product and return its current ``version`` for an order quote."""
    return get_success_data(api.get_tool_product(product_id, APP))["version"]


def current_customer_version(api, customer_id: str) -> int:
    """Re-read a customer and return its current ``version`` for a job intake."""
    return get_success_data(api.get_customer(customer_id, PLAN))["version"]


# ─── Tier 1: single rows ────────────────────────────────────────────────────

def carbide_grade(api, **overrides) -> dict:
    """A DRAFT carbide grade at revision 1."""
    return get_success_data(
        api.create_carbide_grade(f.carbide_grade_payload(**overrides), MET)
    )


def insert_geometry(api, **overrides) -> dict:
    """A DRAFT insert geometry at revision 1."""
    return get_success_data(
        api.create_insert_geometry(f.insert_geometry_payload(**overrides), GEO)
    )


def released_geometry(api, **overrides) -> dict:
    """An insert geometry advanced to RELEASED so products may be built on it."""
    geometry = insert_geometry(api, **overrides)
    return get_success_data(api.release_insert_geometry(geometry["id"], GEO))


def coating_recipe(api, **overrides) -> dict:
    """An unproven PVD recipe: ``is_validated`` false, ``adhesion_class`` null."""
    return get_success_data(
        api.create_coating_recipe(f.coating_recipe_payload(**overrides), COAT)
    )


def grinding_wheel(api, **overrides) -> dict:
    """An AVAILABLE wheel with its abrasive life untouched."""
    return get_success_data(
        api.create_grinding_wheel(f.grinding_wheel_payload(**overrides), PLAN)
    )


def customer(api, **overrides) -> dict:
    """An ACTIVE customer with opening reconditioning credit."""
    return get_success_data(api.create_customer(f.customer_payload(**overrides), PLAN))


# ─── Tier 2: the powder route ───────────────────────────────────────────────

def passed_batch(
    api,
    grade_id: str,
    *,
    press_overrides=None,
    sinter_overrides=None,
    **batch_overrides,
) -> dict:
    """A blend batch pressed to 200 units and sintered to a PASSED QC verdict.

    ``press_overrides`` and ``sinter_overrides`` let a caller size the batch
    smaller, so that a legal ``units_consumed`` (at most 50 per PRD 3.6) can
    still exceed the batch's ``remaining_units``.
    """
    batch = get_success_data(
        api.create_powder_blend_batch(
            f.powder_blend_batch_payload(grade_id, **batch_overrides), MET
        )
    )
    get_success_data(
        api.press_powder_blend_batch(
            batch["id"], f.press_payload(**(press_overrides or {})), MET
        )
    )
    return get_success_data(
        api.sinter_powder_blend_batch(
            batch["id"], f.sinter_payload(**(sinter_overrides or {})), MET
        )
    )


def small_passed_batch(api, grade_id: str, units: int = 40, **batch_overrides) -> dict:
    """A PASSED, SINTERED batch holding exactly ``units`` remaining units."""
    return passed_batch(
        api,
        grade_id,
        press_overrides={"pressed_units": units},
        sinter_overrides={"sintered_units": units, "scrap_units": 0},
        **batch_overrides,
    )


def failed_batch(api, grade_id: str, **batch_overrides) -> dict:
    """A blend batch whose sintered density of 14.34 fails the QC minimum."""
    overrides = {"batch_code": "BLD-B"}
    overrides.update(batch_overrides)
    batch = get_success_data(
        api.create_powder_blend_batch(
            f.powder_blend_batch_payload(grade_id, **overrides), MET
        )
    )
    get_success_data(api.press_powder_blend_batch(batch["id"], f.press_payload(), MET))
    return get_success_data(
        api.sinter_powder_blend_batch(batch["id"], f.failing_sinter_payload(), MET)
    )


def pilot_grade_with_passed_batch(api, **grade_overrides) -> dict:
    """A grade advanced to PILOT on the evidence of one PASSED, SINTERED batch."""
    grade = carbide_grade(api, **grade_overrides)
    batch = passed_batch(api, grade["id"])
    grade = get_success_data(api.start_grade_pilot(grade["id"], MET))
    return {"grade": grade, "batch": batch}


# ─── Tier 2: the coating route ──────────────────────────────────────────────

def validated_pvd_recipe(api, **recipe_overrides) -> dict:
    """A PVD recipe proven in the chamber: adhesion class 2 at 3.10 um measured.

    The chamber window must have elapsed before the run can be closed out, so
    the clock is moved to the window end before completion.
    """
    recipe = coating_recipe(api, **recipe_overrides)
    run = get_success_data(
        api.create_coating_run(f.coating_run_payload(recipe["id"]), COAT)
    )
    advance_clock(api, run["window_end"])
    run = get_success_data(
        api.complete_coating_run(run["id"], f.complete_coating_run_payload(), COAT)
    )
    recipe = get_success_data(api.get_coating_recipe(recipe["id"], COAT))
    return {"recipe": recipe, "coating_run": run}


# ─── Tier 3: products ───────────────────────────────────────────────────────

def product_in_qualification(api, *, coated: bool = True, **product_overrides) -> dict:
    """A catalogue insert moved DEVELOPMENT -> QUALIFICATION with its pins taken.

    With ``coated`` true the product references a validated PVD recipe; with it
    false the product has no coating at all.
    """
    pilot = pilot_grade_with_passed_batch(api)
    geometry = released_geometry(api)
    recipe = None
    coating_run = None
    if coated:
        proven = validated_pvd_recipe(api)
        recipe = proven["recipe"]
        coating_run = proven["coating_run"]
        product_overrides.setdefault("coating_recipe_id", recipe["id"])
    product = get_success_data(
        api.create_tool_product(
            f.tool_product_payload(
                pilot["grade"]["id"], geometry["id"], **product_overrides
            ),
            GEO,
        )
    )
    product = get_success_data(api.enter_product_qualification(product["id"], APP))
    return {
        "grade": pilot["grade"],
        "batch": pilot["batch"],
        "geometry": geometry,
        "recipe": recipe,
        "coating_run": coating_run,
        "product": product,
    }


# ─── Tier 4: dossiers and trials ────────────────────────────────────────────

def open_dossier(api, *, coated: bool = True, **product_overrides) -> dict:
    """A product in QUALIFICATION with an OPEN dossier and no trials yet."""
    state = product_in_qualification(api, coated=coated, **product_overrides)
    state["dossier"] = get_success_data(
        api.create_qualification_dossier(f.dossier_payload(state["product"]["id"]), APP)
    )
    return state


def dossier_with_two_passed_trials(api, *, coated: bool = True, **product_overrides) -> dict:
    """An OPEN dossier carrying two COMPLETED, PASS trials on groups P and M.

    The trials are run by two different operators so that a third user can
    later decide the dossier without breaching the independence rule.
    """
    state = open_dossier(api, coated=coated, **product_overrides)
    dossier_id = state["dossier"]["id"]
    batch_id = state["batch"]["id"]

    trial_one = get_success_data(
        api.create_machining_trial(f.trial_payload(dossier_id, batch_id), OPERATOR_ONE)
    )
    trial_one = get_success_data(
        api.complete_machining_trial(
            trial_one["id"], f.complete_trial_payload(), OPERATOR_ONE
        )
    )
    trial_two = get_success_data(
        api.create_machining_trial(
            f.second_trial_payload(dossier_id, batch_id), OPERATOR_TWO
        )
    )
    trial_two = get_success_data(
        api.complete_machining_trial(
            trial_two["id"], f.complete_second_trial_payload(), OPERATOR_TWO
        )
    )
    state["trial_one"] = trial_one
    state["trial_two"] = trial_two
    state["dossier"] = get_success_data(api.get_qualification_dossier(dossier_id, APP))
    return state


def submitted_dossier(api, *, coated: bool = True, **product_overrides) -> dict:
    """A dossier in SUBMITTED, awaiting an independent quality decision."""
    state = dossier_with_two_passed_trials(api, coated=coated, **product_overrides)
    state["dossier"] = get_success_data(
        api.submit_qualification_dossier(state["dossier"]["id"], SUBMITTER)
    )
    return state


def approved_dossier(api, *, coated: bool = True, **product_overrides) -> dict:
    """A dossier APPROVED by a user who neither submitted nor ran any trial."""
    state = submitted_dossier(api, coated=coated, **product_overrides)
    state["dossier"] = get_success_data(
        api.approve_qualification_dossier(
            state["dossier"]["id"], f.approve_dossier_payload(), APPROVER
        )
    )
    state["grade"] = get_success_data(api.get_carbide_grade(state["grade"]["id"], MET))
    state["product"] = get_success_data(
        api.get_tool_product(state["product"]["id"], APP)
    )
    return state


# ─── Tier 5: released products, customers and orders ────────────────────────

def released_product(api, *, coated: bool = True, **product_overrides) -> dict:
    """A catalogue insert at release_status RELEASED and supply_status STOCKED."""
    state = approved_dossier(api, coated=coated, **product_overrides)
    state["product"] = get_success_data(
        api.release_tool_product(state["product"]["id"], APPROVER)
    )
    state["grade"] = get_success_data(api.get_carbide_grade(state["grade"]["id"], MET))
    return state


def released_product_with_customer(
    api, *, coated: bool = True, customer_overrides=None, **product_overrides
) -> dict:
    """A released catalogue insert plus an ACTIVE customer able to buy it."""
    state = released_product(api, coated=coated, **product_overrides)
    state["customer"] = customer(api, **(customer_overrides or {}))
    return state


def draft_order(
    api,
    *,
    coated: bool = True,
    quantity: int = 100,
    order_overrides=None,
    customer_overrides=None,
    **product_overrides,
) -> dict:
    """A DRAFT order raised against a released catalogue insert."""
    state = released_product_with_customer(
        api, coated=coated, customer_overrides=customer_overrides, **product_overrides
    )
    payload = f.tool_order_payload(
        state["customer"]["id"],
        state["product"]["id"],
        current_product_version(api, state["product"]["id"]),
        quantity=quantity,
        **(order_overrides or {}),
    )
    state["order"] = get_success_data(api.create_tool_order(payload, APP))
    return state


def submitted_order(api, **kwargs) -> dict:
    """A priced order in SUBMITTED with its promised lead time set."""
    state = draft_order(api, **kwargs)
    state["order"] = get_success_data(api.submit_tool_order(state["order"]["id"], APP))
    state["product"] = get_success_data(
        api.get_tool_product(state["product"]["id"], APP)
    )
    return state


def confirmed_order(api, **kwargs) -> dict:
    """An order in CONFIRMED, ready to be driven backwards by a cascade."""
    state = submitted_order(api, **kwargs)
    state["order"] = get_success_data(api.confirm_tool_order(state["order"]["id"], APP))
    return state


# ─── The end-mill spine: grinding and reconditioning ────────────────────────

def endmill_product(api, **product_overrides) -> dict:
    """A regrindable solid-carbide end mill with its K-group grade and geometry."""
    grade = get_success_data(
        api.create_carbide_grade(f.endmill_grade_payload(), MET)
    )
    geometry = get_success_data(
        api.create_insert_geometry(f.endmill_geometry_payload(), GEO)
    )
    product = get_success_data(
        api.create_tool_product(
            f.endmill_product_payload(grade["id"], geometry["id"], **product_overrides),
            GEO,
        )
    )
    return {"grade": grade, "geometry": geometry, "product": product}


def scheduled_grinding_run(api, *, wheel_overrides=None, **run_overrides) -> dict:
    """A SCHEDULED grinding run occupying CELL_A, with no life charged yet."""
    state = endmill_product(api)
    state["wheel"] = grinding_wheel(api, **(wheel_overrides or {}))
    state["run"] = get_success_data(
        api.create_grinding_run(
            f.grinding_run_payload(
                state["wheel"]["id"], state["product"]["id"], **run_overrides
            ),
            PLAN,
        )
    )
    return state


def completed_grinding_run(api, *, wheel_overrides=None, **run_overrides) -> dict:
    """A COMPLETED grinding run that has charged abrasive life to its wheel.

    A run may be closed out only once the logical clock has reached its window
    end, so the clock is moved there first.
    """
    state = scheduled_grinding_run(api, wheel_overrides=wheel_overrides, **run_overrides)
    advance_clock(api, state["run"]["window_end"])
    state["run"] = get_success_data(
        api.complete_grinding_run(
            state["run"]["id"], f.complete_grinding_run_payload(), PLAN
        )
    )
    state["wheel"] = get_success_data(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    return state


def received_recondition_job(
    api, *, customer_overrides=None, job_overrides=None, **product_overrides
) -> dict:
    """A first-pass reconditioning job in RECEIVED with its intake reserved."""
    state = endmill_product(api, **product_overrides)
    state["customer"] = customer(api, **(customer_overrides or {}))
    payload = f.recondition_job_payload(
        state["customer"]["id"],
        state["product"]["id"],
        state["customer"]["version"],
        **(job_overrides or {}),
    )
    state["job"] = get_success_data(api.create_recondition_job(payload, PLAN))
    state["customer"] = get_success_data(
        api.get_customer(state["customer"]["id"], PLAN)
    )
    return state


def inspected_recondition_job(api, *, inspect_overrides=None, **kwargs) -> dict:
    """A reconditioning job in INSPECTED with both life-extension figures set."""
    state = received_recondition_job(api, **kwargs)
    state["job"] = get_success_data(
        api.inspect_recondition_job(
            state["job"]["id"], f.inspect_job_payload(**(inspect_overrides or {})), PLAN
        )
    )
    return state


def refurbished_recondition_job(api, *, wheel_overrides=None, **kwargs) -> dict:
    """A reconditioning job in REFURBISHED, ground on an AVAILABLE wheel."""
    state = inspected_recondition_job(api, **kwargs)
    state["wheel"] = grinding_wheel(
        api, **({"initial_life_units": 100000} | (wheel_overrides or {}))
    )
    state["job"] = get_success_data(
        api.refurbish_recondition_job(
            state["job"]["id"], f.refurbish_job_payload(state["wheel"]["id"]), PLAN
        )
    )
    return state
