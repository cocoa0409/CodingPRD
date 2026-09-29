"""Composite setup helpers.

Every test starts against an empty database, so each helper builds all of its
preconditions from scratch through the documented endpoints. Helpers are
layered: each one accepts (and returns) a mutable ``world`` dictionary, and
builds its own prerequisites when none is supplied.

The two dominant chains are:

* the food-contact chain -- three-layer barrier recipe on a food-certified
  line, through extrusion, roll release, printing, bag converting, seal
  qualification, packout, dossier issue, release and shipment;
* the non-food chain -- single-layer recipe on an uncertified line, whose
  completion generates regrind that a second run can draw back down.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _default_client
from .constants import CLOCK_D1_0600, CLOCK_D1_1500, CLOCK_D2_0600
from .factories import (
    additive_grade_payload,
    barrier_grade_payload,
    create_bag_lot_payload,
    create_blend_recipe_payload,
    create_compliance_dossier_payload,
    create_component_payload,
    create_extrusion_line_payload,
    create_extrusion_run_payload,
    create_film_roll_payload,
    create_plate_set_payload,
    create_print_job_payload,
    create_print_press_payload,
    create_regrind_pool_payload,
    create_resin_grade_payload,
    create_seal_test_payload,
    food_certified_line_payload,
    food_contact_pool_payload,
    food_contact_product_payload,
    non_food_product_payload,
    tie_grade_payload,
)
from .test_users import TEST_USERS, make_converting_operator_headers, \
    make_quality_manager_headers

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["blend_engineer_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
EXTRUDER = TEST_USERS["extrusion_operator_headers"]
PRINTER = TEST_USERS["print_operator_headers"]
CONVERTER = TEST_USERS["converting_operator_headers"]

SEAL_OPERATOR = make_converting_operator_headers("u-co-1")
ISSUING_MANAGER = make_quality_manager_headers("u-qm-1")


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def set_logical_clock(api, current_utc, headers=ADMIN) -> dict:
    """Move the platform's logical clock."""
    return get_success_data(api.set_clock(current_utc, headers))


def read_pool_version(api, pool_id, headers=EXTRUDER) -> int:
    return get_success_data(api.get_regrind_pool(pool_id, headers))["version"]


def read_bag_lot_version(api, lot_id, headers=CONVERTER) -> int:
    return get_success_data(api.get_bag_lot(lot_id, headers))["version"]


# --------------------------------------------------------------------------
# Tier 2: catalogues
# --------------------------------------------------------------------------
def setup_food_contact_catalog(api=None, clock=CLOCK_D1_0600) -> dict:
    """Food-contact product, four resin grades, certified line, pool and press.

    Returns a world dict with keys: product, g_ll, g_ev, g_ti, g_ad, line,
    pool, press.
    """
    api = api or _default_client
    set_logical_clock(api, clock)
    world = {"api": api}
    world["product"] = get_success_data(
        api.create_product(food_contact_product_payload(), ADMIN))
    world["g_ll"] = get_success_data(
        api.create_resin_grade(create_resin_grade_payload(), ADMIN))
    world["g_ev"] = get_success_data(
        api.create_resin_grade(barrier_grade_payload(), ADMIN))
    world["g_ti"] = get_success_data(
        api.create_resin_grade(tie_grade_payload(), ADMIN))
    world["g_ad"] = get_success_data(
        api.create_resin_grade(additive_grade_payload(), ADMIN))
    world["line"] = get_success_data(
        api.create_extrusion_line(food_certified_line_payload(), ADMIN))
    world["pool"] = get_success_data(
        api.create_regrind_pool(food_contact_pool_payload(), ADMIN))
    world["press"] = get_success_data(
        api.create_print_press(create_print_press_payload(), ADMIN))
    return world


def setup_non_food_catalog(api=None, clock=CLOCK_D1_0600) -> dict:
    """Non-food product, one LLDPE grade, uncertified line and pool."""
    api = api or _default_client
    set_logical_clock(api, clock)
    world = {"api": api}
    world["product"] = get_success_data(
        api.create_product(non_food_product_payload(), ADMIN))
    world["g_ll"] = get_success_data(
        api.create_resin_grade(create_resin_grade_payload(), ADMIN))
    world["line"] = get_success_data(
        api.create_extrusion_line(create_extrusion_line_payload(), ADMIN))
    world["pool"] = get_success_data(
        api.create_regrind_pool(create_regrind_pool_payload(), ADMIN))
    return world


