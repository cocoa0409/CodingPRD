"""
Composite state builders.

The server is restarted with an empty database before every individual test, so
every builder here drives the public endpoints from scratch. The shop the
canonical builders assemble is one long chain — program, material, design,
characteristic plan, prototype release, tooling, coiler, setup, certified heat,
run, first article, in-process capability, completion, stress relief, quote,
approval package, customer verdict, allocation, packing, shipment — and
`build_world` walks that chain to whichever stage a test needs, handing each
stage its own payload overrides.

Two orderings inside the chain are load-bearing and easy to get backwards. The
quote must be priced *before* the customer's full approval, because approval
freezes the quote and no further quote may be run. And a safety-critical
in-process subgroup must be recorded before allocation, because a run that has
never taken one carries a null `min_ppk_observed` and fails the Ppk floor.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories
from .api_client import ApiClient
from .test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PLANT_ADMIN_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_ALT_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    make_customer_representative_headers,
)
from .types import Headers, Json


@dataclass
class World:
    """The rows a scenario built, in dependency order."""

    program: Optional[Json] = None
    material: Optional[Json] = None
    design: Optional[Json] = None
    characteristics: List[Json] = field(default_factory=list)
    tooling: Optional[Json] = None
    machine: Optional[Json] = None
    setup: Optional[Json] = None
    wire_lot: Optional[Json] = None
    run: Optional[Json] = None
    fai_records: List[Json] = field(default_factory=list)
    spc_records: List[Json] = field(default_factory=list)
    oven: Optional[Json] = None
    batch: Optional[Json] = None
    submission: Optional[Json] = None
    lot: Optional[Json] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # ── Identifiers ──────────────────────────────────────────────────────────
    @property
    def program_id(self) -> str:
        return self.program["id"]

    @property
    def material_id(self) -> str:
        return self.material["id"]

    @property
    def design_id(self) -> str:
        return self.design["id"]

    @property
    def characteristic_id(self) -> str:
        return self.characteristics[0]["id"]

    @property
    def tooling_id(self) -> str:
        return self.tooling["id"]

    @property
    def machine_id(self) -> str:
        return self.machine["id"]

    @property
    def setup_id(self) -> str:
        return self.setup["id"]

    @property
    def wire_lot_id(self) -> str:
        return self.wire_lot["id"]

    @property
    def run_id(self) -> str:
        return self.run["id"]

    @property
    def oven_id(self) -> str:
        return self.oven["id"]

    @property
    def batch_id(self) -> str:
        return self.batch["id"]

    @property
    def submission_id(self) -> str:
        return self.submission["id"]

    @property
    def lot_id(self) -> str:
        return self.lot["id"]

    # ── Versions, for the three optimistic-concurrency guards ────────────────
    @property
    def program_version(self) -> int:
        return self.program["version"]

    @property
    def design_version(self) -> int:
        return self.design["version"]

    @property
    def machine_version(self) -> int:
        return self.machine["version"]

    # ── The entity-backed customer identity ──────────────────────────────────
    @property
    def customer(self) -> Headers:
        """Headers for the CustomerRepresentative of this world's program."""
        return make_customer_representative_headers(self.program["id"])


# ── The logical shop clock (PRD 2.5) ─────────────────────────────────────────
def pin_clock(
    api: ApiClient, to_iso8601: str, headers: Headers = PLANT_ADMIN_HEADERS
) -> Json:
    """Move the logical clock forward to a known instant."""
    return get_success_data(api.set_clock(factories.clock_payload(to_iso8601), headers))


# ── Subgroups derived from a characteristic's own limits ──────────────────────
def in_control_subgroup(characteristic: Json) -> List[float]:
    """Three readings around the nominal whose Cpk clears any floor at 1.333.

    The spread is a tenth of the binding specification distance, so the
    Bessel-corrected sigma is that same tenth and the index lands at 3.333
    whatever the print limits happen to be.
    """
    nominal = characteristic["nominal_value"]
    binding = min(characteristic["usl"] - nominal, nominal - characteristic["lsl"])
    delta = binding / 10
    return [nominal - delta, nominal, nominal + delta]


