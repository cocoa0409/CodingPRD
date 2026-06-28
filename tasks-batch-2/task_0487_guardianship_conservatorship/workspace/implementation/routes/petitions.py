"""Petition and CapacityEvaluation routes."""

from flask import Blueprint, request

from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_enum,
    parse_pagination,
    paginate,
)
from services import resolve_path, resolve_ref

bp = Blueprint("petitions", __name__)


# Scope coverage (PRD §3.2): an authority is covered only when recommended_scope
# is BOTH, or equals the requested authority. NONE covers only NONE.
def _scope_covers(recommended, requested):
    if recommended == "BOTH":
        return True
    return recommended == requested


# ---------------------------------------------------------------------------
# Petition
# ---------------------------------------------------------------------------
@bp.route("/gc/petitions", methods=["POST"])
def create_petition():
    user_id, role = get_identity()
    require_role(role, ["Petitioner"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    nominated = require_string(body, "nominated_fiduciary_id")
    requested_authority = require_enum(body, "requested_authority", {"PERSON", "ESTATE", "BOTH"})
    alleged_grounds = require_string(body, "alleged_grounds")
    resolve_ref(db.cases, case_id)
    resolve_ref(db.fiduciaries, nominated)

    record = {
        "case_id": case_id,
        "petitioner_user_id": user_id,
        "nominated_fiduciary_id": nominated,
        "requested_authority": requested_authority,
        "alleged_grounds": alleged_grounds,
        "status": "FILED",
    }
    stamp_create(record)
    with db.lock:
        db.petitions[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/petitions/<pid>", methods=["GET"])
def get_petition(pid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.petitions, pid), 200)


@bp.route("/gc/petitions", methods=["GET"])
def list_petitions():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.petitions.values())
    case_id = request.args.get("case_id")
    nominated = request.args.get("nominated_fiduciary_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    if nominated is not None:
        items = [p for p in items if p["nominated_fiduciary_id"] == nominated]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/petitions/<pid>/find-probable-cause", methods=["POST"])
def find_probable_cause(pid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    petition = resolve_path(db.petitions, pid)
    if petition["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Petition must be FILED")
    petition["status"] = "PROBABLE_CAUSE"
    stamp_update(petition)
    case = db.cases.get(petition["case_id"])
    if case is not None and case["status"] == "DRAFT":
        case["status"] = "PENDING_EVALUATION"
        stamp_update(case)
    return object_response(petition, 200)


@bp.route("/gc/petitions/<pid>/order-evaluation", methods=["POST"])
def order_evaluation(pid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    petition = resolve_path(db.petitions, pid)
    if petition["status"] != "PROBABLE_CAUSE":
        raise err("ERR_INVALID_STATE", "Petition must be PROBABLE_CAUSE")
    petition["status"] = "EVALUATION_ORDERED"
    stamp_update(petition)
    return object_response(petition, 200)


def _filed_evaluation_for_petition(petition_id):
    for ev in db.evaluations.values():
        if ev["petition_id"] == petition_id and ev["status"] == "FILED":
            return ev
    return None


@bp.route("/gc/petitions/<pid>/grant", methods=["POST"])
def grant_petition(pid):
    user_id, role = get_identity()
    require_role(role, ["Judge"])
    petition = resolve_path(db.petitions, pid)
    # Validation order: segregation (8) before invalid_state (9)? PRD §3.9 lists
    # ERR_SEGREGATION_OF_DUTIES at priority 8, ERR_INVALID_STATE at 9. So
    # segregation is checked first when both could apply.
    if user_id == petition["petitioner_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Granting judge may not be the petitioner")
    if petition["status"] != "READY_FOR_HEARING":
        raise err("ERR_INVALID_STATE", "Petition must be READY_FOR_HEARING")
    evaluation = _filed_evaluation_for_petition(pid)
    if evaluation is None:
        raise err("ERR_INVALID_STATE", "Petition has no filed evaluation")
    if evaluation["finding"] == "COMPETENT":
        raise err("ERR_EVALUATION_FINDS_COMPETENT", "Evaluation finds the person competent")
    if not _scope_covers(evaluation["recommended_scope"], petition["requested_authority"]):
        raise err("ERR_SCOPE_EXCEEDS_RECOMMENDATION", "Requested authority exceeds recommended scope")

    petition["status"] = "GRANTED"
    stamp_update(petition)
    case = db.cases.get(petition["case_id"])
    if case is not None and case["status"] == "PENDING_EVALUATION":
        case["status"] = "AWAITING_APPOINTMENT"
        stamp_update(case)
    person = db.protected_persons.get(case["protected_person_id"]) if case else None
    if person is not None:
        person["capacity_status"] = "ADJUDICATED_INCAPACITATED"
        stamp_update(person)
    return object_response(petition, 200)


@bp.route("/gc/petitions/<pid>/dismiss", methods=["POST"])
def dismiss_petition(pid):
    user_id, role = get_identity()
    require_role(role, ["Judge"])
    petition = resolve_path(db.petitions, pid)
    if user_id == petition["petitioner_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Dismissing judge may not be the petitioner")
    if petition["status"] not in ("READY_FOR_HEARING", "PROBABLE_CAUSE"):
        raise err("ERR_INVALID_STATE", "Petition must be READY_FOR_HEARING or PROBABLE_CAUSE")
    petition["status"] = "DISMISSED"
    stamp_update(petition)
    case = db.cases.get(petition["case_id"])
    if case is not None:
        case["status"] = "TERMINATED"
        stamp_update(case)
        person = db.protected_persons.get(case["protected_person_id"])
        if person is not None:
            person["active_case_id"] = None
            stamp_update(person)
    return object_response(petition, 200)


# ---------------------------------------------------------------------------
# CapacityEvaluation
# ---------------------------------------------------------------------------
@bp.route("/gc/evaluations", methods=["POST"])
def create_evaluation():
    user_id, role = get_identity()
    require_role(role, ["CourtExaminer"])
    body = get_json_body()
    petition_id = require_string(body, "petition_id")
    finding = require_enum(body, "finding", {"INCAPACITATED", "PARTIALLY_INCAPACITATED", "COMPETENT"})
    recommended_scope = require_enum(body, "recommended_scope", {"NONE", "PERSON", "ESTATE", "BOTH"})
    resolve_ref(db.petitions, petition_id)

    record = {
        "petition_id": petition_id,
        "examiner_user_id": user_id,
        "finding": finding,
        "recommended_scope": recommended_scope,
        "status": "DRAFT",
    }
    stamp_create(record)
    with db.lock:
        db.evaluations[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/evaluations/<eid>", methods=["GET"])
def get_evaluation(eid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.evaluations, eid), 200)


@bp.route("/gc/evaluations", methods=["GET"])
def list_evaluations():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.evaluations.values())
    petition_id = request.args.get("petition_id")
    if petition_id is not None:
        items = [e for e in items if e["petition_id"] == petition_id]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/evaluations/<eid>/file", methods=["POST"])
def file_evaluation(eid):
    _, role = get_identity()
    require_role(role, ["CourtExaminer"])
    evaluation = resolve_path(db.evaluations, eid)
    petition = db.petitions.get(evaluation["petition_id"])
    # Order (PRD §3.2): DRAFT (invalid_state) first, then evaluation-ordered,
    # then segregation. But the global ordering (§3.9) puts segregation (8) before
    # invalid_state (9) and evaluation-not-ordered (11). We follow the §3.2 local
    # narrative which lists DRAFT, then EVALUATION_ORDERED, then segregation —
    # however global priority wins: segregation_of_duties(8) > invalid_state(9) >
    # evaluation_not_ordered(11). We apply the global priority order.
    if petition is not None and evaluation["examiner_user_id"] == petition["petitioner_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Examiner may not be the petitioner")
    if evaluation["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Evaluation must be DRAFT")
    if petition is None or petition["status"] != "EVALUATION_ORDERED":
        raise err("ERR_EVALUATION_NOT_ORDERED", "Parent petition is not EVALUATION_ORDERED")

    evaluation["status"] = "FILED"
    stamp_update(evaluation)
    # Bubble up: petition EVALUATION_ORDERED -> READY_FOR_HEARING.
    petition["status"] = "READY_FOR_HEARING"
    stamp_update(petition)
    return object_response(evaluation, 200)
