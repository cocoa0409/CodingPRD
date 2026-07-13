"""Artist calls, panelists, artists, submissions, scores, tabulation."""
from decimal import Decimal

from flask import Blueprint, request, g

import db
import serialize as S
from util import (
    ApiError, guard, body, ok, ok_list, new_record, touch,
    require_str, require_int, require_number, require_enum,
    parse_dt, round_half_up_2, paginate_params, sort_and_page,
)

bp = Blueprint("selection", __name__)

ALL_ROLES = {"ProgramAdmin", "Registrar", "Artist", "Panelist"}

# Composite score weights & thresholds
W_ART = Decimal("0.40")
W_FEAS = Decimal("0.25")
W_COMM = Decimal("0.20")
W_DUR = Decimal("0.15")
DURABILITY_FLOOR = Decimal("40")
TRIM_MIN = 3


def get_commission(cid):
    rec = db.commissions.get(cid)
    if rec is None:
        raise ApiError("ERR_COMMISSION_NOT_FOUND", "commission not found")
    return rec


def get_call(cid):
    rec = db.calls.get(cid)
    if rec is None:
        raise ApiError("ERR_CALL_NOT_FOUND", "call not found")
    return rec


def get_submission(sid):
    rec = db.submissions.get(sid)
    if rec is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND", "submission not found")
    return rec


def get_artist(aid):
    rec = db.artists.get(aid)
    if rec is None:
        raise ApiError("ERR_ARTIST_NOT_FOUND", "artist not found")
    return rec


def get_panelist(pid):
    rec = db.panelists.get(pid)
    if rec is None:
        raise ApiError("ERR_PANELIST_NOT_FOUND", "panelist not found")
    return rec


# ---------------------------------------------------------------------------
# ArtistCall
# ---------------------------------------------------------------------------
@bp.post("/commissions/<cid>/calls")
def create_call(cid):
    guard({"ProgramAdmin"})
    commission = get_commission(cid)
    data = body()
    call_type = require_enum(data, "call_type", {"RFQ", "RFP"})
    deadline = require_str(data, "submission_deadline")
    parse_dt(deadline)  # validate format
    quorum_min = require_int(data, "quorum_min", minimum=1)
    rec = new_record({
        "commission_id": commission["id"],
        "call_type": call_type,
        "submission_deadline": deadline,
        "quorum_min": quorum_min,
        "status": "OPEN",
    })
    db.calls[rec["id"]] = rec
    return ok(S.call(rec), 201)


@bp.get("/calls/<cid>")
def fetch_call(cid):
    guard(ALL_ROLES)
    return ok(S.call(get_call(cid)))


@bp.get("/calls")
def list_calls():
    guard(ALL_ROLES)
    commission_id = request.args.get("commission_id")
    status = request.args.get("status")
    recs = [
        c for c in db.calls.values()
        if (commission_id is None or c["commission_id"] == commission_id)
        and (status is None or c["status"] == status)
    ]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.call(c) for c in page], limit, offset, total)