def out_of_control_subgroup(characteristic: Json) -> List[float]:
    """Three readings, one of them beyond the upper specification limit."""
    nominal = characteristic["nominal_value"]
    usl = characteristic["usl"]
    return [nominal, nominal, usl + (usl - nominal)]


# ── Single-step builders ─────────────────────────────────────────────────────
def open_program(
    api: ApiClient, headers: Headers = PROGRAM_MANAGER_HEADERS, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_program(factories.program_payload(**overrides), headers)
    )


def register_material(
    api: ApiClient, headers: Headers = DESIGN_ENGINEER_HEADERS, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_material_spec(factories.material_spec_payload(**overrides), headers)
    )


def register_biocompatible_material(
    api: ApiClient, headers: Headers = DESIGN_ENGINEER_HEADERS, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_material_spec(
            factories.biocompatible_material_payload(**overrides), headers
        )
    )


def draft_design(
    api: ApiClient,
    program_id: str,
    material_spec_id: str,
    headers: Headers = DESIGN_ENGINEER_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_design(
            factories.design_payload(program_id, material_spec_id, **overrides), headers
        )
    )


def add_characteristic(
    api: ApiClient,
    design_id: str,
    headers: Headers = DESIGN_ENGINEER_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.add_characteristic(
            design_id, factories.characteristic_payload(**overrides), headers
        )
    )


def release_prototype(
    api: ApiClient,
    design_id: str,
    author: Headers = DESIGN_ENGINEER_HEADERS,
    reviewer: Headers = ENGINEERING_MANAGER_HEADERS,
) -> Json:
    """Submit the design for review and take the APPROVE_PROTOTYPE branch.

    The reviewer is a different identity from the author, because the verdict
    refuses a reviewer whose identifier matches the design's author.
    """
    get_success_data(api.submit_design_for_review(design_id, author))
    return get_success_data(
        api.review_design(
            design_id, {"decision": C.DECISION_APPROVE_PROTOTYPE}, reviewer
        )
    )


def reject_design(
    api: ApiClient,
    design_id: str,
    author: Headers = DESIGN_ENGINEER_HEADERS,
    reviewer: Headers = ENGINEERING_MANAGER_HEADERS,
) -> Json:
    """Submit the design for review and take the REJECT branch."""
    get_success_data(api.submit_design_for_review(design_id, author))
    return get_success_data(
        api.review_design(design_id, {"decision": C.DECISION_REJECT}, reviewer)
    )


def capitalise_tooling(
    api: ApiClient,
    design_id: str,
    headers: Headers = ENGINEERING_MANAGER_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_tooling_asset(factories.tooling_payload(design_id, **overrides), headers)
    )


def commission_machine(
    api: ApiClient, headers: Headers = PLANT_ADMIN_HEADERS, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_machine(factories.machine_payload(**overrides), headers)
    )


def commission_oven(
    api: ApiClient, headers: Headers = PLANT_ADMIN_HEADERS, **overrides: Any
) -> Json:
    return get_success_data(api.create_oven(factories.oven_payload(**overrides), headers))


def book_setup(
    api: ApiClient,
    machine: Json,
    design_id: str,
    tooling_asset_id: str,
    headers: Headers = PROCESS_TECHNICIAN_HEADERS,
    **overrides: Any,
) -> Json:
    """Book a setup window, guarded by the coiler's observed version."""
    return get_success_data(
        api.create_setup(
            factories.setup_payload(
                machine["id"], design_id, tooling_asset_id, machine["version"], **overrides
            ),
            headers,
        )
    )


def activate_setup(
    api: ApiClient, setup_id: str, headers: Headers = PROCESS_TECHNICIAN_HEADERS
) -> Json:
    return get_success_data(api.activate_setup(setup_id, headers))


def receive_wire(
    api: ApiClient,
    material_spec_id: str,
    headers: Headers = QUALITY_INSPECTOR_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_wire_lot(factories.wire_lot_payload(material_spec_id, **overrides), headers)
    )


def certify_wire(
    api: ApiClient,
    wire_lot_id: str,
    headers: Headers = QUALITY_INSPECTOR_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.certify_wire_lot(wire_lot_id, factories.certify_payload(**overrides), headers)
    )


