"""Composite setup helpers for multi-step test prerequisites.

Uses ``get_success_data()`` (the lenient validator) so a broken setup step
reports itself as a setup failure rather than as a confusing assertion
mismatch inside the test body.

Every helper reflects a sequence the PRD makes necessary: an outlet must exist
before an agreement, an agreement needs at least one dispenser unit before it
can be activated, a supply position only becomes allocatable after a forecast
run has raised its alert level, and so on.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    allocation_payload,
    assess_shortfall_payload,
    compliance_hold_payload,
    create_agreement_payload,
    create_dispenser_unit_payload,
    create_maintenance_task_payload,
    create_outlet_payload,
    create_route_payload,
    create_route_stop_payload,
    create_service_call_payload,
    create_supply_item_payload,
    create_supply_position_payload,
    create_telemetry_payload,
    create_van_part_stock_payload,
    dispatch_call_payload,
    dispatch_route_payload,
    escalate_call_payload,
    forecast_payload,
    outlet_status_change_payload,
    recall_decision_payload,
    resolve_call_payload,
    restock_payload,
    service_hold_payload,
    set_clock_payload,
    skip_stop_payload,
    unique_suffix,
    waive_task_payload,
)
from .test_users import TEST_USERS, make_outlet_manager_headers

ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_alt_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_ALT = TEST_USERS["officer_alt_headers"]

DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"


# ─── Tier 0: primitives ───────────────────────────────────────────────────


def pin_clock(instant: str = DEFAULT_CLOCK_INSTANT, headers=ADMIN) -> dict:
    """Move the logical clock to ``instant``."""
    return get_success_data(api_client.set_clock(set_clock_payload(instant), headers))


def read_outlet(outlet_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_outlet(outlet_id, headers))


def read_agreement(agreement_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, headers))


def read_unit(unit_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_dispenser_unit(unit_id, headers))


def read_supply_item(item_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_supply_item(item_id, headers))


def read_position(position_id: str, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_supply_position(position_id, headers))


def read_route(route_id: str, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_route(route_id, headers))


def read_stop(stop_id: str, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, headers))


def read_task(task_id: str, headers=OFFICER) -> dict:
    return get_success_data(api_client.get_maintenance_task(task_id, headers))


def read_call(call_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_service_call(call_id, headers))


def read_van_stock(stock_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_van_part_stock(stock_id, headers))


def route_version(route_id: str) -> int:
    return read_route(route_id)["version"]


def outlet_version(outlet_id: str) -> int:
    return read_outlet(outlet_id)["version"]


# ─── Tier 1: single-entity creation with state progression ────────────────


def create_outlet(**overrides) -> dict:
    """Create an Outlet. It starts ACTIVE with posture OPEN and version 1."""
    return get_success_data(
        api_client.create_outlet(create_outlet_payload(**overrides), ADMIN)
    )


def create_agreement(outlet_id: str, expected_version: Optional[int] = None,
                     **overrides) -> dict:
    """Create a DRAFT PlacementAgreement against the outlet's current version."""
    version = expected_version if expected_version is not None else outlet_version(outlet_id)
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(outlet_id, version, **overrides), ADMIN
        )
    )


def create_unit(outlet_id: str, agreement_id: str, **overrides) -> dict:
    """Create an IN_SERVICE / UNVERIFIED DispenserUnit."""
    return get_success_data(
        api_client.create_dispenser_unit(
            create_dispenser_unit_payload(outlet_id, agreement_id, **overrides), ADMIN
        )
    )


def activate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, ADMIN))


def create_supply_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_supply_item(create_supply_item_payload(**overrides), ADMIN)
    )


def create_van_stock(van_code: str, part_sku: str = "PUMP_ASSY_12",
                     on_van_units: int = 5) -> dict:
    return get_success_data(
        api_client.create_van_part_stock(
            create_van_part_stock_payload(van_code, part_sku, on_van_units), ADMIN
        )
    )


def restock_van(stock_id: str, units: int) -> dict:
    return get_success_data(
        api_client.restock_van_part(stock_id, restock_payload(units), ADMIN)
    )


def add_telemetry(unit_id: str, item_id: str, dispensed_ounces: float,
                  reading_at: str = "2026-07-31T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_telemetry_reading(
            create_telemetry_payload(
                unit_id, item_id, dispensed_ounces, reading_at, **overrides
            ),
            PLANNER,
        )
    )


