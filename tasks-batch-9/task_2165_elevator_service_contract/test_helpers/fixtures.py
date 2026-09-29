"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only: the harness restarts the API server before each test, so each test starts
against an empty database with the logical clock at its 2026-08-01T00:00:00Z
startup value.

Setup calls use the lenient `get_success_data` validator so a broken precondition
surfaces as an explicit "Setup step failed" rather than a confusing assertion.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FULL_MAINTENANCE_REQUIRED_TASK_CODES
from .factories import (
    counter_renegotiation_payload,
    create_callback_payload,
    create_car_payload,
    create_contract_payload,
    create_downtime_window_payload,
    create_inspection_payload,
    create_part_order_payload,
    create_part_payload,
    create_penalty_payload,
    create_project_payload,
    create_renegotiation_payload,
    create_visit_payload,
    full_maintenance_task_items,
    task_items,
)
from .test_users import (
    DEFAULT_ADMIN_USER_ID,
    SECOND_ADMIN_USER_ID,
    make_admin_headers,
    make_building_manager_headers,
    make_contractor_headers,
    make_dispatcher_headers,
    make_inspector_headers,
)


# ─── Tier 0: primitives ──────────────────────────────────────────────────────

def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Advance the logical clock and return the sweep counters."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or make_admin_headers())
    )


def read_contract(contract_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_contract(contract_id, headers or make_admin_headers())
    )


def read_car(car_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_car(car_id, headers or make_admin_headers()))


def read_visit(visit_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_visit(visit_id, headers or make_admin_headers())
    )


def read_callback(callback_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_callback(callback_id, headers or make_admin_headers())
    )


def read_inspection(inspection_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_inspection(inspection_id, headers or make_admin_headers())
    )


def read_project(project_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_project(project_id, headers or make_admin_headers())
    )


def read_window(window_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_downtime_window(window_id, headers or make_admin_headers())
    )


def read_part(part_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_part(part_id, headers or make_admin_headers())
    )


def read_part_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_part_order(order_id, headers or make_admin_headers())
    )


def read_penalty(penalty_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_penalty(penalty_id, headers or make_admin_headers())
    )


def read_round(round_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_renegotiation(round_id, headers or make_admin_headers())
    )


def contract_version(contract_id: str) -> int:
    """Fresh read of the contract's OCC version."""
    return read_contract(contract_id)["version"]


def car_version(car_id: str) -> int:
    """Fresh read of the car's OCC version."""
    return read_car(car_id)["version"]


# ─── Tier 1: contract standing up ────────────────────────────────────────────

class Program:
    """A stood-up elevator program: one contract plus its role headers and cars."""

    def __init__(self, contract: dict, admin_user_id: str = DEFAULT_ADMIN_USER_ID):
        self.contract = contract
        self.contract_id = contract["id"]
        self.admin_user_id = admin_user_id
        self.manager_user_id = contract["building_manager_user_id"]
        self.contractor_user_id = contract["contractor_user_id"]
        self.admin_headers = make_admin_headers(admin_user_id)
        self.second_admin_headers = make_admin_headers(SECOND_ADMIN_USER_ID)
        self.manager_headers = make_building_manager_headers(self.manager_user_id)
        self.contractor_headers = make_contractor_headers(self.contractor_user_id)
        self.inspector_headers = make_inspector_headers()
        self.dispatcher_headers = make_dispatcher_headers()
        self.cars: List[dict] = []

    # -- convenience reads -------------------------------------------------
    def refresh(self) -> dict:
        self.contract = read_contract(self.contract_id, self.admin_headers)
        return self.contract

    @property
    def version(self) -> int:
        return contract_version(self.contract_id)

    def car(self, index: int = 0) -> dict:
        return self.cars[index]

    def car_id(self, index: int = 0) -> str:
        return self.cars[index]["id"]