def certified_wire(
    api: ApiClient,
    material_spec_id: str,
    headers: Headers = QUALITY_INSPECTOR_HEADERS,
    **overrides: Any,
) -> Json:
    """Receive a heat and clear its incoming tensile test in one step."""
    lot = receive_wire(api, material_spec_id, headers, **overrides)
    return certify_wire(api, lot["id"], headers)


def open_run(
    api: ApiClient,
    setup_id: str,
    wire_lot_id: str,
    design_id: str,
    headers: Headers = PROCESS_TECHNICIAN_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_run(
            factories.run_payload(setup_id, wire_lot_id, design_id, **overrides), headers
        )
    )


def record_fai_subgroup(
    api: ApiClient,
    run_id: str,
    characteristic: Json,
    measurements: Optional[Sequence[float]] = None,
    headers: Headers = QUALITY_INSPECTOR_HEADERS,
) -> Json:
    """One first-article subgroup, in control unless readings are supplied."""
    values = list(measurements) if measurements is not None else in_control_subgroup(
        characteristic
    )
    return get_success_data(
        api.record_fai(
            run_id, factories.measurement_payload(characteristic["id"], values), headers
        )
    )


def record_spc_subgroup(
    api: ApiClient,
    run_id: str,
    characteristic: Json,
    measurements: Optional[Sequence[float]] = None,
    headers: Headers = QUALITY_INSPECTOR_HEADERS,
) -> Json:
    """One in-process subgroup, in control unless readings are supplied."""
    values = list(measurements) if measurements is not None else in_control_subgroup(
        characteristic
    )
    return get_success_data(
        api.record_inspection(
            run_id, factories.measurement_payload(characteristic["id"], values), headers
        )
    )


def accept_first_article(
    api: ApiClient, run_id: str, headers: Headers = QUALITY_INSPECTOR_ALT_HEADERS
) -> Json:
    """The first-article verdict, delivered by an inspector who did not measure."""
    return get_success_data(
        api.dispose_fai(run_id, {"decision": C.DECISION_ACCEPT}, headers)
    )


def reject_first_article(
    api: ApiClient, run_id: str, headers: Headers = QUALITY_INSPECTOR_ALT_HEADERS
) -> Json:
    return get_success_data(
        api.dispose_fai(run_id, {"decision": C.DECISION_REJECT}, headers)
    )


def complete_run(
    api: ApiClient,
    run_id: str,
    produced_pieces: int = 25_500,
    scrapped_pieces: int = 500,
    headers: Headers = PROCESS_TECHNICIAN_HEADERS,
) -> Json:
    return get_success_data(
        api.complete_run(
            run_id, factories.completion_payload(produced_pieces, scrapped_pieces), headers
        )
    )


def schedule_batch(
    api: ApiClient,
    oven_id: str,
    run_id: str,
    headers: Headers = PROCESS_TECHNICIAN_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_batch(factories.batch_payload(oven_id, run_id, **overrides), headers)
    )


def start_batch(
    api: ApiClient, batch_id: str, headers: Headers = PROCESS_TECHNICIAN_HEADERS
) -> Json:
    return get_success_data(api.start_batch(batch_id, headers))


def discharge_batch(
    api: ApiClient,
    batch_id: str,
    peening_performed: bool = True,
    headers: Headers = PROCESS_TECHNICIAN_HEADERS,
) -> Json:
    return get_success_data(
        api.complete_batch(batch_id, {"peening_performed": peening_performed}, headers)
    )


def price_program(
    api: ApiClient,
    program: Json,
    design_id: str,
    headers: Headers = PROGRAM_MANAGER_HEADERS,
    **overrides: Any,
) -> Json:
    """Price the program against one design, guarded by its observed version."""
    return get_success_data(
        api.quote_program(
            program["id"],
            factories.quote_payload(design_id, program["version"], **overrides),
            headers,
        )
    )


def file_submission(
    api: ApiClient,
    program_id: str,
    design_id: str,
    headers: Headers = PROGRAM_MANAGER_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_submission(
            factories.submission_payload(program_id, design_id, **overrides), headers
        )
    )


