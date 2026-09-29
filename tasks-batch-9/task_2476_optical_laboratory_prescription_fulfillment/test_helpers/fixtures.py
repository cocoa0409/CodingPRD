"""Composite setup helpers.

The server is restarted with an empty database before every individual test, so
each helper rebuilds the state it needs from scratch through declared endpoints
only. Helpers return a mutable ``dict`` carrying every id and version captured
along the way, so a caller can start from any tier and keep going.

Two standing scenarios recur throughout the suite:

* the **stock** scenario — a self-pay patient on a single-vision polycarbonate
  design that has stock SKUs, so the route is ``STOCK_EDGE_ONLY`` and no blank
  lot is ever touched; the order grosses 26985 cents;
* the **surfaced** scenario — an insured patient on a progressive high-index
  design with no stock SKU, so the route is ``SURFACE_AND_EDGE``; the expedited
  order grosses 81126 cents provisionally.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_START
from .test_users import (
    BENEFITS_A_HEADERS,
    INSPECTOR_A_HEADERS,
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)

Scenario = Dict[str, Any]


# --------------------------------------------------------------------------
# Tier 1 — primitives
# --------------------------------------------------------------------------


def set_clock(api, instant: str = CLOCK_START) -> str:
    """Move the logical clock, which any role may do."""
    data = get_success_data(
        api.set_clock({"current_utc": instant}, MANAGER_A_HEADERS)
    )
    return data.get("current_utc", instant)


def create_prescriber(api, headers=None, **overrides) -> Scenario:
    data = get_success_data(
        api.create_prescriber(
            f.create_prescriber_payload(**overrides), headers or OPTICIAN_A_HEADERS
        )
    )
    return data


def create_self_pay_patient(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_patient(f.create_patient_payload(**overrides), OPTICIAN_A_HEADERS)
    )


def create_plan(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_insurance_plan(
            f.create_insurance_plan_payload(**overrides), BENEFITS_A_HEADERS
        )
    )


def create_basic_plan(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_insurance_plan(
            f.create_basic_plan_payload(**overrides), BENEFITS_A_HEADERS
        )
    )


def create_insured_patient(api, plan_id: str, **overrides) -> Scenario:
    return get_success_data(
        api.create_patient(
            f.create_insured_patient_payload(plan_id, **overrides), OPTICIAN_A_HEADERS
        )
    )


def create_sv_design(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_lens_design(
            f.create_lens_design_payload(**overrides), MANAGER_A_HEADERS
        )
    )


def create_progressive_design(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_lens_design(
            f.create_progressive_design_payload(**overrides), MANAGER_A_HEADERS
        )
    )


def create_sv_standard(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_tolerance_standard(
            f.create_tolerance_standard_payload(**overrides), MANAGER_A_HEADERS
        )
    )


def create_progressive_standard(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_tolerance_standard(
            f.create_progressive_tolerance_standard_payload(**overrides),
            MANAGER_A_HEADERS,
        )
    )


def create_blank_lot(api, design_id: str, **overrides) -> Scenario:
    return get_success_data(
        api.create_lens_blank_lot(
            f.create_lens_blank_lot_payload(design_id, **overrides), MANAGER_A_HEADERS
        )
    )


def create_generator(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_lab_machine(
            f.create_lab_machine_payload(**overrides), MANAGER_A_HEADERS
        )
    )


def create_bay(api, **overrides) -> Scenario:
    return get_success_data(
        api.create_finishing_bay(
            f.create_finishing_bay_payload(**overrides), MANAGER_A_HEADERS
        )
    )


# --------------------------------------------------------------------------
# Tier 2 — the stock (self-pay, single-vision) entity hierarchy
# --------------------------------------------------------------------------


def stock_registry(api, clock: str = CLOCK_START, **design_overrides) -> Scenario:
    """Clock, prescriber, self-pay patient, single-vision design, its tolerance
    standard and a capacity-1 finishing bay."""
    set_clock(api, clock)
    prescriber = create_prescriber(api)
    patient = create_self_pay_patient(api)
    design = create_sv_design(api, **design_overrides)
    standard = create_sv_standard(api)
    bay = create_bay(api, bay_code="BAY-S", concurrent_capacity=1)
    return {
        "clock": clock,
        "prescriber": prescriber,
        "prescriber_id": prescriber["id"],
        "patient": patient,
        "patient_id": patient["id"],
        "design": design,
        "design_id": design["id"],
        "standard": standard,
        "standard_id": standard["id"],
        "bay": bay,
        "bay_id": bay["id"],
    }


def stock_verified_prescription(
    api, scenario: Optional[Scenario] = None, **rx_overrides
) -> Scenario:
    """The stock registry plus a VERIFIED -2.00/-1.00 x 90 prescription."""
    scenario = scenario or stock_registry(api)
    rx = get_success_data(
        api.create_prescription(
            f.create_prescription_payload(
                scenario["patient_id"], scenario["prescriber_id"], **rx_overrides
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    get_success_data(
        api.verify_prescription(
            rx["id"], f.create_verification_payload(), OPTICIAN_A_HEADERS
        )
    )
    scenario["prescription"] = rx
    scenario["prescription_id"] = rx["id"]
    return scenario


def stock_draft_order(
    api, scenario: Optional[Scenario] = None, **order_overrides
) -> Scenario:
    """A DRAFT / PROVISIONAL_QUOTED self-pay order grossing 26985 cents."""
    scenario = scenario or stock_verified_prescription(api)
    order = get_success_data(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                **order_overrides,
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    scenario["order"] = order
    scenario["order_id"] = order["id"]
    scenario["order_version"] = order["version"]
    return scenario


# --------------------------------------------------------------------------
# Tier 3 — the stock lifecycle
# --------------------------------------------------------------------------


def stock_layout_ready_order(
    api, scenario: Optional[Scenario] = None, **layout_overrides
) -> Scenario:
    """Adds the 58.0 mm layout of record, moving the order to LAYOUT_READY."""
    scenario = scenario or stock_draft_order(api)
    layout = get_success_data(
        api.create_frame_layout(
            f.create_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], **layout_overrides
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    scenario["layout"] = layout
    scenario["layout_id"] = layout["id"]
    scenario["order_version"] = read_order(api, scenario["order_id"])["version"]
    return scenario


def stock_queued_job(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Commits the order, producing a QUEUED STOCK_EDGE_ONLY job."""
    scenario = scenario or stock_layout_ready_order(api)
    job = get_success_data(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        )
    )
    scenario["job"] = job
    scenario["job_id"] = job["id"]
    scenario["job_version"] = job["version"]
    return scenario