def create_draft_contract(admin_user_id: str = DEFAULT_ADMIN_USER_ID, **overrides) -> dict:
    """Create one ServiceContract; it lands in DRAFT with version 1."""
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(**overrides), make_admin_headers(admin_user_id)
        )
    )


def create_active_contract(
    admin_user_id: str = DEFAULT_ADMIN_USER_ID, **overrides
) -> dict:
    """Create a contract and activate it (DRAFT -> ACTIVE)."""
    contract = create_draft_contract(admin_user_id, **overrides)
    return get_success_data(
        api_client.activate_contract(contract["id"], make_admin_headers(admin_user_id))
    )


def setup_program(
    car_codes: Optional[List[str]] = None,
    activate: bool = True,
    admin_user_id: str = DEFAULT_ADMIN_USER_ID,
    **contract_overrides,
) -> Program:
    """Stand up one contract (activated by default) plus the named cars.

    `car_codes` are registered in the order given; the PRD pins `car_code`
    ascending as the iteration order for every per-car calculation.
    """
    if activate:
        contract = create_active_contract(admin_user_id, **contract_overrides)
    else:
        contract = create_draft_contract(admin_user_id, **contract_overrides)
    program = Program(contract, admin_user_id)
    for code in car_codes or []:
        add_car(program, code)
    return program


def add_car(program: Program, car_code: str, **overrides) -> dict:
    """Register one ElevatorCar under the program's contract."""
    car = get_success_data(
        api_client.create_car(
            create_car_payload(program.contract_id, car_code=car_code, **overrides),
            program.admin_headers,
        )
    )
    program.cars.append(car)
    return car


# ─── Tier 2: callbacks ───────────────────────────────────────────────────────

def report_callback(program: Program, car_id: str, **overrides) -> dict:
    """Report one callback against a car (status REPORTED)."""
    return get_success_data(
        api_client.create_callback(
            create_callback_payload(car_id, **overrides), program.manager_headers
        )
    )


def run_callback_cycle(
    program: Program,
    car_id: str,
    reported_at: str,
    arrived_at: str,
    cleared_at: Optional[str] = None,
    callback_type: str = "MALFUNCTION",
    out_of_service: bool = True,
    passengers_trapped: Optional[int] = None,
    incident_number: Optional[str] = None,
    resolution_note: str = "resolved",
) -> dict:
    """Drive one callback REPORTED -> (ESCALATED) -> ON_SITE -> CLEARED.

    The clock is moved to `reported_at` before the report and to `arrived_at`
    before the arrival, so `response_minutes` is exactly the gap between them.
    An ENTRAPMENT callback is escalated to the fire department first, as the PRD
    requires before arrival.
    """
    set_clock(reported_at, program.admin_headers)
    overrides: Dict[str, object] = {
        "callback_type": callback_type,
        "out_of_service": out_of_service,
    }
    if passengers_trapped is not None:
        overrides["passengers_trapped"] = passengers_trapped
    callback = report_callback(program, car_id, **overrides)

    if callback_type == "ENTRAPMENT":
        get_success_data(
            api_client.fire_dispatch_callback(
                callback["id"],
                {"incident_number": incident_number or "FD-2026-0001"},
                program.dispatcher_headers,
            )
        )

    set_clock(arrived_at, program.admin_headers)
    get_success_data(
        api_client.arrive_callback(callback["id"], program.contractor_headers)
    )
    if cleared_at is not None:
        set_clock(cleared_at, program.admin_headers)
    return get_success_data(
        api_client.clear_callback(
            callback["id"], program.contractor_headers, {"resolution_note": resolution_note}
        )
    )


# ─── Tier 3: maintenance visits ──────────────────────────────────────────────

def schedule_visit(
    program: Program,
    car_id: str,
    period_month: str = "2026-08",
    scheduled_date: str = "2026-08-15",
) -> dict:
    """Schedule the monthly maintenance visit for one car and one billing month."""
    return get_success_data(
        api_client.create_visit(
            create_visit_payload(
                car_id, period_month=period_month, scheduled_date=scheduled_date
            ),
            program.admin_headers,
        )
    )