def customer_verdict(
    api: ApiClient,
    submission_id: str,
    program_id: str,
    decision: str = C.DECISION_APPROVE,
    **payload_extras: Any,
) -> Json:
    """A customer verdict, delivered as the program the submission belongs to."""
    payload: Json = {"decision": decision}
    payload.update(payload_extras)
    return get_success_data(
        api.review_submission(
            submission_id, payload, make_customer_representative_headers(program_id)
        )
    )


def allocate_lot(
    api: ApiClient,
    run_id: str,
    program_id: str,
    piece_count: int = 1_000,
    headers: Headers = PROGRAM_MANAGER_HEADERS,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_lot(
            factories.lot_payload(run_id, program_id, piece_count, **overrides), headers
        )
    )


def pack_lot(
    api: ApiClient,
    lot_id: str,
    packaging_method: str = C.PACK_TANGLE_FREE_TRAY,
    headers: Headers = PROCESS_TECHNICIAN_HEADERS,
) -> Json:
    return get_success_data(
        api.pack_lot(lot_id, {"packaging_method": packaging_method}, headers)
    )


def ship_lot(
    api: ApiClient, lot_id: str, headers: Headers = PROGRAM_MANAGER_HEADERS
) -> Json:
    return get_success_data(api.ship_lot(lot_id, headers))


# ── Refresh helpers ──────────────────────────────────────────────────────────
def refresh_program(api: ApiClient, program_id: str) -> Json:
    return get_success_data(api.get_program(program_id, PROGRAM_MANAGER_HEADERS))


def refresh_design(api: ApiClient, design_id: str) -> Json:
    return get_success_data(api.get_design(design_id, DESIGN_ENGINEER_HEADERS))


def refresh_tooling(api: ApiClient, tooling_id: str) -> Json:
    return get_success_data(
        api.get_tooling_asset(tooling_id, ENGINEERING_MANAGER_HEADERS)
    )


def refresh_machine(api: ApiClient, machine_id: str) -> Json:
    return get_success_data(api.get_machine(machine_id, PLANT_ADMIN_HEADERS))


def refresh_setup(api: ApiClient, setup_id: str) -> Json:
    return get_success_data(api.get_setup(setup_id, PROCESS_TECHNICIAN_HEADERS))


def refresh_wire_lot(api: ApiClient, wire_lot_id: str) -> Json:
    return get_success_data(api.get_wire_lot(wire_lot_id, QUALITY_INSPECTOR_HEADERS))


def refresh_run(api: ApiClient, run_id: str) -> Json:
    return get_success_data(api.get_run(run_id, PROCESS_TECHNICIAN_HEADERS))


def refresh_oven(api: ApiClient, oven_id: str) -> Json:
    return get_success_data(api.get_oven(oven_id, PLANT_ADMIN_HEADERS))


def refresh_batch(api: ApiClient, batch_id: str) -> Json:
    return get_success_data(api.get_batch(batch_id, PROCESS_TECHNICIAN_HEADERS))


def refresh_submission(api: ApiClient, submission_id: str) -> Json:
    return get_success_data(
        api.get_submission(submission_id, PROGRAM_MANAGER_HEADERS)
    )


def refresh_lot(api: ApiClient, lot_id: str) -> Json:
    return get_success_data(api.get_lot(lot_id, PROGRAM_MANAGER_HEADERS))


def refresh_world(api: ApiClient, world: World) -> World:
    """Re-read every row the world holds, so a test sees post-cascade state."""
    if world.program is not None:
        world.program = refresh_program(api, world.program["id"])
    if world.design is not None:
        world.design = refresh_design(api, world.design["id"])
    if world.tooling is not None:
        world.tooling = refresh_tooling(api, world.tooling["id"])
    if world.machine is not None:
        world.machine = refresh_machine(api, world.machine["id"])
    if world.setup is not None:
        world.setup = refresh_setup(api, world.setup["id"])
    if world.wire_lot is not None:
        world.wire_lot = refresh_wire_lot(api, world.wire_lot["id"])
    if world.run is not None:
        world.run = refresh_run(api, world.run["id"])
    if world.oven is not None:
        world.oven = refresh_oven(api, world.oven["id"])
    if world.batch is not None:
        world.batch = refresh_batch(api, world.batch["id"])
    if world.submission is not None:
        world.submission = refresh_submission(api, world.submission["id"])
    if world.lot is not None:
        world.lot = refresh_lot(api, world.lot["id"])
    return world