@bp.post("/calls/<cid>/close")
def close_call(cid):
    guard({"ProgramAdmin"})
    call = get_call(cid)
    if call["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "call is not OPEN")
    call["status"] = "CLOSED"
    touch(call)
    return ok(S.call(call))


def _weighted_value_decimal(score):
    return (
        W_ART * Decimal(score["artistic_merit"])
        + W_FEAS * Decimal(score["feasibility"])
        + W_COMM * Decimal(score["community_impact"])
        + W_DUR * Decimal(score["durability"])
    )


@bp.post("/calls/<cid>/tabulate")
def tabulate_call(cid):
    guard({"ProgramAdmin"})
    call = get_call(cid)
    if call["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "call is not CLOSED")

    non_withdrawn = [
        s for s in db.submissions.values()
        if s["call_id"] == call["id"] and s["status"] != "WITHDRAWN"
    ]
    non_recused = [
        p for p in db.panelists.values()
        if p["call_id"] == call["id"] and not p["recused"]
    ]

    # Quorum: non-recused panelists who scored EVERY non-withdrawn submission
    def scored_all(panelist):
        for sub in non_withdrawn:
            has = any(
                sc["submission_id"] == sub["id"] and sc["panelist_id"] == panelist["id"]
                for sc in db.scores.values()
            )
            if not has:
                return False
        return True

    qualified = sum(1 for p in non_recused if scored_all(p))
    if qualified < call["quorum_min"]:
        raise ApiError("ERR_QUORUM_NOT_MET", "quorum not met for tabulation")

    non_recused_ids = {p["id"] for p in non_recused}
    call["status"] = "TABULATED"
    touch(call)

    for sub in non_withdrawn:
        if sub["status"] != "SUBMITTED":
            continue
        counted = sorted(
            [
                sc for sc in db.scores.values()
                if sc["submission_id"] == sub["id"] and sc["panelist_id"] in non_recused_ids
            ],
            key=lambda sc: sc["_seq"],
        )
        # Durability gate
        dur_mean = sum(Decimal(sc["durability"]) for sc in counted) / Decimal(len(counted))
        if dur_mean < DURABILITY_FLOOR:
            sub["composite_score"] = 0
            sub["status"] = "DISQUALIFIED"
            touch(sub)
            continue
        if len(counted) >= TRIM_MIN:
            work = list(counted)
            max_item = max(work, key=lambda sc: (sc["weighted_value"], -sc["_seq"]))
            work.remove(max_item)
            min_item = min(work, key=lambda sc: (sc["weighted_value"], sc["_seq"]))
            work.remove(min_item)
            trimmed = work
            mean_wv = sum((_weighted_value_decimal(sc) for sc in trimmed), Decimal("0")) / Decimal(len(trimmed))
        else:
            mean_wv = sum((_weighted_value_decimal(sc) for sc in counted), Decimal("0")) / Decimal(len(counted))
        sub["composite_score"] = float(round_half_up_2(mean_wv))
        sub["status"] = "SCORED"
        touch(sub)

    return ok(S.call(call))


@bp.post("/calls/<cid>/panelists")
def add_panelist(cid):
    guard({"ProgramAdmin"})
    call = get_call(cid)
    data = body()
    evaluator_name = require_str(data, "evaluator_name")
    has_conflict = False
    if data.get("has_conflict") is not None:
        v = data.get("has_conflict")
        if not isinstance(v, bool):
            raise ApiError("ERR_VALIDATION", "has_conflict must be a boolean")
        has_conflict = v
    rec = new_record({
        "call_id": call["id"],
        "evaluator_name": evaluator_name,
        "has_conflict": has_conflict,
        "recused": has_conflict,
    })
    db.panelists[rec["id"]] = rec
    return ok(S.panelist(rec), 201)


@bp.get("/calls/<cid>/panelists")
def list_panelists(cid):
    guard(ALL_ROLES)
    call = get_call(cid)
    recs = [p for p in db.panelists.values() if p["call_id"] == call["id"]]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.panelist(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Artist
# ---------------------------------------------------------------------------
@bp.post("/artists")
def create_artist():
    guard({"ProgramAdmin"})
    data = body()
    display_name = require_str(data, "display_name")
    email = require_str(data, "email")
    region = data.get("region")
    if region is not None and not isinstance(region, str):
        raise ApiError("ERR_VALIDATION", "region must be a string")
    rec = new_record({
        "display_name": display_name,
        "email": email,
        "region": region,
    })
    db.artists[rec["id"]] = rec
    return ok(S.artist(rec), 201)


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------
@bp.post("/calls/<cid>/submissions")
def create_submission(cid):
    guard({"Artist"})
    call = get_call(cid)
    data = body()
    artist_id = require_str(data, "artist_id")
    proposed = require_int(data, "proposed_budget_cents", minimum=1)
    get_artist(artist_id)  # existence -> 404
    if call["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "call is not OPEN")
    # Deadline: logical clock strictly before submission_deadline
    if db.now_dt() >= parse_dt(call["submission_deadline"]):
        raise ApiError("ERR_DEADLINE_PASSED", "submission deadline has passed")
    # At most one non-withdrawn submission per (call, artist)
    for s in db.submissions.values():
        if s["call_id"] == call["id"] and s["artist_id"] == artist_id and s["status"] != "WITHDRAWN":
            raise ApiError("ERR_DUPLICATE_SUBMISSION", "artist already has a live submission on this call")
    rec = new_record({
        "call_id": call["id"],
        "artist_id": artist_id,
        "proposed_budget_cents": proposed,
        "composite_score": None,
        "status": "SUBMITTED",
    })
    db.submissions[rec["id"]] = rec
    return ok(S.submission(rec), 201)


@bp.get("/submissions/<sid>")
def fetch_submission(sid):
    guard(ALL_ROLES)
    return ok(S.submission(get_submission(sid)))


@bp.get("/submissions")
def list_submissions():
    guard(ALL_ROLES)
    call_id = request.args.get("call_id")
    artist_id = request.args.get("artist_id")
    status = request.args.get("status")
    recs = [
        s for s in db.submissions.values()
        if (call_id is None or s["call_id"] == call_id)
        and (artist_id is None or s["artist_id"] == artist_id)
        and (status is None or s["status"] == status)
    ]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.submission(s) for s in page], limit, offset, total)


@bp.post("/submissions/<sid>/request-revision")
def request_revision(sid):
    guard({"ProgramAdmin"})
    sub = get_submission(sid)
    if sub["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "submission is not SUBMITTED")
    call = db.calls.get(sub["call_id"])
    if call is None or call["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "call is not OPEN")
    # Discard existing scores for this submission
    to_delete = [scid for scid, sc in db.scores.items() if sc["submission_id"] == sub["id"]]
    for scid in to_delete:
        del db.scores[scid]
    sub["status"] = "REVISION_REQUESTED"
    touch(sub)
    return ok(S.submission(sub))


@bp.post("/submissions/<sid>/resubmit")
def resubmit(sid):
    guard({"Artist"})
    sub = get_submission(sid)
    if sub["artist_id"] != g.user_id:
        raise ApiError("ERR_NOT_OWNER", "not the owning artist")
    if sub["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "submission is not REVISION_REQUESTED")
    call = db.calls.get(sub["call_id"])
    if call is None or call["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "call is not OPEN")
    if db.now_dt() >= parse_dt(call["submission_deadline"]):
        raise ApiError("ERR_DEADLINE_PASSED", "submission deadline has passed")
    sub["status"] = "SUBMITTED"
    touch(sub)
    return ok(S.submission(sub))


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------
@bp.post("/submissions/<sid>/scores")
def create_score(sid):
    guard({"Panelist"})
    data = body()
    # Ownership (body panelist_id vs X-User-ID) is checked before existence
    panelist_id = require_str(data, "panelist_id")
    if panelist_id != g.user_id:
        raise ApiError("ERR_NOT_OWNER", "panelist_id does not match caller identity")
    sub = get_submission(sid)
    panelist = get_panelist(panelist_id)
    artistic_merit = require_int(data, "artistic_merit", minimum=0, maximum=100)
    feasibility = require_int(data, "feasibility", minimum=0, maximum=100)
    community_impact = require_int(data, "community_impact", minimum=0, maximum=100)
    durability = require_int(data, "durability", minimum=0, maximum=100)
    # Business guards, in order: conflict then duplicate
    if panelist["recused"]:
        raise ApiError("ERR_PANELIST_CONFLICT", "recused panelist may not score")
    for sc in db.scores.values():
        if sc["submission_id"] == sub["id"] and sc["panelist_id"] == panelist_id:
            raise ApiError("ERR_DUPLICATE_SCORE", "panelist already scored this submission")
    weighted = (
        W_ART * Decimal(artistic_merit)
        + W_FEAS * Decimal(feasibility)
        + W_COMM * Decimal(community_impact)
        + W_DUR * Decimal(durability)
    )
    rec = new_record({
        "submission_id": sub["id"],
        "panelist_id": panelist_id,
        "artistic_merit": artistic_merit,
        "feasibility": feasibility,
        "community_impact": community_impact,
        "durability": durability,
        "weighted_value": float(weighted),
    })
    db.scores[rec["id"]] = rec
    return ok(S.score(rec), 201)


@bp.get("/scores/<scid>")
def fetch_score(scid):
    guard(ALL_ROLES)
    rec = db.scores.get(scid)
    if rec is None:
        raise ApiError("ERR_SCORE_NOT_FOUND", "score not found")
    return ok(S.score(rec))


@bp.get("/scores")
def list_scores():
    guard(ALL_ROLES)
    submission_id = request.args.get("submission_id")
    panelist_id = request.args.get("panelist_id")
    recs = [
        sc for sc in db.scores.values()
        if (submission_id is None or sc["submission_id"] == submission_id)
        and (panelist_id is None or sc["panelist_id"] == panelist_id)
    ]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.score(sc) for sc in page], limit, offset, total)
