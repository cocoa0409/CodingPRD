"""Composite setup helpers that build the preconditions PRD.md workflows need.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Everything a test needs must therefore be
built from scratch through PRD-declared endpoints, and the chains involved are
long: reaching a delivered hull takes roughly twenty calls, and reaching an
approved warranty claim takes over thirty.

The helpers here are a ladder. Each rung calls the rung below it, adds one more
step of the workflow, and returns a plain dictionary — a "context" — holding
every entity it created together with the identifiers a caller needs next. A
context returned by a lower rung can always be passed to a higher one, and each
rung documents the state it leaves every entity in.

Three rules are honoured throughout, because getting any of them wrong produces
failures that look like implementation bugs:

* **Identity threading.** The four shop-floor roles are backed by ``Technician``
  rows, so their headers are minted per context and carried in it. Segregation
  of duties in PRD.md section 3.6 means the inspector must be neither the
  cycle's operator nor the hull's outfitter, so the baseline mints four separate
  technicians and never reuses one across those seats.
* **Fresh versions.** Every write guarded by an ``expected_<parent>_version``
  re-reads the parent immediately before the write, exactly as PRD.md
  section 2.6 requires. No context ever hands out a cached version.
* **Explicit clock.** PRD.md section 2.5 says the service never reads the host
  clock, so every rung that depends on ordering sets the logical clock itself
  rather than assuming where it stands.
"""

from typing import Any

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import shift_minutes
from .constants import CLOCK_DEFAULT_UTC
from . import factories as f
from .test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    PLANNER_HEADERS,
    make_assembly_technician_headers,
    make_customer_headers,
    make_molding_operator_headers,
    make_quality_inspector_headers,
    make_resin_technician_headers,
)

# The instants the ladder uses by default, all on the clock's startup date.
# Cooling runs 35 minutes, which clears the default model's 30 minute floor.
DEFAULT_OVEN_START = "2026-08-01T09:00:00Z"
DEFAULT_OVEN_END = "2026-08-01T10:00:00Z"
DEFAULT_COOLING_END = "2026-08-01T10:35:00Z"
DEFAULT_DEPART_AT = "2026-08-01T15:00:00Z"
DEFAULT_DELIVER_AT = "2026-08-02T00:00:00Z"


# ----------------------------------------------------------------------
# Clock and version helpers
# ----------------------------------------------------------------------


