"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and uses the lenient
get_success_data() validator, so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error. Each test runs against a
freshly restarted, empty server, so every helper builds its preconditions from
scratch using only PRD-declared endpoints.

Common default windows used across dispatch/permit setups:
  - a scheduling window wide enough to hold any dispatch: 06:00 -> 20:00
  - a default dispatch window: 08:00 -> 12:00 (240 minutes)
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_asset_payload,
    create_crew_payload,
    create_work_order_payload,
    create_yard_payload,
    create_material_item_payload,
    create_row_permit_payload,
)
from .test_users import (
    supervisor_headers,
    dispatcher_headers,
    crewlead_headers,
    coordinator_headers,
    inspector_headers,
)

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
SCHED_START = "2026-06-02T06:00:00Z"
SCHED_END = "2026-06-02T20:00:00Z"
DEFAULT_WINDOW = ("2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z")


# --- Primitive builders -------------------------------------------------

def set_clock(api, iso=DEFAULT_CLOCK):
    return get_success_data(api.set_clock({"to_iso8601": iso}, supervisor_headers()))


def make_asset(api, **overrides):
    return get_success_data(api.create_asset(create_asset_payload(**overrides), supervisor_headers()))


def make_crew(api, **overrides):
    return get_success_data(api.create_crew(create_crew_payload(**overrides), supervisor_headers()))


def make_yard(api, **overrides):
    return get_success_data(api.create_yard(create_yard_payload(**overrides), supervisor_headers()))


def make_material_item(api, yard_id=None, **overrides):
    if yard_id is None:
        yard_id = make_yard(api)["id"]
    payload = create_material_item_payload(yard_id=yard_id, **overrides)
    return get_success_data(api.create_material_item(payload, supervisor_headers()))


def make_work_order(api, asset_id, **overrides):
    payload = create_work_order_payload(asset_id=asset_id, **overrides)
    return get_success_data(api.create_work_order(payload, dispatcher_headers()))


def schedule_work_order(api, wo_id, scheduled_start=SCHED_START, scheduled_end=SCHED_END):
    return get_success_data(api.schedule_work_order(
        wo_id, {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}, dispatcher_headers()))


def reserve_crew(api, work_order_id, crew_id, window_start=DEFAULT_WINDOW[0],
                 window_end=DEFAULT_WINDOW[1], labor_hours=4, headers=None):
    """Reserve a crew (create a Dispatch), reading the crew's current version
    for the OCC check just before the write."""
    crew = get_success_data(api.get_crew(crew_id, dispatcher_headers()))
    payload = {
        "work_order_id": work_order_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
        "labor_hours": labor_hours,
        "expected_crew_version": crew["version"],
    }
    return get_success_data(api.create_dispatch(payload, headers or dispatcher_headers()))


def reserve_material(api, work_order_id, material_item_id, qty, headers=None):
    """Reserve material, reading the item's current version for the OCC check
    just before the write."""
    item = get_success_data(api.get_material_item(material_item_id, dispatcher_headers()))
    payload = {
        "work_order_id": work_order_id,
        "material_item_id": material_item_id,
        "qty": qty,
        "expected_material_item_version": item["version"],
    }
    return get_success_data(api.create_material_reservation(payload, headers or dispatcher_headers()))


def make_row_permit(api, work_order_id, **overrides):
    payload = create_row_permit_payload(work_order_id=work_order_id, **overrides)
    return get_success_data(api.create_row_permit(payload, coordinator_headers()))


# --- Composite scenarios ------------------------------------------------

def setup_scheduled_work_order(api, clock=DEFAULT_CLOCK, asset_overrides=None,
                               wo_overrides=None):
    """Clock set, one asset, one DRAFT work order advanced to SCHEDULED.
    Returns dict(asset, wo)."""
    set_clock(api, clock)
    asset = make_asset(api, **(asset_overrides or {}))
    wo = make_work_order(api, asset["id"], **(wo_overrides or {}))
    schedule_work_order(api, wo["id"])
    wo = get_success_data(api.get_work_order(wo["id"], dispatcher_headers()))
    return {"asset": asset, "wo": wo}


def setup_in_progress_work_order(api, clock=DEFAULT_CLOCK, asset_overrides=None,
                                 crew_overrides=None, wo_overrides=None,
                                 labor_hours=4, window=DEFAULT_WINDOW,
                                 reservations=None):
    """Full chain to an IN_PROGRESS work order carrying one crew dispatch and
    (optionally) a set of material reservations.

    reservations: list of dicts {"item_id":..., "qty":...} reserved while the
    work order is SCHEDULED (before dispatch). Returns dict(asset, crew, wo).
    """
    set_clock(api, clock)
    asset = make_asset(api, **(asset_overrides or {}))
    crew = make_crew(api, **(crew_overrides or {}))
    wo = make_work_order(api, asset["id"], **(wo_overrides or {}))
    schedule_work_order(api, wo["id"])
    for r in (reservations or []):
        reserve_material(api, wo["id"], r["item_id"], r["qty"])
    reserve_crew(api, wo["id"], crew["id"], window[0], window[1], labor_hours)
    get_success_data(api.dispatch_work_order(wo["id"], dispatcher_headers()))
    get_success_data(api.start_work_order(wo["id"], crewlead_headers()))
    wo = get_success_data(api.get_work_order(wo["id"], dispatcher_headers()))
    return {"asset": asset, "crew": crew, "wo": wo}


def create_submitted_inspection(api, asset_id, inspector_user="insp-1",
                                inspection_type="CONDITION", raw_distress_index=20,
                                clock=None):
    """Create an inspection (as the given inspector user) and submit it.
    Returns the submitted inspection dict."""
    if clock is not None:
        set_clock(api, clock)
    payload = {
        "asset_id": asset_id,
        "inspection_type": inspection_type,
        "raw_distress_index": raw_distress_index,
        "scheduled_window_start": "2026-06-01T08:00:00Z",
        "scheduled_window_end": "2026-06-01T09:00:00Z",
    }
    insp = get_success_data(api.create_inspection(payload, inspector_headers(inspector_user)))
    get_success_data(api.submit_inspection(insp["id"], inspector_headers(inspector_user)))
    return get_success_data(api.get_inspection(insp["id"], inspector_headers(inspector_user)))
