"""Composite scenario builders.

Every test starts against an empty database, so each one has to build its own
preconditions through the public API. The shared preamble — set the clock, stand
up the plant and the agency panel, open the project, freeze a design revision,
get plan review approved, create a module and walk it down the line — is
assembled once here so the tests can state only the step they are actually
about.

Each builder returns a :class:`World`, which carries the created rows and the
identity headers for the three entity-backed roles.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ModularApiClient
from .test_users import (
    DESIGN_ENGINEER_REVIEWER,
    DESIGN_ENGINEER_SUBMITTER,
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    STATE_PROGRAM_OFFICER,
    AUTHORITY_HAVING_JURISDICTION,
    TRANSPORT_COORDINATOR,
    WARRANTY_ADJUDICATOR,
    make_factory_manager_headers,
    make_inspector_headers,
    make_site_superintendent_headers,
)


@dataclass
class World:
    """The rows a scenario has created, plus the identities that own them."""

    api: ModularApiClient
    factory: Dict[str, Any] = field(default_factory=dict)
    project: Dict[str, Any] = field(default_factory=dict)
    agency: Dict[str, Any] = field(default_factory=dict)
    package: Dict[str, Any] = field(default_factory=dict)
    plan_review_permit: Dict[str, Any] = field(default_factory=dict)
    modules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    inspections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    shipment: Dict[str, Any] = field(default_factory=dict)

    # ─── Identity headers ─────────────────────────────────────────────────────
    @property
    def factory_manager(self) -> Dict[str, str]:
        return make_factory_manager_headers(self.factory["id"])

    @property
    def inspector(self) -> Dict[str, str]:
        return make_inspector_headers(self.agency["id"])

    @property
    def superintendent(self) -> Dict[str, str]:
        return make_site_superintendent_headers(self.project["id"])

    # ─── Convenience accessors ────────────────────────────────────────────────
    @property
    def factory_id(self) -> str:
        return self.factory["id"]

    @property
    def project_id(self) -> str:
        return self.project["id"]

    @property
    def package_id(self) -> str:
        return self.package["id"]

    @property
    def agency_id(self) -> str:
        return self.agency["id"]

    @property
    def shipment_id(self) -> str:
        return self.shipment["id"]

    def module(self, module_code: str = "M-01") -> Dict[str, Any]:
        return self.modules[module_code]

    def module_id(self, module_code: str = "M-01") -> str:
        return self.modules[module_code]["id"]

    # ─── Re-reads ─────────────────────────────────────────────────────────────
    def refresh_factory(self) -> Dict[str, Any]:
        self.factory = get_success_data(
            self.api.get_factory(self.factory["id"], PROGRAM_ADMIN)
        )
        return self.factory

    def refresh_project(self) -> Dict[str, Any]:
        self.project = get_success_data(
            self.api.get_project(self.project["id"], PROGRAM_ADMIN)
        )
        return self.project

    def refresh_package(self) -> Dict[str, Any]:
        self.package = get_success_data(
            self.api.get_design_package(self.package["id"], PROGRAM_ADMIN)
        )
        return self.package

    def refresh_module(self, module_code: str = "M-01") -> Dict[str, Any]:
        module = get_success_data(
            self.api.get_module(self.modules[module_code]["id"], PROGRAM_ADMIN)
        )
        self.modules[module_code] = module
        return module

    def refresh_shipment(self) -> Dict[str, Any]:
        self.shipment = get_success_data(
            self.api.get_shipment(self.shipment["id"], PROGRAM_ADMIN)
        )
        return self.shipment

    @property
    def project_version(self) -> int:
        return self.refresh_project()["version"]


# ─── Single-step builders ─────────────────────────────────────────────────────
def set_clock(api: ModularApiClient, current_utc: str = f.DEFAULT_CLOCK) -> None:
    """Move the logical clock to a given instant."""
    get_success_data(api.set_clock(f.clock_payload(current_utc), PROGRAM_ADMIN))


def create_factory(api: ModularApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_factory(f.factory_payload(**overrides), PROGRAM_ADMIN))


def create_agency(api: ModularApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_agency(f.agency_payload(**overrides), PROGRAM_ADMIN))


def create_project(api: ModularApiClient, factory_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_project(f.project_payload(factory_id, **overrides), PROGRAM_ADMIN)
    )


def create_design_package(
    api: ModularApiClient, project_id: str, expected_project_version: int, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_design_package(
            f.design_package_payload(project_id, expected_project_version, **overrides),
            DESIGN_ENGINEER_SUBMITTER,
        )
    )


def freeze_package(api: ModularApiClient, package_id: str) -> Dict[str, Any]:
    """Submit a revision and have a peer engineer freeze it."""
    get_success_data(
        api.submit_design_package(package_id, f.submit_payload(), DESIGN_ENGINEER_SUBMITTER)
    )
    return get_success_data(
        api.decide_design_review(
            package_id, f.review_decision_payload("FREEZE"), DESIGN_ENGINEER_REVIEWER
        )
    )


def approve_permit(
    api: ModularApiClient,
    project_id: str,
    track: str = "STATE_MODULAR_PROGRAM",
    scope: str = "PLAN_REVIEW",
    expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    """File an application on one track and have the matching officer approve it."""
    permit = get_success_data(
        api.create_permit(f.permit_payload(project_id, track, scope), PROGRAM_ADMIN)
    )
    officer = (
        STATE_PROGRAM_OFFICER
        if track == "STATE_MODULAR_PROGRAM"
        else AUTHORITY_HAVING_JURISDICTION
    )
    decision = f.permit_decision_payload("APPROVE")
    if expires_at is not None:
        decision["expires_at"] = expires_at
    return get_success_data(api.decide_permit(permit["id"], decision, officer))


def create_module(
    api: ModularApiClient,
    project_id: str,
    design_package_id: str,
    factory_id: str,
    module_code: str = "M-01",
    set_sequence_index: int = 1,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_module(
            f.module_payload(
                project_id, design_package_id, module_code, set_sequence_index, **overrides
            ),
            make_factory_manager_headers(factory_id),
        )
    )


def open_inspection(
    api: ModularApiClient, module_id: str, agency_id: str, stage: str = "IN_PLANT"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspection(
            f.inspection_payload(module_id, agency_id, stage),
            make_inspector_headers(agency_id),
        )
    )


def record_result(
    api: ModularApiClient,
    inspection_id: str,
    agency_id: str,
    result: str,
    defect_count: int = 0,
    severity_max: int = 0,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_inspection_result(
            inspection_id,
            f.inspection_result_payload(result, defect_count, severity_max),
            make_inspector_headers(agency_id),
        )
    )


def create_shipment(
    api: ModularApiClient, project_id: str, route_state_codes=None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipment(
            f.shipment_payload(project_id, route_state_codes, **overrides),
            TRANSPORT_COORDINATOR,
        )
    )


def load_module(
    api: ModularApiClient, shipment_id: str, module_id: str, shipment_version: int
) -> Dict[str, Any]:
    return get_success_data(
        api.load_module(
            shipment_id,
            f.load_module_payload(module_id, shipment_version),
            TRANSPORT_COORDINATOR,
        )
    )


def create_draw(
    api: ModularApiClient,
    project_id: str,
    certifying_agency_id: str,
    basis_mode: str = "WIP_DEPOSIT",
    draw_index: int = 1,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_draw_request(
            f.draw_request_payload(
                project_id, certifying_agency_id, basis_mode, draw_index
            ),
            LENDER_DRAW_ADMINISTRATOR,
        )
    )


# ─── Tier 1: the plant, the agency panel and the project ──────────────────────
def world_plant_and_project(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    factory_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    agency_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Clock set, plant registered, agency accredited, project opened."""
    set_clock(api, clock)
    world = World(api=api)
    world.factory = create_factory(api, **(factory_overrides or {}))
    world.agency = create_agency(api, **(agency_overrides or {}))
    world.project = create_project(api, world.factory["id"], **(project_overrides or {}))
    return world


