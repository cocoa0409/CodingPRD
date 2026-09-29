"""
Composite state builders.

The harness restarts the server before every test, so every builder here starts
from an empty database and drives the public endpoints in the order the PRD
prescribes. Setup calls use the lenient get_success_data so that a broken setup
step reports itself rather than failing an unrelated assertion.

The canonical plant used by most builders sits at the grid origin with a
300-mile market radius, a 42-cent rate and 40000 green units of daily capacity.
Its formulation blends a 50 percent clay pit (7.500 iron oxide, 1.200 lime) with
a 50 percent shale pit (5.000 iron oxide, 0.800 lime), which lands the absorption
index at exactly 8.00 and therefore the durability grade at SW.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .constants import CLOCK_DEFAULT
from .test_users import (
    ARCHITECT_REVIEWER,
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    LOGISTICS_COORDINATOR,
    PLANT_ADMIN,
    QUALITY_MANAGER,
    SALES_REP,
    make_plant_operator_headers,
)


# --- tier 1: the logical clock and a bare plant --------------------------

def set_clock(api, to_iso8601: str) -> str:
    """Move the logical clock and return the instant the server reports."""
    data = get_success_data(api.set_clock(to_iso8601, PLANT_ADMIN))
    return data["current_utc"]


def create_plant(api, **overrides) -> Dict[str, Any]:
    """Register one plant."""
    return get_success_data(api.create_plant(F.plant_payload(**overrides), PLANT_ADMIN))


def create_clay_pit(api, plant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_clay_pit(plant_id, F.clay_pit_payload(**overrides), PLANT_ADMIN)
    )


def create_shale_pit(api, plant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_clay_pit(plant_id, F.shale_pit_payload(**overrides), PLANT_ADMIN)
    )


def create_kiln(api, plant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_kiln(plant_id, F.kiln_payload(**overrides), PLANT_ADMIN)
    )


def create_kiln_car(api, plant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_kiln_car(plant_id, F.kiln_car_payload(**overrides), PLANT_ADMIN)
    )


# --- tier 2: a qualified body formulation -------------------------------

def create_draft_formulation(api, plant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_formulation(F.formulation_payload(plant_id, **overrides), BODY_ENGINEER)
    )


def add_components(
    api, formulation: Dict[str, Any], shares: List[Tuple[str, float]]
) -> Dict[str, Any]:
    """
    Append one component per (pit_id, share_pct) pair, threading the version.

    Each append is guarded by optimistic concurrency on the formulation's
    version, so the expected version is read from the previous response.
    """
    current = formulation
    for pit_id, share_pct in shares:
        current = get_success_data(
            api.add_formulation_component(
                current["id"],
                F.formulation_component_payload(pit_id, share_pct, current["version"]),
                BODY_ENGINEER,
            )
        )
    return current


def qualify_formulation(api, formulation_id: str) -> Dict[str, Any]:
    return get_success_data(api.qualify_formulation(formulation_id, BODY_ENGINEER))


def build_qualified_formulation(
    api,
    plant_id: str,
    shares: List[Tuple[str, float]],
    **overrides,
) -> Dict[str, Any]:
    """Open a draft formulation, append its components, and qualify it."""
    draft = create_draft_formulation(api, plant_id, **overrides)
    add_components(api, draft, shares)
    return qualify_formulation(api, draft["id"])


# --- tier 3: the canonical plant with all of its assets ------------------

def build_plant_with_assets(
    api,
    clock: Optional[str] = CLOCK_DEFAULT,
    plant_overrides: Optional[Dict[str, Any]] = None,
    formulation_overrides: Optional[Dict[str, Any]] = None,
    kiln_overrides: Optional[Dict[str, Any]] = None,
    car_overrides: Optional[Dict[str, Any]] = None,
    pit_reserve_tons: float = 5000.00,
) -> Dict[str, Any]:
    """
    A plant with two pits, one qualified 50/50 formulation, one kiln and one car.

    Returns the plant, both pits, the qualified formulation, the kiln, the car
    and the operator headers bound to that plant.
    """
    if clock is not None:
        set_clock(api, clock)
    plant = create_plant(api, **(plant_overrides or {}))
    clay = create_clay_pit(api, plant["id"], proven_reserve_tons=pit_reserve_tons)
    shale = create_shale_pit(api, plant["id"], proven_reserve_tons=pit_reserve_tons)
    formulation = build_qualified_formulation(
        api,
        plant["id"],
        [(clay["id"], 50.00), (shale["id"], 50.00)],
        **(formulation_overrides or {}),
    )
    kiln = create_kiln(api, plant["id"], **(kiln_overrides or {}))
    car = create_kiln_car(api, plant["id"], **(car_overrides or {}))
    return {
        "plant": plant,
        "clay_pit": clay,
        "shale_pit": shale,
        "formulation": formulation,
        "kiln": kiln,
        "kiln_car": car,
        "operator": make_plant_operator_headers(plant["id"]),
    }


# --- tier 3: production runs ---------------------------------------------

def create_production_run(
    api, plant_id: str, formulation_id: str, kiln_car_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_production_run(
            F.production_run_payload(plant_id, formulation_id, kiln_car_id, **overrides),
            make_plant_operator_headers(plant_id),
        )
    )


def close_green(api, plant_id: str, run_id: str, green_loss_units: int = 400):
    return get_success_data(
        api.close_green(
            run_id,
            F.close_green_payload(green_loss_units),
            make_plant_operator_headers(plant_id),
        )
    )


def build_set_production_run(
    api,
    plant: Dict[str, Any],
    formulation_id: str,
    kiln_car_id: str,
    green_units_set: int = 10000,
    green_loss_units: int = 400,
    **overrides,
) -> Dict[str, Any]:
    """
    Extrude a run and close green handling on it so it reaches SET.

    A 10000-unit set losing 400 units in handling is a 4.00 percent loss, which
    is inside the six percent hold threshold, so the run forks to SET.
    """
    run = create_production_run(
        api,
        plant["id"],
        formulation_id,
        kiln_car_id,
        green_units_set=green_units_set,
        **overrides,
    )
    return close_green(api, plant["id"], run["id"], green_loss_units)


# --- tier 3: kiln runs and fired lots -----------------------------------

def create_kiln_run(api, plant_id: str, kiln_id: str, formulation_id: str, **overrides):
    return get_success_data(
        api.create_kiln_run(
            F.kiln_run_payload(kiln_id, formulation_id, **overrides),
            make_plant_operator_headers(plant_id),
        )
    )


def load_kiln_run(
    api, plant_id: str, kiln_run: Dict[str, Any], production_run_id: str, kiln_position: int
) -> Dict[str, Any]:
    return get_success_data(
        api.load_kiln_run(
            kiln_run["id"],
            F.kiln_load_payload(production_run_id, kiln_position, kiln_run["version"]),
            make_plant_operator_headers(plant_id),
        )
    )


def start_kiln_run(api, plant_id: str, kiln_run_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.start_kiln_run(kiln_run_id, make_plant_operator_headers(plant_id))
    )


def grade_kiln_run(
    api,
    plant_id: str,
    kiln_run_id: str,
    actual_peak_temp_c: int = 1040,
    actual_soak_hours: float = 3.0,
) -> Dict[str, Any]:
    return get_success_data(
        api.grade_kiln_run(
            kiln_run_id,
            F.grade_payload(actual_peak_temp_c, actual_soak_hours),
            make_plant_operator_headers(plant_id),
        )
    )


def fired_lots_of_run(api, production_run_id: str) -> List[Dict[str, Any]]:
    """Every fired lot minted from one production run."""
    response = api.list_fired_lots(
        PLANT_ADMIN, params={"production_run_id": production_run_id, "limit": 100}
    )
    return get_success_data(response)


def build_fired_lot(
    api,
    clock: Optional[str] = CLOCK_DEFAULT,
    green_units_set: int = 10000,
    green_loss_units: int = 400,
    kiln_position: int = 3,
    actual_peak_temp_c: int = 1040,
    actual_soak_hours: float = 3.0,
    plant_overrides: Optional[Dict[str, Any]] = None,
    formulation_overrides: Optional[Dict[str, Any]] = None,
    kiln_overrides: Optional[Dict[str, Any]] = None,
    car_overrides: Optional[Dict[str, Any]] = None,
    texture: str = "WIRE_CUT",
) -> Dict[str, Any]:
    """
    Drive the whole production chain to one fired lot on the centreline.

    With the canonical kiln fired to 1040 C for three hours, the base colour
    development index is 20.68; the centre position of a five-position kiln has
    no temperature offset, so the lot's position index is also 20.68, which is
    within three of the formulation's 20.00 target and therefore grades ON_COLOR
    at colour index 52.18.
    """
    env = build_plant_with_assets(
        api,
        clock=clock,
        plant_overrides=plant_overrides,
        formulation_overrides=formulation_overrides,
        kiln_overrides=kiln_overrides,
        car_overrides=car_overrides,
    )
    run = build_set_production_run(
        api,
        env["plant"],
        env["formulation"]["id"],
        env["kiln_car"]["id"],
        green_units_set=green_units_set,
        green_loss_units=green_loss_units,
        texture=texture,
    )
    kiln_run = create_kiln_run(
        api, env["plant"]["id"], env["kiln"]["id"], env["formulation"]["id"]
    )
    kiln_run = load_kiln_run(api, env["plant"]["id"], kiln_run, run["id"], kiln_position)
    start_kiln_run(api, env["plant"]["id"], kiln_run["id"])
    graded = grade_kiln_run(
        api, env["plant"]["id"], kiln_run["id"], actual_peak_temp_c, actual_soak_hours
    )
    lots = fired_lots_of_run(api, run["id"])
    env.update(
        {
            "production_run": run,
            "kiln_run": graded,
            "fired_lot": lots[0] if lots else None,
            "fired_lots": lots,
        }
    )
    return env


# --- tier 3: orders, blends, panels --------------------------------------

def create_order(api, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_order(F.order_payload(**overrides), SALES_REP))


def assign_plant(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.assign_plant(order_id, SALES_REP))


def build_assigned_order(api, **overrides) -> Dict[str, Any]:
    """Take an order and run the freight-sensitive plant selector on it."""
    order = create_order(api, **overrides)
    return assign_plant(api, order["id"])


def create_blend(api, order_id: str, requested_units: int, **overrides):
    return get_success_data(
        api.create_blend(
            order_id, F.blend_payload(requested_units, **overrides), BLEND_TECHNICIAN
        )
    )


def add_blend_component(
    api, blend: Dict[str, Any], fired_lot_id: str, units: int, headers=BLEND_TECHNICIAN
) -> Dict[str, Any]:
    """Hand-pick one lot into a draft blend, threading the blend's version."""
    return get_success_data(
        api.add_blend_component(
            blend["id"],
            F.blend_component_payload(fired_lot_id, units, blend["version"]),
            headers,
        )
    )