# ── The staged pipeline ──────────────────────────────────────────────────────
STAGES: List[str] = [
    "program",
    "material",
    "design",
    "characteristic",
    "prototype",
    "tooling",
    "machine",
    "setup",
    "active_setup",
    "wire_lot",
    "certified_wire",
    "run",
    "fai",
    "running",
    "spc",
    "complete",
    "heat_treated",
    "quoted",
    "submitted",
    "approved",
    "allocated",
    "packed",
    "shipped",
]


def _reached(stage: str, upto: str) -> bool:
    return STAGES.index(stage) <= STAGES.index(upto)


def build_world(
    api: ApiClient,
    upto: str,
    *,
    program: Optional[Dict[str, Any]] = None,
    material: Optional[Dict[str, Any]] = None,
    design: Optional[Dict[str, Any]] = None,
    characteristics: Optional[Sequence[Dict[str, Any]]] = None,
    tooling: Optional[Dict[str, Any]] = None,
    machine: Optional[Dict[str, Any]] = None,
    setup: Optional[Dict[str, Any]] = None,
    wire_lot: Optional[Dict[str, Any]] = None,
    run: Optional[Dict[str, Any]] = None,
    oven: Optional[Dict[str, Any]] = None,
    batch: Optional[Dict[str, Any]] = None,
    quote: Optional[Dict[str, Any]] = None,
    submission: Optional[Dict[str, Any]] = None,
    lot: Optional[Dict[str, Any]] = None,
    completion: Optional[Dict[str, Any]] = None,
    author: Headers = DESIGN_ENGINEER_HEADERS,
    reviewer: Headers = ENGINEERING_MANAGER_HEADERS,
    measurer: Headers = QUALITY_INSPECTOR_HEADERS,
    disposer: Headers = QUALITY_INSPECTOR_ALT_HEADERS,
    packaging_method: str = C.PACK_TANGLE_FREE_TRAY,
    peening_performed: Optional[bool] = None,
    verdict: str = C.DECISION_APPROVE,
    verdict_extras: Optional[Dict[str, Any]] = None,
    activation_clock: Optional[str] = None,
    batch_clock: Optional[str] = None,
) -> World:
    """Walk the canonical chain up to and including `upto`.

    Each keyword takes payload overrides for its own stage, so a scenario that
    needs a `MEDICAL_IMPLANT` program on a titanium grade with a hooked end
    states only those three differences. `characteristics` replaces the default
    single-characteristic plan with one payload override dict per characteristic,
    and every stage that measures loops over the whole plan so first-article
    coverage stays complete.
    """
    if upto not in STAGES:
        raise ValueError(f"unknown stage {upto!r}; expected one of {STAGES}")

    world = World()
    world.program = open_program(api, **(program or {}))

    if _reached("material", upto):
        world.material = register_material(api, DESIGN_ENGINEER_HEADERS, **(material or {}))

    if _reached("design", upto):
        world.design = draft_design(
            api,
            world.program["id"],
            world.material["id"],
            author,
            **(design or {}),
        )

    if _reached("characteristic", upto):
        plans = list(characteristics) if characteristics is not None else [{}]
        for plan in plans:
            world.characteristics.append(
                add_characteristic(api, world.design["id"], author, **plan)
            )

    if _reached("prototype", upto):
        world.design = release_prototype(api, world.design["id"], author, reviewer)

    if _reached("tooling", upto):
        world.tooling = capitalise_tooling(
            api, world.design["id"], ENGINEERING_MANAGER_HEADERS, **(tooling or {})
        )

    if _reached("machine", upto):
        world.machine = commission_machine(api, PLANT_ADMIN_HEADERS, **(machine or {}))

    if _reached("setup", upto):
        world.setup = book_setup(
            api,
            world.machine,
            world.design["id"],
            world.tooling["id"],
            PROCESS_TECHNICIAN_HEADERS,
            **(setup or {}),
        )
        world.machine = refresh_machine(api, world.machine["id"])

    if _reached("active_setup", upto):
        pin_clock(api, activation_clock or world.setup["window_start"])
        world.setup = activate_setup(api, world.setup["id"])
        world.machine = refresh_machine(api, world.machine["id"])

    if _reached("wire_lot", upto):
        world.wire_lot = receive_wire(
            api, world.material["id"], QUALITY_INSPECTOR_HEADERS, **(wire_lot or {})
        )

    if _reached("certified_wire", upto):
        world.wire_lot = certify_wire(api, world.wire_lot["id"])

    if _reached("run", upto):
        world.run = open_run(
            api,
            world.setup["id"],
            world.wire_lot["id"],
            world.design["id"],
            PROCESS_TECHNICIAN_HEADERS,
            **(run or {}),
        )
        world.machine = refresh_machine(api, world.machine["id"])
        world.wire_lot = refresh_wire_lot(api, world.wire_lot["id"])

    if _reached("fai", upto):
        for characteristic in world.characteristics:
            world.fai_records.append(
                record_fai_subgroup(
                    api, world.run["id"], characteristic, headers=measurer
                )
            )
        world.run = refresh_run(api, world.run["id"])

    if _reached("running", upto):
        world.run = accept_first_article(api, world.run["id"], disposer)

    if _reached("spc", upto):
        for characteristic in world.characteristics:
            world.spc_records.append(
                record_spc_subgroup(
                    api, world.run["id"], characteristic, headers=measurer
                )
            )
        world.run = refresh_run(api, world.run["id"])

    if _reached("complete", upto):
        counts = completion or {}
        world.run = complete_run(
            api,
            world.run["id"],
            counts.get("produced_pieces", 25_500),
            counts.get("scrapped_pieces", 500),
        )
        world.setup = refresh_setup(api, world.setup["id"])
        world.machine = refresh_machine(api, world.machine["id"])
        world.wire_lot = refresh_wire_lot(api, world.wire_lot["id"])

    if _reached("heat_treated", upto):
        world.oven = commission_oven(api, PLANT_ADMIN_HEADERS, **(oven or {}))
        batch_overrides: Dict[str, Any] = {
            "peening_requested": world.design["shot_peening_required"]
        }
        batch_overrides.update(batch or {})
        world.batch = schedule_batch(
            api,
            world.oven["id"],
            world.run["id"],
            PROCESS_TECHNICIAN_HEADERS,
            **batch_overrides,
        )
        pin_clock(api, batch_clock or world.batch["window_start"])
        world.batch = start_batch(api, world.batch["id"])
        peened = (
            peening_performed
            if peening_performed is not None
            else world.design["shot_peening_required"]
        )
        world.batch = discharge_batch(api, world.batch["id"], peened)
        world.oven = refresh_oven(api, world.oven["id"])
        world.run = refresh_run(api, world.run["id"])

    if _reached("quoted", upto):
        world.program = price_program(
            api,
            world.program,
            world.design["id"],
            PROGRAM_MANAGER_HEADERS,
            **(quote or {}),
        )

    if _reached("submitted", upto):
        world.submission = file_submission(
            api,
            world.program["id"],
            world.design["id"],
            PROGRAM_MANAGER_HEADERS,
            **(submission or {}),
        )
        world.program = refresh_program(api, world.program["id"])

    if _reached("approved", upto):
        world.submission = customer_verdict(
            api,
            world.submission["id"],
            world.program["id"],
            verdict,
            **(verdict_extras or {}),
        )
        world.program = refresh_program(api, world.program["id"])
        world.design = refresh_design(api, world.design["id"])
        world.tooling = refresh_tooling(api, world.tooling["id"])

    if _reached("allocated", upto):
        lot_overrides = dict(lot or {})
        piece_count = lot_overrides.pop("piece_count", 1_000)
        world.lot = allocate_lot(
            api,
            world.run["id"],
            world.program["id"],
            piece_count,
            PROGRAM_MANAGER_HEADERS,
            **lot_overrides,
        )
        world.program = refresh_program(api, world.program["id"])

    if _reached("packed", upto):
        world.lot = pack_lot(api, world.lot["id"], packaging_method)

    if _reached("shipped", upto):
        world.lot = ship_lot(api, world.lot["id"])
        world.program = refresh_program(api, world.program["id"])
        world.tooling = refresh_tooling(api, world.tooling["id"])

    return world


