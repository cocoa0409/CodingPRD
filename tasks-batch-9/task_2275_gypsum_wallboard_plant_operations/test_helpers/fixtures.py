"""Composite setup helpers.

The harness restarts the API with an empty database before every test, so every
piece of state a test needs has to be built here through the public endpoints.
The helpers are layered: each tier calls the one below it and adds one stage of
the gypsum-to-load chain, and every one of them accepts ``**overrides`` so a test
can move a single input without restating the whole chain.

Tier 1  ``create_plant``                  a registered plant
Tier 2  ``baseline``                      plant, board line, two SKUs, one market
Tier 3  ``baseline_with_lots``            two assayed gypsum lots
Tier 4  ``baseline_with_stucco``          a completed batch crediting the silo
Tier 5  ``scheduled_run`` and friends     a run through schedule, start, complete,
                                          specimens, evaluation and load staging
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from . import test_users as users
from .api_client import ApiClient

JsonDict = dict[str, Any]


# --------------------------------------------------------------------------- #
# The world object
# --------------------------------------------------------------------------- #


@dataclass
class World:
    """Every entity a layered fixture has created, keyed by its role in the chain."""

    api: ApiClient
    plant: JsonDict = field(default_factory=dict)
    line: JsonDict = field(default_factory=dict)
    spec_reg: JsonDict = field(default_factory=dict)
    spec_tx: JsonDict = field(default_factory=dict)
    market: JsonDict = field(default_factory=dict)
    lot_a: JsonDict = field(default_factory=dict)
    lot_b: JsonDict = field(default_factory=dict)
    batch: JsonDict = field(default_factory=dict)
    batch_2: JsonDict = field(default_factory=dict)
    run: JsonDict = field(default_factory=dict)
    run_2: JsonDict = field(default_factory=dict)
    load: JsonDict = field(default_factory=dict)
    load_2: JsonDict = field(default_factory=dict)
    outage: JsonDict = field(default_factory=dict)

    # -- convenient identifiers ------------------------------------------- #

    @property
    def plant_id(self) -> str:
        return self.plant["id"]

    @property
    def line_id(self) -> str:
        return self.line["id"]

    @property
    def spec_reg_id(self) -> str:
        return self.spec_reg["id"]

    @property
    def spec_tx_id(self) -> str:
        return self.spec_tx["id"]

    @property
    def market_id(self) -> str:
        return self.market["id"]

    @property
    def lot_a_id(self) -> str:
        return self.lot_a["id"]

    @property
    def lot_b_id(self) -> str:
        return self.lot_b["id"]

    @property
    def batch_id(self) -> str:
        return self.batch["id"]

    @property
    def run_id(self) -> str:
        return self.run["id"]

    @property
    def load_id(self) -> str:
        return self.load["id"]

    @property
    def outage_id(self) -> str:
        return self.outage["id"]

    # -- fresh reads ------------------------------------------------------ #

    def read_plant(self) -> JsonDict:
        self.plant = read_plant(self.api, self.plant_id)
        return self.plant

    def read_line(self) -> JsonDict:
        self.line = read_line(self.api, self.line_id)
        return self.line

    def read_lot_a(self) -> JsonDict:
        self.lot_a = read_lot(self.api, self.lot_a_id)
        return self.lot_a

    def read_lot_b(self) -> JsonDict:
        self.lot_b = read_lot(self.api, self.lot_b_id)
        return self.lot_b

    def read_batch(self, batch_id: Optional[str] = None) -> JsonDict:
        batch = read_batch(self.api, batch_id or self.batch_id)
        if batch_id in (None, self.batch.get("id")):
            self.batch = batch
        return batch

    def read_run(self, run_id: Optional[str] = None) -> JsonDict:
        run = read_run(self.api, run_id or self.run_id)
        if run_id in (None, self.run.get("id")):
            self.run = run
        return run

    def read_load(self, load_id: Optional[str] = None) -> JsonDict:
        load = read_load(self.api, load_id or self.load_id)
        if load_id in (None, self.load.get("id")):
            self.load = load
        return load

    def read_outage(self, outage_id: Optional[str] = None) -> JsonDict:
        outage = read_outage(self.api, outage_id or self.outage_id)
        if outage_id in (None, self.outage.get("id")):
            self.outage = outage
        return outage

    def plant_version(self) -> int:
        return int(self.read_plant()["version"])


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def read_plant(api: ApiClient, plant_id: str) -> JsonDict:
    return validate_success(api.get_plant(plant_id, users.PLANT_ADMIN))


def read_line(api: ApiClient, line_id: str) -> JsonDict:
    return validate_success(api.get_board_line(line_id, users.PLANT_ADMIN))


def read_spec(api: ApiClient, spec_id: str) -> JsonDict:
    return validate_success(api.get_product_spec(spec_id, users.PLANT_ADMIN))


def read_market(api: ApiClient, market_id: str) -> JsonDict:
    return validate_success(api.get_market(market_id, users.PLANT_ADMIN))


def read_lot(api: ApiClient, lot_id: str) -> JsonDict:
    return validate_success(api.get_gypsum_lot(lot_id, users.MATERIALS_CONTROLLER))


def read_batch(api: ApiClient, batch_id: str) -> JsonDict:
    return validate_success(api.get_calciner_batch(batch_id, users.MATERIALS_CONTROLLER))


def read_run(api: ApiClient, run_id: str) -> JsonDict:
    return validate_success(api.get_production_run(run_id, users.PRODUCTION_SCHEDULER))


def read_load(api: ApiClient, load_order_id: str) -> JsonDict:
    return validate_success(api.get_load_order(load_order_id, users.PRODUCTION_SCHEDULER))


def read_outage(api: ApiClient, outage_id: str) -> JsonDict:
    return validate_success(api.get_outage(outage_id, users.MAINTENANCE_PLANNER))


def plant_version(api: ApiClient, plant_id: str) -> int:
    """Read the plant purely to capture the OCC token scheduling requires."""
    return int(read_plant(api, plant_id)["version"])


def lot_version(api: ApiClient, lot_id: str) -> int:
    """Read the lot purely to capture the OCC token a feed requires."""
    return int(read_lot(api, lot_id)["version"])


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #


def set_clock(api: ApiClient, to_iso8601: str) -> JsonDict:
    return get_success_data(api.set_clock(to_iso8601, users.PLANT_ADMIN))


# --------------------------------------------------------------------------- #
# Tier 1: a plant
# --------------------------------------------------------------------------- #


def create_plant(api: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(api.create_plant(f.plant_payload(**overrides), users.PLANT_ADMIN))


def create_line(api: ApiClient, plant_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_board_line(plant_id, f.board_line_payload(**overrides), users.PLANT_ADMIN)
    )


def create_regular_spec(api: ApiClient, plant_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_product_spec(plant_id, f.regular_spec_payload(**overrides), users.PLANT_ADMIN)
    )


def create_type_x_spec(api: ApiClient, plant_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_product_spec(plant_id, f.type_x_spec_payload(**overrides), users.PLANT_ADMIN)
    )


def create_market(api: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(api.create_market(f.market_payload(**overrides), users.PLANT_ADMIN))


# --------------------------------------------------------------------------- #
# Tier 2: plant, line, both SKUs, market
# --------------------------------------------------------------------------- #


def baseline(
    api: ApiClient,
    plant: Optional[JsonDict] = None,
    line: Optional[JsonDict] = None,
    spec_reg: Optional[JsonDict] = None,
    spec_tx: Optional[JsonDict] = None,
    market: Optional[JsonDict] = None,
) -> World:
    """The GYP-1 plant with LINE-1, the REGULAR and TYPE_X SKUs and Denver Metro."""
    world = World(api=api)
    world.plant = create_plant(api, **(plant or {}))
    world.line = create_line(api, world.plant_id, **(line or {}))
    world.spec_reg = create_regular_spec(api, world.plant_id, **(spec_reg or {}))
    world.spec_tx = create_type_x_spec(api, world.plant_id, **(spec_tx or {}))
    world.market = create_market(api, **(market or {}))
    return world


# --------------------------------------------------------------------------- #
# Tier 3: assayed lots
# --------------------------------------------------------------------------- #


def create_lot(api: ApiClient, payload: JsonDict) -> JsonDict:
    return get_success_data(api.create_gypsum_lot(payload, users.MATERIALS_CONTROLLER))


def assay_lot(
    api: ApiClient,
    lot_id: str,
    free_moisture_pct: float,
    purity_pct: float,
    chloride_ppm: int,
) -> JsonDict:
    return get_success_data(
        api.assay_gypsum_lot(
            lot_id,
            f.assay_payload(free_moisture_pct, purity_pct, chloride_ppm),
            users.MATERIALS_CONTROLLER,
        )
    )


def synthetic_lot(
    api: ApiClient,
    plant_id: str,
    free_moisture_pct: float = 9.4,
    purity_pct: float = 94.0,
    chloride_ppm: int = 120,
    **overrides: Any,
) -> JsonDict:
    """A synthetic lot received and immediately assayed into ``APPROVED``."""
    lot = create_lot(api, f.synthetic_lot_payload(plant_id, **overrides))
    return assay_lot(api, lot["id"], free_moisture_pct, purity_pct, chloride_ppm)


def natural_lot(
    api: ApiClient,
    plant_id: str,
    free_moisture_pct: float = 2.6,
    purity_pct: float = 91.5,
    chloride_ppm: int = 80,
    **overrides: Any,
) -> JsonDict:
    """A natural lot received and immediately assayed into ``APPROVED``."""
    lot = create_lot(api, f.natural_lot_payload(plant_id, **overrides))
    return assay_lot(api, lot["id"], free_moisture_pct, purity_pct, chloride_ppm)


def baseline_with_lots(api: ApiClient, **baseline_kwargs: Any) -> World:
    """Tier 2 plus 300 t of Comanche FGD and 200 t of Loveland Quarry, both approved."""
    world = baseline(api, **baseline_kwargs)
    world.lot_a = synthetic_lot(api, world.plant_id)
    world.lot_b = natural_lot(api, world.plant_id)
    return world


# --------------------------------------------------------------------------- #
# Tier 4: batches, feeds and a credited silo
# --------------------------------------------------------------------------- #


def create_batch(api: ApiClient, plant_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_calciner_batch(
            f.calciner_batch_payload(plant_id, **overrides), users.MATERIALS_CONTROLLER
        )
    )


def feed(
    api: ApiClient,
    batch_id: str,
    lot_id: str,
    tons_fed: float,
    measured_free_moisture_pct: float,
    expected_lot_version: Optional[int] = None,
) -> JsonDict:
    """Feed a lot increment, re-reading the lot's version unless one is supplied."""
    version = (
        expected_lot_version if expected_lot_version is not None else lot_version(api, lot_id)
    )
    return get_success_data(
        api.create_batch_feed(
            batch_id,
            f.batch_feed_payload(lot_id, tons_fed, measured_free_moisture_pct, version),
            users.MATERIALS_CONTROLLER,
        )
    )


