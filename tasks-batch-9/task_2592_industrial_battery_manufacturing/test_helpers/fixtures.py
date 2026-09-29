"""Composite fixtures: the plant world every test starts from.

The harness restarts the API before each test, so every fixture builds its
preconditions from an empty database through the public API only. `World`
carries the identifiers and the per-actor headers a test needs, plus the
multi-step shortcuts (advance a lot, certify an assembly, release a lot, ship a
unit) that would otherwise be copied into dozens of tests.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import BatteryApiClient
from .test_users import (
    FLEET_ENGINEER_HEADERS,
    PLANT_ADMIN_HEADERS,
    WARRANTY_ADMIN_HEADERS,
    make_design_engineer_headers,
    make_production_supervisor_headers,
    make_quality_inspector_headers,
    make_safety_officer_headers,
)


def _data(response, expected_status: Optional[int] = None) -> Dict[str, Any]:
    """Unwrap a successful envelope, failing loudly when setup breaks."""
    if expected_status is not None:
        assert response.status_code == expected_status, (
            f"setup call returned {response.status_code}, expected "
            f"{expected_status}: {response.text}"
        )
    else:
        assert response.status_code in (
            200,
            201,
        ), f"setup call failed with {response.status_code}: {response.text}"
    return get_success_data(response)


class World:
    """The plant, its people, its equipment and one approved design."""

    def __init__(self, api: BatteryApiClient, plant_overrides: Optional[Dict] = None):
        self.api = api
        self.admin = PLANT_ADMIN_HEADERS
        self.fleet = FLEET_ENGINEER_HEADERS
        self.warranty = WARRANTY_ADMIN_HEADERS
        self.now = C.CLOCK_START
        self.set_clock(C.CLOCK_START)
        self.plant = _data(
            api.create_plant(F.plant_payload(**(plant_overrides or {})), self.admin), 201
        )
        self.plant_id = self.plant["id"]

    # --- clock -------------------------------------------------------------
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        result = _data(self.api.set_clock(current_utc, PLANT_ADMIN_HEADERS), 200)
        self.now = current_utc
        return result

    # --- people ------------------------------------------------------------
    def add_worker(self, full_name: str, job_class: str, **overrides: Any) -> str:
        worker = _data(
            self.api.create_worker(
                F.worker_payload(self.plant_id, full_name, job_class, **overrides),
                self.admin,
            ),
            201,
        )
        return worker["id"]

    def add_core_staff(self) -> None:
        """Two engineers, a supervisor, an inspector and a safety officer."""
        self.eng_a_id = self.add_worker("Ada Engineer", "ENGINEER")
        self.eng_b_id = self.add_worker("Ben Engineer", "ENGINEER")
        self.sup_a_id = self.add_worker("Cara Supervisor", "PRODUCTION")
        self.qa_a_id = self.add_worker("Dana Quality", "QUALITY")
        self.saf_a_id = self.add_worker("Sam Safety", "SAFETY")
        self.eng_a = make_design_engineer_headers(self.eng_a_id)
        self.eng_b = make_design_engineer_headers(self.eng_b_id)
        self.sup_a = make_production_supervisor_headers(self.sup_a_id)
        self.qa_a = make_quality_inspector_headers(self.qa_a_id)
        self.saf_a = make_safety_officer_headers(self.saf_a_id)

    def add_second_inspector(self) -> str:
        """A second inspector, needed wherever segregation of duties applies."""
        self.qa_b_id = self.add_worker("Eli Quality", "QUALITY")
        self.qa_b = make_quality_inspector_headers(self.qa_b_id)
        return self.qa_b_id

    # --- designs -----------------------------------------------------------
    def draft_design(self, payload: Dict[str, Any], headers=None) -> Dict[str, Any]:
        return _data(
            self.api.create_cell_design(payload, headers or self.eng_a), 201
        )

    def approve_design(self, design_id: str) -> Dict[str, Any]:
        """Submit as the author and approve as a different engineer."""
        _data(
            self.api.review_cell_design(
                design_id, F.review_action_payload("SUBMIT"), self.eng_a
            ),
            200,
        )
        return _data(
            self.api.review_cell_design(
                design_id, F.review_action_payload("APPROVE"), self.eng_b
            ),
            200,
        )

    def approved_lead_design(self, code: str = C.LEAD_DESIGN_CODE, **overrides) -> str:
        design = self.draft_design(F.lead_design_payload(code, **overrides))
        self.approve_design(design["id"])
        return design["id"]

    def approved_lithium_design(self, code: str = "CD-LFP-900", **overrides) -> str:
        design = self.draft_design(F.lithium_design_payload(code, **overrides))
        self.approve_design(design["id"])
        return design["id"]

    # --- equipment ---------------------------------------------------------
    def add_bay(self, bay_code: str = C.BAY_CODE, **overrides: Any) -> str:
        bay = _data(
            self.api.create_formation_bay(
                F.formation_bay_payload(self.plant_id, bay_code, **overrides), self.admin
            ),
            201,
        )
        return bay["id"]

    def add_chamber(self, chamber_code: str = C.CHAMBER_CODE, **overrides: Any) -> str:
        chamber = _data(
            self.api.create_test_chamber(
                F.test_chamber_payload(self.plant_id, chamber_code, **overrides),
                self.admin,
            ),
            201,
        )
        return chamber["id"]

    # --- reads -------------------------------------------------------------
    def read_plant(self) -> Dict[str, Any]:
        return _data(self.api.get_plant(self.plant_id, self.admin), 200)

    def read_lot(self, lot_id: str) -> Dict[str, Any]:
        return _data(self.api.get_production_lot(lot_id, self.admin), 200)

    def read_assembly(self, assembly_id: str) -> Dict[str, Any]:
        return _data(self.api.get_battery_assembly(assembly_id, self.admin), 200)

    def read_run(self, run_id: str) -> Dict[str, Any]:
        return _data(self.api.get_formation_run(run_id, self.admin), 200)

    def read_test(self, test_id: str) -> Dict[str, Any]:
        return _data(self.api.get_capacity_test(test_id, self.admin), 200)

    def read_unit(self, unit_id: str) -> Dict[str, Any]:
        return _data(self.api.get_battery_unit(unit_id, self.admin), 200)

    def read_worker(self, worker_id: str) -> Dict[str, Any]:
        return _data(self.api.get_worker(worker_id, self.admin), 200)

    def read_ledger(self) -> Dict[str, Any]:
        return _data(self.api.get_emission_ledger(self.plant_id, self.admin), 200)

    def read_mass_balance(self) -> Dict[str, Any]:
        return _data(self.api.get_lead_mass_balance(self.plant_id, self.admin), 200)

    # --- lots --------------------------------------------------------------
    def open_lot(
        self,
        lot_code: str = "LOT-A",
        quantity: int = 9,
        design_id: Optional[str] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return _data(
            self.api.create_production_lot(
                F.production_lot_payload(
                    self.plant_id,
                    design_id or self.design_id,
                    lot_code,
                    quantity,
                    **overrides,
                ),
                self.sup_a,
            ),
            201,
        )

    def formation_evidence_for(self, lot_id: str) -> Dict[str, Any]:
        """Give a lot in FORMATION the completed run that ASSEMBLY entry requires.

        Entering `ASSEMBLY` requires at least one formation run of the lot in
        `COMPLETED`, none still `SCHEDULED` or `CHARGING`, and a
        `failed_formation_count` of exactly 0, so the ladder cannot be walked
        past `FORMATION` on paperwork alone. The run is booked on a bay this
        helper commissions for itself, so a test's own bay is never occupied,
        and the logical clock is restored afterwards so the manoeuvre is
        invisible to the caller.
        """
        bay_id = getattr(self, "_ladder_bay_id", None)
        if bay_id is None:
            # A 0.01 kW rectifier over one off-peak hour caps the nameplate
            # estimate at 0.01 kWh, so the evidence run reserves and consumes a
            # few hundredths of a gram and prices at zero cents. The ladder
            # therefore stays affordable inside a plant whose emission permit is
            # deliberately tiny, and it perturbs no ledger a test asserts on.
            bay_id = self.add_bay("BAYLADDER", rated_power_kw=0.01)
            self._ladder_bay_id = bay_id
        resume_at = self.now
        run = self.schedule_run(
            lot_id, bay_id, "2026-09-02T06:00:00Z", "2026-09-02T07:00:00Z"
        )
        self.set_clock("2026-09-02T06:00:00Z")
        self.start_run(run["id"])
        self.set_clock("2026-09-02T07:00:00Z")
        completed = self.complete_run(run["id"], metered_energy_kwh=0.01)
        if resume_at != self.now:
            self.set_clock(resume_at)
        return completed

    def advance_lot_to(self, lot_id: str, to_state: str) -> Dict[str, Any]:
        """Walk the single-step ladder from the lot's current stage."""
        ladder = ["PLANNED", "PLATE_PRODUCTION", "FORMATION", "ASSEMBLY"]
        current = self.read_lot(lot_id)["process_state"]
        target_index = ladder.index(to_state)
        result = None
        for stage in ladder[ladder.index(current) + 1 : target_index + 1]:
            if stage == "ASSEMBLY":
                self.formation_evidence_for(lot_id)
            result = _data(
                self.api.advance_lot(lot_id, F.advance_payload(stage), self.sup_a), 200
            )
        return result or self.read_lot(lot_id)

    def lot_in_state(
        self,
        to_state: str,
        lot_code: str = "LOT-A",
        quantity: int = 9,
        design_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        lot = self.open_lot(lot_code, quantity, design_id)
        if to_state == "PLANNED":
            return lot
        return self.advance_lot_to(lot["id"], to_state)

    def hold_lot(self, lot_id: str) -> Dict[str, Any]:
        return _data(
            self.api.env_hold_lot(
                lot_id,
                F.env_hold_payload("HOLD", C.HOLD_REASON_OPERATOR),
                self.saf_a,
            ),
            200,
        )

    def release_hold(self, lot_id: str) -> Dict[str, Any]:
        return _data(
            self.api.env_hold_lot(lot_id, F.env_hold_payload("RELEASE_HOLD"), self.saf_a),
            200,
        )

    # --- assemblies --------------------------------------------------------
    def add_assembly(
        self, lot_id: str, serial_number: str, module_count: int = 6, **overrides: Any
    ) -> Dict[str, Any]:
        return _data(
            self.api.create_battery_assembly(
                F.assembly_payload(lot_id, serial_number, module_count, **overrides),
                self.sup_a,
            ),
            201,
        )

    def certify_assembly(
        self,
        lot_id: str,
        serial_number: str,
        module_count: int = 6,
        torque_spec_nm: float = 20.00,
        ir_min_megaohm: float = 1.00,
    ) -> Dict[str, Any]:
        """Create an assembly and pass both verification axes."""
        assembly = self.add_assembly(
            lot_id,
            serial_number,
            module_count,
            torque_spec_nm=torque_spec_nm,
            ir_min_megaohm=ir_min_megaohm,
        )
        _data(
            self.api.record_verification(
                assembly["id"],
                F.torque_verification_payload(torque_spec_nm, 2 * module_count),
                self.qa_a,
            ),
            200,
        )
        return _data(
            self.api.record_verification(
                assembly["id"],
                F.insulation_verification_payload(ir_min_megaohm + 1.50),
                self.qa_a,
            ),
            200,
        )

    # --- formation runs ----------------------------------------------------
    def schedule_run(
        self,
        lot_id: str,
        bay_id: str,
        scheduled_start_at: str = "2026-09-02T06:00:00Z",
        scheduled_end_at: str = "2026-09-02T12:00:00Z",
    ) -> Dict[str, Any]:
        return _data(
            self.api.create_formation_run(
                F.formation_run_payload(
                    lot_id, bay_id, scheduled_start_at, scheduled_end_at
                ),
                self.sup_a,
            ),
            201,
        )

    def start_run(self, run_id: str) -> Dict[str, Any]:
        return _data(self.api.start_formation_run(run_id, self.sup_a), 200)

    def complete_run(
        self,
        run_id: str,
        metered_energy_kwh: float = 100.00,
        formation_capacity_pct: float = 95.00,
        actual_end_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        return _data(
            self.api.complete_formation_run(
                run_id,
                F.complete_run_payload(
                    metered_energy_kwh, formation_capacity_pct, actual_end_at
                ),
                self.sup_a,
            ),
            200,
        )

    def completed_formation_for(self, lot_id: str, bay_id: str) -> Dict[str, Any]:
        """Schedule, start and complete one passing formation run on a lot."""
        run = self.schedule_run(lot_id, bay_id)
        self.set_clock("2026-09-02T06:00:00Z")
        self.start_run(run["id"])
        self.set_clock("2026-09-02T12:00:00Z")
        return self.complete_run(run["id"])

    # --- sampling, testing, disposition -----------------------------------
    def draw_plan(self, lot_id: str, plan_reason: str = "initial acceptance plan"):
        lot = self.read_lot(lot_id)
        return _data(
            self.api.draw_sampling_plan(
                lot_id,
                F.sampling_plan_payload(lot["version"], plan_reason=plan_reason),
                self.qa_a,
            ),
            201,
        )

    def schedule_test(
        self,
        assembly_id: str,
        chamber_id: str,
        scheduled_start_at: str,
        scheduled_end_at: str,
        test_type: str = C.TEST_TYPE_CAPACITY,
        draw_kw: float = 3.00,
    ) -> Dict[str, Any]:
        return _data(
            self.api.create_capacity_test(
                F.capacity_test_payload(
                    assembly_id,
                    chamber_id,
                    scheduled_start_at,
                    scheduled_end_at,
                    test_type,
                    draw_kw,
                ),
                self.qa_a,
            ),
            201,
        )

    def record_capacity(
        self, test_id: str, measured_capacity_ah: float, headers=None
    ) -> Dict[str, Any]:
        return _data(
            self.api.record_test_result(
                test_id,
                F.capacity_result_payload(measured_capacity_ah),
                headers or self.qa_a,
            ),
            200,
        )

    def record_cycle_life(
        self,
        test_id: str,
        measured_capacity_ah: float,
        cycles_completed: int,
        headers=None,
    ) -> Dict[str, Any]:
        return _data(
            self.api.record_test_result(
                test_id,
                F.cycle_life_result_payload(measured_capacity_ah, cycles_completed),
                headers or self.qa_a,
            ),
            200,
        )

    def disposition(
        self, lot_id: str, action: str, headers=None, note: str = "acceptance met"
    ) -> Dict[str, Any]:
        return _data(
            self.api.disposition_lot(
                lot_id, F.disposition_payload(action, note), headers or self.qa_a
            ),
            200,
        )

    def pass_three_tests(
        self, lot_id: str, assembly_id: str, chamber_id: str
    ) -> List[Dict[str, Any]]:
        """Two passing capacity tests and one passing cycle-life test.

        The three windows are adjacent, so the chamber's aggregate draw never
        overlaps, and the clock is moved past the last window before results are
        recorded.
        """
        t1 = self.schedule_test(
            assembly_id, chamber_id, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z"
        )
        t2 = self.schedule_test(
            assembly_id, chamber_id, "2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z"
        )
        t3 = self.schedule_test(
            assembly_id,
            chamber_id,
            "2026-09-03T12:00:00Z",
            "2026-09-03T14:00:00Z",
            test_type=C.TEST_TYPE_CYCLE_LIFE,
        )
        self.set_clock("2026-09-03T14:00:00Z")
        self.record_capacity(t1["id"], 441.8)
        self.record_capacity(t2["id"], 442.1)
        self.record_cycle_life(t3["id"], 372.0, 1350)
        return [t1, t2, t3]

    def released_lot(
        self, lot_code: str = "LOT-L", quantity: int = 9, chamber_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Full acceptance chain: a lot of quantity 9 released on a 3 / 0 plan.

        The three results are recorded by one inspector and the release is issued
        by a second one, because the releasing inspector may not be the one who
        recorded the last result.
        """
        if not hasattr(self, "qa_b"):
            self.add_second_inspector()
        chamber_id = chamber_id or self.add_chamber()
        lot = self.lot_in_state("ASSEMBLY", lot_code, quantity)
        assembly = self.certify_assembly(lot["id"], f"ASM-{lot_code}-1")
        self.draw_plan(lot["id"])
        self.pass_three_tests(lot["id"], assembly["id"], chamber_id)
        return self.disposition(lot["id"], C.DISPOSITION_RELEASE, self.qa_b)

    # --- units -------------------------------------------------------------
    def ship_unit(
        self, lot_id: str, serial_number: str, **overrides: Any
    ) -> Dict[str, Any]:
        return _data(
            self.api.create_battery_unit(
                F.battery_unit_payload(lot_id, serial_number, **overrides), self.sup_a
            ),
            201,
        )

    def open_core_return(self, unit_id: str, manifest: str) -> Dict[str, Any]:
        return _data(
            self.api.open_core_return(
                unit_id, F.core_return_payload(manifest), self.warranty
            ),
            200,
        )

    def core_transition(
        self, unit_id: str, action: str, received_lead_kg: Optional[float] = None
    ) -> Dict[str, Any]:
        return _data(
            self.api.transition_core_return(
                unit_id,
                F.core_transition_payload(action, received_lead_kg),
                self.warranty,
            ),
            200,
        )

    # --- exposure ----------------------------------------------------------
    def record_blood(self, worker_id: str, sampled_at: str, level: float):
        return _data(
            self.api.create_exposure_sample(
                worker_id, F.blood_sample_payload(sampled_at, level), self.saf_a
            ),
            201,
        )

    def record_air(
        self, worker_id: str, sampled_at: str, concentration: float, minutes: int
    ):
        return _data(
            self.api.create_exposure_sample(
                worker_id,
                F.air_sample_payload(sampled_at, concentration, minutes),
                self.saf_a,
            ),
            201,
        )

    def clear_worker(self, worker_id: str, note: str = "fit for duty"):
        return _data(
            self.api.grant_medical_clearance(
                worker_id, F.clearance_payload(note), self.saf_a
            ),
            200,
        )


# --- pytest fixtures -------------------------------------------------------
@pytest.fixture
def api() -> BatteryApiClient:
    """A fresh client against the API under test."""
    return BatteryApiClient()


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return PLANT_ADMIN_HEADERS


@pytest.fixture
def warranty_headers() -> Dict[str, str]:
    return WARRANTY_ADMIN_HEADERS


@pytest.fixture
def fleet_headers() -> Dict[str, str]:
    return FLEET_ENGINEER_HEADERS


@pytest.fixture
def make_world(api: BatteryApiClient):
    """Build a plant world, optionally overriding the plant registration."""

    def _build(
        plant_overrides: Optional[Dict[str, Any]] = None,
        with_design: bool = True,
    ) -> World:
        world = World(api, plant_overrides)
        world.add_core_staff()
        if with_design:
            world.design_id = world.approved_lead_design()
        return world

    return _build


@pytest.fixture
def world(make_world) -> World:
    """A plant with a generous emission permit, staff and one approved design."""
    return make_world()


@pytest.fixture
def formation_world(world: World) -> World:
    """The standard world plus one bay and one lot sitting in FORMATION."""
    world.bay_id = world.add_bay()
    world.lot = world.lot_in_state("FORMATION", "LOT-F1", 9)
    world.lot_id = world.lot["id"]
    return world


@pytest.fixture
def assembly_world(world: World) -> World:
    """The standard world plus a chamber and a lot of 100 sitting in ASSEMBLY."""
    world.chamber_id = world.add_chamber()
    world.lot = world.lot_in_state("ASSEMBLY", "LOT-100", 100)
    world.lot_id = world.lot["id"]
    return world


@pytest.fixture
def testing_world(assembly_world: World) -> World:
    """A lot of 100 in LOT_TESTING with one certified assembly and a drawn plan."""
    world = assembly_world
    world.assembly = world.certify_assembly(world.lot_id, "ASM-100-1")
    world.assembly_id = world.assembly["id"]
    world.plan = world.draw_plan(world.lot_id)
    world.lot = world.read_lot(world.lot_id)
    return world


@pytest.fixture
def shipped_unit_world(world: World) -> World:
    """A released lot of 9 with two lead-acid units already shipped."""
    world.lot = world.released_lot("LOT-S", 9)
    world.lot_id = world.lot["id"]
    world.unit_a = world.ship_unit(world.lot_id, "BU-S-001")
    world.unit_b = world.ship_unit(world.lot_id, "BU-S-002")
    return world
