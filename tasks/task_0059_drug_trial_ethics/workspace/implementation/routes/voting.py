from __future__ import annotations

"""Attendance, vote, resolve endpoints."""

from flask import Blueprint, g, request

import db
from clock import iso
from errors import (
    ERR_DUPLICATE_VOTE,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MEMBER_RECUSED,
    ERR_NOT_FOUND,
    ERR_QUORUM_NOT_MET,
    raise_error,
)
from middleware import require_role
from response import success_object
from serializers import serialize_attendance, serialize_resolution, serialize_vote
import services_state as svc
from validation import (
    check_version,
    get_json_body,
    require_enum,
)


bp = Blueprint("voting", __name__)

VOTE_MODES = {"APPROVE", "APPROVE_WITH_MODIFICATION", "REJECT", "DEFER"}


def _require_active_member(member_id: str) -> dict:
    m = db.committee_members.get(member_id)
    if not m:
        raise_error(ERR_FORBIDDEN, "Caller is not a known committee member")
    return m


# ---------------------------------------------------------------------------
# POST /ethics/agenda-items/{id}/attendance
# ---------------------------------------------------------------------------
@bp.post("/ethics/agenda-items/<iid>/attendance")
def confirm_attendance(iid):
    require_role({"CommitteeMember"})
    it = db.agenda_items.get(iid)
    if not it:
        raise_error(ERR_NOT_FOUND, f"AgendaItem {iid} not found")
    member = _require_active_member(g.user_id)

    with db.lock:
        # Conflict gate (priority 8) BEFORE state legality (priority 7)?
        # Per scaffold: priority 7 (state) < priority 8 (recusal) numerically; but
        # the note says recusal beats state, so check recusal first.
        if svc.member_has_active_conflict(member["id"], it["application_id"]):
            raise_error(ERR_MEMBER_RECUSED,
                        "Member has an active conflict for this application")
        if it["status"] != "OPEN_FOR_VOTING":
            raise_error(ERR_INVALID_STATE,
                        f"Agenda item is not open for voting (state={it['status']})")
        # Prevent double-confirm by same member on same item
        for a in db.attendance_confirmations.values():
            if a["agenda_item_id"] == iid and a["member_id"] == member["id"]:
                raise_error(ERR_INVALID_STATE, "Attendance already confirmed for this member")

        att = svc.new_append_only({
            "agenda_item_id": iid,
            "member_id": member["id"],
            "confirmed_at": iso(),
        })
        db.attendance_confirmations[att["id"]] = att
    return success_object(serialize_attendance(att), 201)


# ---------------------------------------------------------------------------
# POST /ethics/agenda-items/{id}/votes
# ---------------------------------------------------------------------------
@bp.post("/ethics/agenda-items/<iid>/votes")
def cast_vote(iid):
    require_role({"CommitteeMember"})
    it = db.agenda_items.get(iid)
    if not it:
        raise_error(ERR_NOT_FOUND, f"AgendaItem {iid} not found")
    member = _require_active_member(g.user_id)
    body = get_json_body()
    vote_mode = require_enum(body, "vote_mode", VOTE_MODES)

    with db.lock:
        # Conflict gate BEFORE state check
        if svc.member_has_active_conflict(member["id"], it["application_id"]):
            raise_error(ERR_MEMBER_RECUSED,
                        "Member has an active conflict for this application")
        if it["status"] != "OPEN_FOR_VOTING":
            raise_error(ERR_INVALID_STATE,
                        f"Agenda item is not open for voting (state={it['status']})")
        # Duplicate vote prevention
        for v in db.votes.values():
            if v["agenda_item_id"] == iid and v["member_id"] == member["id"]:
                raise_error(ERR_DUPLICATE_VOTE,
                            "Member has already voted on this agenda item")

        vote = svc.new_append_only({
            "agenda_item_id": iid,
            "member_id": member["id"],
            "vote_mode": vote_mode,
        })
        db.votes[vote["id"]] = vote
        # Bump agenda item version so a concurrent resolve fails OCC
        svc.bump(it)
    return success_object(serialize_vote(vote), 201)


