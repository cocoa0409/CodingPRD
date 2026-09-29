"""Composite fixtures for the LED Display Manufacturing API test suite.

The API server is restarted before every test, so each test starts against an
empty database and every precondition has to be built from scratch through the
declared endpoints. ``PlantWorkspace`` drives those endpoints in workflow order
— seed the catalogue, specify the wall, approve the drawing, build and soak the
cabinets, mount and commission them, sell the service contract and run the
warranty pipeline — and the pytest fixtures below expose the states tests need
most often.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import api_errors  # noqa: F401  (registers the error/status cross-check)
from .api_client import LedDisplayApiClient
from .constants import (
    CLOCK_EPOCH,
    SOAK_WINDOW_END,
    SOAK_WINDOW_START,
    VISIT_INSTANT,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
    WARRANTY_CASE_INSTANT,
)
from .factories import (
    FP10_IN,
    abort_run_payload,
    assess_payload,
    burn_in_chamber_payload,
    burn_in_run_payload,
    cabinet_payload,
    calibrate_payload,
    commissioning_crew_payload,
    commissioning_visit_payload,
    complete_run_payload,
    degradation_case_payload,
    display_model_payload,
    drawing_revision_payload,
    fulfil_payload,
    install_module_payload,
    module_fault_case_payload,
    module_payload,
    next_serial,
    pixel_test_payload,
    project_payload,
    remove_module_payload,
    review_payload,
    service_contract_payload,
    spare_release_payload,
    spare_reservation_payload,
    visit_calibrate_payload,
)
from .test_users import (
    USER_PRODUCTION_OPERATOR,
    USER_QA_ENGINEER,
    USER_STRUCTURAL_REVIEWER,
    make_design_engineer_headers,
    make_field_engineer_headers,
    make_plant_admin_headers,
    make_production_operator_headers,
    make_qa_engineer_headers,
    make_service_manager_headers,
    make_structural_reviewer_headers,
)


class Scene(dict):
    """A dict of scenario records that also allows attribute access."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