def set_clock(instant: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Move the logical clock and return the sweep counters the call reports.

    Only PlantAdmin may move the clock, so the admin headers are the default.
    """
    return api_client.set_current_utc(instant, headers or ADMIN_HEADERS)


def reset_clock() -> dict[str, Any]:
    """Put the logical clock back on its startup default of 2026-08-01T00:00:00Z."""
    return set_clock(CLOCK_DEFAULT_UTC)


def current_utc(headers: dict[str, str] | None = None) -> str:
    """Read the logical clock's current instant."""
    return api_client.read_current_utc(headers or ADMIN_HEADERS)


def stale_version(version: int) -> int:
    """Return a version number that cannot match ``version``.

    Useful for the five concurrency guards of PRD.md section 2.6, each of which
    refuses a write whose declared version differs from the stored one.
    """
    return version + 1


def warehouse_version(warehouse_id: str) -> int:
    """Re-read a warehouse and return its current version."""
    return api_client.read_version("get_warehouse", warehouse_id, PLANNER_HEADERS)


def production_order_version(production_order_id: str) -> int:
    """Re-read a production order and return its current version."""
    return api_client.read_version(
        "get_production_order", production_order_id, ADMIN_HEADERS
    )


def resin_lot_version(resin_lot_id: str) -> int:
    """Re-read a resin lot and return its current version."""
    return api_client.read_version("get_resin_lot", resin_lot_id, ADMIN_HEADERS)


def shipment_version(shipment_id: str) -> int:
    """Re-read a shipment and return its current version."""
    return api_client.read_version("get_shipment", shipment_id, PLANNER_HEADERS)


def product_model_version(product_model_id: str) -> int:
    """Re-read a product model and return its current version."""
    return api_client.read_version(
        "get_product_model", product_model_id, ADMIN_HEADERS
    )


# ----------------------------------------------------------------------
# Tier 2: entity hierarchy — reference data and identities
# ----------------------------------------------------------------------


def create_technician(role_code: str, **overrides: Any) -> dict[str, Any]:
    """Create one Technician and mint the headers that let it act.

    Returns ``{"technician", "technician_id", "headers"}``. The technician is
    ACTIVE and holds exactly the certifications PRD.md requires for
    ``role_code``, so it can act immediately.
    """
    technician = get_success_data(
        api_client.create_technician(
            f.technician_payload(role_code, **overrides), ADMIN_HEADERS
        )
    )
    builder = {
        "RESIN_TECH": make_resin_technician_headers,
        "MOLDING_OPERATOR": make_molding_operator_headers,
        "ASSEMBLY_TECH": make_assembly_technician_headers,
        "QUALITY_INSPECTOR": make_quality_inspector_headers,
    }[role_code]
    return {
        "technician": technician,
        "technician_id": technician["id"],
        "headers": builder(technician["id"]),
    }


def create_customer(
    *, acknowledged_at: str | None = None, **overrides: Any
) -> dict[str, Any]:
    """Create one ACTIVE Customer and mint its headers.

    Returns ``{"customer", "customer_id", "headers"}``. When
    ``acknowledged_at`` is given, the storage guidance acknowledgement is
    recorded at that instant, which is what a later VERIFIED storage review
    requires: PRD.md section 3.9 needs the acknowledgement to fall at or before
    the hull's ``delivered_at``.
    """
    customer = get_success_data(
        api_client.create_customer(f.customer_payload(**overrides), PLANNER_HEADERS)
    )
    if acknowledged_at is not None:
        customer = get_success_data(
            api_client.acknowledge_storage_guidance(
                customer["id"],
                f.acknowledge_storage_guidance_payload(acknowledged_at),
                PLANNER_HEADERS,
            )
        )
    return {
        "customer": customer,
        "customer_id": customer["id"],
        "headers": make_customer_headers(customer["id"]),
    }


def create_plant_baseline(
    *,
    clock: str | None = CLOCK_DEFAULT_UTC,
    model_overrides: dict[str, Any] | None = None,
    mold_overrides: dict[str, Any] | None = None,
    station_overrides: dict[str, Any] | None = None,
    bay_overrides: dict[str, Any] | None = None,
    warehouse_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stand up the reference data every production workflow needs.

    Creates, in the order PRD.md section 3.1 describes: one ProductModel, one
    Mold bound to it, one OvenStation, one CoolingBay, one Technician for each
    of the four shop-floor roles, and one Warehouse. When ``clock`` is not None
    the logical clock is set to it first, so the whole context is built at a
    known instant.

    Every created row is in its initial state: the mould AVAILABLE with
    ``cycles_since_service`` 0, both equipment rows OPERATIONAL, all four
    technicians ACTIVE, and the warehouse NORMAL with zero committed cube.

    Returns a context carrying each entity, its id, and the four sets of
    shop-floor headers under the keys ``resin_tech_headers``,
    ``operator_headers``, ``assembly_headers`` and ``inspector_headers``.
    """
    if clock is not None:
        set_clock(clock)

    product_model = get_success_data(
        api_client.create_product_model(
            f.product_model_payload(**(model_overrides or {})), ADMIN_HEADERS
        )
    )
    mold = get_success_data(
        api_client.create_mold(
            f.mold_payload(product_model["id"], **(mold_overrides or {})),
            ADMIN_HEADERS,
        )
    )
    oven_station = get_success_data(
        api_client.create_oven_station(
            f.oven_station_payload(**(station_overrides or {})), ADMIN_HEADERS
        )
    )
    cooling_bay = get_success_data(
        api_client.create_cooling_bay(
            f.cooling_bay_payload(**(bay_overrides or {})), ADMIN_HEADERS
        )
    )
    resin_tech = create_technician("RESIN_TECH")
    operator = create_technician("MOLDING_OPERATOR")
    assembly = create_technician("ASSEMBLY_TECH")
    inspector = create_technician("QUALITY_INSPECTOR")
    warehouse = get_success_data(
        api_client.create_warehouse(
            f.warehouse_payload(**(warehouse_overrides or {})), PLANNER_HEADERS
        )
    )

    return {
        "clock": clock,
        "admin_headers": ADMIN_HEADERS,
        "planner_headers": PLANNER_HEADERS,
        "agent_headers": AGENT_HEADERS,
        "product_model": product_model,
        "product_model_id": product_model["id"],
        "mold": mold,
        "mold_id": mold["id"],
        "oven_station": oven_station,
        "oven_station_id": oven_station["id"],
        "cooling_bay": cooling_bay,
        "cooling_bay_id": cooling_bay["id"],
        "warehouse": warehouse,
        "warehouse_id": warehouse["id"],
        "resin_technician": resin_tech["technician"],
        "resin_technician_id": resin_tech["technician_id"],
        "resin_tech_headers": resin_tech["headers"],
        "molding_operator": operator["technician"],
        "molding_operator_id": operator["technician_id"],
        "operator_headers": operator["headers"],
        "assembly_technician": assembly["technician"],
        "assembly_technician_id": assembly["technician_id"],
        "assembly_headers": assembly["headers"],
        "quality_inspector": inspector["technician"],
        "quality_inspector_id": inspector["technician_id"],
        "inspector_headers": inspector["headers"],
    }


def create_resin_lot(**overrides: Any) -> dict[str, Any]:
    """Create one AVAILABLE resin lot qualified for the default product model.

    On intake ``available_kg`` equals ``received_kg`` and the other two ledger
    buckets are zero, as PRD.md section 2.8 requires.
    """
    return get_success_data(
        api_client.create_resin_lot(f.resin_lot_payload(**overrides), ADMIN_HEADERS)
    )


def create_demand_bucket(ctx: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Create a demand forecast bucket for the context's product model.

    The default window spans 2026-07-01 through 2026-12-31, so the clock's
    startup date falls inside it and a store is admitted on the window test.
    """
    return get_success_data(
        api_client.create_demand_forecast_bucket(
            f.demand_forecast_bucket_payload(ctx["product_model_id"], **overrides),
            PLANNER_HEADERS,
        )
    )


def create_production_order(
    ctx: dict[str, Any], *, release: bool = True, **overrides: Any
) -> dict[str, Any]:
    """Create a production order against the context's model and warehouse.

    With ``release`` true the order is also released, which PRD.md section 3.3
    moves from DRAFT to READY_TO_SCHEDULE and is the precondition for
    scheduling a cycle. With ``release`` false the order is left in DRAFT.
    """
    # PRD.md section 2.8 makes `product_model_id` and `target_warehouse_id`
    # client-supplied required fields on a ProductionOrder, so a caller must be
    # able to aim an order at a site other than the context's own.  They are
    # pulled out of ``overrides`` rather than shadowing the positional args.
    product_model_id = overrides.pop("product_model_id", ctx["product_model_id"])
    target_warehouse_id = overrides.pop("target_warehouse_id", ctx["warehouse_id"])
    order = get_success_data(
        api_client.create_production_order(
            f.production_order_payload(
                product_model_id, target_warehouse_id, **overrides
            ),
            PLANNER_HEADERS,
        )
    )
    if release:
        order = get_success_data(
            api_client.release_production_order(order["id"], PLANNER_HEADERS)
        )
    return order


def schedule_cycle(
    ctx: dict[str, Any], production_order: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    """Schedule one cycle on the context's station arm 1 and cooling bay.

    The order's version is re-read immediately before the write, so
    ``expected_production_order_version`` is never stale. The mould is chosen by
    the server. The new cycle is SCHEDULED and its window projections follow
    from ``oven_start_at`` and the two scheduled durations.
    """
    payload = f.molding_cycle_payload(
        production_order["id"],
        ctx["oven_station_id"],
        ctx["cooling_bay_id"],
        production_order_version(production_order["id"]),
        **overrides,
    )
    return get_success_data(
        api_client.create_molding_cycle(payload, ctx["operator_headers"])
    )


def reserve_charge(
    ctx: dict[str, Any],
    molding_cycle: dict[str, Any],
    resin_lot: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    """Reserve resin from ``resin_lot`` against ``molding_cycle``.

    The lot's version is re-read immediately before the write. The resulting
    charge is RESERVED and the lot's ledger has moved the charge mass from
    ``available_kg`` to ``reserved_kg``.
    """
    payload = f.resin_charge_payload(
        molding_cycle["id"],
        resin_lot["id"],
        resin_lot_version(resin_lot["id"]),
        **overrides,
    )
    return get_success_data(
        api_client.create_resin_charge(payload, ctx["resin_tech_headers"])
    )


# ----------------------------------------------------------------------
# Tier 1: state progression — a cycle from scheduled to demoulded
# ----------------------------------------------------------------------


def setup_scheduled_cycle(
    *,
    baseline: dict[str, Any] | None = None,
    order_overrides: dict[str, Any] | None = None,
    cycle_overrides: dict[str, Any] | None = None,
    lot_overrides: dict[str, Any] | None = None,
    charge_overrides: dict[str, Any] | None = None,
    charge: bool = True,
    **baseline_kwargs: Any,
) -> dict[str, Any]:
    """Build a plant, a qualified lot, a released order and one SCHEDULED cycle.

    Creates, on top of ``create_plant_baseline``: one AVAILABLE ResinLot, one
    ProductionOrder released to READY_TO_SCHEDULE, one SCHEDULED MoldingCycle
    on arm 1, and — unless ``charge`` is false — one RESERVED ResinCharge
    covering the mould's full shot mass.

    Adds the keys ``resin_lot``, ``resin_lot_id``, ``production_order``,
    ``production_order_id``, ``molding_cycle``, ``molding_cycle_id`` and
    ``resin_charge``/``resin_charge_id`` to the context it returns.
    """
    if baseline is not None and baseline_kwargs:
        raise TypeError(
            "setup_scheduled_cycle: cannot honour %s alongside an explicit "
            "baseline= — the plant that baseline names is already built, so these "
            "keys would be silently discarded. Pass them to create_plant_baseline() "
            "when you build the baseline instead."
            % ", ".join(sorted(baseline_kwargs))
        )
    ctx = dict(baseline or create_plant_baseline(**baseline_kwargs))
    lot = create_resin_lot(**(lot_overrides or {}))
    order = create_production_order(ctx, **(order_overrides or {}))
    cycle = schedule_cycle(ctx, order, **(cycle_overrides or {}))
    ctx.update(
        {
            "resin_lot": lot,
            "resin_lot_id": lot["id"],
            "production_order": order,
            "production_order_id": order["id"],
            "molding_cycle": cycle,
            "molding_cycle_id": cycle["id"],
            "resin_charge": None,
            "resin_charge_id": None,
        }
    )
    if charge:
        reserved = reserve_charge(ctx, cycle, lot, **(charge_overrides or {}))
        ctx["resin_charge"] = reserved
        ctx["resin_charge_id"] = reserved["id"]
    return ctx


def run_cycle_to_oven_running(
    ctx: dict[str, Any], *, actual_oven_start_at: str = DEFAULT_OVEN_START
) -> dict[str, Any]:
    """Start the oven leg, leaving the cycle OVEN_RUNNING.

    The clock is set to the same instant that is stamped as
    ``actual_oven_start_at``, so the run is anchored on a known clock reading.
    """
    set_clock(actual_oven_start_at)
    cycle = get_success_data(
        api_client.start_oven(
            ctx["molding_cycle_id"],
            f.start_oven_payload(actual_oven_start_at),
            ctx["operator_headers"],
        )
    )
    ctx["molding_cycle"] = cycle
    ctx["clock"] = actual_oven_start_at
    return ctx


def run_cycle_to_cooling(
    ctx: dict[str, Any],
    *,
    actual_oven_start_at: str = DEFAULT_OVEN_START,
    actual_oven_end_at: str = DEFAULT_OVEN_END,
) -> dict[str, Any]:
    """Take a SCHEDULED cycle through the oven leg into COOLING.

    Sets the clock to each instant before stamping it. On return the cycle is
    COOLING with ``actual_oven_minutes`` floored from the two oven stamps.
    """
    if ctx["molding_cycle"].get("status") == "SCHEDULED":
        run_cycle_to_oven_running(ctx, actual_oven_start_at=actual_oven_start_at)
    set_clock(actual_oven_end_at)
    cycle = get_success_data(
        api_client.enter_cooling(
            ctx["molding_cycle_id"],
            f.enter_cooling_payload(actual_oven_end_at),
            ctx["operator_headers"],
        )
    )
    ctx["molding_cycle"] = cycle
    ctx["clock"] = actual_oven_end_at
    return ctx


def run_cycle_to_demold(
    ctx: dict[str, Any],
    *,
    actual_oven_start_at: str = DEFAULT_OVEN_START,
    actual_oven_end_at: str = DEFAULT_OVEN_END,
    actual_cooling_end_at: str = DEFAULT_COOLING_END,
) -> dict[str, Any]:
    """Take a cycle all the way to DEMOLDED and collect the hulls it minted.

    The default instants give a sixty minute oven leg and a thirty-five minute
    cooling leg, which clears the default model's ``min_cooling_minutes`` of 30.
    Demoulding consumes the reserved charge, scores
    ``provisional_warpage_index``, advances the mould's service counter and
    mints one FinishedUnit per cavity — two with the default mould.

    Adds ``finished_units`` (ordered by ``cavity_index``) and
    ``finished_unit_ids`` to the context.
    """
    if ctx["molding_cycle"].get("status") in ("SCHEDULED", "OVEN_RUNNING"):
        run_cycle_to_cooling(
            ctx,
            actual_oven_start_at=actual_oven_start_at,
            actual_oven_end_at=actual_oven_end_at,
        )
    set_clock(actual_cooling_end_at)
    cycle = get_success_data(
        api_client.demold(
            ctx["molding_cycle_id"],
            f.demold_payload(actual_cooling_end_at),
            ctx["operator_headers"],
        )
    )
    ctx["molding_cycle"] = cycle
    ctx["clock"] = actual_cooling_end_at
    units = list_units_for_cycle(ctx["molding_cycle_id"])
    ctx["finished_units"] = units
    ctx["finished_unit_ids"] = [unit["id"] for unit in units]
    return ctx


def list_units_for_cycle(molding_cycle_id: str) -> list[dict[str, Any]]:
    """Return the hulls a cycle minted, ordered by ``cavity_index``."""
    body = api_client.list_finished_units(
        {"molding_cycle_id": molding_cycle_id, "limit": 100}, ADMIN_HEADERS
    ).json()
    rows = body.get("data") or []
    return sorted(rows, key=lambda unit: unit.get("cavity_index", 0))


def setup_demolded_units(**kwargs: Any) -> dict[str, Any]:
    """Shortcut to a DEMOLDED cycle whose hulls exist and are UNALLOCATED.

    Every hull is ``build_status`` DEMOLDED, ``logistics_status`` UNALLOCATED
    and ``inspection_verdict`` PENDING.
    """
    run_kwargs = {
        key: kwargs.pop(key)
        for key in (
            "actual_oven_start_at",
            "actual_oven_end_at",
            "actual_cooling_end_at",
        )
        if key in kwargs
    }
    return run_cycle_to_demold(setup_scheduled_cycle(**kwargs), **run_kwargs)


# ----------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — finishing a hull
# ----------------------------------------------------------------------


def advance_unit_to_outfitted(
    ctx: dict[str, Any],
    unit: dict[str, Any],
    *,
    trim_waste_kg: float = 0.4,
    hardware_kit_serial: str | None = None,
) -> dict[str, Any]:
    """Trim then outfit one hull, leaving it OUTFITTED.

    Both calls act as the context's AssemblyTechnician, so
    ``outfitted_by_technician_id`` is that technician — which PRD.md
    section 3.6 permanently bars from inspecting this hull.
    """
    get_success_data(
        api_client.trim_finished_unit(
            unit["id"], f.trim_payload(trim_waste_kg), ctx["assembly_headers"]
        )
    )
    return get_success_data(
        api_client.outfit_finished_unit(
            unit["id"],
            f.outfit_payload(hardware_kit_serial),
            ctx["assembly_headers"],
        )
    )


def advance_unit_to_sellable(
    ctx: dict[str, Any],
    unit: dict[str, Any],
    *,
    trim_waste_kg: float = 0.4,
    hardware_kit_serial: str | None = None,
    **inspect_overrides: Any,
) -> dict[str, Any]:
    """Trim, outfit and inspect one hull so it becomes SELLABLE.

    The inspection is performed by the context's QualityInspector, who is
    neither the cycle's operator nor the hull's outfitter, so segregation of
    duties holds. The default readings clear every gate the default product
    model declares, so the verdict is PASS, ``final_warpage_index`` is 0.000
    and ``build_status`` becomes SELLABLE.
    """
    advance_unit_to_outfitted(
        ctx,
        unit,
        trim_waste_kg=trim_waste_kg,
        hardware_kit_serial=hardware_kit_serial,
    )
    return get_success_data(
        api_client.inspect_finished_unit(
            unit["id"], f.inspect_payload(**inspect_overrides), ctx["inspector_headers"]
        )
    )


def setup_sellable_units(*, unit_count: int | None = None, **kwargs: Any) -> dict[str, Any]:
    """Take every hull of a demoulded cycle through to SELLABLE.

    With ``unit_count`` set, only the first that many hulls are advanced and the
    rest are left DEMOLDED, which is how a partially finished order is built.

    Adds ``sellable_units`` and ``sellable_unit_ids``, and refreshes
    ``production_order`` — with the default mould and an ``ordered_qty`` of 2,
    finishing both hulls moves the order to COMPLETE.
    """
    ctx = setup_demolded_units(**kwargs)
    targets = ctx["finished_units"][: unit_count or len(ctx["finished_units"])]
    advanced = [advance_unit_to_sellable(ctx, unit) for unit in targets]
    ctx["sellable_units"] = advanced
    ctx["sellable_unit_ids"] = [unit["id"] for unit in advanced]
    ctx["production_order"] = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ADMIN_HEADERS
    )
    return ctx


def setup_rework_unit(**kwargs: Any) -> dict[str, Any]:
    """Take one hull to REWORK through an adverse cosmetic grade.

    A ``cosmetic_defect_grade`` of C reaches clause 7 of the verdict ladder in
    PRD.md section 3.6, which yields REWORK, while the wall readings and impact
    result still clear the earlier scrap clauses. The hull ends with
    ``build_status`` REWORK, ``inspection_verdict`` REWORK and ``rework_count``
    1. Adds ``rework_unit``.
    """
    ctx = setup_demolded_units(**kwargs)
    unit = ctx["finished_units"][0]
    ctx["rework_unit"] = advance_unit_to_sellable(
        ctx, unit, cosmetic_defect_grade="C"
    )
    return ctx


def setup_scrapped_unit(**kwargs: Any) -> dict[str, Any]:
    """Take one hull to SCRAPPED through a rejected cosmetic grade.

    A ``cosmetic_defect_grade`` of REJECT is clause 3 of the verdict ladder, so
    the hull ends SCRAPPED with ``inspection_verdict`` SCRAP and the order's
    ``scrapped_qty`` recomputed. Adds ``scrapped_unit``.
    """
    ctx = setup_demolded_units(**kwargs)
    unit = ctx["finished_units"][0]
    ctx["scrapped_unit"] = advance_unit_to_sellable(
        ctx, unit, cosmetic_defect_grade="REJECT"
    )
    return ctx


# ----------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting — storage
# ----------------------------------------------------------------------


def store_unit(ctx: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    """Store one SELLABLE hull into the producing order's target warehouse.

    The warehouse version is re-read immediately before the write. The server
    chooses the zone; the first hull of a model in a zone becomes the nest
    anchor and pays the model's full ``gross_cube_m3``, and later hulls of the
    same model pay ``gross_cube_m3`` times ``nest_factor``.
    """
    return get_success_data(
        api_client.store_finished_unit(
            unit["id"],
            f.store_payload(warehouse_version(ctx["warehouse_id"])),
            PLANNER_HEADERS,
        )
    )


def setup_stored_units(*, unit_count: int | None = None, **kwargs: Any) -> dict[str, Any]:
    """Store every SELLABLE hull of a finished cycle.

    With the default mould, model and warehouse this stores two hulls into the
    single zone: the first is the anchor at 2.0000 cube and the second nests at
    1.0000 cube, leaving the site at 3.0000 committed cube of its 20.0000
    capacity — 15.00 percent, posture NORMAL.

    Adds ``stored_units``, ``stored_unit_ids`` and a refreshed ``warehouse``.
    """
    ctx = setup_sellable_units(**kwargs)
    targets = ctx["sellable_units"][: unit_count or len(ctx["sellable_units"])]
    stored = [store_unit(ctx, unit) for unit in targets]
    ctx["stored_units"] = stored
    ctx["stored_unit_ids"] = [unit["id"] for unit in stored]
    ctx["warehouse"] = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], PLANNER_HEADERS
    )
    return ctx


def setup_warehouse_at_posture(posture: str, **kwargs: Any) -> dict[str, Any]:
    """Store one hull into a site sized so its posture lands on ``posture``.

    One stored anchor hull of the default model commits exactly 2.0000 cube, so
    the site capacity alone fixes the utilisation PRD.md section 3.7 derives:
    20.0000 gives 10.00 percent and NORMAL, 2.2222 gives 90.00 percent and
    RESTRICTED, and 2.0000 gives 100.00 percent and FROZEN.

    Only one hull is stored, so the second hull of the cycle stays SELLABLE and
    UNALLOCATED and is available as the next candidate — which is how a store
    into a frozen site is exercised. Adds ``stored_units`` with one element.
    """
    if "baseline" in kwargs:
        raise TypeError(
            "setup_warehouse_at_posture sizes the site through warehouse_overrides, "
            "which an already-built baseline= cannot accept — the posture would "
            "silently come back NORMAL. Size the site yourself with "
            "create_plant_baseline(warehouse_overrides=...) instead."
        )
    capacity = {
        "NORMAL": 20.0,
        "RESTRICTED": 2.2222,
        "FROZEN": 2.0,
    }[posture]
    kwargs.setdefault(
        "warehouse_overrides",
        {
            "footprint_capacity_cube_m3": capacity,
            "zones": [f.zone(f.DEFAULT_ZONE_CODE, capacity)],
        },
    )
    return setup_stored_units(unit_count=1, **kwargs)


def setup_build_ahead_bucket(
    *, forecast_qty: int = 2, build_ahead_cap_pct: float = 60.0, **kwargs: Any
) -> dict[str, Any]:
    """Store hulls against a demand bucket so the build-ahead quota is in play.

    The bucket's ``build_ahead_cap_qty`` is the floor of ``forecast_qty`` times
    ``build_ahead_cap_pct`` over 100, so the defaults give a cap of 1: the first
    hull stores and lands exactly on the cap, and a second store of the same
    bucket is the request PRD.md refuses with ERR_BUILD_AHEAD_CAP_EXCEEDED.

    The order names the bucket, so a stored hull copies ``demand_bucket_id`` and
    counts toward ``build_ahead_committed_qty``. Adds ``demand_bucket``,
    ``demand_bucket_id`` and stores exactly one hull.
    """
    baseline = kwargs.pop("baseline", None) or create_plant_baseline()
    bucket = create_demand_bucket(
        baseline, forecast_qty=forecast_qty, build_ahead_cap_pct=build_ahead_cap_pct
    )
    order_overrides = dict(kwargs.pop("order_overrides", {}))
    order_overrides.setdefault("demand_bucket_id", bucket["id"])
    ctx = setup_stored_units(
        baseline=baseline, order_overrides=order_overrides, unit_count=1, **kwargs
    )
    ctx["demand_bucket"] = api_client.read_entity(
        "get_demand_forecast_bucket", bucket["id"], PLANNER_HEADERS
    )
    ctx["demand_bucket_id"] = bucket["id"]
    return ctx


def setup_mold_due_for_service(**kwargs: Any) -> dict[str, Any]:
    """Run enough cycles that the mould's service counter reaches its interval.

    ``service_interval_cycles`` is set to 1, so the single demoulded cycle
    leaves ``cycles_since_service`` at 1 and the mould in MAINTENANCE — the
    counter comparison in PRD.md triggers at or above the interval. A further
    cycle on that mould is the request the service rule refuses.

    Adds a refreshed ``mold``.
    """
    kwargs.setdefault("mold_overrides", {"service_interval_cycles": 1})
    ctx = setup_demolded_units(**kwargs)
    ctx["mold"] = api_client.read_entity("get_mold", ctx["mold_id"], ADMIN_HEADERS)
    return ctx


def setup_depleted_resin_lot(**kwargs: Any) -> dict[str, Any]:
    """Charge a lot whose ``received_kg`` exactly covers one shot.

    The lot receives 24.000 kg, the mould's full shot mass, so reserving one
    charge moves the whole ledger into ``reserved_kg`` and leaves
    ``available_kg`` at 0.000 with the conserved sum intact.

    Adds a refreshed ``resin_lot``.
    """
    kwargs.setdefault("lot_overrides", {"received_kg": 24.0})
    ctx = setup_scheduled_cycle(**kwargs)
    ctx["resin_lot"] = api_client.read_entity(
        "get_resin_lot", ctx["resin_lot_id"], ADMIN_HEADERS
    )
    return ctx


def setup_expired_resin_lot(
    *, expires_on: str = "2026-08-05", expiry_clock: str = "2026-08-06T00:00:00Z", **kwargs: Any
) -> dict[str, Any]:
    """Reserve a charge, then move the clock past the lot's expiry date.

    PRD.md section 2.5 makes setting the clock an active sweep: a lot whose
    ``expires_on`` calendar date now lies strictly before the clock's date is
    expired, and the cascade releases its reserved charges, aborts the cycles
    that depended on them and blocks the affected orders.

    Adds ``clock_result`` with the four sweep counters the call reported, plus
    refreshed ``resin_lot``, ``resin_charge``, ``molding_cycle`` and
    ``production_order``.
    """
    kwargs.setdefault("lot_overrides", {"expires_on": expires_on})
    ctx = setup_scheduled_cycle(**kwargs)
    ctx["clock_result"] = set_clock(expiry_clock)
    ctx["clock"] = expiry_clock
    ctx["resin_lot"] = api_client.read_entity(
        "get_resin_lot", ctx["resin_lot_id"], ADMIN_HEADERS
    )
    if ctx.get("resin_charge_id"):
        ctx["resin_charge"] = api_client.read_entity(
            "get_resin_charge", ctx["resin_charge_id"], ADMIN_HEADERS
        )
    ctx["molding_cycle"] = api_client.read_entity(
        "get_molding_cycle", ctx["molding_cycle_id"], ADMIN_HEADERS
    )
    ctx["production_order"] = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ADMIN_HEADERS
    )
    return ctx


# ----------------------------------------------------------------------
# Tier 3 continued: the trailer ladder
# ----------------------------------------------------------------------


def create_shipment(ctx: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Book a PLANNED trailer out of the context's warehouse.

    The default trailer holds 5.0000 cube and 200.000 kg. Two hulls of the
    default model nest to 3.0000 cube, which is exactly the 60.00 percent
    utilisation PRD.md section 3.8 sets as the minimum for sealing, and selects
    the 3.00 percent volume discount tier.
    """
    return get_success_data(
        api_client.create_shipment(
            f.shipment_payload(ctx["warehouse_id"], **overrides), PLANNER_HEADERS
        )
    )


def load_unit(
    ctx: dict[str, Any], shipment: dict[str, Any], unit: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    """Add one STORED hull to a trailer as a LOADED line.

    The shipment version is re-read immediately before the write. The hull moves
    STORED to LOADED without any footprint movement, and the first line on a
    PLANNED trailer moves it to LOADING.
    """
    return get_success_data(
        api_client.create_shipment_line(
            f.shipment_line_payload(
                shipment["id"],
                unit["id"],
                shipment_version(shipment["id"]),
                **overrides,
            ),
            PLANNER_HEADERS,
        )
    )


def setup_loaded_shipment(
    *, line_count: int | None = None, shipment_overrides: dict[str, Any] | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Store the cycle's hulls, book a trailer and load them all onto it.

    On return the shipment is LOADING with one LOADED line per hull, each hull
    LOADED but still occupying its warehouse zone, and the rollups recomputed:
    with the two default hulls that is ``loaded_cube_m3`` 4.0000,
    ``nested_cube_m3`` 3.0000, ``loaded_weight_kg`` 48.000 and
    ``cube_utilization_pct`` 60.00.

    Adds ``shipment``, ``shipment_id``, ``shipment_lines`` and
    ``shipment_line_ids``.
    """
    ctx = setup_stored_units(**kwargs)
    shipment = create_shipment(ctx, **(shipment_overrides or {}))
    targets = ctx["stored_units"][: line_count or len(ctx["stored_units"])]
    lines = [load_unit(ctx, shipment, unit) for unit in targets]
    ctx["shipment"] = api_client.read_entity(
        "get_shipment", shipment["id"], PLANNER_HEADERS
    )
    ctx["shipment_id"] = shipment["id"]
    ctx["shipment_lines"] = lines
    ctx["shipment_line_ids"] = [line["id"] for line in lines]
    return ctx


def setup_sealed_shipment(**kwargs: Any) -> dict[str, Any]:
    """Seal a loaded trailer, which prices the QUOTED freight variant.

    Sealing requires LOADING, at least one line and a ``cube_utilization_pct``
    at or above 60.00. On return the shipment is SEALED with
    ``quoted_freight_cents`` set and ``sealed_at`` stamped from the clock, and
    ``billed_freight_cents`` still null.
    """
    ctx = setup_loaded_shipment(**kwargs)
    ctx["shipment"] = get_success_data(
        api_client.seal_shipment(ctx["shipment_id"], PLANNER_HEADERS)
    )
    return ctx


def setup_departed_shipment(*, departed_at: str = DEFAULT_DEPART_AT, **kwargs: Any) -> dict[str, Any]:
    """Dispatch a sealed trailer, which frees the hulls' warehouse footprint.

    The clock is set to ``departed_at`` before the stamp. On return the shipment
    is IN_TRANSIT, every hull is IN_TRANSIT with its ``storage_zone_code``,
    ``stored_at`` and ``demand_bucket_id`` cleared and its
    ``stored_footprint_cube_m3`` zeroed, and the origin site's committed cube,
    utilisation and posture have been recomputed downward.

    Adds a refreshed ``warehouse``.
    """
    ctx = setup_sealed_shipment(**kwargs)
    set_clock(departed_at)
    ctx["clock"] = departed_at
    ctx["shipment"] = get_success_data(
        api_client.depart_shipment(
            ctx["shipment_id"], f.depart_payload(departed_at), PLANNER_HEADERS
        )
    )
    ctx["warehouse"] = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], PLANNER_HEADERS
    )
    return ctx


