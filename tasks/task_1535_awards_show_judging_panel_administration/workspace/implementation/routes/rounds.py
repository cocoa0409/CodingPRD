"""ScoringRound endpoints: create/list/get, panel assignments, lifecycle
(lock-panel / open / close / normalize), and round-scoped scores."""
from datetime import timedelta

from flask import Blueprint, request

import audit
import clock
import services
import store
from auth import authenticate, authorize, forbid
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DUPLICATE,
    ERR_ROUND_WINDOW_TOO_CLOSE, ERR_STALE_VERSION, ERR_CONFLICT_OF_INTEREST,
    ERR_SEGREGATION_OF_DUTIES, ERR_PANEL_INCOMPLETE, ERR_INCOMPLETE_BALLOT,
    ERR_REFERENTIAL_INTEGRITY, ERR_CONSTRAINT_VIOLATION,
)
from util import (
    body_json, req_int, opt_int, req_enum, req_datetime, req_str, new_record,
    new_child_record, bump, success_object, list_response, get_or_404,
    ref_or_404,
)

bp = Blueprint("rounds", __name__)

SCORING_MODES = ["RAW_RANK", "Z_SCORE"]
ASSIGNMENT_ROLES = ["CHAIR", "MEMBER"]


# ---------------------------------------------------------------------------
# scoring rounds under a category
# ---------------------------------------------------------------------------
@bp.post("/awards/categories/<cid>/scoring-rounds")
def create_round(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    cat = get_or_404(store.categories, cid, "Category")
    body = body_json()
    round_index = req_int(body, "round_index")
    if round_index not in (1, 2, 3):
        raise_err(ERR_INVALID_REQUEST, "round_index must be 1, 2 or 3")
    advance_count = opt_int(body, "advance_count", None)
    scoring_mode = req_enum(body, "scoring_mode", SCORING_MODES)
    win_start = req_datetime(body, "scheduled_window_start")
    win_end = req_datetime(body, "scheduled_window_end")
    if win_end <= win_start:
        raise_err(ERR_INVALID_REQUEST,
                  "scheduled_window_end must be > scheduled_window_start")
    for r in services.non_voided_rounds(cat["id"]):
        if r["round_index"] == round_index:
            raise_err(ERR_DUPLICATE,
                      "a non-VOIDED round with round_index %d already exists" % round_index)
    gap = timedelta(hours=services.SCORING_ROUND_GAP_HOURS)
    for r in services.non_voided_rounds(cat["id"]):
        earlier_end, later_start = (r["scheduled_window_end"], win_start) \
            if r["scheduled_window_start"] <= win_start else (win_end, r["scheduled_window_start"])
        if later_start - earlier_end < gap:
            raise_err(ERR_ROUND_WINDOW_TOO_CLOSE,
                      "round windows within a category must leave a >= 12h gap")
    rec = new_record()
    rec.update({
        "category_id": cat["id"],
        "round_index": round_index,
        "name": services.ROUND_NAMES[round_index],
        "status": "CONFIGURING",
        "advance_count": advance_count,
        "scoring_mode": scoring_mode,
        "scheduled_window_start": win_start,
        "scheduled_window_end": win_end,
        "opened_at": None,
        "closed_at": None,
        "normalization_snapshot": None,
        "advanced_entry_ids": None,
        "entry_composites": None,
    })
    store.rounds[rec["id"]] = rec
    return success_object(services.serialize_round(rec), 201)


@bp.get("/awards/categories/<cid>/scoring-rounds")
def list_rounds(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    cat = get_or_404(store.categories, cid, "Category")
    records = [r for r in store.rounds.values() if r["category_id"] == cat["id"]]
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    return list_response(records, services.serialize_round)


@bp.get("/awards/scoring-rounds/<rid>")
def get_round(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    r = get_or_404(store.rounds, rid, "ScoringRound")
    return success_object(services.serialize_round(r), 200)


# ---------------------------------------------------------------------------
# panel assignments
# ---------------------------------------------------------------------------
@bp.post("/awards/scoring-rounds/<rid>/panel-assignments")
def propose_assignment(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    body = body_json()
    judge_id = req_str(body, "judge_id")
    arole = req_enum(body, "role", ASSIGNMENT_ROLES)
    expected = body.get("expected_scoring_round_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_scoring_round_version is required and must be an integer")
    judge = ref_or_404(store.judges, judge_id, "Judge")
    if rnd["status"] != "CONFIGURING":
        raise_err(ERR_INVALID_STATE,
                  "panel assignments require a CONFIGURING round")
    if expected != rnd["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_scoring_round_version %s != current %s"
                  % (expected, rnd["version"]))
    rec = new_record()
    rec.update({
        "judge_id": judge["id"],
        "category_id": rnd["category_id"],
        "scoring_round_id": rnd["id"],
        "role": arole,
        "status": "PROPOSED",
    })
    store.assignments[rec["id"]] = rec
    bump(rnd)
    return success_object(services.serialize_assignment(rec), 201)


@bp.get("/awards/scoring-rounds/<rid>/panel-assignments")
def list_round_assignments(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    records = services.assignments_of_round(rnd["id"])
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, services.serialize_assignment)


@bp.get("/awards/categories/<cid>/panel-assignments")
def list_category_assignments(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    cat = get_or_404(store.categories, cid, "Category")
    records = [a for a in store.assignments.values() if a["category_id"] == cat["id"]]
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, services.serialize_assignment)


@bp.post("/awards/panel-assignments/<aid>/confirm")
def confirm_assignment(aid):
    uid, role = authenticate()
    authorize(role, ["Judge"])
    a = get_or_404(store.assignments, aid, "PanelAssignment")
    services.guard_transition("assignment", a, {"PROPOSED"})
    rnd = store.rounds.get(a["scoring_round_id"])
    if rnd is None or rnd["status"] != "CONFIGURING":
        raise_err(ERR_INVALID_STATE, "the linked round must be CONFIGURING")
    judge = store.judges.get(a["judge_id"])
    if judge is None or judge["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "the assigned judge must be ACTIVE")
    # priority 13 (conflict) precedes priority 14 (segregation of duties)
    if services.confirm_blocked_by_conflict(a):
        raise_err(ERR_CONFLICT_OF_INTEREST,
                  "an unresolved conflict bars this assignment")
    if uid != a["judge_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "only the assigned judge may confirm this assignment")
    a["status"] = "ACTIVE"
    bump(a)
    return success_object(services.serialize_assignment(a), 200)


def _end_assignment(a, void_scores=True):
    """Shared recuse/remove side effects."""
    for s in services.scores_of_round(a["scoring_round_id"]):
        if s["judge_id"] == a["judge_id"] and s["status"] == "DRAFT":
            s["status"] = "VOIDED"
    judge = store.judges.get(a["judge_id"])
    if judge is not None:
        services.recompute_reliability(judge)
    rnd = store.rounds.get(a["scoring_round_id"])
    if rnd is not None:
        services.demote_round_if_understaffed(rnd)


@bp.post("/awards/panel-assignments/<aid>/recuse")
def recuse_assignment(aid):
    uid, role = authenticate()
    authorize(role, ["Judge"])
    a = get_or_404(store.assignments, aid, "PanelAssignment")
    if uid != a["judge_id"]:
        forbid("Judge may only recuse their own assignments")
    services.guard_transition("assignment", a, {"ACTIVE"})
    a["status"] = "RECUSED"
    bump(a)
    # seed an ACKNOWLEDGED HARD/OTHER declaration covering this category
    cat = store.categories.get(a["category_id"])
    season_id = cat["season_id"] if cat else None
    covered = any(
        d["judge_id"] == a["judge_id"]
        and d["status"] in ("DECLARED", "ACKNOWLEDGED")
        and (d.get("category_id") in (None, a["category_id"]))
        and (d.get("season_id") in (None, season_id))
        for d in store.declarations.values())
    if not covered:
        d = new_child_record()
        d.update({
            "judge_id": a["judge_id"],
            "season_id": season_id,
            "entrant_id": None,
            "category_id": a["category_id"],
            "conflict_type": "OTHER",
            "severity": "HARD",
            "note": "seeded by recusal",
            "status": "ACKNOWLEDGED",
        })
        store.declarations[d["id"]] = d
    _end_assignment(a)
    return success_object(services.serialize_assignment(a), 200)


@bp.post("/awards/panel-assignments/<aid>/remove")
def remove_assignment(aid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    a = get_or_404(store.assignments, aid, "PanelAssignment")
    services.guard_transition("assignment", a, {"ACTIVE"})
    rnd = store.rounds.get(a["scoring_round_id"])
    if rnd is None or rnd["status"] not in ("CONFIGURING", "PANEL_LOCKED"):
        raise_err(ERR_INVALID_STATE,
                  "removal requires the round to be CONFIGURING or PANEL_LOCKED")
    a["status"] = "REMOVED"
    bump(a)
    _end_assignment(a)
    return success_object(services.serialize_assignment(a), 200)


# ---------------------------------------------------------------------------
# round lifecycle
# ---------------------------------------------------------------------------
@bp.post("/awards/scoring-rounds/<rid>/lock-panel")
def lock_panel(rid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    services.guard_transition("round", rnd, {"CONFIGURING"})
    cat = store.categories.get(rnd["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    if season is None or season["status"] not in ("SUBMISSION_CLOSED", "JUDGING"):
        raise_err(ERR_INVALID_STATE,
                  "panel lock requires season SUBMISSION_CLOSED or JUDGING")
    active = services.active_panel_assignments(rnd["id"])
    chairs = [a for a in active if a["role"] == "CHAIR"]
    if len(chairs) > 1:
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "exactly one ACTIVE CHAIR assignment is required")
    if len(active) < (cat["panel_size"] if cat else 0) or len(chairs) != 1:
        raise_err(ERR_PANEL_INCOMPLETE,
                  "ACTIVE assignments %d (panel_size %d), CHAIR count %d"
                  % (len(active), cat["panel_size"] if cat else 0, len(chairs)))
    rnd["status"] = "PANEL_LOCKED"
    bump(rnd)
    audit.append(season["id"], role, uid, "ROUND_PANEL_LOCKED",
                 "ScoringRound", rnd["id"],
                 {"before": {"status": "CONFIGURING"},
                  "after": {"status": "PANEL_LOCKED"}})
    return success_object(services.serialize_round(rnd), 200)


@bp.post("/awards/scoring-rounds/<rid>/open")
def open_round(rid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    services.guard_transition("round", rnd, {"PANEL_LOCKED"})
    cat = store.categories.get(rnd["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    if season is None or season["status"] != "JUDGING":
        raise_err(ERR_INVALID_STATE, "round open requires season JUDGING")
    pending = [r for r in services.non_voided_rounds(rnd["category_id"])
               if r["status"] not in ("NORMALIZED", "PUBLISHED")]
    if pending:
        min_index = min(r["round_index"] for r in pending)
        if rnd["round_index"] != min_index:
            raise_err(ERR_INVALID_STATE,
                      "rounds run in ascending round_index order")
    prev = None
    for r in services.non_voided_rounds(rnd["category_id"]):
        if r["round_index"] == rnd["round_index"] - 1:
            prev = r
            break
    if prev is not None and prev["status"] != "NORMALIZED":
        raise_err(ERR_INVALID_STATE,
                  "the preceding round must be NORMALIZED first")
    if not services.round_candidate_ids(rnd):
        raise_err(ERR_INVALID_STATE, "the round's candidate set is empty")
    rnd["status"] = "OPEN"
    rnd["opened_at"] = clock.now()
    bump(rnd)
    audit.append(season["id"], role, uid, "ROUND_OPEN", "ScoringRound", rnd["id"],
                 {"before": {"status": "PANEL_LOCKED"}, "after": {"status": "OPEN"}})
    return success_object(services.serialize_round(rnd), 200)


@bp.post("/awards/scoring-rounds/<rid>/close")
def close_round(rid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    services.guard_transition("round", rnd, {"OPEN"})
    cat = store.categories.get(rnd["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    candidates = services.round_candidate_ids(rnd)
    for a in services.active_panel_assignments(rnd["id"]):
        for eid in candidates:
            ok = any(s["judge_id"] == a["judge_id"] and s["entry_id"] == eid
                     and s["status"] in ("SUBMITTED", "LOCKED")
                     for s in services.scores_of_round(rnd["id"]))
            if not ok:
                raise_err(ERR_INCOMPLETE_BALLOT,
                          "judge %s lacks a submitted ballot for entry %s"
                          % (a["judge_id"], eid))
    for s in services.scores_of_round(rnd["id"]):
        if s["status"] == "SUBMITTED":
            s["status"] = "LOCKED"
    rnd["status"] = "CLOSED"
    rnd["closed_at"] = clock.now()
    bump(rnd)
    audit.append(season["id"], role, uid, "ROUND_CLOSE", "ScoringRound", rnd["id"],
                 {"before": {"status": "OPEN"}, "after": {"status": "CLOSED"}})
    return success_object(services.serialize_round(rnd), 200)


@bp.post("/awards/scoring-rounds/<rid>/normalize")
def normalize_round(rid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    services.guard_transition("round", rnd, {"CLOSED"})
    cat = store.categories.get(rnd["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    services.run_normalization(rnd)
    rnd["status"] = "NORMALIZED"
    bump(rnd)
    if season is not None:
        audit.append(season["id"], role, uid, "ROUND_NORMALIZED",
                     "ScoringRound", rnd["id"],
                     {"before": {"status": "CLOSED"},
                      "after": {"status": "NORMALIZED"}})
    return success_object(services.serialize_round(rnd), 200)


# ---------------------------------------------------------------------------
# scores within a round
# ---------------------------------------------------------------------------
@bp.post("/awards/scoring-rounds/<rid>/scores")
def create_score(rid):
    uid, role = authenticate()
    authorize(role, ["Judge"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    body = body_json()
    entry_id = req_str(body, "entry_id")
    judge_id = req_str(body, "judge_id")
    criterion_scores = body.get("criterion_scores")
    if not isinstance(criterion_scores, dict):
        raise_err(ERR_INVALID_REQUEST, "criterion_scores must be an object")
    for k, v in criterion_scores.items():
        if not isinstance(k, str) or not isinstance(v, (int, float)) \
                or isinstance(v, bool):
            raise_err(ERR_INVALID_REQUEST,
                      "criterion_scores must map criterion codes to numbers")
    expected = body.get("expected_scoring_round_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_scoring_round_version is required and must be an integer")
    entry = ref_or_404(store.entries, entry_id, "Entry")
    judge = ref_or_404(store.judges, judge_id, "Judge")
    if judge["id"] != uid:
        forbid("Judge may only create their own ballots")
    if rnd["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "scores require an OPEN round")
    if expected != rnd["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_scoring_round_version %s != current %s"
                  % (expected, rnd["version"]))
    # priority 13: conflict bar at ballot creation
    cat = store.categories.get(rnd["category_id"])
    if cat is not None and services.judge_conflicts_with_entrant(
            judge["id"], entry["entrant_id"], cat["season_id"],
            rnd["category_id"], severity="HARD"):
        raise_err(ERR_CONFLICT_OF_INTEREST,
                  "judge is conflicted with this entry's entrant")
    for s in services.scores_of_round(rnd["id"]):
        if (s["judge_id"] == judge["id"] and s["entry_id"] == entry["id"]
                and s["status"] != "VOIDED"):
            raise_err(ERR_DUPLICATE,
                      "a score for this judge and entry already exists in this round")
    # priority 20: score authorship — ACTIVE assignment + candidate entry
    has_assignment = any(a["judge_id"] == judge["id"] and a["status"] == "ACTIVE"
                         for a in services.assignments_of_round(rnd["id"]))
    if not has_assignment:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  "the acting judge holds no ACTIVE assignment in this round")
    if entry["id"] not in set(services.round_candidate_ids(rnd)):
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  "the entry is not a candidate of this round")
    rec = new_child_record()
    rec.update({
        "scoring_round_id": rnd["id"],
        "entry_id": entry["id"],
        "judge_id": judge["id"],
        "criterion_scores": criterion_scores,
        "weighted_raw": None,
        "z_intermediate": None,
        "rank_among_judges_scores": None,
        "normalized_score": None,
        "status": "DRAFT",
    })
    store.scores[rec["id"]] = rec
    bump(rnd)
    return success_object(services.serialize_score(rec), 201)


@bp.get("/awards/scoring-rounds/<rid>/scores")
def list_round_scores(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Judge"])
    rnd = get_or_404(store.rounds, rid, "ScoringRound")
    records = services.scores_of_round(rnd["id"])
    judge_id = request.args.get("judge_id")
    entry_id = request.args.get("entry_id")
    status = request.args.get("status")
    if judge_id:
        records = [s for s in records if s["judge_id"] == judge_id]
    if entry_id:
        records = [s for s in records if s["entry_id"] == entry_id]
    if status:
        records = [s for s in records if s["status"] == status]
    return list_response(records, services.serialize_score)


@bp.post("/awards/scores/<sid>/submit")
def submit_score(sid):
    uid, role = authenticate()
    authorize(role, ["Judge"])
    s = get_or_404(store.scores, sid, "Score")
    if s["judge_id"] != uid:
        forbid("Judge may only submit their own ballots")
    services.guard_transition("score", s, {"DRAFT"})
    rnd = store.rounds.get(s["scoring_round_id"])
    if rnd is None or rnd["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "the linked round must be OPEN")
    cat = store.categories.get(rnd["category_id"])
    entry = store.entries.get(s["entry_id"])
    # priority 13: conflict bar also enforced at submission
    if cat is not None and entry is not None and services.judge_conflicts_with_entrant(
            s["judge_id"], entry["entrant_id"], cat["season_id"],
            rnd["category_id"], severity="HARD"):
        raise_err(ERR_CONFLICT_OF_INTEREST,
                  "judge is conflicted with this entry's entrant")
    rubric = cat["scoring_rubric"] if cat else []
    for c in rubric:
        v = s["criterion_scores"].get(c["criterion_code"])
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not (0 <= v <= c["max_score"]):
            raise_err(ERR_CONSTRAINT_VIOLATION,
                      "criterion_scores must cover every rubric criterion within [0, max_score]")
    s["weighted_raw"] = services.compute_weighted_raw(s["criterion_scores"], rubric)
    s["status"] = "SUBMITTED"
    return success_object(services.serialize_score(s), 200)
