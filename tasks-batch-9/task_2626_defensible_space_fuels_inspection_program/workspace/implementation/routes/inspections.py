"""Inspection scheduling, noticing, access denials, field findings and close-out."""

import math
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import domain
from auth import auth, own
from db import db, insert, sort_created
from errors import fail
from response import created, jsonable, ok, ok_list, touch
from validate import (
    body, check_window, get_bool, get_decimal, get_dt, get_enum, get_str, lookup, page,
    pagination, resolve_fks,
)

bp = Blueprint("inspections", __name__, url_prefix="/fire-district")

INSPECTION_TYPES = ("INITIAL", "REINSPECTION", "COMPLAINT")
ACCESS_ARRANGEMENTS = ("EXTERIOR_ONLY", "OWNER_PRESENT", "GATE_CODE")
NOTICE_METHODS = ("IN_PERSON", "CERTIFIED_MAIL", "EMAIL")
ITEM_CODES = ("EAVE_VENTS", "ROOF_ASSEMBLY", "DECK_UNDERSIDE", "WINDOW_GLAZING",
              "SIDING", "GUTTER_DEBRIS")
FINDING_STATUSES = ("COMPLIANT", "DEFICIENT", "NOT_APPLICABLE")


def _inspection(inspection_id):
    return lookup("inspections", inspection_id, "ERR_INSPECTION_NOT_FOUND")


def _staffing_gates(parcel, inspector, start, end, exclude_id=None):
    """Rungs 13, 14 and 20, in ladder order."""
    if parcel["hazard_zone"] == "VERY_HIGH" and inspector["certification_level"] != "WUI_SPECIALIST":
        fail(
            "ERR_INSPECTOR_NOT_CERTIFIED",
            "A VERY_HIGH parcel requires a WUI_SPECIALIST inspector.",
        )
    if inspector["status"] != "ACTIVE":
        fail("ERR_INSPECTOR_SUSPENDED", "The assigned inspector is not ACTIVE.")
    for other in sort_created(list(db.inspections.values())):
        if other["id"] == exclude_id:
            continue
        if other["inspector_id"] != inspector["id"]:
            continue
        if other["status"] not in domain.LIVE_INSPECTION_STATUSES:
            continue
        # Half-open windows: [start, end) — exact adjacency does not conflict.
        if start < other["scheduled_end_utc"] and other["scheduled_start_utc"] < end:
            fail(
                "ERR_INSPECTOR_WINDOW_CONFLICT",
                "The inspector already holds an intersecting window.",
            )


@bp.post("/inspections")
def schedule_inspection():
    auth("ProgramAdmin")
    b = body()
    resolved = resolve_fks(b, ["cycle_id", "parcel_id", "inspector_id"])
    cycle = resolved.get("cycle_id")
    parcel = resolved.get("parcel_id")
    inspector = resolved.get("inspector_id")
    for key, value in (("cycle_id", cycle), ("parcel_id", parcel),
                       ("inspector_id", inspector)):
        if value is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    inspection_type = get_enum(b, "inspection_type", INSPECTION_TYPES)
    start = get_dt(b, "scheduled_start_utc")
    end = get_dt(b, "scheduled_end_utc")
    access_arrangement = get_enum(b, "access_arrangement", ACCESS_ARRANGEMENTS)
    check_window(start, end)
    domain.require_active_cycle(cycle)
    _staffing_gates(parcel, inspector, start, end)

    inspection = insert(db.inspections, {
        "parcel_id": parcel["id"],
        "cycle_id": cycle["id"],
        "inspector_id": inspector["id"],
        "inspection_type": inspection_type,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "access_arrangement": access_arrangement,
        "status": "SCHEDULED",
        "result": None,
        "notice_method": None,
        "notice_sent_at_utc": None,
        "access_denial_count": 0,
        "measured_veg_points": None,
        "hardening_credit_points": None,
        "max_deficiency_severity": None,
        "completed_at_utc": None,
    })
    domain.recount_inspector_load(inspector)
    return created(jsonable(inspection))


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    auth("ProgramAdmin", "FireMarshal", "Inspector", "PropertyOwner")
    return ok(jsonable(_inspection(inspection_id)))


