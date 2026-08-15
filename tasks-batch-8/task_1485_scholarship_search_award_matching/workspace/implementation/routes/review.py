"""Review cycles and review scores (PRD §3.5)."""

from decimal import Decimal

from flask import Blueprint, g, request

import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import calc
from services.validate import require_fields, req_string, req_int, req_date, opt_bool
from routes.programs import get_program_or_404

bp = Blueprint("review", __name__)

CYCLE_ROLES = ("ScholarshipCoordinator", "CommitteeReviewer")


def get_cycle_or_404(cid):
    c = db.get("review_cycles", cid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "ReviewCycle not found")
    return c


def get_score_or_404(sid):
    s = db.get("review_scores", sid)
    if s is None:
        raise_err("ERR_NOT_FOUND", "ReviewScore not found")
    return s


def _cycle_scores(cycle_id, application_id=None):
    out = [s for s in db.all_records("review_scores") if s["cycle_id"] == cycle_id]
    if application_id is not None:
        out = [s for s in out if s["application_id"] == application_id]
    return out


def _under_review_apps(program_id):
    return [a for a in db.all_records("applications")
            if a["program_id"] == program_id and a["status"] == "UNDER_REVIEW"]


# ---------------------------------------------------------------------------
# Review cycles
# ---------------------------------------------------------------------------

