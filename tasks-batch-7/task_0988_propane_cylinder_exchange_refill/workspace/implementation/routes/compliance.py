"""Certification records (two-signature condemn protocol) and leak reports."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_FORBIDDEN, ERR_CYLINDER_CONDEMNED, ERR_SEGREGATION_OF_DUTIES,
    ERR_LEAK_ALREADY_OPEN, ERR_REINSPECTION_REQUIRED, ERR_VALIDATION,
)
from middleware import get_actor, require_roles
from response import success_object, success_list
from services import core
from util import (
    body, req_str, opt_str, req_enum, opt_bool, add_years, paginate,
    sorted_by_creation,
)

bp = Blueprint("compliance", __name__)

CERT_READ_ROLES = ("Technician", "PlatformAdmin", "ComplianceOfficer")
LEAK_READ_ROLES = ("SiteClerk", "PlatformAdmin", "ComplianceOfficer", "HostSiteManager")


def _get_record(record_id):
    r = db.cert_records.get(record_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Certification record not found")
    return r


def _get_report(report_id):
    r = db.leak_reports.get(report_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Leak report not found")
    return r


def _acting_technician(uid):
    """The acting technician must be a registered, ACTIVE technician (stage 2)."""
    tech = db.technicians.get(uid)
    if tech is None or tech["status"] != "ACTIVE":
        raise ApiError(ERR_FORBIDDEN, 403, "Acting technician is not an ACTIVE technician")
    return tech


# ---------------------------------------------------------------------------
# Certification records
# ---------------------------------------------------------------------------

@bp.route("/certification-records", methods=["POST"])
def create_cert_record():
    uid, role = get_actor()
    require_roles(role, ("Technician",))
    b = body()
    cylinder_id = req_str(b, "cylinder_id")
    method = req_enum(b, "method", ("VISUAL", "HYDROSTATIC"))
    outcome = req_enum(b, "outcome", ("PASS", "CONDEMN"))
    note = opt_str(b, "note", "")

    # Stage 2 authorization: technician active; cert_level gates HYDROSTATIC and CONDEMN.
    tech = _acting_technician(uid)
    if method == "HYDROSTATIC" and tech["cert_level"] != "FULL":
        raise ApiError(ERR_FORBIDDEN, 403, "HYDROSTATIC method requires cert_level FULL")
    if outcome == "CONDEMN" and tech["cert_level"] != "FULL":
        raise ApiError(ERR_FORBIDDEN, 403, "CONDEMN requests require cert_level FULL")

    # Stage 4: body reference.
    cyl = db.cylinders.get(cylinder_id)
    if cyl is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "cylinder_id does not reference an existing cylinder")
    # Stage 7: condemned cylinders can never be certified again.
    if cyl["cert_status"] == "CONDEMNED":
        raise ApiError(ERR_CYLINDER_CONDEMNED, 409, "Cylinder is CONDEMNED (terminal)")

    performed_on = db.current_date()
    previous_expiry = cyl["certification_expires_on"]
    if outcome == "PASS":
        years = core.VISUAL_RECERT_YEARS if method == "VISUAL" else core.HYDROSTATIC_RECERT_YEARS
        new_expiry = add_years(performed_on, years)
        record = db.new_entity({
            "cylinder_id": cylinder_id,
            "technician_id": uid,
            "method": method,
            "outcome": outcome,
            "performed_on": performed_on,
            "previous_expires_on": previous_expiry,
            "new_expires_on": new_expiry,
            "confirmer_technician_id": None,
            "note": note,
            "status": "RECORDED",
        })
        cyl["certified_on"] = performed_on
        cyl["certification_expires_on"] = new_expiry
        cyl["cert_method_last"] = method
        cyl["cert_status"] = "CERTIFIED"
        db.touch(cyl)
    else:
        record = db.new_entity({
            "cylinder_id": cylinder_id,
            "technician_id": uid,
            "method": method,
            "outcome": outcome,
            "performed_on": performed_on,
            "previous_expires_on": previous_expiry,
            "new_expires_on": None,
            "confirmer_technician_id": None,
            "note": note,
            "status": "PENDING_SECOND",
        })
    db.cert_records[record["id"]] = record
    return success_object(core.serialize(record), 201)


@bp.route("/certification-records/<recordId>", methods=["GET"])
def get_cert_record(recordId):
    uid, role = get_actor()
    require_roles(role, CERT_READ_ROLES)
    return success_object(core.serialize(_get_record(recordId)))


@bp.route("/certification-records", methods=["GET"])
def list_cert_records():
    uid, role = get_actor()
    require_roles(role, CERT_READ_ROLES)
    items = list(db.cert_records.values())
    for param in ("cylinder_id", "technician_id", "confirmer_technician_id", "outcome", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(r) for r in page], total, limit, offset)


def _second_signature(recordId):
    uid, role = get_actor()
    require_roles(role, ("Technician",))
    # Stage 2: confirming/rejecting technician must be ACTIVE with cert_level FULL.
    tech = _acting_technician(uid)
    if tech["cert_level"] != "FULL":
        raise ApiError(ERR_FORBIDDEN, 403, "Second signature requires cert_level FULL")
    record = _get_record(recordId)
    if record["status"] != "PENDING_SECOND":
        raise ApiError(ERR_INVALID_STATE, 409, "Record is not PENDING_SECOND")
    return uid, record


@bp.route("/certification-records/<recordId>/confirm", methods=["POST"])
def confirm_cert_record(recordId):
    uid, record = _second_signature(recordId)
    cyl = db.cylinders[record["cylinder_id"]]
    # Stage 7: cylinder must not already be condemned.
    if cyl["cert_status"] == "CONDEMNED":
        raise ApiError(ERR_CYLINDER_CONDEMNED, 409, "Cylinder is already CONDEMNED")
    # Stage 14: segregation of duties.
    if uid == record["technician_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Confirmer must differ from the requesting technician")
    record["confirmer_technician_id"] = uid
    record["status"] = "CONFIRMED"
    db.touch(record)
    # Condemn cascade hop 1: cylinder leaves the sellable population.
    cyl["cert_status"] = "CONDEMNED"
    db.touch(cyl)
    return success_object(core.serialize(record))


@bp.route("/certification-records/<recordId>/reject", methods=["POST"])
def reject_cert_record(recordId):
    uid, record = _second_signature(recordId)
    # Stage 14: segregation of duties.
    if uid == record["technician_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Rejecter must differ from the requesting technician")
    record["confirmer_technician_id"] = uid
    record["status"] = "REJECTED"
    db.touch(record)
    return success_object(core.serialize(record))


# ---------------------------------------------------------------------------
# Leak reports
# ---------------------------------------------------------------------------

@bp.route("/leak-reports", methods=["POST"])
def create_leak_report():
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    b = body()
    site_id = req_str(b, "site_id")
    severity = req_enum(b, "severity", ("MINOR", "MAJOR"))
    quarantine_cage = opt_bool(b, "quarantine_cage", False)
    cylinder_id = opt_str(b, "cylinder_id", None)
    note = opt_str(b, "note", "")

    if site_id not in db.sites:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")
    if cylinder_id is not None and cylinder_id not in db.cylinders:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "cylinder_id does not reference an existing cylinder")
    # Stage 11: at most one open (REPORTED or CONFIRMED) leak per site.
    for r in db.leak_reports.values():
        if r["site_id"] == site_id and r["status"] in ("REPORTED", "CONFIRMED"):
            raise ApiError(ERR_LEAK_ALREADY_OPEN, 409, "Site already has an open leak report")

    report = db.new_entity({
        "site_id": site_id,
        "cylinder_id": cylinder_id,
        "severity": severity,
        "quarantine_cage": quarantine_cage,
        "reporter_clerk_id": uid,
        "note": note,
        "confirmed_by": None,
        "confirmed_on": None,
        "resolved_by": None,
        "resolution_note": None,
        "false_alarm_reason": None,
        "status": "REPORTED",
    })
    db.leak_reports[report["id"]] = report
    return success_object(core.serialize(report), 201)


@bp.route("/leak-reports/<reportId>", methods=["GET"])
def get_leak_report(reportId):
    uid, role = get_actor()
    require_roles(role, LEAK_READ_ROLES)
    r = _get_report(reportId)
    if role == "HostSiteManager" and r["site_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "Host-site manager may only read own site's leak reports")
    return success_object(core.serialize(r))


@bp.route("/leak-reports", methods=["GET"])
def list_leak_reports():
    uid, role = get_actor()
    require_roles(role, LEAK_READ_ROLES)
    items = list(db.leak_reports.values())
    if role == "HostSiteManager":
        items = [r for r in items if r["site_id"] == uid]
    for param in ("site_id", "cylinder_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(r) for r in page], total, limit, offset)


@bp.route("/leak-reports/<reportId>/confirm", methods=["POST"])
def confirm_leak_report(reportId):
    uid, role = get_actor()
    require_roles(role, ("ComplianceOfficer",))
    r = _get_report(reportId)
    if r["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REPORTED leak can be confirmed")
    r["confirmed_by"] = uid
    r["confirmed_on"] = db.current_date()
    r["status"] = "CONFIRMED"
    db.touch(r)

    if r["severity"] == "MAJOR" or r["quarantine_cage"]:
        # Cage quarantine cascade: every FLEET cylinder at the site in FULL or
        # EMPTY fill status becomes QUARANTINED (each bumps its own version).
        for c in db.cylinders.values():
            if (
                c["owner_kind"] == "FLEET"
                and c["current_site_id"] == r["site_id"]
                and c["fill_status"] in ("FULL", "EMPTY")
            ):
                c["fill_status"] = "QUARANTINED"
                db.touch(c)
        # Posture is derived on read (SALES_BLOCKED); the moment it blocks,
        # every DRAFT order and every OPEN/WEIGHED ticket at the site auto-voids.
        for o in db.exchange_orders.values():
            if o["site_id"] == r["site_id"] and o["status"] == "DRAFT":
                o["status"] = "VOIDED"
                o["void_reason"] = "SAFETY"
                db.touch(o)
        for t in db.refill_tickets.values():
            if t["site_id"] == r["site_id"] and t["status"] in ("OPEN", "WEIGHED"):
                t["status"] = "VOIDED"
                db.touch(t)
    return success_object(core.serialize(r))


@bp.route("/leak-reports/<reportId>/resolve", methods=["POST"])
def resolve_leak_report(reportId):
    uid, role = get_actor()
    require_roles(role, ("ComplianceOfficer",))
    r = _get_report(reportId)
    b = body()
    resolution_note = req_str(b, "resolution_note")
    if r["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a CONFIRMED leak can be resolved")
    # Stage 12: quarantining leaks require post-confirmation PASS re-inspection evidence.
    if r["severity"] == "MAJOR" or r["quarantine_cage"]:
        evidence = False
        for rec in db.cert_records.values():
            if (
                rec["outcome"] == "PASS"
                and rec["status"] == "RECORDED"
                and rec["performed_on"] >= r["confirmed_on"]
            ):
                cyl = db.cylinders.get(rec["cylinder_id"])
                if (
                    cyl is not None
                    and cyl["owner_kind"] == "FLEET"
                    and cyl["current_site_id"] == r["site_id"]
                ):
                    evidence = True
                    break
        if not evidence:
            raise ApiError(ERR_REINSPECTION_REQUIRED, 409, "No post-confirmation PASS re-inspection on a site fleet cylinder")
    # Stage 14: segregation of duties.
    if uid == r["reporter_clerk_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Resolver must differ from the reporting clerk")
    r["resolved_by"] = uid
    r["resolution_note"] = resolution_note
    r["status"] = "RESOLVED"
    db.touch(r)
    return success_object(core.serialize(r))


@bp.route("/leak-reports/<reportId>/false-alarm", methods=["POST"])
def false_alarm_leak_report(reportId):
    uid, role = get_actor()
    require_roles(role, ("ComplianceOfficer",))
    r = _get_report(reportId)
    b = body()
    reason = req_str(b, "reason")
    if r["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REPORTED leak can be marked false alarm")
    r["false_alarm_reason"] = reason
    r["status"] = "FALSE_ALARM"
    db.touch(r)
    return success_object(core.serialize(r))
