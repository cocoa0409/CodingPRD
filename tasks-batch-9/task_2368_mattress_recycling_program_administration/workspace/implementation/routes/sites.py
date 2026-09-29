"""Collection sites, enrollment lifecycle and monthly volume reporting."""

from flask import Blueprint, g

import calc
import response
import services
from db import clock, db
from errors import ApiError
from middleware import (ADMIN, AUDITOR, HAULER, RECYCLER, REGISTRANT,
                        SITE_OPERATOR, auth, get_program, get_site,
                        get_volume_report, own)
from util import (F, apply_filters, base_record, pagination, paginate, public,
                  sort_records, touch, validate_body)

bp = Blueprint("sites", __name__)


@bp.post("/collection-sites")
def create_site():
    auth([ADMIN])
    body = validate_body([
        F("state_program_id", "string"),
        F("operator_name", "string"),
        F("site_type", "enum",
          enum=["COLLECTION_SITE", "TRANSFER_STATION", "PERMANENT_DROPOFF"]),
        F("region_code", "string"),
    ])
    program = get_program(body["state_program_id"])
    rec = base_record()
    rec.update({
        "state_program_id": program["id"],
        "operator_name": body["operator_name"],
        "site_type": body["site_type"],
        "region_code": body["region_code"],
        "enrollment_status": "APPLIED",
        "contamination_strike_count": 0,
        "infestation_quarantine_until": None,
        "units_on_hand": 0,
        "units_in_transit": 0,
        "units_at_recycler_count": 0,
        "units_recycled_count": 0,
        "units_written_off_count": 0,
        "units_reported_total": 0,
        "suspended_at": None,
    })
    db.collection_sites[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/collection-sites/<site_id>")
def read_site(site_id):
    auth([ADMIN, AUDITOR, SITE_OPERATOR, HAULER, RECYCLER, REGISTRANT])
    site = get_site(site_id)
    if g.role == SITE_OPERATOR:
        own(site["id"])
    return response.obj(public(site))


@bp.get("/collection-sites")
def list_sites():
    auth([ADMIN, AUDITOR, SITE_OPERATOR, HAULER, REGISTRANT])
    limit, offset = pagination()
    records = sort_records(list(db.collection_sites.values()))
    records = apply_filters(records, [
        ("state_program_id", "state_program_id"),
        ("enrollment_status", "enrollment_status"),
        ("site_type", "site_type"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/collection-sites/<site_id>/enroll")
def enroll(site_id):
    auth([ADMIN])
    site = get_site(site_id)
    if site["enrollment_status"] != "APPLIED":
        raise ApiError("ERR_SITE_ENROLLMENT_STATE_INVALID")
    site["enrollment_status"] = "ENROLLED"
    touch(site)
    services.refresh_program_and_touch(db.state_programs[site["state_program_id"]])
    return response.obj(public(site))


@bp.post("/collection-sites/<site_id>/suspend")
def suspend(site_id):
    auth([ADMIN])
    body = validate_body([F("reason", "string")])
    site = get_site(site_id)
    if site["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_SITE_ENROLLMENT_STATE_INVALID")
    del body
    services.suspend_site(site, db.state_programs[site["state_program_id"]])
    return response.obj(public(site))


@bp.post("/collection-sites/<site_id>/reinstate")
def reinstate(site_id):
    auth([ADMIN])
    site = get_site(site_id)
    if site["enrollment_status"] != "SUSPENDED":
        raise ApiError("ERR_SITE_ENROLLMENT_STATE_INVALID")
    if services.quarantine_active(site):
        raise ApiError("ERR_SITE_QUARANTINED")
    site["enrollment_status"] = "ENROLLED"
    site["contamination_strike_count"] = 0
    touch(site)
    services.refresh_program_and_touch(db.state_programs[site["state_program_id"]])
    return response.obj(public(site))


# --------------------------------------------------------------------------
# Volume reports
# --------------------------------------------------------------------------
@bp.post("/collection-sites/<site_id>/volume-reports")
def create_report(site_id):
    auth([SITE_OPERATOR])
    body = validate_body([
        F("period_month", "string", pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
        F("units_mattress", "int", minimum=0),
        F("units_foundation", "int", minimum=0),
    ])
    site = get_site(site_id)
    own(site["id"])

    if site["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_SITE_NOT_ENROLLED")

    for existing in db.volume_reports.values():
        if (existing["collection_site_id"] == site["id"]
                and existing["period_month"] == body["period_month"]):
            raise ApiError("ERR_DUPLICATE_VOLUME_PERIOD")

    rec = base_record()
    rec.update({
        "collection_site_id": site["id"],
        "period_month": body["period_month"],
        "units_mattress": body["units_mattress"],
        "units_foundation": body["units_foundation"],
        "credited_units": 0,
        "credit_cents": 0,
        "status": "SUBMITTED",
        "accepted_at": None,
    })
    db.volume_reports[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/collection-sites/<site_id>/volume-reports")
def list_reports(site_id):
    auth([ADMIN, AUDITOR, SITE_OPERATOR])
    limit, offset = pagination()
    site = get_site(site_id)
    if g.role == SITE_OPERATOR:
        own(site["id"])
    records = sort_records([r for r in db.volume_reports.values()
                            if r["collection_site_id"] == site["id"]])
    records = apply_filters(records, [
        ("status", "status"),
        ("period_month", "period_month"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/volume-reports/<report_id>/accept")
def accept_report(report_id):
    auth([ADMIN])
    report = get_volume_report(report_id)

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_VOLUME_REPORT_NOT_SUBMITTED")

    site = db.collection_sites[report["collection_site_id"]]
    if site["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_SITE_NOT_ENROLLED")

    program = db.state_programs[site["state_program_id"]]
    credited_units, credit_cents = calc.site_volume_credit(
        program, report["units_mattress"], report["units_foundation"])

    report["credited_units"] = credited_units
    report["credit_cents"] = credit_cents
    report["status"] = "ACCEPTED"
    report["accepted_at"] = clock.stamp()
    touch(report)

    site["units_on_hand"] += credited_units
    site["units_reported_total"] += credited_units
    touch(site)

    services.refresh_program_and_touch(program)
    return response.obj(public(report))