# --------------------------------------------------------------------------
# Tier 1 / 3: recipes
# --------------------------------------------------------------------------
FOOD_RECIPE_COMPONENTS = (
    (1, "VIRGIN", 30.0, "g_ll"),
    (2, "VIRGIN", 2.5, "g_ev"),
    (2, "VIRGIN", 7.5, "g_ti"),
    (3, "VIRGIN", 50.0, "g_ll"),
    (3, "ADDITIVE", 10.0, "g_ad"),
)


def build_food_recipe_draft(api, world, recipe_code="R-FD-1",
                            components=FOOD_RECIPE_COMPONENTS, **recipe_overrides):
    """Create a three-layer DRAFT recipe on the food-contact product."""
    recipe = get_success_data(api.create_blend_recipe(
        create_blend_recipe_payload(world["product"]["id"],
                                    recipe_code=recipe_code,
                                    layer_count=3,
                                    **recipe_overrides),
        ENGINEER))
    for layer_index, kind, weight, grade_key in components:
        payload = create_component_payload(layer_index=layer_index,
                                          component_kind=kind,
                                          weight_pct=weight)
        if grade_key is not None:
            payload["resin_grade_id"] = world[grade_key]["id"]
        get_success_data(api.add_recipe_component(recipe["id"], payload, ENGINEER))
    return get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))


def setup_approved_food_recipe(api=None, world=None, recipe_code="R-FD-1",
                               submitter="u-be-1", approver="u-qm-1") -> dict:
    """Food-contact catalogue plus an APPROVED three-layer barrier recipe."""
    world = world or setup_food_contact_catalog(api)
    api = world["api"]
    recipe = build_food_recipe_draft(api, world, recipe_code=recipe_code)
    get_success_data(api.submit_blend_recipe(recipe["id"], _engineer(submitter)))
    get_success_data(api.approve_blend_recipe(
        recipe["id"], make_quality_manager_headers(approver)))
    world["recipe"] = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
    return world


def _engineer(user_id):
    from .test_users import make_blend_engineer_headers
    return make_blend_engineer_headers(user_id)


def build_non_food_recipe_draft(api, world, recipe_code="R-NF-0",
                                components=((1, "VIRGIN", 100.0, "g_ll"),)):
    recipe = get_success_data(api.create_blend_recipe(
        create_blend_recipe_payload(world["product"]["id"],
                                    recipe_code=recipe_code,
                                    layer_count=1),
        ENGINEER))
    for layer_index, kind, weight, grade_key in components:
        payload = create_component_payload(layer_index=layer_index,
                                           component_kind=kind,
                                           weight_pct=weight)
        if grade_key is not None:
            payload["resin_grade_id"] = world[grade_key]["id"]
        get_success_data(api.add_recipe_component(recipe["id"], payload, ENGINEER))
    return get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))


def setup_approved_non_food_recipe(api=None, world=None, recipe_code="R-NF-0",
                                   components=((1, "VIRGIN", 100.0, "g_ll"),),
                                   submitter="u-be-1", approver="u-qm-1") -> dict:
    """Non-food catalogue plus an APPROVED single-layer recipe."""
    world = world or setup_non_food_catalog(api)
    api = world["api"]
    recipe = build_non_food_recipe_draft(api, world, recipe_code=recipe_code,
                                         components=components)
    get_success_data(api.submit_blend_recipe(recipe["id"], _engineer(submitter)))
    get_success_data(api.approve_blend_recipe(
        recipe["id"], make_quality_manager_headers(approver)))
    world["recipe"] = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
    return world


# --------------------------------------------------------------------------
# Tier 1 / 4: extrusion runs
# --------------------------------------------------------------------------
def setup_food_run_running(api=None, world=None, run_code="RUN-FD-1",
                           scheduled_start="2026-08-05T06:00:00Z",
                           scheduled_end="2026-08-05T18:00:00Z",
                           target_output_kg=1000.0) -> dict:
    """Approved food recipe plus a RUNNING extrusion run on the certified line."""
    world = world or setup_approved_food_recipe(api)
    api = world["api"]
    run = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code=run_code,
                                     scheduled_start=scheduled_start,
                                     scheduled_end=scheduled_end,
                                     target_output_kg=target_output_kg),
        EXTRUDER))
    get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
    world["run"] = get_success_data(api.get_extrusion_run(run["id"], EXTRUDER))
    return world


