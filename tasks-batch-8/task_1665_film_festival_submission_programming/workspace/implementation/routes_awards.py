"""Routes: jurors, awards, jury ballots, provisional standings, IRV tally,
announcement, disbursement."""

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_juror_not_on_panel,
                    err_not_found, err_phase, err_referential)
from store import DB
from util import (auth, check_ownership, created_key, get_body, get_or_404,
                  ok, paginate, require_role, v_arr, v_enum, v_int, v_str)

bp = Blueprint("awards", __name__)

AWARDS_ADMIN = ["AWARDS_ADMIN"]
JUROR_READ = ["AWARDS_ADMIN", "FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "JUROR"]
AWARD_READ = ["AWARDS_ADMIN", "FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "JUROR"]
BALLOT_READ = ["AWARDS_ADMIN", "FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR"]


# -------------------------------------------------------------------- jurors
@bp.post("/festival/jurors")
def create_juror():
    body = get_body()
    edition_id = v_str(body, "edition_id")
    display_name = v_str(body, "display_name")
    coi = v_arr(body, "coi_production_companies", required=False) or []
    uid, role = auth()
    require_role(role, AWARDS_ADMIN)
    if edition_id not in DB.editions:
        raise err_referential("Edition not found")
    rec = D.new_rec({
        "edition_id": edition_id, "display_name": display_name,
        "coi_production_companies": list(coi),
    })
    DB.jurors[rec["id"]] = rec
    return ok(D.ser_juror(rec), 201)


@bp.get("/festival/jurors/<jid>")
def get_juror(jid):
    uid, role = auth()
    require_role(role, JUROR_READ)
    rec = get_or_404(DB.jurors, jid)
    return ok(D.ser_juror(rec))


@bp.get("/festival/jurors")
def list_jurors():
    uid, role = auth()
    require_role(role, JUROR_READ)
    items = list(DB.jurors.values())
    edition_id = request.args.get("edition_id")
    if edition_id is not None:
        items = [j for j in items if j["edition_id"] == edition_id]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_juror(j) for j in page], pagination=meta)


@bp.get("/festival/jurors/<jid>/ballots")
def list_juror_ballots(jid):
    uid, role = auth()
    require_role(role, JUROR_READ)
    get_or_404(DB.jurors, jid)
    if role == "JUROR":
        check_ownership(jid == uid)
    items = [b for b in DB.ballots.values() if b["juror_id"] == jid]
    award_id = request.args.get("award_id")
    if award_id is not None:
        items = [b for b in items if b["award_id"] == award_id]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_ballot(b) for b in page], pagination=meta)


# -------------------------------------------------------------------- awards
@bp.post("/festival/awards")
def create_award():
    body = get_body()
    edition_id = v_str(body, "edition_id")
    name = v_str(body, "name")
    section = v_enum(body, "section", D.SECTIONS)
    prize_cents = v_int(body, "prize_cents", min_v=0)
    juror_ids = v_arr(body, "assigned_juror_ids")
    if not juror_ids:
        from errors import err_validation
        raise err_validation("assigned_juror_ids must contain >= 1 juror")
    uid, role = auth()
    require_role(role, AWARDS_ADMIN)
    edition = DB.editions.get(edition_id)
    if edition is None:
        raise err_referential("Edition not found")
    for jid in juror_ids:
        juror = DB.jurors.get(jid)
        if juror is None or juror["edition_id"] != edition_id:
            raise err_referential(
                "Every assigned juror must belong to this edition")
    committed = sum(a["prize_cents"] for a in DB.awards.values()
                    if a["edition_id"] == edition_id)
    if prize_cents > edition["prize_pool_cents"] - committed:
        raise err409("ERR_PRIZE_POOL_EXHAUSTED",
                     "The prize exceeds the remaining prize pool")
    rec = D.new_rec({
        "edition_id": edition_id, "name": name, "section": section,
        "prize_cents": prize_cents, "assigned_juror_ids": list(juror_ids),
        "status": "SETUP", "winner_submission_id": None, "rounds_log": [],
        "disbursed_amount_cents": 0,
    })
    DB.awards[rec["id"]] = rec
    D.recompute_edition_ledger(edition)
    return ok(D.ser_award(rec), 201)


@bp.get("/festival/awards/<aid>")
def get_award(aid):
    uid, role = auth()
    require_role(role, AWARD_READ)
    rec = get_or_404(DB.awards, aid)
    return ok(D.ser_award(rec))


@bp.get("/festival/awards")
def list_awards():
    uid, role = auth()
    require_role(role, AWARD_READ)
    items = list(DB.awards.values())
    edition_id = request.args.get("edition_id")
    status = request.args.get("status")
    winner = request.args.get("winner_submission_id")
    if edition_id is not None:
        items = [a for a in items if a["edition_id"] == edition_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if winner is not None:
        items = [a for a in items if a["winner_submission_id"] == winner]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_award(a) for a in page], pagination=meta)


@bp.post("/festival/awards/<aid>/open-voting")
def open_voting(aid):
    get_body()
    uid, role = auth()
    require_role(role, AWARDS_ADMIN)
    rec = get_or_404(DB.awards, aid)
    if rec["status"] != "SETUP":
        raise err_invalid_state("Only a SETUP award may open voting")
    edition = DB.editions.get(rec["edition_id"])
    if edition is None or edition["status"] != "FESTIVAL_LIVE":
        raise err_phase("Voting opens only during FESTIVAL_LIVE")
    rec["status"] = "VOTING_OPEN"
    D.touch(rec)
    D.recompute_edition_ledger(edition)
    return ok(D.ser_award(rec))


