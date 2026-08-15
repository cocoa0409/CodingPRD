"""Acreage report endpoints (PRD §3.3)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from clock import now_dt, now_iso
from errors import (
    ApiError, ERR_ACREAGE_DEADLINE_PASSED, ERR_LINE_ACRES_EXCEED_FIELD,
    ERR_SEGREGATION_OF_DUTIES, invalid_request, invalid_state, not_found,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, get_report_or_404, get_field_or_404,
    active_membership,
)
from validation import (
    body, require_int, require_string, require_decimal, require_enum,
    optional_string,
)

bp = Blueprint("acreage_reports", __name__)

INTENDED_USES = ("GRAIN", "SILAGE", "HAY", "GRAZE", "COVER")

# 2026 crop-year acreage reporting deadline (PRD §3.3).
REPORTING_DEADLINE_ISO = "2026-07-15T23:59:59Z"
LATE_WINDOW_DAYS = 30


def _deadline():
    from clock import _parse_iso
    return _parse_iso(REPORTING_DEADLINE_ISO)


def _recompute_reported_acres(report):
    total = Decimal("0")
    for line in db.acreage_report_lines.values():
        if line["acreage_report_id"] == report["id"]:
            total += Decimal(str(line["planted_acres"]))
            total += Decimal(str(line["prevented_planted_acres"]))
    report["reported_acres"] = float(total)


@bp.post("/fsa/farms/<farm_id>/acreage-reports")
def create_report(farm_id):
    user_id, _ = require_roles(["Producer"])
    farm = get_farm_or_404(farm_id)
    data = body()
    program_year = require_int(data, "program_year")

    report = db.common_fields()
    report.update({
        "farm_id": farm_id,
        "program_year": program_year,
        "report_status": "DRAFT",
        "reported_acres": 0.0,
        "filed_at": None,
        "filed_by_producer_id": None,
    })
    db.acreage_reports[report["id"]] = report
    return success_object(report, 201)


@bp.get("/fsa/acreage-reports/<report_id>")
def get_report(report_id):
    require_roles(ALL_ROLES)
    return success_object(get_report_or_404(report_id))


@bp.get("/fsa/farms/<farm_id>/acreage-reports")
def list_farm_reports(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    program_year = request.args.get("program_year")
    items = [r for r in db.acreage_reports.values() if r["farm_id"] == farm_id]
    if program_year is not None:
        try:
            py = int(program_year)
        except ValueError:
            raise invalid_request("program_year must be an integer")
        items = [r for r in items if r["program_year"] == py]
    items.sort(key=lambda r: r["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/acreage-reports/<report_id>/lines")
def add_line(report_id):
    user_id, _ = require_roles(["Producer"])
    report = get_report_or_404(report_id)
    if report["report_status"] != "DRAFT":
        raise invalid_state("Lines may only be added to a DRAFT report")
    data = body()
    field_id = require_string(data, "field_id")
    field = get_field_or_404(field_id)
    crop_code = require_string(data, "crop_code")
    planted = require_decimal(data, "planted_acres")
    prevented = require_decimal(data, "prevented_planted_acres")
    intended_use = require_enum(data, "intended_use", INTENDED_USES)
    if planted < 0 or prevented < 0:
        raise invalid_request("planted_acres and prevented_planted_acres must be >= 0")

    # Line planted + prevented must not exceed parent field acres
    # (PRD §3.3; validation priority 18).
    if planted + prevented > Decimal(str(field["acres"])):
        raise ApiError(
            ERR_LINE_ACRES_EXCEED_FIELD,
            "Report line planted+prevented acres exceed parent field acres",
            422,
        )

    line = db.common_fields()
    line.update({
        "acreage_report_id": report_id,
        "field_id": field_id,
        "crop_code": crop_code,
        "planted_acres": float(planted),
        "prevented_planted_acres": float(prevented),
        "intended_use": intended_use,
    })
    db.acreage_report_lines[line["id"]] = line
    _recompute_reported_acres(report)
    db.touch(report)
    return success_object(line, 201)


@bp.get("/fsa/acreage-reports/<report_id>/lines")
def list_lines(report_id):
    require_roles(ALL_ROLES)
    get_report_or_404(report_id)
    items = [
        l for l in db.acreage_report_lines.values()
        if l["acreage_report_id"] == report_id
    ]
    items.sort(key=lambda l: l["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/acreage-reports/<report_id>/file")
def file_report(report_id):
    user_id, _ = require_roles(["Producer"])
    report = get_report_or_404(report_id)
    if report["report_status"] != "DRAFT":
        raise invalid_state("Only a DRAFT report may be filed")

    # Producer must hold an ACTIVE membership on the report's farm.
    if active_membership(report["farm_id"], user_id) is None:
        raise invalid_request("Producer does not hold an ACTIVE membership on this farm")

    # Every line's field must belong to the report's farm (via its tract).
    lines = [l for l in db.acreage_report_lines.values()
             if l["acreage_report_id"] == report_id]
    for line in lines:
        field = db.fields.get(line["field_id"])
        if field is None:
            raise not_found(f"Field {line['field_id']} not found")
        tract = db.tracts.get(field["tract_id"])
        if tract is None or tract["farm_id"] != report["farm_id"]:
            raise invalid_request(
                "Every line's field must belong to the report's farm")

    if Decimal(str(report["reported_acres"])) <= 0:
        raise invalid_request("reported_acres must be greater than zero to file")

    # Deadline gate (priority 6, temporal).
    clock = now_dt()
    deadline = _deadline()
    if clock <= deadline:
        new_status = "FILED"
    elif clock <= deadline + timedelta(days=LATE_WINDOW_DAYS):
        new_status = "LATE_FILED"
    else:
        raise ApiError(
            ERR_ACREAGE_DEADLINE_PASSED,
            "File attempted after deadline + 30-day late window",
            422,
        )

    report["report_status"] = new_status
    report["filed_at"] = now_iso()
    report["filed_by_producer_id"] = user_id
    db.touch(report)
    return success_object(report)


@bp.post("/fsa/acreage-reports/<report_id>/certify")
def certify_report(report_id):
    user_id, _ = require_roles(["CountySpecialist"])
    report = get_report_or_404(report_id)
    if report["report_status"] not in ("FILED", "LATE_FILED"):
        raise invalid_state("Report is not FILED or LATE_FILED")
    # Segregation of duties: the certifying specialist must not be the filer.
    # Specialist identity is opaque; the filer is a Producer id, which a
    # specialist id never equals unless the same identifier string was used.
    if report.get("filed_by_producer_id") is not None \
            and report["filed_by_producer_id"] == user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Specialist did not file the report requirement violated",
            422,
        )
    report["report_status"] = "CERTIFIED"
    db.touch(report)
    return success_object(report)


@bp.post("/fsa/acreage-reports/<report_id>/reject")
def reject_report(report_id):
    require_roles(["CountySpecialist"])
    report = get_report_or_404(report_id)
    if report["report_status"] not in ("FILED", "LATE_FILED"):
        raise invalid_state("Report is not FILED or LATE_FILED")
    data = body()
    require_string(data, "reason")
    report["report_status"] = "REJECTED"
    db.touch(report)
    return success_object(report)


@bp.post("/fsa/acreage-reports/<report_id>/reopen")
def reopen_report(report_id):
    require_roles(["CountySpecialist"])
    report = get_report_or_404(report_id)
    if report["report_status"] != "CERTIFIED":
        raise invalid_state("Only a CERTIFIED report may be reopened")
    # No enrollment for this farm+year at CERTIFIED or beyond.
    beyond = ("CERTIFIED", "PAYMENT_COMPUTED", "PAYMENT_ISSUED", "ON_APPEAL", "REMANDED")
    for e in db.enrollments.values():
        if (e["farm_id"] == report["farm_id"]
                and e["program_year"] == report["program_year"]
                and e["enrollment_status"] in beyond):
            raise invalid_state(
                "An enrollment for this farm and year is CERTIFIED or beyond")
    report["report_status"] = "FILED"
    db.touch(report)
    return success_object(report)