def perform_visit(program: Program, visit_id: str, items: Optional[List[dict]] = None) -> dict:
    """Record a performed task list (defaults to the full FULL_MAINTENANCE list)."""
    return get_success_data(
        api_client.perform_visit(
            visit_id,
            {"task_items": items if items is not None else full_maintenance_task_items()},
            program.contractor_headers,
        )
    )


def schedule_and_perform_visit(
    program: Program,
    car_id: str,
    period_month: str = "2026-08",
    scheduled_date: str = "2026-08-15",
    items: Optional[List[dict]] = None,
) -> dict:
    """Schedule then perform a visit; returns the PERFORMED visit."""
    visit = schedule_visit(program, car_id, period_month, scheduled_date)
    return perform_visit(program, visit["id"], items)


def dispute_visit(program: Program, visit_id: str, reason: str = "rework required") -> dict:
    return get_success_data(
        api_client.dispute_visit(
            visit_id, {"dispute_reason": reason}, program.manager_headers
        )
    )


def run_rework_loop(program: Program, visit_id: str, rounds: int = 2) -> dict:
    """Drive the PERFORMED <-> DISPUTED loop `rounds` times.

    Leaves the visit PERFORMED with rework_count == rounds.
    """
    visit = None
    for index in range(rounds):
        dispute_visit(program, visit_id, f"rework {index + 1}")
        visit = perform_visit(
            program, visit_id, task_items(FULL_MAINTENANCE_REQUIRED_TASK_CODES, True, f"pass {index + 2}")
        )
    return visit


# ─── Tier 4: inspections and certificates ────────────────────────────────────

def schedule_inspection(
    program: Program,
    car_id: str,
    inspection_type: str = "PERIODIC",
    scheduled_date: str = "2026-08-01",
) -> dict:
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                car_id, inspection_type=inspection_type, scheduled_date=scheduled_date
            ),
            program.admin_headers,
        )
    )


def record_result(
    program: Program,
    inspection_id: str,
    result: str,
    deficiency_codes: Optional[List[str]] = None,
) -> dict:
    return get_success_data(
        api_client.record_inspection_result(
            inspection_id,
            {"result": result, "deficiency_codes": deficiency_codes or []},
            program.inspector_headers,
        )
    )


def inspect_with_result(
    program: Program,
    car_id: str,
    result: str,
    inspection_type: str = "PERIODIC",
    scheduled_date: str = "2026-08-01",
    deficiency_codes: Optional[List[str]] = None,
) -> dict:
    """Schedule an inspection and record `result` on it in one step."""
    inspection = schedule_inspection(program, car_id, inspection_type, scheduled_date)
    return record_result(program, inspection["id"], result, deficiency_codes)


def red_tag_car(
    program: Program, car_id: str, scheduled_date: str = "2026-08-01"
) -> dict:
    """Drive a car to RED_TAGGED (and therefore OUT_OF_SERVICE) with a FAIL result."""
    return inspect_with_result(
        program, car_id, "FAIL", "PERIODIC", scheduled_date, ["ROPE-09"]
    )


def issue_certificate(
    program: Program,
    car_id: str,
    inspection_type: str = "PERIODIC",
    scheduled_date: str = "2026-08-01",
    result: str = "PASS",
) -> dict:
    """Record a passing result so the certificate reaches ISSUED."""
    return inspect_with_result(
        program, car_id, result, inspection_type, scheduled_date
    )


def issue_and_post_certificate(
    program: Program,
    car_id: str,
    inspection_type: str = "PERIODIC",
    scheduled_date: str = "2026-08-01",
    result: str = "PASS",
) -> dict:
    """Issue a certificate and post it in the car, driving the car to CERTIFIED."""
    inspection = issue_certificate(
        program, car_id, inspection_type, scheduled_date, result
    )
    return get_success_data(
        api_client.post_certificate(inspection["id"], program.manager_headers)
    )


