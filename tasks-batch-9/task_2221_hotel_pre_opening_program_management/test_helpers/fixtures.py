"""Composite setup helpers and pytest fixtures.

The server is restarted before every individual test, so each test starts
against an empty database with the logical clock at its startup instant. Every
precondition therefore has to be built from scratch through the public API.

This module is organised in five tiers:

1. atomic steps — one call each, returning the created record;
2. entity hierarchies — a parent plus the children a scenario needs;
3. lifecycle shortcuts — drive one entity to a named state;
4. accumulation and threshold targeting — park a pool one unit from its limit;
5. finalization and terminal states — programs that are frozen, soft-opened or
   stabilized.

Every helper uses ``get_success_data`` so that a broken precondition fails with
the API's own error identifier rather than as an opaque KeyError.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import PreOpeningApiClient
from .constants import (
    CODE_CONSTRUCTION_COMPLETE,
    DEFAULT_NOW,
    MANDATORY_PERMIT_ISSUE_ORDER,
)
from .test_users import (
    BASELINING_DIRECTOR,
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    PROGRAM_DIRECTOR_2,
    QUALITY_INSPECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
)

# =============================================================================
# Tier 0 — client and clock
# =============================================================================


@pytest.fixture
def api() -> PreOpeningApiClient:
    """A client pointed at the server under test."""
    return PreOpeningApiClient()


def set_clock(api: PreOpeningApiClient, to_iso8601: str, headers=PROGRAM_DIRECTOR) -> Dict[str, Any]:
    """Move the logical clock, which supplies every stamped instant and 'now'."""
    return get_success_data(api.set_clock(to_iso8601, headers))


@pytest.fixture
def clock_at_default(api: PreOpeningApiClient) -> str:
    """Anchor the logical clock at the instant every scenario here starts from."""
    set_clock(api, DEFAULT_NOW)
    return DEFAULT_NOW


# =============================================================================
# Tier 1 — atomic steps
# =============================================================================


def make_program(api: PreOpeningApiClient, headers=PROGRAM_DIRECTOR, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_program(factories.program_payload(**overrides), headers)
    )


def read_program(api: PreOpeningApiClient, program_id: str, headers=PROGRAM_DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, headers))


def program_version(api: PreOpeningApiClient, program_id: str, headers=PROGRAM_DIRECTOR) -> int:
    """Current version of the program, needed for every reservation-block create."""
    return read_program(api, program_id, headers)["version"]


def read_readiness(api: PreOpeningApiClient, program_id: str, headers=PROGRAM_DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.get_readiness(program_id, headers))


def make_milestone(
    api: PreOpeningApiClient,
    program_id: str,
    headers=CONSTRUCTION_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_milestone(factories.milestone_payload(program_id, **overrides), headers)
    )


def link_milestones(
    api: PreOpeningApiClient,
    predecessor_milestone_id: str,
    successor_milestone_id: str,
    headers=CONSTRUCTION_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_dependency(
            factories.dependency_payload(
                predecessor_milestone_id, successor_milestone_id, **overrides
            ),
            headers,
        )
    )


def baseline(api: PreOpeningApiClient, program_id: str, headers=BASELINING_DIRECTOR) -> Dict[str, Any]:
    """Freeze the plan of record; the acting operator lands in baselined_by_user_id."""
    return get_success_data(api.baseline_schedule(program_id, headers))


def recompute(api: PreOpeningApiClient, program_id: str, headers=PROGRAM_DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.recompute_schedule(program_id, headers))


def start_milestone(api: PreOpeningApiClient, milestone_id: str, headers=CONSTRUCTION_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.start_milestone(milestone_id, headers))


def complete_milestone(api: PreOpeningApiClient, milestone_id: str, headers=CONSTRUCTION_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.complete_milestone(milestone_id, headers))


def reopen_milestone(
    api: PreOpeningApiClient,
    milestone_id: str,
    reason: str = "Corridor fire-rating rework",
    headers=CONSTRUCTION_MANAGER,
) -> Dict[str, Any]:
    return get_success_data(
        api.reopen_milestone(milestone_id, factories.reopen_payload(reason), headers)
    )


def make_permit(
    api: PreOpeningApiClient,
    program_id: str,
    gating_milestone_id: str,
    headers=LICENSING_COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_permit_application(
            factories.permit_payload(program_id, gating_milestone_id, **overrides),
            headers,
        )
    )


def submit_permit(api: PreOpeningApiClient, permit_id: str, headers=LICENSING_COORDINATOR) -> Dict[str, Any]:
    return get_success_data(api.submit_permit_application(permit_id, headers))


def record_review(
    api: PreOpeningApiClient,
    permit_id: str,
    decision: str,
    headers=LICENSING_COORDINATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_permit_review(
            permit_id, factories.permit_review_payload(decision, **overrides), headers
        )
    )


def make_system(
    api: PreOpeningApiClient,
    program_id: str,
    headers=SYSTEMS_INTEGRATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_system_implementation(
            factories.system_payload(program_id, **overrides), headers
        )
    )


def add_test_run(
    api: PreOpeningApiClient,
    system_id: str,
    executed_at: str,
    cases_total: int,
    cases_passed: int,
    headers=TEST_RUNNER_INTEGRATOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_test_run(
            system_id,
            factories.test_run_payload(executed_at, cases_total, cases_passed, **overrides),
            headers,
        )
    )


def certify(api: PreOpeningApiClient, system_id: str, headers=CERTIFYING_INTEGRATOR) -> Dict[str, Any]:
    """Sign a system off; the certifier must differ from the latest run's executor."""
    return get_success_data(api.certify_system(system_id, headers))


