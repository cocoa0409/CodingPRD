"""Scenario builders.

Every test starts against an empty database, so all state is built here through
the public API in the order the domain requires: reference data first (airframe,
compartments, runway, performance bands, weight programme), then a flight, then
a load plan and its distribution, then the load sheet and whatever follows it.

The builders come in two tiers.  The single-step functions (``create_aircraft``,
``seat``, ``stow_bags`` …) each perform one call and hand back the created row.
The composite functions (``fx_a``, ``workhorse_world``, ``s2_restricted_world``
…) assemble the recurring distributions whose figures several tests share, so
that a test body can open on the situation it is actually about.

``Scenario`` carries the rows that have been built so far and offers ``id``
shortcuts, so a test reads ``world.compartment_id("H4")`` rather than threading
dictionaries by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import SETUP_CLOCK_UTC
from .test_users import ADMIN, CAPTAIN, DG_OFFICER, LOAD_CONTROLLER, RAMP_AGENT

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Scenario container
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """The rows built so far, plus id shortcuts for the ones tests name most."""

    aircraft: JsonDict
    compartments: Dict[str, JsonDict]
    runway: JsonDict
    bands: List[JsonDict] = field(default_factory=list)
    program: Optional[JsonDict] = None
    flight: Optional[JsonDict] = None
    plan: Optional[JsonDict] = None
    pax_lines: Dict[str, JsonDict] = field(default_factory=dict)
    bag_allocations: Dict[str, JsonDict] = field(default_factory=dict)
    cargo: Dict[str, JsonDict] = field(default_factory=dict)
    declarations: Dict[str, JsonDict] = field(default_factory=dict)
    sheet: Optional[JsonDict] = None

    # -- id shortcuts -------------------------------------------------------
    @property
    def aircraft_id(self) -> str:
        return str(self.aircraft["id"])

    @property
    def runway_id(self) -> str:
        return str(self.runway["id"])

    @property
    def program_id(self) -> str:
        assert self.program is not None, "this scenario has no weight programme"
        return str(self.program["id"])

    @property
    def flight_id(self) -> str:
        assert self.flight is not None, "this scenario has no flight"
        return str(self.flight["id"])

    @property
    def plan_id(self) -> str:
        assert self.plan is not None, "this scenario has no load plan"
        return str(self.plan["id"])

    @property
    def sheet_id(self) -> str:
        assert self.sheet is not None, "this scenario has no load sheet"
        return str(self.sheet["id"])

    def compartment(self, code: str) -> JsonDict:
        assert code in self.compartments, (
            f"compartment {code} was not built in this scenario; have {sorted(self.compartments)}"
        )
        return self.compartments[code]

    def compartment_id(self, code: str) -> str:
        return str(self.compartment(code)["id"])

    def cargo_item(self, awb_number: str) -> JsonDict:
        assert awb_number in self.cargo, (
            f"consignment {awb_number} was not booked in this scenario; have {sorted(self.cargo)}"
        )
        return self.cargo[awb_number]

    def cargo_id(self, awb_number: str) -> str:
        return str(self.cargo_item(awb_number)["id"])

    def pax_line(self, code: str) -> JsonDict:
        return self.pax_lines[code]

    def pax_line_id(self, code: str) -> str:
        return str(self.pax_lines[code]["id"])

    def bag_allocation(self, code: str) -> JsonDict:
        return self.bag_allocations[code]

    def bag_allocation_id(self, code: str) -> str:
        return str(self.bag_allocations[code]["id"])

    def declaration(self, awb_number: str) -> JsonDict:
        return self.declarations[awb_number]

    def declaration_id(self, awb_number: str) -> str:
        return str(self.declarations[awb_number]["id"])


# ---------------------------------------------------------------------------
# Tier one: one call each
# ---------------------------------------------------------------------------


def position_clock(to_iso8601: str = SETUP_CLOCK_UTC, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    """Move the logical clock; only a LoadControlAdmin may do this."""
    return get_success_data(api_client.set_clock(to_iso8601, dict(headers or ADMIN)))


def create_aircraft(
    registration: str = "HB-AAA",
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api_client.create_aircraft(f.aircraft_payload(registration, **overrides), dict(headers or ADMIN))
    )


def create_compartments(
    aircraft_id: str,
    specs: Optional[Sequence[Mapping[str, Any]]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, JsonDict]:
    """Declare a list of compartment specs on one airframe, keyed by code."""
    built: Dict[str, JsonDict] = {}
    for spec in specs if specs is not None else f.CANONICAL_COMPARTMENTS:
        payload = f.compartment_payload(aircraft_id=aircraft_id, **dict(spec))
        built[str(spec["code"])] = get_success_data(
            api_client.create_compartment(payload, dict(headers or ADMIN))
        )
    return built


def create_runway(headers: Optional[Mapping[str, str]] = None, **overrides: Any) -> JsonDict:
    return get_success_data(api_client.create_runway(f.runway_payload(**overrides), dict(headers or ADMIN)))


def create_performance_bands(
    runway_id: str,
    specs: Optional[Sequence[Mapping[str, Any]]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> List[JsonDict]:
    built: List[JsonDict] = []
    for spec in specs if specs is not None else f.CANONICAL_BANDS:
        payload = f.performance_band_payload(runway_id=runway_id, **dict(spec))
        built.append(get_success_data(api_client.create_performance_band(payload, dict(headers or ADMIN))))
    return built


def create_weight_program(headers: Optional[Mapping[str, str]] = None, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_weight_program(f.weight_program_payload(**overrides), dict(headers or ADMIN))
    )


def create_actual_weight_program(
    code: str = "ACT-2026",
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api_client.create_weight_program(
            f.actual_weight_program_payload(code, **overrides), dict(headers or ADMIN)
        )
    )


def create_flight(
    aircraft_id: str,
    departure_runway_id: str,
    weight_program_id: str,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    payload = f.flight_payload(aircraft_id, departure_runway_id, weight_program_id, **overrides)
    return get_success_data(api_client.create_flight(payload, dict(headers or LOAD_CONTROLLER)))


def open_plan(flight_id: str, headers: Optional[Mapping[str, str]] = None, **overrides: Any) -> JsonDict:
    """Open a plan, asserting the flight's current version as the API requires."""
    caller = dict(headers or LOAD_CONTROLLER)
    flight = get_success_data(api_client.get_flight(flight_id, caller))
    payload = f.load_plan_payload(flight_id, int(flight["version"]), **overrides)
    return get_success_data(api_client.create_load_plan(payload, caller))