def create_position(outlet_id: str, item_id: str, on_hand_units: Optional[int] = None,
                    **overrides) -> dict:
    if on_hand_units is not None:
        overrides["on_hand_units"] = on_hand_units
    return get_success_data(
        api_client.create_supply_position(
            create_supply_position_payload(outlet_id, item_id, **overrides), PLANNER
        )
    )


def run_forecast(position_id: str, variant: str = "TRAILING_ACTUAL",
                 window_days: int = 7) -> dict:
    return get_success_data(
        api_client.run_forecast(position_id, forecast_payload(variant, window_days), PLANNER)
    )


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(create_route_payload(**overrides), PLANNER))


def add_stop(route_id: str, outlet_id: str, sequence_index: int = 1,
             window_start: str = "2026-08-02T08:00:00Z",
             window_end: str = "2026-08-02T10:00:00Z", **overrides) -> dict:
    """Add a PENDING RouteStop, reading the route's current version first."""
    return get_success_data(
        api_client.create_route_stop(
            route_id,
            create_route_stop_payload(
                outlet_id,
                route_version(route_id),
                sequence_index,
                window_start,
                window_end,
                **overrides,
            ),
            PLANNER,
        )
    )


def allocate(stop_id: str, position_ids: List[str]) -> dict:
    return get_success_data(
        api_client.allocate_stop(stop_id, allocation_payload(position_ids), PLANNER)
    )


def dispatch_route(route_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_route(
            route_id, dispatch_route_payload(route_version(route_id)), PLANNER
        )
    )


def arrive_stop(stop_id: str) -> dict:
    return get_success_data(api_client.arrive_stop(stop_id, DRIVER))


def serve_stop(stop_id: str) -> dict:
    return get_success_data(api_client.serve_stop(stop_id, DRIVER))


def skip_stop(stop_id: str, skip_reason_code: str = "ACCESS_DENIED") -> dict:
    return get_success_data(
        api_client.skip_stop(stop_id, skip_stop_payload(skip_reason_code), DRIVER)
    )


def create_task(unit_id: str, task_type: str = "PREVENTIVE",
                due_at: str = "2026-08-10T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_maintenance_task(
            create_maintenance_task_payload(unit_id, task_type, due_at, **overrides),
            OFFICER,
        )
    )


def evaluate_task(task_id: str, headers=OFFICER) -> dict:
    return get_success_data(api_client.evaluate_task_due(task_id, headers))


def complete_task(task_id: str, headers=TECH, **payload) -> dict:
    return get_success_data(api_client.complete_task(task_id, headers, payload or {}))


def waive_task(task_id: str, waiver_reason: str = "OPERATOR_REQUEST",
               headers=OFFICER) -> dict:
    return get_success_data(
        api_client.waive_task(task_id, waive_task_payload(waiver_reason), headers)
    )


def create_call(unit_id: str, symptom_code: str = "NO_POUR",
                reported_at: str = DEFAULT_CLOCK_INSTANT, headers=ADMIN,
                **overrides) -> dict:
    return get_success_data(
        api_client.create_service_call(
            create_service_call_payload(unit_id, symptom_code, reported_at, **overrides),
            headers,
        )
    )


def dispatch_call(call_id: str, van_code: str,
                  window_start: str = "2026-08-01T09:00:00Z",
                  window_end: str = "2026-08-01T11:00:00Z", headers=TECH,
                  **overrides) -> dict:
    return get_success_data(
        api_client.dispatch_service_call(
            call_id,
            dispatch_call_payload(van_code, window_start, window_end, **overrides),
            headers,
        )
    )


def arrive_call(call_id: str, headers=TECH) -> dict:
    return get_success_data(api_client.arrive_on_site(call_id, headers))


def resolve_call(call_id: str, resolution_code: str = "NO_FAULT_FOUND", headers=TECH,
                 **overrides) -> dict:
    return get_success_data(
        api_client.resolve_service_call(
            call_id, resolve_call_payload(resolution_code, **overrides), headers
        )
    )


def escalate_call(call_id: str, escalation_reason_code: str = "WRONG_PART",
                  headers=TECH) -> dict:
    return get_success_data(
        api_client.escalate_service_call(
            call_id, escalate_call_payload(escalation_reason_code), headers
        )
    )


def place_service_hold(unit_id: str, headers=TECH) -> dict:
    return get_success_data(
        api_client.unit_service_hold(unit_id, service_hold_payload("PLACE"), headers)
    )