# ---------------------------------------------------------------------------
# POST /ethics/agenda-items/{id}/resolve
# ---------------------------------------------------------------------------
@bp.post("/ethics/agenda-items/<iid>/resolve")
def resolve_item(iid):
    require_role({"Chairperson"})
    it = db.agenda_items.get(iid)
    if not it:
        raise_error(ERR_NOT_FOUND, f"AgendaItem {iid} not found")

    body = get_json_body()
    # require_quorum is query param
    rq_raw = request.args.get("require_quorum", "false")
    require_quorum = str(rq_raw).lower() in ("true", "1", "yes")

    with db.lock:
        if it["status"] != "OPEN_FOR_VOTING":
            raise_error(ERR_INVALID_STATE,
                        f"Agenda item is not open for voting (state={it['status']})")

        check_version(body, it)

        # Filter recused votes — per scaffold, recusal exclusion is applied at
        # publication. But for safety we exclude any votes from members who
        # currently have an active conflict for the application (defensive).
        all_votes = [v for v in db.votes.values() if v["agenda_item_id"] == iid]
        votes_for_tally = [v for v in all_votes
                           if not svc.member_has_active_conflict(v["member_id"],
                                                                 it["application_id"])]

        outcome, tally = svc.tally_outcome(
            votes_for_tally,
            quorum_required=it["quorum_required"],
            eligible_voter_count=it["eligible_voter_count"],
        )

        if outcome == "NO_QUORUM" and require_quorum:
            raise_error(ERR_QUORUM_NOT_MET,
                        "Quorum was not met for this agenda item")

        # Create resolution
        res = svc.new_versioned({
            "agenda_item_id": iid,
            "application_id": it["application_id"],
            "outcome": outcome,
            "tally": tally,
            "document_uri": "",  # set after id known
            "pinned_submission_version": it.get("pinned_submission_version"),
        })
        res["document_uri"] = f"/ethics/resolutions/{res['id']}/document.pdf"
        db.resolutions[res["id"]] = res

        # Agenda item state
        if outcome == "NO_QUORUM":
            it["status"] = "CLOSED_WITHOUT_QUORUM"
        else:
            it["status"] = "RESOLVED"
        svc.bump(it)

        # Cascade Application
        app = db.applications.get(it["application_id"])
        annual_report_id = it.get("annual_report_id")
        rectification_id = it.get("rectification_id")

        # Audit: REVIEW_DECISION row first
        svc.write_audit(g.user_role, g.user_id, "REVIEW_DECISION",
                        "AgendaItem", it["id"],
                        {"outcome": outcome, "tally": tally,
                         "resolution_id": res["id"],
                         "application_id": it["application_id"]})

        if app:
            review_kind = it["review_kind"]
            if review_kind in ("INITIAL_REVIEW",):
                svc.cascade_initial_review(app, it, res, g.user_role, g.user_id)
            elif review_kind == "SECONDARY_REVIEW":
                rec = db.rectifications.get(rectification_id) if rectification_id else None
                if rec:
                    svc.cascade_secondary_review(app, it, res, rec, g.user_role, g.user_id)
                else:
                    svc.cascade_initial_review(app, it, res, g.user_role, g.user_id)
            elif review_kind in ("ANNUAL_REVIEW", "AMENDMENT_REVIEW", "FINAL_REPORT_REVIEW"):
                ar = db.annual_reports.get(annual_report_id) if annual_report_id else None
                if ar:
                    svc.cascade_continuing_review(app, it, res, ar, g.user_role, g.user_id)

    return success_object(serialize_resolution(res))


# ---------------------------------------------------------------------------
# GET /ethics/resolutions/{id}
# ---------------------------------------------------------------------------
@bp.get("/ethics/resolutions/<rid>")
def get_resolution(rid):
    require_role({"Secretary", "Chairperson", "CommitteeMember", "Applicant", "RegulatoryWatcher"})
    r = db.resolutions.get(rid)
    if not r:
        raise_error(ERR_NOT_FOUND, f"Resolution {rid} not found")
    if g.user_role == "Applicant":
        app = db.applications.get(r["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "Applicant may not read this resolution")
    return success_object(serialize_resolution(r))