def setup_delivered_units(*, delivered_at: str = DEFAULT_DELIVER_AT, **kwargs: Any) -> dict[str, Any]:
    """Deliver a departed trailer, which starts each hull's warranty clock.

    The clock is set to ``delivered_at`` before the stamp, so every hull's own
    ``delivered_at`` — the origin of the warranty clock — is that instant. On
    return the shipment is DELIVERED with ``billed_freight_cents`` set from the
    gross-cube BILLED variant, and every hull is DELIVERED with
    ``warehouse_id`` cleared.

    Adds ``delivered_units`` and ``delivered_unit_ids``.
    """
    ctx = setup_departed_shipment(**kwargs)
    set_clock(delivered_at)
    ctx["clock"] = delivered_at
    ctx["shipment"] = get_success_data(
        api_client.deliver_shipment(
            ctx["shipment_id"], f.deliver_payload(delivered_at), PLANNER_HEADERS
        )
    )
    delivered = [
        api_client.read_entity("get_finished_unit", unit_id, PLANNER_HEADERS)
        for unit_id in ctx["stored_unit_ids"]
    ]
    ctx["delivered_units"] = delivered
    ctx["delivered_unit_ids"] = [unit["id"] for unit in delivered]
    ctx["delivered_at"] = delivered_at
    return ctx


