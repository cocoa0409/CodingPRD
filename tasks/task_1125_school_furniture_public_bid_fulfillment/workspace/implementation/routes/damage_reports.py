"""DamageReport endpoints: filing (delivery/install phase), get/list,
approve-replacement (three-link cascade), close-no-fault."""
from flask import Blueprint, request

from db import clock_date, new_record, public, store, touch
from errors import (
    ERR_DAMAGE_EXCEEDS_DELIVERED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REPLACEMENT_WINDOW_MISSED,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles, scope_crew
from response import success
from routes.install_tasks import (
    _check_crew_double_booking,
    _check_site_capacity,
    create_install_task_record,
)
from services.cascade import po_of_line
from services.pricing import replacement_deadline
from validation import (
    body,
    get_or_404,
    paginate,
    parse_pagination,
    pdate,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("damage_reports", __name__)


@bp.route("/v1/damage-reports", methods=["POST"])
def create_damage_report():
    caller = authenticate()
    require_roles(caller, ["CrewLead"])
    data = body()

    po_line_id = data.get("po_line_id")
    shipment_id = data.get("shipment_id")
    install_task_id = data.get("install_task_id")
    discovered = data.get("discovered_during")

    # priority 3: CrewLead files install-phase reports only for their own crew's tasks
    if discovered == "INSTALL" and isinstance(install_task_id, str):
        task = store.install_tasks.get(install_task_id)
        if task is not None:
            scope_crew(caller, task["crew_id"])

    # priority 4: provided body FK existence, canonical order (shipment -> install_task -> po_line)
    if isinstance(shipment_id, str):
        get_or_404(store.shipments, shipment_id, "shipment")
    if isinstance(install_task_id, str):
        get_or_404(store.install_tasks, install_task_id, "install task")
    line = None
    if isinstance(po_line_id, str):
        line = get_or_404(store.po_lines, po_line_id, "PO line")

    # priority 5: shape + discovery-context consistency (exactly one reference, matching the phase)
    po_line_id = req_str(data, "po_line_id")
    damaged_qty = req_int(data, "damaged_qty", minimum=1)
    discovered = req_enum(data, "discovered_during", ("DELIVERY", "INSTALL"))
    fault_type = req_enum(data, "fault_type", ("TRANSIT", "HANDLING", "DEFECT"))
    if discovered == "DELIVERY":
        if not isinstance(shipment_id, str) or install_task_id is not None:
            raise_err(ERR_INVALID_REQUEST, "A DELIVERY-phase report must reference exactly shipment_id")
    else:  # INSTALL
        if not isinstance(install_task_id, str) or shipment_id is not None:
            raise_err(ERR_INVALID_REQUEST, "An INSTALL-phase report must reference exactly install_task_id")

    # priority 14: damaged_qty may not exceed the line's delivered quantity
    if damaged_qty > line["delivered_qty"]:
        raise_err(ERR_DAMAGE_EXCEEDS_DELIVERED, "damaged_qty exceeds the line's delivered_qty")

    reported = clock_date()
    deadline = replacement_deadline(line, reported)
    rec = new_record({
        "po_line_id": po_line_id,
        "shipment_id": shipment_id if discovered == "DELIVERY" else None,
        "install_task_id": install_task_id if discovered == "INSTALL" else None,
        "damaged_qty": damaged_qty,
        "discovered_during": discovered,
        "fault_type": fault_type,
        "reported_date": reported.isoformat(),
        "replacement_deadline": deadline.isoformat(),
        "status": "OPEN",
    })
    store.damage_reports[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/damage-reports/<rid>", methods=["GET"])
def get_damage_report(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.damage_reports, rid, "damage report")
    return success(public(rec), code=200)


@bp.route("/v1/damage-reports", methods=["GET"])
def list_damage_reports():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.damage_reports.values())
    shipment_id = request.args.get("shipment_id")
    install_task_id = request.args.get("install_task_id")
    po_line_id = request.args.get("po_line_id")
    status = request.args.get("status")
    if shipment_id is not None:
        records = [r for r in records if r.get("shipment_id") == shipment_id]
    if install_task_id is not None:
        records = [r for r in records if r.get("install_task_id") == install_task_id]
    if po_line_id is not None:
        records = [r for r in records if r["po_line_id"] == po_line_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


def _report_site_id(report):
    """Destination site from the report's shipment or the shipment behind its install task."""
    if report.get("shipment_id"):
        shipment = store.shipments.get(report["shipment_id"])
        return shipment["school_site_id"] if shipment else None
    if report.get("install_task_id"):
        task = store.install_tasks.get(report["install_task_id"])
        return task["school_site_id"] if task else None
    return None


@bp.route("/v1/damage-reports/<rid>/approve-replacement", methods=["POST"])
def approve_replacement(rid):
    caller = authenticate()
    require_roles(caller, ["ContractManager"])
    report = get_or_404(store.damage_reports, rid, "damage report")
    data = body()

    crew_id = data.get("crew_id")
    # priority 4: body FK existence
    crew = None
    if isinstance(crew_id, str):
        crew = get_or_404(store.crews, crew_id, "crew")

    # priority 5: shape
    scheduled_date = req_date(data, "scheduled_date")
    crew_id = req_str(data, "crew_id")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    crew_count = req_int(data, "crew_count", minimum=1)
    room_label = req_str(data, "room_label")
    if pdate(end_date) <= pdate(start_date):
        raise_err(ERR_INVALID_REQUEST, "end_date must be strictly later than start_date")

    # priority 6: report must be OPEN
    if report["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"Cannot approve a replacement for a report in status {report['status']}")

    # priority 8: replacement scheduled on or before the replacement deadline (inclusive)
    if pdate(scheduled_date) > pdate(report["replacement_deadline"]):
        raise_err(ERR_REPLACEMENT_WINDOW_MISSED, "Replacement scheduled_date is after the replacement_deadline")

    line = store.po_lines.get(report["po_line_id"])
    site_id = _report_site_id(report)
    site = store.school_sites.get(site_id)

    # Link 1: replacement shipment (its own cascade creation also advances the PO)
    shipment = new_record({
        "purchase_order_id": line["purchase_order_id"],
        "school_site_id": site_id,
        "kind": "REPLACEMENT",
        "damage_report_id": report["id"],
        "scheduled_date": scheduled_date,
        "lines": [{"po_line_id": line["id"], "qty": report["damaged_qty"]}],
        "status": "SCHEDULED",
    })
    # Links 1-3 atomically: booking constraints (crew double-booking 11, site
    # capacity 12) are validated BEFORE any cascade record is persisted.
    _check_crew_double_booking(crew["id"], start_date, end_date)
    _check_site_capacity(site, start_date, end_date, crew_count)

    store.shipments[shipment["id"]] = shipment
    po = po_of_line(line)
    if po is not None and po["status"] == "ACCEPTED":
        po["status"] = "IN_FULFILLMENT"
        touch(po)

    # Link 2 + 3: install task creation and crew booking ledger debit
    create_install_task_record(shipment, crew, site_id, room_label, start_date, end_date, crew_count)

    report["status"] = "REPLACEMENT_ORDERED"
    touch(report)
    return success(public(report), code=200)


@bp.route("/v1/damage-reports/<rid>/close-no-fault", methods=["POST"])
def close_no_fault(rid):
    caller = authenticate()
    require_roles(caller, ["ContractManager"])
    report = get_or_404(store.damage_reports, rid, "damage report")
    body()

    if report["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"Cannot close a report in status {report['status']}")
    report["status"] = "CLOSED_NO_FAULT"
    touch(report)
    return success(public(report), code=200)