def close_feed(api: ApiClient, batch_id: str) -> JsonDict:
    return get_success_data(api.close_feed(batch_id, {}, users.MATERIALS_CONTROLLER))


def record_stucco_test(
    api: ApiClient,
    batch_id: str,
    sample_seq: int = 1,
    headers: Optional[dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.create_stucco_test(
            batch_id,
            f.stucco_test_payload(sample_seq=sample_seq, **overrides),
            headers or users.QUALITY_INSPECTOR,
        )
    )


def abort_batch(api: ApiClient, batch_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.abort_calciner_batch(batch_id, f.abort_payload(**overrides), users.MATERIALS_CONTROLLER)
    )


def fed_batch(api: ApiClient, world: World, **batch_overrides: Any) -> JsonDict:
    """The canonical B1 batch fed 120 t, 80 t and 60 t, then closed to ``CALCINING``.

    The three increments are the ones the design recipes use: two draws on the
    synthetic lot with a natural draw between them, which is what makes the
    plan and as-fed moisture bases disagree.
    """
    batch = create_batch(api, world.plant_id, **batch_overrides)
    feed(api, batch["id"], world.lot_a_id, 120.0, 10.2)
    feed(api, batch["id"], world.lot_b_id, 80.0, 3.1)
    feed(api, batch["id"], world.lot_a_id, 60.0, 9.8)
    return close_feed(api, batch["id"])


def baseline_with_stucco(api: ApiClient, **baseline_kwargs: Any) -> World:
    """Tier 3 plus batch B1 completed on a passing sample, crediting 204.530 tons."""
    world = baseline_with_lots(api, **baseline_kwargs)
    world.batch = fed_batch(api, world)
    record_stucco_test(api, world.batch_id)
    world.read_batch()
    world.read_plant()
    return world


def second_batch_completed(api: ApiClient, world: World) -> JsonDict:
    """Batch B2 on the 15:00-19:00 window, fed 120 t of lot A and completed.

    Its actual yield of 92.747 tons is the second silo credit the cascade and
    cross-entity recipes rely on.
    """
    batch = create_batch(
        api,
        world.plant_id,
        target_stucco_tons=100.0,
        feed_rate_tph=20.0,
        feed_window_start="2026-08-02T15:00:00Z",
        feed_window_end="2026-08-02T19:00:00Z",
    )
    feed(api, batch["id"], world.lot_a_id, 120.0, 9.4)
    close_feed(api, batch["id"])
    record_stucco_test(
        api,
        batch["id"],
        sample_seq=1,
        combined_water_pct=5.4,
        free_water_pct=0.2,
        set_time_minutes=8.0,
    )
    world.batch_2 = read_batch(api, batch["id"])
    return world.batch_2


# --------------------------------------------------------------------------- #
# The compact chain: one plant, one lot, one batch
# --------------------------------------------------------------------------- #


def compact_batch_world(
    api: ApiClient,
    tons_fed: float = 100.0,
    measured_free_moisture_pct: float = 10.0,
    received_tons: float = 100.0,
    assay: tuple[float, float, int] = (10.0, 90.0, 100),
    close: bool = True,
    **batch_overrides: Any,
) -> World:
    """A single Pawnee FGD lot fed into a single batch, optionally closed.

    A 100-ton draw at 10 percent moisture on a 90 percent pure lot gives a dry
    tonnage of exactly 90.000, which makes the hemihydrate arithmetic legible.
    """
    world = baseline(api)
    world.lot_a = synthetic_lot(
        api,
        world.plant_id,
        free_moisture_pct=assay[0],
        purity_pct=assay[1],
        chloride_ppm=assay[2],
        supplier_name="Pawnee FGD",
        received_tons=received_tons,
        declared_free_moisture_pct=10.0,
        declared_purity_pct=90.0,
    )
    defaults: JsonDict = {
        "target_stucco_tons": 80.0,
        "calcination_temp_f": 320.0,
        "feed_rate_tph": 25.0,
        "feed_window_start": "2026-08-02T08:00:00Z",
        "feed_window_end": "2026-08-02T12:00:00Z",
    }
    defaults.update(batch_overrides)
    world.batch = create_batch(api, world.plant_id, **defaults)
    feed(api, world.batch_id, world.lot_a_id, tons_fed, measured_free_moisture_pct)
    if close:
        world.batch = close_feed(api, world.batch_id)
    else:
        world.read_batch()
    return world


# --------------------------------------------------------------------------- #
# Tier 5: runs
# --------------------------------------------------------------------------- #


def draft_run(
    api: ApiClient,
    world: World,
    spec_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload = f.run_draft_payload(
        world.plant_id,
        world.line_id,
        spec_id or world.spec_reg_id,
        batch_id or world.batch_id,
        **overrides,
    )
    return get_success_data(api.create_production_run(payload, users.PRODUCTION_SCHEDULER))


def schedule(
    api: ApiClient,
    run_id: str,
    plant_id: str,
    expected_plant_version: Optional[int] = None,
) -> JsonDict:
    """Schedule a drafted run, re-reading the plant version unless one is supplied."""
    version = (
        expected_plant_version
        if expected_plant_version is not None
        else plant_version(api, plant_id)
    )
    return get_success_data(
        api.schedule_run(run_id, f.schedule_payload(version), users.PRODUCTION_SCHEDULER)
    )


def start(api: ApiClient, run_id: str) -> JsonDict:
    return get_success_data(api.start_run(run_id, {}, users.PRODUCTION_SCHEDULER))


def complete(api: ApiClient, run_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.complete_run(run_id, f.complete_run_payload(**overrides), users.PRODUCTION_SCHEDULER)
    )


def cancel_run(api: ApiClient, run_id: str, headers: Optional[dict[str, str]] = None,
               **overrides: Any) -> JsonDict:
    return get_success_data(
        api.cancel_run(
            run_id, f.cancel_run_payload(**overrides), headers or users.PRODUCTION_SCHEDULER
        )
    )


def scheduled_run(api: ApiClient, world: Optional[World] = None, **draft_overrides: Any) -> World:
    """Tier 4 plus run R1 scheduled: 300.000 MSF effective, 202.500 tons reserved."""
    world = world or baseline_with_stucco(api)
    world.run = draft_run(api, world, **draft_overrides)
    world.run = schedule(api, world.run_id, world.plant_id)
    world.read_plant()
    return world


def running_run(api: ApiClient, world: Optional[World] = None, **draft_overrides: Any) -> World:
    """A scheduled run started at its window_start of 2026-08-03T06:00:00Z."""
    world = scheduled_run(api, world, **draft_overrides)
    set_clock(api, "2026-08-03T06:00:00Z")
    world.run = start(api, world.run_id)
    world.read_plant()
    return world


def completed_run(
    api: ApiClient,
    world: Optional[World] = None,
    actual_msf: float = 295.0,
    scrap_msf: float = 5.0,
    edge_defect_ppm: int = 800,
    end_defect_ppm: int = 400,
    **draft_overrides: Any,
) -> World:
    """A run completed at 295.000 produced and 5.000 scrapped: 290.000 net good."""
    world = running_run(api, world, **draft_overrides)
    world.run = complete(
        api,
        world.run_id,
        actual_msf=actual_msf,
        scrap_msf=scrap_msf,
        edge_defect_ppm=edge_defect_ppm,
        end_defect_ppm=end_defect_ppm,
    )
    world.read_plant()
    return world


# --------------------------------------------------------------------------- #
# Tier 5: board specimens and quality
# --------------------------------------------------------------------------- #


def record_specimen(
    api: ApiClient,
    run_id: str,
    payload: JsonDict,
    headers: Optional[dict[str, str]] = None,
) -> JsonDict:
    return get_success_data(
        api.create_board_test(run_id, payload, headers or users.QUALITY_INSPECTOR)
    )


def record_passing_specimens(
    api: ApiClient,
    run_id: str,
    count: int = 3,
    headers: Optional[dict[str, str]] = None,
) -> list[JsonDict]:
    """Record the first ``count`` of the three canonical passing specimens."""
    return [
        record_specimen(api, run_id, payload, headers)
        for payload in f.PASSING_SPECIMENS[:count]
    ]


def evaluate(api: ApiClient, run_id: str) -> JsonDict:
    return get_success_data(api.evaluate_quality(run_id, {}, users.QUALITY_INSPECTOR))


def disposition(
    api: ApiClient,
    run_id: str,
    headers: Optional[dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.disposition_quality(
            run_id, f.disposition_payload(**overrides), headers or users.QUALITY_MANAGER
        )
    )


def released_run(api: ApiClient, world: Optional[World] = None, **kwargs: Any) -> World:
    """A completed run with three passing specimens evaluated into ``RELEASED``."""
    world = completed_run(api, world, **kwargs)
    record_passing_specimens(api, world.run_id, 3)
    world.run = evaluate(api, world.run_id)
    world.read_plant()
    return world


def downgraded_run(api: ApiClient, world: Optional[World] = None, **kwargs: Any) -> World:
    """A completed run whose fourth specimen fails nail pull: fail_rate 0.2500."""
    world = completed_run(api, world, **kwargs)
    record_passing_specimens(api, world.run_id, 3)
    record_specimen(api, world.run_id, f.NAIL_PULL_FAILING_SPECIMEN)
    world.run = evaluate(api, world.run_id)
    world.read_plant()
    return world


def held_run(api: ApiClient, world: Optional[World] = None, **kwargs: Any) -> World:
    """A completed run held by a fail rate of 0.3333 across three specimens."""
    world = completed_run(api, world, **kwargs)
    record_passing_specimens(api, world.run_id, 2)
    record_specimen(api, world.run_id, f.board_test_payload(3, 16.0, 70.0, 38.0, 105.0, 0.58))
    world.run = evaluate(api, world.run_id)
    world.read_plant()
    return world


# --------------------------------------------------------------------------- #
# Tier 5: load orders
# --------------------------------------------------------------------------- #


def stage_load(
    api: ApiClient,
    world: World,
    bundles_count: int = 12,
    boards_per_bundle: int = 48,
    run_id: Optional[str] = None,
    market_id: Optional[str] = None,
) -> JsonDict:
    return get_success_data(
        api.create_load_order(
            f.load_order_payload(
                run_id or world.run_id,
                market_id or world.market_id,
                bundles_count=bundles_count,
                boards_per_bundle=boards_per_bundle,
            ),
            users.PRODUCTION_SCHEDULER,
        )
    )


def record_load(api: ApiClient, load_order_id: str, loaded_bundles_count: int) -> JsonDict:
    return get_success_data(
        api.load_load_order(
            load_order_id,
            f.record_load_payload(loaded_bundles_count),
            users.PRODUCTION_SCHEDULER,
        )
    )


def ship_load(
    api: ApiClient, load_order_id: str, backhaul: Optional[bool] = None
) -> JsonDict:
    return get_success_data(
        api.ship_load_order(load_order_id, f.ship_payload(backhaul), users.PLANT_MANAGER)
    )


def cancel_load(api: ApiClient, load_order_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.cancel_load_order(
            load_order_id, f.cancel_load_payload(**overrides), users.PRODUCTION_SCHEDULER
        )
    )


def released_run_with_load(
    api: ApiClient,
    world: Optional[World] = None,
    bundles_count: int = 12,
    boards_per_bundle: int = 48,
    **kwargs: Any,
) -> World:
    """A released run with one staged load of 12 bundles of 48 boards."""
    world = released_run(api, world, **kwargs)
    world.load = stage_load(
        api, world, bundles_count=bundles_count, boards_per_bundle=boards_per_bundle
    )
    world.read_run()
    return world


# --------------------------------------------------------------------------- #
# Tier 5: maintenance outages
# --------------------------------------------------------------------------- #


def propose_outage(
    api: ApiClient,
    line_id: str,
    headers: Optional[dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.create_outage(
            f.outage_payload(line_id, **overrides), headers or users.MAINTENANCE_PLANNER
        )
    )


def approve_outage(
    api: ApiClient, outage_id: str, headers: Optional[dict[str, str]] = None
) -> JsonDict:
    return get_success_data(api.approve_outage(outage_id, {}, headers or users.PLANT_MANAGER))


def defer_outage(api: ApiClient, outage_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.defer_outage(outage_id, f.defer_payload(**overrides), users.MAINTENANCE_PLANNER)
    )


def repropose_outage(
    api: ApiClient, outage_id: str, window_start: str, window_end: str
) -> JsonDict:
    return get_success_data(
        api.repropose_outage(
            outage_id, f.repropose_payload(window_start, window_end), users.MAINTENANCE_PLANNER
        )
    )


def start_outage(api: ApiClient, outage_id: str) -> JsonDict:
    return get_success_data(api.start_outage(outage_id, {}, users.MAINTENANCE_PLANNER))


def close_outage(api: ApiClient, outage_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.close_outage(outage_id, f.close_outage_payload(**overrides), users.MAINTENANCE_PLANNER)
    )


def approved_outage(
    api: ApiClient,
    world: World,
    window_start: str = "2026-10-05T06:00:00Z",
    window_end: str = "2026-10-07T06:00:00Z",
    **overrides: Any,
) -> JsonDict:
    """An outage proposed by the planner and approved by the manager.

    The two identities differ because PRD 3.9 bars an approver from approving
    the outage they proposed.
    """
    outage = propose_outage(
        api, world.line_id, window_start=window_start, window_end=window_end, **overrides
    )
    world.outage = approve_outage(api, outage["id"])
    return world.outage


# --------------------------------------------------------------------------- #
# Listing helpers
# --------------------------------------------------------------------------- #


def list_data(response: Any) -> list[JsonDict]:
    """The ``data`` array of a listing, ignoring pagination metadata."""
    return get_success_data(response)  # type: ignore[return-value]