def add_gauge_readings(api, run_id, thicknesses, headers=EXTRUDER, **extra):
    """Append one gauge reading per thickness value."""
    results = []
    for thickness in thicknesses:
        payload = {"thickness_micron": thickness}
        payload.update(extra)
        results.append(get_success_data(api.add_gauge_reading(run_id, payload, headers)))
    return results


def setup_food_run_gauged(api=None, world=None, thicknesses=(50.0,) * 5) -> dict:
    """RUNNING food run carrying a full gauge panel."""
    world = world or setup_food_run_running(api)
    api = world["api"]
    add_gauge_readings(api, world["run"]["id"], thicknesses)
    world["run"] = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
    return world


def setup_food_run_completed(api=None, world=None, thicknesses=(50.0,) * 5,
                             gross_output_kg=1000.0, scrap_kg=12.0,
                             roll_specs=((1, 600.0), (2, 200.0), (3, 50.0)),
                             roll_overrides=None) -> dict:
    """COMPLETED food run with three wound rolls; scrap booked into POOL-FD.

    ``roll_overrides`` maps roll_number to a dict of extra film roll input
    fields (for example ``{1: {"layflat_mm": 320.0}}``).
    """
    world = world or setup_food_run_gauged(api, thicknesses=thicknesses)
    api = world["api"]
    roll_overrides = roll_overrides or {}
    rolls = {}
    for roll_number, net_kg in roll_specs:
        payload = create_film_roll_payload(world["run"]["id"], roll_number, net_kg,
                                           **roll_overrides.get(roll_number, {}))
        rolls[roll_number] = get_success_data(api.create_film_roll(payload, EXTRUDER))
    world["rolls"] = rolls
    world["run"] = get_success_data(api.complete_extrusion_run(
        world["run"]["id"], gross_output_kg, scrap_kg, EXTRUDER))
    return world


def setup_food_rolls_released(api=None, world=None, roll_numbers=(1, 2)) -> dict:
    """COMPLETED food run whose named rolls have been RELEASED."""
    world = world or setup_food_run_completed(api)
    api = world["api"]
    for roll_number in roll_numbers:
        get_success_data(api.release_film_roll(world["rolls"][roll_number]["id"], QUALITY))
    for roll_number, roll in world["rolls"].items():
        world["rolls"][roll_number] = get_success_data(
            api.get_film_roll(roll["id"], QUALITY))
    return world


def setup_non_food_run_completed(api=None, world=None, run_code="RUN-NF-1",
                                 scheduled_start="2026-08-05T06:00:00Z",
                                 scheduled_end="2026-08-05T14:00:00Z",
                                 target_output_kg=500.0,
                                 thicknesses=(40.0,) * 5,
                                 gross_output_kg=500.0, scrap_kg=100.0,
                                 roll_specs=((1, 100.0),)) -> dict:
    """Non-food run driven to COMPLETED, generating regrind in POOL-NF."""
    world = world or setup_approved_non_food_recipe(api)
    api = world["api"]
    run = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code=run_code,
                                     scheduled_start=scheduled_start,
                                     scheduled_end=scheduled_end,
                                     target_output_kg=target_output_kg),
        EXTRUDER))
    get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
    add_gauge_readings(api, run["id"], thicknesses)
    rolls = world.setdefault("rolls", {})
    for roll_number, net_kg in roll_specs:
        rolls[roll_number] = get_success_data(api.create_film_roll(
            create_film_roll_payload(run["id"], roll_number, net_kg), EXTRUDER))
    world["run"] = get_success_data(api.complete_extrusion_run(
        run["id"], gross_output_kg, scrap_kg, EXTRUDER))
    world["pool"] = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
    return world


