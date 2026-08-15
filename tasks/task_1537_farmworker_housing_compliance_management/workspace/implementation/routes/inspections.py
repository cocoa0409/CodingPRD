"""Regulatory inspections: schedule, list, get, drive lifecycle with the
condemnation cascade and cure-certification segregation of duties."""

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, parse_date_strict,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("inspections", __name__)

AGENCIES = {"STATE_HOUSING", "USDA_RD", "HUD", "COUNTY_HEALTH"}
INSPECTION_TARGETS = {"CONDUCTED", "FINDINGS_ISSUED", "CURE_CERTIFIED", "CLOSED", "CANCELLED"}
FINDING_SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}


def _view(i):
    return {
        "id": i["id"],
        "site_id": i["site_id"],
        "agency": i["agency"],
        "scheduled_date": i["scheduled_date"],
        "status": i["status"],
        "findings": i["findings"],
        "open_critical_count": i["open_critical_count"],
        "issued_by": i["issued_by"],
        "cure_certified_by": i["cure_certified_by"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def _validate_findings(findings):
    if not isinstance(findings, list):
        raise err("ERR_INVALID_REQUEST", "findings must be an array")
    for f in findings:
        if not isinstance(f, dict):
            raise err("ERR_INVALID_REQUEST", "each finding must be an object")
        uid = f.get("unit_id")
        if not isinstance(uid, str) or not uid:
            raise err("ERR_INVALID_REQUEST", "finding unit_id is required")
        sev = f.get("severity")
        if sev not in FINDING_SEVERITIES:
            raise err("ERR_INVALID_REQUEST", "finding severity must be CRITICAL, MAJOR, or MINOR")
        code = f.get("code")
        if not isinstance(code, str) or not code:
            raise err("ERR_INVALID_REQUEST", "finding code is required")


@bp.route("/regulatory-inspections", methods=["POST"])
def create_inspection():
    require_roles("ComplianceInspector")
    body = get_body()
    site_id = require_string(body, "site_id")
    agency = require_enum(body, "agency", AGENCIES)
    scheduled = parse_date_strict(body.get("scheduled_date"), "scheduled_date")

    if db.sites.get(site_id) is None:
        raise err("ERR_SITE_NOT_FOUND")

    now = db.now_ts()
    i = {
        "id": db.new_id(),
        "site_id": site_id,
        "agency": agency,
        "scheduled_date": scheduled.isoformat(),
        "status": "SCHEDULED",
        "findings": None,
        "open_critical_count": 0,
        "issued_by": None,
        "cure_certified_by": None,
        "findings_issued_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.regulatory_inspections[i["id"]] = i
    return success_object(_view(i), status=201)


@bp.route("/regulatory-inspections", methods=["GET"])
def list_inspections():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.regulatory_inspections.values())
    site_f = get_filter("site_id")
    status_f = get_filter("status")
    if site_f is not None:
        items = [i for i in items if i["site_id"] == site_f]
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(i) for i in page], total, limit, offset)


