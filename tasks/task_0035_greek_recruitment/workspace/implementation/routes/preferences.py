from __future__ import annotations

"""Preference routes."""
from flask import Blueprint, request, g

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import pagination as P
from services import validation as V


bp = Blueprint("preferences", __name__)


SIDES = {"PNM_TO_CHAPTER", "CHAPTER_TO_PNM"}


def _preference_or_404(pid: str) -> dict:
    if pid not in db.preferences:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"Preference {pid} not found")
    return db.preferences[pid]


@bp.route("/rush/preferences", methods=["POST"])
@require_auth(["PNM", "ChapterOfficer"])
def create_preference():
    body = request.get_json(silent=True) or {}
    round_id = V.require_string(body, "round_id")
    side = V.require_enum(body, "side", SIDES)
    pnm_id = V.require_string(body, "pnm_id")
    chapter_id = V.require_string(body, "chapter_id")
    rank = V.require_int(body, "rank", min_val=1)

    # Priority 4: FK existence.
    if round_id not in db.rounds:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"round_id {round_id} not found")
    if pnm_id not in db.pnms:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"pnm_id {pnm_id} not found")
    if chapter_id not in db.chapters:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"chapter_id {chapter_id} not found")

    rnd = db.rounds[round_id]
    pnm = db.pnms[pnm_id]

    # Role-side restriction (per PRD §3.4): PNM may only file PNM_TO_CHAPTER;
    # ChapterOfficer may only file CHAPTER_TO_PNM. Authorship belongs at
    # role auth layer (priority 2).
    if g.user_role == "PNM":
        if side != "PNM_TO_CHAPTER":
            raise E.APIError(
                E.ERR_UNAUTHORIZED,
                "PNM may only file PNM_TO_CHAPTER preferences",
            )
        if g.user_id != pnm_id:
            raise E.APIError(
                E.ERR_UNAUTHORIZED,
                "PNM may only file preferences for themselves",
            )
    elif g.user_role == "ChapterOfficer":
        if side != "CHAPTER_TO_PNM":
            raise E.APIError(
                E.ERR_UNAUTHORIZED,
                "ChapterOfficer may only file CHAPTER_TO_PNM preferences",
            )
        if g.user_id != chapter_id:
            raise E.APIError(
                E.ERR_UNAUTHORIZED,
                "ChapterOfficer may only file preferences for their own chapter",
            )

    # Priority 10: eligibility.
    if side == "PNM_TO_CHAPTER":
        if pnm["status"] != "ACTIVE":
            raise E.APIError(
                E.ERR_PREFERENCE_NOT_ELIGIBLE,
                "PNM must be ACTIVE to file PNM_TO_CHAPTER preference",
            )
    elif side == "CHAPTER_TO_PNM":
        if pnm["status"] != "ACTIVE":
            raise E.APIError(
                E.ERR_PREFERENCE_NOT_ELIGIBLE,
                "Target PNM must be ACTIVE for CHAPTER_TO_PNM preference",
            )
        # Must have at least one ATTENDED invitation on a party hosted by this chapter in this round.
        has_attended = False
        for inv in db.invitations.values():
            if inv["pnm_id"] != pnm_id:
                continue
            if inv["rsvp_status"] != "ATTENDED":
                continue
            party = db.parties.get(inv["party_id"])
            if party is None:
                continue
            if party["round_id"] == round_id and party["chapter_id"] == chapter_id:
                has_attended = True
                break
        if not has_attended:
            raise E.APIError(
                E.ERR_PREFERENCE_NOT_ELIGIBLE,
                "Target PNM has no ATTENDED invitation on this chapter in this round",
            )

    # Priority 11: (round_id, side, ranker, rank) uniqueness.
    ranker_id = pnm_id if side == "PNM_TO_CHAPTER" else chapter_id
    for existing in db.preferences.values():
        if existing["round_id"] != round_id:
            continue
        if existing["side"] != side:
            continue
        existing_ranker = existing["pnm_id"] if side == "PNM_TO_CHAPTER" else existing["chapter_id"]
        if existing_ranker != ranker_id:
            continue
        if existing["rank"] == rank:
            raise E.APIError(
                E.ERR_PREFERENCE_RANK_TAKEN,
                f"Rank {rank} already filed",
            )

    # Priority 12: round phase must be MUTUAL_SELECTION.
    if rnd["phase"] != "MUTUAL_SELECTION":
        raise E.APIError(
            E.ERR_ROUND_PHASE_MISMATCH,
            f"Round phase is {rnd['phase']}, expected MUTUAL_SELECTION",
        )

    now = db.now_utc()
    pid = db.new_id()
    pref = {
        "id": pid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "round_id": round_id,
        "side": side,
        "pnm_id": pnm_id,
        "chapter_id": chapter_id,
        "rank": rank,
    }
    db.preferences[pid] = pref
    return response.success_object(S.preference(pref), status=201)


@bp.route("/rush/preferences/<preference_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def get_preference(preference_id):
    p = _preference_or_404(preference_id)
    return response.success_object(S.preference(p))
