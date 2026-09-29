"""
Composite setup helpers and pytest fixtures.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Every precondition therefore has to be built from
scratch through declared endpoints — there is no seeded data and no back door.

The builders below are plain functions rather than fixtures wherever a test needs to
vary the shape of the world (tier, allowance, operating window, checklist, stock),
and each one returns the created row so a test can read its derived fields directly.
Fixtures are provided only for the two things every test needs: the client and the
operator headers.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import FleetCareClient
from .factories import (
    club_payload,
    contract_payload,
    dispatch_payload,
    equipment_model_payload,
    equipment_payload,
    part_payload,
    parts_hold_payload,
    preventive_visit_payload,
    service_call_payload,
    technician_payload,
    usage_reading_payload,
)
from .test_users import (
    CONTRACT_ADMIN,
    PARTS_PLANNER,
    SERVICE_COORDINATOR,
    make_club_manager_headers,
    make_field_technician_headers,
    make_safety_inspector_headers,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def api() -> FleetCareClient:
    """A client pointed at the API under test."""
    return FleetCareClient()


@pytest.fixture
def admin() -> Dict[str, str]:
    """ContractAdministrator headers (opaque operator identity)."""
    return CONTRACT_ADMIN


@pytest.fixture
def coordinator() -> Dict[str, str]:
    """ServiceCoordinator headers (opaque operator identity)."""
    return SERVICE_COORDINATOR


@pytest.fixture
def planner() -> Dict[str, str]:
    """PartsPlanner headers (opaque operator identity)."""
    return PARTS_PLANNER


# ─── The logical clock ────────────────────────────────────────────────────────


def set_clock(api: FleetCareClient, to_iso8601: str, headers=CONTRACT_ADMIN) -> str:
    """Reposition the logical service clock and return the adopted instant."""
    data = get_success_data(api.set_clock(to_iso8601, headers))
    return data["current_utc"]


# ─── Single-row builders ──────────────────────────────────────────────────────


def new_club(api: FleetCareClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(api.create_club(club_payload(**kwargs), CONTRACT_ADMIN), 201)


def new_model(api: FleetCareClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_equipment_model(equipment_model_payload(**kwargs), CONTRACT_ADMIN),
        201,
    )


def new_equipment(
    api: FleetCareClient, club_id: str, model_id: str, **kwargs
) -> Dict[str, Any]:
    return get_success_data(
        api.create_equipment(
            equipment_payload(club_id, model_id, **kwargs), CONTRACT_ADMIN
        ),
        201,
    )


def new_contract(api: FleetCareClient, club_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_contract(contract_payload(club_id, **kwargs), CONTRACT_ADMIN), 201
    )


def activate_contract(api: FleetCareClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_contract(contract_id, CONTRACT_ADMIN))


def new_active_contract(api: FleetCareClient, club_id: str, **kwargs) -> Dict[str, Any]:
    """Draft a contract and activate it, returning the ACTIVE row."""
    contract = new_contract(api, club_id, **kwargs)
    return activate_contract(api, contract["id"])


def new_technician(api: FleetCareClient, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_technician(technician_payload(**kwargs), CONTRACT_ADMIN), 201
    )


def new_part(api: FleetCareClient, model_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_part(part_payload(model_id, **kwargs), PARTS_PLANNER), 201
    )


def record_usage(api: FleetCareClient, equipment_id: str, usage_hours) -> Dict[str, Any]:
    return get_success_data(
        api.record_usage_reading(
            equipment_id, usage_reading_payload(usage_hours), SERVICE_COORDINATOR
        )
    )


# ─── Reads that locate a child row created as a side effect ───────────────────


def rows_of(response) -> List[Dict[str, Any]]:
    """Return the data list of a validated paginated response."""
    data, _meta = validate_paginated(response)
    return data


def event_for_call(api: FleetCareClient, call_id: str) -> Dict[str, Any]:
    """The one DowntimeEvent that was born with a service call."""
    events = rows_of(api.list_downtime_events(CONTRACT_ADMIN, service_call_id=call_id))
    assert len(events) == 1, f"expected exactly one downtime event, got {len(events)}"
    return events[0]


def assignment_for_visit(api: FleetCareClient, visit_id: str) -> Dict[str, Any]:
    """The calendar reservation created as a side effect of scheduling a visit."""
    rows = rows_of(
        api.list_technician_assignments(SERVICE_COORDINATOR, preventive_visit_id=visit_id)
    )
    assert len(rows) == 1, f"expected exactly one assignment, got {len(rows)}"
    return rows[0]


def assignment_for_call(api: FleetCareClient, call_id: str) -> Dict[str, Any]:
    """The calendar reservation created as a side effect of dispatching a call."""
    rows = rows_of(
        api.list_technician_assignments(SERVICE_COORDINATOR, service_call_id=call_id)
    )
    assert len(rows) == 1, f"expected exactly one assignment, got {len(rows)}"
    return rows[0]


def read_contract(api: FleetCareClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, CONTRACT_ADMIN))


def contract_version(api: FleetCareClient, contract_id: str) -> int:
    """Re-read the contract and return the live OCC token."""
    return read_contract(api, contract_id)["version"]


def read_equipment(api: FleetCareClient, equipment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_equipment(equipment_id, CONTRACT_ADMIN))


def read_club(api: FleetCareClient, club_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_club(club_id, CONTRACT_ADMIN))


def read_technician(api: FleetCareClient, technician_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_technician(technician_id, CONTRACT_ADMIN))


def read_call(api: FleetCareClient, call_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_call(call_id, CONTRACT_ADMIN))


def read_visit(api: FleetCareClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_preventive_visit(visit_id, CONTRACT_ADMIN))


def read_part(api: FleetCareClient, part_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_part(part_id, PARTS_PLANNER))


def read_part_order(api: FleetCareClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_part_order(order_id, CONTRACT_ADMIN))


def read_event(api: FleetCareClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_downtime_event(event_id, CONTRACT_ADMIN))


def read_quote(api: FleetCareClient, quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_renewal_quote(quote_id, CONTRACT_ADMIN))


def read_assignment(api: FleetCareClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_technician_assignment(assignment_id, CONTRACT_ADMIN)
    )


# ─── Composite worlds ─────────────────────────────────────────────────────────


def build_fleet(
    api: FleetCareClient,
    clock: Optional[str] = None,
    club_kwargs: Optional[Dict[str, Any]] = None,
    model_kwargs: Optional[Dict[str, Any]] = None,
    contract_kwargs: Optional[Dict[str, Any]] = None,
    serials: Optional[List[str]] = None,
    equipment_kwargs: Optional[Dict[str, Any]] = None,
    technicians: Optional[List[Dict[str, Any]]] = None,
    activate: bool = True,
) -> Dict[str, Any]:
    """
    Build the preamble almost every scenario needs, in the order the PRD requires.

    Clock, then club, then model, then one unit per entry of ``serials``, then a
    contract that is optionally activated, then one technician per entry of
    ``technicians``. Returns a dict of the created rows so a test can read ids and
    derived fields without re-reading them.
    """
    if clock is not None:
        set_clock(api, clock)
    club = new_club(api, **(club_kwargs or {}))
    model = new_model(api, **(model_kwargs or {}))
    units = []
    for index, serial in enumerate(serials or ["SN-0001"]):
        units.append(
            new_equipment(
                api,
                club["id"],
                model["id"],
                serial_number=serial,
                **(equipment_kwargs or {}),
            )
        )
    contract = new_contract(api, club["id"], **(contract_kwargs or {}))
    if activate:
        contract = activate_contract(api, contract["id"])
    techs = [new_technician(api, **spec) for spec in (technicians or [])]
    return {
        "club": club,
        "club_id": club["id"],
        "model": model,
        "model_id": model["id"],
        "units": units,
        "equipment_ids": [u["id"] for u in units],
        "contract": contract,
        "contract_id": contract["id"],
        "technicians": techs,
        "technician_ids": [t["id"] for t in techs],
        "manager": make_club_manager_headers(club["id"]),
    }


def open_call(
    api: FleetCareClient,
    contract_id: str,
    equipment_id: str,
    headers=SERVICE_COORDINATOR,
    **kwargs,
) -> Dict[str, Any]:
    """Open a reactive service call, which also opens its DowntimeEvent."""
    return get_success_data(
        api.create_service_call(
            service_call_payload(contract_id, equipment_id, **kwargs), headers
        ),
        201,
    )


def dispatch_call(
    api: FleetCareClient, call_id: str, start_at: str, technician_id: Optional[str] = None
) -> Dict[str, Any]:
    """Dispatch a call, creating the technician's RESERVED assignment."""
    return get_success_data(
        api.dispatch_service_call(
            call_id, dispatch_payload(start_at, technician_id), SERVICE_COORDINATOR
        )
    )


