"""Abstraction + OverReadReview routes."""
from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import require_roles, get_json_body, require_fields, require_enum
from response import success_object, success_list, parse_pagination
from serializers import abstraction_view, overread_view
from services.core import (touch, find_chase, find_abstraction,
                           recompute_run_counters, selector_top_up,
                           abstractions_of_sample)

bp = Blueprint("abstractions", __name__)

ABSTRACTOR = ["Abstractor"]
OVERREADER = ["OverReader"]
ALL = ["QualityAdmin", "QualityAnalyst", "Abstractor", "OverReader",
       "ProviderRelations", "Auditor", "QualityDirector"]
OVERREAD_LIST_ROLES = ["QualityAdmin", "QualityAnalyst", "Abstractor",
                       "OverReader", "Auditor", "QualityDirector"]

TERMINAL_ABSTRACTION_STATES = {"CONFIRMED", "OVERREAD_PASSED"}


def _run_for_abstraction(a):
    chase = db.chases.get(a["chase_id"])
    if chase is None:
        return None, None
    sample = db.samples.get(chase["sample_id"])
    if sample is None:
        return None, None
    return db.runs.get(sample["run_id"]), sample


def _recompute_for(a):
    run, _ = _run_for_abstraction(a)
    if run is not None:
        recompute_run_counters(run)