# ── Named shortcuts for the stages tests reach for most ───────────────────────
def program_world(api: ApiClient, **kwargs: Any) -> World:
    """A program and a registered wire grade, nothing engineered yet."""
    return build_world(api, "material", **kwargs)


def draft_design_world(api: ApiClient, **kwargs: Any) -> World:
    """A DRAFT design carrying one critical characteristic."""
    return build_world(api, "characteristic", **kwargs)


def prototype_world(api: ApiClient, **kwargs: Any) -> World:
    """A PROTOTYPE_RELEASED design with capitalised tooling."""
    return build_world(api, "tooling", **kwargs)


def scheduled_setup_world(api: ApiClient, **kwargs: Any) -> World:
    """A coiler carrying one SCHEDULED setup window."""
    return build_world(api, "setup", **kwargs)


def active_setup_world(api: ApiClient, **kwargs: Any) -> World:
    """The setup activated, so the coiler reads SETUP."""
    return build_world(api, "active_setup", **kwargs)


def certified_wire_world(api: ApiClient, **kwargs: Any) -> World:
    """An active setup plus a CERTIFIED heat of the design's own grade."""
    return build_world(api, "certified_wire", **kwargs)


def run_world(api: ApiClient, **kwargs: Any) -> World:
    """A FAI_PENDING run holding its wire reservation."""
    return build_world(api, "run", **kwargs)