# ─── Tier 2: a frozen design revision ─────────────────────────────────────────
def world_frozen_design(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    factory_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    package_overrides: Optional[Dict[str, Any]] = None,
    agency_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Tier 1 plus revision R1 submitted by one engineer and frozen by a peer."""
    world = world_plant_and_project(
        api, clock, factory_overrides, project_overrides, agency_overrides
    )
    world.package = create_design_package(
        api,
        world.project_id,
        world.project["version"],
        **(package_overrides or {}),
    )
    world.package = freeze_package(api, world.package["id"])
    world.refresh_project()
    return world


# ─── Tier 3: plan review approved, so the line is released ────────────────────
def world_plan_review_approved(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    factory_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    package_overrides: Optional[Dict[str, Any]] = None,
    plan_review_expires_at: Optional[str] = None,
    agency_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Tier 2 plus a live state plan-review approval pinning the frozen revision."""
    world = world_frozen_design(
        api,
        clock,
        factory_overrides,
        project_overrides,
        package_overrides,
        agency_overrides,
    )
    world.plan_review_permit = approve_permit(
        api,
        world.project_id,
        "STATE_MODULAR_PROGRAM",
        "PLAN_REVIEW",
        plan_review_expires_at,
    )
    world.refresh_project()
    return world


# ─── Tier 4: a module on the books ────────────────────────────────────────────
def world_with_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    module_code: str = "M-01",
    set_sequence_index: int = 1,
    module_overrides: Optional[Dict[str, Any]] = None,
    **tier_kwargs,
) -> World:
    """Tier 3 plus one PLANNED module detailed against the pinned revision."""
    world = world_plan_review_approved(api, clock, **tier_kwargs)
    world.modules[module_code] = create_module(
        api,
        world.project_id,
        world.package_id,
        world.factory_id,
        module_code,
        set_sequence_index,
        **(module_overrides or {}),
    )
    return world


