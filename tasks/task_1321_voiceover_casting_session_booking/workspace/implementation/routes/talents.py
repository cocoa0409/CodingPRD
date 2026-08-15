"""Talent roster endpoints."""
from flask import Blueprint

import errors
from db import DB
from middleware import auth, json_body
from response import ok, ok_list
from services import (
    ROSTER_STATUSES, UNION_STATUSES, VOICE_PROFILES,
    base_record, lazy_read_tick, paginate, sorted_rows, talent_json, touch,
)

bp = Blueprint("talents", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@bp.post("/talents")
def create_talent():
    auth(["CastingDirector"])
    body = json_body()
    # priority 10: uniqueness (before shape, priority 11)
    email = body.get("email")
    if isinstance(email, str) and any(t["email"] == email for t in DB["talents"].values()):
        raise errors.duplicate("Talent email already registered")
    # priority 11: shape
    for field in ("stage_name", "email", "voice_profile", "languages", "union_status", "base_session_fee_cents"):
        if body.get(field) is None:
            raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(body["stage_name"], str) or not isinstance(body["email"], str):
        raise errors.invalid_request("stage_name and email must be strings")
    if body["voice_profile"] not in VOICE_PROFILES:
        raise errors.invalid_request("Invalid voice_profile")
    if body["union_status"] not in UNION_STATUSES:
        raise errors.invalid_request("Invalid union_status")
    if not isinstance(body["languages"], list) or not all(isinstance(x, str) for x in body["languages"]):
        raise errors.invalid_request("languages must be a list of ISO 639-1 codes")
    if not _is_int(body["base_session_fee_cents"]):
        raise errors.invalid_request("base_session_fee_cents must be an integer")
    rec = base_record()
    rec.update({
        "stage_name": body["stage_name"],
        "email": body["email"],
        "voice_profile": body["voice_profile"],
        "languages": list(body["languages"]),
        "union_status": body["union_status"],
        "base_session_fee_cents": body["base_session_fee_cents"],
        "roster_status": "ACTIVE",
    })
    DB["talents"][rec["id"]] = rec
    return ok(talent_json(rec), 201)


@bp.get("/talents")
def list_talents():
    auth(["CastingDirector", "Client"])
    lazy_read_tick()
    rows = sorted_rows("talents")
    vp = request_arg("voice_profile")
    us = request_arg("union_status")
    rs = request_arg("roster_status")
    if vp is not None:
        rows = [t for t in rows if t["voice_profile"] == vp]
    if us is not None:
        rows = [t for t in rows if t["union_status"] == us]
    if rs is not None:
        rows = [t for t in rows if t["roster_status"] == rs]
    page, total, limit, offset = paginate(rows, request_args())
    return ok_list([talent_json(t) for t in page], total, limit, offset)


def request_arg(name):
    from flask import request
    return request.args.get(name)


def request_args():
    from flask import request
    return request.args


@bp.get("/talents/<tid>")
def get_talent(tid):
    auth(["CastingDirector", "Client", "Talent", "Agent"])
    lazy_read_tick()
    rec = DB["talents"].get(tid)
    if rec is None:
        raise errors.not_found("Talent not found")
    return ok(talent_json(rec))


@bp.put("/talents/<tid>")
def update_talent(tid):
    auth(["CastingDirector"])
    rec = DB["talents"].get(tid)
    if rec is None:
        raise errors.not_found("Talent not found")
    body = json_body()
    # OCC (scaffold §1.2.1): expected_talent_version is required on this endpoint.
    expected = body.get("expected_talent_version")
    if expected is None:
        raise errors.invalid_request("expected_talent_version is required")
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        raise errors.invalid_request("expected_talent_version must be an integer")
    if expected != rec["version"]:
        raise errors.stale_version("Talent version has advanced since last read")
    if "stage_name" in body and body["stage_name"] is not None:
        if not isinstance(body["stage_name"], str):
            raise errors.invalid_request("stage_name must be a string")
        rec["stage_name"] = body["stage_name"]
    if "base_session_fee_cents" in body and body["base_session_fee_cents"] is not None:
        if not _is_int(body["base_session_fee_cents"]):
            raise errors.invalid_request("base_session_fee_cents must be an integer")
        rec["base_session_fee_cents"] = body["base_session_fee_cents"]
    if "roster_status" in body and body["roster_status"] is not None:
        if body["roster_status"] not in ROSTER_STATUSES:
            raise errors.invalid_request("Invalid roster_status")
        rec["roster_status"] = body["roster_status"]
    touch(rec)
    return ok(talent_json(rec))


@bp.get("/talents/<tid>/conflict_exclusions")
def list_talent_conflicts(tid):
    auth(["CastingDirector", "Client", "Talent", "Agent"])
    lazy_read_tick()
    rec = DB["talents"].get(tid)
    if rec is None:
        raise errors.not_found("Talent not found")
    from services import conflict_json
    rows = [ce for ce in sorted_rows("conflict_exclusions") if ce["talent_id"] == tid]
    page, total, limit, offset = paginate(rows, request_args())
    return ok_list([conflict_json(ce) for ce in page], total, limit, offset)
