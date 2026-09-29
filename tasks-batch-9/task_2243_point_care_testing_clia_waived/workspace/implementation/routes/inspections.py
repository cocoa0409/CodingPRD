"""Surveys, deficiency findings and the weight ledger (PRD 3.8)."""

from flask import Blueprint

import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("inspections", __name__)

READ_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor")

CATEGORIES = ("PERSONNEL_COMPETENCY", "QUALITY_CONTROL", "PROFICIENCY_TESTING",
              "REAGENT_STORAGE", "RESULT_REPORTING", "CERTIFICATE_SCOPE")
SEVERITIES = ("CONDITION_LEVEL", "STANDARD_LEVEL", "ADVISORY")
INSPECTION_TYPES = ("BIENNIAL_SURVEY", "COMPLAINT_SURVEY", "INTERNAL_READINESS")

VOIDABLE = ("DRAFT", "OPEN", "CORRECTION_SUBMITTED", "CORRECTION_REJECTED")


def _findings_of_inspection(inspection_id):
    items = [f for f in db.data["findings"].values()
             if f["inspection_id"] == inspection_id]
    items.sort(key=lambda f: (f["created_at"], f["category"], f["_seq"]))
    return items


# --------------------------------------------------------------------------
# Surveys
# --------------------------------------------------------------------------

@route(bp, "/inspections", ["POST"], ["Surveyor"])
def open_inspection(user_id, role):
    payload = valid.body()
    site = valid.resolve_body("sites", payload, "site_id")
    inspection_type = valid.req_enum(payload, "inspection_type", INSPECTION_TYPES)
    scheduled_date = valid.req_date(payload, "scheduled_date")

    row = db.insert("inspections", {
        "site_id": site["id"],
        "inspection_type": inspection_type,
        "scheduled_date": scheduled_date.isoformat(),
        "status": "IN_PROGRESS",
        "issued_on": None,
        "issued_by_user_id": None,
        "issued_weight_total": 0,
        "readiness_score_at_issue": None,
        "rescind_reason": None,
    })
    return response.object_response(serializers.dump("inspections", row), 201)


@route(bp, "/inspections/<inspection_id>", ["GET"], READ_ROLES)
def read_inspection(user_id, role, inspection_id):
    row = valid.resolve("inspections", inspection_id)
    return response.object_response(serializers.dump("inspections", row))


@route(bp, "/inspections", ["GET"], READ_ROLES)
def list_inspections(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    status = valid.arg("status")
    items = [i for i in db.rows("inspections")
             if (site_id is None or i["site_id"] == site_id)
             and (status is None or i["status"] == status)]
    return response.list_response(
        serializers.dump_many("inspections", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/inspections/<inspection_id>/issue", ["POST"], ["Surveyor"])
def issue_statement(user_id, role, inspection_id):
    inspection = valid.resolve("inspections", inspection_id)
    payload = valid.body()
    issued_on = valid.req_date(payload, "issued_on")
    # Rank 48.
    if inspection["status"] != "IN_PROGRESS":
        raise errors.ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409)
    drafts = [f for f in _findings_of_inspection(inspection["id"])
              if f["status"] == "DRAFT"]
    # Rank 50 — an empty statement cannot be issued.
    if not drafts:
        raise errors.invalid_state(
            "The survey holds no DRAFT finding to issue.")

    total = calc.dec(0)
    for finding in drafts:
        snap = db.snapshot(finding)
        multiplier = calc.repeat_multiplier(finding)
        weight = calc.deficiency_weight(finding["severity"], multiplier)
        finding["repeat_multiplier"] = float(multiplier)
        finding["weight"] = float(weight)
        finding["status"] = "OPEN"
        finding["issued_by_user_id"] = user_id
        db.touch_if_changed(finding, snap)
        total += weight

    snap = db.snapshot(inspection)
    inspection["status"] = "DEFICIENCIES_ISSUED"
    inspection["issued_on"] = issued_on.isoformat()
    inspection["issued_by_user_id"] = user_id
    inspection["issued_weight_total"] = float(calc.round2(total))
    db.touch_if_changed(inspection, snap)

    site = db.get("sites", inspection["site_id"])
    derive.recompute_site(site)
    if site is not None:
        # Snapshot the freshly computed score.
        inspection["readiness_score_at_issue"] = site["inspection_readiness_score"]
    return response.object_response(serializers.dump("inspections", inspection))


@route(bp, "/inspections/<inspection_id>/rescind", ["POST"],
       ["Surveyor", "ProgramAdmin"])
def rescind(user_id, role, inspection_id):
    inspection = valid.resolve("inspections", inspection_id)
    payload = valid.body()
    reason = valid.req_str(payload, "reason")
    # Rank 48.
    if inspection["status"] not in ("IN_PROGRESS", "DEFICIENCIES_ISSUED"):
        raise errors.ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409)

    for finding in _findings_of_inspection(inspection["id"]):
        if finding["status"] not in VOIDABLE:
            continue
        snap = db.snapshot(finding)
        finding["status"] = "VOIDED"
        db.touch_if_changed(finding, snap)

    snap = db.snapshot(inspection)
    inspection["status"] = "RESCINDED"
    inspection["rescind_reason"] = reason
    # issued_weight_total is a historical record and is left exactly as it was.
    db.touch_if_changed(inspection, snap)

    derive.recompute_site_by_id(inspection["site_id"])
    return response.object_response(serializers.dump("inspections", inspection))


# --------------------------------------------------------------------------
# Deficiency findings
# --------------------------------------------------------------------------

@route(bp, "/deficiencies", ["POST"], ["Surveyor"])
def add_finding(user_id, role):
    payload = valid.body()
    # Rank 14 — inspection first, then the optional parent finding.
    inspection = valid.resolve_body("inspections", payload, "inspection_id")
    parent = valid.resolve_body_optional("findings", payload, "parent_finding_id")
    # Rank 20.
    category = valid.req_enum(payload, "category", CATEGORIES)
    severity = valid.req_enum(payload, "severity", SEVERITIES)
    description = valid.req_str(payload, "description")
    due_date = valid.req_date(payload, "correction_due_date")
    # Rank 48.
    if inspection["status"] != "IN_PROGRESS":
        raise errors.ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409)
    # Rank 50 — the repeated finding must itself be CLOSED.
    if parent is not None and parent["status"] != "CLOSED":
        raise errors.invalid_state("The parent finding is not CLOSED.")
    # Rank 60.
    if parent is not None and parent["site_id"] != inspection["site_id"]:
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)

    row = db.insert("findings", {
        "site_id": inspection["site_id"],
        "inspection_id": inspection["id"],
        "parent_finding_id": parent["id"] if parent is not None else None,
        "category": category,
        "severity": severity,
        "description": description,
        "correction_due_date": due_date.isoformat(),
        "weight": 0,
        "repeat_multiplier": 1.0,
        "status": "DRAFT",
        "issued_by_user_id": None,
        "correction_narrative": None,
        "evidence_ref": None,
        "correction_round": 0,
        "closed_by_user_id": None,
    })
    return response.object_response(serializers.dump("findings", row), 201)