def setup_second_non_food_run_running(api=None, world=None, run_code="RUN-NF-2",
                                      clock=CLOCK_D1_1500,
                                      scheduled_start="2026-08-05T15:00:00Z",
                                      scheduled_end="2026-08-05T20:00:00Z",
                                      target_output_kg=500.0) -> dict:
    """First non-food run COMPLETED, a second one RUNNING on the same line."""
    world = world or setup_non_food_run_completed(api)
    api = world["api"]
    set_logical_clock(api, clock)
    run2 = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code=run_code,
                                     scheduled_start=scheduled_start,
                                     scheduled_end=scheduled_end,
                                     target_output_kg=target_output_kg),
        EXTRUDER))
    get_success_data(api.start_extrusion_run(run2["id"], EXTRUDER))
    world["run2"] = get_success_data(api.get_extrusion_run(run2["id"], EXTRUDER))
    return world


def setup_pool_with_reincorporation(api=None, world=None, kg=50.0) -> dict:
    """Second non-food run RUNNING having drawn ``kg`` back out of POOL-NF.

    Records the resulting OUT ledger row under the ``out_transaction`` key.
    """
    world = world or setup_second_non_food_run_running(api)
    api = world["api"]
    version = read_pool_version(api, world["pool"]["id"])
    world["out_transaction"] = get_success_data(api.create_regrind_reincorporation(
        world["run2"]["id"],
        {"pool_id": world["pool"]["id"], "kg": kg,
         "expected_regrind_pool_version": version},
        EXTRUDER))
    world["pool"] = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
    return world


def setup_incapable_non_food_run(api=None, world=None, run_code="RUN-NF-A",
                                 scheduled_start="2026-08-05T06:00:00Z",
                                 scheduled_end="2026-08-05T14:00:00Z",
                                 thicknesses=(37.0, 43.0, 40.0, 40.0, 40.0),
                                 roll_number=1) -> dict:
    """A non-food run completed with a gauge panel too wide to be capable.

    Stores the completed run under ``incapable_runs`` and its roll under
    ``rolls[roll_number]``.
    """
    world = world or setup_approved_non_food_recipe(api)
    api = world["api"]
    run = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code=run_code,
                                     scheduled_start=scheduled_start,
                                     scheduled_end=scheduled_end),
        EXTRUDER))
    get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
    add_gauge_readings(api, run["id"], thicknesses)
    rolls = world.setdefault("rolls", {})
    rolls[roll_number] = get_success_data(api.create_film_roll(
        create_film_roll_payload(run["id"], roll_number, 100.0), EXTRUDER))
    completed = get_success_data(api.complete_extrusion_run(run["id"], 500.0, 100.0,
                                                            EXTRUDER))
    world.setdefault("incapable_runs", []).append(completed)
    world["run"] = completed
    world["line"] = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
    return world


def setup_frozen_line_by_two_incapable_runs(api=None, world=None) -> dict:
    """Line FROZEN by two INCAPABLE runs, with a third run left SCHEDULED.

    Keys: ``incapable_runs`` (two completed runs), ``blocked_run`` (the run
    that was still SCHEDULED when the freeze landed), ``rolls`` 1 and 2.
    """
    world = world or setup_approved_non_food_recipe(api)
    api = world["api"]
    world = setup_incapable_non_food_run(api, world, run_code="RUN-NF-A",
                                         roll_number=1)
    set_logical_clock(api, CLOCK_D1_1500)
    blocked = get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code="RUN-NF-C",
                                     scheduled_start="2026-08-06T06:00:00Z",
                                     scheduled_end="2026-08-06T14:00:00Z"),
        EXTRUDER))
    world["blocked_run"] = blocked
    world = setup_incapable_non_food_run(
        api, world, run_code="RUN-NF-B",
        scheduled_start="2026-08-05T15:00:00Z",
        scheduled_end="2026-08-05T20:00:00Z",
        roll_number=2)
    world["blocked_run"] = get_success_data(
        api.get_extrusion_run(blocked["id"], EXTRUDER))
    return world


# --------------------------------------------------------------------------
# Tier 3: printing
# --------------------------------------------------------------------------
def setup_mounted_plate(api=None, world=None, plate_code="PL-1", color_count=4,
                        wear_limit_impressions=None) -> dict:
    """Plate set for the food-contact product, MOUNTED on PR-1."""
    world = world or setup_food_rolls_released(api)
    api = world["api"]
    overrides = {"plate_code": plate_code, "color_count": color_count}
    if wear_limit_impressions is not None:
        overrides["wear_limit_impressions"] = wear_limit_impressions
    plate = get_success_data(api.create_plate_set(
        create_plate_set_payload(world["product"]["id"], **overrides), PRINTER))
    get_success_data(api.mount_plate_set(plate["id"], world["press"]["id"], PRINTER))
    world["plate"] = get_success_data(api.get_plate_set(plate["id"], PRINTER))
    return world


