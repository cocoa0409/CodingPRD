"""Arrival and export reports (PRD 3.5)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("reports", __name__)

REPORT_TYPES = ("ARRIVAL", "EXPORT")
ALLOWED_BY_TYPE = {
    "IT": ("ARRIVAL",),
    "TE": ("ARRIVAL", "EXPORT"),
    "IE": ("EXPORT",),
}


def _approved_diversion_to(movement, port):
    for amendment in domain.amendments_of(movement["id"]):
        if amendment["amendment_type"] != "DIVERSION" or amendment["status"] != "APPROVED":
            continue
        if amendment["requested_destination_port_code"] == port["port_code"]:
            return True
    return False


@bp.route("/in-bond/reports", methods=["POST"])
def file_report():
    user_id, _role = require("BondedCarrier")

    peeked = v.peek_body().get("movement_id")
    if isinstance(peeked, str):
        target = db.movements.get(peeked)
        if target is not None and target["carrier_id"] != user_id:
            raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    movement_id = v.req_str(body, "movement_id")
    port_id = v.req_str(body, "port_id")
    report_type = v.req_enum(body, "report_type", REPORT_TYPES)
    packages_reported = v.req_int(body, "packages_reported", minimum=0)
    proof_of_export_ref = v.opt_str(body, "proof_of_export_ref")
    export_conveyance_ref = v.opt_str(body, "export_conveyance_ref")

    movement = db.movements.get(movement_id)
    if movement is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    port = db.ports.get(port_id)
    if port is None:
        raise ApiError("ERR_PORT_NOT_FOUND")
    if movement["carrier_id"] != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    type_allowed = report_type in ALLOWED_BY_TYPE.get(movement["in_bond_type"], ())
    transit = movement["transit_status"]

    # Band 9 - the movement's own state, only for a report type it can ever take.
    if type_allowed:
        if transit in ("CLOSED", "CANCELLED"):
            raise ApiError("ERR_MOVEMENT_INVALID_STATE")
        if report_type == "ARRIVAL" and transit in ("ARRIVED", "EXPORTED"):
            raise ApiError("ERR_MOVEMENT_INVALID_STATE")
        if report_type == "EXPORT":
            if transit == "EXPORTED":
                raise ApiError("ERR_MOVEMENT_INVALID_STATE")
            if movement["in_bond_type"] == "TE" and transit in ("IN_TRANSIT", "OVERDUE"):
                raise ApiError("ERR_MOVEMENT_INVALID_STATE")

    # Band 10 / 11.
    if movement["custody_status"] == "GENERAL_ORDER":
        raise ApiError("ERR_MOVEMENT_IN_GENERAL_ORDER")
    if movement["seal_number"] is None:
        raise ApiError("ERR_SEAL_NOT_APPLIED")
    if not movement["seal_intact"]:
        raise ApiError("ERR_SEAL_INTEGRITY_UNRESOLVED")
    if type_allowed and report_type == "ARRIVAL":
        destination = db.ports.get(movement["destination_port_id"])
        same_port = port["id"] == movement["destination_port_id"]
        same_region = destination is not None and destination["region_code"] == port["region_code"]
        if not (same_port or same_region or _approved_diversion_to(movement, port)):
            raise ApiError("ERR_UNAUTHORIZED_DIVERSION")

    # Band 13.
    if not type_allowed:
        raise ApiError("ERR_REPORT_TYPE_NOT_ALLOWED")

    now = db.now
    rec = new_record()
    rec.update({
        "movement_id": movement["id"],
        "port_id": port["id"],
        "report_type": report_type,
        "packages_reported": packages_reported,
        "proof_of_export_ref": proof_of_export_ref,
        "export_conveyance_ref": export_conveyance_ref,
        "status": "ACCEPTED",
        "reported_at": now,
        "package_discrepancy": movement["package_count"] - packages_reported,
    })
    db.reports[rec["id"]] = rec

    if report_type == "ARRIVAL":
        movement["transit_status"] = "ARRIVED"
        movement["arrival_port_id"] = port["id"]
        movement["arrival_reported_at"] = now
        movement["diversion_flag"] = port["id"] != movement["destination_port_id"]
        movement["go_deadline_utc"] = now + calc.days(calc.GO_DAYS)
        touch(movement)
        return ok(domain.report_json(rec), 201)

    # EXPORT: supersede an earlier export report still awaiting proof.
    for other in domain.reports_of(movement["id"]):
        if other["id"] == rec["id"] or other["report_type"] != "EXPORT":
            continue
        if other["status"] != "PENDING_PROOF":
            continue
        other["status"] = "SUPERSEDED"
        touch(other)

    if proof_of_export_ref is None:
        rec["status"] = "PENDING_PROOF"
        return ok(domain.report_json(rec), 201)

    movement["transit_status"] = "EXPORTED"
    movement["export_reported_at"] = now
    touch(movement)
    domain.close_if_exported(movement)
    return ok(domain.report_json(rec), 201)


@bp.route("/in-bond/reports/<report_id>/proof", methods=["POST"])
def perfect_report(report_id):
    user_id, _role = require("BondedCarrier")

    rec = db.reports.get(report_id)
    if rec is not None:
        movement = db.movements.get(rec["movement_id"])
        if movement is not None and movement["carrier_id"] != user_id:
            raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    proof_of_export_ref = v.req_str(body, "proof_of_export_ref")
    export_conveyance_ref = v.opt_str(body, "export_conveyance_ref")

    if rec is None:
        raise ApiError("ERR_REPORT_NOT_FOUND")
    if rec["status"] != "PENDING_PROOF":
        raise ApiError("ERR_REPORT_INVALID_STATE")

    movement = db.movements.get(rec["movement_id"])
    if movement is None:
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if movement["custody_status"] == "GENERAL_ORDER":
        raise ApiError("ERR_MOVEMENT_IN_GENERAL_ORDER")
    if not movement["seal_intact"]:
        raise ApiError("ERR_SEAL_INTEGRITY_UNRESOLVED")

    rec["status"] = "ACCEPTED"
    rec["proof_of_export_ref"] = proof_of_export_ref
    if export_conveyance_ref is not None:
        rec["export_conveyance_ref"] = export_conveyance_ref
    touch(rec)

    movement["transit_status"] = "EXPORTED"
    movement["export_reported_at"] = db.now
    touch(movement)
    domain.close_if_exported(movement)
    return ok(domain.report_json(rec))


@bp.route("/in-bond/reports/<report_id>", methods=["GET"])
def read_report(report_id):
    require(*ALL_ROLES)
    rec = db.reports.get(report_id)
    if rec is None:
        raise ApiError("ERR_REPORT_NOT_FOUND")
    return ok(domain.report_json(rec))


@bp.route("/in-bond/reports", methods=["GET"])
def list_reports():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = domain.rows(db.reports)
    for key in ("movement_id", "port_id", "report_type", "status"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [r for r in items if r[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.report_json(r) for r in page], limit, offset, total)
