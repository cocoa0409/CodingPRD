"""Damage findings, owner notification and repair holds."""

from flask import Blueprint

import errors
import validation as v
from db import base_fields, db, now, ordered, touch
from errors import fail
from middleware import authenticate
from response import created, ok, ok_list
from services import lookup
from services.cascade import block_incoming_gate, release_incoming_gate
from services.checklist import NON_TERMINAL_TURNOVER_STATUSES
from services.listing import sort_default
from services.pay import sync_open_issue_count
from services.serialize import issue_report_view, repair_order_view

bp = Blueprint("issues", __name__)

ISSUE_TYPES = ("DAMAGE", "MAINTENANCE", "SAFETY", "CONSUMABLE_SHORTAGE")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ISSUE_STATUSES = ("REPORTED", "OWNER_NOTIFIED", "DISPATCHED", "RESOLVED")
REPAIR_STATUSES = ("DISPATCHED", "COMPLETED")


@bp.post("/issue-reports")
def create_issue_report():
    actor = authenticate(("Cleaner", "Coordinator"))
    body = v.json_body()
    turnover_id = v.req_string(body, "turnover_id", allow_empty=False)
    issue_type = v.req_enum(body, "issue_type", ISSUE_TYPES)
    severity = v.req_enum(body, "severity", SEVERITIES)
    description = v.req_string(body, "description", allow_empty=False)
    estimated_cost_cents = v.req_int(body, "estimated_cost_cents", minimum=0)
    guest_chargeable = v.opt_bool(body, "guest_chargeable", False)

    turnover = lookup.get_turnover(turnover_id)
    lookup.cleaner_scope_turnover(actor, turnover, ("ACCEPTED", "ACTIVE"))

    prop = db.properties[turnover["property_id"]]

    notify = (severity in ("HIGH", "CRITICAL")
              or estimated_cost_cents >= prop["owner_notify_min_cost_cents"])

    record = base_fields()
    record.update({
        "turnover_id": turnover["id"],
        "property_id": prop["id"],
        "reported_by_cleaner_id": actor.user_id if actor.is_cleaner else None,
        "issue_type": issue_type,
        "severity": severity,
        "description": description,
        "estimated_cost_cents": estimated_cost_cents,
        "guest_chargeable": guest_chargeable,
        "status": "OWNER_NOTIFIED" if notify else "REPORTED",
        "owner_notified_at": now() if notify else None,
    })
    db.issue_reports[record["id"]] = record
    sync_open_issue_count(prop)
    return created(issue_report_view(record))