def compose_blend(api, blend_id: str, auto_fill: bool = False, headers=BLEND_TECHNICIAN):
    return get_success_data(
        api.compose_blend(blend_id, F.compose_payload(auto_fill), headers)
    )


def certify_blend(api, blend_id: str, headers=QUALITY_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.certify_blend(blend_id, headers))


def build_draft_blend_with_allocation(
    api,
    order: Dict[str, Any],
    allocations: List[Tuple[str, int]],
    requested_units: Optional[int] = None,
    **blend_overrides,
) -> Dict[str, Any]:
    """
    Open a blend on an assigned order and hand-pick the given lots into it.

    Each allocation is (fired_lot_id, units), appended in the order given.
    """
    blend = create_blend(
        api,
        order["id"],
        requested_units if requested_units is not None else order["requested_units"],
        **blend_overrides,
    )
    for fired_lot_id, units in allocations:
        blend = add_blend_component(api, blend, fired_lot_id, units)
    return blend


def build_composed_blend(
    api,
    order: Dict[str, Any],
    allocations: List[Tuple[str, int]],
    requested_units: Optional[int] = None,
    auto_fill: bool = False,
    **blend_overrides,
) -> Dict[str, Any]:
    """Allocate the given lots and compose the blend, writing its colour profile."""
    blend = build_draft_blend_with_allocation(
        api, order, allocations, requested_units=requested_units, **blend_overrides
    )
    return compose_blend(api, blend["id"], auto_fill=auto_fill)


