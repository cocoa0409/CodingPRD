"""Judge and JudgeConflict routes."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import judge_out, judge_conflict_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL, ERR_FORBIDDEN, ERR_JUDGE_HAS_ASSIGNMENTS,
    ERR_REFERENTIAL_INTEGRITY,
)

bp = Blueprint("judges", __name__)

_ALL_ROLES = ("FairDirector", "Mentor", "EthicsReviewer", "Judge",
              "OperationsLead", "SafetyInspector")

_VALID_JUDGE_STATUS = {"INVITED", "ACTIVE", "INACTIVE"}
_ACTIVATABLE_PHASES = {"SETUP", "REGISTRATION_OPEN", "REGISTRATION_CLOSED"}


def _touch(j):
    j["updated_at"] = db.now_display_iso()
    j["version"] += 1


@bp.route("/science-fair/judges", methods=["POST"])
def create_judge():
    body = V.get_json_body()
    V.require_fields(body, ["fair_edition_id", "full_name", "max_assignments"])
    feid = V.req_str(body, "fair_edition_id")
    full_name = V.req_str(body, "full_name")
    expertise = V.opt_str_list(body, "expertise_category_ids")
    max_a = V.req_int(body, "max_assignments")
    if max_a < 1:
        raise_err(ERR_INVALID_REQUEST, "max_assignments must be >= 1")

    require_roles("FairDirector")

    edition = db.fair_editions.get(feid)
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Fair edition not found: {feid}")

    # expertise_category_ids must reference categories in the same edition
    expertise = expertise or []
    for cid in expertise:
        cat = db.categories.get(cid)
        if cat is None or cat["fair_edition_id"] != feid:
            raise_err(ERR_REFERENTIAL_INTEGRITY,
                      f"Expertise category {cid} does not exist in edition "
                      f"{feid}")

    now = db.now_display_iso()
    j = {
        "id": db.new_id(),
        "fair_edition_id": feid,
        "full_name": full_name,
        "expertise_category_ids": expertise,
        "max_assignments": max_a,
        "active_assignment_count": 0,
        "status": "INVITED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.judges[j["id"]] = j
    return success_object(judge_out(j), 201)


@bp.route("/science-fair/judges", methods=["GET"])
def list_judges():
    require_roles(*_ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.judges.values())
    feid = request.args.get("fair_edition_id")
    if feid:
        items = [j for j in items if j["fair_edition_id"] == feid]
    st = request.args.get("status")
    if st:
        items = [j for j in items if j["status"] == st]
    data, total = paginate(items, judge_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/judges/<jid>", methods=["GET"])
def get_judge(jid):
    require_roles(*_ALL_ROLES)
    j = db.judges.get(jid)
    if j is None:
        raise_err(ERR_NOT_FOUND, f"Judge not found: {jid}")
    return success_object(judge_out(j))


@bp.route("/science-fair/judges/<jid>/activate", methods=["POST"])
def activate_judge(jid):
    V.get_json_body()
    require_roles("FairDirector")
    j = db.judges.get(jid)
    if j is None:
        raise_err(ERR_NOT_FOUND, f"Judge not found: {jid}")
    if j["status"] == "INACTIVE":
        raise_err(ERR_ALREADY_TERMINAL, "Judge is INACTIVE (terminal)")
    if j["status"] != "INVITED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot activate judge from status {j['status']}")
    edition = db.fair_editions.get(j["fair_edition_id"])
    if edition is None or edition["status"] not in _ACTIVATABLE_PHASES:
        st = edition["status"] if edition else "missing"
        raise_err(ERR_INVALID_STATE,
                  f"Cannot activate judge while edition is {st}")
    j["status"] = "ACTIVE"
    _touch(j)
    return success_object(judge_out(j))


@bp.route("/science-fair/judges/<jid>/deactivate", methods=["POST"])
def deactivate_judge(jid):
    V.get_json_body()
    require_roles("FairDirector")
    j = db.judges.get(jid)
    if j is None:
        raise_err(ERR_NOT_FOUND, f"Judge not found: {jid}")
    if j["status"] == "INACTIVE":
        raise_err(ERR_ALREADY_TERMINAL, "Judge is INACTIVE (terminal)")
    if j["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot deactivate judge from status {j['status']}")
    if j["active_assignment_count"] > 0:
        raise_err(ERR_JUDGE_HAS_ASSIGNMENTS,
                  "Deactivate attempted while judge.active_assignment_count "
                  "> 0")
    j["status"] = "INACTIVE"
    _touch(j)
    return success_object(judge_out(j))


# ---- JudgeConflict ----

@bp.route("/science-fair/judges/<jid>/conflicts", methods=["POST"])
def declare_conflict(jid):
    body = V.get_json_body()
    V.require_fields(body, ["project_id", "reason"])
    project_id = V.req_str(body, "project_id")
    reason = V.req_str(body, "reason")

    user_id, role = require_roles("FairDirector", "Judge")

    j = db.judges.get(jid)
    if j is None:
        raise_err(ERR_NOT_FOUND, f"Judge not found: {jid}")

    # Judge role may only declare own conflicts
    if role == "Judge" and user_id != jid:
        raise_err(ERR_FORBIDDEN,
                  "Judge may only declare conflicts for self")

    project = db.projects.get(project_id)
    if project is None or project["fair_edition_id"] != j["fair_edition_id"]:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Project {project_id} does not exist in the judge's "
                  f"edition")

    now = db.now_display_iso()
    c = {
        "id": db.new_id(),
        "judge_id": jid,
        "project_id": project_id,
        "reason": reason,
        "created_at": now,
    }
    db.judge_conflicts[c["id"]] = c
    return success_object(judge_conflict_out(c), 201)


@bp.route("/science-fair/judges/<jid>/conflicts", methods=["GET"])
def list_judge_conflicts(jid):
    require_roles("FairDirector", "Judge")
    limit, offset = parse_pagination()
    if db.judges.get(jid) is None:
        raise_err(ERR_NOT_FOUND, f"Judge not found: {jid}")
    items = [c for c in db.judge_conflicts.values() if c["judge_id"] == jid]
    data, total = paginate(items, judge_conflict_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/judge-conflicts", methods=["GET"])
def list_all_conflicts():
    require_roles("FairDirector", "Judge")
    limit, offset = parse_pagination()
    items = list(db.judge_conflicts.values())
    jid = request.args.get("judge_id")
    if jid:
        items = [c for c in items if c["judge_id"] == jid]
    pid = request.args.get("project_id")
    if pid:
        items = [c for c in items if c["project_id"] == pid]
    data, total = paginate(items, judge_conflict_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/judge-conflicts/<cid>", methods=["GET"])
def get_conflict(cid):
    require_roles("FairDirector", "Judge")
    c = db.judge_conflicts.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, f"Judge conflict not found: {cid}")
    return success_object(judge_conflict_out(c))
