"""Composite setup helpers.

The test harness restarts the server before every test, so each test starts from
an empty database and builds everything it needs through the documented
endpoints. These helpers layer that setup, from single writes at the bottom to
whole-hatch shortcuts at the top, so that a test body contains only the calls
whose behaviour it is actually asserting.

Layering
--------
1. Single-step primitives and state progressions (clock, configuration, flock
   through PLACED / IN_LAY / EGG_HOLD, lot through GRADED / IN_STORAGE).
2. Entity hierarchies (a programme with a laying flock and a stored lot; a
   sanitised machine with a profile and a planned load).
3. Full lifecycle shortcuts (planned load through INCUBATING, CANDLED,
   TRANSFERRED, pulled, sexed, vaccinated, BOXED).
4. Accumulation and threshold targeting (probe reading sequences that drive the
   environment dimension; hatch counts that put rolling hatchability just above
   or just below the corrective-action threshold).
5. Finalisation (cleared farms with confirmed orders, an allocation run, a
   delivered or reversed assignment, a corrective action ready to work off).
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    CHICK_PROCESSOR,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    make_grower_farm_headers,
)
from .types import (
    Breed,
    LabResult,
    LabSubjectType,
    LabTestCode,
    UnitType,
)

# Instants that recur across the whole suite.
CLOCK_SETUP = "2026-08-01T12:00:00Z"
CLOCK_SET_AT = "2026-08-01T18:00:00Z"
CLOCK_PULL_IN_WINDOW = "2026-08-22T18:00:00Z"
STANDARD_PLANNED_SET_AT = "2026-08-01T18:00:00Z"
STANDARD_TRANSFER_AT = "2026-08-02T02:00:00Z"


# ===========================================================================
# 1. Primitives and single-step state progressions
# ===========================================================================


def set_clock(api, current_utc: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Move the logical clock and return the ``current_utc`` now in force."""
    response = api.set_clock(current_utc, headers or HATCHERY_MANAGER)
    data = get_success_data(response, 200)
    return data.get("current_utc", current_utc)


def create_program(api, **overrides: Any) -> Dict[str, Any]:
    """Author a lighting and nutrition programme."""
    response = api.create_flock_program(
        f.flock_program_payload(**overrides), HATCHERY_MANAGER
    )
    return get_success_data(response, 201)


def create_profile(api, **overrides: Any) -> Dict[str, Any]:
    """Author an incubation temperature and humidity profile."""
    response = api.create_incubation_profile(
        f.incubation_profile_payload(**overrides), HATCHERY_MANAGER
    )
    return get_success_data(response, 201)


def create_unit(api, **overrides: Any) -> Dict[str, Any]:
    """Register a machine; it starts DIRTY and FREE."""
    response = api.create_incubation_unit(
        f.incubation_unit_payload(**overrides), HATCHERY_MANAGER
    )
    return get_success_data(response, 201)


def sanitized_unit(api, **overrides: Any) -> Dict[str, Any]:
    """Register a machine and sanitise it, returning the sanitised row."""
    unit = create_unit(api, **overrides)
    response = api.sanitize_incubation_unit(unit["id"], INCUBATION_OPERATOR)
    return get_success_data(response, 200)


