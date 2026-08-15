"""Composite setup helpers.

Every helper builds preconditions from scratch against an empty database using
only PRD-declared endpoints. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors. Ownership-gated calls always use
per-instance headers built from the real entity id.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_call_ticket_payload,
    create_incident_record_payload,
    create_pay_period_payload,
    create_relocation_case_payload,
    create_rotation_shift_payload,
    create_supervisor_payload,
    create_technician_payload,
    create_unit_payload,
    create_vendor_authorization_payload,
    create_vendor_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_supervisor_headers,
    make_technician_headers,
    make_vendor_headers,
)

ADMIN = TEST_USERS["property_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# --- Tier 0: single-entity creators ------------------------------------------


def make_technician(**overrides) -> dict:
    return get_success_data(
        api_client.create_technician(create_technician_payload(**overrides), ADMIN)
    )


def make_supervisor(**overrides) -> dict:
    return get_success_data(
        api_client.create_technician(create_supervisor_payload(**overrides), ADMIN)
    )


def make_unit(**overrides) -> dict:
    return get_success_data(api_client.create_unit(create_unit_payload(**overrides), ADMIN))


def make_vendor(**overrides) -> dict:
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(**overrides), ADMIN)
    )


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_call_ticket(ticket_id, DISPATCHER))


def get_shift(shift_id: str) -> dict:
    return get_success_data(api_client.get_rotation_shift(shift_id, ADMIN))


def get_technician(technician_id: str) -> dict:
    return get_success_data(api_client.get_technician(technician_id, ADMIN))


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, DISPATCHER))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, ADMIN))


def get_vendor_authorization(authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_vendor_authorization(authorization_id, DISPATCHER)
    )


def get_relocation_case(case_id: str) -> dict:
    return get_success_data(api_client.get_relocation_case(case_id, ADMIN))


def get_incident_record(record_id: str) -> dict:
    return get_success_data(api_client.get_incident_record(record_id, DISPATCHER))


def get_pay_period(pay_period_id: str) -> dict:
    return get_success_data(api_client.get_pay_period(pay_period_id, ADMIN))


# --- Tier 1: state progression -----------------------------------------------


def publish_shift(technician_id: str, start_at: str, end_at: str) -> dict:
    """Publish a PUBLISHED rotation shift for the technician."""
    return get_success_data(
        api_client.create_rotation_shift(
            create_rotation_shift_payload(
                technician_id=technician_id, start_at=start_at, end_at=end_at
            ),
            ADMIN,
        )
    )


def start_shift(shift_id: str) -> dict:
    """PUBLISHED -> ACTIVE, performed by a PropertyAdmin (PRD §3.2)."""
    return get_success_data(api_client.start_rotation_shift(shift_id, ADMIN))


def complete_shift(shift_id: str) -> dict:
    """ACTIVE -> COMPLETED; computes standby_minutes / provisional pay."""
    return get_success_data(api_client.complete_rotation_shift(shift_id, ADMIN))


def create_active_shift(technician_id: str, start_at: str, end_at: str,
                        start_clock: Optional[str] = None) -> dict:
    """Publish a shift and start it (clock set to start_clock if given)."""
    shift = publish_shift(technician_id, start_at, end_at)
    if start_clock is not None:
        set_clock(start_clock)
    start_shift(shift["id"])
    return get_shift(shift["id"])


def create_completed_shift(technician_id: str, start_at: str, end_at: str,
                           start_clock: str, complete_clock: str) -> dict:
    """Publish -> start -> complete a shift. Returns the COMPLETED shift."""
    shift = publish_shift(technician_id, start_at, end_at)
    set_clock(start_clock)
    start_shift(shift["id"])
    set_clock(complete_clock)
    return complete_shift(shift["id"])


# --- Tier 2: call ticket chains ----------------------------------------------


def create_ticket(unit_id: str, category: str = "LEAK_MINOR", **overrides) -> dict:
    """Intake a RECEIVED ticket (received_at stamped from the logical clock)."""
    return get_success_data(
        api_client.create_call_ticket(
            create_call_ticket_payload(unit_id=unit_id, category=category, **overrides),
            DISPATCHER,
        )
    )


def triage_ticket(ticket_id: str, is_true_emergency: bool = True) -> dict:
    return get_success_data(
        api_client.triage_call_ticket(
            ticket_id, {"is_true_emergency": is_true_emergency}, DISPATCHER
        )
    )


def dispatch_ticket(ticket_id: str, technician_id: str,
                    actor_headers: Optional[dict] = None) -> dict:
    """Read the current version, then dispatch with the OCC field set."""
    version = get_ticket(ticket_id)["version"]
    return get_success_data(
        api_client.dispatch_call_ticket(
            ticket_id,
            {
                "technician_id": technician_id,
                "expected_call_ticket_version": version,
            },
            actor_headers or DISPATCHER,
        )
    )


def arrive_ticket(ticket_id: str, technician_id: str) -> dict:
    """Assigned technician arrives (ownership-gated self action)."""
    return get_success_data(
        api_client.arrive_call_ticket(ticket_id, make_technician_headers(technician_id))
    )


def mitigate_ticket(ticket_id: str, technician_id: str,
                    unit_uninhabitable: bool = False,
                    mitigation_notes: str = "Temporary mitigation applied") -> dict:
    return get_success_data(
        api_client.mitigate_call_ticket(
            ticket_id,
            {
                "mitigation_notes": mitigation_notes,
                "unit_uninhabitable": unit_uninhabitable,
            },
            make_technician_headers(technician_id),
        )
    )


def create_incident_record(ticket_id: str, creator_technician_id: str,
                           narrative: str = "Incident narrative",
                           estimated_damage_cents: int = 0) -> dict:
    return get_success_data(
        api_client.create_incident_record(
            ticket_id,
            create_incident_record_payload(
                narrative=narrative, estimated_damage_cents=estimated_damage_cents
            ),
            make_technician_headers(creator_technician_id),
        )
    )


def submit_incident_record(record_id: str, creator_technician_id: str) -> dict:
    return get_success_data(
        api_client.submit_incident_record(
            record_id, make_technician_headers(creator_technician_id)
        )
    )


def close_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.close_call_ticket(ticket_id, DISPATCHER))


# --- Tier 3: full lifecycle shortcuts -----------------------------------------


def create_triaged_ticket(unit_id: str, category: str = "LEAK_MINOR",
                          at: Optional[str] = None, **overrides) -> dict:
    """Create + triage (true emergency). Returns the TRIAGED ticket."""
    if at is not None:
        set_clock(at)
    ticket = create_ticket(unit_id, category, **overrides)
    return triage_ticket(ticket["id"], True)


def create_dispatched_ticket(unit_id: str, technician_id: str,
                             category: str = "LEAK_MINOR",
                             at: Optional[str] = None, **overrides) -> dict:
    """Create + triage + dispatch at the current (or given) clock instant."""
    ticket = create_triaged_ticket(unit_id, category, at=at, **overrides)
    return dispatch_ticket(ticket["id"], technician_id)


def create_mitigated_ticket(unit_id: str, technician_id: str,
                            category: str = "LEAK_MINOR",
                            dispatch_at: Optional[str] = None,
                            arrive_at: Optional[str] = None,
                            mitigate_at: Optional[str] = None,
                            unit_uninhabitable: bool = False,
                            **overrides) -> dict:
    """Full chain through MITIGATED. Returns the MITIGATED ticket."""
    ticket = create_dispatched_ticket(
        unit_id, technician_id, category, at=dispatch_at, **overrides
    )
    if arrive_at is not None:
        set_clock(arrive_at)
    arrive_ticket(ticket["id"], technician_id)
    if mitigate_at is not None:
        set_clock(mitigate_at)
    return mitigate_ticket(ticket["id"], technician_id, unit_uninhabitable)


def create_closed_ticket(unit_id: str, technician_id: str,
                         category: str = "LEAK_MINOR",
                         dispatch_at: Optional[str] = None,
                         arrive_at: Optional[str] = None,
                         mitigate_at: Optional[str] = None,
                         close_at: Optional[str] = None,
                         unit_uninhabitable: bool = False,
                         estimated_damage_cents: int = 0,
                         **overrides) -> dict:
    """Full chain through CLOSED with a SUBMITTED incident record.

    Caller must pre-arrange any relocation case when unit_uninhabitable=True.
    """
    ticket = create_mitigated_ticket(
        unit_id,
        technician_id,
        category,
        dispatch_at=dispatch_at,
        arrive_at=arrive_at,
        mitigate_at=mitigate_at,
        unit_uninhabitable=unit_uninhabitable,
        **overrides,
    )
    record = create_incident_record(
        ticket["id"], technician_id, estimated_damage_cents=estimated_damage_cents
    )
    submit_incident_record(record["id"], technician_id)
    if close_at is not None:
        set_clock(close_at)
    return close_ticket(ticket["id"])


def mitigated_ticket_with_work_order(unit_id: str, technician_id: str,
                                     category: str = "LEAK_MINOR",
                                     dispatch_at: Optional[str] = None,
                                     arrive_at: Optional[str] = None,
                                     mitigate_at: Optional[str] = None,
                                     unit_uninhabitable: bool = False):
    """Mitigate a ticket and return (ticket, auto follow-up work order)."""
    ticket = create_mitigated_ticket(
        unit_id,
        technician_id,
        category,
        dispatch_at=dispatch_at,
        arrive_at=arrive_at,
        mitigate_at=mitigate_at,
        unit_uninhabitable=unit_uninhabitable,
    )
    orders, _meta = _list_work_orders(ticket["id"])
    assert len(orders) == 1, f"expected exactly one auto work order, got {len(orders)}"
    return ticket, orders[0]


def _list_work_orders(ticket_id: str, **params):
    from prd_bench_local_runner.testing import validate_paginated

    merged = {"call_ticket_id": ticket_id}
    merged.update(params)
    return validate_paginated(api_client.list_work_orders(DISPATCHER, params=merged))


def list_ticket_work_orders(ticket_id: str, **params):
    return _list_work_orders(ticket_id, **params)


# --- Tier 4: vendor authorizations --------------------------------------------


def propose_vendor_authorization(ticket_id: str, work_order_id: str,
                                 vendor_id: str, amount_cents: int,
                                 requester_technician_id: str) -> dict:
    """Propose spend; requested_by_technician_id copied from X-User-ID."""
    return get_success_data(
        api_client.create_vendor_authorization(
            ticket_id,
            create_vendor_authorization_payload(
                work_order_id=work_order_id,
                vendor_id=vendor_id,
                amount_cents=amount_cents,
            ),
            make_technician_headers(requester_technician_id),
        )
    )


def authorize_vendor_authorization(authorization_id: str,
                                   actor_headers: dict) -> dict:
    return get_success_data(
        api_client.authorize_vendor_authorization(authorization_id, actor_headers)
    )


def create_authorized_va(ticket_id: str, work_order_id: str, vendor_id: str,
                         amount_cents: int, requester_technician_id: str,
                         approver_headers: dict) -> dict:
    va = propose_vendor_authorization(
        ticket_id, work_order_id, vendor_id, amount_cents, requester_technician_id
    )
    return authorize_vendor_authorization(va["id"], approver_headers)


# --- Tier 5: relocation chains -------------------------------------------------


def propose_relocation(unit_id: str, ticket_id: str, start_date: str,
                       end_date: str, nightly_rate_cents: int,
                       proposer_technician_id: str,
                       proposer_headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.create_relocation_case(
            create_relocation_case_payload(
                unit_id=unit_id,
                call_ticket_id=ticket_id,
                start_date=start_date,
                end_date=end_date,
                nightly_rate_cents=nightly_rate_cents,
            ),
            proposer_headers or make_technician_headers(proposer_technician_id),
        )
    )


def approve_relocation(case_id: str, approver_headers: dict) -> dict:
    return get_success_data(api_client.approve_relocation_case(case_id, approver_headers))


def activate_relocation(case_id: str, supervisor: dict) -> dict:
    return get_success_data(
        api_client.activate_relocation_case(
            case_id, make_supervisor_headers(supervisor["id"])
        )
    )


def end_relocation(case_id: str, actual_end_date: str, supervisor: dict) -> dict:
    return get_success_data(
        api_client.end_relocation_case(
            case_id, {"actual_end_date": actual_end_date},
            make_supervisor_headers(supervisor["id"]),
        )
    )


def setup_uninhabitable_incident(unit_number: str = "U-1",
                                 dispatcher_arrival: bool = True):
    """Technician + supervisor + unit + active shift + FLOOD ticket mitigated
    with unit_uninhabitable=True. Returns dict of the cast."""
    set_clock("2026-08-01T00:00:00Z")
    tech = make_technician()
    sup = make_supervisor()
    unit = make_unit(unit_number=unit_number)
    shift = publish_shift(
        tech["id"], "2026-08-01T00:00:00Z", "2026-08-01T08:00:00Z"
    )
    start_shift(shift["id"])
    ticket = create_ticket(unit["id"], "FLOOD")
    triage_ticket(ticket["id"], True)
    dispatch_ticket(ticket["id"], tech["id"])
    if dispatcher_arrival:
        arrive_ticket(ticket["id"], tech["id"])
        set_clock("2026-08-01T01:00:00Z")
        ticket = mitigate_ticket(ticket["id"], tech["id"], unit_uninhabitable=True)
    return {
        "technician": tech,
        "supervisor": sup,
        "unit": unit,
        "shift": shift,
        "ticket": ticket,
    }


# --- Tier 5: payroll -----------------------------------------------------------


def create_pay_period(period_start: str, period_end: str) -> dict:
    return get_success_data(
        api_client.create_pay_period(
            create_pay_period_payload(
                period_start=period_start, period_end=period_end
            ),
            ADMIN,
        )
    )


def list_period_statements(pay_period_id: str):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api_client.list_pay_statements(ADMIN, params={"pay_period_id": pay_period_id})
    )