# ─── Tier 5: projects and downtime windows ───────────────────────────────────

def plan_project(program: Program, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(
            create_project_payload(program.contract_id, **overrides),
            program.admin_headers,
        )
    )


def plan_and_approve_project(program: Program, **overrides) -> dict:
    """Plan a modernization project and approve it (PLANNED -> APPROVED)."""
    project = plan_project(program, **overrides)
    return get_success_data(
        api_client.approve_project(project["id"], program.manager_headers)
    )


def add_window(
    program: Program,
    car_id: str,
    window_start: str,
    window_end: str,
    window_type: str = "REPAIR",
    project_id: Optional[str] = None,
) -> dict:
    """Reserve one downtime window on a car."""
    return get_success_data(
        api_client.create_downtime_window(
            create_downtime_window_payload(
                car_id, window_start, window_end, window_type, project_id
            ),
            program.admin_headers,
        )
    )


# ─── Tier 6: spare parts and orders ──────────────────────────────────────────

def add_part(
    part_number: str,
    unit_price_cents: int,
    lead_time_days: int,
    part_class: str = "COMPONENT",
    description_text: str = "Catalog part",
    headers: Optional[dict] = None,
) -> dict:
    """Add one ACTIVE catalog part."""
    return get_success_data(
        api_client.create_part(
            create_part_payload(
                part_number=part_number,
                description_text=description_text,
                part_class=part_class,
                unit_price_cents=unit_price_cents,
                lead_time_days=lead_time_days,
            ),
            headers or make_admin_headers(),
        )
    )


def obsolete_part(
    part_id: str, replacement_part_id: Optional[str] = None, headers: Optional[dict] = None
) -> dict:
    """Retire a part: OBSOLETE with a successor, or DISCONTINUED without one."""
    payload = {} if replacement_part_id is None else {"replacement_part_id": replacement_part_id}
    return get_success_data(
        api_client.obsolete_part(part_id, headers or make_admin_headers(), payload)
    )


def build_supersession_chain(
    prefix: str,
    length: int,
    unit_price_cents: int = 100_000,
    lead_time_days: int = 10,
    part_class: str = "COMPONENT",
) -> List[dict]:
    """Create `length` catalog parts and chain each onto the next as its successor.

    The last part stays ACTIVE; every earlier part becomes OBSOLETE pointing at
    its immediate successor, so ordering the first part walks `length - 1` hops.
    """
    parts = [
        add_part(
            part_number=f"{prefix}-P{index + 1}",
            unit_price_cents=unit_price_cents,
            lead_time_days=lead_time_days,
            part_class=part_class,
            description_text=f"Generation {index + 1}",
        )
        for index in range(length)
    ]
    for index in range(length - 2, -1, -1):
        obsolete_part(parts[index]["id"], parts[index + 1]["id"])
    return parts


def order_part(
    program: Program,
    car_id: str,
    part_id: str,
    quantity: int = 1,
    expedite: Optional[bool] = None,
    window_id: Optional[str] = None,
    expected_car_version: Optional[int] = None,
) -> dict:
    """Create a PartOrder, reading the car's current version unless one is given."""
    version = (
        expected_car_version if expected_car_version is not None else car_version(car_id)
    )
    payload = create_part_order_payload(car_id, part_id, version, quantity=quantity)
    if expedite is not None:
        payload["expedite"] = expedite
    if window_id is not None:
        payload["window_id"] = window_id
    return get_success_data(
        api_client.create_part_order(payload, program.contractor_headers)
    )


# ─── Tier 7: penalties ───────────────────────────────────────────────────────

def assess_penalty(
    program: Program, period_month: str = "2026-08", headers: Optional[dict] = None
) -> dict:
    """Assess a closed month, reading the contract's current version first."""
    return get_success_data(
        api_client.create_penalty(
            create_penalty_payload(
                program.contract_id, period_month, contract_version(program.contract_id)
            ),
            headers or program.admin_headers,
        )
    )