def build_certified_blend(
    api,
    order: Dict[str, Any],
    allocations: List[Tuple[str, int]],
    requested_units: Optional[int] = None,
    **blend_overrides,
) -> Dict[str, Any]:
    """
    Compose and certify a blend.

    The certifier is a different quality manager from nobody in particular: the
    composer is a blend technician, so the segregation rule is already satisfied.
    """
    blend = build_composed_blend(
        api, order, allocations, requested_units=requested_units, **blend_overrides
    )
    return certify_blend(api, blend["id"])


def create_sample_panel(
    api,
    order_id: str,
    formulation_id: str,
    dye_lot_id: str,
    panel_color_index: float,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_sample_panel(
            order_id,
            F.sample_panel_payload(
                formulation_id, dye_lot_id, panel_color_index, **overrides
            ),
            BLEND_TECHNICIAN,
        )
    )


def build_approved_panel(
    api,
    order_id: str,
    formulation_id: str,
    dye_lot_id: str,
    panel_color_index: float,
    tolerance_delta_e: float = 1.00,
    **overrides,
) -> Dict[str, Any]:
    """
    Lay up a panel, submit it and have the architect approve it.

    Approval pins the formulation version and the dye lot code and opens a
    180-day window measured from the logical clock.
    """
    panel = create_sample_panel(
        api,
        order_id,
        formulation_id,
        dye_lot_id,
        panel_color_index,
        tolerance_delta_e=tolerance_delta_e,
        **overrides,
    )
    get_success_data(api.submit_panel(panel["id"], BLEND_TECHNICIAN))
    return get_success_data(api.approve_panel(panel["id"], ARCHITECT_REVIEWER))


