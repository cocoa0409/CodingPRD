"""Routes: screener assignments and rubric scores."""

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_not_found, err_phase,
                    err_referential)
from store import DB
from util import (auth, check_ownership, created_key, get_body, get_or_404,
                  ok, paginate, require_role, v_dt, v_enum, v_int, v_str)

bp = Blueprint("screening", __name__)

ASSIGN_READ = ["FESTIVAL_ADMIN", "PROGRAM_CHAIR", "PROGRAMMER"]
SCORE_READ = ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "PROGRAM_CHAIR",
              "PROGRAMMER"]


def _score_fields(body, partial=False):
    kw = {"required": not partial}
    originality = v_int(body, "originality", min_v=1, max_v=10, **kw)
    craft = v_int(body, "craft", min_v=1, max_v=10, **kw)
    story = v_int(body, "story", min_v=1, max_v=10, **kw)
    overall = v_int(body, "overall", min_v=1, max_v=10, **kw)
    recommendation = v_enum(body, "recommendation", D.RECOMMENDATIONS, **kw)
    return originality, craft, story, overall, recommendation


@bp.post("/festival/screener-assignments")
def create_assignment():
    body = get_body()
    submission_id = v_str(body, "submission_id")
    programmer_id = v_str(body, "programmer_id")
    due_at = v_dt(body, "due_at")
    uid, role = auth()
    require_role(role, ["PROGRAM_CHAIR"])
    sub = DB.submissions.get(submission_id)
    prog = DB.programmers.get(programmer_id)
    if sub is not None and sub["status"] != "IN_SCREENING":
        raise err_invalid_state("Submission is not IN_SCREENING")
    if sub is not None:
        edition = DB.editions.get(sub["edition_id"])
        if edition is not None and edition["status"] != "SCREENING":
            raise err_phase("Edition is not in SCREENING")
    if sub is not None and prog is not None:
        if sub["production_company"] in prog["coi_production_companies"]:
            raise err409("ERR_COI_RECUSAL_REQUIRED",
                         "Programmer is conflicted with this production company")
    if sub is None or prog is None:
        raise err_referential("Submission or programmer not found")
    if any(a["submission_id"] == submission_id
           and a["programmer_id"] == programmer_id and a["status"] == "ASSIGNED"
           for a in DB.assignments.values()):
        raise err409("ERR_DUPLICATE_ASSIGNMENT",
                     "An open assignment already exists for this pair")
    if not prog["active"]:
        raise err_invalid_state("Programmer is inactive")
    if sub["category"] not in prog["categories_covered"]:
        raise err_invalid_state("Programmer does not cover this category")
    if D.active_assignment_count(programmer_id) >= prog["max_active_assignments"]:
        raise err409("ERR_ASSIGNMENT_CAP",
                     "Programmer is at their active assignment cap")
    rec = D.new_rec({
        "submission_id": submission_id, "programmer_id": programmer_id,
        "due_at": due_at, "status": "ASSIGNED",
        "replaced_by_assignment_id": None,
    })
    DB.assignments[rec["id"]] = rec
    D.touch(prog)
    return ok(D.ser_assignment(rec), 201)


@bp.get("/festival/screener-assignments/<aid>")
def get_assignment(aid):
    uid, role = auth()
    require_role(role, ASSIGN_READ)
    rec = get_or_404(DB.assignments, aid)
    if role == "PROGRAMMER":
        check_ownership(rec["programmer_id"] == uid)
    return ok(D.ser_assignment(rec))


@bp.get("/festival/screener-assignments")
def list_assignments():
    uid, role = auth()
    require_role(role, ASSIGN_READ)
    items = list(DB.assignments.values())
    if role == "PROGRAMMER":
        items = [a for a in items if a["programmer_id"] == uid]
    submission_id = request.args.get("submission_id")
    programmer_id = request.args.get("programmer_id")
    status = request.args.get("status")
    if submission_id is not None:
        items = [a for a in items if a["submission_id"] == submission_id]
    if programmer_id is not None:
        items = [a for a in items if a["programmer_id"] == programmer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_assignment(a) for a in page], pagination=meta)


