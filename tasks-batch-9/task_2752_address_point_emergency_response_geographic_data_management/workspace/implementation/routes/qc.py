"""QC validation reports, defect waivers and certification."""

from flask import Blueprint

import calc
import cascade
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import base_record, db, sorted_rows, touch

bp = Blueprint("qc", __name__)

SCOPES = ["FULL", "JURISDICTION", "ROAD"]
REPORT_STATUSES = ["GENERATED", "CERTIFIED", "REJECTED", "DECERTIFIED"]
SEVERITIES = ["BLOCKING", "WARNING", "INFO"]
CATEGORIES = ["ADDRESS", "ROAD", "BOUNDARY"]
DEFECT_STATUSES = ["OPEN", "WAIVED"]
DEFECT_CODES = sorted(calc.DEFECT_SEVERITY.keys())


@bp.post("/qc-validation-reports")
def create_report():
    user_id, _role = v.auth(["GisAnalyst"])
    data = v.body()
    jurisdiction = v.maybe_find("jurisdiction", v.raw_ref(data, "jurisdiction_id"))
    road = v.maybe_find("road", v.raw_ref(data, "road_centerline_id"))
    scope = v.req_enum(data, "scope", SCOPES)
    jurisdiction_id = v.opt_id(data, "jurisdiction_id")
    road_centerline_id = v.opt_id(data, "road_centerline_id")

    if scope == "JURISDICTION":
        if jurisdiction_id is None:
            v.bad("jurisdiction_id", "is required for a JURISDICTION-scoped report")
        if road_centerline_id is not None:
            v.bad("road_centerline_id", "is forbidden on a JURISDICTION-scoped report")
    elif scope == "ROAD":
        if road_centerline_id is None:
            v.bad("road_centerline_id", "is required for a ROAD-scoped report")
        if jurisdiction_id is not None:
            v.bad("jurisdiction_id", "is forbidden on a ROAD-scoped report")
    else:
        if jurisdiction_id is not None:
            v.bad("jurisdiction_id", "is forbidden on a FULL-scoped report")
        if road_centerline_id is not None:
            v.bad("road_centerline_id", "is forbidden on a FULL-scoped report")

    row = base_record()
    row.update({
        "scope": scope,
        "jurisdiction_id": jurisdiction["id"] if jurisdiction is not None else None,
        "road_centerline_id": road["id"] if road is not None else None,
        "status": "GENERATED",
        "generated_by_user_id": user_id,
        "certified_by_user_id": None,
        "certified_at": None,
        "rejection_reason": None,
        "decertified_reason": None,
    })
    db.reports[row["id"]] = row

    for candidate in calc.qc_defect_scan(scope, row["jurisdiction_id"],
                                         row["road_centerline_id"]):
        defect = base_record()
        defect.update({
            "report_id": row["id"],
            "defect_code": candidate["defect_code"],
            "severity": candidate["severity"],
            "defect_category": candidate["defect_category"],
            "entity_type": candidate["entity_type"],
            "entity_ref_id": candidate["entity_ref_id"],
            "detail": candidate["detail"],
            "status": "OPEN",
            "waived_by_user_id": None,
            "waiver_reason": None,
            "waived_at": None,
        })
        db.defects[defect["id"]] = defect
    return created(ser.report(row))


@bp.get("/qc-validation-reports/<identifier>")
def get_report(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("report", identifier)
    return ok(ser.report(row))


@bp.get("/qc-validation-reports")
def list_reports():
    v.auth(v.ALL_ROLES)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    road_id = v.q_str("road_centerline_id")
    if road_id is not None:
        v.find("road", road_id)
    scope = v.q_enum("scope", SCOPES)
    status = v.q_enum("status", REPORT_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.reports.values()))
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if road_id is not None:
        rows = [r for r in rows if r["road_centerline_id"] == road_id]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.report(r) for r in page], limit, offset, total)


@bp.get("/qc-validation-reports/<identifier>/defects")
def list_report_defects(identifier):
    v.auth(v.ALL_ROLES)
    report = v.find("report", identifier)
    severity = v.q_enum("severity", SEVERITIES)
    category = v.q_enum("defect_category", CATEGORIES)
    defect_code = v.q_enum("defect_code", DEFECT_CODES)
    status = v.q_enum("status", DEFECT_STATUSES)
    limit, offset = v.pagination()
    rows = calc.report_defects(report["id"])
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if category is not None:
        rows = [r for r in rows if r["defect_category"] == category]
    if defect_code is not None:
        rows = [r for r in rows if r["defect_code"] == defect_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.defect(r) for r in page], limit, offset, total)


@bp.get("/qc-defects/<identifier>")
def get_defect(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("defect", identifier)
    return ok(ser.defect(row))


@bp.post("/qc-defects/<identifier>/waive")
def waive_defect(identifier):
    user_id, _role = v.auth(["QcCertifier"])
    defect = v.find("defect", identifier)
    data = v.body()
    reason = v.req_str(data, "waiver_reason", 1)
    if defect["status"] != "OPEN":
        raise ApiError("ERR_DEFECT_INVALID_STATE",
                       "Only an OPEN defect may be waived; this one is %s." % defect["status"])
    report = db.reports.get(defect["report_id"])
    if report is None or report["status"] != "GENERATED":
        raise ApiError("ERR_DEFECT_INVALID_STATE",
                       "Defects may only be waived while the owning report is GENERATED.")

    defect["status"] = "WAIVED"
    defect["waived_by_user_id"] = user_id
    defect["waiver_reason"] = reason
    defect["waived_at"] = db.now()
    touch(defect)
    touch(report)
    return ok(ser.defect(defect))


@bp.post("/qc-validation-reports/<identifier>/certify")
def certify_report(identifier):
    user_id, _role = v.auth(["QcCertifier"])
    report = v.find("report", identifier)
    if report["status"] != "GENERATED":
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "Only a GENERATED report may be certified; this one is %s."
                       % report["status"])
    counts = calc.report_counts(report["id"])
    if counts["open_blocking_defect_count"] > 0:
        raise ApiError("ERR_QC_BLOCKING_DEFECTS_OPEN",
                       "%d BLOCKING defects are still OPEN."
                       % counts["open_blocking_defect_count"])
    if user_id == report["generated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator who generated a report may not certify it.")

    report["status"] = "CERTIFIED"
    report["certified_by_user_id"] = user_id
    report["certified_at"] = db.now()
    touch(report)

    points = calc.points_by_house_number(
        calc.report_scope_points(report["scope"], report["jurisdiction_id"],
                                 report["road_centerline_id"]))
    for point in points:
        point["certified_confidence_score"] = calc.confidence_score(point, "certified")
        point["confidence_basis"] = "CERTIFIED"
        touch(point)
        cascade.pin_staleness_for_point(point)
    return ok(ser.report(report))


@bp.post("/qc-validation-reports/<identifier>/reject")
def reject_report(identifier):
    v.auth(["QcCertifier"])
    report = v.find("report", identifier)
    data = v.body()
    reason = v.req_str(data, "rejection_reason", 1)
    if report["status"] != "GENERATED":
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "Only a GENERATED report may be rejected; this one is %s."
                       % report["status"])
    report["status"] = "REJECTED"
    report["rejection_reason"] = reason
    touch(report)
    return ok(ser.report(report))