@bp.get("/issue-reports")
def list_issue_reports():
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner", "PropertyOwner"))
    limit, offset = v.pagination()
    turnover_id = v.query_string("turnover_id")
    property_id = v.query_string("property_id")
    reported_by_cleaner_id = v.query_string("reported_by_cleaner_id")
    status = v.query_enum("status", ISSUE_STATUSES)
    severity = v.query_enum("severity", SEVERITIES)

    lookup.owner_scope_list(actor, property_id)

    rows = list(db.issue_reports.values())
    if turnover_id is not None:
        rows = [i for i in rows if i["turnover_id"] == turnover_id]
    if property_id is not None:
        rows = [i for i in rows if i["property_id"] == property_id]
    if reported_by_cleaner_id is not None:
        rows = [i for i in rows if i["reported_by_cleaner_id"] == reported_by_cleaner_id]
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if severity is not None:
        rows = [i for i in rows if i["severity"] == severity]
    rows = sort_default(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([issue_report_view(r) for r in page], limit, offset, total)


@bp.get("/issue-reports/<issue_id>")
def read_issue_report(issue_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner", "PropertyOwner"))
    issue = lookup.get_issue_report(issue_id)
    lookup.owner_scope_resource(actor, issue["property_id"])
    return ok(issue_report_view(issue))


@bp.post("/issue-reports/<issue_id>/dispatch")
def dispatch_issue_report(issue_id):
    actor = authenticate(("Coordinator", "PropertyOwner"))
    body = v.json_body()
    vendor_name = v.req_string(body, "vendor_name", allow_empty=False)
    scheduled_at = v.req_datetime(body, "scheduled_at")
    blocks_checkin = v.opt_bool(body, "blocks_checkin", False)

    issue = lookup.get_issue_report(issue_id)
    lookup.owner_scope_resource(actor, issue["property_id"])

    if issue["status"] not in ("REPORTED", "OWNER_NOTIFIED"):
        fail(errors.ERR_INVALID_ISSUE_STATE,
             "This finding has already been dispatched or resolved.")

    issue["status"] = "DISPATCHED"
    touch(issue)

    order = base_fields()
    order.update({
        "issue_report_id": issue["id"],
        "property_id": issue["property_id"],
        "vendor_name": vendor_name,
        "scheduled_at": scheduled_at,
        "blocks_checkin": blocks_checkin,
        "actual_cost_cents": None,
        "completion_note": None,
        "status": "DISPATCHED",
        "completed_at": None,
    })
    db.repair_orders[order["id"]] = order

    turnover = db.turnovers.get(issue["turnover_id"])
    if blocks_checkin and turnover is not None:
        if turnover["status"] in NON_TERMINAL_TURNOVER_STATUSES:
            turnover["pre_hold_status"] = turnover["status"]
            turnover["status"] = "ON_HOLD"
            turnover["blocking_repair_order_id"] = order["id"]
            touch(turnover)
            block_incoming_gate(turnover)

    return created(repair_order_view(order))


@bp.get("/repair-orders")
def list_repair_orders():
    actor = authenticate(("PlatformAdmin", "Coordinator", "PropertyOwner"))
    limit, offset = v.pagination()
    issue_report_id = v.query_string("issue_report_id")
    property_id = v.query_string("property_id")
    status = v.query_enum("status", REPAIR_STATUSES)

    lookup.owner_scope_list(actor, property_id)

    rows = list(db.repair_orders.values())
    if issue_report_id is not None:
        rows = [r for r in rows if r["issue_report_id"] == issue_report_id]
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_default(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([repair_order_view(r) for r in page], limit, offset, total)


@bp.get("/repair-orders/<order_id>")
def read_repair_order(order_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "PropertyOwner"))
    order = lookup.get_repair_order(order_id)
    lookup.owner_scope_resource(actor, order["property_id"])
    return ok(repair_order_view(order))


@bp.post("/repair-orders/<order_id>/complete")
def complete_repair_order(order_id):
    authenticate(("Coordinator",))
    body = v.json_body()
    actual_cost_cents = v.opt_int(body, "actual_cost_cents", minimum=0)
    completion_note = v.opt_string(body, "completion_note")

    order = lookup.get_repair_order(order_id)
    if order["status"] != "DISPATCHED":
        fail(errors.ERR_INVALID_REPAIR_STATE, "This repair order is already COMPLETED.")

    order["status"] = "COMPLETED"
    order["completed_at"] = now()
    if actual_cost_cents is not None:
        order["actual_cost_cents"] = actual_cost_cents
    if completion_note is not None:
        order["completion_note"] = completion_note
    touch(order)

    issue = db.issue_reports.get(order["issue_report_id"])
    if issue is not None and issue["status"] == "DISPATCHED":
        issue["status"] = "RESOLVED"
        touch(issue)
    sync_open_issue_count(db.properties.get(order["property_id"]))

    # Only a turnover carrying THIS order as its blocking order leaves ON_HOLD.
    for turnover in ordered(db.turnovers.values()):
        if turnover.get("blocking_repair_order_id") != order["id"]:
            continue
        restored = turnover.get("pre_hold_status")
        if restored:
            turnover["status"] = restored
        turnover["pre_hold_status"] = None
        turnover["blocking_repair_order_id"] = None
        touch(turnover)
        release_incoming_gate(turnover)

    return ok(repair_order_view(order))