def dispute_penalty(
    program: Program, penalty_id: str, reason: str = "outage was owner-caused"
) -> dict:
    return get_success_data(
        api_client.dispute_penalty(
            penalty_id, {"dispute_reason": reason}, program.manager_headers
        )
    )


def assess_and_dispute_penalty(
    program: Program, period_month: str = "2026-08", reason: str = "disputed"
) -> dict:
    """Issue an assessment and drive it ISSUED -> DISPUTED."""
    penalty = assess_penalty(program, period_month)
    return dispute_penalty(program, penalty["id"], reason)


# ─── Tier 8: performance score and renegotiation ─────────────────────────────

def setup_contract_scoring_fifty(
    car_code: str = "CAR-01",
    manager_user_id: str = "bm-1",
    contractor_user_id: str = "sc-1",
    **contract_overrides,
) -> Program:
    """Build a program whose 2026-08 performance score evaluates to exactly 50.00.

    One car with no downtime windows and one callback reported with
    `out_of_service` false, so August uptime is 100.00; that callback is cleared
    120 minutes after it was reported against a 60-minute allowance, so the
    response component is 0.00; one August visit is left SCHEDULED and swept to
    MISSED, so the visit component is 0.00; the penalty ledger is untouched, so
    the drag term is 0.00. The clock is left at 2026-09-15T00:00:00Z, making
    2026-08 the scoring month.
    """
    overrides = dict(contract_overrides)
    overrides.setdefault("building_manager_user_id", manager_user_id)
    overrides.setdefault("contractor_user_id", contractor_user_id)
    program = setup_program([car_code], **overrides)
    car_id = program.car_id()
    schedule_visit(program, car_id, "2026-08", "2026-08-15")
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-04T09:00:00Z",
        arrived_at="2026-08-04T11:00:00Z",
        out_of_service=False,
        resolution_note="late",
    )
    set_clock("2026-09-15T00:00:00Z", program.admin_headers)
    return program


def open_renegotiation(program: Program, **overrides) -> dict:
    """Open a renegotiation round on behalf of the contract's BuildingManager."""
    return get_success_data(
        api_client.create_renegotiation(
            create_renegotiation_payload(program.contract_id, **overrides),
            program.manager_headers,
        )
    )


def counter_round(
    program: Program, round_id: str, as_contractor: bool = True, **overrides
) -> dict:
    """Counter an OPEN round, spawning its successor round."""
    headers = program.contractor_headers if as_contractor else program.manager_headers
    return get_success_data(
        api_client.counter_renegotiation(
            round_id, counter_renegotiation_payload(**overrides), headers
        )
    )


def setup_renegotiation_in_progress(
    counters: int = 0, **contract_overrides
) -> Dict[str, object]:
    """Open a renegotiation on a score-50.00 contract and counter it `counters` times.

    Returns {"program": Program, "rounds": [round, ...]}; the last round is OPEN
    and the contract sits in UNDER_RENEGOTIATION.
    """
    program = setup_contract_scoring_fifty(**contract_overrides)
    rounds = [open_renegotiation(program)]
    for index in range(counters):
        rounds.append(
            counter_round(
                program,
                rounds[-1]["id"],
                as_contractor=(index % 2 == 0),
                proposed_monthly_fee_cents=380_000 + index * 5_000,
            )
        )
    return {"program": program, "rounds": rounds}


