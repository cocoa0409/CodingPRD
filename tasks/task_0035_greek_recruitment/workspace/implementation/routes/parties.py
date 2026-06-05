from __future__ import annotations

"""Party routes."""
from datetime import timedelta

from flask import Blueprint, request, g

import db
import errors as E
import response
import serializers as S
from middleware import require_auth
from services import chapter_service as cs
from services import pagination as P
from services import validation as V


bp = Blueprint("parties", __name__)


def _party_or_404(pid: str) -> dict:
    if pid not in db.parties:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"Party {pid} not found")
    return db.parties[pid]


def _intervals_overlap(start_a, dur_a_min, start_b, dur_b_min) -> bool:
    """Half-open intervals [start, start+duration). Adjacency (gap == 0) is NOT overlap."""
    end_a = start_a + timedelta(minutes=dur_a_min)
    end_b = start_b + timedelta(minutes=dur_b_min)
    return start_a < end_b and start_b < end_a


@bp.route("/rush/parties", methods=["POST"])
@require_auth(["ChapterOfficer"])
def create_party():
    body = request.get_json(silent=True) or {}

    # Per priority order: existence (path) -> existence (FK) -> state -> ... -> business gates.
    round_id = V.require_string(body, "round_id")
    chapter_id = V.require_string(body, "chapter_id")
    sched_raw = V.require_string(body, "scheduled_start_utc")
    duration = V.require_int(body, "duration_minutes", min_val=30, max_val=240)
    capacity = V.require_int(body, "capacity", min_val=1)

    try:
        sched_start = db.parse_iso8601(sched_raw)
    except ValueError:
        raise E.APIError(E.ERR_INVALID_REQUEST, "scheduled_start_utc must be ISO 8601 UTC")

    # FK existence (priority 4).
    if round_id not in db.rounds:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"round_id {round_id} not found")
    if chapter_id not in db.chapters:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"chapter_id {chapter_id} not found")

    chapter = db.chapters[chapter_id]
    rnd = db.rounds[round_id]

    # Priority 6 (OCC) — not applicable on this endpoint per scaffold.
    # Priority 7: chapter suspension safety gate (dominates fiscal gates).
    if chapter["risk_status"] == "SUSPENDED":
        raise E.APIError(E.ERR_CHAPTER_SUSPENDED, "Chapter is suspended; cannot host parties")

    # Priority 9: same-chapter double-book check.
    for p in db.parties.values():
        if p["chapter_id"] != chapter_id:
            continue
        if p["status"] == "CANCELLED":
            # Cancelled parties don't block scheduling.
            continue
        if _intervals_overlap(sched_start, duration, p["scheduled_start_utc"], p["duration_minutes"]):
            raise E.APIError(
                E.ERR_CHAPTER_DOUBLE_BOOK,
                "Same-chapter party overlaps an existing party",
            )

    # Priority 12: round.phase must be PARTY.
    if rnd["phase"] != "PARTY":
        raise E.APIError(
            E.ERR_ROUND_PHASE_MISMATCH,
            f"Round phase is {rnd['phase']}, expected PARTY",
        )

    # Officer ownership: ChapterOfficer X-User-ID must be the hosting chapter.
    if g.user_role == "ChapterOfficer" and g.user_id != chapter_id:
        raise E.APIError(
            E.ERR_UNAUTHORIZED,
            "ChapterOfficer may only schedule parties for their own chapter",
        )

    now = db.now_utc()
    pid = db.new_id()
    party = {
        "id": pid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "round_id": round_id,
        "chapter_id": chapter_id,
        "scheduled_start_utc": sched_start,
        "duration_minutes": duration,
        "capacity": capacity,
        "confirmed_count": 0,
        "status": "SCHEDULED",
    }
    db.parties[pid] = party
    return response.success_object(S.party(party), status=201)


