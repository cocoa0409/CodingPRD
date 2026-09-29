"""Move-in inspections: scheduling, deficiency logging, tenant acknowledgement."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import base_row, bump, db, fmt_date, now_iso, sort_rows
from errors import ApiError
from services import core, lookup

bp = Blueprint("inspections", __name__)

INSPECTION_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                         mw.MAINTENANCE_TECH, mw.INSTALLATION_HOUSING_OFFICE)


def _sponsor_of(inspection):
    lease = db.leases.get(inspection["lease_id"])
    return lease["service_member_id"] if lease else None


@bp.post("/move-in-inspections")
def schedule_inspection():
    user_id, _role = mw.authenticate((mw.PROPERTY_MANAGER,))
    body = mw.json_body()
    lease_id = mw.v_id(body, "lease_id")
    scheduled_date = mw.v_date(body, "scheduled_date")
    lease = lookup.lease(lease_id)
    if lease["occupancy_status"] == "TERMINATED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if lease["occupancy_status"] != "PENDING_MOVE_IN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The lease is no longer awaiting move-in.")
    row = base_row()
    row["lease_id"] = lease["id"]
    row["scheduled_date"] = fmt_date(scheduled_date)
    row["conducted_by_user_id"] = user_id
    row["status"] = "SCHEDULED"
    row["deficiencies"] = []
    row["deficiency_count"] = 0
    row["critical_open_count"] = 0
    row["tenant_signature_name"] = None
    row["tenant_signature_at"] = None
    row["bill_of_rights_version_ack"] = None
    db.inspections[row["id"]] = row
    return resp.created(row)


@bp.get("/move-in-inspections/<inspection_id>")
def get_inspection(inspection_id):
    user_id, role = mw.authenticate(INSPECTION_READ_ROLES)
    existing = lookup.maybe("inspections", inspection_id)
    if existing is not None:
        mw.require_owner(role, user_id, _sponsor_of(existing))
    return resp.ok(lookup.inspection(inspection_id))


@bp.post("/move-in-inspections/<inspection_id>/deficiencies")
def log_deficiencies(inspection_id):
    mw.authenticate((mw.PROPERTY_MANAGER,))
    body = mw.json_body()
    if "deficiencies" not in body or body.get("deficiencies") is None:
        mw.bad("deficiencies", "is required")
    entries = body["deficiencies"]
    if not isinstance(entries, list):
        mw.bad("deficiencies", "must be an array")
    parsed = []
    for entry in entries:
        if not isinstance(entry, dict):
            mw.bad("deficiencies", "must contain objects")
        code = mw.v_enum(entry, "deficiency_code", mw.WORK_ORDER_CATEGORIES)
        room = mw.v_str(entry, "room")
        severity = mw.v_enum(entry, "severity", mw.DEFICIENCY_SEVERITIES)
        parsed.append({"deficiency_code": code, "room": room, "severity": severity})

    inspection = lookup.inspection(inspection_id)
    if inspection["status"] == "COMPLETED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if inspection["status"] not in ("SCHEDULED", "DEFICIENCIES_LOGGED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    seen = set(e["deficiency_code"] for e in inspection["deficiencies"])
    for entry in parsed:
        if entry["deficiency_code"] in seen:
            mw.bad("deficiency_code", "must be unique within the inspection")
        seen.add(entry["deficiency_code"])

    for entry in parsed:
        inspection["deficiencies"].append({
            "deficiency_code": entry["deficiency_code"],
            "room": entry["room"],
            "severity": entry["severity"],
            "status": "OPEN",
            "work_order_id": None,
        })
    if inspection["status"] == "SCHEDULED":
        inspection["status"] = "DEFICIENCIES_LOGGED"
    core.recompute_inspection_counts(inspection)
    bump(inspection)
    return resp.ok(inspection)


@bp.post("/move-in-inspections/<inspection_id>/tenant-acknowledge")
def tenant_acknowledge(inspection_id):
    user_id, role = mw.authenticate((mw.SERVICE_MEMBER,))
    existing = lookup.maybe("inspections", inspection_id)
    if existing is not None:
        mw.require_owner(role, user_id, _sponsor_of(existing))
    body = mw.json_body()
    signature_name = mw.v_str(body, "tenant_signature_name")
    version_ack = mw.v_str(body, "bill_of_rights_version_ack")

    inspection = lookup.inspection(inspection_id)
    if inspection["status"] == "COMPLETED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if inspection["status"] not in ("SCHEDULED", "DEFICIENCIES_LOGGED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    lease = lookup.lease(inspection["lease_id"])
    unit = lookup.lease_unit(lease)
    installation = lookup.unit_installation(unit)
    if version_ack != installation["bill_of_rights_version"]:
        mw.bad("bill_of_rights_version_ack",
               "must equal the installation's published Tenant Bill of Rights version")

    stamped_at = now_iso()
    inspection["status"] = "TENANT_ACKNOWLEDGED"
    inspection["tenant_signature_name"] = signature_name
    inspection["tenant_signature_at"] = stamped_at
    inspection["bill_of_rights_version_ack"] = version_ack

    lease["bill_of_rights_version_ack"] = version_ack
    lease["bill_of_rights_ack_at"] = stamped_at
    bump(lease)

    for entry in inspection["deficiencies"]:
        if entry["severity"] != "HABITABILITY_CRITICAL" or entry["status"] != "OPEN":
            continue
        order = core.create_work_order(
            unit, lease["id"], None, entry["deficiency_code"],
            "Move-in inspection deficiency %s in %s"
            % (entry["deficiency_code"], entry["room"]),
            True, inspection_deficiency_code=entry["deficiency_code"])
        entry["status"] = "WORK_ORDER_CREATED"
        entry["work_order_id"] = order["id"]

    core.recompute_inspection_counts(inspection)
    if int(inspection["critical_open_count"]) == 0:
        inspection["status"] = "COMPLETED"
    bump(inspection)
    return resp.ok(inspection)