def add_module(
    world: World,
    module_code: str,
    set_sequence_index: int,
    **module_overrides,
) -> Dict[str, Any]:
    """Add one more module of the same project and revision."""
    module = create_module(
        world.api,
        world.project_id,
        world.package_id,
        world.factory_id,
        module_code,
        set_sequence_index,
        **module_overrides,
    )
    world.modules[module_code] = module
    return module


# ─── Line walking helpers ─────────────────────────────────────────────────────
DEFAULT_LINE_SLOT_START = "2026-09-02T14:00:00Z"
DEFAULT_PICK_WINDOW_START = "2026-09-05T10:00:00Z"
DEFAULT_PICK_WINDOW_END = "2026-09-05T11:00:00Z"
DEFAULT_PICK_RADIUS_FT = 75
DEFAULT_RIGGING_WEIGHT_LB = 4000


def schedule_slot(
    world: World,
    module_code: str = "M-01",
    line_slot_start: str = DEFAULT_LINE_SLOT_START,
) -> Dict[str, Any]:
    """Claim a takt window for one module."""
    module = get_success_data(
        world.api.schedule_line_slot(
            world.module_id(module_code),
            f.line_slot_payload(line_slot_start),
            world.factory_manager,
        )
    )
    world.modules[module_code] = module
    return module


def advance_stations(
    world: World, module_code: str = "M-01", stations_advanced: int = 1
) -> Dict[str, Any]:
    """Advance one module along the line."""
    module = get_success_data(
        world.api.advance_station(
            world.module_id(module_code),
            f.advance_payload(stations_advanced),
            world.factory_manager,
        )
    )
    world.modules[module_code] = module
    return module


def release_quality(world: World, module_code: str = "M-01") -> Dict[str, Any]:
    """Walk both inspection stages to a PASS so the module is QC released."""
    in_plant = open_inspection(
        world.api, world.module_id(module_code), world.agency_id, "IN_PLANT"
    )
    world.inspections[f"{module_code}:IN_PLANT"] = record_result(
        world.api, in_plant["id"], world.agency_id, "PASS"
    )
    final = open_inspection(
        world.api, world.module_id(module_code), world.agency_id, "FINAL_FACTORY"
    )
    world.inspections[f"{module_code}:FINAL_FACTORY"] = record_result(
        world.api, final["id"], world.agency_id, "PASS"
    )
    return world.refresh_module(module_code)


def plan_pick(
    world: World,
    module_code: str = "M-01",
    pick_window_start: str = DEFAULT_PICK_WINDOW_START,
    pick_window_end: str = DEFAULT_PICK_WINDOW_END,
    pick_radius_ft: int = DEFAULT_PICK_RADIUS_FT,
    rigging_weight_lb: int = DEFAULT_RIGGING_WEIGHT_LB,
) -> Dict[str, Any]:
    """Plan the crane lift for one module."""
    module = get_success_data(
        world.api.schedule_pick(
            world.module_id(module_code),
            f.pick_payload(
                pick_window_start, pick_window_end, pick_radius_ft, rigging_weight_lb
            ),
            world.superintendent,
        )
    )
    world.modules[module_code] = module
    return module