@bp.post("/hedis/abstractions")
def create_abstraction():
    user_id, _ = require_roles(ABSTRACTOR)
    body = get_json_body()
    require_fields(body, ["chase_id", "result"])
    result = require_enum(body, "result", ["HIT", "MISS", "NOT_ABSTRACTABLE"])
    chase = find_chase(body.get("chase_id") if isinstance(body.get("chase_id"), str) else "")
    # cross-entity guard: chase must be RECEIVED
    if chase["status"] != "RECEIVED":
        raise errors.invalid_state("Chase must be RECEIVED to abstract")
    # uniqueness: at most one non-terminal abstraction per chase
    for a in db.abstractions.values():
        if a["chase_id"] == chase["id"] and a["status"] not in TERMINAL_ABSTRACTION_STATES:
            raise errors.ApiError(errors.ERR_DUPLICATE_ABSTRACTION, 409,
                                  "A non-terminal abstraction already exists for this chase")
    rec = {
        "id": new_id(),
        "chase_id": chase["id"],
        "result": result,
        "abstractor_user_id": user_id,
        "requires_overread": False,
        "status": "DRAFT",
        "resubmission_count": 0,
        "submitted_at": None,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.abstractions[rec["id"]] = rec
    return success_object(abstraction_view(rec), 201)


@bp.get("/hedis/abstractions/<abstractionId>")
def get_abstraction(abstractionId):
    require_roles(ALL)
    a = find_abstraction(abstractionId)
    return success_object(abstraction_view(a))


@bp.put("/hedis/abstractions/<abstractionId>")
def edit_abstraction(abstractionId):
    user_id, _ = require_roles(ABSTRACTOR)
    body = get_json_body()
    require_fields(body, ["result"])
    result = require_enum(body, "result", ["HIT", "MISS", "NOT_ABSTRACTABLE"])
    a = find_abstraction(abstractionId)
    if a["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT abstractions may be edited")
    if user_id != a["abstractor_user_id"]:
        raise errors.insufficient("Only the author may edit the abstraction")
    a["result"] = result
    touch(a)
    return success_object(abstraction_view(a))


@bp.post("/hedis/abstractions/<abstractionId>/submit")
def submit_abstraction(abstractionId):
    user_id, _ = require_roles(ABSTRACTOR)
    get_json_body()
    a = find_abstraction(abstractionId)
    if a["status"] not in ("DRAFT", "REMEDIATION"):
        raise errors.invalid_state("Abstraction must be DRAFT or REMEDIATION to submit")
    if user_id != a["abstractor_user_id"]:
        raise errors.insufficient("Only the author may submit the abstraction")

    from_remediation = a["status"] == "REMEDIATION"
    a["status"] = "SUBMITTED"
    if from_remediation:
        a["resubmission_count"] += 1
    a["submitted_at"] = db.clock

    # side effect: first submit moves chase RECEIVED -> ABSTRACTED
    chase = db.chases.get(a["chase_id"])
    if chase is not None and chase["status"] == "RECEIVED":
        chase["status"] = "ABSTRACTED"
        touch(chase)

    # selector top-up + numerator recompute
    _, sample = _run_for_abstraction(a)
    if sample is not None:
        selector_top_up(sample)
    _recompute_for(a)
    touch(a)
    return success_object(abstraction_view(a))


@bp.post("/hedis/abstractions/<abstractionId>/retract")
def retract_abstraction(abstractionId):
    user_id, _ = require_roles(ABSTRACTOR)
    get_json_body()
    a = find_abstraction(abstractionId)
    if a["status"] not in ("SUBMITTED", "REMEDIATION"):
        raise errors.invalid_state("Abstraction must be SUBMITTED or REMEDIATION to retract")
    if user_id != a["abstractor_user_id"]:
        raise errors.insufficient("Only the author may retract the abstraction")

    chase = db.chases.get(a["chase_id"])
    if a["status"] == "SUBMITTED":
        # blocked once an over-read exists for the current round
        if any(o["abstraction_id"] == a["id"]
               and o["resubmission_count"] == a["resubmission_count"]
               for o in db.over_reads.values()):
            raise errors.invalid_state("An over-read exists for the current round")
        # compensation: chase ABSTRACTED -> RECEIVED
        if chase is not None and chase["status"] == "ABSTRACTED":
            chase["status"] = "RECEIVED"
            touch(chase)
        a["status"] = "DRAFT"
        # selector re-runs because an abstraction left SUBMITTED
        _, sample = _run_for_abstraction(a)
        a_status_cache = a["status"]
        if sample is not None:
            selector_top_up(sample)
        _recompute_for(a)
    else:  # REMEDIATION
        a["resubmission_count"] += 1
        a["status"] = "DRAFT"
        # chase stays ABSTRACTED — chart remains in hand during remediation
    touch(a)
    return success_object(abstraction_view(a))


@bp.get("/hedis/abstractions/<id>/over-reads")
def list_abstraction_overreads(id):
    require_roles(OVERREAD_LIST_ROLES)
    find_abstraction(id)
    items = [o for o in db.over_reads.values() if o["abstraction_id"] == id]
    items.sort(key=lambda o: o["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([overread_view(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------- over-reads
@bp.post("/hedis/over-reads")
def create_overread():
    user_id, _ = require_roles(OVERREADER)
    body = get_json_body()
    require_fields(body, ["abstraction_id", "outcome"])
    outcome = require_enum(body, "outcome", ["AGREE", "DISAGREE"])
    final_result = body.get("final_result")
    if outcome == "DISAGREE":
        if final_result is None:
            raise errors.invalid_request("final_result is required when outcome is DISAGREE")
        if final_result not in ("HIT", "MISS"):
            raise errors.invalid_request("final_result must be HIT or MISS")
    elif final_result is not None and final_result not in ("HIT", "MISS"):
        raise errors.invalid_request("final_result must be HIT or MISS")

    a = find_abstraction(body.get("abstraction_id") if isinstance(body.get("abstraction_id"), str) else "")
    # state guard: must be SUBMITTED and flagged
    if a["status"] != "SUBMITTED" or not a["requires_overread"]:
        raise errors.invalid_state("Abstraction must be SUBMITTED and flagged for over-read")
    # SoD (priority 8)
    if user_id == a["abstractor_user_id"]:
        raise errors.ApiError(errors.ERR_SOD_SELF_OVERREAD, 403,
                              "Over-reader must differ from the abstractor")

    rec = {
        "id": new_id(),
        "abstraction_id": a["id"],
        "reviewer_user_id": user_id,
        "outcome": outcome,
        "final_result": final_result if outcome == "DISAGREE" else None,
        "resubmission_count": a["resubmission_count"],
        "created_at": db.clock,
    }
    db.over_reads[rec["id"]] = rec

    run, sample = _run_for_abstraction(a)
    if outcome == "AGREE":
        a["status"] = "OVERREAD_PASSED"
        if sample is not None:
            selector_top_up(sample)
        if run is not None:
            recompute_run_counters(run)
    else:  # DISAGREE
        a["status"] = "REMEDIATION"
        if sample is not None:
            # cascade link 1: remediation_count
            sample["remediation_count"] += 1
            # cascade link 2: hard override at 2
            if sample["remediation_count"] >= 2:
                sample["required_overread_fraction"] = 1.0
            sample["updated_at"] = db.clock
            sample["version"] += 1
            # cascade link 3: selector top-up under the new fraction
            selector_top_up(sample)
        if run is not None:
            recompute_run_counters(run)
    touch(a)
    return success_object(overread_view(rec), 201)
