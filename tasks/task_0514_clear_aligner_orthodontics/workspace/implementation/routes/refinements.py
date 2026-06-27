"""RefinementRequest endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.calculations import INCLUDED_REFINEMENTS, REFINEMENT_FEE_CENTS
from services.case_service import first_run_steps
from services.listing import paginate
from services.store import (get_refinement, get_case, fk_case, fk_checkin)
from validation import get_body, require_str, require_int, parse_pagination

bp = Blueprint("refinements", __name__)


@bp.route("/refinements", methods=["POST"])
def create_refinement():
    _, role = get_auth()
    require_roles(role, {"Patient"})
    body = get_body()
    case_id = require_str(body, "case_id")
    triggering_checkin_id = require_str(body, "triggering_checkin_id")
    additional_step_count = require_int(body, "additional_step_count")
    if additional_step_count < 1:
        raise err("ERR_INVALID_REQUEST", "additional_step_count must be >= 1.")
    # FK existence
    fk_case(case_id)
    fk_checkin(triggering_checkin_id)

    rec = base_record(common_fields=True)
    rec.update({
        "case_id": case_id,
        "triggering_checkin_id": triggering_checkin_id,
        "additional_step_count": additional_step_count,
        "status": "REQUESTED",
        "is_billable": False,
    })
    db.refinements[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/refinements/<rid>", methods=["GET"])
def fetch_refinement(rid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin"})
    rec = get_refinement(rid)
    return object_response(serialize(rec), status=200)


@bp.route("/refinements", methods=["GET"])
def list_refinements():
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    triggering_checkin_id = request.args.get("triggering_checkin_id")
    status = request.args.get("status")
    records = list(db.refinements.values())
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if triggering_checkin_id is not None:
        records = [r for r in records
                   if r["triggering_checkin_id"] == triggering_checkin_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/refinements/<rid>/grant", methods=["POST"])
def grant_refinement(rid):
    _, role = get_auth()
    require_roles(role, {"Clinician"})
    refinement = get_refinement(rid)
    case = get_case(refinement["case_id"])
    # state preconditions
    if case["status"] != "ACTIVE" or refinement["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE",
                  "Case must be ACTIVE and refinement REQUESTED to grant.")
    # business: triggering check-in must belong to this case and be OFF_TRACK
    checkin = db.checkins.get(refinement["triggering_checkin_id"])
    if (checkin is None or checkin["case_id"] != case["id"]
            or checkin["tracking_assessment"] != "OFF_TRACK"):
        raise err("ERR_REFINEMENT_NOT_JUSTIFIED",
                  "Triggering check-in must belong to this case and be OFF_TRACK.")

    # refinement_fee: read refinement_count BEFORE incrementing
    pre_count = case["refinement_count"]
    if pre_count >= INCLUDED_REFINEMENTS:
        refinement["is_billable"] = True
        case["total_contracted_cents"] += REFINEMENT_FEE_CENTS
    else:
        refinement["is_billable"] = False

    refinement["status"] = "GRANTED"
    touch(refinement)
    case["refinement_count"] += 1
    case["status"] = "REFINEMENT"

    # generate additional_step_count new PLANNED steps superseding originals.
    # Each new refinement step replaces the matching original first-run step by
    # step_index order; new steps continue the case's step_index sequence.
    originals = sorted(first_run_steps(case["id"]), key=lambda s: s["step_index"])
    max_index = max((s["step_index"] for s in db.aligner_steps.values()
                     if s["case_id"] == case["id"]), default=0)
    for i in range(refinement["additional_step_count"]):
        supersedes_id = originals[i]["id"] if i < len(originals) else None
        max_index += 1
        step = base_record(common_fields=True)
        step.update({
            "case_id": case["id"],
            "step_index": max_index,
            "status": "PLANNED",
            "supersedes_step_id": supersedes_id,
            "scheduled_ship_at": None,
        })
        db.aligner_steps[step["id"]] = step
        case["planned_step_count"] += 1

    touch(case)
    return object_response(serialize(refinement), status=200)


@bp.route("/refinements/<rid>/deny", methods=["POST"])
def deny_refinement(rid):
    _, role = get_auth()
    require_roles(role, {"Clinician"})
    refinement = get_refinement(rid)
    if refinement["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Refinement must be REQUESTED to deny.")
    refinement["status"] = "DENIED"
    touch(refinement)
    return object_response(serialize(refinement), status=200)
