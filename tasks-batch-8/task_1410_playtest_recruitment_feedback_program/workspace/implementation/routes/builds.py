"""Game build & access key endpoints."""

from datetime import timedelta

import db
from db import _format_iso, _parse_iso
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_int, optional_int,
    stamp_new, touch, mint_key_code,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_INVALID_REQUEST, ERR_BUILD_NOT_RELEASED, ERR_NDA_NOT_SIGNED,
    ERR_KEY_QUOTA_EXCEEDED, ERR_DUPLICATE_KEY, ERR_KEY_EXPIRED,
)
from services.serializers import public
from services.cascade import write_exposure, revoke_key_cascade

bp = make_blueprint("builds")


def _get_build(bid):
    b = db.builds.get(bid)
    if b is None:
        raise_error(ERR_NOT_FOUND, "Build not found")
    return b


def _get_key(kid):
    k = db.access_keys.get(kid)
    if k is None:
        raise_error(ERR_NOT_FOUND, "Access key not found")
    return k


@bp.route("/playtests/builds", methods=["POST"])
def create_build():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    study_id = require_string(body, "study_id")
    build_label = require_string(body, "build_label")
    max_keys = require_int(body, "max_keys", minimum=1)
    key_ttl_hours = optional_int(body, "key_ttl_hours", default=72, minimum=1)
    if study_id not in db.studies:
        raise_error(ERR_NOT_FOUND, "Study not found")
    for b in db.builds.values():
        if b["study_id"] == study_id and b["build_label"] == build_label:
            raise_error(ERR_INVALID_REQUEST, "build_label must be unique per study")
    rec = {
        "study_id": study_id,
        "build_label": build_label,
        "max_keys": max_keys,
        "key_ttl_hours": key_ttl_hours,
        "status": "STAGED",
        "released_at": None,
        "keys_active_count": 0,
    }
    stamp_new(rec)
    db.builds[rec["id"]] = rec
    return success(public(rec, "build"), status=201)