def make_hiring_plan(
    api: PreOpeningApiClient,
    program_id: str,
    headers=TALENT_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_hiring_plan(factories.hiring_plan_payload(program_id, **overrides), headers)
    )


def make_training_session(
    api: PreOpeningApiClient,
    program_id: str,
    headers=TALENT_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_training_session(
            factories.training_session_payload(program_id, **overrides), headers
        )
    )


def complete_session(api: PreOpeningApiClient, session_id: str, headers=TALENT_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.complete_training_session(session_id, headers))


def make_hire(
    api: PreOpeningApiClient,
    hiring_plan_id: str,
    orientation_session_id: Optional[str] = None,
    headers=TALENT_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_hire(
            factories.hire_payload(hiring_plan_id, orientation_session_id, **overrides),
            headers,
        )
    )


def respond_to_offer(
    api: PreOpeningApiClient, hire_id: str, decision: str, headers=TALENT_MANAGER
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_offer(hire_id, factories.hire_response_payload(decision), headers)
    )


def onboard(api: PreOpeningApiClient, hire_id: str, headers=TALENT_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.onboard_hire(hire_id, headers))


def make_budget_line(
    api: PreOpeningApiClient,
    program_id: str,
    headers=PROGRAM_DIRECTOR,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_budget_line(factories.budget_line_payload(program_id, **overrides), headers)
    )


def read_budget_lines(
    api: PreOpeningApiClient, program_id: str, headers=PROGRAM_DIRECTOR, **params: Any
) -> List[Dict[str, Any]]:
    return get_success_data(api.list_budget_lines(program_id, headers, params or None))


def budget_line_version(api: PreOpeningApiClient, program_id: str, budget_line_id: str) -> int:
    """Current version of one budget line, needed for every OS&E order create."""
    for line in read_budget_lines(api, program_id):
        if line["id"] == budget_line_id:
            return line["version"]
    raise AssertionError(f"budget line {budget_line_id} not found on program {program_id}")


def make_ose_order(
    api: PreOpeningApiClient,
    program_id: str,
    budget_line_id: str,
    expected_budget_line_version: int,
    headers=PROCUREMENT_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_ose_order(
            factories.ose_order_payload(
                program_id, budget_line_id, expected_budget_line_version, **overrides
            ),
            headers,
        )
    )


def receive_order(
    api: PreOpeningApiClient,
    order_id: str,
    stored_bay_code: str = "BAY-01",
    headers=PROCUREMENT_MANAGER,
) -> Dict[str, Any]:
    return get_success_data(
        api.receive_ose_order(order_id, factories.receive_payload(stored_bay_code), headers)
    )


def cancel_order(api: PreOpeningApiClient, order_id: str, headers=PROCUREMENT_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.cancel_ose_order(order_id, headers))


def open_booking(api: PreOpeningApiClient, program_id: str, headers=COMMERCIAL_DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.open_booking(program_id, headers))


def suspend_booking(api: PreOpeningApiClient, program_id: str, headers=COMMERCIAL_DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.suspend_booking(program_id, headers))


def make_block(
    api: PreOpeningApiClient,
    program_id: str,
    expected_program_version: Optional[int] = None,
    headers=COMMERCIAL_DIRECTOR,
    **overrides: Any,
) -> Dict[str, Any]:
    """Accept a reservation block, reading the program version when not supplied."""
    if expected_program_version is None:
        expected_program_version = program_version(api, program_id)
    return get_success_data(
        api.create_reservation_block(
            factories.reservation_block_payload(
                program_id, expected_program_version, **overrides
            ),
            headers,
        )
    )


def guarantee_block(api: PreOpeningApiClient, block_id: str, headers=COMMERCIAL_DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.guarantee_block(block_id, headers))


def resolve_block(
    api: PreOpeningApiClient, block_id: str, resolution: str, headers=COMMERCIAL_DIRECTOR
) -> Dict[str, Any]:
    return get_success_data(
        api.resolve_contingency(
            block_id, factories.resolve_contingency_payload(resolution), headers
        )
    )


def make_punch_item(
    api: PreOpeningApiClient,
    program_id: str,
    headers=CONSTRUCTION_MANAGER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_punch_item(factories.punch_item_payload(program_id, **overrides), headers)
    )


def submit_for_verification(
    api: PreOpeningApiClient, item_id: str, headers=CONSTRUCTION_MANAGER
) -> Dict[str, Any]:
    return get_success_data(api.submit_punch_verification(item_id, headers))


def rule_on_punch_item(
    api: PreOpeningApiClient, item_id: str, decision: str, headers=QUALITY_INSPECTOR
) -> Dict[str, Any]:
    return get_success_data(
        api.verify_punch_item(item_id, factories.punch_verify_payload(decision), headers)
    )


def reopen_punch_item(
    api: PreOpeningApiClient,
    item_id: str,
    reason: str = "Gap reappeared after settling",
    headers=QUALITY_INSPECTOR,
) -> Dict[str, Any]:
    return get_success_data(
        api.reopen_punch_item(item_id, factories.reopen_payload(reason), headers)
    )


# =============================================================================
# Tier 2 — entity hierarchies
# =============================================================================


def program_with_milestones(
    api: PreOpeningApiClient,
    milestones: List[Dict[str, Any]],
    edges: Optional[List[Dict[str, Any]]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A PLANNING program plus a milestone network, keyed by milestone code.

    ``milestones`` is a list of override dicts for the milestone factory; each
    must carry a distinct ``code``. ``edges`` is a list of
    ``{"predecessor": code, "successor": code, ...}`` dicts.
    """
    program = make_program(api, **(program_overrides or {}))
    by_code: Dict[str, Dict[str, Any]] = {}
    for spec in milestones:
        record = make_milestone(api, program["id"], **spec)
        by_code[record["code"]] = record
    for edge in edges or []:
        spec = dict(edge)
        predecessor = spec.pop("predecessor")
        successor = spec.pop("successor")
        link_milestones(api, by_code[predecessor]["id"], by_code[successor]["id"], **spec)
    return {"program": program, "milestones": by_code}


def baselined_program(
    api: PreOpeningApiClient,
    milestones: Optional[List[Dict[str, Any]]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    baselined_by=BASELINING_DIRECTOR,
) -> Dict[str, Any]:
    """A program in BASELINED over the supplied network, with both projections set."""
    if milestones is None:
        milestones = [
            {
                "code": CODE_CONSTRUCTION_COMPLETE,
                "name": "Construction complete",
                "duration_days": 60,
                "planned_start_date": "2026-09-01",
            }
        ]
    built = program_with_milestones(api, milestones, edges, program_overrides)
    built["program"] = baseline(api, built["program"]["id"], baselined_by)
    return built


def program_with_budget_line(
    api: PreOpeningApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    **line_overrides: Any,
) -> Dict[str, Any]:
    """A program plus one authorized budget line and that line's current version."""
    program = make_program(api, **(program_overrides or {}))
    line = make_budget_line(api, program["id"], **line_overrides)
    return {"program": program, "budget_line": line, "line_version": line["version"]}


def program_with_hiring_plan(
    api: PreOpeningApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    **plan_overrides: Any,
) -> Dict[str, Any]:
    program = make_program(api, **(program_overrides or {}))
    plan = make_hiring_plan(api, program["id"], **plan_overrides)
    return {"program": program, "plan": plan}


def program_with_system(
    api: PreOpeningApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    **system_overrides: Any,
) -> Dict[str, Any]:
    program = make_program(api, **(program_overrides or {}))
    system = make_system(api, program["id"], **system_overrides)
    return {"program": program, "system": system}


# =============================================================================
# Tier 3 — lifecycle shortcuts
# =============================================================================


def construction_complete_program(
    api: PreOpeningApiClient,
    finish_iso: str = "2026-10-31T00:00:00Z",
    duration_days: int = 60,
    program_overrides: Optional[Dict[str, Any]] = None,
    baselined_by=BASELINING_DIRECTOR,
) -> Dict[str, Any]:
    """Drive a single-milestone program to CONSTRUCTION_COMPLETE.

    The CONSTRUCTION_COMPLETE-coded milestone is started at the current clock
    instant and completed after the clock has been moved to ``finish_iso``,
    which advances the delivery dimension BASELINED -> CONSTRUCTION_COMPLETE.
    """
    built = baselined_program(
        api,
        milestones=[
            {
                "code": CODE_CONSTRUCTION_COMPLETE,
                "name": "Construction complete",
                "duration_days": duration_days,
                "planned_start_date": "2026-09-01",
            }
        ],
        program_overrides=program_overrides,
        baselined_by=baselined_by,
    )
    milestone = built["milestones"][CODE_CONSTRUCTION_COMPLETE]
    start_milestone(api, milestone["id"])
    set_clock(api, finish_iso)
    built["milestones"][CODE_CONSTRUCTION_COMPLETE] = complete_milestone(api, milestone["id"])
    built["program"] = read_program(api, built["program"]["id"])
    return built


def issued_permit(
    api: PreOpeningApiClient,
    program_id: str,
    gating_milestone_id: str,
    permit_type: str,
    review_days: int = 21,
) -> Dict[str, Any]:
    """Draft, submit and issue one permit application in a single step."""
    permit = make_permit(
        api,
        program_id,
        gating_milestone_id,
        permit_type=permit_type,
        review_days=review_days,
    )
    submit_permit(api, permit["id"])
    return record_review(api, permit["id"], "ISSUE")


def all_mandatory_permits_issued(
    api: PreOpeningApiClient, program_id: str, gating_milestone_id: str
) -> Dict[str, Dict[str, Any]]:
    """Issue all four opening-mandatory permits in prerequisite order.

    A certificate of occupancy needs the elevator approval issued first, and a
    liquor licence needs both the certificate of occupancy and the food service
    approval, so the order is fixed.
    """
    issued: Dict[str, Dict[str, Any]] = {}
    for permit_type in MANDATORY_PERMIT_ISSUE_ORDER:
        issued[permit_type] = issued_permit(
            api, program_id, gating_milestone_id, permit_type
        )
    return issued


def certified_system(
    api: PreOpeningApiClient,
    program_id: str,
    system_type: str = "PMS",
    executed_at: str = "2026-09-01T09:00:00Z",
    cases_total: int = 40,
    cases_passed: int = 40,
    **system_overrides: Any,
) -> Dict[str, Any]:
    """Register a system, log one passing run and certify it with a second operator."""
    system = make_system(api, program_id, system_type=system_type, **system_overrides)
    run = add_test_run(api, system["id"], executed_at, cases_total, cases_passed)
    certified = certify(api, system["id"])
    return {"system": certified, "run": run}


def ready_department(
    api: PreOpeningApiClient,
    program_id: str,
    department: str = "ROOMS",
    headcount_target: int = 1,
    wave_start_date: str = "2026-09-10",
    session_overrides: Optional[Dict[str, Any]] = None,
    hire_overrides: Optional[Dict[str, Any]] = None,
    onboard_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one department whose readiness_flag has flipped to READY.

    A plan, an orientation session, one accepted hire enrolled in it, the
    session completed, then the hire onboarded — which is the full bubble-up
    chain from hire to plan to program.
    """
    plan = make_hiring_plan(
        api,
        program_id,
        department=department,
        headcount_target=headcount_target,
        wave_start_date=wave_start_date,
    )
    session_spec = {
        "title": f"{department} orientation",
        "training_room_code": "TR-1",
        "starts_at": "2026-09-14T09:00:00Z",
        "ends_at": "2026-09-14T12:00:00Z",
        "capacity": max(5, headcount_target),
        "department": department,
    }
    session_spec.update(session_overrides or {})
    session = make_training_session(api, program_id, **session_spec)

    hires: List[Dict[str, Any]] = []
    onboarded_needed = -(-headcount_target * 80 // 100)  # ceiling of 80 percent
    for index in range(headcount_target):
        spec = {
            "full_name": f"{department.title()} Hire {index + 1}",
            "start_date": "2026-09-15",
        }
        spec.update(hire_overrides or {})
        hire = make_hire(api, plan["id"], session["id"], **spec)
        respond_to_offer(api, hire["id"], "ACCEPT")
        hires.append(hire)

    session = complete_session(api, session["id"])
    if onboard_at is not None:
        set_clock(api, onboard_at)
    for hire in hires[:onboarded_needed]:
        onboard(api, hire["id"])

    plans = get_success_data(api.list_hiring_plans(program_id, TALENT_MANAGER))
    refreshed = next(item for item in plans if item["id"] == plan["id"])
    return {"plan": refreshed, "session": session, "hires": hires}


def booking_open_program(
    api: PreOpeningApiClient,
    finish_iso: str = "2026-10-31T00:00:00Z",
    duration_days: int = 60,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A program at CONSTRUCTION_COMPLETE whose commercial dimension is BOOKING_OPEN."""
    built = construction_complete_program(
        api,
        finish_iso=finish_iso,
        duration_days=duration_days,
        program_overrides=program_overrides,
    )
    built["program"] = open_booking(api, built["program"]["id"])
    return built


def licensing_program(
    api: PreOpeningApiClient,
    finish_iso: str = "2026-10-31T00:00:00Z",
    duration_days: int = 60,
    program_overrides: Optional[Dict[str, Any]] = None,
    baselined_by=BASELINING_DIRECTOR,
) -> Dict[str, Any]:
    """A program in LICENSING with all four mandatory permits ISSUED."""
    built = construction_complete_program(
        api,
        finish_iso=finish_iso,
        duration_days=duration_days,
        program_overrides=program_overrides,
        baselined_by=baselined_by,
    )
    built["permits"] = all_mandatory_permits_issued(
        api,
        built["program"]["id"],
        built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"],
    )
    built["program"] = read_program(api, built["program"]["id"])
    return built


def soft_opening_ready_program(
    api: PreOpeningApiClient,
    finish_iso: str = "2026-10-31T00:00:00Z",
    duration_days: int = 60,
    program_overrides: Optional[Dict[str, Any]] = None,
    baselined_by=BASELINING_DIRECTOR,
) -> Dict[str, Any]:
    """A LICENSING program that satisfies every soft-opening gate at once.

    All four mandatory permits issued, no punch-list item, no system
    implementation at all — so certified_system_count equals
    required_system_count at zero — and one hiring plan whose single hire is
    onboarded after a completed orientation session.
    """
    built = licensing_program(
        api,
        finish_iso=finish_iso,
        duration_days=duration_days,
        program_overrides=program_overrides,
        baselined_by=baselined_by,
    )
    built["staffing"] = ready_department(
        api,
        built["program"]["id"],
        session_overrides={
            "starts_at": "2026-10-20T09:00:00Z",
            "ends_at": "2026-10-20T12:00:00Z",
        },
    )
    built["program"] = read_program(api, built["program"]["id"])
    return built


def soft_opening_program(
    api: PreOpeningApiClient,
    soft_opening_date: str = "2026-11-10",
    authorized_by=PROGRAM_DIRECTOR_2,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A program whose delivery dimension has reached SOFT_OPENING."""
    built = soft_opening_ready_program(api, **kwargs)
    built["program"] = get_success_data(
        api.authorize_soft_opening(
            built["program"]["id"],
            factories.soft_opening_payload(soft_opening_date),
            authorized_by,
        )
    )
    return built


def verified_punch_item(
    api: PreOpeningApiClient,
    program_id: str,
    severity: str = "MAJOR",
    milestone_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Raise a defect and take it all the way to VERIFIED by two distinct people."""
    spec: Dict[str, Any] = {"severity": severity}
    if milestone_id is not None:
        spec["milestone_id"] = milestone_id
    spec.update(overrides)
    item = make_punch_item(api, program_id, **spec)
    submit_for_verification(api, item["id"])
    return rule_on_punch_item(api, item["id"], "VERIFY")


# =============================================================================
# Tier 4 — accumulation and threshold targeting
# =============================================================================


def budget_line_at_available(
    api: PreOpeningApiClient,
    authorized_cents: int,
    committed_cents: int,
    program_overrides: Optional[Dict[str, Any]] = None,
    category: str = "SETUP",
) -> Dict[str, Any]:
    """A budget line parked at an exact available_cents figure.

    One committed order of ``committed_cents`` is placed against a line
    authorized at ``authorized_cents``, leaving available_cents at the
    difference so the next order sits one cent either side of the ceiling.
    """
    program = make_program(api, **(program_overrides or {}))
    line = make_budget_line(
        api, program["id"], category=category, authorized_cents=authorized_cents
    )
    order = None
    if committed_cents:
        order = make_ose_order(
            api,
            program["id"],
            line["id"],
            line["version"],
            amount_cents=committed_cents,
            pallet_count=1,
        )
    refreshed = next(
        item for item in read_budget_lines(api, program["id"]) if item["id"] == line["id"]
    )
    return {"program": program, "budget_line": refreshed, "order": order}


def storage_loaded_program(
    api: PreOpeningApiClient,
    pallet_loads: List[int],
    storage_capacity_pallets: int,
    delivery_window_start: str = "2026-10-01",
    delivery_window_end: str = "2026-10-10",
    authorized_cents: int = 10000000,
    amount_cents: int = 100000,
) -> Dict[str, Any]:
    """A program whose receiving area already holds the supplied pallet loads.

    Every order shares one delivery window, so the whole load contends for the
    same bays and the next candidate is measured against their sum.
    """
    program = make_program(
        api, storage_capacity_pallets=storage_capacity_pallets
    )
    line = make_budget_line(api, program["id"], authorized_cents=authorized_cents)
    orders: List[Dict[str, Any]] = []
    for pallets in pallet_loads:
        orders.append(
            make_ose_order(
                api,
                program["id"],
                line["id"],
                budget_line_version(api, program["id"], line["id"]),
                amount_cents=amount_cents,
                pallet_count=pallets,
                delivery_window_start=delivery_window_start,
                delivery_window_end=delivery_window_end,
            )
        )
    return {"program": program, "budget_line": line, "orders": orders}


def program_with_accepted_block(
    api: PreOpeningApiClient,
    block_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    finish_iso: str = "2026-10-31T00:00:00Z",
    duration_days: int = 60,
) -> Dict[str, Any]:
    """A BOOKING_OPEN program holding one ACCEPTED pre-opening block."""
    built = booking_open_program(
        api,
        finish_iso=finish_iso,
        duration_days=duration_days,
        program_overrides=program_overrides,
    )
    built["block"] = make_block(
        api, built["program"]["id"], **(block_overrides or {})
    )
    built["program"] = read_program(api, built["program"]["id"])
    return built


# =============================================================================
# Tier 5 — finalization and terminal states
# =============================================================================


def frozen_by_critical_punch(
    api: PreOpeningApiClient,
    program_id: str,
    milestone_id: Optional[str] = None,
    description: str = "Stair pressurization fan inoperative",
) -> Dict[str, Any]:
    """Raise one CRITICAL defect, which matches the first posture branch at once."""
    spec: Dict[str, Any] = {"severity": "CRITICAL", "description": description}
    if milestone_id is not None:
        spec["milestone_id"] = milestone_id
    return make_punch_item(api, program_id, **spec)


def frozen_by_permit_deficiency(
    api: PreOpeningApiClient,
    program_id: str,
    gating_milestone_id: str,
    permit_type: str = "FOOD_SERVICE",
    review_days: int = 21,
    deficiency_reason: str = "Grease interceptor undersized",
) -> Dict[str, Any]:
    """Drive the five-link deficiency cascade on one mandatory permit."""
    permit = make_permit(
        api,
        program_id,
        gating_milestone_id,
        permit_type=permit_type,
        review_days=review_days,
    )
    submit_permit(api, permit["id"])
    return record_review(
        api, permit["id"], "DEFICIENCY", deficiency_reason=deficiency_reason
    )


def stabilized_program(
    api: PreOpeningApiClient,
    soft_opening_date: str = "2026-11-10",
    stabilize_at: str = "2026-12-11T00:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A program driven all the way to the terminal STABILIZED delivery state."""
    built = soft_opening_program(api, soft_opening_date=soft_opening_date, **kwargs)
    set_clock(api, stabilize_at)
    built["program"] = get_success_data(
        api.transition_to_stabilized(built["program"]["id"], PROGRAM_DIRECTOR)
    )
    return built


# =============================================================================
# Ready-made pytest fixtures for the most reused shapes
# =============================================================================


@pytest.fixture
def program(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A freshly created program in PLANNING / BOOKING_CLOSED."""
    return make_program(api)


@pytest.fixture
def planning_program_with_network(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A PLANNING program with a three-milestone chain wired predecessor to successor."""
    return program_with_milestones(
        api,
        milestones=[
            {
                "code": CODE_CONSTRUCTION_COMPLETE,
                "name": "Construction complete",
                "duration_days": 90,
                "planned_start_date": "2026-09-01",
            },
            {
                "code": "CO_ISSUANCE",
                "name": "Certificate of occupancy issuance",
                "duration_days": 30,
                "planned_start_date": "2026-12-01",
            },
            {
                "code": "SYSTEMS_CUTOVER",
                "name": "Systems cutover",
                "duration_days": 25,
                "planned_start_date": "2027-01-05",
            },
        ],
        edges=[
            {"predecessor": CODE_CONSTRUCTION_COMPLETE, "successor": "CO_ISSUANCE", "lag_days": 0},
            {"predecessor": "CO_ISSUANCE", "successor": "SYSTEMS_CUTOVER", "lag_days": 5},
        ],
    )


@pytest.fixture
def baselined(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A BASELINED program over a single sixty-day construction milestone."""
    return baselined_program(api)


@pytest.fixture
def construction_complete(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A program whose delivery dimension has advanced to CONSTRUCTION_COMPLETE."""
    return construction_complete_program(api)


@pytest.fixture
def booking_open(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A CONSTRUCTION_COMPLETE program whose commercial dimension is BOOKING_OPEN."""
    return booking_open_program(api)


@pytest.fixture
def licensing(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A LICENSING program with every mandatory permit issued."""
    return licensing_program(api)


@pytest.fixture
def soft_opening_ready(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A LICENSING program that satisfies all seven soft-opening conditions."""
    return soft_opening_ready_program(api)


@pytest.fixture
def budgeted_program(api: PreOpeningApiClient, clock_at_default: str) -> Dict[str, Any]:
    """A program with one SETUP budget line authorized at one million cents."""
    return program_with_budget_line(api)