def add_pax_line(
    load_plan_id: str,
    compartment_id: str,
    headers: Optional[Mapping[str, str]] = None,
    **counts: Any,
) -> JsonDict:
    payload = f.pax_line_payload(load_plan_id, compartment_id, **counts)
    return get_success_data(api_client.create_pax_line(payload, dict(headers or LOAD_CONTROLLER)))


def add_bag_allocation(
    load_plan_id: str,
    compartment_id: str,
    bag_count: int,
    bag_weight_kg: Optional[float] = None,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    payload = f.bag_allocation_payload(load_plan_id, compartment_id, bag_count, bag_weight_kg, **overrides)
    return get_success_data(api_client.create_bag_allocation(payload, dict(headers or LOAD_CONTROLLER)))


def book_cargo_item(
    flight_id: str,
    awb_number: str,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    payload = f.cargo_item_payload(flight_id, awb_number, **overrides)
    return get_success_data(api_client.create_cargo_item(payload, dict(headers or RAMP_AGENT)))


def stow_cargo_item(
    cargo_item_id: str,
    compartment_id: str,
    headers: Optional[Mapping[str, str]] = None,
) -> JsonDict:
    payload = {"assigned_compartment_id": compartment_id}
    return get_success_data(api_client.assign_cargo_item(cargo_item_id, payload, dict(headers or RAMP_AGENT)))


def accept_cargo_item(cargo_item_id: str, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    return get_success_data(api_client.accept_cargo_item(cargo_item_id, dict(headers or RAMP_AGENT)))


def declare_hazmat(
    cargo_item_id: str,
    quantity_kg: float,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    payload = f.hazmat_declaration_payload(cargo_item_id, quantity_kg, **overrides)
    return get_success_data(api_client.create_hazmat_declaration(payload, dict(headers or RAMP_AGENT)))


def accept_declaration(declaration_id: str, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    return get_success_data(api_client.accept_hazmat_declaration(declaration_id, dict(headers or DG_OFFICER)))


# ---------------------------------------------------------------------------
# Tier two: scenario-aware steps
# ---------------------------------------------------------------------------


def seat(scenario: Scenario, code: str, headers: Optional[Mapping[str, str]] = None, **counts: Any) -> JsonDict:
    """Seat a passenger mix in one cabin zone of the scenario's plan."""
    line = add_pax_line(scenario.plan_id, scenario.compartment_id(code), headers, **counts)
    scenario.pax_lines[code] = line
    return line


def stow_bags(
    scenario: Scenario,
    code: str,
    bag_count: int,
    bag_weight_kg: Optional[float] = None,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    allocation = add_bag_allocation(
        scenario.plan_id, scenario.compartment_id(code), bag_count, bag_weight_kg, headers, **overrides
    )
    scenario.bag_allocations[code] = allocation
    return allocation


def book_cargo(
    scenario: Scenario,
    awb_number: str,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    item = book_cargo_item(scenario.flight_id, awb_number, headers, **overrides)
    scenario.cargo[awb_number] = item
    return item


def stow_cargo(
    scenario: Scenario,
    awb_number: str,
    code: str,
    headers: Optional[Mapping[str, str]] = None,
) -> JsonDict:
    item = stow_cargo_item(scenario.cargo_id(awb_number), scenario.compartment_id(code), headers)
    scenario.cargo[awb_number] = item
    return item


def book_and_stow_cargo(
    scenario: Scenario,
    awb_number: str,
    code: str,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    """Book a consignment and stow it, the ordinary route to a counted mass."""
    book_cargo(scenario, awb_number, headers, **overrides)
    return stow_cargo(scenario, awb_number, code, headers)


def submit_declaration(
    scenario: Scenario,
    awb_number: str,
    quantity_kg: float,
    headers: Optional[Mapping[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    declaration = declare_hazmat(scenario.cargo_id(awb_number), quantity_kg, headers, **overrides)
    scenario.declarations[awb_number] = declaration
    return declaration


def compute_plan(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    """Compute the plan and record the returned figures on the scenario."""
    scenario.plan = get_success_data(
        api_client.compute_load_plan(scenario.plan_id, dict(headers or LOAD_CONTROLLER))
    )
    return scenario.plan


def apply_offload(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    scenario.plan = get_success_data(
        api_client.apply_offload(scenario.plan_id, dict(headers or LOAD_CONTROLLER))
    )
    return scenario.plan


def issue_sheet(scenario: Scenario, headers: Optional[Mapping[str, str]] = None, **overrides: Any) -> JsonDict:
    """Issue a sheet, asserting the plan's current version as the API requires."""
    caller = dict(headers or LOAD_CONTROLLER)
    plan = get_success_data(api_client.get_load_plan(scenario.plan_id, caller))
    payload = f.load_sheet_payload(scenario.plan_id, int(plan["version"]), **overrides)
    scenario.sheet = get_success_data(api_client.create_load_sheet(payload, caller))
    return scenario.sheet


def accept_sheet(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    scenario.sheet = get_success_data(
        api_client.accept_load_sheet(scenario.sheet_id, dict(headers or CAPTAIN))
    )
    return scenario.sheet


def depart(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    scenario.flight = get_success_data(
        api_client.depart_flight(scenario.flight_id, dict(headers or LOAD_CONTROLLER))
    )
    return scenario.flight


# -- re-reads ---------------------------------------------------------------


def refresh_flight(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    scenario.flight = get_success_data(
        api_client.get_flight(scenario.flight_id, dict(headers or LOAD_CONTROLLER))
    )
    return scenario.flight


def refresh_plan(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    scenario.plan = get_success_data(
        api_client.get_load_plan(scenario.plan_id, dict(headers or LOAD_CONTROLLER))
    )
    return scenario.plan


def refresh_sheet(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> JsonDict:
    scenario.sheet = get_success_data(
        api_client.get_load_sheet(scenario.sheet_id, dict(headers or LOAD_CONTROLLER))
    )
    return scenario.sheet


def refresh_cargo(
    scenario: Scenario,
    awb_number: str,
    headers: Optional[Mapping[str, str]] = None,
) -> JsonDict:
    item = get_success_data(
        api_client.get_cargo_item(scenario.cargo_id(awb_number), dict(headers or RAMP_AGENT))
    )
    scenario.cargo[awb_number] = item
    return item


def refresh_declaration(
    scenario: Scenario,
    awb_number: str,
    headers: Optional[Mapping[str, str]] = None,
) -> JsonDict:
    declaration = get_success_data(
        api_client.get_hazmat_declaration(scenario.declaration_id(awb_number), dict(headers or DG_OFFICER))
    )
    scenario.declarations[awb_number] = declaration
    return declaration


def flight_version(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> int:
    return int(refresh_flight(scenario, headers)["version"])


def plan_version(scenario: Scenario, headers: Optional[Mapping[str, str]] = None) -> int:
    return int(refresh_plan(scenario, headers)["version"])


# ---------------------------------------------------------------------------
# Tier three: composite worlds
# ---------------------------------------------------------------------------


def reference_world(
    *,
    registration: str = "HB-AAA",
    compartment_specs: Optional[Sequence[Mapping[str, Any]]] = None,
    band_specs: Optional[Sequence[Mapping[str, Any]]] = None,
    program_code: str = "STD-2026",
    program_overrides: Optional[Mapping[str, Any]] = None,
    clock: Optional[str] = SETUP_CLOCK_UTC,
) -> Scenario:
    """The reference airframe, its layout, the reference runway, its published
    temperature bands and a standard weight programme — no flight yet."""
    if clock is not None:
        position_clock(clock)
    aircraft = create_aircraft(registration)
    compartments = create_compartments(aircraft["id"], compartment_specs)
    runway = create_runway()
    bands = create_performance_bands(runway["id"], band_specs)
    program = create_weight_program(code=program_code, **dict(program_overrides or {}))
    return Scenario(
        aircraft=aircraft,
        compartments=compartments,
        runway=runway,
        bands=bands,
        program=program,
    )


def sibling_airframe_world(
    base: Scenario,
    registration: str = "HB-BBB",
    compartment_specs: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Scenario:
    """A second airframe sharing the first world's runway, bands and programme."""
    aircraft = create_aircraft(registration)
    compartments = create_compartments(aircraft["id"], compartment_specs)
    return Scenario(
        aircraft=aircraft,
        compartments=compartments,
        runway=base.runway,
        bands=base.bands,
        program=base.program,
    )


def flight_world(
    scenario: Optional[Scenario] = None,
    *,
    headers: Optional[Mapping[str, str]] = None,
    **flight_overrides: Any,
) -> Scenario:
    """Add a flight to a reference world, building the world first if needed."""
    world = scenario if scenario is not None else reference_world()
    world.flight = create_flight(
        world.aircraft_id, world.runway_id, world.program_id, headers, **flight_overrides
    )
    return world


def plan_world(
    scenario: Optional[Scenario] = None,
    *,
    flight_overrides: Optional[Mapping[str, Any]] = None,
    **plan_overrides: Any,
) -> Scenario:
    """A flight with a DRAFT load plan open on it."""
    world = scenario if scenario is not None else flight_world(**dict(flight_overrides or {}))
    if world.flight is None:
        flight_world(world, **dict(flight_overrides or {}))
    world.plan = open_plan(world.flight_id, **plan_overrides)
    return world


def hot_wet_plan_world(**plan_overrides: Any) -> Scenario:
    """A plan on a flight departing at 30 °C onto a wet runway, where the
    performance limit rather than the structural limit binds the payload."""
    world = flight_world(outside_air_temp_c=30, runway_condition="WET")
    world.plan = open_plan(world.flight_id, **plan_overrides)
    return world


def fx_a(**plan_overrides: Any) -> Scenario:
    """The reference distribution before computation: 25 male and 35 female
    seated in the aft cabin zone and 1450 kg of checked bags in the forward
    hold, for a base payload of 6100.00 kg."""
    world = plan_world(**plan_overrides)
    seat(world, "OC", male_count=25, female_count=35)
    stow_bags(world, "H1", 112, 1450)
    return world


def fx_a_computed(**plan_overrides: Any) -> Scenario:
    """``fx_a`` carried through computation: the plan is COMPUTED and the flight
    LOAD_CONTROLLED."""
    world = fx_a(**plan_overrides)
    compute_plan(world)
    return world


def workhorse_world(**plan_overrides: Any) -> Scenario:
    """``fx_a`` plus a 400 kg general consignment stowed aft, computed: base
    payload 6500.00 kg, takeoff weight 58600.00 kg, underload 13680.00 kg."""
    world = fx_a(**plan_overrides)
    book_and_stow_cargo(world, "724-11110001", "H4", item_kind="GENERAL", weight_kg=400, length_m=1.0)
    compute_plan(world)
    return world


def issued_sheet_world(**plan_overrides: Any) -> Scenario:
    """``workhorse_world`` with a load sheet issued against it."""
    world = workhorse_world(**plan_overrides)
    issue_sheet(world)
    return world


def accepted_sheet_world(captain_headers: Optional[Mapping[str, str]] = None, **plan_overrides: Any) -> Scenario:
    """``issued_sheet_world`` with the commander's acceptance recorded, so the
    load is released and the stowed consignment is LOADED."""
    world = issued_sheet_world(**plan_overrides)
    accept_sheet(world, captain_headers)
    return world


def departed_sheet_world(**plan_overrides: Any) -> Scenario:
    """An accepted sheet on a flight that has since gone off blocks."""
    world = accepted_sheet_world(**plan_overrides)
    depart(world)
    return world


#: The weight-restricted distribution used by the offload tests: 13080.00 kg of
#: passengers across three cabin zones, 4200.00 kg of bags across three holds and
#: three consignments — company traffic, general cargo and mail — for a base
#: payload of 20880.00 kg against an allowed payload of 20180.00 kg.
S2_PAX = (
    ("OA", {"male_count": 40, "female_count": 2}),
    ("OB", {"male_count": 30, "female_count": 30}),
    ("OC", {"male_count": 30, "female_count": 28, "child_count": 2, "infant_count": 1}),
)
S2_BAGS = (
    ("H1", 138, 1800),
    ("H4", 123, 1600),
    ("H5", 61, 800),
)
S2_CARGO = (
    ("0001", "COMPANY", 400, 0.8, "H1"),
    ("0002", "GENERAL", 2200, 2.4, "H4"),
    ("0003", "MAIL", 1000, 1.2, "H4"),
)


def s2_restricted_world(
    offload_strategy: str = "PRIORITY_FIRST",
    *,
    scenario: Optional[Scenario] = None,
    awb_prefix: str = "724-2222",
    compute: bool = True,
    **flight_overrides: Any,
) -> Scenario:
    """Build the weight-restricted distribution and compute it, leaving the plan
    RESTRICTED with a frozen underload of -700.00 kg and the flight PLANNING."""
    world = scenario if scenario is not None else reference_world()
    if world.flight is None:
        flight_world(world, **flight_overrides)
    world.plan = open_plan(world.flight_id, offload_strategy=offload_strategy)
    for code, counts in S2_PAX:
        seat(world, code, **counts)
    for code, bag_count, bag_weight_kg in S2_BAGS:
        stow_bags(world, code, bag_count, bag_weight_kg)
    for suffix, item_kind, weight_kg, length_m, code in S2_CARGO:
        book_and_stow_cargo(
            world,
            f"{awb_prefix}{suffix}",
            code,
            item_kind=item_kind,
            weight_kg=weight_kg,
            length_m=length_m,
        )
    if compute:
        compute_plan(world)
    return world