@bp.route("/api/review-cycles", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_cycle():
    data = body()
    require_fields(data, ["program_id", "label", "starts_on", "ends_on",
                          "quorum_count", "selection_quota"])
    program_id = data["program_id"]
    if not isinstance(program_id, str) or db.get("programs", program_id) is None:
        raise_err("ERR_NOT_FOUND", "ScholarshipProgram not found")
    label = req_string(data, "label")
    starts_on = req_date(data, "starts_on")
    ends_on = req_date(data, "ends_on")
    quorum = req_int(data, "quorum_count", 0)
    selection = req_int(data, "selection_quota", 0)
    waitlist = 0
    if "waitlist_quota" in data and data["waitlist_quota"] is not None:
        waitlist = req_int(data, "waitlist_quota", 0)
    if ends_on <= starts_on:
        raise_err("ERR_INVALID_DATE_RANGE", "ends_on must be later than starts_on")
    s, e = starts_on, ends_on
    for other in db.all_records("review_cycles"):
        if other["program_id"] != program_id:
            continue
        # Half-open [starts_on, ends_on) overlap; adjacency (ends == starts) allowed.
        if s < other["ends_on"] and other["starts_on"] < e:
            raise_err("ERR_CYCLE_WINDOW_OVERLAP",
                      "Cycle window overlaps another cycle of the same program")
    rec = db.create_record("review_cycles", {
        "program_id": program_id,
        "label": label,
        "starts_on": s,
        "ends_on": e,
        "quorum_count": quorum,
        "selection_quota": selection,
        "waitlist_quota": waitlist,
        "status": "SETUP",
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/review-cycles", methods=["GET"])
@require_roles(*CYCLE_ROLES)
def list_cycles():
    items = db.all_records("review_cycles")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/review-cycles/<cid>", methods=["GET"])
@require_roles(*CYCLE_ROLES)
def get_cycle(cid):
    return success(db.serialize(get_cycle_or_404(cid)))


@bp.route("/api/review-cycles/<cid>/open-scoring", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def open_scoring(cid):
    cycle = get_cycle_or_404(cid)
    if cycle["status"] != "SETUP":
        raise_err("ERR_INVALID_STATE", "Only a SETUP cycle can open scoring")
    db.mutate(cycle, status="SCORING")
    for app in db.all_records("applications"):
        if app["program_id"] == cycle["program_id"] and app["status"] == "SUBMITTED":
            db.mutate(app, status="UNDER_REVIEW", _cycle_id=cycle["id"])
    return success(db.serialize(cycle))


@bp.route("/api/review-cycles/<cid>/open-deliberation", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def open_deliberation(cid):
    cycle = get_cycle_or_404(cid)
    if cycle["status"] != "SCORING":
        raise_err("ERR_INVALID_STATE", "Only a SCORING cycle can open deliberation")
    for app in _under_review_apps(cycle["program_id"]):
        counted = [s for s in _cycle_scores(cid, app["id"])
                   if s["status"] in ("SUBMITTED", "LOCKED")]
        if len(counted) < cycle["quorum_count"]:
            raise_err("ERR_QUORUM_NOT_MET",
                      "Every UNDER_REVIEW application needs quorum_count submitted/locked scores")
    for s in _cycle_scores(cid):
        if s["status"] == "SUBMITTED":
            db.mutate(s, status="LOCKED")
    db.mutate(cycle, status="DELIBERATION")
    return success(db.serialize(cycle))


@bp.route("/api/review-cycles/<cid>/reopen-scoring", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def reopen_scoring(cid):
    cycle = get_cycle_or_404(cid)
    if cycle["status"] != "DELIBERATION":
        raise_err("ERR_INVALID_STATE", "Only a DELIBERATION cycle can reopen scoring")
    # Lock is monotone: LOCKED scores stay LOCKED.
    db.mutate(cycle, status="SCORING")
    return success(db.serialize(cycle))


@bp.route("/api/review-cycles/<cid>/finalize", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def finalize_cycle(cid):
    cycle = get_cycle_or_404(cid)
    if cycle["status"] != "DELIBERATION":
        raise_err("ERR_INVALID_STATE", "Only a DELIBERATION cycle can be finalized")
    apps = _under_review_apps(cycle["program_id"])
    for app in apps:
        locked = [s for s in _cycle_scores(cid, app["id"]) if s["status"] == "LOCKED"]
        if len(locked) < cycle["quorum_count"]:
            raise_err("ERR_QUORUM_NOT_MET",
                      "Every UNDER_REVIEW application needs quorum_count LOCKED scores")
    if cycle["selection_quota"] + cycle["waitlist_quota"] > len(apps):
        raise_err("ERR_VALIDATION",
                  "selection_quota + waitlist_quota exceeds the number of UNDER_REVIEW applications")

    program = get_program_or_404(cycle["program_id"])
    ranked = []
    for app in apps:
        locked = [s for s in _cycle_scores(cid, app["id"]) if s["status"] == "LOCKED"]
        totals = [Decimal(str(s["weighted_total"])) for s in locked]
        cycle_score = calc.q2(sum(totals) / Decimal(len(totals)))
        need_avg = sum(Decimal(s["need_score"]) for s in locked) / Decimal(len(locked))
        ranked.append((app, cycle_score, need_avg))
    # cycle_score DESC, need avg DESC, submitted_at ASC, created_at ASC.
    ranked.sort(key=lambda t: (-t[1], -t[2], t[0].get("submitted_at") or "",
                               t[0]["created_at"], t[0]["_seq"]))
    n = len(ranked)
    for idx, (app, cycle_score, _need_avg) in enumerate(ranked):
        rank = idx + 1
        if rank <= cycle["selection_quota"]:
            outcome = "SELECTED"
        elif rank <= cycle["selection_quota"] + cycle["waitlist_quota"]:
            outcome = "WAITLISTED"
        else:
            outcome = "NOT_SELECTED"
        db.mutate(app, status=outcome, cycle_score=float(cycle_score),
                  decision_rank=rank, _cycle_id=cycle["id"])
    assert sum(1 for _ in ranked) == n  # count invariant: S + W + NS == prior UNDER_REVIEW
    db.mutate(cycle, status="FINALIZED")
    return success(db.serialize(cycle))


# ---------------------------------------------------------------------------
# Review scores
# ---------------------------------------------------------------------------

@bp.route("/api/review-scores", methods=["POST"])
@require_roles("CommitteeReviewer")
def create_score():
    data = body()
    require_fields(data, ["cycle_id", "application_id", "academic_score",
                          "essay_score", "need_score"])
    cycle_id = data["cycle_id"]
    application_id = data["application_id"]
    if not isinstance(cycle_id, str) or db.get("review_cycles", cycle_id) is None:
        raise_err("ERR_NOT_FOUND", "ReviewCycle not found")
    if not isinstance(application_id, str) or db.get("applications", application_id) is None:
        raise_err("ERR_NOT_FOUND", "Application not found")
    academic = req_int(data, "academic_score", 0, 100)
    essay = req_int(data, "essay_score", 0, 100)
    need = req_int(data, "need_score", 0, 100)
    coi = opt_bool(data, "conflict_of_interest", False)

    cycle = db.get("review_cycles", cycle_id)
    app = db.get("applications", application_id)
    if cycle["status"] != "SCORING":
        raise_err("ERR_INVALID_STATE", "Scores may be drafted only while the cycle is SCORING")
    if app["program_id"] != cycle["program_id"]:
        raise_err("ERR_VALIDATION", "Application does not belong to the cycle's program")
    if app["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Application is not UNDER_REVIEW")
    for s in _cycle_scores(cycle_id, application_id):
        if s["reviewer_user_id"] == g.user_id:
            raise_err("ERR_REVIEWER_DUPLICATE_SCORE",
                      "One score per reviewer per application per cycle")
    rec = db.create_record("review_scores", {
        "cycle_id": cycle_id,
        "application_id": application_id,
        "reviewer_user_id": g.user_id,
        "academic_score": academic,
        "essay_score": essay,
        "need_score": need,
        "conflict_of_interest": coi,
        "status": "DRAFT",
        "weighted_total": None,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/review-scores", methods=["GET"])
@require_roles(*CYCLE_ROLES)
def list_scores():
    items = db.all_records("review_scores")
    cycle_id = request.args.get("cycle_id")
    application_id = request.args.get("application_id")
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if application_id is not None:
        items = [s for s in items if s["application_id"] == application_id]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(s) for s in page], response_type="array", pagination=meta)


@bp.route("/api/review-scores/<sid>", methods=["GET"])
@require_roles(*CYCLE_ROLES)
def get_score(sid):
    return success(db.serialize(get_score_or_404(sid)))


@bp.route("/api/review-scores/<sid>/submit", methods=["POST"])
@require_roles("CommitteeReviewer")
def submit_score(sid):
    score = get_score_or_404(sid)
    if score["reviewer_user_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Reviewers may only submit their own scores")
    if score["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT score can be submitted")
    cycle = get_cycle_or_404(score["cycle_id"])
    if cycle["status"] != "SCORING":
        raise_err("ERR_INVALID_STATE", "The cycle is not in SCORING")
    if score["conflict_of_interest"]:
        raise_err("ERR_CONFLICT_OF_INTEREST",
                  "A score declared as conflict-of-interest cannot be submitted")
    program = get_program_or_404(cycle["program_id"])
    app = db.get("applications", score["application_id"])
    student = db.get("students", app["student_id"])
    total = calc.committee_weighted_total(program, student, score["academic_score"],
                                          score["essay_score"], score["need_score"])
    db.mutate(score, status="SUBMITTED", weighted_total=float(total))
    return success(db.serialize(score))


@bp.route("/api/review-scores/<sid>/recall", methods=["POST"])
@require_roles("CommitteeReviewer")
def recall_score(sid):
    score = get_score_or_404(sid)
    if score["reviewer_user_id"] != g.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Reviewers may only recall their own scores")
    if score["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED score can be recalled")
    cycle = get_cycle_or_404(score["cycle_id"])
    if cycle["status"] != "SCORING":
        raise_err("ERR_INVALID_STATE", "Recall is impossible once deliberation has locked scores")
    db.mutate(score, status="DRAFT", weighted_total=None)
    return success(db.serialize(score))