@bp.post("/festival/screener-assignments/<aid>/recuse")
def recuse_assignment(aid):
    get_body()
    uid, role = auth()
    require_role(role, ["PROGRAMMER"])
    rec = get_or_404(DB.assignments, aid)
    check_ownership(rec["programmer_id"] == uid)
    if rec["status"] != "ASSIGNED":
        raise err_invalid_state("Only an ASSIGNED assignment may be recused")
    rec["status"] = "RECUSED"
    D.touch(rec)
    sub = DB.submissions.get(rec["submission_id"])
    if sub is not None:
        D.replacement_cascade(sub, rec)
    prog = DB.programmers.get(rec["programmer_id"])
    if prog is not None:
        D.touch(prog)
    return ok(D.ser_assignment(rec))


@bp.post("/festival/screener-assignments/<aid>/scores")
def create_score(aid):
    body = get_body()
    originality, craft, story, overall, recommendation = _score_fields(body)
    uid, role = auth()
    require_role(role, ["PROGRAMMER"])
    rec = get_or_404(DB.assignments, aid)
    check_ownership(rec["programmer_id"] == uid)
    if rec["status"] == "SCORED" or any(
            s["assignment_id"] == aid for s in DB.scores.values()):
        raise err409("ERR_SCORE_EXISTS",
                     "This assignment already has a score")
    if rec["status"] != "ASSIGNED":
        raise err_invalid_state("Only an ASSIGNED assignment may be scored")
    sub = DB.submissions.get(rec["submission_id"])
    edition = DB.editions.get(sub["edition_id"]) if sub else None
    if edition is None or edition["status"] != "SCREENING":
        raise err_phase("Scores are accepted only during SCREENING")
    score = D.new_rec({
        "assignment_id": aid, "originality": originality, "craft": craft,
        "story": story, "overall": overall, "recommendation": recommendation,
        "locked": False,
    })
    DB.scores[score["id"]] = score
    rec["status"] = "SCORED"
    D.touch(rec)
    prog = DB.programmers.get(rec["programmer_id"])
    if prog is not None:
        D.touch(prog)
    if sub is not None:
        D.recompute_submission_scores(sub)
        D.touch(sub)
    return ok(D.ser_score(score), 201)


@bp.get("/festival/screener-assignments/<aid>/scores")
def list_assignment_scores(aid):
    uid, role = auth()
    require_role(role, SCORE_READ)
    rec = get_or_404(DB.assignments, aid)
    if role == "PROGRAMMER":
        check_ownership(rec["programmer_id"] == uid)
    items = sorted((s for s in DB.scores.values() if s["assignment_id"] == aid),
                   key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_score(s) for s in page], pagination=meta)


@bp.get("/festival/scores/<sid>")
def get_score(sid):
    uid, role = auth()
    require_role(role, SCORE_READ)
    rec = get_or_404(DB.scores, sid)
    if role == "PROGRAMMER":
        assignment = DB.assignments.get(rec["assignment_id"])
        check_ownership(assignment is not None
                        and assignment["programmer_id"] == uid)
    return ok(D.ser_score(rec))


@bp.patch("/festival/scores/<sid>")
def patch_score(sid):
    body = get_body()
    originality, craft, story, overall, recommendation = _score_fields(
        body, partial=True)
    uid, role = auth()
    require_role(role, ["PROGRAMMER"])
    rec = get_or_404(DB.scores, sid)
    assignment = DB.assignments.get(rec["assignment_id"])
    check_ownership(assignment is not None
                    and assignment["programmer_id"] == uid)
    if rec["locked"]:
        raise err409("ERR_SCORES_LOCKED",
                     "Scores are locked once the edition leaves SCREENING")
    if originality is not None:
        rec["originality"] = originality
    if craft is not None:
        rec["craft"] = craft
    if story is not None:
        rec["story"] = story
    if overall is not None:
        rec["overall"] = overall
    if recommendation is not None:
        rec["recommendation"] = recommendation
    D.touch(rec)
    sub = DB.submissions.get(assignment["submission_id"]) if assignment else None
    if sub is not None:
        D.recompute_submission_scores(sub)
        D.touch(sub)
    return ok(D.ser_score(rec))