def setup_print_job_in_setup(api=None, world=None, job_code="PJ-1", roll_number=1,
                             window_start="2026-08-05T06:00:00Z",
                             window_end="2026-08-05T18:00:00Z") -> dict:
    """Print job created against a RELEASED roll; still in SETUP."""
    world = world or setup_mounted_plate(api)
    api = world["api"]
    job = get_success_data(api.create_print_job(
        create_print_job_payload(world["rolls"][roll_number]["id"],
                                 world["plate"]["id"], world["press"]["id"],
                                 job_code=job_code,
                                 window_start=window_start,
                                 window_end=window_end),
        PRINTER))
    world["print_job"] = job
    return world


def setup_print_job_printing(api=None, world=None, registration_drift_micron=40.0,
                             delta_e_measured=1.2, **kwargs) -> dict:
    """Print job that has passed registration and colour and is PRINTING."""
    world = world or setup_print_job_in_setup(api, **kwargs)
    api = world["api"]
    job_id = world["print_job"]["id"]
    get_success_data(api.registration_check(job_id, registration_drift_micron, PRINTER))
    get_success_data(api.color_proof(job_id, delta_e_measured, PRINTER))
    world["print_job"] = get_success_data(api.start_print(job_id, PRINTER))
    return world


def setup_print_job_completed(api=None, world=None, printed_kg=576.0, **kwargs) -> dict:
    """COMPLETED print job; the plate has taken its impressions."""
    world = world or setup_print_job_printing(api, **kwargs)
    api = world["api"]
    world["print_job"] = get_success_data(api.complete_print_job(
        world["print_job"]["id"], printed_kg, PRINTER))
    world["plate"] = get_success_data(api.get_plate_set(world["plate"]["id"], PRINTER))
    return world


# --------------------------------------------------------------------------
# Tier 3 / 4: bag lots
# --------------------------------------------------------------------------
def setup_bag_lot_converting(api=None, world=None, lot_code="BL-1",
                             bag_count_produced=46000, **lot_overrides) -> dict:
    """Bag lot in CONVERTING, built from a COMPLETED food-contact print job."""
    world = world or setup_print_job_completed(api)
    api = world["api"]
    world["bag_lot"] = get_success_data(api.create_bag_lot(
        create_bag_lot_payload(world["print_job"]["id"], world["product"]["id"],
                               bag_count_produced, lot_code=lot_code,
                               **lot_overrides),
        CONVERTER))
    return world


def append_seal_specimens(api, lot_id, specimens, headers=SEAL_OPERATOR):
    """Append (specimen_index, measured_n_per_15mm) pairs to the seal panel."""
    results = []
    for specimen_index, measured in specimens:
        results.append(get_success_data(api.add_seal_test(
            lot_id, create_seal_test_payload(specimen_index, measured), headers)))
    return results


DEFAULT_FOOD_SPECIMENS = ((1, 26.0), (2, 25.0), (3, 24.0))


def setup_bag_lot_testing(api=None, world=None, specimens=DEFAULT_FOOD_SPECIMENS,
                          specimen_headers=SEAL_OPERATOR, **kwargs) -> dict:
    """Bag lot in TESTING with a full first-pass bottom-seal panel."""
    world = world or setup_bag_lot_converting(api, **kwargs)
    api = world["api"]
    append_seal_specimens(api, world["bag_lot"]["id"], specimens, specimen_headers)
    world["bag_lot"] = get_success_data(api.get_bag_lot(world["bag_lot"]["id"],
                                                        CONVERTER))
    return world


def setup_bag_lot_qualified(api=None, world=None, finalizer=ISSUING_MANAGER,
                            **kwargs) -> dict:
    """Bag lot whose seal panel has been finalised."""
    world = world or setup_bag_lot_testing(api, **kwargs)
    api = world["api"]
    world["bag_lot"] = get_success_data(
        api.finalize_seal_tests(world["bag_lot"]["id"], finalizer))
    return world