def release_service_hold(unit_id: str, headers=TECH) -> dict:
    return get_success_data(
        api_client.unit_service_hold(unit_id, service_hold_payload("RELEASE"), headers)
    )


def place_compliance_hold(outlet_id: str, headers=OFFICER,
                          hold_reason_code: str = "HEALTH_INSPECTION") -> dict:
    return get_success_data(
        api_client.outlet_compliance_hold(
            outlet_id, compliance_hold_payload("PLACE", hold_reason_code), headers
        )
    )


def release_compliance_hold(outlet_id: str, headers=OFFICER,
                            hold_reason_code: str = "HEALTH_INSPECTION") -> dict:
    return get_success_data(
        api_client.outlet_compliance_hold(
            outlet_id, compliance_hold_payload("RELEASE", hold_reason_code), headers
        )
    )


def change_outlet_status(outlet_id: str, action: str) -> dict:
    return get_success_data(
        api_client.outlet_status_change(
            outlet_id, outlet_status_change_payload(action), ADMIN
        )
    )


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────────


@dataclass
class OutletScenario:
    """An outlet with an ACTIVE agreement and one IN_SERVICE dispenser unit."""

    outlet: dict
    agreement: dict
    unit: dict
    units: List[dict] = field(default_factory=list)

    @property
    def outlet_id(self) -> str:
        return self.outlet["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def unit_id(self) -> str:
        return self.unit["id"]

    @property
    def manager_headers(self) -> dict:
        return make_outlet_manager_headers(self.outlet["id"])


def setup_outlet_with_draft_agreement(outlet_overrides=None,
                                      agreement_overrides=None) -> OutletScenario:
    """Outlet + DRAFT agreement + one unit; the agreement is not activated."""
    outlet = create_outlet(**(outlet_overrides or {}))
    agreement = create_agreement(outlet["id"], **(agreement_overrides or {}))
    unit = create_unit(outlet["id"], agreement["id"])
    return OutletScenario(outlet=outlet, agreement=agreement, unit=unit, units=[unit])


def setup_active_outlet(clock: Optional[str] = DEFAULT_CLOCK_INSTANT,
                        outlet_overrides=None, agreement_overrides=None,
                        unit_overrides=None, unit_count: int = 1) -> OutletScenario:
    """Pinned clock + Outlet + ACTIVE agreement + ``unit_count`` IN_SERVICE units."""
    if clock:
        pin_clock(clock)
    outlet = create_outlet(**(outlet_overrides or {}))
    agreement = create_agreement(outlet["id"], **(agreement_overrides or {}))
    units = [
        create_unit(outlet["id"], agreement["id"], **(unit_overrides or {}))
        for _ in range(unit_count)
    ]
    activate_agreement(agreement["id"])
    return OutletScenario(
        outlet=read_outlet(outlet["id"]),
        agreement=read_agreement(agreement["id"]),
        unit=units[0],
        units=units,
    )


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────


@dataclass
class SupplyScenario:
    """Outlet scenario plus a SKU, telemetry history and a forecast-run position."""

    base: OutletScenario
    item: dict
    position: dict

    @property
    def outlet_id(self) -> str:
        return self.base.outlet_id

    @property
    def unit_id(self) -> str:
        return self.base.unit_id

    @property
    def item_id(self) -> str:
        return self.item["id"]

    @property
    def position_id(self) -> str:
        return self.position["id"]


def setup_position_with_alert(dispensed_ounces: float = 7000,
                             on_hand_units: int = 6,
                             reading_at: str = "2026-07-31T00:00:00Z",
                             variant: str = "TRAILING_ACTUAL",
                             window_days: int = 7,
                             clock: Optional[str] = DEFAULT_CLOCK_INSTANT,
                             outlet_overrides=None, agreement_overrides=None,
                             item_overrides=None,
                             run_forecast_now: bool = True) -> SupplyScenario:
    """Reach a position whose forecast run has raised ``requested_units`` and an alert.

    Chain: clock → outlet → agreement → unit → activate → SKU → telemetry →
    position → forecast. With the default numbers a 7000 oz week over a
    350 oz cartridge and 6 units on hand leaves the position CRITICAL.
    """
    base = setup_active_outlet(
        clock=clock,
        outlet_overrides=outlet_overrides,
        agreement_overrides=agreement_overrides,
    )
    item = create_supply_item(**(item_overrides or {}))
    if dispensed_ounces:
        add_telemetry(base.unit_id, item["id"], dispensed_ounces, reading_at)
    position = create_position(base.outlet_id, item["id"], on_hand_units)
    if run_forecast_now:
        position = run_forecast(position["id"], variant, window_days)
    return SupplyScenario(base=base, item=item, position=position)


@dataclass
class RouteScenario:
    """A supply scenario plus a route, a stop and (optionally) an allocation."""

    supply: SupplyScenario
    route: dict
    stop: dict
    allocation: Optional[dict] = None

    @property
    def route_id(self) -> str:
        return self.route["id"]

    @property
    def stop_id(self) -> str:
        return self.stop["id"]

    @property
    def position_id(self) -> str:
        return self.supply.position_id

    @property
    def item_id(self) -> str:
        return self.supply.item_id

    @property
    def outlet_id(self) -> str:
        return self.supply.outlet_id

    @property
    def unit_id(self) -> str:
        return self.supply.unit_id


def setup_allocated_stop(capacity_units: int = 500,
                         dispensed_ounces: float = 7000,
                         on_hand_units: int = 6,
                         region_code: str = "R-WEST",
                         item_overrides=None,
                         allocate_now: bool = True,
                         clock: Optional[str] = DEFAULT_CLOCK_INSTANT,
                         outlet_overrides=None) -> RouteScenario:
    """Walk all the way to a PENDING stop holding a whole-case allocation.

    The route's depot region and the outlet's region are kept equal because the
    PRD refuses a stop whose outlet sits in a different region from the depot.
    """
    outlet_overrides = dict(outlet_overrides or {})
    outlet_overrides.setdefault("region_code", region_code)
    supply = setup_position_with_alert(
        dispensed_ounces=dispensed_ounces,
        on_hand_units=on_hand_units,
        clock=clock,
        outlet_overrides=outlet_overrides,
        item_overrides=item_overrides,
    )
    route = create_route(depot_region_code=region_code, capacity_units=capacity_units)
    stop = add_stop(route["id"], supply.outlet_id)
    allocation = allocate(stop["id"], [supply.position_id]) if allocate_now else None
    return RouteScenario(
        supply=supply, route=read_route(route["id"]), stop=read_stop(stop["id"]),
        allocation=allocation,
    )


def setup_arrived_stop(**kwargs) -> RouteScenario:
    """A DISPATCHED route whose single stop has been ARRIVED at, allocation intact."""
    scenario = setup_allocated_stop(**kwargs)
    dispatch_route(scenario.route_id)
    arrive_stop(scenario.stop_id)
    scenario.route = read_route(scenario.route_id)
    scenario.stop = read_stop(scenario.stop_id)
    return scenario


# ─── Tier 4: accumulation / threshold targeting ───────────────────────────


def setup_overdue_tasks(unit_id: str, count: int, due_at: str = "2026-08-02T00:00:00Z",
                        evaluate_at: str = "2026-08-10T00:00:00Z",
                        task_type: str = "PREVENTIVE") -> List[dict]:
    """Drive ``count`` tasks on one unit into OVERDUE so the posture bands can be hit.

    Each task is scheduled with a ``due_at`` already behind ``evaluate_at`` by
    more than the grace period, then evaluated once the clock has moved.
    """
    tasks = [create_task(unit_id, task_type, due_at) for _ in range(count)]
    pin_clock(evaluate_at)
    return [evaluate_task(task["id"]) for task in tasks]


def setup_unit_at_gallon_reading(unit_id: str, item_id: str, total_ounces: float,
                                 reading_at: str = "2026-07-31T00:00:00Z") -> dict:
    """Push a unit's ``lifetime_dispensed_gallons`` to a chosen level in one reading."""
    add_telemetry(unit_id, item_id, total_ounces, reading_at)
    return read_unit(unit_id)


def setup_filter_change_task(unit_id: str, gallon_interval: float,
                             due_at: str = "2027-01-01T00:00:00Z") -> dict:
    """A SCHEDULED FILTER_CHANGE whose date is far off, so only gallons can breach it."""
    return create_task(unit_id, "FILTER_CHANGE", due_at, gallon_interval=gallon_interval)


def setup_out_of_spec_unit(unit_id: str, measured_brix_ratio: float = 5.40,
                           due_at: str = "2026-08-05T00:00:00Z") -> dict:
    """Grade a unit OUT_OF_SPEC by completing a calibration outside tolerance."""
    task = create_task(unit_id, "BRIX_CALIBRATION", due_at)
    complete_task(task["id"], measured_brix_ratio=measured_brix_ratio)
    return read_unit(unit_id)


def setup_in_spec_unit(unit_id: str, measured_brix_ratio: float = 5.10,
                       due_at: str = "2026-08-06T00:00:00Z") -> dict:
    """Grade a unit IN_SPEC by completing a calibration inside tolerance."""
    task = create_task(unit_id, "BRIX_CALIBRATION", due_at)
    complete_task(task["id"], measured_brix_ratio=measured_brix_ratio)
    return read_unit(unit_id)


def setup_frozen_outlet(outlet_id: str, headers=OFFICER) -> dict:
    """Freeze an outlet's posture through a compliance hold."""
    place_compliance_hold(outlet_id, headers)
    return read_outlet(outlet_id)


def setup_dispatched_call_holding_parts(unit_id: str, van_code: str,
                                        part_sku: str = "PUMP_ASSY_12",
                                        on_van_units: int = 5,
                                        part_units: int = 2,
                                        window_start: str = "2026-08-01T09:00:00Z",
                                        window_end: str = "2026-08-01T11:00:00Z",
                                        symptom_code: str = "NO_POUR",
                                        headers=TECH):
    """A DISPATCHED service call that has reserved parts from a van's stock."""
    stock = create_van_stock(van_code, part_sku, on_van_units)
    call = create_call(unit_id, symptom_code)
    call = dispatch_call(
        call["id"], van_code, window_start, window_end, headers,
        part_sku=part_sku, part_units=part_units,
    )
    return call, read_van_stock(stock["id"])


def setup_escalated_call(unit_id: str, van_code: str, headers=TECH) -> dict:
    """Walk a call OPEN → DISPATCHED → ON_SITE → ESCALATED."""
    call = create_call(unit_id)
    dispatch_call(call["id"], van_code, headers=headers)
    arrive_call(call["id"], headers)
    return escalate_call(call["id"], headers=headers)


# ─── Tier 5: finalization / terminal state ────────────────────────────────


def setup_shortfall_review(annual_commitment_gallons: float = 8000,
                           shortfall_fee_cents_per_gallon: int = 50,
                           equipment_value_cents: int = 480000,
                           installed_at: str = "2026-01-01T00:00:00Z",
                           term_start_date: str = "2026-01-01T00:00:00Z",
                           term_end_date: str = "2027-01-01T00:00:00Z",
                           readings: Optional[List[tuple]] = None,
                           assess_clock: str = "2026-10-01T00:00:00Z",
                           period_start_date: str = "2026-01-01T00:00:00Z",
                           period_end_date: str = "2026-10-01T00:00:00Z",
                           exposure_variant: Optional[str] = None,
                           assessor_headers=ADMIN_ALT,
                           free_on_loan: bool = True,
                           clock: Optional[str] = DEFAULT_CLOCK_INSTANT):
    """Drive an agreement through assess-shortfall into SHORTFALL_REVIEW.

    ``readings`` is a list of ``(dispensed_ounces, reading_at)`` pairs recorded
    against the agreement's unit before the assessment runs.
    """
    base = setup_active_outlet(
        clock=clock,
        agreement_overrides={
            "annual_commitment_gallons": annual_commitment_gallons,
            "shortfall_fee_cents_per_gallon": shortfall_fee_cents_per_gallon,
            "equipment_value_cents": equipment_value_cents,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
            "free_on_loan": free_on_loan,
        },
        unit_overrides={"installed_at": installed_at},
    )
    item = create_supply_item()
    for ounces, reading_at in readings or []:
        add_telemetry(base.unit_id, item["id"], ounces, reading_at)
    pin_clock(assess_clock)
    payload = assess_shortfall_payload(period_start_date, period_end_date)
    if exposure_variant is not None:
        payload["exposure_variant"] = exposure_variant
    agreement = get_success_data(
        api_client.assess_shortfall(base.agreement_id, payload, assessor_headers)
    )
    return base, item, agreement


def setup_recall_pending(decider_headers=OFFICER, **kwargs):
    """Take an agreement all the way to RECALL_PENDING with its unit RECALL_STAGED."""
    base, item, agreement = setup_shortfall_review(**kwargs)
    agreement = get_success_data(
        api_client.recall_decision(
            base.agreement_id, recall_decision_payload("RECALL"), decider_headers
        )
    )
    return base, item, agreement