# --- tier 5: packaging and delivery -------------------------------------

def package_order(api, order_id: str, pallet_count: int, band_count: int):
    return get_success_data(
        api.package_order(
            order_id, F.package_payload(pallet_count, band_count), LOGISTICS_COORDINATOR
        )
    )


def deliver_order(api, order_id: str, equipment: str = "TRUCK_MOUNTED_FORKLIFT"):
    return get_success_data(
        api.deliver_order(order_id, F.deliver_payload(equipment), LOGISTICS_COORDINATOR)
    )


def build_packaged_order(
    api, order_id: str, pallet_count: int, band_count: int
) -> Dict[str, Any]:
    """Palletize and band a certified blend, which re-quotes the freight."""
    return package_order(api, order_id, pallet_count, band_count)


# --- tier 4: one plant, one order, one blend, end to end ----------------

def build_order_ready_to_blend(
    api,
    requested_units: int = 9600,
    green_units_set: int = 10000,
    green_loss_units: int = 400,
    order_overrides: Optional[Dict[str, Any]] = None,
    **fired_lot_kwargs,
) -> Dict[str, Any]:
    """
    A single plant holding one ON_COLOR fired lot, plus an order assigned to it.

    Returns the whole production environment plus the assigned order, so a test
    can go straight to blending.
    """
    env = build_fired_lot(
        api,
        green_units_set=green_units_set,
        green_loss_units=green_loss_units,
        **fired_lot_kwargs,
    )
    order = build_assigned_order(
        api, requested_units=requested_units, **(order_overrides or {})
    )
    env["order"] = order
    return env


def build_two_fired_lots(
    api,
    clock: Optional[str] = CLOCK_DEFAULT,
    positions: Tuple[int, int] = (3, 1),
    green_units_set: int = 10000,
    green_loss_units: int = 400,
    actual_peak_temp_c: int = 1040,
    actual_soak_hours: float = 3.0,
    plant_overrides: Optional[Dict[str, Any]] = None,
    formulation_overrides: Optional[Dict[str, Any]] = None,
    kiln_overrides: Optional[Dict[str, Any]] = None,
    texture: str = "WIRE_CUT",
) -> Dict[str, Any]:
    """
    Two production runs fired together in one kiln run at two car positions.

    At the five-position kiln's centreline the position offset is zero, so a
    centre lot and a wall lot come out of the same firing with different colour
    indices: 52.18 at position 3 and 49.81 at position 1.
    """
    env = build_plant_with_assets(
        api,
        clock=clock,
        plant_overrides=plant_overrides,
        formulation_overrides=formulation_overrides,
        kiln_overrides=kiln_overrides,
    )
    car_two = create_kiln_car(api, env["plant"]["id"])
    run_one = build_set_production_run(
        api,
        env["plant"],
        env["formulation"]["id"],
        env["kiln_car"]["id"],
        green_units_set=green_units_set,
        green_loss_units=green_loss_units,
        texture=texture,
    )
    run_two = build_set_production_run(
        api,
        env["plant"],
        env["formulation"]["id"],
        car_two["id"],
        green_units_set=green_units_set,
        green_loss_units=green_loss_units,
        texture=texture,
    )
    kiln_run = create_kiln_run(
        api, env["plant"]["id"], env["kiln"]["id"], env["formulation"]["id"]
    )
    kiln_run = load_kiln_run(
        api, env["plant"]["id"], kiln_run, run_one["id"], positions[0]
    )
    kiln_run = load_kiln_run(
        api, env["plant"]["id"], kiln_run, run_two["id"], positions[1]
    )
    start_kiln_run(api, env["plant"]["id"], kiln_run["id"])
    graded = grade_kiln_run(
        api, env["plant"]["id"], kiln_run["id"], actual_peak_temp_c, actual_soak_hours
    )
    lot_one = fired_lots_of_run(api, run_one["id"])[0]
    lot_two = fired_lots_of_run(api, run_two["id"])[0]
    env.update(
        {
            "kiln_car_two": car_two,
            "production_run_one": run_one,
            "production_run_two": run_two,
            "kiln_run": graded,
            "lot_one": lot_one,
            "lot_two": lot_two,
        }
    )
    return env
