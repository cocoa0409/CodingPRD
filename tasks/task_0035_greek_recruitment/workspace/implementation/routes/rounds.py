from __future__ import annotations

"""RecruitmentRound routes."""
from flask import Blueprint, request

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import allocator
from services import chapter_service as cs
from services import pagination as P
from services import validation as V


bp = Blueprint("rounds", __name__)


def _round_or_404(rid: str) -> dict:
    if rid not in db.rounds:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"Round {rid} not found")
    return db.rounds[rid]


@bp.route("/rush/rounds", methods=["POST"])
@require_auth(["PanhellenicAdmin"])
def create_round():
    body = request.get_json(silent=True) or {}
    cycle_label = V.require_string(body, "cycle_label", min_len=1, max_len=40)
    bid_day_at_raw = V.require_string(body, "bid_day_at")
    try:
        bid_day_at = db.parse_iso8601(bid_day_at_raw)
    except ValueError:
        raise E.APIError(E.ERR_INVALID_REQUEST, "bid_day_at must be ISO 8601 UTC")

    # cycle_label uniqueness.
    for r in db.rounds.values():
        if r["cycle_label"] == cycle_label:
            raise E.APIError(E.ERR_INVALID_REQUEST, "cycle_label must be unique")

    now = db.now_utc()
    rid = db.new_id()
    rnd = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "cycle_label": cycle_label,
        "phase": "PARTY",
        "bid_day_at": bid_day_at,
    }
    db.rounds[rid] = rnd
    return response.success_object(S.round_(rnd), status=201)


@bp.route("/rush/rounds/<round_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer", "PNM"])
def get_round(round_id):
    r = _round_or_404(round_id)
    return response.success_object(S.round_(r))


