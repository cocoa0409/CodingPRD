"""Composite state builders and pytest fixtures.

The API is a deep chain: nothing can be measured until a lot is tracked in,
nothing can be tracked in until a plan is committed, and a plan cannot be
committed until a flow with priced steps has been released against qualified
chambers staffed by a gowned, certified operator.

Rather than re-thread that chain inline, tests declare the shape of the line
they need with a :class:`LineSpec` and hand it to :func:`build_line`.  Higher
tier helpers then drive the line forward: open a run, raise an excursion,
walk a lot all the way to sort, cycle a tool through maintenance.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing.validators import get_success_data

from . import factories as f
from .api_client import FabApiClient
from .api_errors import register_error_status_map
from .constants import DEFAULT_PARTICLE_LIMIT, T0
from .test_users import (
    USER_EQUIPMENT_ENGINEER,
    USER_FAB_PLANNER,
    USER_PROCESS_ENGINEER,
    USER_QUALITY_MANAGER,
    USER_YIELD_ENGINEER,
    equipment_engineer_headers,
    fab_planner_headers,
    make_operator_headers,
    process_engineer_headers,
    quality_manager_headers,
    yield_engineer_headers,
)


class Env(dict):
    """Dict of built rows that also supports attribute access."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


# ==========================================================================
# Low level builder: one method per API act, each returning the stored row
# ==========================================================================


