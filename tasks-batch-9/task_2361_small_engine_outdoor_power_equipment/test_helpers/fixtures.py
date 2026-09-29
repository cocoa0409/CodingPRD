"""Composite state builders and pytest fixtures.

Every test starts against an empty database, so all preconditions are built
from scratch through the documented endpoints. The builders below are the
reusable middle layer: each one drives one documented transition and returns
the resource it produced, and the fixtures at the bottom of the file compose
them into the states the suite needs repeatedly.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_CLOCK_UTC,
    CAPABLE_MEASUREMENTS,
    HOT_TEST_NOMINAL_RPM,
    HOT_TEST_PASSING_EMISSION,
)
from .factories import (
    close_machining_run_payload,
    complete_durability_test_payload,
    create_assembly_line_payload,
    create_build_order_payload,
    create_certification_family_payload,
    create_component_lot_payload,
    create_durability_test_payload,
    create_engine_platform_payload,
    create_engine_unit_payload,
    create_line_audit_payload,
    create_machining_run_payload,
    create_parts_request_payload,
    create_product_model_payload,
    create_safety_certification_payload,
    create_service_part_payload,
    create_supplier_payload,
    hot_test_payload,
    inspect_component_lot_payload,
    record_line_audit_payload,
    run_allocations_payload,
    set_clock_payload,
    supersede_service_part_payload,
    torque_record_payload,
)
from .test_users import TEST_USERS

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
CERTIFICATION_ENGINEER = TEST_USERS["certification_engineer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
QUALITY_ENGINEER = TEST_USERS["quality_engineer_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]
CHANNEL_PARTNER = TEST_USERS["channel_partner_headers"]
SECOND_COMPLIANCE_OFFICER = TEST_USERS["second_compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Scenario container
# ---------------------------------------------------------------------------


@dataclass
class PlantScenario:
    """Everything a composed fixture has built so far."""

    family: Optional[dict] = None
    platform: Optional[dict] = None
    durability_run: Optional[dict] = None
    model: Optional[dict] = None
    safety_certification: Optional[dict] = None
    line: Optional[dict] = None
    suppliers: Dict[str, dict] = field(default_factory=dict)
    lots: Dict[str, dict] = field(default_factory=dict)
    machining_run: Optional[dict] = None
    build_order: Optional[dict] = None
    units: List[dict] = field(default_factory=list)

    @property
    def family_id(self) -> str:
        return self.family["id"]

    @property
    def platform_id(self) -> str:
        return self.platform["id"]

    @property
    def model_id(self) -> str:
        return self.model["id"]

    @property
    def line_id(self) -> str:
        return self.line["id"]

    @property
    def build_order_id(self) -> str:
        return self.build_order["id"]

    @property
    def machining_run_id(self) -> str:
        return self.machining_run["id"]

    @property
    def carburetor_lot_id(self) -> str:
        return self.lots["carburetor"]["id"]

    @property
    def ignition_lot_id(self) -> str:
        return self.lots["ignition"]["id"]

    @property
    def casting_lot_id(self) -> str:
        return self.lots["casting"]["id"]

    def refresh_build_order(self) -> dict:
        self.build_order = read_build_order(self.build_order_id)
        return self.build_order

    def refresh_family(self) -> dict:
        self.family = read_family(self.family_id)
        return self.family

    def refresh_platform(self) -> dict:
        self.platform = read_platform(self.platform_id)
        return self.platform

    def refresh_model(self) -> dict:
        self.model = read_model(self.model_id)
        return self.model


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str = CANONICAL_CLOCK_UTC) -> dict:
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), PLANT_ADMIN)
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_family(family_id: str) -> dict:
    return get_success_data(
        api_client.get_certification_family(family_id, PLANT_ADMIN)
    )


def read_platform(platform_id: str) -> dict:
    return get_success_data(api_client.get_engine_platform(platform_id, PLANT_ADMIN))


def read_model(model_id: str) -> dict:
    return get_success_data(api_client.get_product_model(model_id, PLANT_ADMIN))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_component_lot(lot_id, PLANT_ADMIN))


def read_machining_run(run_id: str) -> dict:
    return get_success_data(api_client.get_machining_run(run_id, PLANT_ADMIN))


def read_build_order(order_id: str) -> dict:
    return get_success_data(api_client.get_build_order(order_id, PLANT_ADMIN))


def read_engine_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_engine_unit(unit_id, PLANT_ADMIN))


def read_service_part(part_id: str) -> dict:
    return get_success_data(api_client.get_service_part(part_id, PLANT_ADMIN))


def read_supplier_scorecard(supplier_id: str) -> dict:
    return get_success_data(
        api_client.get_supplier_scorecard(supplier_id, PLANT_ADMIN)
    )


def read_durability_run(run_id: str) -> dict:
    return get_success_data(api_client.get_durability_test(run_id, PLANT_ADMIN))


def family_version(family_id: str) -> int:
    return read_family(family_id)["version"]


def build_order_version(order_id: str) -> int:
    return read_build_order(order_id)["version"]


# ---------------------------------------------------------------------------
# Certification families, platforms and durability
# ---------------------------------------------------------------------------


def build_certification_family(**overrides) -> dict:
    return get_success_data(
        api_client.create_certification_family(
            create_certification_family_payload(**overrides), CERTIFICATION_ENGINEER
        ),
        201,
    )


def build_engine_platform(certification_family_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_engine_platform(
            create_engine_platform_payload(certification_family_id, **overrides),
            PLANT_ADMIN,
        ),
        201,
    )


def schedule_durability_run(
    certification_family_id: str, engine_platform_id: str, **overrides
) -> dict:
    expected = overrides.pop(
        "expected_certification_family_version", family_version(certification_family_id)
    )
    return get_success_data(
        api_client.create_durability_test(
            create_durability_test_payload(
                certification_family_id, engine_platform_id, expected, **overrides
            ),
            CERTIFICATION_ENGINEER,
        ),
        201,
    )


def complete_durability_run(run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.complete_durability_test(
            run_id, complete_durability_test_payload(**overrides), CERTIFICATION_ENGINEER
        )
    )


def submit_family(family_id: str) -> dict:
    return get_success_data(
        api_client.submit_certification_family(family_id, CERTIFICATION_ENGINEER)
    )


def certify_family(family_id: str, headers=None) -> dict:
    """The certifier must differ from the submitting operator."""
    return get_success_data(
        api_client.certify_certification_family(
            family_id, headers if headers is not None else COMPLIANCE_OFFICER
        )
    )


def build_certified_family_and_platform(
    family_overrides: Optional[dict] = None,
    platform_overrides: Optional[dict] = None,
    durability_overrides: Optional[dict] = None,
    completion_overrides: Optional[dict] = None,
) -> PlantScenario:
    """Family taken all the way to CERTIFIED, leaving its platform posture OPEN."""
    family = build_certification_family(**(family_overrides or {}))
    platform = build_engine_platform(family["id"], **(platform_overrides or {}))
    run = schedule_durability_run(
        family["id"], platform["id"], **(durability_overrides or {})
    )
    run = complete_durability_run(run["id"], **(completion_overrides or {}))
    submit_family(family["id"])
    family = certify_family(family["id"])
    return PlantScenario(
        family=family, platform=read_platform(platform["id"]), durability_run=run
    )


# ---------------------------------------------------------------------------
# Product models and safety certifications
# ---------------------------------------------------------------------------


def build_product_model(engine_platform_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_product_model(
            create_product_model_payload(engine_platform_id, **overrides), PLANT_ADMIN
        ),
        201,
    )


def build_safety_certification(product_model_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_safety_certification(
            create_safety_certification_payload(product_model_id, **overrides),
            COMPLIANCE_OFFICER,
        ),
        201,
    )


def release_product_model(product_model_id: str) -> dict:
    return get_success_data(
        api_client.release_product_model(product_model_id, PLANT_ADMIN)
    )


def build_released_model(
    scenario: PlantScenario,
    model_overrides: Optional[dict] = None,
    certification_overrides: Optional[dict] = None,
) -> PlantScenario:
    """A model with a passing bench test, released for production."""
    model = build_product_model(scenario.platform_id, **(model_overrides or {}))
    certification = build_safety_certification(
        model["id"], **(certification_overrides or {})
    )
    scenario.model = release_product_model(model["id"])
    scenario.safety_certification = certification
    return scenario


# ---------------------------------------------------------------------------
# Suppliers, component lots and machining
# ---------------------------------------------------------------------------


def build_supplier(**overrides) -> dict:
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(**overrides), PLANT_ADMIN),
        201,
    )


def receive_component_lot(supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_component_lot(
            create_component_lot_payload(supplier_id, **overrides), QUALITY_ENGINEER
        ),
        201,
    )


def inspect_component_lot(lot_id: str, defects_found: int = 0, **overrides) -> dict:
    return get_success_data(
        api_client.inspect_component_lot(
            lot_id,
            inspect_component_lot_payload(defects_found, **overrides),
            QUALITY_ENGINEER,
        )
    )


def deviation_accept_lot(lot_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.deviation_accept_component_lot(
            lot_id, headers if headers is not None else COMPLIANCE_OFFICER
        )
    )


def build_accepted_lot(
    supplier_id: str, defects_found: int = 0, **overrides
) -> dict:
    """A received lot carried through a clean incoming inspection."""
    lot = receive_component_lot(supplier_id, **overrides)
    return inspect_component_lot(lot["id"], defects_found)


def build_supply_base(scenario: PlantScenario) -> PlantScenario:
    """One approved supplier and one accepted lot per component category."""
    carburetor_supplier = build_supplier(
        supplier_code="SUP-CARB",
        name="Kirin Carburetor Works",
        component_category="CARBURETOR",
    )
    ignition_supplier = build_supplier(
        supplier_code="SUP-IGN",
        name="Nagata Ignition Systems",
        component_category="IGNITION",
    )
    casting_supplier = build_supplier(
        supplier_code="SUP-CAST",
        name="Foundry Nord Castings",
        component_category="CASTING",
    )
    scenario.suppliers = {
        "carburetor": carburetor_supplier,
        "ignition": ignition_supplier,
        "casting": casting_supplier,
    }
    scenario.lots = {
        "carburetor": build_accepted_lot(carburetor_supplier["id"], lot_code="CB-001"),
        "ignition": build_accepted_lot(ignition_supplier["id"], lot_code="IG-001"),
        "casting": build_accepted_lot(casting_supplier["id"], lot_code="CS-001"),
    }
    return scenario


def open_machining_run(
    engine_platform_id: str, casting_lot_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_machining_run(
            create_machining_run_payload(
                engine_platform_id, casting_lot_id, **overrides
            ),
            QUALITY_ENGINEER,
        ),
        201,
    )


def close_machining_run(run_id: str, measurements=None, **overrides) -> dict:
    return get_success_data(
        api_client.close_machining_run(
            run_id,
            close_machining_run_payload(measurements, **overrides),
            QUALITY_ENGINEER,
        )
    )


def build_closed_machining_run(
    engine_platform_id: str,
    casting_lot_id: str,
    measurements=None,
    **overrides,
) -> dict:
    run = open_machining_run(engine_platform_id, casting_lot_id, **overrides)
    return close_machining_run(
        run["id"], measurements if measurements is not None else CAPABLE_MEASUREMENTS
    )


# ---------------------------------------------------------------------------
# Assembly lines and build orders
# ---------------------------------------------------------------------------


def build_assembly_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_assembly_line(
            create_assembly_line_payload(**overrides), PLANT_ADMIN
        ),
        201,
    )


def plan_build_order(product_model_id: str, assembly_line_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_build_order(
            create_build_order_payload(product_model_id, assembly_line_id, **overrides),
            PRODUCTION_PLANNER,
        ),
        201,
    )


def release_build_order(order_id: str) -> dict:
    return get_success_data(
        api_client.release_build_order(order_id, PRODUCTION_PLANNER)
    )


def run_allocations(order_id: str, expected_version: Optional[int] = None) -> dict:
    version = (
        expected_version
        if expected_version is not None
        else build_order_version(order_id)
    )
    return get_success_data(
        api_client.run_build_order_allocations(
            order_id, run_allocations_payload(version), PRODUCTION_PLANNER
        )
    )


def reset_allocations(order_id: str) -> dict:
    return get_success_data(
        api_client.reset_build_order_allocations(order_id, PRODUCTION_PLANNER)
    )


def schedule_line_audit(order_id: str, audit_week: str = "2026-09-14", **overrides):
    return get_success_data(
        api_client.create_line_audit(
            order_id, create_line_audit_payload(audit_week, **overrides), COMPLIANCE_OFFICER
        ),
        201,
    )


def record_line_audit(audit_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.record_line_audit(
            audit_id,
            record_line_audit_payload(**overrides),
            headers if headers is not None else COMPLIANCE_OFFICER,
        )
    )


# ---------------------------------------------------------------------------
# Engine units
# ---------------------------------------------------------------------------


def stage_engine_unit(
    scenario: PlantScenario, serial_number: str = "SN-0001", **overrides
) -> dict:
    arguments = {
        "build_order_id": scenario.build_order_id,
        "machining_run_id": scenario.machining_run_id,
        "carburetor_lot_id": scenario.carburetor_lot_id,
        "ignition_lot_id": scenario.ignition_lot_id,
        "serial_number": serial_number,
    }
    # A caller may point any slot at a different row (e.g. a deviation lot); the
    # override replaces the scenario default instead of colliding with it.
    arguments.update(overrides)
    unit = get_success_data(
        api_client.create_engine_unit(
            create_engine_unit_payload(**arguments),
            QUALITY_ENGINEER,
        ),
        201,
    )
    scenario.units.append(unit)
    return unit


def record_torque(unit_id: str, torque_readings=None, **overrides) -> dict:
    return get_success_data(
        api_client.torque_record_engine_unit(
            unit_id, torque_record_payload(torque_readings, **overrides), QUALITY_ENGINEER
        )
    )


def hot_test_unit(
    unit_id: str,
    measured_rpm: int = HOT_TEST_NOMINAL_RPM,
    measured_emission_g_per_kwh: float = HOT_TEST_PASSING_EMISSION,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.hot_test_engine_unit(
            unit_id,
            hot_test_payload(measured_rpm, measured_emission_g_per_kwh, **overrides),
            QUALITY_ENGINEER,
        )
    )


def release_engine_unit(unit_id: str) -> dict:
    return get_success_data(api_client.release_engine_unit(unit_id, QUALITY_ENGINEER))


def rework_engine_unit(unit_id: str) -> dict:
    return get_success_data(api_client.rework_engine_unit(unit_id, QUALITY_ENGINEER))


def cancel_engine_unit(unit_id: str) -> dict:
    return get_success_data(api_client.cancel_engine_unit(unit_id, QUALITY_ENGINEER))


def build_and_release_unit(
    scenario: PlantScenario, serial_number: str = "SN-0001"
) -> dict:
    """Stage, torque in band, hot-test inside the window, then release."""
    unit = stage_engine_unit(scenario, serial_number)
    record_torque(unit["id"])
    hot_test_unit(unit["id"])
    return release_engine_unit(unit["id"])


def build_and_release_units(scenario: PlantScenario, count: int) -> List[dict]:
    """Fill the order's allocation pool with the requested number of units."""
    return [
        build_and_release_unit(scenario, f"SN-{index:04d}")
        for index in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# Service parts
# ---------------------------------------------------------------------------


def build_service_part(engine_platform_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_part(
            create_service_part_payload(engine_platform_id, **overrides), PLANT_ADMIN
        ),
        201,
    )


def raise_parts_request(service_part_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_parts_request(
            create_parts_request_payload(service_part_id, **overrides),
            headers if headers is not None else CHANNEL_PARTNER,
        ),
        201,
    )


def supersede_service_part(part_id: str, successor_part_id: str) -> dict:
    return get_success_data(
        api_client.supersede_service_part(
            part_id, supersede_service_part_payload(successor_part_id), PLANT_ADMIN
        )
    )


def obsolete_service_part(part_id: str) -> dict:
    return get_success_data(api_client.obsolete_service_part(part_id, PLANT_ADMIN))


# ---------------------------------------------------------------------------
# Composed scenario builders
# ---------------------------------------------------------------------------


def build_production_ready_plant(
    model_overrides: Optional[dict] = None,
    line_overrides: Optional[dict] = None,
) -> PlantScenario:
    """Certified family, released model, running line, supply base, closed run."""
    scenario = build_certified_family_and_platform()
    build_released_model(scenario, model_overrides=model_overrides)
    scenario.line = build_assembly_line(**(line_overrides or {}))
    build_supply_base(scenario)
    scenario.machining_run = build_closed_machining_run(
        scenario.platform_id, scenario.casting_lot_id
    )
    return scenario


def build_released_order_plant(
    order_overrides: Optional[dict] = None,
    model_overrides: Optional[dict] = None,
    line_overrides: Optional[dict] = None,
) -> PlantScenario:
    """A production-ready plant whose build order is released to the floor."""
    scenario = build_production_ready_plant(
        model_overrides=model_overrides, line_overrides=line_overrides
    )
    order = plan_build_order(
        scenario.model_id, scenario.line_id, **(order_overrides or {})
    )
    scenario.build_order = release_build_order(order["id"])
    return scenario


def build_allocatable_plant(
    released_units: int = 2,
    order_overrides: Optional[dict] = None,
    model_overrides: Optional[dict] = None,
) -> PlantScenario:
    """A released order carrying the requested number of released units."""
    scenario = build_released_order_plant(
        order_overrides=order_overrides, model_overrides=model_overrides
    )
    build_and_release_units(scenario, released_units)
    scenario.refresh_build_order()
    return scenario


def build_probation_supplier() -> dict:
    """A supplier pushed onto PROBATION by one clean lot and one rejected lot.

    The first lot is inspected clean at the NORMAL level; the second is a much
    smaller lot whose two defects exceed its acceptance number, which both
    rejects that lot and lifts the supplier's pooled defect rate past the
    probation threshold.
    """
    supplier = build_supplier(
        supplier_code="SUP-CARB",
        name="Kirin Carburetor Works",
        component_category="CARBURETOR",
    )
    clean_lot = build_accepted_lot(supplier["id"], lot_code="CB-001", lot_quantity=800)
    dirty_lot = receive_component_lot(
        supplier["id"], lot_code="CB-002", lot_quantity=200
    )
    rejected_lot = inspect_component_lot(dirty_lot["id"], defects_found=2)
    return {
        "supplier": read_supplier_scorecard(supplier["id"]),
        "supplier_id": supplier["id"],
        "clean_lot": clean_lot,
        "rejected_lot": rejected_lot,
    }


def build_supersession_pair(
    engine_platform_id: str,
    predecessor_stock: int = 0,
    successor_stock: int = 10,
) -> dict:
    """A predecessor part with no stock and a successor holding stock."""
    predecessor = build_service_part(
        engine_platform_id,
        part_number="PN-CARB-KIT-1",
        on_hand_qty=predecessor_stock,
    )
    successor = build_service_part(
        engine_platform_id,
        part_number="PN-CARB-KIT-2",
        on_hand_qty=successor_stock,
    )
    return {"predecessor": predecessor, "successor": successor}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def canonical_clock():
    """Positions the logical clock at the reference plant instant."""
    return set_clock(CANONICAL_CLOCK_UTC)


@pytest.fixture
def draft_family(canonical_clock):
    return build_certification_family()


@pytest.fixture
def family_with_platform(canonical_clock):
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    return PlantScenario(family=read_family(family["id"]), platform=platform)


@pytest.fixture
def certified_platform(canonical_clock):
    return build_certified_family_and_platform()


@pytest.fixture
def released_model(certified_platform):
    return build_released_model(certified_platform)


@pytest.fixture
def production_ready_plant(canonical_clock):
    return build_production_ready_plant()


@pytest.fixture
def released_order_plant(canonical_clock):
    return build_released_order_plant()


@pytest.fixture
def allocatable_plant(canonical_clock):
    return build_allocatable_plant(released_units=2)


@pytest.fixture
def probation_supplier(canonical_clock):
    return build_probation_supplier()


@pytest.fixture
def supersession_pair(certified_platform):
    return build_supersession_pair(certified_platform.platform_id)
