"""Composite setup helpers.

Every test starts against an empty database, so all state is built from scratch
through the public endpoints. The helpers below are layered:

* **Tier 1 — primitives.** One thin wrapper per creating endpoint that validates
  the setup call and returns the created entity.
* **Tier 2 — the base plant.** A configured line with two stations, a supplier,
  a part, a released model variant and its bill-of-materials position, plus the
  optional shift plan that build slots need.
* **Tier 3 — slot and unit lifecycles.** Shortcuts that drive a build slot from
  PLANNED all the way to a shipped production unit, and the quality-gate
  progressions in between.
* **Tier 4 — accumulation targeting.** Helpers that sequence several slots at
  once so option-load windows, fatigue tiers and labour capacity can be pushed
  to a chosen boundary.
* **Tier 5 — terminal and downstream state.** Warranty returns at each
  disposition, engineering changes at each review stage, and the checkpoint
  sweep.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ENGINEERING_LEAD_HEADERS,
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    make_engineering_lead_headers,
    make_supplier_portal_headers,
)
from .types import ChangeDecision, Disposition, TestType

#: The instant every fixture chain pins the logical clock to unless told otherwise.
BASE_CLOCK = "2026-08-03T06:00:00Z"


class Plant:
    """Mutable bag of everything a fixture chain has created so far."""

    def __init__(self):
        self.line: dict = {}
        self.stations: dict = {}          # station_code -> station
        self.supplier: dict = {}
        self.suppliers: dict = {}         # supplier_code -> supplier
        self.parts: dict = {}             # part_number -> part
        self.variants: dict = {}          # model_code -> variant
        self.bom_lines: dict = {}         # (model_code, position_code) -> bom line
        self.shift_plan: dict = {}
        self.slots: dict = {}             # sequence_index -> build slot
        self.units: dict = {}             # sequence_index -> production unit
        self.calls: list = []             # delivery calls in creation order
        self.changes: list = []           # engineering changes in creation order
        self.returns: list = []           # warranty returns in creation order
        self.clock: str = BASE_CLOCK

    # -- convenience accessors ------------------------------------------------
    @property
    def line_id(self) -> str:
        return self.line["id"]

    @property
    def line_code(self) -> str:
        return self.line["line_code"]

    @property
    def st10(self) -> dict:
        return self.stations["ST10"]

    @property
    def st20(self) -> dict:
        return self.stations["ST20"]

    @property
    def st10_id(self) -> str:
        return self.stations["ST10"]["id"]

    @property
    def st20_id(self) -> str:
        return self.stations["ST20"]["id"]

    @property
    def supplier_id(self) -> str:
        return self.supplier["id"]

    @property
    def part(self) -> dict:
        """The plant's canonical part.

        ``base_plant`` names it ``P-DOOR-A``; plants built by another Tier 2
        helper (``module_plant``, for instance) carry a differently coded part,
        so fall back to the first part the chain registered.
        """
        if "P-DOOR-A" in self.parts:
            return self.parts["P-DOOR-A"]
        return next(iter(self.parts.values()))

    @property
    def part_id(self) -> str:
        return self.part["id"]

    @property
    def variant(self) -> dict:
        """The plant's canonical model variant.

        ``base_plant`` names it ``WM-X``; ``module_plant`` and
        ``cut_in_ready_plant`` name theirs ``WM-M``, so fall back to the first
        variant the chain registered.
        """
        if "WM-X" in self.variants:
            return self.variants["WM-X"]
        return next(iter(self.variants.values()))

    @property
    def variant_id(self) -> str:
        return self.variant["id"]

    @property
    def shift_plan_id(self) -> str:
        return self.shift_plan["id"]

    def slot(self, sequence_index: int = 1) -> dict:
        return self.slots[sequence_index]

    def slot_id(self, sequence_index: int = 1) -> str:
        return self.slots[sequence_index]["id"]

    def unit(self, sequence_index: int = 1) -> dict:
        return self.units[sequence_index]

    def unit_id(self, sequence_index: int = 1) -> str:
        return self.units[sequence_index]["id"]


# =============================================================================
# Tier 1 — primitives
# =============================================================================
def set_clock(api, current_utc: str, headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.set_clock(f.clock_payload(current_utc), headers))


def new_line(api, line_code: str = "L1", headers: dict = PLANT_ADMIN_HEADERS,
             **overrides) -> dict:
    return get_success_data(
        api.create_line(f.line_payload(line_code, **overrides), headers)
    )


def new_station(api, line_id: str, station_code: str = "ST10",
                position_index: int = 10, headers: dict = PLANT_ADMIN_HEADERS,
                **overrides) -> dict:
    return get_success_data(
        api.create_station(
            f.station_payload(line_id, station_code, position_index, **overrides),
            headers,
        )
    )


def new_supplier(api, supplier_code: str = "SUP1",
                 name: str = "Hinge and Module Co",
                 headers: dict = PLANT_ADMIN_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_supplier(f.supplier_payload(supplier_code, name, **overrides),
                            headers)
    )


def new_part(api, supplier_id: str, part_number: str = "P-DOOR-A",
             headers: dict = PLANT_ADMIN_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_part(f.part_payload(supplier_id, part_number, **overrides), headers)
    )


def new_model_variant(api, model_code: str = "WM-X", family_code: str = "FAM_A",
                      headers: dict = PLANT_ADMIN_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_model_variant(
            f.model_variant_payload(model_code, family_code, **overrides), headers
        )
    )


def new_bom_line(api, variant_id: str, part_id: str, station_id: str,
                 expected_version: int, bom_position_code: str = "POS-DOOR",
                 headers: dict = PLANT_ADMIN_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_bom_line(
            f.bom_line_payload(variant_id, part_id, station_id, expected_version,
                               bom_position_code, **overrides),
            headers,
        )
    )


def release_variant(api, variant_id: str,
                    headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.release_model_variant(variant_id, headers))


def obsolete_variant(api, variant_id: str,
                     headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.obsolete_model_variant(variant_id, headers))


def line_version(api, line_id: str,
                 headers: dict = PRODUCTION_PLANNER_HEADERS) -> int:
    return get_success_data(api.get_line(line_id, headers))["version"]


def variant_version(api, variant_id: str,
                    headers: dict = PLANT_ADMIN_HEADERS) -> int:
    return get_success_data(api.get_model_variant(variant_id, headers))["version"]


def new_shift_plan(api, line_id: str, expected_version: Optional[int] = None,
                   headers: dict = PRODUCTION_PLANNER_HEADERS, api_for_read=None,
                   **overrides) -> dict:
    if expected_version is None:
        expected_version = line_version(api, line_id)
    return get_success_data(
        api.create_shift_plan(
            f.shift_plan_payload(line_id, expected_version, **overrides), headers
        )
    )


def new_build_slot(api, line_id: str, variant_id: str, sequence_index: int = 1,
                   planned_start: str = "2026-08-03T07:00:00Z",
                   headers: dict = PRODUCTION_PLANNER_HEADERS, **overrides) -> dict:
    return get_success_data(
        api.create_build_slot(
            f.build_slot_payload(line_id, variant_id, sequence_index, planned_start,
                                 **overrides),
            headers,
        )
    )


def new_delivery_call(api, supplier_id: str, part_id: str, station_id: str,
                      window_start: str = "2026-08-03T09:00:00Z",
                      window_end: str = "2026-08-03T10:00:00Z",
                      headers: dict = PRODUCTION_PLANNER_HEADERS,
                      **overrides) -> dict:
    return get_success_data(
        api.create_delivery_call(
            f.delivery_call_payload(supplier_id, part_id, station_id,
                                    window_start, window_end, **overrides),
            headers,
        )
    )


def sequence_slot(api, slot_id: str,
                  headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.sequence_build_slot(slot_id, headers))


def de_sequence_slot(api, slot_id: str,
                     headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.de_sequence_build_slot(slot_id, headers))


def release_slot(api, slot_id: str, headers: dict = LINE_OPERATOR_HEADERS) -> dict:
    """Release a sequenced slot; returns the minted production unit."""
    return get_success_data(api.release_build_slot(slot_id, headers))


def record_test(api, unit_id: str, test_type: str, measured_value: float,
                headers: dict = QUALITY_INSPECTOR_HEADERS) -> dict:
    return get_success_data(
        api.record_quality_test(
            unit_id, f.quality_test_payload(test_type, measured_value), headers
        )
    )


def run_checkpoint(api, line_id: str,
                   headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.run_checkpoint(line_id, headers))


def read_line(api, line_id: str,
              headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.get_line(line_id, headers))


def read_station(api, station_id: str,
                 headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.get_station(station_id, headers))


def read_slot(api, slot_id: str,
              headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.get_build_slot(slot_id, headers))


def read_shift_plan(api, plan_id: str,
                    headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.get_shift_plan(plan_id, headers))


def read_unit(api, unit_id: str,
              headers: dict = QUALITY_INSPECTOR_HEADERS) -> dict:
    return get_success_data(api.get_production_unit(unit_id, headers))


def read_part(api, part_id: str, headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.get_part(part_id, headers))


def read_supplier(api, supplier_id: str,
                  headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.get_supplier(supplier_id, headers))


def read_call(api, call_id: str,
              headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.get_delivery_call(call_id, headers))


def read_variant(api, variant_id: str,
                 headers: dict = PLANT_ADMIN_HEADERS) -> dict:
    return get_success_data(api.get_model_variant(variant_id, headers))


def read_change(api, change_id: str,
                headers: dict = ENGINEERING_LEAD_HEADERS) -> dict:
    return get_success_data(api.get_engineering_change(change_id, headers))


def read_return(api, return_id: str,
                headers: dict = WARRANTY_ANALYST_HEADERS) -> dict:
    return get_success_data(api.get_warranty_return(return_id, headers))


def read_warranty_metrics(api, part_id: str,
                          headers: dict = WARRANTY_ANALYST_HEADERS) -> dict:
    return get_success_data(api.get_warranty_metrics(part_id, headers))


# =============================================================================
# Tier 2 — the base plant
# =============================================================================
def released_variant(api, plant: Plant, model_code: str, part_id: str,
                     station_id: str, bom_position_code: str = "POS-DOOR",
                     qty_per_unit: int = 1, effective_from_sequence: int = 1,
                     family_code: str = "FAM_A",
                     bom_headers: dict = PLANT_ADMIN_HEADERS,
                     **variant_overrides) -> dict:
    """Create a variant, author one bill-of-materials position, release it."""
    variant = new_model_variant(api, model_code, family_code, **variant_overrides)
    bom = new_bom_line(
        api, variant["id"], part_id, station_id, variant["version"],
        bom_position_code, headers=bom_headers,
        qty_per_unit=qty_per_unit, effective_from_sequence=effective_from_sequence,
    )
    release_variant(api, variant["id"])
    plant.variants[model_code] = variant
    plant.bom_lines[(model_code, bom_position_code)] = bom
    return variant


def plain_variant(api, plant: Plant, model_code: str,
                  option_content_points: int, labor_minutes: int,
                  part_id: Optional[str] = None,
                  station_id: Optional[str] = None,
                  qty_per_unit: int = 1,
                  bom_position_code: str = "POS-DOOR",
                  family_code: str = "FAM_A",
                  effective_from_sequence: int = 1,
                  option_codes: Optional[list] = None,
                  functional_cycle_count_required: int = 1,
                  hipot_leakage_ma_limit: float = 0.50,
                  **overrides) -> dict:
    """A released dry variant: no leak test, no energy limit, no water limit.

    Useful wherever the point of the test is the sequencing arithmetic rather
    than the quality gates, since such a variant needs the fewest measurements.
    """
    return released_variant(
        api, plant, model_code, part_id or plant.part_id,
        station_id or plant.st10_id, bom_position_code, qty_per_unit,
        effective_from_sequence, family_code,
        option_codes=option_codes or ["OPT-A"],
        option_content_points=option_content_points,
        labor_minutes=labor_minutes,
        functional_cycle_count_required=functional_cycle_count_required,
        hipot_leakage_ma_limit=hipot_leakage_ma_limit,
        requires_leak_test=f.OMIT,
        leak_limit_ml_per_min=f.OMIT,
        energy_kwh_limit=f.OMIT,
        water_liters_limit=f.OMIT,
        **overrides,
    )


def base_plant(api, clock: str = BASE_CLOCK, line_code: str = "L1",
               st20_cycle_seconds: int = 115,
               supplier_name: str = "Hinge and Module Co",
               sync_window_minutes: int = 30,
               bom_qty_per_unit: int = 2,
               line_side_max_units: int = 24,
               bom_headers: dict = PLANT_ADMIN_HEADERS,
               line_overrides: Optional[dict] = None,
               variant_overrides: Optional[dict] = None) -> Plant:
    """Clock, line, two stations, supplier, part, released variant with a BOM.

    Stations ST10 (position 10) and ST20 (position 20) each hold forty
    presentation slots, so the line's total is eighty.
    """
    plant = Plant()
    plant.clock = clock
    set_clock(api, clock)
    plant.line = new_line(api, line_code, **(line_overrides or {}))
    plant.stations["ST10"] = new_station(
        api, plant.line_id, "ST10", 10,
        presentation_slot_capacity=40, station_cycle_seconds=110,
    )
    plant.stations["ST20"] = new_station(
        api, plant.line_id, "ST20", 20,
        presentation_slot_capacity=40, station_cycle_seconds=st20_cycle_seconds,
    )
    plant.supplier = new_supplier(
        api, "SUP1", supplier_name, sync_window_minutes=sync_window_minutes
    )
    plant.suppliers["SUP1"] = plant.supplier
    plant.parts["P-DOOR-A"] = new_part(
        api, plant.supplier_id, "P-DOOR-A",
        is_sequenced_module=False, line_side_max_units=line_side_max_units,
    )
    released_variant(
        api, plant, "WM-X", plant.part_id, plant.st10_id,
        bom_position_code="POS-DOOR", qty_per_unit=bom_qty_per_unit,
        bom_headers=bom_headers, **(variant_overrides or {}),
    )
    return plant


def base_plant_with_shift(api, planned_headcount: int = 20, **kwargs) -> Plant:
    """The base plant plus shift plan A covering 06:00 to 14:00."""
    plant = base_plant(api, **kwargs)
    plant.shift_plan = new_shift_plan(
        api, plant.line_id, planned_headcount=planned_headcount
    )
    return plant


def module_plant(api, clock: str = BASE_CLOCK, planned_headcount: int = 20,
                 with_shift: bool = True,
                 bom_headers: dict = PLANT_ADMIN_HEADERS) -> Plant:
    """A plant whose variant WM-M consumes a sequenced module, P-MOD-1.

    P-MOD-1 has a line-side maximum of one unit, so without a covering delivery
    call it would swamp any station; with one it charges nothing.
    """
    plant = Plant()
    plant.clock = clock
    set_clock(api, clock)
    plant.line = new_line(api, "L1")
    plant.stations["ST10"] = new_station(
        api, plant.line_id, "ST10", 10,
        presentation_slot_capacity=40, station_cycle_seconds=110,
    )
    plant.stations["ST20"] = new_station(
        api, plant.line_id, "ST20", 20,
        presentation_slot_capacity=40, station_cycle_seconds=110,
    )
    plant.supplier = new_supplier(api, "SUP1", "Sync Modules GmbH",
                                  sync_window_minutes=45)
    plant.suppliers["SUP1"] = plant.supplier
    plant.parts["P-MOD-1"] = new_part(
        api, plant.supplier_id, "P-MOD-1",
        is_sequenced_module=True, line_side_max_units=1,
    )
    released_variant(
        api, plant, "WM-M", plant.parts["P-MOD-1"]["id"], plant.st10_id,
        bom_position_code="POS-MOD", qty_per_unit=1, bom_headers=bom_headers,
        option_content_points=1, labor_minutes=100,
        functional_cycle_count_required=1, requires_leak_test=False,
        hipot_leakage_ma_limit=0.50,
        leak_limit_ml_per_min=f.OMIT, water_liters_limit=f.OMIT,
        energy_kwh_limit=f.OMIT, option_codes=["OPT-MOD"],
    )
    if with_shift:
        plant.shift_plan = new_shift_plan(
            api, plant.line_id, planned_headcount=planned_headcount
        )
    return plant


def cut_in_ready_plant(api, clock: str = BASE_CLOCK,
                       stopped_at: str = "2026-08-03T08:00:00Z") -> Plant:
    """Everything a cut-in needs: an APPROVED change and a stopped line.

    Variant WM-M carries two positions — the sequenced module P-MOD-1 at ST10 and
    two door panels at ST20 — and build slot 1 is sequenced against a delivery
    call that covers it, so the module charges nothing and the door charges two
    presentation units. The change replaces the module with P-MOD-2 from sequence
    index 5, was submitted by one engineer and approved by another, and the line
    has been stopped so the cut-in ladder can be walked.
    """
    plant = Plant()
    plant.clock = clock
    set_clock(api, clock)
    plant.line = new_line(api, "L1")
    plant.stations["ST10"] = new_station(
        api, plant.line_id, "ST10", 10,
        presentation_slot_capacity=40, station_cycle_seconds=110,
    )
    plant.stations["ST20"] = new_station(
        api, plant.line_id, "ST20", 20,
        presentation_slot_capacity=40, station_cycle_seconds=110,
    )
    plant.supplier = new_supplier(api, "SUP1", "Sync Modules GmbH",
                                  sync_window_minutes=45)
    plant.suppliers["SUP1"] = plant.supplier
    plant.parts["P-MOD-1"] = new_part(
        api, plant.supplier_id, "P-MOD-1",
        is_sequenced_module=True, line_side_max_units=1,
    )
    plant.parts["P-MOD-2"] = new_part(
        api, plant.supplier_id, "P-MOD-2",
        is_sequenced_module=True, line_side_max_units=1,
    )
    plant.parts["P-DOOR-A"] = new_part(
        api, plant.supplier_id, "P-DOOR-A",
        is_sequenced_module=False, line_side_max_units=24,
    )
    variant = new_model_variant(
        api, "WM-M", "FAM_A", option_codes=["OPT-MOD"], option_content_points=1,
        labor_minutes=100, functional_cycle_count_required=1,
        requires_leak_test=False, hipot_leakage_ma_limit=0.50,
        leak_limit_ml_per_min=f.OMIT, energy_kwh_limit=f.OMIT,
        water_liters_limit=f.OMIT,
    )
    plant.variants["WM-M"] = variant
    plant.bom_lines[("WM-M", "POS-MOD")] = new_bom_line(
        api, variant["id"], plant.parts["P-MOD-1"]["id"], plant.st10_id,
        variant["version"], "POS-MOD", qty_per_unit=1, effective_from_sequence=1,
    )
    plant.bom_lines[("WM-M", "POS-DOOR")] = new_bom_line(
        api, variant["id"], plant.parts["P-DOOR-A"]["id"], plant.st20_id,
        variant_version(api, variant["id"]), "POS-DOOR",
        qty_per_unit=2, effective_from_sequence=1,
    )
    release_variant(api, variant["id"])
    plant.shift_plan = new_shift_plan(api, plant.line_id, planned_headcount=20)
    plant.calls.append(new_delivery_call(
        api, plant.supplier_id, plant.parts["P-MOD-1"]["id"], plant.st10_id,
        "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z", sequenced_qty=1,
    ))
    sequenced_slot(api, plant, 1, "2026-08-03T09:30:00Z", variant["id"])
    alice = make_engineering_lead_headers("eng-alice")
    bob = make_engineering_lead_headers("eng-bob")
    approved_change(
        api, plant, alice, bob,
        affected_part_id=plant.parts["P-MOD-1"]["id"], variant_id=variant["id"],
        bom_position_code="POS-MOD", cut_in_sequence_index=5,
        replacement_part_id=plant.parts["P-MOD-2"]["id"],
    )
    stop_line(api, plant.line_id, reason="engineering change cut-in")
    set_clock(api, stopped_at)
    plant.clock = stopped_at
    return plant


def add_fam_b_variant(api, plant: Plant, model_code: str = "WM-Y",
                      station_id: Optional[str] = None) -> dict:
    """A released variant in the other family, so a changeover is required."""
    return released_variant(
        api, plant, model_code, plant.part_id, station_id or plant.st20_id,
        bom_position_code="POS-DOOR", qty_per_unit=1, family_code="FAM_B",
        option_codes=["OPT-ECO"], option_content_points=2, labor_minutes=145,
        functional_cycle_count_required=2, requires_leak_test=False,
        hipot_leakage_ma_limit=0.60, energy_kwh_limit=300.00,
        leak_limit_ml_per_min=f.OMIT, water_liters_limit=f.OMIT,
    )


# =============================================================================
# Tier 3 — slot and unit lifecycles
# =============================================================================
def planned_slot(api, plant: Plant, sequence_index: int = 1,
                 planned_start: str = "2026-08-03T07:00:00Z",
                 variant_id: Optional[str] = None,
                 line_id: Optional[str] = None) -> dict:
    slot = new_build_slot(
        api, line_id or plant.line_id, variant_id or plant.variant_id,
        sequence_index, planned_start,
    )
    plant.slots[sequence_index] = slot
    return slot


def sequenced_slot(api, plant: Plant, sequence_index: int = 1,
                   planned_start: str = "2026-08-03T07:00:00Z",
                   variant_id: Optional[str] = None,
                   line_id: Optional[str] = None) -> dict:
    planned_slot(api, plant, sequence_index, planned_start, variant_id, line_id)
    slot = sequence_slot(api, plant.slot_id(sequence_index))
    plant.slots[sequence_index] = slot
    return slot


def released_unit(api, plant: Plant, sequence_index: int = 1,
                  planned_start: str = "2026-08-03T07:00:00Z",
                  variant_id: Optional[str] = None,
                  line_id: Optional[str] = None) -> dict:
    """Sequence a fresh slot and release it, returning the minted unit."""
    sequenced_slot(api, plant, sequence_index, planned_start, variant_id, line_id)
    unit = release_slot(api, plant.slot_id(sequence_index))
    plant.units[sequence_index] = unit
    return unit


def pass_safety_test(api, unit_id: str, measured_value: float = 0.30) -> dict:
    return record_test(api, unit_id, TestType.ELECTRICAL_SAFETY.value, measured_value)


def drive_unit_to_gated(api, unit_id: str, safety: float = 0.30,
                        cycles: float = 3, leak: Optional[float] = 1.10) -> None:
    """Walk the quality gates in the only order they are accepted in.

    Electrical safety first, then the functional cycle test, then — for a
    variant that requires it — the leak test.
    """
    pass_safety_test(api, unit_id, safety)
    record_test(api, unit_id, TestType.FUNCTIONAL_CYCLE.value, cycles)
    if leak is not None:
        record_test(api, unit_id, TestType.LEAK.value, leak)


def record_consumption(api, unit_id: str, energy: Optional[list] = None,
                       water: Optional[list] = None) -> None:
    """Record the consumption measurements the efficiency index averages."""
    for value in energy if energy is not None else [380.00]:
        record_test(api, unit_id, TestType.ENERGY.value, value)
    for value in water if water is not None else [184.00]:
        record_test(api, unit_id, TestType.WATER.value, value)


def certify(api, unit_id: str) -> dict:
    return get_success_data(api.certify_unit(unit_id, QUALITY_INSPECTOR_HEADERS))


def complete_assembly(api, unit_id: str) -> dict:
    return get_success_data(api.complete_assembly(unit_id, LINE_OPERATOR_HEADERS))


def ship(api, unit_id: str) -> dict:
    return get_success_data(api.ship_unit(unit_id, LINE_OPERATOR_HEADERS))


def gated_unit(api, plant: Plant, sequence_index: int = 1,
               planned_start: str = "2026-08-03T07:00:00Z",
               safety: float = 0.30, cycles: float = 3,
               leak: Optional[float] = 1.10,
               energy: Optional[list] = None,
               water: Optional[list] = None) -> dict:
    """A unit whose quality dimension has reached GATED, with consumption data.

    Pass ``energy=[]`` and ``water=[]`` to stop short of recording consumption.
    """
    unit = released_unit(api, plant, sequence_index, planned_start)
    drive_unit_to_gated(api, unit["id"], safety, cycles, leak)
    record_consumption(api, unit["id"], energy, water)
    plant.units[sequence_index] = read_unit(api, unit["id"])
    return plant.units[sequence_index]


def shipped_unit(api, plant: Plant, sequence_index: int = 1,
                 planned_start: str = "2026-08-03T07:00:00Z",
                 safety: float = 0.30, cycles: float = 3,
                 leak: Optional[float] = 1.10,
                 energy: Optional[list] = None,
                 water: Optional[list] = None) -> dict:
    """A unit certified, assembled and shipped — the warranty entry condition."""
    unit = gated_unit(api, plant, sequence_index, planned_start,
                      safety, cycles, leak, energy, water)
    certify(api, unit["id"])
    complete_assembly(api, unit["id"])
    shipped = ship(api, unit["id"])
    plant.units[sequence_index] = shipped
    return shipped


def quarantined_unit(api, plant: Plant, sequence_index: int = 1,
                     planned_start: str = "2026-08-03T07:00:00Z",
                     failing_safety_value: float = 0.60) -> dict:
    """A unit whose failed safety test has quarantined both of its dimensions."""
    unit = released_unit(api, plant, sequence_index, planned_start)
    record_test(api, unit["id"], TestType.ELECTRICAL_SAFETY.value,
                failing_safety_value)
    plant.units[sequence_index] = read_unit(api, unit["id"])
    return plant.units[sequence_index]


# =============================================================================
# Tier 4 — accumulation targeting
# =============================================================================
def sequence_many(api, plant: Plant, specs: list) -> list:
    """Create and sequence a run of slots.

    ``specs`` is a list of ``(sequence_index, planned_start, variant_id)``
    triples; the slots are created and sequenced in the order given.
    """
    slots = []
    for sequence_index, planned_start, variant_id in specs:
        slots.append(
            sequenced_slot(api, plant, sequence_index, planned_start, variant_id)
        )
    return slots


def plan_many(api, plant: Plant, specs: list) -> list:
    """Create a run of slots and leave every one of them PLANNED."""
    slots = []
    for sequence_index, planned_start, variant_id in specs:
        slots.append(
            planned_slot(api, plant, sequence_index, planned_start, variant_id)
        )
    return slots


def missed_calls_plant(api, plant: Plant, windows: list,
                       part_id: Optional[str] = None,
                       station_id: Optional[str] = None) -> list:
    """Book a run of delivery calls that a later checkpoint will sweep as missed.

    ``windows`` is a list of ``(window_start, window_end)`` pairs.
    """
    calls = []
    for window_start, window_end in windows:
        call = new_delivery_call(
            api, plant.supplier_id,
            part_id or next(iter(plant.parts.values()))["id"],
            station_id or plant.st10_id,
            window_start, window_end, sequenced_qty=1,
        )
        plant.calls.append(call)
        calls.append(call)
    return calls


# =============================================================================
# Tier 5 — downstream and terminal state
# =============================================================================
def stop_line(api, line_id: str, reason: str = "ENGINEERING_CHANGE",
              headers: dict = LINE_OPERATOR_HEADERS) -> dict:
    return get_success_data(
        api.stop_line(line_id, f.stop_line_payload(reason), headers)
    )


def start_line(api, line_id: str, to_family_code: Optional[str] = None,
               headers: dict = LINE_OPERATOR_HEADERS) -> dict:
    return get_success_data(
        api.start_line(line_id, f.start_line_payload(to_family_code), headers)
    )


def draft_change(api, plant: Plant, affected_part_id: Optional[str] = None,
                 variant_id: Optional[str] = None,
                 bom_position_code: str = "POS-DOOR",
                 cut_in_sequence_index: int = 5,
                 headers: dict = ENGINEERING_LEAD_HEADERS,
                 **overrides) -> dict:
    change = get_success_data(
        api.create_engineering_change(
            f.engineering_change_payload(
                variant_id or plant.variant_id,
                affected_part_id or plant.part_id,
                plant.line_id, bom_position_code, cut_in_sequence_index,
                **overrides,
            ),
            headers,
        )
    )
    plant.changes.append(change)
    return change


def submitted_change(api, plant: Plant, submitter_headers: dict,
                     **kwargs) -> dict:
    change = draft_change(api, plant, headers=submitter_headers, **kwargs)
    return get_success_data(
        api.submit_engineering_change(change["id"], submitter_headers)
    )


def change_under_review(api, plant: Plant, submitter_headers: dict,
                        **kwargs) -> dict:
    change = submitted_change(api, plant, submitter_headers, **kwargs)
    return get_success_data(
        api.start_review_engineering_change(change["id"], submitter_headers)
    )


def approved_change(api, plant: Plant, submitter_headers: dict,
                    decider_headers: dict, **kwargs) -> dict:
    change = change_under_review(api, plant, submitter_headers, **kwargs)
    return get_success_data(
        api.decide_engineering_change(
            change["id"], f.decide_payload(ChangeDecision.APPROVE.value,
                                           "supplier qualified"),
            decider_headers,
        )
    )


def received_return(api, plant: Plant, unit_id: str,
                    failure_code: str = "F-DOOR-SEAL",
                    field_hours: float = 500,
                    returned_at: Optional[str] = None) -> dict:
    overrides = {} if returned_at is None else {"returned_at": returned_at}
    wr = get_success_data(
        api.create_warranty_return(
            f.warranty_return_payload(unit_id, failure_code, field_hours,
                                      **overrides),
            WARRANTY_ANALYST_HEADERS,
        )
    )
    plant.returns.append(wr)
    return wr


def torn_down_return(api, plant: Plant, unit_id: str, **kwargs) -> dict:
    wr = received_return(api, plant, unit_id, **kwargs)
    return get_success_data(
        api.teardown_warranty_return(wr["id"], WARRANTY_ANALYST_HEADERS)
    )


def analyzed_return(api, plant: Plant, unit_id: str, disposition: str,
                    root_cause_part_id: Optional[str] = None, **kwargs) -> dict:
    wr = torn_down_return(api, plant, unit_id, **kwargs)
    return get_success_data(
        api.analyze_warranty_return(
            wr["id"], f.analyze_payload(disposition, root_cause_part_id),
            WARRANTY_ANALYST_HEADERS,
        )
    )


def design_defect_return(api, plant: Plant, unit_id: str, **kwargs) -> dict:
    return analyzed_return(api, plant, unit_id, Disposition.DESIGN_DEFECT.value,
                           plant.part_id, **kwargs)


def supplier_defect_return(api, plant: Plant, unit_id: str, **kwargs) -> dict:
    return analyzed_return(api, plant, unit_id, Disposition.SUPPLIER_DEFECT.value,
                           plant.part_id, **kwargs)


def record_arrival(api, call_id: str, supplier_id: str, arrived_at: str) -> dict:
    return get_success_data(
        api.record_arrival(call_id, f.record_arrival_payload(arrived_at),
                           make_supplier_portal_headers(supplier_id))
    )


def cancel_call(api, call_id: str,
                headers: dict = PRODUCTION_PLANNER_HEADERS) -> dict:
    return get_success_data(api.cancel_delivery_call(call_id, headers))
