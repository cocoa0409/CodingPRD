from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created, require_fields, check_enum
from services import constants as C

bp = Blueprint("interpreters", __name__)


@bp.post("/interpretation/interpreters")
def create_interpreter():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["full_name"])
    mcl = body.get("max_concurrent_load", 1)
    if not isinstance(mcl, int) or isinstance(mcl, bool) or mcl < 1:
        raise err("ERR_INVALID_REQUEST", "max_concurrent_load must be a positive integer")
    entity = db.base_fields()
    entity.update({
        "full_name": body["full_name"],
        "status": "AVAILABLE",
        "max_concurrent_load": mcl,
        "active_load": 0,
        "rating_avg": None,
        "rating_count": 0,
        "acceptance_pct": 100,
        "no_show_strikes": 0,
    })
    db.interpreters[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/interpreters/<iid>")
def get_interpreter(iid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter"})
    i = db.interpreters.get(iid)
    if not i:
        raise err("ERR_RESOURCE_NOT_FOUND", "Interpreter not found")
    return ok(i)


@bp.get("/interpretation/interpreters")
def list_interpreters():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    rows = list(db.interpreters.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/interpretation/interpreters/<iid>/status")
def set_interpreter_status(iid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Interpreter"})
    i = db.interpreters.get(iid)
    if not i:
        raise err("ERR_RESOURCE_NOT_FOUND", "Interpreter not found")
    body = get_body()
    require_fields(body, ["status"])
    check_enum(body["status"], {"AVAILABLE", "OFFLINE"}, "status")
    if role == "Interpreter" and uid != iid:
        raise err("ERR_NOT_OWNER", "Interpreter may only set own status")
    i["status"] = body["status"]
    db.touch(i)
    return ok(i)


# ===================== Certification =====================

@bp.post("/interpretation/interpreters/<iid>/certifications")
def add_certification(iid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    i = db.interpreters.get(iid)
    if not i:
        raise err("ERR_RESOURCE_NOT_FOUND", "Interpreter not found")
    body = get_body()
    require_fields(body, ["tier", "expires_at"])
    check_enum(body["tier"], C.CERT_TIERS, "tier")
    entity = db.base_fields()
    entity.update({
        "interpreter_id": iid,
        "tier": body["tier"],
        "expires_at": body["expires_at"],
        "revoked": False,
    })
    db.certifications[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/interpreters/<iid>/certifications")
def list_certifications(iid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter"})
    i = db.interpreters.get(iid)
    if not i:
        raise err("ERR_RESOURCE_NOT_FOUND", "Interpreter not found")
    rows = [c for c in db.certifications.values() if c["interpreter_id"] == iid]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/interpretation/certifications/<cid>/revoke")
def revoke_certification(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    c = db.certifications.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Certification not found")
    c["revoked"] = True
    db.touch(c)
    return ok(c)


# ===================== InterpreterLanguage (junction) =====================

@bp.post("/interpretation/interpreters/<iid>/languages")
def add_language(iid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    i = db.interpreters.get(iid)
    if not i:
        raise err("ERR_RESOURCE_NOT_FOUND", "Interpreter not found")
    body = get_body()
    require_fields(body, ["language_pair_id"])
    if db.language_pairs.get(body["language_pair_id"]) is None:
        raise err("ERR_FK_NOT_FOUND", "language_pair_id not found")
    entity = db.base_fields()
    entity.update({
        "interpreter_id": iid,
        "language_pair_id": body["language_pair_id"],
    })
    db.interpreter_languages[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/interpreters/<iid>/languages")
def list_interpreter_languages(iid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    i = db.interpreters.get(iid)
    if not i:
        raise err("ERR_RESOURCE_NOT_FOUND", "Interpreter not found")
    rows = [j for j in db.interpreter_languages.values() if j["interpreter_id"] == iid]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


@bp.get("/interpretation/interpreter-languages/<jid>")
def get_junction(jid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    j = db.interpreter_languages.get(jid)
    if not j:
        raise err("ERR_RESOURCE_NOT_FOUND", "Junction not found")
    return ok(j)


@bp.get("/interpretation/interpreter-languages")
def list_junctions():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    rows = list(db.interpreter_languages.values())
    lpid = request.args.get("language_pair_id")
    iid = request.args.get("interpreter_id")
    if lpid is not None:
        rows = [r for r in rows if r["language_pair_id"] == lpid]
    if iid is not None:
        rows = [r for r in rows if r["interpreter_id"] == iid]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)