# ----------------------------------------------------------------------
# Tier 5: finalisation and terminal state — the warranty ladder
# ----------------------------------------------------------------------


def setup_delivered_unit_with_customer(
    *,
    acknowledged_at: str = CLOCK_DEFAULT_UTC,
    delivered_at: str = DEFAULT_DELIVER_AT,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deliver hulls and register a customer who acknowledged storage guidance.

    The acknowledgement is dated on the clock's startup default, well before
    ``delivered_at``, which is what a VERIFIED storage review requires in
    PRD.md section 3.9.

    Adds ``customer``, ``customer_id``, ``customer_headers`` and ``unit`` — the
    first delivered hull, the one the claim ladder files against.
    """
    account = create_customer(acknowledged_at=acknowledged_at)
    ctx = setup_delivered_units(delivered_at=delivered_at, **kwargs)
    ctx["customer"] = account["customer"]
    ctx["customer_id"] = account["customer_id"]
    ctx["customer_headers"] = account["headers"]
    ctx["unit"] = ctx["delivered_units"][0]
    ctx["unit_id"] = ctx["delivered_units"][0]["id"]
    return ctx


def setup_submitted_claim(**kwargs: Any) -> dict[str, Any]:
    """File one claim against a delivered hull.

    The claim is a HULL_DEFORMATION claim whose ``reported_deformation_mm`` of
    4.50 clears the 3.00 mm threshold. It starts SUBMITTED with
    ``storage_review_status`` NOT_STARTED, no money fields set and version 1.

    Adds ``warranty_claim`` and ``warranty_claim_id``.
    """
    claim_overrides = dict(kwargs.pop("claim_overrides", {}))
    ctx = setup_delivered_unit_with_customer(**kwargs)
    claim = get_success_data(
        api_client.create_warranty_claim(
            f.warranty_claim_payload(
                ctx["unit_id"], ctx["customer_id"], **claim_overrides
            ),
            AGENT_HEADERS,
        )
    )
    ctx["warranty_claim"] = claim
    ctx["warranty_claim_id"] = claim["id"]
    return ctx


def setup_claim_under_review(**kwargs: Any) -> dict[str, Any]:
    """Move a submitted claim into review, which freezes its age.

    Starting review computes ``months_in_service`` as the complete calendar
    months from the hull's ``delivered_at`` to the clock, floored. With the
    ladder's default instants the clock still stands at delivery, so the frozen
    age is 0 months and a PRO_RATA_AGE model covers 100.00 percent.
    """
    ctx = setup_submitted_claim(**kwargs)
    ctx["warranty_claim"] = get_success_data(
        api_client.start_claim_review(ctx["warranty_claim_id"], AGENT_HEADERS)
    )
    return ctx


def setup_claim_storage_verified(**kwargs: Any) -> dict[str, Any]:
    """Decide the storage axis as VERIFIED on a claim under review.

    VERIFIED requires the customer's ``storage_guidance_acknowledged_at`` to be
    non-null and at or before the hull's ``delivered_at``, which the ladder's
    customer satisfies. The axis becomes GUIDANCE_VERIFIED, the adjudication
    axis stays UNDER_REVIEW, and the eventual approval carries a zero storage
    deduction.
    """
    ctx = setup_claim_under_review(**kwargs)
    ctx["warranty_claim"] = get_success_data(
        api_client.submit_storage_review(
            ctx["warranty_claim_id"],
            f.storage_review_payload("VERIFIED"),
            AGENT_HEADERS,
        )
    )
    return ctx


def setup_claim_storage_violated(**kwargs: Any) -> dict[str, Any]:
    """Decide the storage axis as VIOLATED on a claim under review.

    The axis becomes GUIDANCE_VIOLATED, which blocks approval until a
    PlantAdmin waives the finding, and forces a denial's ``denial_reason`` to
    STORAGE_GUIDANCE_VIOLATED whatever the request body asks for.
    """
    ctx = setup_claim_under_review(**kwargs)
    ctx["warranty_claim"] = get_success_data(
        api_client.submit_storage_review(
            ctx["warranty_claim_id"],
            f.storage_review_payload("VIOLATED"),
            AGENT_HEADERS,
        )
    )
    return ctx


def setup_claim_storage_waived(**kwargs: Any) -> dict[str, Any]:
    """Waive a violated storage finding, which unblocks approval at a cost.

    The axis becomes WAIVED. A claim approved from WAIVED still pays the
    35.00 percent storage deduction, so this is the fixture that separates a
    waiver from a clean VERIFIED review.
    """
    ctx = setup_claim_storage_violated(**kwargs)
    ctx["warranty_claim"] = get_success_data(
        api_client.waive_storage_finding(
            ctx["warranty_claim_id"],
            f.waive_storage_finding_payload(),
            ADMIN_HEADERS,
        )
    )
    return ctx


def setup_approved_claim(*, waived: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Approve a claim, which is the only path that spends the reserve.

    With ``waived`` false the claim is approved from GUIDANCE_VERIFIED and the
    storage deduction is 0; with ``waived`` true it is approved from WAIVED and
    the 35.00 percent deduction applies. The model's version is re-read
    immediately before the write, so ``expected_product_model_version`` is
    current.

    On return the claim is APPROVED with all four money fields set and
    ``payout_basis`` copied from the model, and the model's reserve has moved:
    ``warranty_reserve_cents`` down and ``warranty_paid_cents`` up by the
    identical ``net_payout_cents``.

    Adds a refreshed ``product_model``.
    """
    ctx = (
        setup_claim_storage_waived(**kwargs)
        if waived
        else setup_claim_storage_verified(**kwargs)
    )
    ctx["warranty_claim"] = get_success_data(
        api_client.approve_warranty_claim(
            ctx["warranty_claim_id"],
            f.approve_claim_payload(product_model_version(ctx["product_model_id"])),
            AGENT_HEADERS,
        )
    )
    ctx["product_model"] = api_client.read_entity(
        "get_product_model", ctx["product_model_id"], ADMIN_HEADERS
    )
    return ctx


def setup_denied_claim(
    *, denial_reason: str = "NOT_A_MANUFACTURING_DEFECT", **kwargs: Any
) -> dict[str, Any]:
    """Deny a claim whose storage axis has been decided.

    Denial requires the storage axis to be anything but NOT_STARTED. On return
    the claim is DENIED with all four money fields set to an explicit 0 and no
    reserve movement.
    """
    ctx = setup_claim_storage_verified(**kwargs)
    ctx["warranty_claim"] = get_success_data(
        api_client.deny_warranty_claim(
            ctx["warranty_claim_id"],
            f.deny_claim_payload(denial_reason),
            AGENT_HEADERS,
        )
    )
    return ctx


# ----------------------------------------------------------------------
# Resource contention: a second schedulable order beside a stored cycle
# ----------------------------------------------------------------------


def overlapping_window(
    cycle: dict[str, Any],
    *,
    start_offset_minutes: int = 0,
    oven_minutes: int | None = None,
) -> dict[str, Any]:
    """Cycle-creation overrides whose oven window sits beside ``cycle``'s.

    ``start_offset_minutes`` is measured from the stored cycle's
    ``oven_start_at``, so 0 reproduces it exactly, a negative value starts
    earlier and a positive value starts later. PRD.md section 3.4 treats the
    oven window as half-open, so an offset equal to the stored cycle's oven
    duration abuts without overlapping unless the station's changeover buffer
    pushes the two apart. ``oven_minutes`` overrides the new cycle's own oven
    duration; by default it matches the stored cycle's.
    """
    minutes = (
        cycle["scheduled_oven_minutes"] if oven_minutes is None else oven_minutes
    )
    return {
        "oven_start_at": shift_minutes(cycle["oven_start_at"], start_offset_minutes),
        "scheduled_oven_minutes": minutes,
    }


def setup_cycle_with_spare_order(**kwargs: Any) -> dict[str, Any]:
    """A SCHEDULED cycle plus a second released order ready to schedule.

    Builds ``setup_scheduled_cycle`` and then adds one more ResinLot and one
    more ProductionOrder released to READY_TO_SCHEDULE against the same model,
    warehouse, station and cooling bay. Nothing is scheduled for the second
    order, so a test can attempt its own cycle — overlapping, abutting or on
    another arm — and observe the resource rules of PRD.md section 3.4.

    Adds ``spare_production_order``/``spare_production_order_id`` and
    ``spare_resin_lot``/``spare_resin_lot_id`` to the context.
    """
    ctx = setup_scheduled_cycle(**kwargs)
    spare_lot = create_resin_lot()
    spare_order = create_production_order(ctx)
    ctx.update(
        {
            "spare_resin_lot": spare_lot,
            "spare_resin_lot_id": spare_lot["id"],
            "spare_production_order": spare_order,
            "spare_production_order_id": spare_order["id"],
        }
    )
    return ctx


def setup_cooling_bay_at_capacity(**kwargs: Any) -> dict[str, Any]:
    """A cooling bay whose single concurrent slot is already taken.

    Same shape as ``setup_cycle_with_spare_order`` but the bay is created with
    ``concurrent_slot_capacity`` 1, so the stored SCHEDULED cycle already
    occupies the bay for its whole closed cooling interval and any second cycle
    overlapping that interval must be refused.
    """
    kwargs.setdefault("bay_overrides", {"concurrent_slot_capacity": 1})
    return setup_cycle_with_spare_order(**kwargs)


# ----------------------------------------------------------------------
# Cascade preconditions: equipment down, mould service, lot quarantine
# ----------------------------------------------------------------------


def setup_station_down(**kwargs: Any) -> dict[str, Any]:
    """A SCHEDULED cycle whose oven station has since been marked DOWN.

    Marks the context's station DOWN after the cycle is stored, which PRD.md
    section 3.4 says leaves the cycle in place while blocking any further
    scheduling on that station. Refreshes ``oven_station`` and
    ``molding_cycle`` and adds ``down_reason``.
    """
    ctx = setup_scheduled_cycle(**kwargs)
    reason = "Burner service"
    ctx["oven_station"] = get_success_data(
        api_client.mark_down_oven_station(
            ctx["oven_station_id"], f.mark_down_payload(reason), ADMIN_HEADERS
        )
    )
    ctx["down_reason"] = reason
    ctx["molding_cycle"] = api_client.read_entity(
        "get_molding_cycle", ctx["molding_cycle_id"]
    )
    return ctx


def setup_mold_on_service_hold(**kwargs: Any) -> dict[str, Any]:
    """A plant baseline whose only mould is in MAINTENANCE.

    Places the mould on service hold straight from AVAILABLE, so scheduling a
    cycle for its product model has no usable mould. Refreshes ``mold`` and
    adds ``hold_note``.
    """
    ctx = create_plant_baseline(**kwargs)
    note = "Vent tube inspection"
    ctx["mold"] = get_success_data(
        api_client.service_hold_mold(
            ctx["mold_id"], f.service_hold_payload(note), ADMIN_HEADERS
        )
    )
    ctx["hold_note"] = note
    return ctx


def setup_quarantined_lot_with_charge(**kwargs: Any) -> dict[str, Any]:
    """A SCHEDULED cycle whose reserved lot has since been QUARANTINED.

    Builds the charge first and then quarantines the lot, which is the
    precondition PRD.md section 3.2 describes for the quarantine cascade: the
    lot leaves AVAILABLE while its reserved mass is accounted for. Quarantine
    carries no version declaration, so nothing is re-read before the write.
    Refreshes ``resin_lot``, ``resin_charge`` and ``molding_cycle`` and adds
    ``quarantine_reason``.
    """
    ctx = setup_scheduled_cycle(**kwargs)
    reason = "Colour drift audit"
    ctx["resin_lot"] = get_success_data(
        api_client.quarantine_resin_lot(
            ctx["resin_lot_id"], f.quarantine_payload(reason), ADMIN_HEADERS
        )
    )
    ctx["quarantine_reason"] = reason
    if ctx.get("resin_charge_id"):
        ctx["resin_charge"] = api_client.read_entity(
            "get_resin_charge", ctx["resin_charge_id"]
        )
    ctx["molding_cycle"] = api_client.read_entity(
        "get_molding_cycle", ctx["molding_cycle_id"]
    )
    return ctx
