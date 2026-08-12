"""Routes: rotations, warm-up blocks, scores, inquiries."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from common import (APPARATUS, ApiError, DB, RESOLUTIONS, apply_filters,
                    authorize, body, delta_field, fk_or_404, get_or_404,
                    meet_of_entry, meet_of_score, new_entity, now, ok_array,
                    ok_list, ok_object, parse_dt, q3, req_enum, req_str,
                    required, score_field, sort_items, touch)
from logic import (compute_provisional, generate_rotations,
                   generate_warmup_blocks, has_open_inquiry,
                   run_system_transitions)
from serialize import ser_block, ser_inquiry, ser_rotation, ser_score

bp = Blueprint("scoring", __name__)

ROTATION_TERMINAL = ("FINALIZED",)
SCORE_TERMINAL = ("FINAL", "VOID")
INQUIRY_TERMINAL = ("UPHELD", "DENIED", "WITHDRAWN", "EXPIRED")
SCORE_READ = ["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach",
              "Spectator"]


# ----------------------------------------------------------------------------
# Rotations
# ----------------------------------------------------------------------------

@bp.post("/api/v1/sessions/<sid>/rotations/generate")
def generate_session_rotations(sid):
    authorize(["MeetDirector"])
    session = get_or_404(DB.sessions, sid, "Session")
    created = generate_rotations(session)
    run_system_transitions()
    return ok_array([ser_rotation(r) for r in created], 201)


@bp.get("/api/v1/sessions/<sid>/rotations")
def list_rotations(sid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach"])
    get_or_404(DB.sessions, sid, "Session")
    items = apply_filters(
        sort_items(r for r in DB.rotations.values() if r["session_id"] == sid),
        {"state": ("str", "state")})
    return ok_list([ser_rotation(r) for r in items])


@bp.get("/api/v1/rotations/<rid>")
def get_rotation(rid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach"])
    return ok_object(ser_rotation(get_or_404(DB.rotations, rid, "Rotation")))


@bp.post("/api/v1/rotations/<rid>/open-scoring")
def open_rotation_scoring(rid):
    authorize(["MeetDirector"])
    rotation = get_or_404(DB.rotations, rid, "Rotation")
    if rotation["state"] in ROTATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Rotation is FINALIZED")
    if rotation["state"] != "TIMED_WARMUP_HELD":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rotation state is %s, expected TIMED_WARMUP_HELD"
                       % rotation["state"])
    panel = None
    for p in DB.panels.values():
        if p["session_id"] == rotation["session_id"] \
                and p["apparatus"] == rotation["apparatus"]:
            panel = p
            break
    confirmed = 0
    if panel is not None:
        confirmed = sum(1 for a in DB.assignments.values()
                        if a["judge_panel_id"] == panel["id"]
                        and a["assignment_state"] == "CONFIRMED")
    if panel is None or confirmed < (panel["required_judge_count"] if panel else 1):
        raise ApiError("ERR_PANEL_UNDERSTAFFED", 422,
                       "Judge panel for this apparatus is not fully staffed")
    if panel["panel_state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Judge panel state is %s, expected ACTIVE"
                       % panel["panel_state"])
    if now() < rotation["scheduled_start"]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rotation scheduled_start has not been reached")
    rotation["state"] = "OPEN_FOR_SCORING"
    rotation["actual_start"] = now()
    touch(rotation)
    run_system_transitions()
    return ok_object(ser_rotation(rotation))


@bp.post("/api/v1/rotations/<rid>/close-scoring")
def close_rotation_scoring(rid):
    authorize(["MeetDirector"])
    rotation = get_or_404(DB.rotations, rid, "Rotation")
    if rotation["state"] in ROTATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Rotation is FINALIZED")
    if rotation["state"] != "OPEN_FOR_SCORING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rotation state is %s, expected OPEN_FOR_SCORING"
                       % rotation["state"])
    acceptable = ("FINAL", "PUBLISHED", "UNDER_INQUIRY", "INQUIRY_RESOLVED",
                  "VOID")
    for e in DB.entries.values():
        if e["session_id"] != rotation["session_id"]:
            continue
        if e["squad_id"] is None or e["entry_status"] == "SCRATCHED":
            continue
        has_score = any(
            s["athlete_entry_id"] == e["id"] and s["rotation_id"] == rid
            and s["score_state"] in acceptable
            for s in DB.scores.values())
        if not has_score:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "AthleteEntry %s has no recorded score for this "
                           "rotation" % e["id"])
    rotation["state"] = "SCORING_CLOSED"
    rotation["actual_end"] = now()
    touch(rotation)
    for q in DB.squads.values():
        if q["session_id"] == rotation["session_id"]:
            q["rotation_index"] = min(3, q["rotation_index"] + 1)
            touch(q)
    run_system_transitions()
    return ok_object(ser_rotation(rotation))


# ----------------------------------------------------------------------------
# Warm-up blocks
# ----------------------------------------------------------------------------

@bp.post("/api/v1/rotations/<rid>/warmup-blocks")
def create_block(rid):
    authorize(["MeetDirector"])
    rotation = get_or_404(DB.rotations, rid, "Rotation")
    data = body()
    squad_id = required(data, "squad_id")
    if not isinstance(squad_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "squad_id must be a string")
    squad = fk_or_404(DB.squads, squad_id, "squad_id")
    if squad["session_id"] != rotation["session_id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "squad_id does not belong to the rotation's session")
    apparatus = req_enum(data, "apparatus", APPARATUS)
    block_start = parse_dt(required(data, "block_start"), "block_start")
    block_end = parse_dt(required(data, "block_end"), "block_end")
    if block_end <= block_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "block_end must be after block_start")
    window_start = rotation["scheduled_start"] - timedelta(minutes=60)
    if block_start < window_start or block_end > rotation["scheduled_start"]:
        raise ApiError("ERR_WARMUP_BLOCK_OVERLAP", 422,
                       "Warm-up block must fit within the 60-minute window "
                       "before the rotation start")
    for b in DB.blocks.values():
        if b["rotation_id"] != rid:
            continue
        if b["block_start"] < block_end and block_start < b["block_end"]:
            raise ApiError("ERR_WARMUP_BLOCK_OVERLAP", 422,
                           "Warm-up block overlaps another block on this rotation")
    b = new_entity()
    b.update({
        "rotation_id": rid,
        "squad_id": squad_id,
        "apparatus": apparatus,
        "block_start": block_start,
        "block_end": block_end,
        "state": "SCHEDULED",
    })
    DB.blocks[b["id"]] = b
    run_system_transitions()
    return ok_object(ser_block(b), 201)


@bp.post("/api/v1/rotations/<rid>/warmup-blocks/generate")
def generate_blocks(rid):
    authorize(["MeetDirector"])
    rotation = get_or_404(DB.rotations, rid, "Rotation")
    created = generate_warmup_blocks(rotation)
    run_system_transitions()
    return ok_array([ser_block(b) for b in created], 201)


@bp.get("/api/v1/rotations/<rid>/warmup-blocks")
def list_rotation_blocks(rid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    get_or_404(DB.rotations, rid, "Rotation")
    items = apply_filters(
        sort_items(b for b in DB.blocks.values() if b["rotation_id"] == rid),
        {"state": ("str", "state")})
    return ok_list([ser_block(b) for b in items])


@bp.get("/api/v1/squads/<qid>/warmup-blocks")
def list_squad_blocks(qid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    get_or_404(DB.squads, qid, "Squad")
    items = sort_items(b for b in DB.blocks.values() if b["squad_id"] == qid)
    return ok_list([ser_block(b) for b in items])


@bp.get("/api/v1/warmup-blocks/<bid>")
def get_block(bid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    return ok_object(ser_block(get_or_404(DB.blocks, bid, "WarmupBlock")))


# ----------------------------------------------------------------------------
# Scores
# ----------------------------------------------------------------------------

def _check_score_posture(score_or_entry_meet):
    if score_or_entry_meet is not None and score_or_entry_meet["posture"] in (
            "FINALIZED", "ARCHIVED"):
        raise ApiError("ERR_MEET_POSTURE_FORBIDS", 409,
                       "Meet posture %s forbids score mutations"
                       % score_or_entry_meet["posture"])


@bp.post("/api/v1/athlete-entries/<eid>/scores")
def create_score(eid):
    authorize(["JudgePanelChief"])
    entry = get_or_404(DB.entries, eid, "AthleteEntry")
    data = body()
    _check_score_posture(meet_of_entry(entry))
    rotation_id = required(data, "rotation_id")
    if not isinstance(rotation_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "rotation_id must be a string")
    fk_or_404(DB.rotations, rotation_id, "rotation_id")
    apparatus = req_enum(data, "apparatus", APPARATUS)
    difficulty = score_field(required(data, "difficulty_score"), 0, 10,
                             "difficulty_score")
    execution = score_field(required(data, "execution_score"), 0, 10,
                            "execution_score")
    deduction = score_field(data.get("neutral_deduction", 0), 0, 5,
                            "neutral_deduction")
    s = new_entity()
    s.update({
        "athlete_entry_id": eid,
        "rotation_id": rotation_id,
        "apparatus": apparatus,
        "difficulty_score": difficulty,
        "execution_score": execution,
        "neutral_deduction": deduction,
        "provisional_total": None,
        "final_total": None,
        "score_state": "DRAFT",
        "published_at": None,
        "finalized_at": None,
        "is_tied": False,
        "tiebreak_rank": None,
    })
    DB.scores[s["id"]] = s
    return ok_object(ser_score(s), 201)


@bp.get("/api/v1/athlete-entries/<eid>/scores")
def list_entry_scores(eid):
    authorize(SCORE_READ)
    get_or_404(DB.entries, eid, "AthleteEntry")
    items = apply_filters(
        sort_items(s for s in DB.scores.values() if s["athlete_entry_id"] == eid),
        {"apparatus": ("str", "apparatus"), "score_state": ("str", "score_state")})
    return ok_list([ser_score(s) for s in items])


@bp.get("/api/v1/rotations/<rid>/scores")
def list_rotation_scores(rid):
    authorize(SCORE_READ)
    get_or_404(DB.rotations, rid, "Rotation")
    items = sort_items(s for s in DB.scores.values() if s["rotation_id"] == rid)
    return ok_list([ser_score(s) for s in items])


@bp.get("/api/v1/scores/<sid>")
def get_score(sid):
    authorize(SCORE_READ)
    return ok_object(ser_score(get_or_404(DB.scores, sid, "Score")))


@bp.put("/api/v1/scores/<sid>")
def amend_score(sid):
    authorize(["JudgePanelChief"])
    score = get_or_404(DB.scores, sid, "Score")
    data = body()
    _check_score_posture(meet_of_score(score))
    if score["score_state"] != "DRAFT":
        raise ApiError("ERR_SCORE_AMEND_AFTER_PUBLISH", 409,
                       "Score can only be amended while in DRAFT")
    if "difficulty_score" in data and data["difficulty_score"] is not None:
        score["difficulty_score"] = score_field(data["difficulty_score"], 0, 10,
                                                "difficulty_score")
    if "execution_score" in data and data["execution_score"] is not None:
        score["execution_score"] = score_field(data["execution_score"], 0, 10,
                                               "execution_score")
    if "neutral_deduction" in data and data["neutral_deduction"] is not None:
        score["neutral_deduction"] = score_field(data["neutral_deduction"], 0, 5,
                                                 "neutral_deduction")
    touch(score)
    return ok_object(ser_score(score))


@bp.post("/api/v1/scores/<sid>/publish")
def publish_score(sid):
    uid, _ = authorize(["JudgePanelChief"])
    score = get_or_404(DB.scores, sid, "Score")
    data = body()
    _check_score_posture(meet_of_score(score))
    # Ownership: acting judge must be CONFIRMED PANEL_CHIEF on this panel
    entry = DB.entries.get(score["athlete_entry_id"])
    session = DB.sessions.get(entry["session_id"]) if entry else None
    panel = None
    if session is not None:
        for p in DB.panels.values():
            if p["session_id"] == session["id"] \
                    and p["apparatus"] == score["apparatus"]:
                panel = p
                break
    chief_ok = panel is not None and any(
        a["judge_panel_id"] == panel["id"] and a["judge_id"] == uid
        and a["role"] == "PANEL_CHIEF" and a["assignment_state"] == "CONFIRMED"
        for a in DB.assignments.values())
    if not chief_ok:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Acting judge is not a confirmed panel chief for this "
                       "apparatus and session")
    if score["score_state"] in SCORE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Score is in terminal state %s" % score["score_state"])
    if "expected_score_version" not in data or data["expected_score_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_score_version is required")
    expected = data["expected_score_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_score_version must be an integer")
    if expected != score["version"]:
        raise ApiError("ERR_STALE_SCORE_VERSION", 412,
                       "expected_score_version does not match current version")
    if score["score_state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Score state is %s, expected DRAFT" % score["score_state"])
    rotation = DB.rotations.get(score["rotation_id"])
    if rotation is None or rotation["state"] != "OPEN_FOR_SCORING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rotation is not OPEN_FOR_SCORING")
    score["provisional_total"] = compute_provisional(
        score["difficulty_score"], score["execution_score"],
        score["neutral_deduction"])
    score["score_state"] = "PUBLISHED"
    score["published_at"] = now()
    touch(score)
    run_system_transitions()
    return ok_object(ser_score(score))


@bp.post("/api/v1/scores/<sid>/void")
def void_score(sid):
    authorize(["MeetReferee"])
    score = get_or_404(DB.scores, sid, "Score")
    _check_score_posture(meet_of_score(score))
    if score["score_state"] in SCORE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Score is in terminal state %s" % score["score_state"])
    if score["score_state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Score state is %s, expected DRAFT" % score["score_state"])
    entry = DB.entries.get(score["athlete_entry_id"])
    if entry is None or entry["entry_status"] != "SCRATCHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Score can only be voided for a SCRATCHED entry")
    score["score_state"] = "VOID"
    touch(score)
    run_system_transitions()
    return ok_object(ser_score(score))


@bp.post("/api/v1/scores/<sid>/finalize")
def finalize_score_endpoint(sid):
    authorize(["MeetReferee"])
    score = get_or_404(DB.scores, sid, "Score")
    _check_score_posture(meet_of_score(score))
    if score["score_state"] in SCORE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Score is in terminal state %s" % score["score_state"])
    if score["score_state"] != "INQUIRY_RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Score state is %s, expected INQUIRY_RESOLVED"
                       % score["score_state"])
    linked = any(iq["score_id"] == sid and iq["inquiry_state"] in
                 ("UPHELD", "DENIED") for iq in DB.inquiries.values())
    if not linked:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Linked inquiry is not UPHELD or DENIED")
    score["score_state"] = "FINAL"
    if score["final_total"] is None:
        score["final_total"] = score["provisional_total"]
    score["finalized_at"] = now()
    touch(score)
    run_system_transitions()
    return ok_object(ser_score(score))


# ----------------------------------------------------------------------------
# Inquiries
# ----------------------------------------------------------------------------

@bp.post("/api/v1/scores/<sid>/inquiries")
def file_inquiry(sid):
    authorize(["Coach"])
    score = get_or_404(DB.scores, sid, "Score")
    data = body()
    coach_id = required(data, "filed_by_coach_id")
    if not isinstance(coach_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "filed_by_coach_id must be a string")
    coach = fk_or_404(DB.coaches, coach_id, "filed_by_coach_id")
    meet = meet_of_score(score)
    _check_score_posture(meet)
    # Coach standing (business_safety) precedes the inquiry window (temporal)
    has_pass = any(p["coach_id"] == coach_id and meet is not None
                   and p["meet_id"] == meet["id"]
                   and p["pass_state"] == "FLOOR_ACCESS_GRANTED"
                   for p in DB.passes.values())
    if not has_pass:
        raise ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422,
                       "Coach does not hold floor access on this meet")
    if not (coach["background_check_expiry"] > now()
            and coach["safety_cert_expiry"] > now()):
        raise ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422,
                       "Coach background check or safety cert has lapsed")
    # Window check precedes the terminal gate: a score whose window lapsed
    # unchallenged has self-finalized, and filing on it must still report the
    # expired window rather than the terminal state.
    window = meet["inquiry_window_minutes"] if meet else 5
    if score["published_at"] is not None and now() > score["published_at"] \
            + timedelta(minutes=window):
        raise ApiError("ERR_INQUIRY_WINDOW_EXPIRED", 422,
                       "Inquiry window has expired")
    if score["score_state"] in SCORE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Score is in terminal state %s" % score["score_state"])
    if has_open_inquiry(sid):
        raise ApiError("ERR_INQUIRY_ALREADY_OPEN", 409,
                       "Another inquiry is already open on this score")
    if score["score_state"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Score state is %s, expected PUBLISHED"
                       % score["score_state"])
    iq = new_entity()
    iq.update({
        "score_id": sid,
        "filed_by_coach_id": coach_id,
        "filed_at": now(),
        "inquiry_state": "FILED",
        "resolution": None,
        "d_score_delta": Decimal("0.000"),
        "e_score_delta": Decimal("0.000"),
        "deduction_delta": Decimal("0.000"),
        "resolved_at": None,
        "resolution_reason": None,
    })
    DB.inquiries[iq["id"]] = iq
    score["score_state"] = "UNDER_INQUIRY"
    touch(score)
    return ok_object(ser_inquiry(iq), 201)


@bp.get("/api/v1/scores/<sid>/inquiries")
def list_score_inquiries(sid):
    authorize(["MeetDirector", "MeetReferee", "JudgePanelChief", "Coach"])
    get_or_404(DB.scores, sid, "Score")
    items = apply_filters(
        sort_items(i for i in DB.inquiries.values() if i["score_id"] == sid),
        {"inquiry_state": ("str", "inquiry_state")})
    return ok_list([ser_inquiry(i) for i in items])


@bp.get("/api/v1/coaches/<cid>/inquiries")
def list_coach_inquiries(cid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    get_or_404(DB.coaches, cid, "Coach")
    items = sort_items(i for i in DB.inquiries.values()
                       if i["filed_by_coach_id"] == cid)
    return ok_list([ser_inquiry(i) for i in items])


@bp.get("/api/v1/inquiries/<iid>")
def get_inquiry(iid):
    authorize(["MeetDirector", "MeetReferee", "Coach"])
    return ok_object(ser_inquiry(get_or_404(DB.inquiries, iid, "Inquiry")))


@bp.post("/api/v1/inquiries/<iid>/begin-review")
def begin_review(iid):
    authorize(["MeetReferee"])
    iq = get_or_404(DB.inquiries, iid, "Inquiry")
    if iq["inquiry_state"] in INQUIRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Inquiry is in terminal state %s" % iq["inquiry_state"])
    if iq["inquiry_state"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inquiry state is %s, expected FILED" % iq["inquiry_state"])
    iq["inquiry_state"] = "UNDER_REVIEW"
    touch(iq)
    return ok_object(ser_inquiry(iq))


@bp.post("/api/v1/inquiries/<iid>/return-to-queue")
def return_to_queue(iid):
    authorize(["MeetReferee"])
    iq = get_or_404(DB.inquiries, iid, "Inquiry")
    if iq["inquiry_state"] in INQUIRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Inquiry is in terminal state %s" % iq["inquiry_state"])
    if iq["inquiry_state"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inquiry state is %s, expected UNDER_REVIEW"
                       % iq["inquiry_state"])
    iq["inquiry_state"] = "FILED"
    touch(iq)
    return ok_object(ser_inquiry(iq))


@bp.post("/api/v1/inquiries/<iid>/resolve")
def resolve_inquiry(iid):
    authorize(["MeetReferee"])
    iq = get_or_404(DB.inquiries, iid, "Inquiry")
    data = body()
    if "expected_inquiry_version" not in data or data["expected_inquiry_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_inquiry_version is required")
    expected = data["expected_inquiry_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_inquiry_version must be an integer")
    resolution = req_enum(data, "resolution", RESOLUTIONS)
    if iq["inquiry_state"] in INQUIRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Inquiry is in terminal state %s" % iq["inquiry_state"])
    if expected != iq["version"]:
        raise ApiError("ERR_STALE_INQUIRY_VERSION", 412,
                       "expected_inquiry_version does not match current version")
    if iq["inquiry_state"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inquiry state is %s, expected UNDER_REVIEW"
                       % iq["inquiry_state"])
    d_delta = delta_field(data.get("d_score_delta", 0), -2, 2, "d_score_delta")
    e_delta = delta_field(data.get("e_score_delta", 0), -2, 2, "e_score_delta")
    n_delta = delta_field(data.get("deduction_delta", 0), -5, 0,
                          "deduction_delta")
    reason = data.get("resolution_reason")
    if reason is not None:
        if not isinstance(reason, str) or len(reason) > 512:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "resolution_reason must be a string of at most 512 "
                           "characters")
    any_delta = (d_delta != 0 or e_delta != 0 or n_delta != 0)
    if resolution == "NO_CHANGE" and any_delta:
        raise ApiError("ERR_INQUIRY_RESOLUTION_INCONSISTENT", 422,
                       "NO_CHANGE resolution requires all deltas to be zero")
    if resolution != "NO_CHANGE" and not any_delta:
        raise ApiError("ERR_INQUIRY_RESOLUTION_INCONSISTENT", 422,
                       "A non-NO_CHANGE resolution requires at least one "
                       "non-zero delta")
    score = DB.scores.get(iq["score_id"])
    iq["resolution"] = resolution
    iq["d_score_delta"] = d_delta
    iq["e_score_delta"] = e_delta
    iq["deduction_delta"] = n_delta
    iq["resolved_at"] = now()
    if resolution == "NO_CHANGE":
        iq["inquiry_state"] = "DENIED"
    else:
        iq["inquiry_state"] = "UPHELD"
    touch(iq)
    if score is not None and score["score_state"] == "UNDER_INQUIRY":
        if iq["inquiry_state"] == "UPHELD":
            new_d = score["difficulty_score"] + d_delta
            new_e = score["execution_score"] + e_delta
            new_n = score["neutral_deduction"] + n_delta
            score["difficulty_score"] = new_d
            score["execution_score"] = new_e
            score["neutral_deduction"] = new_n
            score["provisional_total"] = compute_provisional(new_d, new_e, new_n)
        score["final_total"] = score["provisional_total"]
        score["score_state"] = "INQUIRY_RESOLVED"
        touch(score)
    run_system_transitions()
    return ok_object(ser_inquiry(iq))


@bp.post("/api/v1/inquiries/<iid>/withdraw")
def withdraw_inquiry(iid):
    uid, _ = authorize(["Coach"])
    iq = get_or_404(DB.inquiries, iid, "Inquiry")
    if iq["inquiry_state"] in INQUIRY_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       "Inquiry is in terminal state %s" % iq["inquiry_state"])
    if iq["inquiry_state"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inquiry state is %s, expected FILED" % iq["inquiry_state"])
    if iq["filed_by_coach_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Only the filing coach may withdraw this inquiry")
    iq["inquiry_state"] = "WITHDRAWN"
    iq["resolved_at"] = now()
    touch(iq)
    score = DB.scores.get(iq["score_id"])
    if score is not None and score["score_state"] == "UNDER_INQUIRY":
        score["score_state"] = "PUBLISHED"
        score["final_total"] = score["provisional_total"]
        touch(score)
    run_system_transitions()
    return ok_object(ser_inquiry(iq))
