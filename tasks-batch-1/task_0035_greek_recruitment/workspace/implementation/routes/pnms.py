from __future__ import annotations

"""PNM routes."""
from flask import Blueprint, request

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import chapter_service as cs
from services import pagination as P
from services import validation as V


bp = Blueprint("pnms", __name__)


PNM_STATUSES = {"REGISTERED", "ACTIVE", "MATCHED", "WITHDRAWN", "BID_ACCEPTED", "BID_DECLINED"}


def _pnm_or_404(pnm_id: str) -> dict:
    if pnm_id not in db.pnms:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"PNM {pnm_id} not found")
    return db.pnms[pnm_id]


def _chapter_or_404(cid: str) -> dict:
    if cid not in db.chapters:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"Chapter {cid} not found")
    return db.chapters[cid]


@bp.route("/rush/pnms/register", methods=["POST"])
@require_auth(["Anonymous", "PNM", "PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "RiskOfficer"])
def register_pnm():
    # Public endpoint per PRD §2.1: Anonymous allowed.
    body = request.get_json(silent=True) or {}

    full_name = V.require_string(body, "full_name", min_len=1, max_len=120)
    gpa = V.require_number(body, "gpa", min_val=0.00, max_val=4.00)
    legacy_chapter_id = V.optional_string(body, "legacy_chapter_id")

    # FK existence check on legacy_chapter_id (priority 4).
    if legacy_chapter_id is not None and legacy_chapter_id not in db.chapters:
        raise E.APIError(
            E.ERR_REFERENCE_NOT_FOUND,
            f"legacy_chapter_id {legacy_chapter_id} not found",
        )

    now = db.now_utc()
    pid = db.new_id()
    pnm = {
        "id": pid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "full_name": full_name,
        "gpa": gpa,
        "legacy_chapter_id": legacy_chapter_id,
        "is_legacy": legacy_chapter_id is not None,
        "status": "REGISTERED",
        "matched_chapter_id": None,
    }
    db.pnms[pid] = pnm
    return response.success_object(S.pnm(pnm), status=201)


@bp.route("/rush/pnms/<pnm_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def get_pnm(pnm_id):
    p = _pnm_or_404(pnm_id)
    return response.success_object(S.pnm(p))


@bp.route("/rush/pnms", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer"])
def list_pnms():
    limit, offset = P.parse_limit_offset()
    status = request.args.get("status")
    legacy_chapter_id = request.args.get("legacy_chapter_id")
    matched_chapter_id = request.args.get("matched_chapter_id")
    rows = list(db.pnms.values())
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if legacy_chapter_id is not None:
        rows = [p for p in rows if p["legacy_chapter_id"] == legacy_chapter_id]
    if matched_chapter_id is not None:
        rows = [p for p in rows if p["matched_chapter_id"] == matched_chapter_id]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.pnm(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/pnms/<pnm_id>/activate", methods=["POST"])
@require_auth(["RecruitmentChair"])
def activate_pnm(pnm_id):
    p = _pnm_or_404(pnm_id)
    if p["status"] != "REGISTERED":
        raise E.APIError(E.ERR_INVALID_STATE, f"PNM is in status {p['status']}, cannot activate")
    if p["gpa"] < 2.50:
        raise E.APIError(E.ERR_GPA_BELOW_MINIMUM, "PNM gpa below 2.50")
    p["status"] = "ACTIVE"
    cs.bump_pnm_version(pnm_id)
    return response.success_object(S.pnm(p))


@bp.route("/rush/pnms/<pnm_id>/withdraw", methods=["POST"])
@require_auth(["PNM"])
def withdraw_pnm(pnm_id):
    p = _pnm_or_404(pnm_id)
    # Ownership: PNM can only withdraw themselves.
    from flask import g
    if g.user_id != pnm_id:
        raise E.APIError(E.ERR_UNAUTHORIZED, "PNM may only withdraw themselves")

    if p["status"] != "ACTIVE":
        raise E.APIError(E.ERR_INVALID_STATE, f"PNM is in status {p['status']}, cannot withdraw")

    p["status"] = "WITHDRAWN"
    cs.bump_pnm_version(pnm_id)

    # Cascade: every PartyInvitation on this PNM with rsvp_status IN {INVITED, ACCEPTED} -> DECLINED.
    for inv in db.invitations.values():
        if inv["pnm_id"] == pnm_id and inv["rsvp_status"] in ("INVITED", "ACCEPTED"):
            was_accepted = inv["rsvp_status"] == "ACCEPTED"
            inv["rsvp_status"] = "DECLINED"
            cs.bump_invitation_version(inv["id"])
            if was_accepted:
                # Decrement that party's confirmed_count.
                cs.recompute_party_confirmed_count(inv["party_id"])
                cs.bump_party_version(inv["party_id"])

    return response.success_object(S.pnm(p))


@bp.route("/rush/pnms/<pnm_id>/invitations", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def list_pnm_invitations(pnm_id):
    _pnm_or_404(pnm_id)
    limit, offset = P.parse_limit_offset()
    rsvp = request.args.get("rsvp_status")
    rows = [i for i in db.invitations.values() if i["pnm_id"] == pnm_id]
    if rsvp is not None:
        rows = [i for i in rows if i["rsvp_status"] == rsvp]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.invitation(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/pnms/<pnm_id>/preferences", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def list_pnm_preferences(pnm_id):
    _pnm_or_404(pnm_id)
    limit, offset = P.parse_limit_offset()
    side = request.args.get("side")
    round_id = request.args.get("round_id")
    rows = [p for p in db.preferences.values() if p["pnm_id"] == pnm_id]
    if side is not None:
        rows = [p for p in rows if p["side"] == side]
    if round_id is not None:
        rows = [p for p in rows if p["round_id"] == round_id]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.preference(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/pnms/<pnm_id>/bid-matches", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RecruitmentChair", "ChapterOfficer", "PNM"])
def list_pnm_bid_matches(pnm_id):
    _pnm_or_404(pnm_id)
    limit, offset = P.parse_limit_offset()
    status = request.args.get("status")
    rows = [b for b in db.bid_matches.values() if b["pnm_id"] == pnm_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.bid_match(b) for b in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/pnms/legacy-of/<chapter_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair"])
def list_legacy_pnms(chapter_id):
    _chapter_or_404(chapter_id)
    limit, offset = P.parse_limit_offset()
    rows = [p for p in db.pnms.values() if p["legacy_chapter_id"] == chapter_id]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.pnm(p) for p in page],
        limit=limit, offset=offset, total_count=total,
    )