def arrive_call(api: FleetCareClient, call_id: str, technician_id: str) -> Dict[str, Any]:
    """Record the assigned technician's arrival, freezing the SLA verdict."""
    return get_success_data(
        api.arrive_service_call(call_id, make_field_technician_headers(technician_id))
    )


def call_on_site(
    api: FleetCareClient,
    contract_id: str,
    equipment_id: str,
    technician_id: str,
    start_at: str,
    **call_kwargs,
) -> Dict[str, Any]:
    """Open, dispatch and arrive in one step, leaving the call ON_SITE."""
    call = open_call(api, contract_id, equipment_id, **call_kwargs)
    dispatch_call(api, call["id"], start_at, technician_id)
    return arrive_call(api, call["id"], technician_id)


def place_hold(
    api: FleetCareClient,
    call_id: str,
    technician_id: str,
    part_id: str,
    qty: int = 1,
    source: str = "NEW",
) -> Dict[str, Any]:
    """Put an ON_SITE call on parts hold, which creates the PartOrder."""
    return get_success_data(
        api.place_parts_hold(
            call_id,
            parts_hold_payload(part_id, qty, source),
            make_field_technician_headers(technician_id),
        ),
        201,
    )


def schedule_visit(
    api: FleetCareClient,
    contract_id: str,
    equipment_id: str,
    window_start: str,
    window_end: str,
    technician_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Book a preventive visit, reserving the technician's window."""
    return get_success_data(
        api.create_preventive_visit(
            preventive_visit_payload(
                contract_id, equipment_id, window_start, window_end, technician_id
            ),
            SERVICE_COORDINATOR,
        ),
        201,
    )


def start_visit(api: FleetCareClient, visit_id: str, technician_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.start_visit(visit_id, make_field_technician_headers(technician_id))
    )


def inspector_headers(technician_id: str) -> Dict[str, str]:
    """Headers for a technician acting on their SafetyInspector credential."""
    return make_safety_inspector_headers(technician_id)


def technician_headers(technician_id: str) -> Dict[str, str]:
    """Headers for a technician acting as a FieldTechnician."""
    return make_field_technician_headers(technician_id)


def manager_headers(club_id: str) -> Dict[str, str]:
    """Headers for the club itself, acting as ClubManager."""
    return make_club_manager_headers(club_id)
