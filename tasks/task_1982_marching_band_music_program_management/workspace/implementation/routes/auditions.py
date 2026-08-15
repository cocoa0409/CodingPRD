"""Audition + AuditionEntry + ChairPlacement endpoints."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from flask import Blueprint, request
from db import store, new_id, now, now_iso, parse_dt
from errors import (
    raise_err, ERR_AUDITION_NOT_FOUND, ERR_AUDITION_ENTRY_NOT_FOUND,
    ERR_CHAIR_PLACEMENT_NOT_FOUND, ERR_AUDITION_NOT_SCORING,
    ERR_AUDITION_SCORES_NOT_FINAL, ERR_AUDITION_NOT_PUBLISHED,
    ERR_SCORES_INCOMPLETE, ERR_DUPLICATE_SCORE, ERR_SCORE_OUT_OF_RANGE,
    ERR_STUDENT_NOT_ENROLLED, ERR_STUDENT_NOT_FOUND, ERR_STALE_VERSION,
    ERR_SECTION_LEADER_REQUIRED, ERR_CHALLENGE_WINDOW_EXPIRED,
    ERR_INVALID_REQUEST, ERR_FORBIDDEN_OWNERSHIP,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import audition_out, audition_entry_out, chair_placement_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions
from routes.programs import _get_program_or_404, _program_posture_open
from routes.students import _get_student_or_404

bp = Blueprint("auditions", __name__)

SECTIONS = {"WOODWIND", "BRASS", "PERCUSSION", "GUARD"}

W_MUSICIANSHIP = Decimal("0.5")
W_MARCHING = Decimal("0.3")
W_LEADERSHIP = Decimal("0.2")
SINGLE_JUDGE_PENALTY = Decimal("0.95")


def _get_audition_or_404(aid):
    a = store.auditions.get(aid)
    if a is None:
        raise_err(ERR_AUDITION_NOT_FOUND, f"audition {aid} not found")
    return a


def _get_entry_or_404(eid):
    e = store.audition_entries.get(eid)
    if e is None:
        raise_err(ERR_AUDITION_ENTRY_NOT_FOUND, f"audition entry {eid} not found")
    return e


def _get_placement_or_404(pid):
    c = store.chair_placements.get(pid)
    if c is None:
        raise_err(ERR_CHAIR_PLACEMENT_NOT_FOUND, f"chair placement {pid} not found")
    return c


def _weighted(js):
    return (W_MUSICIANSHIP * Decimal(str(js["musicianship"])) +
            W_MARCHING * Decimal(str(js["marching"])) +
            W_LEADERSHIP * Decimal(str(js["leadership"])))


def _compute_scores_raw(entries):
    """RAW_WEIGHTED: per entry, weighted mean with drop-lowest/single-judge penalty."""
    for entry in entries:
        wjs = [_weighted(js) for js in entry["judge_scores"]]
        if len(wjs) == 1:
            composite = (wjs[0] * SINGLE_JUDGE_PENALTY).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif len(wjs) == 2:
            composite = ((wjs[0] + wjs[1]) / Decimal(2)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            wjs.sort()
            rest = wjs[1:]
            composite = (sum(rest) / Decimal(len(rest))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entry["composite_score"] = float(composite)


def _compute_scores_rank(entries):
    """RANK_NORMALIZED: Borda per judge."""
    n = len(entries)
    # composite = sum over judges of (n - rank)
    composites = {e["id"]: 0 for e in entries}
    if not entries:
        return
    # Get the union of judge_ids (assume consistent across entries for simplicity; per judge in the entry)
    # We'll build: for each judge_id present in any entry, rank entries by that judge's weighted score DESC
    all_judges = set()
    for e in entries:
        for js in e["judge_scores"]:
            all_judges.add(js["judge_id"])
    for jid in all_judges:
        # rank entries that have a score from this judge
        scored = []
        for e in entries:
            for js in e["judge_scores"]:
                if js["judge_id"] == jid:
                    scored.append((e, _weighted(js)))
                    break
        # Sort by weighted DESC, tie created_at ASC
        scored.sort(key=lambda t: (-t[1], t[0]["created_at"]))
        # Borda: rank 1 -> n-1 points; rank k -> n-k points
        for rank_idx, (e, _) in enumerate(scored):
            borda = n - (rank_idx + 1)
            composites[e["id"]] += borda
    for e in entries:
        e["composite_score"] = composites[e["id"]]


def _assign_ranks(entries):
    """rank by composite DESC, tie created_at ASC, 1-based."""
    ordered = sorted(entries, key=lambda e: (-Decimal(str(e["composite_score"])), e["created_at"]))
    for i, e in enumerate(ordered, start=1):
        e["rank"] = i


@bp.route("/band/auditions", methods=["POST"])
def create_audition():
    require_roles(["BandDirector", "AssistantDirector"])
    data = body()
    check_unknown(data, {"program_id", "section", "chair_capacity"})
    require(data, "program_id", "section", "chair_capacity")
    pid = to_str(data["program_id"], "program_id")
    section = to_enum(data["section"], "section", SECTIONS)
    chair_capacity = to_int(data["chair_capacity"], "chair_capacity")
    if chair_capacity < 0:
        raise_err(ERR_INVALID_REQUEST, "chair_capacity must be non-negative")

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    aid = new_id()
    now_s = now_iso()
    a = {
        "id": aid,
        "program_id": pid,
        "section": section,
        "chair_capacity": chair_capacity,
        "scoring_mode": program["scoring_mode"],
        "status": "SCORING_OPEN",
        "published_at": None,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.auditions[aid] = a
    return success(audition_out(a), status=201)


@bp.route("/band/auditions", methods=["GET"])
def list_auditions():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.auditions.values())
    pid = request.args.get("program_id")
    if pid:
        items = [a for a in items if a["program_id"] == pid]
    sect = request.args.get("section")
    if sect:
        items = [a for a in items if a["section"] == sect]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([audition_out(a) for a in page], is_list=True, pagination=pag)


@bp.route("/band/auditions/<aid>", methods=["GET"])
def get_audition(aid):
    require_roles(["Any"])
    apply_time_transitions()
    a = _get_audition_or_404(aid)
    return success(audition_out(a))


@bp.route("/band/auditions/<aid>/finalize-scores", methods=["POST"])
def finalize_scores(aid):
    require_roles(["BandDirector"])
    a = _get_audition_or_404(aid)
    if a["status"] not in ("SCORING_OPEN", "UNDER_CHALLENGE"):
        raise_err(ERR_AUDITION_NOT_SCORING, "audition is not SCORING_OPEN or UNDER_CHALLENGE")
    entries = [e for e in store.audition_entries.values() if e["audition_id"] == aid]
    for e in entries:
        if not e.get("judge_scores"):
            raise_err(ERR_SCORES_INCOMPLETE, "every entry must have at least one judge score")
    if not entries:
        raise_err(ERR_SCORES_INCOMPLETE, "no entries to finalize")

    if a["scoring_mode"] == "RAW_WEIGHTED":
        _compute_scores_raw(entries)
    else:
        _compute_scores_rank(entries)
    _assign_ranks(entries)
    for e in entries:
        e["version"] += 1
        e["updated_at"] = now_iso()
    a["status"] = "SCORES_FINALIZED"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(audition_out(a))


@bp.route("/band/auditions/<aid>/placements", methods=["POST"])
def publish_placements(aid):
    require_roles(["BandDirector"])
    a = _get_audition_or_404(aid)
    data = body()
    check_unknown(data, {"expected_audition_version"})
    require(data, "expected_audition_version")
    expected = to_int(data["expected_audition_version"], "expected_audition_version")
    if a["status"] != "SCORES_FINALIZED":
        raise_err(ERR_AUDITION_SCORES_NOT_FINAL, "audition is not SCORES_FINALIZED")
    if a["version"] != expected:
        raise_err(ERR_STALE_VERSION, "expected_audition_version does not match current version")

    # Supersede prior PUBLISHED placements for this audition
    for cp in store.chair_placements.values():
        if cp["audition_id"] == aid and cp["status"] == "PUBLISHED":
            cp["status"] = "SUPERSEDED"
            cp["version"] += 1
            cp["updated_at"] = now_iso()

    # Create new placements by rank
    entries = [e for e in store.audition_entries.values() if e["audition_id"] == aid]
    entries.sort(key=lambda e: e["rank"])
    for e in entries:
        cp_id = new_id()
        now_s = now_iso()
        if e["rank"] <= a["chair_capacity"]:
            chair_number = e["rank"]
            is_alternate = False
        else:
            chair_number = None
            is_alternate = True
        cp = {
            "id": cp_id,
            "audition_id": aid,
            "entry_id": e["id"],
            "chair_number": chair_number,
            "is_alternate": is_alternate,
            "status": "PUBLISHED",
            "created_at": now_s,
            "updated_at": now_s,
            "version": 1,
        }
        store.chair_placements[cp_id] = cp

    a["published_at"] = now_iso()
    a["status"] = "PLACEMENTS_PUBLISHED"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(audition_out(a))


@bp.route("/band/auditions/<aid>/challenge", methods=["POST"])
def challenge_audition(aid):
    uid, role = require_roles(["SectionLeader"])
    a = _get_audition_or_404(aid)
    data = body()
    check_unknown(data, {"entry_id", "reason"})
    require(data, "entry_id")
    entry_id = to_str(data["entry_id"], "entry_id")
    # Path / body FK check
    entry = _get_entry_or_404(entry_id)

    # SectionLeader checks
    student = store.students.get(uid)
    if student is None or not student.get("is_section_leader") or student.get("section") != a["section"]:
        raise_err(ERR_SECTION_LEADER_REQUIRED,
                  "acting student must be section leader of the audition's section")

    if a["status"] != "PLACEMENTS_PUBLISHED":
        raise_err(ERR_AUDITION_NOT_PUBLISHED, "audition is not PLACEMENTS_PUBLISHED")

    # Challenge window: 7 days
    published_at = parse_dt(a["published_at"]) if a.get("published_at") else None
    if published_at is not None and now() > published_at + timedelta(days=7):
        raise_err(ERR_CHALLENGE_WINDOW_EXPIRED, "challenge window expired")

    a["status"] = "UNDER_CHALLENGE"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(audition_out(a))


# -------- AuditionEntry --------

@bp.route("/band/audition-entries", methods=["POST"])
def create_entry():
    require_roles(["BandDirector", "AssistantDirector"])
    data = body()
    check_unknown(data, {"audition_id", "student_id"})
    require(data, "audition_id", "student_id")
    audition_id = to_str(data["audition_id"], "audition_id")
    student_id = to_str(data["student_id"], "student_id")

    audition = _get_audition_or_404(audition_id)
    student = _get_student_or_404(student_id)
    if student["enrollment_status"] != "ENROLLED":
        raise_err(ERR_STUDENT_NOT_ENROLLED, "student must be ENROLLED")

    eid = new_id()
    now_s = now_iso()
    e = {
        "id": eid,
        "audition_id": audition_id,
        "student_id": student_id,
        "judge_scores": [],
        "composite_score": None,
        "rank": None,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.audition_entries[eid] = e
    return success(audition_entry_out(e), status=201)


@bp.route("/band/audition-entries", methods=["GET"])
def list_entries():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.audition_entries.values())
    aid = request.args.get("audition_id")
    if aid:
        items = [e for e in items if e["audition_id"] == aid]
    sid = request.args.get("student_id")
    if sid:
        items = [e for e in items if e["student_id"] == sid]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([audition_entry_out(e) for e in page], is_list=True, pagination=pag)


@bp.route("/band/audition-entries/<eid>", methods=["GET"])
def get_entry(eid):
    require_roles(["Any"])
    apply_time_transitions()
    e = _get_entry_or_404(eid)
    return success(audition_entry_out(e))


@bp.route("/band/audition-entries/<eid>/scores", methods=["POST"])
def submit_score(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_entry_or_404(eid)
    data = body()
    check_unknown(data, {"judge_id", "musicianship", "marching", "leadership"})
    require(data, "judge_id", "musicianship", "marching", "leadership")
    judge_id = to_str(data["judge_id"], "judge_id")
    musicianship = to_int(data["musicianship"], "musicianship")
    marching = to_int(data["marching"], "marching")
    leadership = to_int(data["leadership"], "leadership")

    # Audition must be SCORING_OPEN
    audition = _get_audition_or_404(e["audition_id"])
    if audition["status"] != "SCORING_OPEN":
        raise_err(ERR_AUDITION_NOT_SCORING, "audition is not SCORING_OPEN")

    # Duplicate judge
    for js in e["judge_scores"]:
        if js["judge_id"] == judge_id:
            raise_err(ERR_DUPLICATE_SCORE, f"judge {judge_id} has already scored this entry")

    # Range check
    for v, name in [(musicianship, "musicianship"), (marching, "marching"), (leadership, "leadership")]:
        if v < 0 or v > 100:
            raise_err(ERR_SCORE_OUT_OF_RANGE, f"{name} must be between 0 and 100")

    e["judge_scores"].append({
        "judge_id": judge_id,
        "musicianship": musicianship,
        "marching": marching,
        "leadership": leadership,
    })
    e["version"] += 1
    e["updated_at"] = now_iso()
    return success(audition_entry_out(e), status=201)


# -------- ChairPlacement --------

@bp.route("/band/chair-placements", methods=["GET"])
def list_placements():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.chair_placements.values())
    aid = request.args.get("audition_id")
    if aid:
        items = [c for c in items if c["audition_id"] == aid]
    eid = request.args.get("entry_id")
    if eid:
        items = [c for c in items if c["entry_id"] == eid]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([chair_placement_out(c) for c in page], is_list=True, pagination=pag)


@bp.route("/band/chair-placements/<cid>", methods=["GET"])
def get_placement(cid):
    require_roles(["Any"])
    apply_time_transitions()
    c = _get_placement_or_404(cid)
    return success(chair_placement_out(c))