@bp.route("/rush/rounds", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer"])
def list_rounds():
    limit, offset = P.parse_limit_offset()
    phase = request.args.get("phase")
    rows = list(db.rounds.values())
    if phase is not None:
        rows = [r for r in rows if r["phase"] == phase]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.round_(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )


def _advance_party_to_mutual(rnd: dict) -> None:
    rid = rnd["id"]
    # Precondition: every Party on this round is COMPLETED or CANCELLED.
    for p in db.parties.values():
        if p["round_id"] == rid and p["status"] not in ("COMPLETED", "CANCELLED"):
            raise E.APIError(
                E.ERR_INVALID_STATE,
                "Cannot advance round while parties are not terminal",
            )

    rnd["phase"] = "MUTUAL_SELECTION"
    cs.bump_round_version(rid)

    # Side effect (a): ACTIVE PNMs with zero ATTENDED PartyInvitations -> WITHDRAWN.
    # Walk PNMs, count their ATTENDED invitations that belong to a party on this round.
    party_ids_on_round = {p["id"] for p in db.parties.values() if p["round_id"] == rid}
    for pnm in list(db.pnms.values()):
        if pnm["status"] != "ACTIVE":
            continue
        attended_on_round = any(
            inv["pnm_id"] == pnm["id"]
            and inv["rsvp_status"] == "ATTENDED"
            and inv["party_id"] in party_ids_on_round
            for inv in db.invitations.values()
        )
        if not attended_on_round:
            pnm["status"] = "WITHDRAWN"
            cs.bump_pnm_version(pnm["id"])

    # Side effect (b): expire ACTIVE RiskIncidents tied to a party on this round.
    affected_chapters: set[str] = set()
    for ri in list(db.risk_incidents.values()):
        if ri["status"] != "ACTIVE":
            continue
        if ri["party_id"] is None:
            continue
        # Must belong to a party on this round.
        party = db.parties.get(ri["party_id"])
        if party is None:
            continue
        if party["round_id"] != rid:
            continue
        ri["status"] = "EXPIRED"
        cs.bump_risk_incident_version(ri["id"])
        affected_chapters.add(ri["chapter_id"])

    for cid in affected_chapters:
        cs.recompute_risk(cid)
        cs.bump_chapter_version(cid)


def _advance_mutual_to_bid_day(rnd: dict) -> None:
    rid = rnd["id"]
    # Precondition: every chapter that has received at least one PNM_TO_CHAPTER preference
    # also has filed >= 1 CHAPTER_TO_PNM preference.
    chapters_receiving_pnm_to_chapter: set[str] = set()
    chapters_filing_chapter_to_pnm: set[str] = set()
    for pref in db.preferences.values():
        if pref["round_id"] != rid:
            continue
        if pref["side"] == "PNM_TO_CHAPTER":
            chapters_receiving_pnm_to_chapter.add(pref["chapter_id"])
        elif pref["side"] == "CHAPTER_TO_PNM":
            chapters_filing_chapter_to_pnm.add(pref["chapter_id"])
    missing = chapters_receiving_pnm_to_chapter - chapters_filing_chapter_to_pnm
    if missing:
        raise E.APIError(
            E.ERR_INVALID_STATE,
            "Some chapters received PNM_TO_CHAPTER preferences but did not file CHAPTER_TO_PNM in return",
        )

    rnd["phase"] = "BID_DAY"
    cs.bump_round_version(rid)

    # Run mutual selection allocator.
    allocator.run_mutual_selection(rid)


def _advance_bid_day_to_closed(rnd: dict) -> None:
    rid = rnd["id"]
    # Precondition: every BidMatch on this round is ACCEPTED or DECLINED.
    for b in db.bid_matches.values():
        if b["round_id"] == rid and b["status"] not in ("ACCEPTED", "DECLINED"):
            raise E.APIError(
                E.ERR_INVALID_STATE,
                "Cannot close round while some bid matches remain PROPOSED",
            )

    rnd["phase"] = "CLOSED"
    cs.bump_round_version(rid)

    # Side effect: every MATCHED PNM whose BidMatch is still PROPOSED becomes WITHDRAWN.
    # Per PRD §3.7, the precondition above guarantees no PROPOSED bids remain, but the
    # PRD specifies this safety cascade explicitly.
    for pnm in list(db.pnms.values()):
        if pnm["status"] != "MATCHED":
            continue
        pnm["status"] = "WITHDRAWN"
        pnm["matched_chapter_id"] = None
        cs.bump_pnm_version(pnm["id"])


@bp.route("/rush/rounds/<round_id>/advance", methods=["POST"])
@require_auth(["RecruitmentChair"])
def advance_round(round_id):
    rnd = _round_or_404(round_id)

    if rnd["phase"] == "PARTY":
        _advance_party_to_mutual(rnd)
    elif rnd["phase"] == "MUTUAL_SELECTION":
        _advance_mutual_to_bid_day(rnd)
    elif rnd["phase"] == "BID_DAY":
        _advance_bid_day_to_closed(rnd)
    else:
        # CLOSED is terminal
        raise E.APIError(E.ERR_INVALID_STATE, "Round is already CLOSED")

    return response.success_object(S.round_(rnd))


@bp.route("/rush/rounds/<round_id>/parties", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer", "PNM"])
def list_round_parties(round_id):
    _round_or_404(round_id)
    limit, offset = P.parse_limit_offset()
    chapter_id = request.args.get("chapter_id")
    status = request.args.get("status")
    rows = [p for p in db.parties.values() if p["round_id"] == round_id]
    if chapter_id is not None:
        rows = [p for p in rows if p["chapter_id"] == chapter_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.party(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/rounds/<round_id>/preferences", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair"])
def list_round_preferences(round_id):
    _round_or_404(round_id)
    limit, offset = P.parse_limit_offset()
    side = request.args.get("side")
    chapter_id = request.args.get("chapter_id")
    pnm_id = request.args.get("pnm_id")
    rows = [p for p in db.preferences.values() if p["round_id"] == round_id]
    if side is not None:
        rows = [p for p in rows if p["side"] == side]
    if chapter_id is not None:
        rows = [p for p in rows if p["chapter_id"] == chapter_id]
    if pnm_id is not None:
        rows = [p for p in rows if p["pnm_id"] == pnm_id]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.preference(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/rounds/<round_id>/bid-matches", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer"])
def list_round_bid_matches(round_id):
    _round_or_404(round_id)
    limit, offset = P.parse_limit_offset()
    chapter_id = request.args.get("chapter_id")
    pnm_id = request.args.get("pnm_id")
    status = request.args.get("status")
    rows = [b for b in db.bid_matches.values() if b["round_id"] == round_id]
    if chapter_id is not None:
        rows = [b for b in rows if b["chapter_id"] == chapter_id]
    if pnm_id is not None:
        rows = [b for b in rows if b["pnm_id"] == pnm_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.bid_match(b) for b in page],
        limit=limit, offset=offset, total_count=total,
    )