def setup_performed_visit_then_open_renegotiation(
    car_code: str = "CAR-O1",
    manager_user_id: str = "bm-o",
    contractor_user_id: str = "sc-o",
    **contract_overrides,
) -> Dict[str, object]:
    """Build a contract parked in UNDER_RENEGOTIATION with a still-PERFORMED visit.

    August carries one cleared callback answered 120 minutes after it was reported
    against a 60-minute allowance (reported with `out_of_service` false so uptime
    stays 100.00) and one visit performed with the complete FULL_MAINTENANCE task
    list, so the 2026-08 score is 50.00 and a renegotiation may be opened. The
    visit is left PERFORMED and never verified.

    Returns {"program": Program, "visit": visit, "round": round}.
    """
    overrides = dict(contract_overrides)
    overrides.setdefault("building_manager_user_id", manager_user_id)
    overrides.setdefault("contractor_user_id", contractor_user_id)
    program = setup_program([car_code], **overrides)
    car_id = program.car_id()
    visit = schedule_visit(program, car_id, "2026-08", "2026-08-20")
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-04T09:00:00Z",
        arrived_at="2026-08-04T11:00:00Z",
        out_of_service=False,
        resolution_note="late",
    )
    set_clock("2026-08-20T10:00:00Z", program.admin_headers)
    visit = perform_visit(program, visit["id"])
    set_clock("2026-09-15T00:00:00Z", program.admin_headers)
    opened = open_renegotiation(
        program,
        proposed_monthly_fee_cents=340_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    return {"program": program, "visit": visit, "round": opened}


def setup_late_callback_month(
    car_code: str = "CAR-01",
    monthly_base_fee_cents: int = 480_000,
    out_of_service: bool = False,
    **contract_overrides,
) -> Program:
    """One car and one August callback answered 120 minutes after it was reported.

    The contract allows 60 response minutes, so the callback breaches its SLA and
    counts once toward `late_callback_count`. Reported with `out_of_service` false
    by default, so August uptime stays 100.00. The clock is left at
    2026-09-01T00:00:00Z, closing 2026-08.
    """
    overrides = dict(contract_overrides)
    overrides.setdefault("monthly_base_fee_cents", monthly_base_fee_cents)
    program = setup_program([car_code], **overrides)
    run_callback_cycle(
        program,
        program.car_id(),
        reported_at="2026-08-04T09:00:00Z",
        arrived_at="2026-08-04T11:00:00Z",
        out_of_service=out_of_service,
        resolution_note="late arrival",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)
    return program


def setup_two_schedules_with_identical_incidents() -> Dict[str, Program]:
    """Two contracts carrying byte-identical incident data under the two schedules.

    Each contract is FULL_MAINTENANCE with a 480,000-cent monthly fee and one car
    holding one 2880-minute REPAIR window inside 2026-08 and one cleared
    out-of-service MALFUNCTION callback answered 360 minutes after it was reported
    against a 60-minute allowance. The only difference between them is
    `penalty_schedule`. The clock is left at 2026-09-01T00:00:00Z.

    Returns {"schedule_a": Program, "schedule_b": Program}.
    """
    program_a = setup_program(
        ["CAR-A1"],
        building_name="Alpha House",
        building_address="2 Alpha Ave",
        building_manager_user_id="bm-a",
        contractor_user_id="sc-a",
        penalty_schedule="SCHEDULE_A",
        monthly_base_fee_cents=480_000,
        term_end_date="2026-12-31",
    )
    program_b = setup_program(
        ["CAR-B1"],
        building_name="Beta House",
        building_address="3 Beta Ave",
        building_manager_user_id="bm-b",
        contractor_user_id="sc-b",
        penalty_schedule="SCHEDULE_B",
        monthly_base_fee_cents=480_000,
        term_end_date="2026-12-31",
    )
    add_window(
        program_a,
        program_a.car_id(),
        "2026-08-10T08:00:00Z",
        "2026-08-12T08:00:00Z",
        "REPAIR",
    )
    add_window(
        program_b,
        program_b.car_id(),
        "2026-08-10T08:00:00Z",
        "2026-08-12T08:00:00Z",
        "REPAIR",
    )

    set_clock("2026-08-05T09:00:00Z", program_a.admin_headers)
    callback_a = report_callback(
        program_a, program_a.car_id(), callback_type="MALFUNCTION", out_of_service=True
    )
    callback_b = report_callback(
        program_b, program_b.car_id(), callback_type="MALFUNCTION", out_of_service=True
    )
    set_clock("2026-08-05T15:00:00Z", program_a.admin_headers)
    for program, callback in ((program_a, callback_a), (program_b, callback_b)):
        get_success_data(
            api_client.arrive_callback(callback["id"], program.contractor_headers)
        )
        get_success_data(
            api_client.clear_callback(
                callback["id"], program.contractor_headers, {"resolution_note": "reset"}
            )
        )
    set_clock("2026-09-01T00:00:00Z", program_a.admin_headers)
    return {"schedule_a": program_a, "schedule_b": program_b}


def setup_three_car_late_callbacks() -> Program:
    """Three cars, each with one cleared 384-minute out-of-service August outage.

    No downtime windows exist, so every car's exclusive uptime for 2026-08 is
    99.14 and all three callbacks breached the 60-minute allowance. The monthly fee
    is 500,000 cents and the clock is left at 2026-09-01T00:00:00Z.
    """
    program = setup_program(
        ["CAR-A", "CAR-B", "CAR-C"],
        building_name="Delta Plaza",
        building_address="5 Delta Way",
        building_manager_user_id="bm-d",
        contractor_user_id="sc-d",
        monthly_base_fee_cents=500_000,
        term_end_date="2026-12-31",
    )
    set_clock("2026-08-05T09:00:00Z", program.admin_headers)
    callbacks = [
        report_callback(
            program, program.car_id(index), callback_type="MALFUNCTION", out_of_service=True
        )
        for index in range(3)
    ]
    set_clock("2026-08-05T15:24:00Z", program.admin_headers)
    for callback in callbacks:
        get_success_data(
            api_client.arrive_callback(callback["id"], program.contractor_headers)
        )
        get_success_data(
            api_client.clear_callback(
                callback["id"], program.contractor_headers, {"resolution_note": "reset"}
            )
        )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)
    return program