@bp.route("/regulatory-inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    get_auth()
    i = db.regulatory_inspections.get(iid)
    if i is None:
        raise err("ERR_INSPECTION_NOT_FOUND")
    return success_object(_view(i))


def _refresh_open_critical_count(insp):
    """Count CRITICAL findings whose cited unit lacks a PASSED certification
    with inspection_date later than the findings' issued date."""
    findings = insp.get("findings") or []
    issued_date = insp.get("findings_issued_date")
    count = 0
    for f in findings:
        if f.get("severity") != "CRITICAL":
            continue
        unit_id = f.get("unit_id")
        resolved = False
        for cert in core.certifications_of_unit(unit_id):
            if cert["status"] == "PASSED" and cert.get("inspection_date"):
                if issued_date is None or cert["inspection_date"] > issued_date:
                    resolved = True
                    break
        if not resolved:
            count += 1
    insp["open_critical_count"] = count
    return count


@bp.route("/regulatory-inspections/<iid>", methods=["PUT"])
def drive_inspection(iid):
    user_id, _ = require_roles("ComplianceInspector")
    body = get_body()
    target = require_enum(body, "status", INSPECTION_TARGETS)
    insp = db.regulatory_inspections.get(iid)
    if insp is None:
        raise err("ERR_INSPECTION_NOT_FOUND")
    current = insp["status"]
    now = db.now_ts()
    clock_date = clock.current_date()
    site = db.sites.get(insp["site_id"])

    # Segregation of duties (priority 6) ahead of state validity.
    if target == "CURE_CERTIFIED" and current == "FINDINGS_ISSUED":
        if insp.get("issued_by") is not None and user_id == insp["issued_by"]:
            raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    allowed = {
        "SCHEDULED": {"CONDUCTED", "CANCELLED"},
        "CONDUCTED": {"FINDINGS_ISSUED"},
        "FINDINGS_ISSUED": {"CONDUCTED", "CURE_CERTIFIED"},
        "CURE_CERTIFIED": {"CLOSED"},
        "CLOSED": set(),
        "CANCELLED": set(),
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move inspection from {current} to {target}")

    if target == "CONDUCTED":
        if current == "SCHEDULED":
            if site is None or site["status"] != "OPEN":
                raise err("ERR_SITE_NOT_OPEN")
        insp["status"] = "CONDUCTED"
        insp["updated_at"] = now

    elif target == "FINDINGS_ISSUED":
        findings = body.get("findings")
        if findings is None:
            raise err("ERR_INVALID_REQUEST", "findings is required on FINDINGS_ISSUED")
        _validate_findings(findings)
        # Existence of cited units.
        for f in findings:
            if db.units.get(f["unit_id"]) is None:
                raise err("ERR_UNIT_NOT_FOUND")
        insp["status"] = "FINDINGS_ISSUED"
        insp["findings"] = findings
        insp["issued_by"] = user_id
        insp["findings_issued_date"] = clock_date.isoformat()
        insp["open_critical_count"] = sum(1 for f in findings if f["severity"] == "CRITICAL")
        insp["updated_at"] = now
        # Condemnation cascade for each CRITICAL finding.
        for f in findings:
            if f["severity"] != "CRITICAL":
                continue
            unit = db.units.get(f["unit_id"])
            if unit is None:
                continue
            if unit["status"] in ("CERTIFIED", "OCCUPIED", "HABITABILITY_HOLD"):
                unit["status"] = "CONDEMNED"
                unit["updated_at"] = now
                # Forced notice on ACTIVE/NOTICE tenancies of this unit.
                for t in core.tenancies_of_unit(unit["id"]):
                    if t["status"] in ("ACTIVE", "NOTICE"):
                        t["status"] = "NOTICE"
                        t["notice_reason"] = "CONDEMNATION"
                        t["updated_at"] = now
                        t["version"] += 1
                        hh = db.households.get(t["household_id"])
                        if hh is not None:
                            hh["rehousing_priority"] = True
                            hh["updated_at"] = now
        if site is not None:
            core.recompute_site_posture(site["id"])

    elif target == "CURE_CERTIFIED":
        # Requires open_critical_count == 0 (recomputed live).
        _refresh_open_critical_count(insp)
        if insp["open_critical_count"] > 0:
            raise err("ERR_UNRESOLVED_CRITICAL_FINDINGS")
        insp["status"] = "CURE_CERTIFIED"
        insp["cure_certified_by"] = user_id
        insp["updated_at"] = now
        # Every CONDEMNED unit cited by this inspection -> REGISTERED.
        findings = insp.get("findings") or []
        for f in findings:
            if f.get("severity") != "CRITICAL":
                continue
            unit = db.units.get(f["unit_id"])
            if unit is not None and unit["status"] == "CONDEMNED":
                unit["status"] = "REGISTERED"
                unit["updated_at"] = now
        if site is not None:
            core.recompute_site_posture(site["id"])

    elif target == "CLOSED":
        insp["status"] = "CLOSED"
        insp["updated_at"] = now

    elif target == "CANCELLED":
        insp["status"] = "CANCELLED"
        insp["updated_at"] = now

    return success_object(_view(insp))