def stock_edged_job(
    api,
    scenario: Optional[Scenario] = None,
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T09:00:00Z",
) -> Scenario:
    """Books, starts and completes one edging window, leaving the job EDGED."""
    scenario = scenario or stock_queued_job(api)
    operation = book_edging(api, scenario, window_start, window_end)
    get_success_data(api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    get_success_data(api.complete_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    scenario["operation"] = read_operation(api, operation["id"])
    scenario["operation_id"] = operation["id"]
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    return scenario


def stock_passed_job(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Records both on-prescription eye inspections, driving the job to PASSED."""
    scenario = scenario or stock_edged_job(api)
    od = inspect_eye(api, scenario["job_id"], "OD")
    os_ = inspect_eye(api, scenario["job_id"], "OS")
    scenario["inspection_od"] = od
    scenario["inspection_od_id"] = od["id"]
    scenario["inspection_os"] = os_
    scenario["inspection_os_id"] = os_["id"]
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    return scenario


def stock_released_job(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Releases the passed job, so the order reaches LAB_COMPLETE."""
    scenario = scenario or stock_passed_job(api)
    get_success_data(api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS))
    scenario["job"] = read_job(api, scenario["job_id"])
    scenario["job_version"] = scenario["job"]["version"]
    scenario["order"] = read_order(api, scenario["order_id"])
    scenario["order_version"] = scenario["order"]["version"]
    return scenario


def stock_self_pay_final_order(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Finalises the self-pay quote, leaving 26985 cents outstanding."""
    scenario = scenario or stock_released_job(api)
    order = get_success_data(
        api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    scenario["order"] = order
    scenario["order_version"] = order["version"]
    return scenario


def stock_settled_order(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Pays the whole self-pay balance, moving billing to PATIENT_SETTLED."""
    scenario = scenario or stock_self_pay_final_order(api)
    order = get_success_data(
        api.settle_patient_portion(
            scenario["order_id"],
            f.create_settlement_payload(scenario["order"]["patient_balance_due_cents"]),
            OPTICIAN_A_HEADERS,
        )
    )
    scenario["order"] = order
    scenario["order_version"] = order["version"]
    return scenario


# --------------------------------------------------------------------------
# Tier 2/3 — the surfaced (insured, progressive) hierarchy and lifecycle
# --------------------------------------------------------------------------


def surfaced_registry(api, clock: str = CLOCK_START, **plan_overrides) -> Scenario:
    """Clock, prescriber, capped vision plan, insured patient, progressive
    design, its tolerance standard, an 80.0 mm blank lot of two, a generator
    with the default 15-minute buffer and a capacity-2 finishing bay."""
    set_clock(api, clock)
    prescriber = create_prescriber(api, MANAGER_A_HEADERS)
    plan = create_plan(api, **plan_overrides)
    patient = create_insured_patient(api, plan["id"])
    design = create_progressive_design(api)
    standard = create_progressive_standard(api)
    lot = create_blank_lot(api, design["id"])
    machine = create_generator(api)
    bay = create_bay(api)
    return {
        "clock": clock,
        "prescriber": prescriber,
        "prescriber_id": prescriber["id"],
        "plan": plan,
        "plan_id": plan["id"],
        "patient": patient,
        "patient_id": patient["id"],
        "design": design,
        "design_id": design["id"],
        "standard": standard,
        "standard_id": standard["id"],
        "lot": lot,
        "lot_id": lot["id"],
        "machine": machine,
        "machine_id": machine["id"],
        "bay": bay,
        "bay_id": bay["id"],
    }


def surfaced_verified_prescription(
    api, scenario: Optional[Scenario] = None, **rx_overrides
) -> Scenario:
    scenario = scenario or surfaced_registry(api)
    rx = get_success_data(
        api.create_prescription(
            f.create_multifocal_prescription_payload(
                scenario["patient_id"], scenario["prescriber_id"], **rx_overrides
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    get_success_data(
        api.verify_prescription(
            rx["id"], f.create_verification_payload(), OPTICIAN_A_HEADERS
        )
    )
    scenario["prescription"] = rx
    scenario["prescription_id"] = rx["id"]
    return scenario


def surfaced_draft_order(
    api, scenario: Optional[Scenario] = None, **order_overrides
) -> Scenario:
    """The expedited progressive order grossing 81126 cents provisionally."""
    scenario = scenario or surfaced_verified_prescription(api)
    order = get_success_data(
        api.create_rx_order(
            f.create_progressive_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                **order_overrides,
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    scenario["order"] = order
    scenario["order_id"] = order["id"]
    scenario["order_version"] = order["version"]
    return scenario


def surfaced_layout_ready_order(
    api, scenario: Optional[Scenario] = None, **layout_overrides
) -> Scenario:
    """Adds the 77.0 mm layout of record."""
    scenario = scenario or surfaced_draft_order(api)
    layout = get_success_data(
        api.create_frame_layout(
            f.create_progressive_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], **layout_overrides
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    scenario["layout"] = layout
    scenario["layout_id"] = layout["id"]
    scenario["order_version"] = read_order(api, scenario["order_id"])["version"]
    return scenario


def surfaced_queued_job(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Commits the order, reserving one blank from the 80.0 mm lot."""
    scenario = scenario or surfaced_layout_ready_order(api)
    job = get_success_data(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        )
    )
    scenario["job"] = job
    scenario["job_id"] = job["id"]
    scenario["job_version"] = job["version"]
    return scenario


def surfaced_surfaced_job(
    api,
    scenario: Optional[Scenario] = None,
    window_start: str = "2026-08-01T09:00:00Z",
    window_end: str = "2026-08-01T10:00:00Z",
) -> Scenario:
    """Runs the surfacing window to completion, leaving the job SURFACED."""
    scenario = scenario or surfaced_queued_job(api)
    operation = book_surfacing(api, scenario, window_start, window_end)
    get_success_data(api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    get_success_data(api.complete_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    scenario["surfacing_operation_id"] = operation["id"]
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    return scenario


def surfaced_edged_job(
    api,
    scenario: Optional[Scenario] = None,
    window_start: str = "2026-08-01T11:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
) -> Scenario:
    """Runs the edging window to completion, leaving the job EDGED."""
    scenario = scenario or surfaced_surfaced_job(api)
    operation = book_edging(api, scenario, window_start, window_end)
    get_success_data(api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    get_success_data(api.complete_lab_operation(operation["id"], TECHNICIAN_A_HEADERS))
    scenario["edging_operation_id"] = operation["id"]
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    return scenario


def surfaced_passed_job(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Inspects OD at -3.13 (delta 0.13, exactly on tolerance) and OS on
    prescription, driving the job to PASSED."""
    scenario = scenario or surfaced_edged_job(api)
    od = inspect_eye(
        api,
        scenario["job_id"],
        "OD",
        measured_sphere=-3.13,
        measured_cylinder=-1.25,
        measured_axis=90,
        measured_prism=0.5,
    )
    os_ = inspect_eye(
        api,
        scenario["job_id"],
        "OS",
        measured_sphere=-2.75,
        measured_cylinder=-1.0,
        measured_axis=85,
        measured_prism=0.0,
    )
    scenario["inspection_od"] = od
    scenario["inspection_od_id"] = od["id"]
    scenario["inspection_os"] = os_
    scenario["inspection_os_id"] = os_["id"]
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    return scenario


def surfaced_released_job(api, scenario: Optional[Scenario] = None) -> Scenario:
    scenario = scenario or surfaced_passed_job(api)
    get_success_data(api.release_lab_job(scenario["job_id"], TECHNICIAN_A_HEADERS))
    scenario["job"] = read_job(api, scenario["job_id"])
    scenario["job_version"] = scenario["job"]["version"]
    scenario["order"] = read_order(api, scenario["order_id"])
    scenario["order_version"] = scenario["order"]["version"]
    return scenario


def surfaced_benefit_applied_order(
    api, scenario: Optional[Scenario] = None
) -> Scenario:
    """Applies the insurance benefit, producing the FINAL quote."""
    scenario = scenario or surfaced_released_job(api)
    order = get_success_data(
        api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    scenario["order"] = order
    scenario["order_version"] = order["version"]
    return scenario


def surfaced_settled_order(api, scenario: Optional[Scenario] = None) -> Scenario:
    """Clears the whole patient balance, moving billing to PATIENT_SETTLED."""
    scenario = scenario or surfaced_benefit_applied_order(api)
    order = get_success_data(
        api.settle_patient_portion(
            scenario["order_id"],
            f.create_settlement_payload(scenario["order"]["patient_balance_due_cents"]),
            OPTICIAN_A_HEADERS,
        )
    )
    scenario["order"] = order
    scenario["order_version"] = order["version"]
    return scenario


# --------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# --------------------------------------------------------------------------


def stock_remake_pending_order(
    api, scenario: Optional[Scenario] = None, **case_overrides
) -> Scenario:
    """Opens a remake case on the released stock job, so the order sits in
    REMAKE_PENDING with remake_count 1."""
    scenario = scenario or stock_released_job(api)
    payload = f.create_remake_case_payload(scenario["job_id"], **case_overrides)
    case = get_success_data(api.create_remake_case(payload, OPTICIAN_A_HEADERS))
    scenario.setdefault("cases", []).append(case)
    scenario["case"] = case
    scenario["case_id"] = case["id"]
    scenario["first_job_id"] = scenario["job_id"]
    scenario["order"] = read_order(api, scenario["order_id"])
    scenario["order_version"] = scenario["order"]["version"]
    return scenario


def stock_replacement_job(api, scenario: Scenario) -> Scenario:
    """Commits a replacement job from REMAKE_PENDING, returning the order to
    IN_LAB."""
    job = get_success_data(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        )
    )
    scenario["job"] = job
    scenario["job_id"] = job["id"]
    scenario["job_version"] = job["version"]
    scenario.setdefault("jobs", []).append(job)
    return scenario


def stock_replacement_released_job(
    api,
    scenario: Scenario,
    window_start: str = "2026-08-01T10:00:00Z",
    window_end: str = "2026-08-01T11:00:00Z",
) -> Scenario:
    """Drives the replacement job all the way to RELEASED, so the order returns
    to LAB_COMPLETE."""
    scenario = stock_replacement_job(api, scenario)
    scenario = stock_edged_job(api, scenario, window_start, window_end)
    scenario = stock_passed_job(api, scenario)
    return stock_released_job(api, scenario)


def near_cap_insured_scenario(api, cap_cents: int) -> Scenario:
    """A basic-plan patient whose annual cap is exactly consumed by one order
    carried through to BENEFIT_APPLIED."""
    set_clock(api)
    prescriber = create_prescriber(api)
    plan = create_basic_plan(api, plan_code="CAP-TIGHT", annual_benefit_cap_cents=cap_cents)
    patient = create_insured_patient(api, plan["id"])
    design = create_sv_design(api)
    standard = create_sv_standard(api)
    bay = create_bay(api, bay_code="BAY-S", concurrent_capacity=1)
    scenario: Scenario = {
        "clock": CLOCK_START,
        "prescriber": prescriber,
        "prescriber_id": prescriber["id"],
        "plan": plan,
        "plan_id": plan["id"],
        "patient": patient,
        "patient_id": patient["id"],
        "design": design,
        "design_id": design["id"],
        "standard": standard,
        "standard_id": standard["id"],
        "bay": bay,
        "bay_id": bay["id"],
    }
    scenario = stock_verified_prescription(api, scenario)
    scenario = stock_draft_order(api, scenario)
    scenario = stock_layout_ready_order(api, scenario)
    scenario = stock_queued_job(api, scenario)
    first_order = get_success_data(
        api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    scenario["first_order"] = first_order
    scenario["first_order_id"] = first_order["id"]
    return scenario


def second_order_on_same_prescription(api, scenario: Scenario) -> Scenario:
    """Opens a second order on the same still-valid prescription and commits it
    so its route is known."""
    order = get_success_data(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
            ),
            OPTICIAN_A_HEADERS,
        )
    )
    layout = get_success_data(
        api.create_frame_layout(
            f.create_frame_layout_payload(order["id"], order["version"]),
            OPTICIAN_A_HEADERS,
        )
    )
    job = get_success_data(
        api.create_lab_job(f.create_lab_job_payload(order["id"]), TECHNICIAN_A_HEADERS)
    )
    scenario["second_order"] = order
    scenario["second_order_id"] = order["id"]
    scenario["second_layout_id"] = layout["id"]
    scenario["second_job_id"] = job["id"]
    return scenario


def failing_inspection_rework_cycle(
    api,
    scenario: Scenario,
    eye: str = "OD",
    measured_sphere: float = -2.30,
    window_start: str = "2026-08-01T10:00:00Z",
    window_end: str = "2026-08-01T11:00:00Z",
) -> Scenario:
    """Fails one eye, then re-edges the rework-queued job back to EDGED."""
    failing = inspect_eye(
        api, scenario["job_id"], eye, measured_sphere=measured_sphere
    )
    scenario.setdefault("failing_inspections", []).append(failing)
    scenario["failing_inspection"] = failing
    scenario["failing_inspection_id"] = failing["id"]
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    return stock_edged_job(api, scenario, window_start, window_end)


# --------------------------------------------------------------------------
# Tier 5 — booking and read shortcuts
# --------------------------------------------------------------------------


def book_edging(
    api,
    scenario: Scenario,
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T09:00:00Z",
    bay_id: Optional[str] = None,
    headers=None,
) -> Scenario:
    """Books one edging window, re-reading the job version first because every
    booking bumps it."""
    version = read_job(api, scenario["job_id"])["version"]
    operation = get_success_data(
        api.create_lab_operation(
            f.create_edging_operation_payload(
                scenario["job_id"],
                version,
                bay_id or scenario["bay_id"],
                window_start,
                window_end,
            ),
            headers or TECHNICIAN_A_HEADERS,
        )
    )
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    scenario.setdefault("operations", []).append(operation)
    return operation


def book_surfacing(
    api,
    scenario: Scenario,
    window_start: str = "2026-08-01T09:00:00Z",
    window_end: str = "2026-08-01T10:00:00Z",
    machine_id: Optional[str] = None,
    headers=None,
) -> Scenario:
    version = read_job(api, scenario["job_id"])["version"]
    operation = get_success_data(
        api.create_lab_operation(
            f.create_surfacing_operation_payload(
                scenario["job_id"],
                version,
                machine_id or scenario["machine_id"],
                window_start,
                window_end,
            ),
            headers or TECHNICIAN_A_HEADERS,
        )
    )
    scenario["job_version"] = read_job(api, scenario["job_id"])["version"]
    scenario.setdefault("operations", []).append(operation)
    return operation


def inspect_eye(api, job_id: str, eye: str, headers=None, **overrides) -> Scenario:
    return get_success_data(
        api.create_quality_inspection(
            f.create_quality_inspection_payload(job_id, eye, **overrides),
            headers or INSPECTOR_A_HEADERS,
        )
    )


def read_order(api, order_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_rx_order(order_id, headers or OPTICIAN_A_HEADERS)
    )


def read_job(api, job_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_lab_job(job_id, headers or TECHNICIAN_A_HEADERS)
    )


def read_operation(api, operation_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_lab_operation(operation_id, headers or TECHNICIAN_A_HEADERS)
    )


def read_lot(api, lot_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_lens_blank_lot(lot_id, headers or MANAGER_A_HEADERS)
    )


def read_patient(api, patient_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_patient(patient_id, headers or OPTICIAN_A_HEADERS)
    )


def read_prescriber(api, prescriber_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_prescriber(prescriber_id, headers or OPTICIAN_A_HEADERS)
    )


def read_prescription(api, rx_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_prescription(rx_id, headers or OPTICIAN_A_HEADERS)
    )


def read_layout(api, layout_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_frame_layout(layout_id, headers or OPTICIAN_A_HEADERS)
    )


def read_inspection(api, inspection_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_quality_inspection(inspection_id, headers or MANAGER_A_HEADERS)
    )


def read_case(api, case_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_remake_case(case_id, headers or MANAGER_A_HEADERS)
    )


def read_charge_summary(api, order_id: str, headers=None) -> Scenario:
    return get_success_data(
        api.get_charge_summary(order_id, headers or OPTICIAN_A_HEADERS)
    )