@bp.get("/inspections")
def list_inspections():
    auth("ProgramAdmin", "FireMarshal", "Inspector")
    limit, offset = pagination()
    records = sort_created(list(db.inspections.values()))
    for field in ("parcel_id", "cycle_id", "inspector_id", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.post("/inspections/<inspection_id>/notice")
def serve_notice(inspection_id):
    auth("ProgramAdmin")
    inspection = _inspection(inspection_id)
    b = body()
    notice_method = get_enum(b, "notice_method", NOTICE_METHODS)
    if inspection["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED inspection can be noticed.")
    cycle = domain.governing_cycle(inspection)
    domain.require_active_cycle(cycle)
    whole_days = math.floor(
        (inspection["scheduled_start_utc"] - db.clock).total_seconds() / 86400.0
    )
    if whole_days < cycle["notice_lead_days"]:
        fail(
            "ERR_NOTICE_LEAD_TIME_VIOLATION",
            "The notice must precede the visit by %s whole days."
            % cycle["notice_lead_days"],
        )
    inspection["notice_method"] = notice_method
    inspection["notice_sent_at_utc"] = db.clock
    inspection["status"] = "NOTICED"
    touch(inspection)
    return ok(jsonable(inspection))


@bp.post("/inspections/<inspection_id>/access-denial")
def access_denial(inspection_id):
    auth("Inspector")
    inspection = _inspection(inspection_id)
    own(g.user_id == inspection["inspector_id"])
    b = body()
    get_str(b, "reason_code", allow_empty=False)
    if (
        inspection["access_denial_count"] >= calc.MAX_ACCESS_DENIALS
        or inspection["status"] == "ABANDONED"
    ):
        fail(
            "ERR_ACCESS_DENIAL_LIMIT_REACHED",
            "This inspection has exhausted its access attempts.",
        )
    if inspection["status"] != "NOTICED":
        fail("ERR_INVALID_STATE", "Only a NOTICED inspection can record a denial.")

    inspection["access_denial_count"] += 1
    if inspection["access_denial_count"] < calc.MAX_ACCESS_DENIALS:
        inspection["status"] = "ACCESS_DENIED"
        touch(inspection)
    else:
        # Second denial: refusing the district twice is itself a violation.
        inspection["status"] = "ABANDONED"
        touch(inspection)
        parcel = db.parcels.get(inspection["parcel_id"])
        domain.issue_notice(parcel, inspection, "CRITICAL", "CERTIFIED_MAIL", supersede=True)
        parcel["compliance_status"] = "NON_COMPLIANT"
        touch(parcel)
        domain.recount_inspector_load(db.inspectors.get(inspection["inspector_id"]))
        domain.cascade_parcel_posture(parcel)
    return ok(jsonable(inspection))


@bp.post("/inspections/<inspection_id>/reschedule")
def reschedule_inspection(inspection_id):
    auth("ProgramAdmin")
    inspection = _inspection(inspection_id)
    b = body()
    resolved = resolve_fks(b, ["inspector_id"])
    start = get_dt(b, "scheduled_start_utc")
    end = get_dt(b, "scheduled_end_utc")
    check_window(start, end)
    if inspection["status"] != "ACCESS_DENIED":
        fail("ERR_INVALID_STATE", "Only an ACCESS_DENIED inspection can be rebooked.")
    previous = db.inspectors.get(inspection["inspector_id"])
    inspector = resolved.get("inspector_id") or previous
    parcel = db.parcels.get(inspection["parcel_id"])
    _staffing_gates(parcel, inspector, start, end, exclude_id=inspection["id"])

    inspection["scheduled_start_utc"] = start
    inspection["scheduled_end_utc"] = end
    inspection["inspector_id"] = inspector["id"]
    inspection["notice_method"] = None
    inspection["notice_sent_at_utc"] = None
    inspection["status"] = "SCHEDULED"
    touch(inspection)
    domain.recount_inspector_load(previous)
    domain.recount_inspector_load(inspector)
    return ok(jsonable(inspection))


@bp.post("/inspections/<inspection_id>/cancel")
def cancel_inspection(inspection_id):
    auth("ProgramAdmin")
    inspection = _inspection(inspection_id)
    b = body()
    get_str(b, "reason")
    if inspection["status"] not in ("SCHEDULED", "NOTICED"):
        fail("ERR_INVALID_STATE", "Only a SCHEDULED or NOTICED inspection can be cancelled.")
    inspection["status"] = "CANCELLED"
    touch(inspection)
    domain.recount_inspector_load(db.inspectors.get(inspection["inspector_id"]))
    return ok(jsonable(inspection))


@bp.post("/inspections/<inspection_id>/zone-evaluations")
def create_zone_evaluation(inspection_id):
    auth("Inspector")
    inspection = _inspection(inspection_id)
    own(g.user_id == inspection["inspector_id"])
    b = body()
    zone = get_enum(b, "zone", calc.ZONES)
    measured = get_decimal(b, "measured_clearance_ft", minimum=0)
    ladder = get_bool(b, "ladder_fuel_present", required=False, default=False)
    for existing in domain.inspection_zone_evaluations(inspection["id"]):
        if existing["zone"] == zone:
            fail("ERR_ZONE_ALREADY_EVALUATED", "Zone %s already carries an evaluation." % zone)
    domain.require_active_cycle(domain.governing_cycle(inspection))

    parcel = db.parcels.get(inspection["parcel_id"])
    graded = calc.grade_zone(parcel, zone, measured, ladder)
    fields = {
        "inspection_id": inspection["id"],
        "zone": zone,
        "measured_clearance_ft": measured,
        "ladder_fuel_present": ladder,
    }
    fields.update(graded)
    evaluation = insert(db.zone_evaluations, fields, audit=False)
    return created(jsonable(evaluation))


@bp.post("/inspections/<inspection_id>/hardening-findings")
def create_hardening_finding(inspection_id):
    auth("Inspector")
    inspection = _inspection(inspection_id)
    own(g.user_id == inspection["inspector_id"])
    b = body()
    item_code = get_enum(b, "item_code", ITEM_CODES)
    status = get_enum(b, "status", FINDING_STATUSES)
    for existing in domain.inspection_hardening_findings(inspection["id"]):
        if existing["item_code"] == item_code:
            fail("ERR_INVALID_STATE", "Item %s already carries a finding." % item_code)
    domain.require_active_cycle(domain.governing_cycle(inspection))

    finding = insert(db.hardening_findings, {
        "inspection_id": inspection["id"],
        "item_code": item_code,
        "status": status,
        "credit_points": (
            calc.HARDENING_CREDIT_PER_ITEM if status == "COMPLIANT" else Decimal("0.00")
        ),
    }, audit=False)
    return created(jsonable(finding))


@bp.post("/inspections/<inspection_id>/complete")
def complete_inspection(inspection_id):
    auth("Inspector")
    inspection = _inspection(inspection_id)
    own(g.user_id == inspection["inspector_id"])
    b = body()
    result = get_enum(b, "result", ("PASS", "FAIL"))
    notice_method = get_enum(b, "violation_notice_method", NOTICE_METHODS, required=False)
    if inspection["status"] != "NOTICED":
        fail("ERR_INVALID_STATE", "Only a NOTICED inspection can be completed.")
    domain.require_active_cycle(domain.governing_cycle(inspection))

    evaluations = domain.inspection_zone_evaluations(inspection["id"])
    covered = [e["zone"] for e in evaluations]
    if len(evaluations) != len(calc.ZONES) or set(covered) != set(calc.ZONES):
        fail(
            "ERR_ZONE_COVERAGE_INCOMPLETE",
            "Completion requires exactly one evaluation per defensible-space zone.",
        )
    clean = all(e["deficiency_severity"] == "NONE" for e in evaluations)
    if (result == "PASS") != clean:
        fail("ERR_ZONE_COVERAGE_INCOMPLETE", "The submitted result disagrees with the findings.")

    findings = domain.inspection_hardening_findings(inspection["id"])
    veg_points, credit, worst = calc.rollup(evaluations, findings)
    inspection["measured_veg_points"] = veg_points
    inspection["hardening_credit_points"] = credit
    inspection["max_deficiency_severity"] = worst
    inspection["completed_at_utc"] = db.clock
    inspection["result"] = result
    inspection["status"] = "COMPLETED"
    touch(inspection)

    parcel = db.parcels.get(inspection["parcel_id"])
    parcel["_verified_veg_points"] = veg_points
    parcel["_verified_hardening_credit"] = credit
    domain.rescore_parcel(parcel, veg_points, credit, basis="POST_INSPECTION_VERIFIED")
    domain.recount_inspector_load(db.inspectors.get(inspection["inspector_id"]))

    if result == "PASS":
        parcel["last_passed_inspection_at_utc"] = inspection["completed_at_utc"]
        if not parcel["exemption_flag"]:
            parcel["compliance_status"] = "COMPLIANT"
        if inspection["inspection_type"] == "REINSPECTION":
            for notice in domain.parcel_notices(parcel["id"]):
                if notice["status"] in ("ISSUED", "EXTENDED", "OVERDUE"):
                    notice["status"] = "CLEARED"
                    notice["cleared_at_utc"] = db.clock
                    touch(notice)
            domain.recount_open_violations(parcel)
        touch(parcel)
        domain.cascade_parcel_posture(parcel)
    else:
        parcel["compliance_status"] = "NON_COMPLIANT"
        touch(parcel)
        domain.issue_notice(
            parcel, inspection, worst, notice_method or "CERTIFIED_MAIL", supersede=False
        )
        domain.revoke_certificates(parcel)
        domain.cascade_parcel_posture(parcel)
    return ok(jsonable(inspection))
