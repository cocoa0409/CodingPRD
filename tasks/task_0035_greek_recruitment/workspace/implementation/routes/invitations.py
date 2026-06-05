from __future__ import annotations

"""PartyInvitation routes."""
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


bp = Blueprint("invitations", __name__)


def _invitation_or_404(iid: str) -> dict:
    if iid not in db.invitations:
        raise E.APIError(E.ERR_RESOURCE_NOT_FOUND, f"Invitation {iid} not found")
    return db.invitations[iid]


@bp.route("/rush/invitations", methods=["POST"])
@require_auth(["ChapterOfficer"])
def create_invitation():
    body = request.get_json(silent=True) or {}
    party_id = V.require_string(body, "party_id")
    pnm_id = V.require_string(body, "pnm_id")

    # Priority 4: FK existence.
    if party_id not in db.parties:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"party_id {party_id} not found")
    if pnm_id not in db.pnms:
        raise E.APIError(E.ERR_REFERENCE_NOT_FOUND, f"pnm_id {pnm_id} not found")

    party = db.parties[party_id]
    pnm = db.pnms[pnm_id]

    # Officer ownership: ChapterOfficer X-User-ID == party's chapter_id.
    if g.user_role == "ChapterOfficer" and g.user_id != party["chapter_id"]:
        raise E.APIError(
            E.ERR_UNAUTHORIZED,
            "ChapterOfficer may only invite to their own chapter's parties",
        )

    # Precondition: PNM.status must be ACTIVE.
    if pnm["status"] != "ACTIVE":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"PNM is in status {pnm['status']}, cannot be invited",
        )

    # Priority 14: duplicate invitation check.
    for inv in db.invitations.values():
        if inv["party_id"] == party_id and inv["pnm_id"] == pnm_id:
            raise E.APIError(
                E.ERR_DUPLICATE_INVITATION,
                "Invitation already exists for this (party, PNM) pair",
            )

    now = db.now_utc()
    iid = db.new_id()
    inv = {
        "id": iid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_insertion_seq": db.next_insertion_seq(),
        "party_id": party_id,
        "pnm_id": pnm_id,
        "rsvp_status": "INVITED",
    }
    db.invitations[iid] = inv
    return response.success_object(S.invitation(inv), status=201)


@bp.route("/rush/invitations/<invitation_id>", methods=["GET"])
@require_auth(["PanhellenicAdmin", "ChapterOfficer", "RecruitmentChair", "PNM"])
def get_invitation(invitation_id):
    i = _invitation_or_404(invitation_id)
    return response.success_object(S.invitation(i))


@bp.route("/rush/invitations/<invitation_id>/accept", methods=["POST"])
@require_auth(["PNM"])
def accept_invitation(invitation_id):
    inv = _invitation_or_404(invitation_id)

    # Ownership: PNM may only act on their own invitations.
    if g.user_id != inv["pnm_id"]:
        raise E.APIError(E.ERR_UNAUTHORIZED, "PNM may only act on their own invitations")

    if inv["rsvp_status"] != "INVITED":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"Invitation rsvp_status is {inv['rsvp_status']}, cannot accept",
        )

    party = db.parties[inv["party_id"]]
    if party["status"] != "OPEN":
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"Party status is {party['status']}, RSVP only allowed while OPEN",
        )

    if party["confirmed_count"] >= party["capacity"]:
        raise E.APIError(E.ERR_INVALID_STATE, "Party is at capacity")

    # Priority 8: party time conflict on the PNM's schedule.
    new_start = party["scheduled_start_utc"]
    new_end = new_start + timedelta(minutes=party["duration_minutes"])
    for other in db.invitations.values():
        if other["id"] == inv["id"]:
            continue
        if other["pnm_id"] != inv["pnm_id"]:
            continue
        if other["rsvp_status"] != "ACCEPTED":
            continue
        other_party = db.parties[other["party_id"]]
        o_start = other_party["scheduled_start_utc"]
        o_end = o_start + timedelta(minutes=other_party["duration_minutes"])
        # Half-open [start, end); adjacency at gap=0 is allowed.
        if new_start < o_end and o_start < new_end:
            raise E.APIError(
                E.ERR_PARTY_TIME_CONFLICT,
                "Party time overlaps another ACCEPTED invitation",
            )

    inv["rsvp_status"] = "ACCEPTED"
    cs.bump_invitation_version(inv["id"])
    cs.recompute_party_confirmed_count(party["id"])
    cs.bump_party_version(party["id"])

    return response.success_object(S.invitation(inv))


@bp.route("/rush/invitations/<invitation_id>/decline", methods=["POST"])
@require_auth(["PNM"])
def decline_invitation(invitation_id):
    inv = _invitation_or_404(invitation_id)

    if g.user_id != inv["pnm_id"]:
        raise E.APIError(E.ERR_UNAUTHORIZED, "PNM may only act on their own invitations")

    if inv["rsvp_status"] not in ("INVITED", "ACCEPTED"):
        raise E.APIError(
            E.ERR_INVALID_STATE,
            f"Invitation rsvp_status is {inv['rsvp_status']}, cannot decline",
        )

    was_accepted = inv["rsvp_status"] == "ACCEPTED"
    if was_accepted:
        # Underlying party must be SCHEDULED or OPEN.
        party = db.parties[inv["party_id"]]
        if party["status"] not in ("SCHEDULED", "OPEN"):
            raise E.APIError(
                E.ERR_INVALID_STATE,
                f"Cannot decline ACCEPTED invite once party is {party['status']}",
            )

    inv["rsvp_status"] = "DECLINED"
    cs.bump_invitation_version(inv["id"])

    if was_accepted:
        cs.recompute_party_confirmed_count(inv["party_id"])
        cs.bump_party_version(inv["party_id"])

    return response.success_object(S.invitation(inv))
