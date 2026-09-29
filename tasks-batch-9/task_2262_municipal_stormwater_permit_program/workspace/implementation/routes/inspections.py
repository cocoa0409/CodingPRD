"""Inspections: one record for both programmes, and the finalize cascade."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, new_row, touch
from errors import ApiError
from middleware import body, get_bool, get_date, get_enum, get_str, require
from routes.common import find, listing, one, require_active, settle, snapshot
from services import calc, derive, enforce

bp = Blueprint("inspections", __name__)

READERS = mw.OPERATIONAL_ROLES
SITE_OPEN_FIELD_STATES = ("ACTIVE_DISTURBANCE", "STOP_WORK")


@bp.post("/inspections")
def create_inspection():
    require([mw.INSPECTOR])
    payload = body()
    inspection_type = get_enum(payload, "inspection_type", enums.INSPECTION_TYPE)
    period_start = get_date(payload, "period_start")
    period_end = get_date(payload, "period_end")
    if period_end < period_start:
        raise ApiError("ERR_VALIDATION", "period_end must not precede period_start.")
    site_id = get_str(payload, "construction_site_id", required=False, default=None)
    facility_id = get_str(payload, "post_construction_facility_id", required=False, default=None)
    rainfall = get_bool(payload, "rainfall_trigger", required=False, default=False)

    site = find("sites", site_id) if site_id is not None else None
    facility = find("facilities", facility_id) if facility_id is not None else None

    if site is not None and site.get("field_status") == "CLOSED":
        raise ApiError("ERR_SITE_CLOSED")

    subject_term = None
    if site is not None:
        subject_term = derive.term_of_site(site)
    elif facility is not None:
        subject_term = derive.term_of_facility(facility)
    if subject_term is not None:
        require_active(subject_term)

    if inspection_type == "CONSTRUCTION_ESC":
        if site is None or facility is not None:
            raise ApiError("ERR_INSPECTION_SUBJECT_MISMATCH")
        if site["plan_status"] != "APPROVED":
            raise ApiError("ERR_ESC_PLAN_NOT_APPROVED")
        if site["field_status"] not in SITE_OPEN_FIELD_STATES:
            raise ApiError("ERR_SITE_NOT_ACTIVE_DISTURBANCE")
        subject_key = "construction_site_id"
        subject_id = site["id"]
    else:
        if facility is None or site is not None:
            raise ApiError("ERR_INSPECTION_SUBJECT_MISMATCH")
        subject_key = "post_construction_facility_id"
        subject_id = facility["id"]

    for other in DB.inspections.values():
        if other["inspection_type"] != inspection_type:
            continue
        if other.get(subject_key) != subject_id:
            continue
        other_start = calc.date.fromisoformat(other["period_start"])
        other_end = calc.date.fromisoformat(other["period_end"])
        if period_start <= other_end and other_start <= period_end:
            raise ApiError("ERR_INSPECTION_PERIOD_OVERLAP")

    row = new_row(
        {
            "inspection_type": inspection_type,
            "construction_site_id": site["id"] if site is not None else None,
            "post_construction_facility_id": facility["id"] if facility is not None else None,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "rainfall_trigger": rainfall,
            "findings": [],
            "minor_finding_count": 0,
            "major_finding_count": 0,
            "critical_finding_count": 0,
            "deficiency_score": 0,
            "escalation_triggered": False,
            "status": "DRAFT",
            "finalized_at": None,
            "finalized_by_user_id": None,
        }
    )
    DB.inspections[row["id"]] = row
    return one(row, 201)


@bp.get("/inspections")
def list_inspections():
    require(READERS)
    spec = {
        "inspection_type": ("inspection_type", enums.INSPECTION_TYPE),
        "construction_site_id": ("construction_site_id", None),
        "post_construction_facility_id": ("post_construction_facility_id", None),
        "status": ("status", enums.INSPECTION_STATUS),
    }
    return listing(spec, lambda: list(DB.inspections.values()))


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    require(READERS)
    return one(find("inspections", inspection_id))


@bp.post("/inspections/<inspection_id>/findings")
def append_finding(inspection_id):
    require([mw.INSPECTOR])
    payload = body()
    severity = get_enum(payload, "severity", enums.SEVERITY)
    description = get_str(payload, "description")
    inspection = find("inspections", inspection_id)
    if inspection["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_NOT_DRAFT")

    inspection["findings"].append({"severity": severity, "description": description})
    key = {
        "MINOR": "minor_finding_count",
        "MAJOR": "major_finding_count",
        "CRITICAL": "critical_finding_count",
    }[severity]
    inspection[key] = int(inspection.get(key) or 0) + 1
    touch(inspection)
    return one(inspection)


@bp.post("/inspections/<inspection_id>/finalize")
def finalize_inspection(inspection_id):
    user_id, _role = require([mw.INSPECTOR])
    inspection = find("inspections", inspection_id)
    if inspection["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_NOT_DRAFT")

    site = DB.sites.get(inspection.get("construction_site_id"))
    facility = DB.facilities.get(inspection.get("post_construction_facility_id"))
    if inspection["inspection_type"] == "CONSTRUCTION_ESC" and site is not None:
        if site.get("field_status") == "CLOSED":
            raise ApiError("ERR_SITE_CLOSED")
    if not inspection["findings"]:
        raise ApiError("ERR_INSPECTION_NO_FINDINGS")
    if inspection["inspection_type"] == "CONSTRUCTION_ESC":
        if site is None or site["field_status"] not in SITE_OPEN_FIELD_STATES:
            raise ApiError("ERR_SITE_NOT_ACTIVE_DISTURBANCE")
    else:
        if facility is None or facility.get("agreement_status") not in (
            "RECORDED",
            "NOT_REQUIRED",
        ):
            raise ApiError("ERR_AGREEMENT_NOT_RECORDED")

    facility_state = derive.facility_state(facility) if facility is not None else None
    score, escalated = calc.deficiency_score(
        inspection, site=site, facility_state=facility_state, facility=facility
    )
    term = derive.term_of_inspection(inspection)
    before = snapshot(term)

    inspection["deficiency_score"] = score
    inspection["escalation_triggered"] = escalated
    inspection["status"] = "FINALIZED"
    inspection["finalized_at"] = CLOCK.stamp()
    inspection["finalized_by_user_id"] = user_id
    touch(inspection)

    if inspection["inspection_type"] == "CONSTRUCTION_ESC" and escalated and site is not None:
        if site["field_status"] == "ACTIVE_DISTURBANCE":
            site["field_status"] = "STOP_WORK"
            site["stop_work_count"] = int(site.get("stop_work_count") or 0) + 1
        site["stop_work_reason"] = "AUTOMATIC_ESC_DEFICIENCY"
        site["open_deficiency_score"] = score
        touch(site)
        enforce.issue(
            "NOTICE_OF_VIOLATION",
            "construction_site_id",
            site["id"],
            violation_days=0,
            source_inspection_id=inspection["id"],
            user_id=enforce.SYSTEM_USER_ID,
            auto_generated=True,
        )

    settle(term, before, CLOCK.now())
    return one(inspection)
