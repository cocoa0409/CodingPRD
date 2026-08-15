"""Self-audition endpoints."""
from flask import Blueprint, request

import errors
from db import DB, clock_now
from middleware import auth, json_body
from response import ok, ok_list
from services import audition_json, base_record, lazy_read_tick, paginate, sorted_rows, touch

bp = Blueprint("auditions", __name__)


def _get_audition(aid):
    a = DB["self_auditions"].get(aid)
    if a is None:
        raise errors.not_found("Self-audition not found")
    return a


def _client_gate(a, uid):
    p = DB["projects"].get(a["project_id"])
    if p is not None and p["client_id"] != uid:
        raise errors.forbidden("Audition belongs to a different client's project")
    return p


@bp.post("/projects/<pid>/self_auditions")
def submit_audition(pid):
    uid, _ = auth(["Talent"])
    p = DB["projects"].get(pid)
    if p is None:
        raise errors.not_found("Project not found")
    body = json_body()
    # priority 3: body FK existence
    tid = body.get("talent_id")
    talent = DB["talents"].get(tid) if isinstance(tid, str) else None
    if tid is not None and talent is None:
        raise errors.not_found("Talent not found")
    # priority 4: ownership
    if tid is not None and tid != uid:
        raise errors.forbidden("talent_id must equal the acting talent's X-User-ID")
    # priority 5: state
    if p["status"] != "CASTING":
        raise errors.invalid_state("Project is not in CASTING")
    # priority 10: one audition per (project, talent)
    if isinstance(tid, str) and any(
        a["project_id"] == pid and a["talent_id"] == tid for a in DB["self_auditions"].values()
    ):
        raise errors.duplicate("Talent already submitted an audition for this project")
    # priority 11: shape
    if tid is None:
        raise errors.invalid_request("Missing required field: talent_id")
    if not isinstance(body.get("audio_file_url"), str) or not body.get("audio_file_url"):
        raise errors.invalid_request("Missing required field: audio_file_url")
    slate = body.get("slate_text", "")
    if not isinstance(slate, str):
        raise errors.invalid_request("slate_text must be a string")
    rec = base_record()
    rec.update({
        "project_id": pid,
        "talent_id": tid,
        "audio_file_url": body["audio_file_url"],
        "slate_text": slate,
        "submitted_at": clock_now(),
        "status": "SUBMITTED",
    })
    DB["self_auditions"][rec["id"]] = rec
    return ok(audition_json(rec), 201)


@bp.get("/projects/<pid>/self_auditions")
def list_project_auditions(pid):
    auth(["CastingDirector", "Client"])
    lazy_read_tick()
    if DB["projects"].get(pid) is None:
        raise errors.not_found("Project not found")
    rows = [a for a in sorted_rows("self_auditions") if a["project_id"] == pid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([audition_json(a) for a in page], total, limit, offset)


@bp.get("/self_auditions")
def list_auditions():
    auth(["CastingDirector", "Client", "Talent"])
    lazy_read_tick()
    rows = sorted_rows("self_auditions")
    tid = request.args.get("talent_id")
    if tid is not None:
        rows = [a for a in rows if a["talent_id"] == tid]
    page, total, limit, offset = paginate(rows, request.args)
    return ok_list([audition_json(a) for a in page], total, limit, offset)


@bp.get("/self_auditions/<aid>")
def get_audition(aid):
    auth(["CastingDirector", "Client", "Talent"])
    lazy_read_tick()
    return ok(audition_json(_get_audition(aid)))


@bp.post("/self_auditions/<aid>/shortlist")
def shortlist(aid):
    uid, _ = auth(["Client"])
    a = _get_audition(aid)
    p = _client_gate(a, uid)
    if p is None or p["status"] != "CASTING":
        raise errors.invalid_state("Project is not in CASTING")
    if a["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED audition can be shortlisted")
    a["status"] = "SHORTLISTED"
    touch(a)
    return ok(audition_json(a))


@bp.post("/self_auditions/<aid>/reject")
def reject(aid):
    uid, _ = auth(["Client"])
    a = _get_audition(aid)
    p = _client_gate(a, uid)
    if p is None or p["status"] != "CASTING":
        raise errors.invalid_state("Project is not in CASTING")
    if a["status"] not in ("SUBMITTED", "SHORTLISTED"):
        raise errors.invalid_state("Audition is already in a terminal state")
    a["status"] = "REJECTED"
    touch(a)
    return ok(audition_json(a))