class PlantWorkspace:
    """Drives the API through the plant's workflow to build test preconditions."""

    def __init__(self, api: LedDisplayApiClient):
        self.api = api
        self.admin = make_plant_admin_headers()
        self.engineer = make_design_engineer_headers()
        self.reviewer = make_structural_reviewer_headers()
        self.operator = make_production_operator_headers()
        self.qa = make_qa_engineer_headers()
        self.service = make_service_manager_headers()

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(to_iso8601, self.admin))

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------

    def register_model(self, base: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
        payload = display_model_payload(base if base is not None else FP10_IN, **overrides)
        return get_success_data(self.api.create_display_model(payload, self.admin))

    def register_chamber(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_burn_in_chamber(burn_in_chamber_payload(**overrides), self.admin)
        )

    def register_crew(self, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_commissioning_crew(commissioning_crew_payload(**overrides), self.admin)
        )

    # ------------------------------------------------------------------
    # Projects and engineering
    # ------------------------------------------------------------------

    def create_project(self, display_model_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_project(project_payload(display_model_id, **overrides), self.engineer)
        )

    def submit_revision(self, project_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_drawing_revision(
                drawing_revision_payload(project_id, **overrides), self.engineer
            )
        )

    def review_revision(
        self,
        drawing_revision_id: str,
        decision: str = "APPROVE",
        reason: Optional[str] = None,
        reviewer_user_id: str = USER_STRUCTURAL_REVIEWER,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.review_drawing_revision(
                drawing_revision_id,
                review_payload(decision, reason),
                make_structural_reviewer_headers(reviewer_user_id),
            )
        )

    def approve_engineering(self, project_id: str, **revision_overrides) -> Dict[str, Any]:
        """Submit a revision and have an independent reviewer approve it."""
        revision = self.submit_revision(project_id, **revision_overrides)
        self.review_revision(revision["id"], "APPROVE")
        return revision

    # ------------------------------------------------------------------
    # Modules
    # ------------------------------------------------------------------

    def register_module(
        self, display_model_id: str, serial_no: Optional[str] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_module(module_payload(display_model_id, serial_no), self.operator)
        )

    def pixel_test(
        self,
        module_id: str,
        dead_pixel_count: int = 1,
        max_cluster_size: int = 1,
        operator_user_id: str = USER_PRODUCTION_OPERATOR,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.pixel_test_module(
                module_id,
                pixel_test_payload(dead_pixel_count, max_cluster_size),
                make_production_operator_headers(operator_user_id),
            )
        )

    def calibrate(
        self,
        module_id: str,
        measured_brightness_nits: int = 4900,
        measured_color_x: float = 0.3130,
        measured_color_y: float = 0.3292,
        operator_user_id: str = USER_PRODUCTION_OPERATOR,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.calibrate_module(
                module_id,
                calibrate_payload(measured_brightness_nits, measured_color_x, measured_color_y),
                make_production_operator_headers(operator_user_id),
            )
        )

    def calibrated_module(
        self,
        display_model_id: str,
        serial_no: Optional[str] = None,
        dead_pixel_count: int = 1,
        max_cluster_size: int = 1,
        measured_brightness_nits: int = 4900,
        measured_color_x: float = 0.3130,
        measured_color_y: float = 0.3292,
        operator_user_id: str = USER_PRODUCTION_OPERATOR,
    ) -> Dict[str, Any]:
        """Register a module, pixel-test it and colour-calibrate it into CALIBRATED."""
        module = self.register_module(display_model_id, serial_no)
        self.pixel_test(module["id"], dead_pixel_count, max_cluster_size, operator_user_id)
        return self.calibrate(
            module["id"],
            measured_brightness_nits,
            measured_color_x,
            measured_color_y,
            operator_user_id,
        )

    # ------------------------------------------------------------------
    # Cabinets
    # ------------------------------------------------------------------

    def plan_cabinet(self, project_id: str, grid_row: int = 1, grid_col: int = 1) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_cabinet(cabinet_payload(project_id, grid_row, grid_col), self.operator)
        )

    def cabinet_version(self, cabinet_id: str) -> int:
        return self.cabinet(cabinet_id)["version"]

    def install(
        self,
        cabinet_id: str,
        module_id: str,
        slot_index: int = 1,
        operator_user_id: str = USER_PRODUCTION_OPERATOR,
    ) -> Dict[str, Any]:
        """Install a calibrated module, reading the cabinet's current version first."""
        version = self.cabinet_version(cabinet_id)
        return get_success_data(
            self.api.install_module(
                cabinet_id,
                install_module_payload(module_id, slot_index, version),
                make_production_operator_headers(operator_user_id),
            )
        )

    def remove(self, cabinet_id: str, module_id: str) -> Dict[str, Any]:
        version = self.cabinet_version(cabinet_id)
        return get_success_data(
            self.api.remove_module(
                cabinet_id, remove_module_payload(module_id, version), self.operator
            )
        )

    def populate_cabinet(
        self,
        cabinet_id: str,
        display_model_id: str,
        modules_per_cabinet: int = 1,
        brightnesses: Optional[List[int]] = None,
        chroma: Optional[List[tuple]] = None,
        dead_pixel_counts: Optional[List[int]] = None,
        operator_user_id: str = USER_PRODUCTION_OPERATOR,
    ) -> List[Dict[str, Any]]:
        """Fill every slot of a cabinet with freshly calibrated modules."""
        modules: List[Dict[str, Any]] = []
        for slot in range(1, modules_per_cabinet + 1):
            brightness = brightnesses[slot - 1] if brightnesses else 4900
            color_x, color_y = chroma[slot - 1] if chroma else (0.3130, 0.3292)
            dead = dead_pixel_counts[slot - 1] if dead_pixel_counts else 1
            cluster = 1 if dead > 0 else 0
            module = self.calibrated_module(
                display_model_id,
                dead_pixel_count=dead,
                max_cluster_size=cluster,
                measured_brightness_nits=brightness,
                measured_color_x=color_x,
                measured_color_y=color_y,
                operator_user_id=operator_user_id,
            )
            modules.append(self.install(cabinet_id, module["id"], slot, operator_user_id))
        return modules

    def qa_approve(self, cabinet_id: str, qa_user_id: str = USER_QA_ENGINEER) -> Dict[str, Any]:
        return get_success_data(
            self.api.qa_approve_cabinet(cabinet_id, make_qa_engineer_headers(qa_user_id))
        )

    def mount(self, cabinet_id: str, commissioning_crew_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.mount_cabinet(cabinet_id, make_field_engineer_headers(commissioning_crew_id))
        )

    # ------------------------------------------------------------------
    # Burn-in
    # ------------------------------------------------------------------

    def schedule_run(self, cabinet_id: str, burn_in_chamber_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_burn_in_run(
                burn_in_run_payload(cabinet_id, burn_in_chamber_id, **overrides), self.qa
            )
        )

    def complete_run(
        self, burn_in_run_id: str, qa_user_id: str = USER_QA_ENGINEER, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.complete_burn_in_run(
                burn_in_run_id,
                complete_run_payload(**overrides),
                make_qa_engineer_headers(qa_user_id),
            )
        )

    def abort_run(self, burn_in_run_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        payload = abort_run_payload(reason) if reason is not None else abort_run_payload()
        return get_success_data(self.api.abort_burn_in_run(burn_in_run_id, payload, self.qa))

    def soak_and_pass(
        self,
        cabinet_id: str,
        burn_in_chamber_id: str,
        window_start: str = SOAK_WINDOW_START,
        window_end: str = SOAK_WINDOW_END,
        new_dead_pixel_count: int = 0,
        measured_brightness_nits: int = 4900,
        measured_uniformity_pct: float = 95.00,
        qa_user_id: str = USER_QA_ENGINEER,
        **run_overrides,
    ) -> Dict[str, Any]:
        """Schedule a soak, advance the clock to its window end, and pass the run."""
        run = self.schedule_run(
            cabinet_id,
            burn_in_chamber_id,
            window_start=window_start,
            window_end=window_end,
            **run_overrides,
        )
        self.set_clock(window_end)
        return self.complete_run(
            run["id"],
            qa_user_id=qa_user_id,
            new_dead_pixel_count=new_dead_pixel_count,
            measured_brightness_nits=measured_brightness_nits,
            measured_uniformity_pct=measured_uniformity_pct,
        )

    # ------------------------------------------------------------------
    # Commissioning
    # ------------------------------------------------------------------

    def book_visit(
        self, project_id: str, commissioning_crew_id: str, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_commissioning_visit(
                commissioning_visit_payload(project_id, commissioning_crew_id, **overrides),
                self.admin,
            )
        )

    def arrive(self, commissioning_visit_id: str, commissioning_crew_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.arrive_at_visit(
                commissioning_visit_id, make_field_engineer_headers(commissioning_crew_id)
            )
        )

    def calibrate_on_site(
        self,
        commissioning_visit_id: str,
        commissioning_crew_id: str,
        measured_brightness_nits: int = 4900,
        measured_uniformity_pct: float = 95.00,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.calibrate_visit(
                commissioning_visit_id,
                visit_calibrate_payload(measured_brightness_nits, measured_uniformity_pct),
                make_field_engineer_headers(commissioning_crew_id),
            )
        )

    def sign_off(self, commissioning_visit_id: str, commissioning_crew_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.sign_off_visit(
                commissioning_visit_id, make_field_engineer_headers(commissioning_crew_id)
            )
        )

    def commission_visit(
        self,
        commissioning_visit_id: str,
        commissioning_crew_id: str,
        at_instant: str = VISIT_INSTANT,
        measured_brightness_nits: int = 4900,
        measured_uniformity_pct: float = 95.00,
    ) -> Dict[str, Any]:
        """Walk a booked visit through arrival, on-site calibration and sign-off."""
        self.set_clock(at_instant)
        self.arrive(commissioning_visit_id, commissioning_crew_id)
        self.calibrate_on_site(
            commissioning_visit_id,
            commissioning_crew_id,
            measured_brightness_nits,
            measured_uniformity_pct,
        )
        return self.sign_off(commissioning_visit_id, commissioning_crew_id)

    # ------------------------------------------------------------------
    # Service contracts and the spare pool
    # ------------------------------------------------------------------

    def sell_contract(self, project_id: str, **overrides) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_service_contract(
                service_contract_payload(project_id, **overrides), self.service
            )
        )

    def contract_version(self, service_contract_id: str) -> int:
        return self.contract(service_contract_id)["version"]

    def reserve_spare(
        self, service_contract_id: str, module_id: Optional[str] = None
    ) -> Dict[str, Any]:
        version = self.contract_version(service_contract_id)
        return get_success_data(
            self.api.reserve_spare(
                service_contract_id,
                spare_reservation_payload(version, module_id),
                self.service,
            )
        )

    def release_spare(self, service_contract_id: str, module_id: str) -> Dict[str, Any]:
        version = self.contract_version(service_contract_id)
        return get_success_data(
            self.api.release_spare(
                service_contract_id, spare_release_payload(module_id, version), self.service
            )
        )

    # ------------------------------------------------------------------
    # Warranty cases
    # ------------------------------------------------------------------

    def open_module_fault_case(
        self, service_contract_id: str, cabinet_id: str, faulty_module_id: str, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_service_case(
                module_fault_case_payload(
                    service_contract_id, cabinet_id, faulty_module_id, **overrides
                ),
                self.service,
            )
        )

    def open_degradation_case(
        self, service_contract_id: str, cabinet_id: str, **overrides
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_service_case(
                degradation_case_payload(service_contract_id, cabinet_id, **overrides),
                self.service,
            )
        )

    def respond(self, service_case_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.respond_to_case(service_case_id, self.service))

    def assess(
        self,
        service_case_id: str,
        decision: str = "APPROVE",
        assessment_basis: Optional[str] = None,
        denial_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.assess_case(
                service_case_id,
                assess_payload(decision, assessment_basis, denial_reason),
                self.service,
            )
        )

    def fulfil(
        self,
        service_case_id: str,
        cabinet_id: str,
        replacement_module_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        version = self.cabinet_version(cabinet_id)
        return get_success_data(
            self.api.fulfil_case(
                service_case_id,
                fulfil_payload(version, replacement_module_id),
                self.service,
            )
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def model(self, display_model_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_display_model(display_model_id, self.admin))

    def chamber(self, burn_in_chamber_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_burn_in_chamber(burn_in_chamber_id, self.qa))

    def crew(self, commissioning_crew_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_commissioning_crew(commissioning_crew_id, self.admin))

    def project(self, project_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_project(project_id, self.engineer))

    def revision(self, drawing_revision_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_drawing_revision(drawing_revision_id, self.engineer))

    def cabinet(self, cabinet_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_cabinet(cabinet_id, self.operator))

    def module(self, module_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_module(module_id, self.operator))

    def run(self, burn_in_run_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_burn_in_run(burn_in_run_id, self.qa))

    def visit(self, commissioning_visit_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_commissioning_visit(commissioning_visit_id, self.admin))

    def contract(self, service_contract_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_service_contract(service_contract_id, self.service))

    def case(self, service_case_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_service_case(service_case_id, self.service))

    # ------------------------------------------------------------------
    # Whole-scenario builders
    # ------------------------------------------------------------------

    def approved_project_scene(
        self,
        model_base: Optional[Dict[str, Any]] = None,
        model_overrides: Optional[Dict[str, Any]] = None,
        project_overrides: Optional[Dict[str, Any]] = None,
        revision_overrides: Optional[Dict[str, Any]] = None,
    ) -> Scene:
        """A wall whose structural package has been independently approved."""
        model = self.register_model(model_base, **(model_overrides or {}))
        project = self.create_project(model["id"], **(project_overrides or {}))
        revision = self.approve_engineering(project["id"], **(revision_overrides or {}))
        return Scene(
            model=model,
            project=self.project(project["id"]),
            revision=self.revision(revision["id"]),
        )

    def populated_cabinet_scene(
        self,
        brightnesses: Optional[List[int]] = None,
        chroma: Optional[List[tuple]] = None,
        dead_pixel_counts: Optional[List[int]] = None,
        **kwargs,
    ) -> Scene:
        """One planned cabinet of an approved wall, filled to POPULATED."""
        scene = self.approved_project_scene(**kwargs)
        cabinet = self.plan_cabinet(scene.project["id"])
        modules = self.populate_cabinet(
            cabinet["id"],
            scene.model["id"],
            modules_per_cabinet=scene.model["modules_per_cabinet"],
            brightnesses=brightnesses,
            chroma=chroma,
            dead_pixel_counts=dead_pixel_counts,
        )
        scene.cabinet = self.cabinet(cabinet["id"])
        scene.modules = [self.module(module["id"]) for module in modules]
        scene.project = self.project(scene.project["id"])
        return scene

    def burn_in_passed_scene(self, **kwargs) -> Scene:
        """A populated cabinet that has passed its soak, freezing the QA baseline."""
        scene = self.populated_cabinet_scene(**kwargs)
        chamber = self.register_chamber()
        window_end = SOAK_WINDOW_END
        if scene.model["burn_in_hours_required"] > 24:
            window_end = "2026-08-04T00:00:00.000Z"
        run = self.soak_and_pass(scene.cabinet["id"], chamber["id"], window_end=window_end)
        scene.chamber = self.chamber(chamber["id"])
        scene.run = self.run(run["id"])
        scene.cabinet = self.cabinet(scene.cabinet["id"])
        return scene

    def mounted_project_scene(self, **kwargs) -> Scene:
        """Every cabinet QA-signed and mounted, so the project reaches INSTALLED."""
        scene = self.burn_in_passed_scene(**kwargs)
        self.qa_approve(scene.cabinet["id"])
        crew = self.register_crew()
        self.mount(scene.cabinet["id"], crew["id"])
        scene.crew = self.crew(crew["id"])
        scene.cabinet = self.cabinet(scene.cabinet["id"])
        scene.project = self.project(scene.project["id"])
        return scene

    def commissioned_scene(
        self,
        contract_overrides: Optional[Dict[str, Any]] = None,
        sell_contract: bool = True,
        **kwargs,
    ) -> Scene:
        """A commissioned wall: the visit is signed off and any contract is ACTIVE."""
        scene = self.mounted_project_scene(**kwargs)
        if sell_contract:
            contract = self.sell_contract(scene.project["id"], **(contract_overrides or {}))
        else:
            contract = None
        visit = self.book_visit(
            scene.project["id"],
            scene.crew["id"],
            window_start=VISIT_WINDOW_START,
            window_end=VISIT_WINDOW_END,
        )
        self.commission_visit(visit["id"], scene.crew["id"])
        scene.visit = self.visit(visit["id"])
        scene.project = self.project(scene.project["id"])
        scene.contract = self.contract(contract["id"]) if contract else None
        scene.cabinet = self.cabinet(scene.cabinet["id"])
        return scene

    def reserved_spare_scene(
        self,
        spare_brightness: int = 4850,
        spare_chroma: tuple = (0.3124, 0.3287),
        **kwargs,
    ) -> Scene:
        """A commissioned wall with one calibrated spare reserved against the contract."""
        scene = self.commissioned_scene(**kwargs)
        spare = self.calibrated_module(
            scene.model["id"],
            serial_no=next_serial("S"),
            measured_brightness_nits=spare_brightness,
            measured_color_x=spare_chroma[0],
            measured_color_y=spare_chroma[1],
        )
        self.reserve_spare(scene.contract["id"], spare["id"])
        scene.spare = self.module(spare["id"])
        scene.contract = self.contract(scene.contract["id"])
        return scene

    def warranty_case_scene(
        self,
        measured_brightness_nits: int = 4600,
        reported_at: str = WARRANTY_CASE_INSTANT,
        **kwargs,
    ) -> Scene:
        """A reserved-spare wall with a brightness-degradation case already RESPONDED."""
        scene = self.reserved_spare_scene(**kwargs)
        self.set_clock(reported_at)
        case = self.open_degradation_case(
            scene.contract["id"],
            scene.cabinet["id"],
            measured_brightness_nits=measured_brightness_nits,
        )
        self.respond(case["id"])
        scene.case = self.case(case["id"])
        scene.contract = self.contract(scene.contract["id"])
        return scene


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> LedDisplayApiClient:
    """A client bound to the service under test."""
    return LedDisplayApiClient()


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return make_plant_admin_headers()


@pytest.fixture
def engineer_headers() -> Dict[str, str]:
    return make_design_engineer_headers()


@pytest.fixture
def reviewer_headers() -> Dict[str, str]:
    return make_structural_reviewer_headers()


@pytest.fixture
def operator_headers() -> Dict[str, str]:
    return make_production_operator_headers()


@pytest.fixture
def qa_headers() -> Dict[str, str]:
    return make_qa_engineer_headers()


@pytest.fixture
def service_headers() -> Dict[str, str]:
    return make_service_manager_headers()


@pytest.fixture
def plant(api: LedDisplayApiClient) -> PlantWorkspace:
    """A workspace whose logical clock has been parked at the canonical epoch."""
    workspace = PlantWorkspace(api)
    workspace.set_clock(CLOCK_EPOCH)
    return workspace


@pytest.fixture
def fp10_model(plant: PlantWorkspace) -> Dict[str, Any]:
    """The one-module-per-cabinet indoor family used by most scenarios."""
    return plant.register_model()


@pytest.fixture
def chamber(plant: PlantWorkspace) -> Dict[str, Any]:
    """A four-slot chamber with a sixty minute turnaround."""
    return plant.register_chamber()


@pytest.fixture
def crew(plant: PlantWorkspace) -> Dict[str, Any]:
    """A level three crew licensed for the region the canonical wall stands in."""
    return plant.register_crew()


@pytest.fixture
def approved_project(plant: PlantWorkspace) -> Scene:
    """An FP10-IN wall whose drawing revision has been approved."""
    return plant.approved_project_scene()


@pytest.fixture
def populated_cabinet(plant: PlantWorkspace) -> Scene:
    """An approved FP10-IN wall with its single cabinet POPULATED."""
    return plant.populated_cabinet_scene()


@pytest.fixture
def burn_in_passed_cabinet(plant: PlantWorkspace) -> Scene:
    """A cabinet that has passed its soak, with its QA baseline frozen."""
    return plant.burn_in_passed_scene()


@pytest.fixture
def mounted_project(plant: PlantWorkspace) -> Scene:
    """Every cabinet QA-signed and mounted, so production_state is INSTALLED."""
    return plant.mounted_project_scene()


@pytest.fixture
def commissioned_project(plant: PlantWorkspace) -> Scene:
    """A signed-off wall carrying an ACTIVE GOLD contract."""
    return plant.commissioned_scene()


@pytest.fixture
def commissioned_without_contract(plant: PlantWorkspace) -> Scene:
    """A signed-off wall with no service contract sold against it."""
    return plant.commissioned_scene(sell_contract=False)


@pytest.fixture
def contract_with_spare(plant: PlantWorkspace) -> Scene:
    """A commissioned wall with one calibrated spare reserved to its contract."""
    return plant.reserved_spare_scene()


@pytest.fixture
def responded_degradation_case(plant: PlantWorkspace) -> Scene:
    """A brightness-degradation claim in RESPONDED, six warranty months in."""
    return plant.warranty_case_scene()