@route(bp, "/deficiencies/<finding_id>", ["GET"], READ_ROLES)
def read_finding(user_id, role, finding_id):
    row = valid.resolve("findings", finding_id)
    return response.object_response(serializers.dump("findings", row))


@route(bp, "/deficiencies", ["GET"], READ_ROLES)
def list_findings(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    inspection_id = valid.arg("inspection_id")
    parent_id = valid.arg("parent_finding_id")
    status = valid.arg("status")
    items = [f for f in db.rows("findings")
             if (site_id is None or f["site_id"] == site_id)
             and (inspection_id is None or f["inspection_id"] == inspection_id)
             and (parent_id is None or f["parent_finding_id"] == parent_id)
             and (status is None or f["status"] == status)]
    return response.list_response(
        serializers.dump_many("findings", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/deficiencies/<finding_id>/correction", ["POST"],
       ["QualityCoordinator", "LabDirector"])
def submit_correction(user_id, role, finding_id):
    finding = valid.resolve("findings", finding_id)
    payload = valid.body()
    narrative = valid.req_str(payload, "correction_narrative")
    evidence = valid.req_str(payload, "evidence_ref")
    # Rank 47.
    if finding["status"] not in ("OPEN", "CORRECTION_REJECTED"):
        raise errors.ApiError("ERR_DEFICIENCY_NOT_CORRECTABLE", 409)
    # Rank 48.
    inspection = db.get("inspections", finding["inspection_id"])
    if inspection is None or inspection["status"] != "DEFICIENCIES_ISSUED":
        raise errors.ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409)

    finding["status"] = "CORRECTION_SUBMITTED"
    finding["correction_narrative"] = narrative
    finding["evidence_ref"] = evidence
    finding["correction_round"] = int(finding["correction_round"] or 0) + 1
    db.touch(finding)
    # The site's open_deficiency_weight is deliberately unchanged: a submitted
    # plan is a promise, and CORRECTION_SUBMITTED still counts as open.
    return response.object_response(serializers.dump("findings", finding))


@route(bp, "/deficiencies/<finding_id>/correction-decision", ["POST"],
       ["Surveyor"])
def decide_correction(user_id, role, finding_id):
    finding = valid.resolve("findings", finding_id)
    payload = valid.body()
    decision = valid.req_enum(payload, "decision", ("ACCEPT", "REJECT"))
    valid.opt_str(payload, "note")
    # Rank 47.
    if finding["status"] != "CORRECTION_SUBMITTED":
        raise errors.ApiError("ERR_DEFICIENCY_NOT_CORRECTABLE", 409)
    # Rank 65 (c).
    if finding["issued_by_user_id"] is not None \
            and user_id == finding["issued_by_user_id"]:
        raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES", 422)

    snap = db.snapshot(finding)
    if decision == "ACCEPT":
        finding["status"] = "CLOSED"
        finding["closed_by_user_id"] = user_id
    else:
        finding["status"] = "CORRECTION_REJECTED"
    db.touch_if_changed(finding, snap)

    if decision == "ACCEPT":
        inspection = db.get("inspections", finding["inspection_id"])
        if inspection is not None and inspection["status"] == "DEFICIENCIES_ISSUED":
            siblings = _findings_of_inspection(inspection["id"])
            if siblings and all(f["status"] in ("CLOSED", "VOIDED")
                                for f in siblings):
                isnap = db.snapshot(inspection)
                inspection["status"] = "CLOSED"
                db.touch_if_changed(inspection, isnap)
        derive.recompute_site_by_id(finding["site_id"])
    return response.object_response(serializers.dump("findings", finding))
