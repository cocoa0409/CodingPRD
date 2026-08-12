"""InstallTask endpoints: assignment (crew/site booking checks), get/list,
start, complete (checklist + verification cascade), unassign."""
from flask import Blueprint, request

from db import new_record, now_ts, public, store, touch
from errors import (
    ERR_CREW_DOUBLE_BOOKED,
    ERR_INSTALL_CHECKLIST_INCOMPLETE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SITE_CAPACITY_EXCEEDED,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles, scope_crew
from response import success
from services.cascade import po_of_line, recompute_crew
from validation import (
    body,
    get_or_404,
    occupied_dates,
    paginate,
    parse_pagination,
    pdate,
    req_bool,
    req_date,
    req_int,
    req_str,
)

bp = Blueprint("install_tasks", __name__)


def _check_crew_double_booking(crew_id, start_s, end_s):
    """No two non-CANCELLED tasks of the same crew may overlap half-open
    [start_date, end_date); adjacency (end == next start) is allowed."""
    start = pdate(start_s)
    end = pdate(end_s)
    for t in store.install_tasks.values():
        if t["crew_id"] != crew_id or t["status"] == "CANCELLED":
            continue
        t_start = pdate(t["start_date"])
        t_end = pdate(t["end_date"])
        if start < t_end and t_start < end:
            raise_err(ERR_CREW_DOUBLE_BOOKED, "Crew already has a non-CANCELLED task overlapping this interval")


def _check_site_capacity(site, start_s, end_s, crew_count):
    """For every occupied date d: summed crew_count + new crew_count must not
    exceed site.daily_crew_capacity (== capacity is allowed)."""
    for d in occupied_dates(start_s, end_s):
        load = 0
        for t in store.install_tasks.values():
            if t["school_site_id"] != site["id"] or t["status"] == "CANCELLED":
                continue
            if pdate(t["start_date"]) <= d < pdate(t["end_date"]):
                load += t["crew_count"]
        if load + crew_count > site["daily_crew_capacity"]:
            raise_err(ERR_SITE_CAPACITY_EXCEEDED, "Summed crew_count on an occupied date would exceed the site's daily_crew_capacity")


def create_install_task_record(shipment, crew, site_id, room_label, start_date, end_date, crew_count):
    """Shared by POST /v1/install-tasks and the damage-approval cascade.
    Crew double-booking and site capacity are checked before any mutation."""
    site = store.school_sites.get(site_id)
    _check_crew_double_booking(crew["id"], start_date, end_date)
    _check_site_capacity(site, start_date, end_date, crew_count)

    days = (pdate(end_date) - pdate(start_date)).days
    crew_days = crew_count * days
    rec = new_record({
        "shipment_id": shipment["id"],
        "crew_id": crew["id"],
        "school_site_id": site_id,
        "room_label": room_label,
        "start_date": start_date,
        "end_date": end_date,
        "crew_count": crew_count,
        "crew_days": crew_days,
        "completed_checklist": [],
        "status": "SCHEDULED",
    })
    store.install_tasks[rec["id"]] = rec
    recompute_crew(crew)  # booked_days += crew_days (ledger sync)
    return rec


@bp.route("/v1/install-tasks", methods=["POST"])
def create_install_task():
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    data = body()

    shipment_id = data.get("shipment_id")
    crew_id = data.get("crew_id")
    school_site_id = data.get("school_site_id")

    # priority 4: body FK existence in canonical order (school_site_id -> crew_id -> shipment_id)
    site = None
    if isinstance(school_site_id, str):
        site = get_or_404(store.school_sites, school_site_id, "school site")
    crew = None
    if isinstance(crew_id, str):
        crew = get_or_404(store.crews, crew_id, "crew")
    shipment = None
    if isinstance(shipment_id, str):
        shipment = get_or_404(store.shipments, shipment_id, "shipment")

    # priority 5: shape
    shipment_id = req_str(data, "shipment_id")
    crew_id = req_str(data, "crew_id")
    school_site_id = req_str(data, "school_site_id")
    room_label = req_str(data, "room_label")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    crew_count = req_int(data, "crew_count", minimum=1)
    if pdate(end_date) <= pdate(start_date):
        raise_err(ERR_INVALID_REQUEST, "end_date must be strictly later than start_date")
    if shipment["school_site_id"] != school_site_id:
        raise_err(ERR_INVALID_REQUEST, "school_site_id must equal the shipment's site")

    # priority 6: shipment must be SCHEDULED or DELIVERED
    if shipment["status"] not in ("SCHEDULED", "DELIVERED"):
        raise_err(ERR_INVALID_STATE, f"Cannot create an install task for a shipment in status {shipment['status']}")

    rec = create_install_task_record(shipment, crew, school_site_id, room_label, start_date, end_date, crew_count)
    return success(public(rec), code=201)


@bp.route("/v1/install-tasks/<rid>", methods=["GET"])
def get_install_task(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.install_tasks, rid, "install task")
    return success(public(rec), code=200)


@bp.route("/v1/install-tasks", methods=["GET"])
def list_install_tasks():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.install_tasks.values())
    shipment_id = request.args.get("shipment_id")
    crew_id = request.args.get("crew_id")
    school_site_id = request.args.get("school_site_id")
    status = request.args.get("status")
    if shipment_id is not None:
        records = [r for r in records if r["shipment_id"] == shipment_id]
    if crew_id is not None:
        records = [r for r in records if r["crew_id"] == crew_id]
    if school_site_id is not None:
        records = [r for r in records if r["school_site_id"] == school_site_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


def _load_scoped_task(caller, rid):
    rec = store.install_tasks.get(rid)
    if rec is not None:
        scope_crew(caller, rec["crew_id"])  # priority 3
    return get_or_404(store.install_tasks, rid, "install task")  # priority 4


@bp.route("/v1/install-tasks/<rid>/start", methods=["POST"])
def start_install_task(rid):
    caller = authenticate()
    require_roles(caller, ["CrewLead"])
    task = _load_scoped_task(caller, rid)
    body()

    if task["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"Cannot start a task in status {task['status']}")
    # priority 7: goods must be on site
    shipment = store.shipments.get(task["shipment_id"])
    if shipment is None or shipment["status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "Install task start requires the shipment to be DELIVERED")

    task["status"] = "IN_PROGRESS"
    touch(task)
    return success(public(task), code=200)


@bp.route("/v1/install-tasks/<rid>/complete", methods=["POST"])
def complete_install_task(rid):
    caller = authenticate()
    require_roles(caller, ["CrewLead"])
    task = _load_scoped_task(caller, rid)
    data = body()

    # priority 5: checklist payload shape
    uncrated = req_bool(data, "uncrated")
    debris_removed = req_bool(data, "debris_removed")
    placed = req_bool(data, "placed")

    # priority 6: state guard
    if task["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, f"Cannot complete a task in status {task['status']}")
    if not (uncrated and debris_removed and placed):
        raise_err(ERR_INSTALL_CHECKLIST_INCOMPLETE, "uncrated, debris_removed and placed must all be true")

    task["status"] = "COMPLETED"
    task["completed_checklist"] = ["UNCRATED", "DEBRIS_REMOVED", "PLACED"]
    touch(task)

    crew = store.crews.get(task["crew_id"])
    if crew is not None:
        recompute_crew(crew)  # booked_days -= crew_days (release)

    shipment = store.shipments.get(task["shipment_id"])
    if shipment is not None:
        # verification cascade: shipment lines DELIVERED -> VERIFIED, installed_at := clock
        for sl_entry in shipment["lines"]:
            line = store.po_lines.get(sl_entry["po_line_id"])
            if line is not None and line["status"] == "DELIVERED" and line["delivered_qty"] > 0:
                line["status"] = "VERIFIED"
                line["installed_at"] = now_ts()
                line["_installed_qty"] = line["delivered_qty"]
                touch(line)
                _maybe_fulfill_po(line)

        # bubble-up: all non-CANCELLED tasks complete -> shipment COMPLETED
        if shipment["status"] == "DELIVERED":
            tasks = [t for t in store.install_tasks.values()
                     if t["shipment_id"] == shipment["id"] and t["status"] != "CANCELLED"]
            if tasks and all(t["status"] == "COMPLETED" for t in tasks):
                shipment["status"] = "COMPLETED"
                touch(shipment)

    return success(public(task), code=200)


def _maybe_fulfill_po(line):
    """When every non-CANCELLED line of the PO is VERIFIED, the PO bubbles
    IN_FULFILLMENT -> FULFILLED."""
    po = po_of_line(line)
    if po is None or po["status"] != "IN_FULFILLMENT":
        return
    siblings = [l for l in store.po_lines.values()
                if l["purchase_order_id"] == po["id"] and l["status"] != "CANCELLED"]
    if siblings and all(l["status"] == "VERIFIED" for l in siblings):
        po["status"] = "FULFILLED"
        touch(po)


@bp.route("/v1/install-tasks/<rid>/unassign", methods=["POST"])
def unassign_install_task(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    task = get_or_404(store.install_tasks, rid, "install task")
    body()

    if task["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, f"Cannot unassign a task in status {task['status']}")

    task["status"] = "CANCELLED"
    touch(task)
    crew = store.crews.get(task["crew_id"])
    if crew is not None:
        recompute_crew(crew)  # compensating release of the booking
    return success(public(task), code=200)
