"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a setup step that
fails surfaces as a clear "setup failed" error rather than a confusing
assertion failure inside a test.

The test harness restarts the server (empty database) before every test, so
every helper builds all of its preconditions from scratch using only
PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_intersection_payload, create_pole_payload, create_device_payload,
    create_crew_payload, create_pole_attachment_payload, create_ticket_payload,
    create_work_order_payload, create_timing_change_request_payload,
    create_locate_request_payload, create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_fieldtech_headers

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
TRAFFIC_ENGINEER = TEST_USERS["traffic_engineer_headers"]
UTILITY = TEST_USERS["utility_coordinator_headers"]

DEFAULT_START = "2026-03-02T08:00:00Z"
DEFAULT_END = "2026-03-02T09:00:00Z"


# ─── Clock ────────────────────────────────────────────
def set_clock(iso: str):
    """Advance the logical clock; returns the response data ({current_utc})."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


# ─── Tier 1: single-entity creators ───────────────────
def new_intersection(**overrides):
    return get_success_data(api_client.create_intersection(
        create_intersection_payload(**overrides), ADMIN))


def new_pole(**overrides):
    return get_success_data(api_client.create_pole(
        create_pole_payload(**overrides), ADMIN))


def new_device(intersection_id, **overrides):
    return get_success_data(api_client.create_device(
        create_device_payload(intersection_id=intersection_id, **overrides), ADMIN))


def new_crew(**overrides):
    return get_success_data(api_client.create_crew(
        create_crew_payload(**overrides), ADMIN))


def new_ticket(device_id, **overrides):
    return get_success_data(api_client.create_ticket(
        create_ticket_payload(device_id=device_id, **overrides), DISPATCHER))


def new_work_order(device_id, **overrides):
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(device_id=device_id, **overrides), DISPATCHER))


def new_timing_change_request(intersection_id, **overrides):
    return get_success_data(api_client.create_timing_change_request(
        create_timing_change_request_payload(intersection_id=intersection_id, **overrides),
        DISPATCHER))


def new_locate_request(intersection_id, **overrides):
    return get_success_data(api_client.create_locate_request(
        create_locate_request_payload(intersection_id=intersection_id, **overrides),
        UTILITY))


def new_warranty_claim(device_id, **overrides):
    return get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(device_id=device_id, **overrides), UTILITY))


def new_pole_attachment(pole_id, expected_pole_version, **overrides):
    return get_success_data(api_client.create_pole_attachment(
        create_pole_attachment_payload(
            pole_id=pole_id, expected_pole_version=expected_pole_version, **overrides),
        UTILITY))


# ─── Tier 1: transition shortcuts ─────────────────────
def triage(ticket_id):
    return get_success_data(api_client.triage_ticket(ticket_id, DISPATCHER))


def get_pole(pole_id):
    return get_success_data(api_client.get_pole(pole_id, UTILITY))


def get_ticket(ticket_id):
    return get_success_data(api_client.get_ticket(ticket_id, DISPATCHER))


def get_device(device_id):
    return get_success_data(api_client.get_device(device_id, ADMIN))


def get_intersection(intersection_id):
    return get_success_data(api_client.get_intersection(intersection_id, ADMIN))


def get_crew(crew_id):
    return get_success_data(api_client.get_crew(crew_id, ADMIN))


def get_timing_change_request(tcr_id):
    return get_success_data(api_client.get_timing_change_request(tcr_id, TRAFFIC_ENGINEER))


# ─── Tier 2: hierarchy setups ─────────────────────────
def setup_triaged_ticket(device_overrides=None, ticket_overrides=None):
    """Intersection + device + ticket + triage. Returns (intersection, device, ticket)."""
    inter = new_intersection()
    device = new_device(inter["id"], **(device_overrides or {}))
    ticket = new_ticket(device["id"], **(ticket_overrides or {}))
    triaged = triage(ticket["id"])
    return inter, device, triaged


# ─── Tier 3: work-order lifecycle shortcuts ───────────
def schedule_work_order(work_order_id, crew_id, scheduled_start=DEFAULT_START,
                        scheduled_end=DEFAULT_END):
    payload = {"crew_id": crew_id, "scheduled_start": scheduled_start,
               "scheduled_end": scheduled_end}
    return get_success_data(api_client.schedule_work_order(work_order_id, payload, DISPATCHER))


def dispatch_work_order(work_order_id):
    return get_success_data(api_client.dispatch_work_order(work_order_id, DISPATCHER))


def complete_work_order(work_order_id, crew_id, actual_labor_hours=1.0, actual_parts=None):
    payload = {"actual_labor_hours": actual_labor_hours}
    if actual_parts is not None:
        payload["actual_parts"] = actual_parts
    return get_success_data(api_client.complete_work_order(
        work_order_id, payload, make_fieldtech_headers(crew_id)))


def setup_dispatched_work_order(work_type="REPAIR", estimated_labor_hours=1.0,
                                estimated_parts=None, crew_capacity=8.0,
                                with_ticket=True):
    """Intersection + device + crew + (optional ticket) + work order taken through
    schedule and dispatch. Returns a dict of the created resources plus wo_id."""
    inter = new_intersection()
    device = new_device(inter["id"])
    crew = new_crew(labor_capacity_hours=crew_capacity)
    ticket = None
    wo_overrides = {"work_type": work_type, "estimated_labor_hours": estimated_labor_hours}
    if estimated_parts is not None:
        wo_overrides["estimated_parts"] = estimated_parts
    if with_ticket:
        ticket = new_ticket(device["id"])
        triage(ticket["id"])
        wo_overrides["ticket_id"] = ticket["id"]
    wo = new_work_order(device["id"], **wo_overrides)
    schedule_work_order(wo["id"], crew["id"])
    dispatch_work_order(wo["id"])
    return {"intersection": inter, "device": device, "crew": crew,
            "ticket": ticket, "wo_id": wo["id"], "work_order": wo}


def setup_completed_work_order(work_type="REPAIR", estimated_labor_hours=1.0,
                               estimated_parts=None, actual_labor_hours=1.0,
                               actual_parts=None, crew_capacity=8.0, with_ticket=True):
    """Full chain through work-order COMPLETED. Returns a dict with the completed
    work order and its context resources."""
    ctx = setup_dispatched_work_order(
        work_type=work_type, estimated_labor_hours=estimated_labor_hours,
        estimated_parts=estimated_parts, crew_capacity=crew_capacity,
        with_ticket=with_ticket)
    completed = complete_work_order(
        ctx["wo_id"], ctx["crew"]["id"],
        actual_labor_hours=actual_labor_hours, actual_parts=actual_parts)
    ctx["work_order"] = completed
    return ctx


def setup_resolved_ticket(clock=None):
    """Intersection + device + crew + ticket triaged + work order completed +
    ticket resolved. Returns dict with intersection/device/crew/ticket/wo_id."""
    if clock is not None:
        set_clock(clock)
    inter = new_intersection()
    device = new_device(inter["id"])
    crew = new_crew()
    ticket = new_ticket(device["id"])
    triage(ticket["id"])
    wo = new_work_order(device["id"], work_type="REPAIR",
                        estimated_labor_hours=1.0, ticket_id=ticket["id"])
    schedule_work_order(wo["id"], crew["id"])
    dispatch_work_order(wo["id"])
    complete_work_order(wo["id"], crew["id"], actual_labor_hours=1.0)
    resolved = get_success_data(api_client.resolve_ticket(ticket["id"], DISPATCHER))
    return {"intersection": inter, "device": device, "crew": crew,
            "ticket": resolved, "wo_id": wo["id"]}


# ─── Tier 4: pole / attachment setups ─────────────────
def setup_pole_with_approved_attachment(capacity=100, load_units=30, mount_zone="LOW",
                                        effective_from="2026-04-01T00:00:00Z",
                                        effective_to="2026-05-01T00:00:00Z",
                                        attacher_name="A", intersection_id=None):
    """Pole + one APPROVED attachment. Returns (fresh_pole, attachment). The
    returned pole is re-read so its version/committed_load_units reflect the approve."""
    pole_overrides = {"load_capacity_units": capacity}
    if intersection_id is not None:
        pole_overrides["intersection_id"] = intersection_id
    pole = new_pole(**pole_overrides)
    att = new_pole_attachment(
        pole["id"], pole["version"], attacher_name=attacher_name, mount_zone=mount_zone,
        load_units=load_units, effective_from=effective_from, effective_to=effective_to)
    get_success_data(api_client.approve_pole_attachment(att["id"], UTILITY))
    fresh_pole = get_pole(pole["id"])
    return fresh_pole, att


# ─── Tier 5: cascade / emergency setups ───────────────
def setup_emergency_intersection():
    """Intersection with a pole-mounted CRITICAL device and a KNOCKDOWN ticket
    triaged (struck_pole true) → intersection driven to EMERGENCY. Returns a dict
    with intersection/pole/device/ticket_id."""
    inter = new_intersection()
    pole = new_pole(load_capacity_units=100, intersection_id=inter["id"])
    device = new_device(inter["id"], pole_id=pole["id"],
                        device_type="SIGNAL_CONTROLLER", criticality="CRITICAL",
                        replacement_cost=5000.00)
    ticket = new_ticket(device["id"], source="KNOCKDOWN", reported_severity=5,
                        description="vehicle knockdown", hazard_flag=True, struck_pole=True)
    triage(ticket["id"])
    return {"intersection": inter, "pole": pole, "device": device,
            "ticket_id": ticket["id"]}


def setup_cleared_locate(intersection_id, valid_days=None):
    """Locate request created, marked, and cleared. Returns the cleared locate."""
    overrides = {}
    if valid_days is not None:
        overrides["valid_days"] = valid_days
    locate = new_locate_request(intersection_id, **overrides)
    get_success_data(api_client.mark_locate_request(locate["id"], UTILITY))
    return get_success_data(api_client.clear_locate_request(locate["id"], UTILITY))