# ------------------------------------------------------------------- ballots
@bp.post("/festival/awards/<aid>/ballots")
def cast_ballot(aid):
    body = get_body()
    ranked = v_arr(body, "ranked_submission_ids")
    uid, role = auth()
    require_role(role, ["JUROR"])
    award = get_or_404(DB.awards, aid)
    if uid not in award["assigned_juror_ids"]:
        raise err_juror_not_on_panel()
    if award["status"] != "VOTING_OPEN":
        raise err_invalid_state("Voting is not open for this award")
    juror = DB.jurors.get(uid)
    # Conflict-of-interest discipline follows the juror.
    coi = juror["coi_production_companies"] if juror else []
    if coi:
        for sid in ranked:
            sub = DB.submissions.get(sid)
            if sub is not None and sub["production_company"] in coi:
                raise err409("ERR_JUROR_CONFLICT",
                             "Ballot ranks a conflicted production company")
    if any(b["award_id"] == aid and b["juror_id"] == uid
           for b in DB.ballots.values()):
        raise err409("ERR_BALLOT_EXISTS",
                     "This juror has already cast a ballot for this award")
    candidates = {c["id"] for c in D.award_candidates(award)}
    if (not ranked or len(set(ranked)) != len(ranked)
            or any(not isinstance(sid, str) for sid in ranked)
            or any(sid not in candidates for sid in ranked)):
        raise err409("ERR_BALLOT_INVALID",
                     "Ballot must rank only PROGRAMMED candidates of the "
                     "award's section, be non-empty, and have no duplicates")
    rec = D.new_ballot({
        "award_id": aid, "juror_id": uid,
        "ranked_submission_ids": list(ranked),
    })
    DB.ballots[rec["id"]] = rec
    return ok(D.ser_ballot(rec), 201)


@bp.get("/festival/awards/<aid>/ballots")
def list_award_ballots(aid):
    uid, role = auth()
    require_role(role, BALLOT_READ)
    get_or_404(DB.awards, aid)
    items = [b for b in DB.ballots.values() if b["award_id"] == aid]
    juror_id = request.args.get("juror_id")
    if juror_id is not None:
        items = [b for b in items if b["juror_id"] == juror_id]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_ballot(b) for b in page], pagination=meta)


@bp.get("/festival/awards/<aid>/standings")
def standings(aid):
    uid, role = auth()
    require_role(role, AWARD_READ)
    award = get_or_404(DB.awards, aid)
    candidates = D.award_candidates(award)
    counts = {c["id"]: 0 for c in candidates}
    ballots = [b for b in DB.ballots.values() if b["award_id"] == aid]
    for b in ballots:
        if b["ranked_submission_ids"]:
            first = b["ranked_submission_ids"][0]
            if first in counts:
                counts[first] += 1
    leaders = []
    if ballots and counts:
        top = max(counts.values())
        if top > 0:
            leaders = [cid for cid, k in counts.items() if k == top]
    return ok({"first_preference_counts": counts,
               "provisional_leaders": leaders})


@bp.post("/festival/awards/<aid>/tally")
def tally(aid):
    get_body()
    uid, role = auth()
    require_role(role, AWARDS_ADMIN)
    rec = get_or_404(DB.awards, aid)
    if rec["status"] != "VOTING_OPEN":
        raise err_invalid_state("Only a VOTING_OPEN award may be tallied")
    ballots = [b for b in DB.ballots.values() if b["award_id"] == aid]
    quorum = (len(rec["assigned_juror_ids"]) + 1) // 2
    if len(ballots) < quorum:
        raise err409("ERR_QUORUM_NOT_MET",
                     "Fewer than half the panel (rounded up) have voted")
    winner, rounds_log = D.irv_tally(rec)
    rec["winner_submission_id"] = winner
    rec["rounds_log"] = rounds_log
    rec["status"] = "TALLIED"
    D.touch(rec)
    edition = DB.editions.get(rec["edition_id"])
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_award(rec))


@bp.post("/festival/awards/<aid>/announce")
def announce(aid):
    get_body()
    uid, role = auth()
    require_role(role, ["FESTIVAL_DIRECTOR"])
    rec = get_or_404(DB.awards, aid)
    if rec["status"] != "TALLIED":
        raise err_invalid_state("Only a TALLIED award may be announced")
    edition = DB.editions.get(rec["edition_id"])
    if edition is None or edition["status"] != "AWARDS_NIGHT":
        raise err_phase("Awards are announced only during AWARDS_NIGHT")
    rec["status"] = "ANNOUNCED"
    D.touch(rec)
    winner = DB.submissions.get(rec["winner_submission_id"])
    if winner is not None:
        winner["award_names"].append(rec["name"])
        D.touch(winner)
    D.recompute_edition_ledger(edition)
    return ok(D.ser_award(rec))


@bp.post("/festival/awards/<aid>/disburse")
def disburse(aid):
    get_body()
    uid, role = auth()
    require_role(role, AWARDS_ADMIN)
    rec = get_or_404(DB.awards, aid)
    if rec["status"] != "ANNOUNCED":
        raise err_invalid_state("Only an ANNOUNCED award may be disbursed")
    rec["status"] = "DISBURSED"
    rec["disbursed_amount_cents"] = rec["prize_cents"]
    D.touch(rec)
    edition = DB.editions.get(rec["edition_id"])
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_award(rec))