def measured_run_world(api: ApiClient, **kwargs: Any) -> World:
    """A FAI_PENDING run with full first-article coverage on file."""
    return build_world(api, "fai", **kwargs)


def running_run_world(api: ApiClient, **kwargs: Any) -> World:
    """The first article accepted, so the run reads RUNNING."""
    return build_world(api, "running", **kwargs)


def spc_run_world(api: ApiClient, **kwargs: Any) -> World:
    """A RUNNING run carrying one in-process subgroup per characteristic."""
    return build_world(api, "spc", **kwargs)


def complete_run_world(api: ApiClient, **kwargs: Any) -> World:
    """A COMPLETE run with its wire ledger settled."""
    return build_world(api, "complete", **kwargs)


def heat_treated_world(api: ApiClient, **kwargs: Any) -> World:
    """The run stress relieved and peened, so heat treatment reads COMPLETE."""
    return build_world(api, "heat_treated", **kwargs)


def quoted_world(api: ApiClient, **kwargs: Any) -> World:
    """The program priced against the design."""
    return build_world(api, "quoted", **kwargs)


def submitted_world(api: ApiClient, **kwargs: Any) -> World:
    """A SUBMITTED approval package on a quoted program."""
    return build_world(api, "submitted", **kwargs)


def approved_world(api: ApiClient, **kwargs: Any) -> World:
    """The customer's full approval landed: PRODUCTION_RELEASED and AMORTIZING."""
    return build_world(api, "approved", **kwargs)


def interim_approved_world(api: ApiClient, interim_piece_cap: int = 5_000, **kwargs: Any) -> World:
    """The capped conditional release, which arms nothing."""
    kwargs.setdefault("verdict", C.DECISION_INTERIM_APPROVE)
    kwargs.setdefault("verdict_extras", {"interim_piece_cap": interim_piece_cap})
    return build_world(api, "approved", **kwargs)


def allocated_world(api: ApiClient, **kwargs: Any) -> World:
    """One ALLOCATED lot carrying its snapshotted commercial terms."""
    return build_world(api, "allocated", **kwargs)


def packed_world(api: ApiClient, **kwargs: Any) -> World:
    """The lot packed and waiting on the dock."""
    return build_world(api, "packed", **kwargs)


def shipped_world(api: ApiClient, **kwargs: Any) -> World:
    """The lot shipped, with the tooling recovery posted."""
    return build_world(api, "shipped", **kwargs)