def setup_entrapment_breach_month() -> Program:
    """An OIL_AND_GREASE / SCHEDULE_B contract with one breached entrapment in August.

    The single car holds a 2880-minute REPAIR window inside 2026-08 and one cleared
    ENTRAPMENT callback answered 360 minutes after it was reported against a
    30-minute entrapment allowance, contributing a 360-minute unplanned outage. The
    monthly fee is 500,000 cents and the clock is left at 2026-09-01T00:00:00Z.
    """
    program = setup_program(
        ["CAR-G1"],
        building_name="Gamma Lofts",
        building_address="4 Gamma Rd",
        building_manager_user_id="bm-g",
        contractor_user_id="sc-g",
        fire_district_code="FD-11",
        scope_type="OIL_AND_GREASE",
        penalty_schedule="SCHEDULE_B",
        monthly_base_fee_cents=500_000,
        term_end_date="2026-12-31",
    )
    add_window(
        program,
        program.car_id(),
        "2026-08-10T08:00:00Z",
        "2026-08-12T08:00:00Z",
        "REPAIR",
    )
    run_callback_cycle(
        program,
        program.car_id(),
        reported_at="2026-08-05T09:00:00Z",
        arrived_at="2026-08-05T15:00:00Z",
        callback_type="ENTRAPMENT",
        out_of_service=True,
        passengers_trapped=2,
        incident_number="FD-2026-0815",
        resolution_note="passengers released",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)
    return program


