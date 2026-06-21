"""BackgroundCheck endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
from db import store, now_iso
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.cascade import flag_caregiver_cascade
from services.common import base_record, touch
from services.lookup import get_background_check, get_caregiver, sorted_by_created
from services.serialize import background_check_out

bp = Blueprint("background_checks", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}
TIER_ORDER = {"NONE": 0, "BASIC": 1, "STANDARD": 2, "PREMIUM": 3}
DECISIONS = {"CLEAR", "CONSIDER", "FLAGGED"}


@bp.route("/marketplace/background-checks", methods=["POST"])
def create_check():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    body = get_json()
    caregiver_id = v.req_str(body, "caregiver_id")
    requested_tier = v.req_enum(body, "requested_tier", TIERS)
    get_caregiver(caregiver_id)  # existence

    rec = base_record()
    rec.update({
        "caregiver_id": caregiver_id,
        "requested_tier": requested_tier,
        "status": "INITIATED",
        "adjudication_note": None,
        "cleared_at_iso": None,
    })
    store.background_checks[rec["id"]] = rec
    return ok(background_check_out(rec), status=201)


@bp.route("/marketplace/background-checks/<bid>", methods=["GET"])
def get_one_check(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    b = get_background_check(bid)
    if auth.is_caregiver and auth.user_id != b["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own checks")
    return ok(background_check_out(b), status=200)


@bp.route("/marketplace/background-checks", methods=["GET"])
def list_checks():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    limit, offset = parse_pagination()
    caregiver_id = request.args.get("caregiver_id")
    status = request.args.get("status")

    items = list(store.background_checks.values())
    if auth.is_caregiver:
        items = [b for b in items if b["caregiver_id"] == auth.user_id]
    if caregiver_id is not None:
        items = [b for b in items if b["caregiver_id"] == caregiver_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([background_check_out(b) for b in page], status=200, pagination=meta)


@bp.route("/marketplace/background-checks/<bid>/start", methods=["POST"])
def start_check(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    b = get_background_check(bid)
    if b["status"] not in {"INITIATED", "CONSIDER"}:
        raise err(errors.ERR_INVALID_STATE, "Check is not INITIATED or CONSIDER")
    b["status"] = "IN_PROGRESS"
    touch(b)
    cg = get_caregiver(b["caregiver_id"])
    cg["verification_status"] = "PENDING"
    touch(cg)
    return ok(background_check_out(b), status=200)


@bp.route("/marketplace/background-checks/<bid>/adjudicate", methods=["POST"])
def adjudicate_check(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    b = get_background_check(bid)
    body = get_json()
    decision = v.req_enum(body, "decision", DECISIONS)
    note = v.opt_str(body, "adjudication_note", default=None)

    cg = get_caregiver(b["caregiver_id"])

    if decision == "CLEAR":
        if b["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "CLEAR requires IN_PROGRESS")
        b["status"] = "CLEAR"
        b["cleared_at_iso"] = now_iso()
        b["adjudication_note"] = note
        touch(b)
        cg["verification_status"] = "CLEAR"
        new_tier = b["requested_tier"]
        if TIER_ORDER[new_tier] > TIER_ORDER[cg["background_check_tier"]]:
            cg["background_check_tier"] = new_tier
        touch(cg)
    elif decision == "CONSIDER":
        if b["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "CONSIDER requires IN_PROGRESS")
        b["status"] = "CONSIDER"
        b["adjudication_note"] = note
        touch(b)
        cg["verification_status"] = "CONSIDER"
        touch(cg)
    else:  # FLAGGED
        if b["status"] not in {"IN_PROGRESS", "CONSIDER"}:
            raise err(errors.ERR_INVALID_STATE, "FLAGGED requires IN_PROGRESS or CONSIDER")
        b["status"] = "FLAGGED"
        b["adjudication_note"] = note
        touch(b)
        cg["verification_status"] = "FLAGGED"
        touch(cg)
        flag_caregiver_cascade(cg)

    return ok(background_check_out(b), status=200)