def create_flock(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Place a breeder flock; it starts in PLACED."""
    response = api.create_breeder_flock(
        f.breeder_flock_payload(program_id, **overrides), FLOCK_MANAGER
    )
    return get_success_data(response, 201)


def register_lab_test(api, subject_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a laboratory sample; it starts PENDING."""
    response = api.create_lab_test(
        f.lab_test_payload(subject_id, **overrides), VETERINARIAN
    )
    return get_success_data(response, 201)


def release_lab_test(
    api,
    test_id: str,
    result: str = LabResult.NEGATIVE.value,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Release a laboratory result; the release is one-shot and terminal."""
    response = api.release_lab_test(test_id, result, headers or VETERINARIAN)
    return get_success_data(response, 200)


def salmonella_clearance(
    api,
    flock_id: str,
    collected_at: str = "2026-07-20T00:00:00Z",
    result: str = LabResult.NEGATIVE.value,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Put a released SALMONELLA_PULLORUM result on a flock's record."""
    test = register_lab_test(
        api,
        flock_id,
        subject_type=LabSubjectType.BREEDER_FLOCK.value,
        test_code=LabTestCode.SALMONELLA_PULLORUM.value,
        collected_at=collected_at,
    )
    release_lab_test(api, test["id"], result, headers)
    return test


def flock_in_lay(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Place a flock, clear it and photostimulate it into IN_LAY."""
    flock = create_flock(api, program_id, **overrides)
    salmonella_clearance(api, flock["id"])
    response = api.start_lay(flock["id"], FLOCK_MANAGER)
    return get_success_data(response, 200)


def collect_lot(api, flock_id: str, **overrides: Any) -> Dict[str, Any]:
    """Close a hatching egg collection; the lot starts COLLECTED."""
    response = api.create_egg_lot(f.egg_lot_payload(flock_id, **overrides), FLOCK_MANAGER)
    return get_success_data(response, 201)


def graded_lot(api, flock_id: str, grade: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
    """Collect and grade a lot, returning the GRADED row."""
    lot = collect_lot(api, flock_id, **overrides)
    response = api.grade_egg_lot(lot["id"], f.grade_payload(**(grade or {})), FLOCK_MANAGER)
    return get_success_data(response, 200)


def stored_lot(
    api,
    flock_id: str,
    grade: Optional[Dict[str, Any]] = None,
    storage_temp_c: float = 15.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Collect, grade and cool a lot, returning the IN_STORAGE row (with version)."""
    lot = graded_lot(api, flock_id, grade=grade, **overrides)
    response = api.store_egg_lot(
        lot["id"], f.store_payload(storage_temp_c), INCUBATION_OPERATOR
    )
    return get_success_data(response, 200)


def lot_version(api, lot_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """Read a lot purely to learn the ``version`` a draw must quote."""
    response = api.get_egg_lot(lot_id, headers or INCUBATION_OPERATOR)
    return get_success_data(response, 200)["version"]


def batch_version(api, batch_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """Read a batch purely to learn the ``version`` an allocation run must quote."""
    response = api.get_chick_batch(batch_id, headers or HATCHERY_MANAGER)
    return get_success_data(response, 200)["version"]


def draw_eggs(
    api,
    load_id: str,
    lot_id: str,
    eggs_taken: int,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Draw eggs from a stored lot into a planned load under lot concurrency."""
    version = expected_version if expected_version is not None else lot_version(api, lot_id)
    response = api.draw_eggs(
        load_id, f.draw_payload(lot_id, eggs_taken, version), INCUBATION_OPERATOR
    )
    return get_success_data(response, 201)


def ingest_reading(
    api,
    load_id: str,
    recorded_at: str,
    temp_c: float = 37.8,
    humidity_pct: float = 55.0,
) -> Dict[str, Any]:
    """Ingest one probe reading against an INCUBATING load."""
    response = api.add_environment_reading(
        load_id,
        f.environment_reading_payload(recorded_at, temp_c, humidity_pct),
        INCUBATION_OPERATOR,
    )
    return get_success_data(response, 201)


# ===========================================================================
# 2. Entity hierarchies
# ===========================================================================


def program_with_laying_flock(api, clock: str = CLOCK_SETUP) -> Dict[str, Any]:
    """The clock, a programme and a cleared flock in IN_LAY."""
    set_clock(api, clock)
    program = create_program(api)
    flock = flock_in_lay(api, program["id"])
    return {"program": program, "flock": flock}


def planned_load_context(
    api,
    *,
    clock: str = CLOCK_SETUP,
    lot_collected_at: str = "2026-07-30T00:00:00Z",
    collected_count: int = 10500,
    grade: Optional[Dict[str, Any]] = None,
    storage_temp_c: float = 15.0,
    setter_capacity: int = 20000,
    sanitize_setter: bool = True,
    planned_set_at: str = STANDARD_PLANNED_SET_AT,
    eggs_taken: int = 10000,
) -> Dict[str, Any]:
    """The full configuration chain down to a PLANNED load holding drawn eggs.

    Returns the ids and rows every downstream helper needs: ``program``,
    ``flock``, ``lot``, ``setter_unit``, ``profile``, ``load`` and ``item``.
    """
    set_clock(api, clock)
    program = create_program(api)
    flock = flock_in_lay(api, program["id"])
    lot = stored_lot(
        api,
        flock["id"],
        grade=grade,
        storage_temp_c=storage_temp_c,
        collected_at=lot_collected_at,
        collected_count=collected_count,
    )
    if sanitize_setter:
        setter_unit = sanitized_unit(
            api, code="U1", unit_type=UnitType.SETTER.value, capacity_eggs=setter_capacity
        )
    else:
        setter_unit = create_unit(
            api, code="U1", unit_type=UnitType.SETTER.value, capacity_eggs=setter_capacity
        )
    profile = create_profile(api)
    load = get_success_data(
        api.create_setter_load(
            f.setter_load_payload(setter_unit["id"], profile["id"], planned_set_at),
            INCUBATION_OPERATOR,
        ),
        201,
    )
    item = draw_eggs(api, load["id"], lot["id"], eggs_taken, lot["version"])
    return {
        "program": program,
        "flock": flock,
        "lot": lot,
        "setter_unit": setter_unit,
        "profile": profile,
        "load": load,
        "item": item,
    }


# ===========================================================================
# 3. Full lifecycle shortcuts
# ===========================================================================


def incubating_load_context(
    api, *, set_at: str = CLOCK_SET_AT, **kwargs: Any
) -> Dict[str, Any]:
    """A planned load moved to INCUBATING at ``set_at``, with the window derived."""
    ctx = planned_load_context(api, **kwargs)
    set_clock(api, set_at)
    ctx["load"] = get_success_data(
        api.start_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR), 200
    )
    return ctx


def candled_load_context(
    api, *, fertile_count: int = 9600, set_at: str = CLOCK_SET_AT, **kwargs: Any
) -> Dict[str, Any]:
    """An INCUBATING load candled to CANDLED with ``fertile_count`` fertile eggs."""
    ctx = incubating_load_context(api, set_at=set_at, **kwargs)
    ctx["load"] = get_success_data(
        api.candle_setter_load(ctx["load"]["id"], fertile_count, INCUBATION_OPERATOR), 200
    )
    return ctx


def transferred_load_context(
    api,
    *,
    fertile_count: int = 9600,
    set_at: str = CLOCK_SET_AT,
    transfer_at: Optional[str] = None,
    hatcher_capacity: int = 20000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A candled load transferred into a sanitised hatcher, producing a HATCHING load.

    Adds ``hatcher_unit`` and ``hatcher_load`` to the context.
    """
    ctx = candled_load_context(api, fertile_count=fertile_count, set_at=set_at, **kwargs)
    hatcher_unit = sanitized_unit(
        api, code="U2", unit_type=UnitType.HATCHER.value, capacity_eggs=hatcher_capacity
    )
    if transfer_at is not None:
        set_clock(api, transfer_at)
    ctx["hatcher_unit"] = hatcher_unit
    ctx["hatcher_load"] = get_success_data(
        api.transfer_setter_load(
            ctx["load"]["id"], hatcher_unit["id"], INCUBATION_OPERATOR
        ),
        201,
    )
    return ctx


def pulled_batch_context(
    api,
    *,
    pull_at: str = CLOCK_PULL_IN_WINDOW,
    hatched_count: int = 9400,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A transferred load pulled at ``pull_at``, producing a PULLED chick batch.

    ``hatcher_load`` is refreshed after the pull, so it carries the branch the
    clock selected (EARLY_PULLED, WINDOW_PULLED or LATE_PULLED) together with
    ``pull_class``, ``pull_offset_hours``, ``quality_flag`` and
    ``hold_release_at`` rather than the pre-pull HATCHING snapshot.
    """
    ctx = transferred_load_context(api, **kwargs)
    set_clock(api, pull_at)
    ctx["batch"] = get_success_data(
        api.pull_chicks(ctx["hatcher_load"]["id"], hatched_count, CHICK_PROCESSOR), 201
    )
    ctx["hatcher_load"] = read_hatcher_load(api, ctx["hatcher_load"]["id"])
    return ctx


def sexed_batch_context(
    api, *, sexing: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """A PULLED batch sexed to SEXED, resolving the preliminary yield."""
    ctx = pulled_batch_context(api, **kwargs)
    ctx["batch"] = get_success_data(
        api.sex_chick_batch(
            ctx["batch"]["id"], f.sexing_payload(**(sexing or {})), CHICK_PROCESSOR
        ),
        200,
    )
    return ctx


def vaccinated_batch_context(
    api, *, vaccine_code: str = "MAREKS_HVT", **kwargs: Any
) -> Dict[str, Any]:
    """A SEXED batch vaccinated to VACCINATED, resolving the reject tier and culls."""
    ctx = sexed_batch_context(api, **kwargs)
    ctx["vaccinated_version"] = ctx["batch"]["version"]
    ctx["batch"] = get_success_data(
        api.vaccinate_chick_batch(ctx["batch"]["id"], vaccine_code, CHICK_PROCESSOR), 200
    )
    return ctx


def boxed_batch_context(
    api, *, box_headers: Optional[Dict[str, str]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """A VACCINATED batch boxed to BOXED, freezing the final quality score.

    ``box_headers`` selects the principal whose boxing call would be recorded as
    ``opened_by_user_id`` on any corrective action the boxing auto-opens.
    """
    ctx = vaccinated_batch_context(api, **kwargs)
    ctx["batch"] = get_success_data(
        api.box_chick_batch(ctx["batch"]["id"], box_headers or CHICK_PROCESSOR), 200
    )
    return ctx


# ===========================================================================
# 4. Accumulation and threshold targeting
# ===========================================================================


def ingest_reading_sequence(
    api, load_id: str, readings: List[Tuple[str, float]], humidity_pct: float = 55.0
) -> List[Dict[str, Any]]:
    """Ingest ``(recorded_at, temp_c)`` pairs in order, returning each reading row.

    Readings of a load are strictly increasing in ``recorded_at``, so the caller
    supplies them already in order.
    """
    return [
        ingest_reading(api, load_id, recorded_at, temp_c, humidity_pct)
        for recorded_at, temp_c in readings
    ]


def deviation_open_context(
    api,
    *,
    readings: Optional[List[Tuple[str, float]]] = None,
    clock_after: str = "2026-08-02T02:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """An INCUBATING load driven into DEVIATION_OPEN by out-of-tolerance readings.

    The default pair charges a 0.50-degree excess across two hours, which is
    2.000 degree-hours in one segment and therefore above the 1.50 threshold.
    """
    ctx = incubating_load_context(api, **kwargs)
    set_clock(api, clock_after)
    ctx["readings"] = ingest_reading_sequence(
        api,
        ctx["load"]["id"],
        readings
        or [
            ("2026-08-01T18:00:00Z", 38.6),
            ("2026-08-01T22:00:00Z", 38.6),
        ],
    )
    ctx["load"] = get_success_data(
        api.get_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR), 200
    )
    return ctx


#: Sexing counts that leave rolling hatchability comfortably above 82.0 percent.
HEALTHY_SEXING = {
    "male_count": 4600,
    "female_count": 4700,
    "unsexed_count": 0,
    "sexing_cull_count": 100,
}

#: Sexing counts for the 8332-chick pull that lands hatchability below 82.0.
LOW_HATCHABILITY_SEXING = {
    "male_count": 4100,
    "female_count": 4132,
    "unsexed_count": 0,
    "sexing_cull_count": 100,
}

#: Sexing counts for the 8333-chick pull that lands hatchability at exactly 82.00.
THRESHOLD_SEXING = {
    "male_count": 4100,
    "female_count": 4133,
    "unsexed_count": 0,
    "sexing_cull_count": 100,
}


def low_hatchability_boxed_context(
    api, *, box_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """A boxed batch whose set-basis rolling hatchability falls below 82.0 percent,
    which auto-opens a corrective action against the primary breeder flock."""
    return boxed_batch_context(
        api,
        fertile_count=9000,
        hatched_count=8332,
        sexing=LOW_HATCHABILITY_SEXING,
        box_headers=box_headers,
    )


def threshold_hatchability_boxed_context(api) -> Dict[str, Any]:
    """A boxed batch whose set-basis rolling hatchability lands on exactly 82.00
    percent, which is not strictly below the threshold."""
    return boxed_batch_context(
        api, fertile_count=9000, hatched_count=8333, sexing=THRESHOLD_SEXING
    )


def open_corrective_action(
    api, flock_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """The single corrective action standing open against ``flock_id``."""
    response = api.list_corrective_actions(
        headers or HATCHERY_MANAGER, {"flock_id": flock_id, "status": "OPEN"}
    )
    rows = get_success_data(response, 200)
    assert rows, f"expected an open corrective action against flock {flock_id}"
    return rows[0]


# ===========================================================================
# 5. Finalisation: farms, orders, allocation, delivery
# ===========================================================================


def cleared_farm(api, **overrides: Any) -> Dict[str, Any]:
    """Register a grower farm and clear it for placement."""
    farm = get_success_data(
        api.create_grower_farm(f.grower_farm_payload(**overrides), HATCHERY_MANAGER), 201
    )
    return get_success_data(api.clear_grower_farm(farm["id"], VETERINARIAN), 200)


def pending_farm(api, **overrides: Any) -> Dict[str, Any]:
    """Register a grower farm and leave it at PENDING biosecurity."""
    return get_success_data(
        api.create_grower_farm(f.grower_farm_payload(**overrides), HATCHERY_MANAGER), 201
    )


def requested_order(
    api, farm_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Place a placement order; it starts REQUESTED."""
    return get_success_data(
        api.create_placement_order(
            f.placement_order_payload(farm_id, **overrides), headers or HATCHERY_MANAGER
        ),
        201,
    )


def confirmed_order(api, farm_id: str, **overrides: Any) -> Dict[str, Any]:
    """Place and confirm a placement order against a cleared farm."""
    order = requested_order(api, farm_id, **overrides)
    return get_success_data(
        api.confirm_placement_order(order["id"], HATCHERY_MANAGER), 200
    )


def allocation_ready_context(
    api,
    *,
    farm_capacity: int = 20000,
    orders: Optional[List[Dict[str, Any]]] = None,
    operator_user_id: str = "u_grower_1",
    allocation_clock: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A boxed batch plus a cleared farm carrying confirmed orders.

    ``orders`` is a list of keyword dicts for the placement order factory, each
    confirmed in turn; the context gains ``farm`` and ``orders``.
    """
    ctx = boxed_batch_context(api, **kwargs)
    farm = cleared_farm(
        api,
        code="FM1",
        operator_user_id=operator_user_id,
        capacity_chicks=farm_capacity,
    )
    order_specs = orders if orders is not None else [{"requested_chicks": 5000}]
    confirmed = [confirmed_order(api, farm["id"], **spec) for spec in order_specs]
    if allocation_clock is not None:
        set_clock(api, allocation_clock)
    ctx["farm"] = farm
    ctx["orders"] = confirmed
    return ctx


def run_allocation(
    api, batch_id: str, expected_version: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Run the whole-box allocation waterfall, returning the assignments created."""
    version = (
        expected_version if expected_version is not None else batch_version(api, batch_id)
    )
    response = api.allocate_chicks(batch_id, version, HATCHERY_MANAGER)
    return get_success_data(response, 201)


def grower_headers_for(farm: Dict[str, Any]) -> Dict[str, str]:
    """Headers for the grower principal that owns ``farm``'s scope."""
    return make_grower_farm_headers(farm["operator_user_id"])


def read_flock(api, flock_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_breeder_flock(flock_id, headers or FLOCK_MANAGER), 200)


def read_lot(api, lot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_egg_lot(lot_id, headers or INCUBATION_OPERATOR), 200)


def read_load(api, load_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_setter_load(load_id, headers or INCUBATION_OPERATOR), 200
    )


def read_unit(api, unit_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_incubation_unit(unit_id, headers or INCUBATION_OPERATOR), 200
    )


def read_hatcher_load(
    api, load_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_hatcher_load(load_id, headers or CHICK_PROCESSOR), 200
    )


def read_batch(api, batch_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_chick_batch(batch_id, headers or CHICK_PROCESSOR), 200
    )


def read_order(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_placement_order(order_id, headers or HATCHERY_MANAGER), 200
    )


def read_assignment(
    api, assignment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_delivery_assignment(assignment_id, headers or HATCHERY_MANAGER), 200
    )


def read_action(api, action_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_corrective_action(action_id, headers or HATCHERY_MANAGER), 200
    )


def list_items_of_load(
    api, load_id: str, params: Optional[Dict] = None, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_setter_load_items(load_id, headers or INCUBATION_OPERATOR, params), 200
    )


def list_draws_of_lot(
    api, lot_id: str, params: Optional[Dict] = None, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_egg_lot_draws(lot_id, headers or INCUBATION_OPERATOR, params), 200
    )


def list_assignments_of_batch(
    api, batch_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_delivery_assignments(
            headers or HATCHERY_MANAGER, {"chick_batch_id": batch_id}
        ),
        200,
    )


#: The breed every default fixture runs on, so tests can state mismatches plainly.
DEFAULT_BREED = Breed.ROSS_308.value