class FabBuilder:
    """Thin, role-correct wrapper that returns ``data`` instead of responses."""

    def __init__(self, client: FabApiClient):
        self.client = client

    # -- clock ------------------------------------------------------------

    def set_clock(self, instant: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.set_clock(instant, fab_planner_headers()), expected_status=200
        )

    # -- process engineering ---------------------------------------------

    def recipe(
        self,
        recipe_code: str = "LITHO-200",
        tool_type: str = "LITHO",
        target_value: float = 50.0,
        qual_expiry_days: Optional[int] = 100,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_recipe(
                f.recipe_payload(recipe_code, tool_type, target_value, qual_expiry_days),
                process_engineer_headers(),
            ),
            expected_status=201,
        )

    def flow(
        self, flow_code: str = "FLOW-A", product_family: str = "LOGIC_N5"
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_process_flow(
                f.process_flow_payload(flow_code, product_family),
                process_engineer_headers(),
            ),
            expected_status=201,
        )

    def step(
        self,
        flow_id: str,
        recipe_id: str,
        step_seq: int = 10,
        step_name: str = "LITHO-1",
        standard_hours: float = 2.0,
        metrology_required: Optional[bool] = None,
        rework_target_step_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.add_process_step(
                flow_id,
                f.process_step_payload(
                    recipe_id,
                    step_seq=step_seq,
                    step_name=step_name,
                    standard_hours=standard_hours,
                    metrology_required=metrology_required,
                    rework_target_step_id=rework_target_step_id,
                ),
                process_engineer_headers(),
            ),
            expected_status=201,
        )

    def release_flow(
        self, flow_id: str, supersedes_flow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        payload = {}
        if supersedes_flow_id is not None:
            payload["supersedes_flow_id"] = supersedes_flow_id
        return get_success_data(
            self.client.release_process_flow(
                flow_id, process_engineer_headers(), payload
            ),
            expected_status=200,
        )

    def chart(
        self,
        step_id: str,
        param_name: str = "ETCH_DEPTH",
        target: float = 100.0,
        sigma: float = 2.0,
        usl: float = 110.0,
        lsl: float = 90.0,
        ucl: float = 106.0,
        lcl: float = 94.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_spc_chart(
                f.spc_chart_payload(
                    step_id, param_name, target, sigma, usl, lsl, ucl, lcl
                ),
                headers or process_engineer_headers(),
            ),
            expected_status=201,
        )

    # -- change notices ---------------------------------------------------

    def change_request(
        self,
        recipe_id: str,
        change_class: str = "MINOR",
        proposed_target: float = 50.5,
        justification: str = "Process window centring",
        author_user_id: str = USER_PROCESS_ENGINEER,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_change_request(
                recipe_id,
                f.change_request_payload(change_class, proposed_target, justification),
                process_engineer_headers(author_user_id),
            ),
            expected_status=201,
        )

    def approve_change_request(
        self,
        cr_id: str,
        expected_recipe_version: int,
        approver_user_id: str = USER_QUALITY_MANAGER,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.approve_change_request(
                cr_id,
                f.approve_payload(expected_recipe_version),
                quality_manager_headers(approver_user_id),
            ),
            expected_status=200,
        )

    def implement_change_request(
        self, cr_id: str, user_id: str = USER_PROCESS_ENGINEER
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.implement_change_request(
                cr_id, process_engineer_headers(user_id)
            ),
            expected_status=200,
        )

    def request_change_revision(
        self, cr_id: str, comment: str = "Add split-lot data"
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.request_change_revision(
                cr_id, f.request_revision_payload(comment), quality_manager_headers()
            ),
            expected_status=200,
        )

    def resubmit_change_request(
        self,
        cr_id: str,
        change_class: str = "MAJOR",
        proposed_target: float = 110.0,
        justification: str = "Split-lot data attached",
        author_user_id: str = USER_PROCESS_ENGINEER,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.resubmit_change_request(
                cr_id,
                f.change_request_payload(change_class, proposed_target, justification),
                process_engineer_headers(author_user_id),
            ),
            expected_status=200,
        )

    # -- equipment engineering -------------------------------------------

    def equipment(
        self,
        equipment_code: str = "LITHO-1",
        tool_type: str = "LITHO",
        pm_interval_hours: float = 168.0,
        purge_buffer_hours: float = 24.0,
        hours_since_pm: float = 0.0,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_equipment(
                f.equipment_payload(
                    equipment_code,
                    tool_type,
                    pm_interval_hours,
                    purge_buffer_hours,
                    hours_since_pm,
                ),
                equipment_engineer_headers(),
            ),
            expected_status=201,
        )

    def chamber(
        self,
        equipment_id: str,
        qualified_recipe_id: str,
        chamber_code: str = "CH_L1",
        particle_limit: float = DEFAULT_PARTICLE_LIMIT,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_chamber(
                f.chamber_payload(
                    equipment_id, qualified_recipe_id, chamber_code, particle_limit
                ),
                equipment_engineer_headers(),
            ),
            expected_status=201,
        )

    def qualify_chamber(self, chamber_id: str, qual_result: str = "PASS") -> Dict[str, Any]:
        return get_success_data(
            self.client.create_qualification_run(
                chamber_id,
                f.qualification_run_payload(qual_result),
                equipment_engineer_headers(),
            ),
            expected_status=200,
        )

    def particle_reading(
        self, chamber_id: str, particle_reading: float, headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_particle_reading(
                chamber_id,
                f.particle_reading_payload(particle_reading),
                headers or equipment_engineer_headers(),
            ),
            expected_status=200,
        )

    def pm_start(self, equipment_id: str, pm_reason: str = "Scheduled preventive maintenance"):
        return get_success_data(
            self.client.pm_start(
                equipment_id, f.pm_start_payload(pm_reason), equipment_engineer_headers()
            ),
            expected_status=200,
        )

    def pm_complete(self, equipment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.pm_complete(equipment_id, equipment_engineer_headers()),
            expected_status=200,
        )

    # -- operators --------------------------------------------------------

    def operator(
        self,
        badge_id: str = "OP-001",
        full_name: str = "Ada Fabrizio",
        certified_tool_types: Optional[List[str]] = None,
        gowned: bool = True,
    ) -> Dict[str, Any]:
        row = get_success_data(
            self.client.create_operator(
                f.operator_payload(badge_id, full_name, certified_tool_types),
                quality_manager_headers(),
            ),
            expected_status=201,
        )
        if gowned:
            row = self.gown(row["id"])
        return row

    def gown(self, operator_id: str, gown_state: str = "GOWNED") -> Dict[str, Any]:
        return get_success_data(
            self.client.patch_operator(
                operator_id,
                f.gown_patch(gown_state),
                make_operator_headers(operator_id),
            ),
            expected_status=200,
        )

    def set_cert_status(self, operator_id: str, cert_status: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.patch_operator(
                operator_id, f.cert_patch(cert_status), quality_manager_headers()
            ),
            expected_status=200,
        )

    # -- planning ---------------------------------------------------------

    def plan(
        self,
        flow_id: str,
        product_family: str = "LOGIC_N5",
        planned_wafer_starts: int = 10,
        capacity_budget_hours: float = 100.0,
        cycle_time_target_days: float = 30.0,
        week_start_date: str = "2026-08-03T00:00:00Z",
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_plan(
                f.plan_payload(
                    flow_id,
                    product_family,
                    week_start_date,
                    planned_wafer_starts,
                    capacity_budget_hours,
                    cycle_time_target_days,
                ),
                fab_planner_headers(),
            ),
            expected_status=201,
        )

    def commit_plan(self, plan_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.commit_plan(plan_id, fab_planner_headers()),
            expected_status=200,
        )

    def read_plan(self, plan_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_plan(plan_id, fab_planner_headers()), expected_status=200
        )

    # -- lots -------------------------------------------------------------

    def lot(
        self,
        plan_id: str,
        flow_id: str,
        lot_number: str = "LOT-001",
        wafer_count: int = 3,
        priority_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_lot(
                f.lot_payload(plan_id, flow_id, lot_number, wafer_count, priority_class),
                fab_planner_headers(),
            ),
            expected_status=201,
        )

    def release_lot(self, lot_id: str, plan_id: str) -> Dict[str, Any]:
        """Release a lot, reading the plan first for its current version."""
        plan_version = self.read_plan(plan_id)["version"]
        return get_success_data(
            self.client.release_lot(
                lot_id, f.release_lot_payload(plan_version), fab_planner_headers()
            ),
            expected_status=200,
        )

    def read_lot(self, lot_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_lot(lot_id, fab_planner_headers()), expected_status=200
        )

    def cycle_time_projection(self, lot_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_cycle_time_projection(lot_id, fab_planner_headers()),
            expected_status=200,
        )

    def split_lot(
        self,
        lot_id: str,
        split_wafer_count: int,
        lot_number: str = "LOT-001-S1",
        priority_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        lot_version = self.read_lot(lot_id)["version"]
        return get_success_data(
            self.client.split_lot(
                lot_id,
                f.split_payload(
                    lot_version, split_wafer_count, lot_number, priority_class
                ),
                process_engineer_headers(),
            ),
            expected_status=201,
        )

    def rejoin_lot(self, child_lot_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.rejoin_lot(child_lot_id, process_engineer_headers()),
            expected_status=200,
        )

    def rework_lot(self, lot_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.rework_lot(lot_id, process_engineer_headers()),
            expected_status=200,
        )

    # -- shop floor -------------------------------------------------------

    def track_in(self, lot_id: str, step_id: str, operator_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_step_run(
                f.step_run_payload(lot_id, step_id, operator_id),
                make_operator_headers(operator_id),
            ),
            expected_status=201,
        )

    def track_out(self, run_id: str, operator_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.track_out(run_id, make_operator_headers(operator_id)),
            expected_status=200,
        )

    def abort_run(
        self, run_id: str, operator_id: str, abort_reason: str = "Chamber excursion"
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.abort_step_run(
                run_id, f.abort_payload(abort_reason), make_operator_headers(operator_id)
            ),
            expected_status=200,
        )

    def measure(
        self, run_id: str, chart_id: str, measured_value: float, operator_id: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_measurement(
                f.measurement_payload(run_id, chart_id, measured_value),
                make_operator_headers(operator_id),
            ),
            expected_status=201,
        )

    # -- excursions -------------------------------------------------------

    def contain(
        self,
        excursion_id: str,
        containment_scope: str,
        chamber_id: Optional[str] = None,
        user_id: str = USER_QUALITY_MANAGER,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.contain_excursion(
                excursion_id,
                f.contain_payload(containment_scope, chamber_id),
                quality_manager_headers(user_id),
            ),
            expected_status=200,
        )

    def disposition(
        self,
        excursion_id: str,
        disposition: str,
        root_cause_note: str = "Chamber drift confirmed by cross-section",
        user_id: str = USER_YIELD_ENGINEER,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.disposition_excursion(
                excursion_id,
                f.disposition_payload(disposition, root_cause_note),
                yield_engineer_headers(user_id),
            ),
            expected_status=200,
        )

    def read_excursion(self, excursion_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_excursion(excursion_id, quality_manager_headers()),
            expected_status=200,
        )

    def read_chamber(self, chamber_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_chamber(chamber_id, equipment_engineer_headers()),
            expected_status=200,
        )

    def read_equipment(self, equipment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_equipment(equipment_id, equipment_engineer_headers()),
            expected_status=200,
        )

    def read_chart(self, chart_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_spc_chart(chart_id, process_engineer_headers()),
            expected_status=200,
        )

    def read_step_run(self, run_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_step_run(run_id, process_engineer_headers()),
            expected_status=200,
        )

    def read_recipe(self, recipe_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_recipe(recipe_id, process_engineer_headers()),
            expected_status=200,
        )

    def read_flow(self, flow_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_process_flow(flow_id, process_engineer_headers()),
            expected_status=200,
        )

    def read_change_request(self, cr_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_change_request(cr_id, process_engineer_headers()),
            expected_status=200,
        )

    def read_operator(self, operator_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_operator(operator_id, quality_manager_headers()),
            expected_status=200,
        )

    def read_measurement(self, measurement_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_measurement(measurement_id, quality_manager_headers()),
            expected_status=200,
        )

    def read_step(self, step_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_process_step(step_id, process_engineer_headers()),
            expected_status=200,
        )

    # -- die sort ---------------------------------------------------------

    def die_sort(
        self,
        lot_id: str,
        wafer_results: List[Dict[str, Any]],
        gross_die_per_wafer: int = 100,
        baseline_yield: float = 0.92,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.create_die_sort_run(
                f.die_sort_payload(
                    lot_id, wafer_results, gross_die_per_wafer, baseline_yield
                ),
                yield_engineer_headers(),
            ),
            expected_status=201,
        )

    def bin_sort_run(
        self, run_id: str, premium_target_die: int, standard_target_die: int
    ) -> Dict[str, Any]:
        return get_success_data(
            self.client.bin_die_sort_run(
                run_id,
                f.bin_payload(premium_target_die, standard_target_die),
                yield_engineer_headers(),
            ),
            expected_status=200,
        )

    def read_die_sort_run(self, run_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_die_sort_run(run_id, yield_engineer_headers()),
            expected_status=200,
        )

    # -- list helpers -----------------------------------------------------

    def count(self, list_response) -> int:
        body = list_response.json()
        return body["meta"]["total_count"]


# ==========================================================================
# Declarative line specification
# ==========================================================================


@dataclass
class RecipeSpec:
    recipe_code: str = "LITHO-200"
    tool_type: str = "LITHO"
    target_value: float = 50.0
    qual_expiry_days: Optional[int] = 100


@dataclass
class StepSpec:
    step_seq: int = 10
    step_name: str = "LITHO-1"
    standard_hours: float = 2.0
    recipe_ix: int = 0
    metrology_required: Optional[bool] = None
    #: index into the steps built so far, used as ``rework_target_step_id``
    rework_target_ix: Optional[int] = None


@dataclass
class EquipmentSpec:
    equipment_code: str = "LITHO-1"
    tool_type: str = "LITHO"
    pm_interval_hours: float = 168.0
    purge_buffer_hours: float = 24.0
    hours_since_pm: float = 0.0


@dataclass
class ChamberSpec:
    chamber_code: str = "CH_L1"
    equipment_ix: int = 0
    recipe_ix: int = 0
    particle_limit: float = DEFAULT_PARTICLE_LIMIT
    qualify: bool = True


@dataclass
class OperatorSpec:
    badge_id: str = "OP-001"
    full_name: str = "Ada Fabrizio"
    certified_tool_types: Optional[List[str]] = None
    gowned: bool = True


@dataclass
class ChartSpec:
    step_ix: int = 0
    param_name: str = "ETCH_DEPTH"
    target: float = 100.0
    sigma: float = 2.0
    usl: float = 110.0
    lsl: float = 90.0
    ucl: float = 106.0
    lcl: float = 94.0


@dataclass
class LotSpec:
    lot_number: str = "LOT-001"
    wafer_count: int = 3
    priority_class: Optional[str] = None
    release: bool = True


@dataclass
class LineSpec:
    """Everything needed to stand a production line up from an empty store."""

    clock: Optional[str] = T0
    recipes: List[RecipeSpec] = field(default_factory=lambda: [RecipeSpec()])
    flow_code: str = "FLOW-A"
    product_family: str = "LOGIC_N5"
    steps: List[StepSpec] = field(default_factory=lambda: [StepSpec()])
    release_flow: bool = True
    equipments: List[EquipmentSpec] = field(default_factory=lambda: [EquipmentSpec()])
    chambers: List[ChamberSpec] = field(default_factory=lambda: [ChamberSpec()])
    operators: List[OperatorSpec] = field(default_factory=lambda: [OperatorSpec()])
    charts: List[ChartSpec] = field(default_factory=list)
    make_plan: bool = True
    plan_product_family: Optional[str] = None
    planned_wafer_starts: int = 10
    capacity_budget_hours: float = 100.0
    cycle_time_target_days: float = 30.0
    week_start_date: str = "2026-08-03T00:00:00Z"
    commit_plan: bool = True
    lots: List[LotSpec] = field(default_factory=lambda: [LotSpec()])


def build_line(builder: FabBuilder, spec: Optional[LineSpec] = None) -> Env:
    """Stand up a line from an empty store and return every row it created."""
    spec = spec or LineSpec()
    env = Env()

    if spec.clock is not None:
        builder.set_clock(spec.clock)

    env.recipes = [
        builder.recipe(
            r.recipe_code, r.tool_type, r.target_value, r.qual_expiry_days
        )
        for r in spec.recipes
    ]
    env.recipe = env.recipes[0]

    env.flow = builder.flow(spec.flow_code, spec.product_family)

    steps: List[Dict[str, Any]] = []
    for s in spec.steps:
        rework_target = (
            steps[s.rework_target_ix]["id"] if s.rework_target_ix is not None else None
        )
        steps.append(
            builder.step(
                env.flow["id"],
                env.recipes[s.recipe_ix]["id"],
                s.step_seq,
                s.step_name,
                s.standard_hours,
                s.metrology_required,
                rework_target,
            )
        )
    env.steps = steps

    if spec.release_flow:
        env.flow = builder.release_flow(env.flow["id"])

    env.charts = [
        builder.chart(
            steps[c.step_ix]["id"],
            c.param_name,
            c.target,
            c.sigma,
            c.usl,
            c.lsl,
            c.ucl,
            c.lcl,
        )
        for c in spec.charts
    ]
    env.chart = env.charts[0] if env.charts else None

    env.equipments = [
        builder.equipment(
            e.equipment_code,
            e.tool_type,
            e.pm_interval_hours,
            e.purge_buffer_hours,
            e.hours_since_pm,
        )
        for e in spec.equipments
    ]
    env.equipment = env.equipments[0]

    chambers: List[Dict[str, Any]] = []
    for c in spec.chambers:
        row = builder.chamber(
            env.equipments[c.equipment_ix]["id"],
            env.recipes[c.recipe_ix]["id"],
            c.chamber_code,
            c.particle_limit,
        )
        if c.qualify:
            row = builder.qualify_chamber(row["id"])
        chambers.append(row)
    env.chambers = chambers
    env.chamber = chambers[0] if chambers else None

    env.operators = [
        builder.operator(o.badge_id, o.full_name, o.certified_tool_types, o.gowned)
        for o in spec.operators
    ]
    env.operator = env.operators[0] if env.operators else None

    env.plan = None
    env.lots = []
    env.lot = None
    if spec.make_plan:
        env.plan = builder.plan(
            env.flow["id"],
            spec.plan_product_family or spec.product_family,
            spec.planned_wafer_starts,
            spec.capacity_budget_hours,
            spec.cycle_time_target_days,
            spec.week_start_date,
        )
        if spec.commit_plan:
            env.plan = builder.commit_plan(env.plan["id"])

        lots: List[Dict[str, Any]] = []
        for lot_spec in spec.lots:
            row = builder.lot(
                env.plan["id"],
                env.flow["id"],
                lot_spec.lot_number,
                lot_spec.wafer_count,
                lot_spec.priority_class,
            )
            if lot_spec.release:
                row = builder.release_lot(row["id"], env.plan["id"])
            lots.append(row)
        env.lots = lots
        env.lot = lots[0] if lots else None

    return env


# ==========================================================================
# Named presets
# ==========================================================================


def single_step_spec(**overrides: Any) -> LineSpec:
    """One LITHO step, one qualified chamber, one released 3-wafer lot."""
    spec = LineSpec()
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def metrology_step_spec(**overrides: Any) -> LineSpec:
    """Single LITHO step that requires metrology, with a chart over it."""
    spec = LineSpec(
        steps=[
            StepSpec(
                step_seq=10,
                step_name="LITHO-1",
                standard_hours=2.0,
                metrology_required=True,
            )
        ],
        charts=[ChartSpec(step_ix=0, param_name="CD-10")],
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def two_recipe_line_spec(**overrides: Any) -> LineSpec:
    """The three-step litho / etch / litho line used by the deep scenarios.

    Step 20 requires metrology and reworks back to step 10; a chart sits over
    it.  Two tools each carry one qualified chamber, and the plan is sized so
    that neither the budget nor the tool ledger is the binding constraint.
    """
    spec = LineSpec(
        recipes=[
            RecipeSpec("LITHO-100", "LITHO", 50.0, 100),
            RecipeSpec("ETCH-100", "ETCH", 100.0, 100),
        ],
        steps=[
            StepSpec(10, "LITHO-1", 2.0, recipe_ix=0),
            StepSpec(20, "ETCH-1", 3.0, recipe_ix=1, metrology_required=True,
                     rework_target_ix=0),
            StepSpec(30, "LITHO-2", 2.0, recipe_ix=0),
        ],
        equipments=[
            EquipmentSpec("LITHO-1", "LITHO", 168.0, 24.0, 0.0),
            EquipmentSpec("ETCH-1", "ETCH", 168.0, 24.0, 0.0),
        ],
        chambers=[
            ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0),
            ChamberSpec("CH_E1", equipment_ix=1, recipe_ix=1),
        ],
        charts=[ChartSpec(step_ix=1, param_name="ETCH_DEPTH")],
        planned_wafer_starts=50,
        capacity_budget_hours=500.0,
        cycle_time_target_days=30.0,
        lots=[LotSpec("LOT-001", 3), LotSpec("LOT-002", 3)],
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def rework_line_spec(**overrides: Any) -> LineSpec:
    """Three LITHO steps where step 20 reworks back to step 10."""
    spec = LineSpec(
        recipes=[RecipeSpec("LITHO-200", "LITHO", 100.0, 100)],
        steps=[
            StepSpec(10, "LITHO-1", 2.0),
            StepSpec(20, "LITHO-2", 3.0, metrology_required=True, rework_target_ix=0),
            StepSpec(30, "LITHO-3", 2.0),
        ],
        charts=[ChartSpec(step_ix=1, param_name="CD-20")],
        planned_wafer_starts=10,
        capacity_budget_hours=200.0,
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


# ==========================================================================
# Progression helpers
# ==========================================================================


def open_run(builder: FabBuilder, env: Env, step_ix: int = 0, lot_ix: int = 0) -> Dict[str, Any]:
    """Track a lot in at one step and return the resulting open run."""
    return builder.track_in(
        env.lots[lot_ix]["id"], env.steps[step_ix]["id"], env.operators[0]["id"]
    )


def complete_step(
    builder: FabBuilder,
    env: Env,
    step_ix: int = 0,
    lot_ix: int = 0,
    measured_value: Optional[float] = None,
    chart_ix: int = 0,
) -> Dict[str, Any]:
    """Track in, satisfy metrology if the step demands it, then track out."""
    operator_id = env.operators[0]["id"]
    run = open_run(builder, env, step_ix, lot_ix)
    if env.steps[step_ix].get("metrology_required"):
        value = (
            measured_value
            if measured_value is not None
            else env.charts[chart_ix]["target"]
        )
        builder.measure(run["id"], env.charts[chart_ix]["id"], value, operator_id)
    return builder.track_out(run["id"], operator_id)


def advance_to_at_sort(builder: FabBuilder, env: Env, lot_ix: int = 0) -> List[Dict[str, Any]]:
    """Walk a released lot through every step so it lands at sort."""
    runs = []
    for step_ix in range(len(env.steps)):
        runs.append(complete_step(builder, env, step_ix, lot_ix))
    return runs


def raise_spc_excursion(
    builder: FabBuilder,
    env: Env,
    measured_value: float,
    step_ix: int = 0,
    lot_ix: int = 0,
    chart_ix: int = 0,
) -> Env:
    """Open a run, record one out-of-limit reading, return run and excursion."""
    operator_id = env.operators[0]["id"]
    run = open_run(builder, env, step_ix, lot_ix)
    measurement = builder.measure(
        run["id"], env.charts[chart_ix]["id"], measured_value, operator_id
    )
    excursion = None
    if measurement.get("excursion_id"):
        excursion = builder.read_excursion(measurement["excursion_id"])
    return Env(run=run, measurement=measurement, excursion=excursion)


def raise_particle_excursion(
    builder: FabBuilder, env: Env, particle_reading: float, chamber_ix: int = 0
) -> Env:
    """Record a particle reading and return the chamber plus any excursion."""
    chamber_id = env.chambers[chamber_ix]["id"]
    chamber = builder.particle_reading(chamber_id, particle_reading)
    matches = builder.client.list_excursions(
        quality_manager_headers(), {"chamber_id": chamber_id}
    ).json()["data"]
    excursion = matches[0] if matches else None
    return Env(chamber=chamber, excursion=excursion)


def pm_cycle(builder: FabBuilder, equipment_id: str) -> Dict[str, Any]:
    """Take a tool through maintenance and back to idle."""
    builder.pm_start(equipment_id)
    return builder.pm_complete(equipment_id)


def sorted_run(
    builder: FabBuilder,
    env: Env,
    wafer_results: List[Dict[str, Any]],
    gross_die_per_wafer: int = 100,
    baseline_yield: float = 0.92,
    lot_ix: int = 0,
) -> Dict[str, Any]:
    """Drive a released lot to sort and file its die results."""
    advance_to_at_sort(builder, env, lot_ix)
    return builder.die_sort(
        env.lots[lot_ix]["id"], wafer_results, gross_die_per_wafer, baseline_yield
    )


# ==========================================================================
# pytest fixtures
# ==========================================================================


@pytest.fixture(scope="session", autouse=True)
def _error_status_map():
    """Teach the validators the PRD's error-to-status mapping once."""
    register_error_status_map()


@pytest.fixture
def api() -> FabApiClient:
    """A route-aware client against the server under test."""
    return FabApiClient()


@pytest.fixture
def fab(api: FabApiClient) -> FabBuilder:
    """Builder over a fresh, empty store with the clock pinned at T0."""
    builder = FabBuilder(api)
    builder.set_clock(T0)
    return builder
