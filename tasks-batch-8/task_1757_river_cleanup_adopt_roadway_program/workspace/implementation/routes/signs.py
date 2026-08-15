"""SignRecognition endpoints (PRD 3.8): request, list, install."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_SIGN_NOT_FOUND,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_SIGN_NOT_REQUESTED,
    ERR_SIGN_ALREADY_EXISTS,
    ERR_NO_COMPLETED_CLEANUP,
)
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object, success_list
from routes.helpers import get_pagination
from services.core import stamp_new, touch, public, signs_of_agreement
from util import CLOCK
from validate import get_body, req_str, require_resource

bp = Blueprint("signs", __name__)

SIGN_TEXT_MAX = 60


@bp.post("/program/agreements/<aid>/signs")
def request_sign(aid):
    caller = get_caller()
    check_role(caller, [LEADER])
    agreement = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    check_ownership(caller, agreement["group_id"])
    body = get_body()
    sign_text = req_str(body, "sign_text")
    if len(sign_text) > SIGN_TEXT_MAX:
        raise_error(ERR_INVALID_REQUEST, "sign_text must be between 1 and 60 characters")
    # family 6: the agreement must be ACTIVE
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "sign requests require an ACTIVE agreement")
    # family 9: at most one live (REQUESTED or INSTALLED) sign per agreement
    if any(s["status"] in ("REQUESTED", "INSTALLED") for s in signs_of_agreement(aid)):
        raise_error(ERR_SIGN_ALREADY_EXISTS,
                    "agreement already has a live recognition sign")
    rec = stamp_new({
        "agreement_id": aid,
        "sign_text": sign_text,
        "status": "REQUESTED",
        "installed_date": None,
    })
    db["signs"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/agreements/<aid>/signs")
def list_signs(aid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    agreement = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    check_ownership(caller, agreement["group_id"])
    items = signs_of_agreement(aid)
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/program/signs/<sid>/install")
def install_sign(sid):
    caller = get_caller()
    check_role(caller, [COORD])
    rec = require_resource("signs", sid, ERR_SIGN_NOT_FOUND)
    get_body()
    # family 6: sign state, then agreement state
    if rec["status"] != "REQUESTED":
        raise_error(ERR_SIGN_NOT_REQUESTED, "sign is not REQUESTED")
    agreement = db["agreements"].get(rec["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "sign installation requires an ACTIVE agreement")
    # family 9: installation is earned by at least one COMPLETED cleanup
    if not any(e["agreement_id"] == rec["agreement_id"] and e["status"] == "COMPLETED"
               for e in db["events"].values()):
        raise_error(ERR_NO_COMPLETED_CLEANUP,
                    "no COMPLETED cleanup exists under the agreement")
    rec["status"] = "INSTALLED"
    rec["installed_date"] = CLOCK.today().isoformat()
    touch(rec)
    return success_object(public(rec))