def setup_contract_scoring_sixty_two_fifty(**contract_overrides) -> Dict[str, object]:
    """Build a program whose 2026-08 performance score evaluates to exactly 62.50.

    One car with no downtime windows and two callbacks reported with
    `out_of_service` false, so August uptime is 100.00; one of them was answered in
    30 minutes against the 60-minute allowance and the other in 120 minutes, so the
    response component is 50.00; one August visit is left SCHEDULED and swept to
    MISSED, so the visit component is 0.00; the ledger is untouched, so the drag is
    0.00. The clock is left at 2026-09-15T00:00:00Z.

    Returns {"program": Program, "visit": visit, "sweep": clock response}.
    """
    overrides = dict(contract_overrides)
    overrides.setdefault("building_manager_user_id", "bm-t")
    overrides.setdefault("contractor_user_id", "sc-t")
    program = setup_program(["CAR-T1"], **overrides)
    car_id = program.car_id()
    visit = schedule_visit(program, car_id, "2026-08", "2026-08-20")
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-03T09:00:00Z",
        arrived_at="2026-08-03T09:30:00Z",
        out_of_service=False,
        resolution_note="ok",
    )
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-04T09:00:00Z",
        arrived_at="2026-08-04T11:00:00Z",
        out_of_service=False,
        resolution_note="late",
    )
    sweep = set_clock("2026-09-15T00:00:00Z", program.admin_headers)
    return {"program": program, "visit": visit, "sweep": sweep}


def setup_contract_scoring_seventy_five(**contract_overrides) -> Dict[str, object]:
    """Build a program whose 2026-08 performance score evaluates to exactly 75.00.

    One car with no downtime windows and one callback reported with `out_of_service`
    false and answered in 30 minutes against the 60-minute allowance, so uptime is
    100.00 and the response component is 100.00; one August visit is left SCHEDULED
    and swept to MISSED, so the visit component is 0.00; the ledger is untouched, so
    the drag is 0.00. The clock is left at 2026-09-15T00:00:00Z.

    Returns {"program": Program, "visit": visit, "callback": callback}.
    """
    overrides = dict(contract_overrides)
    overrides.setdefault("building_manager_user_id", "bm-n")
    overrides.setdefault("contractor_user_id", "sc-n")
    program = setup_program(["CAR-N1"], **overrides)
    car_id = program.car_id()
    visit = schedule_visit(program, car_id, "2026-08", "2026-08-20")
    callback = run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-03T09:00:00Z",
        arrived_at="2026-08-03T09:30:00Z",
        out_of_service=False,
        resolution_note="ok",
    )
    set_clock("2026-09-15T00:00:00Z", program.admin_headers)
    return {"program": program, "visit": visit, "callback": callback}


def setup_penalty_drag_world(**contract_overrides) -> Dict[str, object]:
    """Build a program carrying an unresolved 25,000-cent balance into a 2026-09 score.

    August holds one cleared breached callback (reported with `out_of_service`
    false), which is assessed on 2026-09-01 and left ISSUED, so
    `penalty_balance_cents` is 25,000. September holds one MISSED visit and one
    cleared breached callback, so the response and visit components are both 0.00
    while uptime stays 100.00. The clock is left at 2026-10-15T00:00:00Z, making
    2026-09 the scoring month.

    Returns {"program": Program, "penalty": penalty, "visit": visit}.
    """
    overrides = dict(contract_overrides)
    overrides.setdefault("building_manager_user_id", "bm-k6")
    overrides.setdefault("contractor_user_id", "sc-k6")
    overrides.setdefault("monthly_base_fee_cents", 480_000)
    program = setup_program(["CAR-K6"], **overrides)
    car_id = program.car_id()
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-04T09:00:00Z",
        arrived_at="2026-08-04T11:00:00Z",
        out_of_service=False,
        resolution_note="late",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)
    penalty = assess_penalty(program, "2026-08")
    visit = schedule_visit(program, car_id, "2026-09", "2026-09-20")
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-09-05T09:00:00Z",
        arrived_at="2026-09-05T11:00:00Z",
        out_of_service=False,
        resolution_note="late again",
    )
    set_clock("2026-10-15T00:00:00Z", program.admin_headers)
    return {"program": program, "penalty": penalty, "visit": visit}