@bp.route("/playtests/builds", methods=["GET"])
def list_builds():
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.builds.values())
    for param in ("study_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if str(b.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(b, "build") for b in page], status=200, pagination=pagination)


@bp.route("/playtests/builds/<bid>", methods=["GET"])
def get_build(bid):
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator", "Participant")
    b = _get_build(bid)
    return success(public(b, "build"), status=200)


@bp.route("/playtests/builds/<bid>/release", methods=["POST"])
def release_build(bid):
    require_roles("ResearchOpsAdmin")
    b = _get_build(bid)
    if b["status"] != "STAGED":
        raise_error(ERR_INVALID_STATE, "Build must be STAGED to release")
    study = db.studies.get(b["study_id"])
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    if study["status"] not in ("RECRUITING", "CLOSED", "ANALYSIS"):
        raise_error(ERR_INVALID_STATE, "Study must be RECRUITING, CLOSED, or ANALYSIS")
    b["status"] = "RELEASED"
    b["released_at"] = db.clock.now_iso()
    touch(b)
    return success(public(b, "build"), status=200)


@bp.route("/playtests/builds/<bid>/retire", methods=["POST"])
def retire_build(bid):
    require_roles("ResearchOpsAdmin")
    b = _get_build(bid)
    if b["status"] != "RELEASED":
        raise_error(ERR_INVALID_STATE, "Build must be RELEASED to retire")
    b["status"] = "RETIRED"
    touch(b)
    # Revoke every ISSUED key of this build (REDEEMED untouched)
    for key in list(db.access_keys.values()):
        if key["build_id"] == b["id"] and key["status"] == "ISSUED":
            revoke_key_cascade(key)
    return success(public(b, "build"), status=200)


# ---------------------------------------------------------------------------
# Access keys
# ---------------------------------------------------------------------------

@bp.route("/playtests/access-keys", methods=["POST"])
def issue_key():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    build_id = require_string(body, "build_id")
    participant_id = require_string(body, "participant_id")

    # Existence (body FKs, in order)
    build = db.builds.get(build_id)
    if build is None:
        raise_error(ERR_NOT_FOUND, "Build not found")
    participant = db.participants.get(participant_id)
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    # Referential gate: build must be RELEASED
    if build["status"] != "RELEASED":
        raise_error(ERR_BUILD_NOT_RELEASED, "Build is not RELEASED")

    # Safety gate (outranks quota): SIGNED signature on the study's current
    # PUBLISHED agreement.
    published = None
    for a in db.nda_agreements.values():
        if a["study_id"] == build["study_id"] and a["status"] == "PUBLISHED":
            published = a
            break
    signed = False
    if published is not None:
        for sig in db.nda_signatures.values():
            if (sig["agreement_id"] == published["id"]
                    and sig["participant_id"] == participant["id"]
                    and sig["status"] == "SIGNED"):
                signed = True
                break
    if not signed:
        raise_error(ERR_NDA_NOT_SIGNED,
                    "No SIGNED signature on the study's current PUBLISHED agreement")

    # Capacity (PRD 3.4 order): keys_active_count strictly below max_keys
    if build.get("keys_active_count", 0) >= build["max_keys"]:
        raise_error(ERR_KEY_QUOTA_EXCEEDED, "Key quota exhausted for this build")

    # Uniqueness: one active key per (build, participant)
    for k in db.access_keys.values():
        if (k["build_id"] == build["id"] and k["participant_id"] == participant["id"]
                and k["status"] in ("ISSUED", "REDEEMED")):
            raise_error(ERR_DUPLICATE_KEY, "An active key already exists for this build and participant")

    # Mint the key — ensure unique key_code
    while True:
        code = mint_key_code()
        if not any(k["key_code"] == code for k in db.access_keys.values()):
            break
    expires = db.clock.now() + timedelta(hours=build["key_ttl_hours"])
    rec = {
        "build_id": build["id"],
        "participant_id": participant["id"],
        "key_code": code,
        "status": "ISSUED",
        "expires_at": _format_iso(expires),
        "redeemed_at": None,
    }
    stamp_new(rec)
    db.access_keys[rec["id"]] = rec
    build["keys_active_count"] = build.get("keys_active_count", 0) + 1
    touch(build)
    write_exposure(participant["id"], build["id"], build["study_id"], "KEY_ISSUED")
    return success(public(rec, "access_key"), status=201)


@bp.route("/playtests/access-keys", methods=["GET"])
def list_keys():
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel", "Participant")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.access_keys.values())
    for param in ("build_id", "participant_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [k for k in items if str(k.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(k, "access_key") for k in page], status=200, pagination=pagination)


@bp.route("/playtests/access-keys/<kid>", methods=["GET"])
def get_key(kid):
    require_roles("ResearchOpsAdmin", "Researcher", "LegalCounsel", "Participant")
    k = _get_key(kid)
    return success(public(k, "access_key"), status=200)


@bp.route("/playtests/access-keys/<kid>/redeem", methods=["POST"])
def redeem_key(kid):
    user_id, _role = require_roles("Participant")
    k = _get_key(kid)
    if user_id != k["participant_id"]:
        raise_error(ERR_FORBIDDEN, "Only the key's participant may redeem it")
    if k["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE, "Key must be ISSUED to redeem")
    now = db.clock.now()
    if now >= _parse_iso(k["expires_at"]):
        raise_error(ERR_KEY_EXPIRED, "Key has expired")
    k["status"] = "REDEEMED"
    k["redeemed_at"] = _format_iso(now)
    touch(k)
    build = db.builds.get(k["build_id"])
    write_exposure(k["participant_id"], k["build_id"],
                   build["study_id"] if build else None, "KEY_REDEEMED")
    return success(public(k, "access_key"), status=200)


@bp.route("/playtests/access-keys/<kid>/revoke", methods=["POST"])
def revoke_key(kid):
    require_roles("ResearchOpsAdmin", "LegalCounsel")
    k = _get_key(kid)
    if k["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE, "Key must be ISSUED to revoke")
    revoke_key_cascade(k)
    return success(public(k, "access_key"), status=200)
