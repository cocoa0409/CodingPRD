"""Submission intake / review and SelfTape endpoints."""
from flask import Blueprint, request

import db
from errors import (err_channel_forbidden, err_deadline_passed,
                    err_invalid_request, err_invalid_state, err_not_found,
                    err_ref_not_found, err_stale_version, err_tape_too_long,
                    err_unauthorized)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_int, check_string, filter_status, get_payload,
                  logical_now, new_record, paginate, serialize, touch)

S = db.STORE
bp = Blueprint("submissions", __name__)

RELEASED = ("RELEASED_AGENT_ONLY", "RELEASED_OPEN")
READ_ROLES = ("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")


def _get_submission(sid):
    s = domain.find("submissions", sid)
    if s is None:
        raise err_not_found("Submission not found")
    return s


def _get_breakdown(bid):
    b = domain.find("breakdowns", bid)
    if b is None:
        raise err_not_found("Breakdown not found")
    return b


# ---------------------------------------------------------------------------
# Submission intake
# ---------------------------------------------------------------------------

@bp.post("/casting/breakdowns/<bid>/submissions")
def create_submission(bid):
    user_id, role = require_roles("Agent", "CastingAssociate")
    bd = _get_breakdown(bid)
    body = get_payload()

    # Body FK existence (pipeline step 4)
    talent = None
    if body.get("talent_id") is not None:
        talent = domain.find("talents", body.get("talent_id"))
        if talent is None:
            raise err_ref_not_found("talent_id does not reference a Talent")
    agent = None
    if body.get("agent_id") is not None:
        agent = domain.find("agents", body.get("agent_id"))
        if agent is None:
            raise err_ref_not_found("agent_id does not reference an AgentProfile")

    # State-machine legality (step 5)
    if bd["status"] not in RELEASED:
        raise err_invalid_state("Breakdown must be released to accept submissions")

    # OCC on Breakdown.version (step 6)
    expected = body.get("expected_breakdown_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != bd["version"]:
            raise err_stale_version("expected_breakdown_version does not match the breakdown version")

    # Deadline gate (business, step 7 order per PRD 3.3)
    if not logical_now() < bd["submission_deadline"]:
        raise err_deadline_passed()

    # Distribution gate
    agent_id = body.get("agent_id")
    if bd["distribution"] == "AGENT_ONLY":
        if agent is None or agent["franchise_status"] != "FRANCHISED" or not agent["active"]:
            raise err_channel_forbidden()

    # Required-field validation (step 8, deliberately last)
    check_string(body, "talent_id")
    if agent_id is not None:
        check_string(body, "agent_id", required=False)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_breakdown_version is required and must be an integer")

    # Duplicate detection: earlier active submission for same (breakdown, talent)
    # is persisted as auto-REJECTED with duplicate_of_id (still HTTP 201).
    duplicate_of = None
    for s in S["submissions"].values():
        if s["breakdown_id"] == bid and s["talent_id"] == talent["id"] \
                and s["status"] not in ("REJECTED", "WITHDRAWN", "NOT_BOOKED"):
            duplicate_of = s
            break

    rec = new_record({
        "breakdown_id": bid,
        "talent_id": talent["id"],
        "agent_id": agent_id,
        "submitted_via": "AGENT" if agent_id is not None else "SELF",
        "status": "REJECTED" if duplicate_of is not None else "SUBMITTED",
        "duplicate_of_id": duplicate_of["id"] if duplicate_of is not None else None,
        "reviewed_at": None,
    })
    S["submissions"][rec["id"]] = rec
    domain.recompute_submission_count(bd, bump=True)
    return success_object(serialize(rec), 201)


@bp.get("/casting/submissions/<sid>")
def get_submission(sid):
    require_roles(*READ_ROLES)
    return success_object(serialize(_get_submission(sid)))


@bp.get("/casting/breakdowns/<bid>/submissions")
def list_breakdown_submissions(bid):
    require_roles(*READ_ROLES)
    _get_breakdown(bid)
    records = filter_status(domain.children("submissions", "breakdown_id", bid))
    tid = request.args.get("talent_id")
    if tid is not None:
        records = [r for r in records if r.get("talent_id") == tid]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/submissions")
def list_submissions():
    require_roles(*READ_ROLES)
    records = filter_status(S["submissions"].values())
    for param in ("talent_id", "agent_id", "breakdown_id", "duplicate_of_id"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(param) == v]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------

@bp.post("/casting/submissions/<sid>/start-review")
def start_review(sid):
    require_roles("CastingAssociate")
    sub = _get_submission(sid)
    bd = domain.find("breakdowns", sub["breakdown_id"])
    if sub["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED submission can enter review")
    if bd is None or bd["status"] not in RELEASED:
        raise err_invalid_state("Parent breakdown must remain released to start review")
    sub["status"] = "UNDER_REVIEW"
    sub["reviewed_at"] = logical_now()
    touch(sub)
    return success_object(serialize(sub))


@bp.post("/casting/submissions/<sid>/shortlist")
def shortlist(sid):
    require_roles("CastingAssociate")
    sub = _get_submission(sid)
    if sub["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW submission can be shortlisted")
    sub["status"] = "SHORTLISTED"
    touch(sub)
    return success_object(serialize(sub))


@bp.post("/casting/submissions/<sid>/reject")
def reject(sid):
    require_roles("CastingAssociate")
    sub = _get_submission(sid)
    if sub["status"] not in ("UNDER_REVIEW", "SHORTLISTED"):
        raise err_invalid_state("Only UNDER_REVIEW or SHORTLISTED submissions can be rejected")
    sub["status"] = "REJECTED"
    touch(sub)
    domain.release_active_holds_on_submission(sid)
    return success_object(serialize(sub))


@bp.post("/casting/submissions/<sid>/withdraw")
def withdraw(sid):
    user_id, role = require_roles("Agent", "CastingAssociate")
    sub = _get_submission(sid)
    if role == "Agent":
        if sub.get("agent_id") != user_id:
            raise err_unauthorized("Only the submitting agent may withdraw this submission")
    else:  # CastingAssociate: self-submission path only
        if sub.get("agent_id") is not None:
            raise err_unauthorized("CastingAssociate may withdraw only self-submissions")
    if sub["status"] not in ("SUBMITTED", "UNDER_REVIEW", "SHORTLISTED"):
        raise err_invalid_state("Submission cannot be withdrawn from its current state")
    sub["status"] = "WITHDRAWN"
    touch(sub)
    domain.release_active_holds_on_submission(sid)
    bd = domain.find("breakdowns", sub["breakdown_id"])
    if bd is not None:
        domain.recompute_submission_count(bd, bump=True)
    return success_object(serialize(sub))


# ---------------------------------------------------------------------------
# Self tapes
# ---------------------------------------------------------------------------

@bp.post("/casting/submissions/<sid>/self-tapes")
def create_self_tape(sid):
    require_roles("Agent", "CastingAssociate")
    sub = _get_submission(sid)
    body = get_payload()
    duration = body.get("duration_seconds")
    if isinstance(duration, int) and not isinstance(duration, bool):
        if duration <= 0 or duration > 600:
            raise err_tape_too_long()
    check_string(body, "media_url")
    if not isinstance(duration, int) or isinstance(duration, bool):
        raise err_invalid_request("duration_seconds is required and must be an integer")
    existing = domain.children("self_tapes", "submission_id", sid)
    rec = new_record({
        "submission_id": sid,
        "media_url": body["media_url"],
        "duration_seconds": duration,
        "tape_index": len(existing) + 1,
        "status": "RECEIVED",
    })
    S["self_tapes"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


def _get_tape(tid):
    t = domain.find("self_tapes", tid)
    if t is None:
        raise err_not_found("SelfTape not found")
    return t


TAPE_READ_ROLES = ("CastingDirector", "CastingAssociate", "Agent")


@bp.get("/casting/self-tapes/<tid>")
def get_self_tape(tid):
    require_roles(*TAPE_READ_ROLES)
    return success_object(serialize(_get_tape(tid)))


@bp.get("/casting/submissions/<sid>/self-tapes")
def list_self_tapes(sid):
    require_roles(*TAPE_READ_ROLES)
    _get_submission(sid)
    records = filter_status(domain.children("self_tapes", "submission_id", sid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/self-tapes/<tid>/accept")
def accept_tape(tid):
    require_roles("CastingAssociate")
    t = _get_tape(tid)
    if t["status"] != "RECEIVED":
        raise err_invalid_state("Only a RECEIVED self-tape can be accepted")
    sub = domain.find("submissions", t["submission_id"])
    if sub is not None and sub["status"] in ("REJECTED", "WITHDRAWN", "NOT_BOOKED"):
        raise err_invalid_state("Cannot accept a tape on a dead submission")
    t["status"] = "ACCEPTED"
    touch(t)
    return success_object(serialize(t))


@bp.post("/casting/self-tapes/<tid>/reject")
def reject_tape(tid):
    require_roles("CastingAssociate")
    t = _get_tape(tid)
    if t["status"] != "RECEIVED":
        raise err_invalid_state("Only a RECEIVED self-tape can be rejected")
    t["status"] = "REJECTED"
    touch(t)
    return success_object(serialize(t))