# ─── Tier 5: a module holding a takt window ───────────────────────────────────
def world_slotted_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    line_slot_start: str = DEFAULT_LINE_SLOT_START,
    module_code: str = "M-01",
    **tier_kwargs,
) -> World:
    """Tier 4 plus that module SLOTTED on the line."""
    world = world_with_module(api, clock, module_code, **tier_kwargs)
    schedule_slot(world, module_code, line_slot_start)
    return world


# ─── Tier 6: a module off the end of the line ─────────────────────────────────
def world_line_complete_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    line_slot_start: str = DEFAULT_LINE_SLOT_START,
    module_code: str = "M-01",
    **tier_kwargs,
) -> World:
    """Tier 5 plus every station advanced, so production is LINE_COMPLETE."""
    world = world_slotted_module(api, clock, line_slot_start, module_code, **tier_kwargs)
    advance_stations(world, module_code, world.factory["station_count"])
    return world


# ─── Tier 7: a QC released module ─────────────────────────────────────────────
def world_qc_released_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    line_slot_start: str = DEFAULT_LINE_SLOT_START,
    module_code: str = "M-01",
    **tier_kwargs,
) -> World:
    """Tier 6 plus both inspection stages passed, so qc_status is RELEASED."""
    world = world_line_complete_module(
        api, clock, line_slot_start, module_code, **tier_kwargs
    )
    release_quality(world, module_code)
    return world


# ─── Tier 8: a module aboard a load ───────────────────────────────────────────
def world_loaded_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    route_state_codes: Optional[List[str]] = None,
    module_code: str = "M-01",
    **tier_kwargs,
) -> World:
    """Tier 7 plus an open load carrying that module."""
    world = world_qc_released_module(api, clock, module_code=module_code, **tier_kwargs)
    world.shipment = create_shipment(api, world.project_id, route_state_codes)
    world.shipment = load_module(
        api, world.shipment["id"], world.module_id(module_code), world.shipment["version"]
    )
    world.refresh_module(module_code)
    return world


# ─── Tier 9: a module delivered to site ───────────────────────────────────────
def world_delivered_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    route_state_codes: Optional[List[str]] = None,
    module_code: str = "M-01",
    escort_confirmed: bool = False,
    **tier_kwargs,
) -> World:
    """Tier 8 plus route survey, dispatch and delivery."""
    world = world_loaded_module(
        api, clock, route_state_codes, module_code, **tier_kwargs
    )
    survey = f.route_survey_payload()
    if escort_confirmed:
        survey["escort_confirmed"] = True
    get_success_data(
        api.record_route_survey(world.shipment_id, survey, TRANSPORT_COORDINATOR)
    )
    get_success_data(api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR))
    world.shipment = get_success_data(
        api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )
    world.refresh_module(module_code)
    return world


def clear_the_site_for_setting(world: World) -> World:
    """Approve state insignia and the local set permit, reaching SET_CLEARED."""
    approve_permit(world.api, world.project_id, "STATE_MODULAR_PROGRAM", "INSIGNIA")
    approve_permit(world.api, world.project_id, "LOCAL_AHJ", "SET")
    world.refresh_project()
    return world


# ─── Tier 10: a module landed on the foundation ───────────────────────────────
def world_set_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    module_code: str = "M-01",
    **tier_kwargs,
) -> World:
    """Tier 9 plus insignia and set permits, a planned lift and an executed set."""
    world = world_delivered_module(api, clock, module_code=module_code, **tier_kwargs)
    clear_the_site_for_setting(world)
    plan_pick(world, module_code)
    world.modules[module_code] = get_success_data(
        api.execute_set(world.module_id(module_code), {}, world.superintendent)
    )
    world.refresh_project()
    return world


# ─── Tier 11: a module closed in ──────────────────────────────────────────────
def world_connected_module(
    api: ModularApiClient,
    clock: str = f.DEFAULT_CLOCK,
    module_code: str = "M-01",
    **tier_kwargs,
) -> World:
    """Tier 10 plus signed-off field scope and closed connections."""
    world = world_set_module(api, clock, module_code, **tier_kwargs)
    world.modules[module_code] = get_success_data(
        api.close_connections(
            world.module_id(module_code),
            f.close_connections_payload(True),
            world.superintendent,
        )
    )
    world.refresh_project()
    return world
