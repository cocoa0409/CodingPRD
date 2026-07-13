"""Resource temporal semantics: half-open technician overlap (gap==0 allowed) vs buffered
24h equipment spacing (adjacency forbidden) — difficulty queue."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
)
from test_helpers.fixtures import (
    new_customer, new_site, new_equipment, new_technician, new_work_order,
    dispatch_work_order,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─────────────── Technician half-open overlap ───────────────
def _tech_with_dispatched_10_to_12(num_extra_equipment=2):
    cust = new_customer()
    site = new_site(cust["id"])
    equipment = [new_equipment(site["id"]) for _ in range(1 + num_extra_equipment)]
    tech = new_technician("BASIC")
    wo1 = new_work_order(site["id"], equipment[0]["id"],
                         planned_start="2026-05-10T10:00:00Z", planned_end="2026-05-10T12:00:00Z")
    dispatch_work_order(wo1["id"], tech["id"])
    return site, equipment, tech


def test_overlapping_technician_window_rejected(api):
    """PRD §3.3: "Overlap is evaluated on the half-open interval from `planned_start` up to
    `planned_end`, so two windows that merely touch at an endpoint (a gap of exactly zero) do
    not conflict, whereas any true overlap is rejected with `ERR_TECHNICIAN_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/technician_half_open_overlap
    """
    site, equipment, tech = _tech_with_dispatched_10_to_12()
    wo2 = new_work_order(site["id"], equipment[1]["id"],
                         planned_start="2026-05-10T11:00:00Z", planned_end="2026-05-10T13:00:00Z")
    res = api.transition_work_order(
        wo2["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    validate_error(res, "ERR_TECHNICIAN_SCHEDULE_CONFLICT")


def test_abutting_technician_window_allowed(api):
    """PRD §3.3: "Overlap is evaluated on the half-open interval from `planned_start` up to
    `planned_end`, so two windows that merely touch at an endpoint (a gap of exactly zero) do
    not conflict, whereas any true overlap is rejected with `ERR_TECHNICIAN_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/technician_half_open_overlap
    """
    site, equipment, tech = _tech_with_dispatched_10_to_12()
    wo3 = new_work_order(site["id"], equipment[2]["id"],
                         planned_start="2026-05-10T12:00:00Z", planned_end="2026-05-10T14:00:00Z")
    res = api.transition_work_order(
        wo3["id"], {"to_status": "DISPATCHED", "technician_id": tech["id"]}, DISPATCHER)
    dispatched = validate_success(res, 200)
    assert dispatched["status"] == "DISPATCHED", "a window abutting at the endpoint must be allowed"


# ─────────────── Equipment 24h buffer (adjacency forbidden) ───────────────
def _equipment_with_first_work_order():
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    new_work_order(site["id"], eq["id"],
                   planned_start="2026-05-10T08:00:00Z", planned_end="2026-05-10T10:00:00Z")
    return site, eq


def test_second_work_order_within_24h_buffer_rejected(api):
    """PRD §3.3: "the new window must be separated by at least 24 hours from the window of
    every other non-`CANCELLED` work order on the same equipment. Adjacency is forbidden — a
    gap of less than 24 hours, including touching or overlapping windows, is rejected with
    `ERR_EQUIPMENT_SERVICE_TOO_SOON`."

    Design: Difficulty/resource_temporal_overlap/equipment_service_buffer_24h
    """
    site, eq = _equipment_with_first_work_order()
    res = api.create_work_order(
        {"site_id": site["id"], "equipment_id": eq["id"], "service_type": "SCHEDULED",
         "planned_start": "2026-05-10T20:00:00Z", "planned_end": "2026-05-10T22:00:00Z"},
        DISPATCHER)
    validate_error(res, "ERR_EQUIPMENT_SERVICE_TOO_SOON")


def test_second_work_order_beyond_24h_buffer_allowed(api):
    """PRD §3.3: "the new window must be separated by at least 24 hours from the window of
    every other non-`CANCELLED` work order on the same equipment."

    Design: Difficulty/resource_temporal_overlap/equipment_service_buffer_24h
    """
    site, eq = _equipment_with_first_work_order()
    res = api.create_work_order(
        {"site_id": site["id"], "equipment_id": eq["id"], "service_type": "SCHEDULED",
         "planned_start": "2026-05-12T08:00:00Z", "planned_end": "2026-05-12T10:00:00Z"},
        DISPATCHER)
    created = validate_success(res, 201)
    assert created["status"] == "SCHEDULED", "a window >= 24h away must be accepted"