@bp.route("/rush/parties/<party_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "RiskOfficer", "PNM"])
def get_party(party_id):
    p = _party_or_404(party_id)
    return response.success_object(S.party(p))


def _ownership_check_chapter_officer(party: dict) -> None:
    if g.user_role == "ChapterOfficer" and g.user_id != party["chapter_id"]:
        raise E.APIError(
            E.ERR_UNAUTHORIZED,
            "ChapterOfficer may only act on their own chapter's parties",
        )


@bp.route("/rush/parties/<party_id>/open", methods=["POST"])
@require_auth(["ChapterOfficer"])
def open_party(party_id):
    party = _party_or_404(party_id)
    _ownership_check_chapter_officer(party)

    if party["status"] != "SCHEDULED":
        raise E.APIError(E.ERR_INVALID_STATE, f"Party is in status {party['status']}, cannot open")

    chapter = db.chapters[party["chapter_id"]]
    if chapter["risk_status"] == "SUSPENDED":
        # Per PRD §3.2: the opening precondition fails with ERR_INVALID_STATE here,
        # because the precondition is on the transition itself.
        raise E.APIError(
            E.ERR_INVALID_STATE,
            "Chapter has been suspended; party cannot open",
        )

    rnd = db.rounds[party["round_id"]]
    if rnd["phase"] != "PARTY":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"Round phase is {rnd['phase']}, expected PARTY",
        )

    party["status"] = "OPEN"
    cs.bump_party_version(party_id)
    return response.success_object(S.party(party))


@bp.route("/rush/parties/<party_id>/complete", methods=["POST"])
@require_auth(["ChapterOfficer"])
def complete_party(party_id):
    party = _party_or_404(party_id)
    _ownership_check_chapter_officer(party)

    if party["status"] != "OPEN":
        raise E.APIError(E.ERR_INVALID_STATE, f"Party is in status {party['status']}, cannot complete")

    party["status"] = "COMPLETED"
    cs.bump_party_version(party_id)

    # Cascade: ACCEPTED -> ATTENDED, INVITED -> NO_SHOW.
    for inv in db.invitations.values():
        if inv["party_id"] != party_id:
            continue
        if inv["rsvp_status"] == "ACCEPTED":
            inv["rsvp_status"] = "ATTENDED"
            cs.bump_invitation_version(inv["id"])
        elif inv["rsvp_status"] == "INVITED":
            inv["rsvp_status"] = "NO_SHOW"
            cs.bump_invitation_version(inv["id"])

    # confirmed_count is computed from ACCEPTED; after complete there are 0 ACCEPTED.
    cs.recompute_party_confirmed_count(party_id)

    return response.success_object(S.party(party))


@bp.route("/rush/parties/<party_id>/cancel", methods=["POST"])
@require_auth(["ChapterOfficer"])
def cancel_party(party_id):
    party = _party_or_404(party_id)
    _ownership_check_chapter_officer(party)

    if party["status"] not in ("SCHEDULED", "OPEN"):
        raise E.APIError(E.ERR_INVALID_STATE, f"Party is in status {party['status']}, cannot cancel")

    party["status"] = "CANCELLED"
    cs.bump_party_version(party_id)

    # Cascade: every non-terminal invitation -> DECLINED.
    for inv in db.invitations.values():
        if inv["party_id"] != party_id:
            continue
        if inv["rsvp_status"] in ("INVITED", "ACCEPTED"):
            inv["rsvp_status"] = "DECLINED"
            cs.bump_invitation_version(inv["id"])

    cs.recompute_party_confirmed_count(party_id)

    return response.success_object(S.party(party))


@bp.route("/rush/parties/<party_id>/invitations", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "PNM"])
def list_party_invitations(party_id):
    _party_or_404(party_id)
    limit, offset = P.parse_limit_offset()
    rsvp = request.args.get("rsvp_status")
    rows = [i for i in db.invitations.values() if i["party_id"] == party_id]
    if rsvp is not None:
        rows = [i for i in rows if i["rsvp_status"] == rsvp]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.invitation(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.route("/rush/parties/<party_id>/risk-incidents", methods=["GET"])
@require_auth(["PanhellenicAdmin", "RiskOfficer"])
def list_party_risk_incidents(party_id):
    _party_or_404(party_id)
    limit, offset = P.parse_limit_offset()
    status = request.args.get("status")
    rows = [r for r in db.risk_incidents.values() if r["party_id"] == party_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = P.sort_by_created_at(rows)
    page, total = P.slice_page(rows, limit, offset)
    return response.success_array(
        [S.risk_incident(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )
