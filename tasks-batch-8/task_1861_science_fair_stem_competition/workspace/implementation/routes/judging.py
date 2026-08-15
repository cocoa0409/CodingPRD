"""JudgingAssignment and ScoreSheet routes."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import judging_assignment_out, score_sheet_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL, ERR_FORBIDDEN, ERR_SOD_VIOLATION,
    ERR_CONSTRAINT_VIOLATION, ERR_REFERENTIAL_INTEGRITY,
    ERR_NOT_JUDGING_PHASE, ERR_NO_ELIGIBLE_JUDGE,
)
from services.calculations import (
    renormalize_judge_pool, recompute_project_aggregates,
)

bp = Blueprint("judging", __name__)

_ASSIGNABLE_PHASES = {"REGISTRATION_CLOSED", "JUDGING"}
_VALID_ASG_STATUS = {"ASSIGNED", "SUBMITTED", "RECUSED", "RELEASED"}
_NON_TERMINAL_ASG = {"ASSIGNED"}


def _touch_entity(e):
    e["updated_at"] = db.now_display_iso()
    e["version"] += 1


def _get_assignment_or_404(aid):
    a = db.judging_assignments.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Judging assignment not found: {aid}")
    return a


def _has_conflict(judge_id, project_id):
    return any(c["judge_id"] == judge_id and c["project_id"] == project_id
               for c in db.judge_conflicts.values())


def _has_live_assignment(judge_id, project_id):
    return any(a["judge_id"] == judge_id and a["project_id"] == project_id
               and a["status"] in _NON_TERMINAL_ASG
               for a in db.judging_assignments.values())


# ---------------------------------------------------------------------------
# Assignment creation (explicit or auto mode)
# ---------------------------------------------------------------------------

@bp.route("/science-fair/projects/<pid>/judging-assignments", methods=["POST"])
def create_assignment(pid):
    body = V.get_json_body()
    judge_id = V.opt_str(body, "judge_id")

    require_roles("FairDirector")

    project = db.projects.get(pid)
    if project is None:
        raise_err(ERR_NOT_FOUND, f"Project not found: {pid}")

    if project["registration_status"] == "WITHDRAWN":
        raise_err(ERR_ALREADY_TERMINAL, "Project is WITHDRAWN (terminal)")

    edition = db.fair_editions.get(project["fair_edition_id"])
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent edition missing")

    # Edition must be in REGISTRATION_CLOSED or JUDGING
    if edition["status"] not in _ASSIGNABLE_PHASES:
        raise_err(ERR_INVALID_STATE,
                  "Judging assignment requires edition status "
                  "REGISTRATION_CLOSED or JUDGING")
    # Project must be CONFIRMED
    if project["registration_status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE,
                  "Project must be CONFIRMED for judging assignment")

    if judge_id is None:
        # Auto mode: run the selector
        judge_id = _select_judge(project, edition)
        if judge_id is None:
            raise_err(ERR_NO_ELIGIBLE_JUDGE,
                      "Auto-assign selector found an empty eligible-judge "
                      "pool")
    else:
        # Explicit mode: pipeline order SoD(5) -> capacity/dup(7) ->
        # referential(8). Referential check on the judge's existence must
        # still 404-vs-422: judge_id is a payload reference, so a dangling
        # reference is ERR_REFERENTIAL_INTEGRITY per the validation table.
        judge = db.judges.get(judge_id)
        if judge is not None and judge["fair_edition_id"] != project["fair_edition_id"]:
            raise_err(ERR_REFERENTIAL_INTEGRITY,
                      f"Judge {judge_id} belongs to a different edition")

        # Priority 5: SoD — conflict row excludes the judge
        if judge is not None and _has_conflict(judge_id, pid):
            raise_err(ERR_SOD_VIOLATION,
                      "Judge has a declared conflict with this project")

        # Priority 7: capacity + duplicate live assignment
        if judge is not None:
            if judge["active_assignment_count"] >= judge["max_assignments"]:
                raise_err(ERR_CONSTRAINT_VIOLATION,
                          "Judge at max_assignments capacity")
            if _has_live_assignment(judge_id, pid):
                raise_err(ERR_CONSTRAINT_VIOLATION,
                          "Duplicate non-terminal assignment for "
                          "(judge, project)")

        # Priority 8: referential integrity
        if judge is None:
            raise_err(ERR_REFERENTIAL_INTEGRITY,
                      f"Judge not found: {judge_id}")

    judge = db.judges[judge_id]

    now = db.now_display_iso()
    a = {
        "id": db.new_id(),
        "project_id": pid,
        "judge_id": judge_id,
        "status": "ASSIGNED",
        "assigned_at": db.now_display_iso(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.judging_assignments[a["id"]] = a

    judge["active_assignment_count"] += 1
    _touch_entity(judge)

    project["judging_status"] = "ASSIGNED"
    _touch_entity(project)

    return success_object(judging_assignment_out(a), 201)


def _select_judge(project, edition):
    """judge_selector calculation: deterministic eligible-judge ranking."""
    eligible = []
    for j in db.judges.values():
        if j["status"] != "ACTIVE":
            continue
        if j["fair_edition_id"] != project["fair_edition_id"]:
            continue
        if j["active_assignment_count"] >= j["max_assignments"]:
            continue
        if _has_conflict(j["id"], project["id"]):
            continue
        if _has_live_assignment(j["id"], project["id"]):
            continue
        eligible.append(j)

    if not eligible:
        return None

    cat_id = project["category_id"]

    def rank_key(j):
        expertise_match = 0 if cat_id in j["expertise_category_ids"] else 1
        return (expertise_match, j["active_assignment_count"],
                j["created_at"], j["id"])

    eligible.sort(key=rank_key)
    return eligible[0]["id"]


# ---------------------------------------------------------------------------
# Assignment readback
# ---------------------------------------------------------------------------

@bp.route("/science-fair/judging-assignments", methods=["GET"])
def list_assignments():
    require_roles("FairDirector", "Judge")
    limit, offset = parse_pagination()
    items = list(db.judging_assignments.values())
    pid = request.args.get("project_id")
    if pid:
        items = [a for a in items if a["project_id"] == pid]
    jid = request.args.get("judge_id")
    if jid:
        items = [a for a in items if a["judge_id"] == jid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    data, total = paginate(items, judging_assignment_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/judging-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles("FairDirector", "Judge")
    a = _get_assignment_or_404(aid)
    return success_object(judging_assignment_out(a))


# ---------------------------------------------------------------------------
# Score sheet submission
# ---------------------------------------------------------------------------

@bp.route("/science-fair/judging-assignments/<aid>/score-sheets",
          methods=["POST"])
def submit_score_sheet(aid):
    body = V.get_json_body()
    V.require_fields(body, ["raw_score"])
    raw = V.req_int(body, "raw_score")
    if raw < 0 or raw > 100:
        raise_err(ERR_INVALID_REQUEST,
                  "raw_score must be an integer between 0 and 100")

    user_id, role = require_roles("Judge")
    a = _get_assignment_or_404(aid)

    project = db.projects.get(a["project_id"])
    if project is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent project missing")

    # Ownership: judge scores own assignment only
    if a["judge_id"] != user_id:
        raise_err(ERR_FORBIDDEN,
                  "Judge may only score own assignments")

    # Assignment must be ASSIGNED (terminal check first)
    if a["status"] in ("SUBMITTED", "RECUSED", "RELEASED"):
        raise_err(ERR_ALREADY_TERMINAL,
                  f"Assignment is {a['status']} (terminal)")
    if a["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot submit score from assignment status "
                  f"{a['status']}")

    # Priority 5: SoD — judge must not have a conflict with the project
    if _has_conflict(user_id, a["project_id"]):
        raise_err(ERR_SOD_VIOLATION,
                  "Judge has a declared conflict with this project")

    # Priority 6: temporal — edition must be in JUDGING
    edition = db.fair_editions.get(project["fair_edition_id"])
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent edition missing")
    if edition["status"] != "JUDGING":
        raise_err(ERR_NOT_JUDGING_PHASE,
                  "Score submission requires edition in JUDGING phase")

    judge = db.judges.get(a["judge_id"])
    if judge is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Judge missing")

    # Create the score sheet
    now = db.now_display_iso()
    s = {
        "id": db.new_id(),
        "judging_assignment_id": aid,
        "project_id": a["project_id"],
        "judge_id": a["judge_id"],
        "raw_score": raw,
        "normalized_score": None,
        "submitted_at": db.now_display_iso(),
        "created_at": now,
    }
    db.score_sheets[s["id"]] = s

    # Transition assignment
    a["status"] = "SUBMITTED"
    _touch_entity(a)

    # Judge workload decrement
    judge["active_assignment_count"] -= 1
    _touch_entity(judge)

    # Re-normalize the judge's full SUBMITTED pool in this edition; the
    # pool re-derivation can change normalized scores on OTHER projects'
    # sheets, so recompute aggregates for every affected project.
    affected = renormalize_judge_pool(judge["id"], edition["id"],
                                      edition["normalization_algorithm"])
    for apid in affected:
        ap = db.projects.get(apid)
        if ap is not None:
            recompute_project_aggregates(ap, edition)
            _touch_entity(ap)

    # Maybe flip to JUDGED
    submitted_count = sum(
        1 for x in db.judging_assignments.values()
        if x["project_id"] == project["id"] and x["status"] == "SUBMITTED")
    if submitted_count >= edition["max_judges_per_project"]:
        project["judging_status"] = "JUDGED"
        _touch_entity(project)

    return success_object(score_sheet_out(s), 201)


# ---------------------------------------------------------------------------
# Recuse / release
# ---------------------------------------------------------------------------

@bp.route("/science-fair/judging-assignments/<aid>/recuse", methods=["POST"])
def recuse_assignment(aid):
    V.get_json_body()
    user_id, role = require_roles("Judge")
    a = _get_assignment_or_404(aid)

    if a["judge_id"] != user_id:
        raise_err(ERR_FORBIDDEN,
                  "Judge may only recuse from own assignments")

    if a["status"] in ("SUBMITTED", "RECUSED", "RELEASED"):
        raise_err(ERR_ALREADY_TERMINAL,
                  f"Assignment is {a['status']} (terminal)")
    if a["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot recuse from assignment status {a['status']}")

    judge = db.judges.get(a["judge_id"])
    project = db.projects.get(a["project_id"])

    a["status"] = "RECUSED"
    _touch_entity(a)

    if judge is not None:
        judge["active_assignment_count"] -= 1
        _touch_entity(judge)

    # Create JudgeConflict row if none exists
    if not _has_conflict(a["judge_id"], a["project_id"]):
        now = db.now_display_iso()
        c = {
            "id": db.new_id(),
            "judge_id": a["judge_id"],
            "project_id": a["project_id"],
            "reason": "recused",
            "created_at": now,
        }
        db.judge_conflicts[c["id"]] = c

    # If project has zero remaining ASSIGNED assignments -> UNASSIGNED
    if project is not None:
        remaining = sum(
            1 for x in db.judging_assignments.values()
            if x["project_id"] == project["id"] and x["status"] == "ASSIGNED")
        if remaining == 0:
            project["judging_status"] = "UNASSIGNED"
            _touch_entity(project)

    return success_object(judging_assignment_out(a))


@bp.route("/science-fair/judging-assignments/<aid>/release", methods=["POST"])
def release_assignment(aid):
    V.get_json_body()
    require_roles("FairDirector")
    a = _get_assignment_or_404(aid)

    if a["status"] in ("SUBMITTED", "RECUSED", "RELEASED"):
        raise_err(ERR_ALREADY_TERMINAL,
                  f"Assignment is {a['status']} (terminal)")
    if a["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot release assignment in status {a['status']}")

    project = db.projects.get(a["project_id"])
    edition = db.fair_editions.get(project["fair_edition_id"]) if project else None
    if edition is None or edition["status"] != "JUDGING":
        st = edition["status"] if edition else "missing"
        raise_err(ERR_INVALID_STATE,
                  f"Release is a judging-phase operation; edition is {st}")

    judge = db.judges.get(a["judge_id"])

    a["status"] = "RELEASED"
    _touch_entity(a)

    if judge is not None:
        judge["active_assignment_count"] -= 1
        _touch_entity(judge)

    if project is not None:
        remaining = sum(
            1 for x in db.judging_assignments.values()
            if x["project_id"] == project["id"] and x["status"] == "ASSIGNED")
        if remaining == 0:
            project["judging_status"] = "UNASSIGNED"
            _touch_entity(project)

    return success_object(judging_assignment_out(a))


# ---------------------------------------------------------------------------
# ScoreSheet readback
# ---------------------------------------------------------------------------

@bp.route("/science-fair/score-sheets", methods=["GET"])
def list_score_sheets():
    require_roles("FairDirector", "Judge")
    limit, offset = parse_pagination()
    items = list(db.score_sheets.values())
    pid = request.args.get("project_id")
    if pid:
        items = [s for s in items if s["project_id"] == pid]
    jid = request.args.get("judge_id")
    if jid:
        items = [s for s in items if s["judge_id"] == jid]
    aid = request.args.get("judging_assignment_id")
    if aid:
        items = [s for s in items if s["judging_assignment_id"] == aid]
    data, total = paginate(items, score_sheet_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/score-sheets/<sid>", methods=["GET"])
def get_score_sheet(sid):
    require_roles("FairDirector", "Judge")
    s = db.score_sheets.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, f"Score sheet not found: {sid}")
    return success_object(score_sheet_out(s))