def setup_bag_lot_packed(api=None, world=None, requested_bags=22500, **kwargs) -> dict:
    """Bag lot with one packout allocation committed."""
    world = world or setup_bag_lot_qualified(api, **kwargs)
    api = world["api"]
    lot_id = world["bag_lot"]["id"]
    version = read_bag_lot_version(api, lot_id)
    world["bag_lot"] = get_success_data(
        api.packout_bag_lot(lot_id, requested_bags, version, CONVERTER))
    return world


# --------------------------------------------------------------------------
# Tier 5: dossiers, release, shipment
# --------------------------------------------------------------------------
def setup_draft_dossier(api=None, world=None, dossier_code="CD-1",
                        food_contact_declared=True,
                        recycled_content_claim_pct=0.0,
                        author=ISSUING_MANAGER, **kwargs) -> dict:
    """DRAFT compliance dossier for the current bag lot."""
    world = world or setup_bag_lot_packed(api, **kwargs)
    api = world["api"]
    world["dossier"] = get_success_data(api.create_compliance_dossier(
        create_compliance_dossier_payload(
            world["bag_lot"]["id"], dossier_code=dossier_code,
            food_contact_declared=food_contact_declared,
            recycled_content_claim_pct=recycled_content_claim_pct),
        author))
    return world


def setup_issued_dossier(api=None, world=None, issuer=ISSUING_MANAGER, **kwargs) -> dict:
    """ISSUED compliance dossier, with its as-built figure frozen."""
    world = world or setup_draft_dossier(api, **kwargs)
    api = world["api"]
    world["dossier"] = get_success_data(
        api.issue_compliance_dossier(world["dossier"]["id"], issuer))
    return world


def setup_released_bag_lot(api=None, world=None, **kwargs) -> dict:
    """Bag lot RELEASED behind an issued, conforming dossier."""
    world = world or setup_issued_dossier(api, **kwargs)
    api = world["api"]
    world["bag_lot"] = get_success_data(
        api.release_bag_lot(world["bag_lot"]["id"], ISSUING_MANAGER))
    return world


def setup_shipped_bag_lot(api=None, world=None, **kwargs) -> dict:
    """Bag lot SHIPPED -- the terminal state of the converting lifecycle."""
    world = world or setup_released_bag_lot(api, **kwargs)
    api = world["api"]
    world["bag_lot"] = get_success_data(api.ship_bag_lot(world["bag_lot"]["id"], ADMIN))
    return world


# --------------------------------------------------------------------------
# Non-food converting chain (single-layer, gusseted, perforated product)
# --------------------------------------------------------------------------
def setup_non_food_bag_lot(api=None, world=None, lot_code="BL-NF",
                           bag_count_produced=5157,
                           perforation_verified=True,
                           gusset_verified=True) -> dict:
    """Non-food lot converted from a released roll on the uncertified line."""
    world = world or setup_non_food_run_completed(api)
    api = world["api"]
    if "press" not in world:
        world["press"] = get_success_data(
            api.create_print_press(create_print_press_payload(), ADMIN))
    get_success_data(api.release_film_roll(world["rolls"][1]["id"], QUALITY))
    plate = get_success_data(api.create_plate_set(
        create_plate_set_payload(world["product"]["id"], plate_code="PL-NF",
                                 color_count=4), PRINTER))
    get_success_data(api.mount_plate_set(plate["id"], world["press"]["id"], PRINTER))
    world["plate"] = plate
    job = get_success_data(api.create_print_job(
        create_print_job_payload(world["rolls"][1]["id"], plate["id"],
                                 world["press"]["id"], job_code="PJ-NF"),
        PRINTER))
    get_success_data(api.registration_check(job["id"], 30.0, PRINTER))
    get_success_data(api.color_proof(job["id"], 0.9, PRINTER))
    get_success_data(api.start_print(job["id"], PRINTER))
    world["print_job"] = get_success_data(api.complete_print_job(job["id"], 100.0,
                                                                 PRINTER))
    world["bag_lot"] = get_success_data(api.create_bag_lot(
        create_bag_lot_payload(job["id"], world["product"]["id"], bag_count_produced,
                               lot_code=lot_code,
                               perforation_verified=perforation_verified,
                               gusset_verified=gusset_verified),
        CONVERTER))
    return world
