from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created, require_fields, check_enum
from services import constants as C

bp = Blueprint("catalog", __name__)


# ===================== ClientAccount =====================

@bp.post("/interpretation/clients")
def create_client():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["org_name", "org_type", "contact_email"])
    check_enum(body["org_type"], C.ORG_TYPES, "org_type")
    credit = body.get("credit_limit_cents", 5000000)
    if not isinstance(credit, int) or isinstance(credit, bool):
        raise err("ERR_INVALID_REQUEST", "credit_limit_cents must be an integer")
    entity = db.base_fields()
    entity.update({
        "org_name": body["org_name"],
        "org_type": body["org_type"],
        "contact_email": body["contact_email"],
        "status": "ACTIVE",
        "credit_limit_cents": credit,
        "outstanding_balance_cents": 0,
    })
    db.clients[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/clients/<cid>")
def get_client(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "ClientAccount", "CoordinatorOps"})
    c = db.clients.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Client not found")
    return ok(c)


@bp.post("/interpretation/clients/<cid>/suspend")
def suspend_client(cid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    c = db.clients.get(cid)
    if not c:
        raise err("ERR_RESOURCE_NOT_FOUND", "Client not found")
    c["status"] = "SUSPENDED"
    db.touch(c)
    return ok(c)


# ===================== RatePlan =====================

@bp.post("/interpretation/rate-plans")
def create_rate_plan():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["client_id", "certification_tier", "modality", "billing_mode", "rate_cents"])
    if db.clients.get(body["client_id"]) is None:
        raise err("ERR_FK_NOT_FOUND", "client_id not found")
    check_enum(body["certification_tier"], C.CERT_TIERS, "certification_tier")
    check_enum(body["modality"], C.MODALITIES, "modality")
    check_enum(body["billing_mode"], C.BILLING_MODES, "billing_mode")
    rate_cents = body["rate_cents"]
    if not isinstance(rate_cents, int) or isinstance(rate_cents, bool):
        raise err("ERR_INVALID_REQUEST", "rate_cents must be an integer")
    min_block = body.get("min_block_units", 10)
    if not isinstance(min_block, int) or isinstance(min_block, bool):
        raise err("ERR_INVALID_REQUEST", "min_block_units must be an integer")
    surcharge = body.get("travel_surcharge_cents", 0)
    if not isinstance(surcharge, int) or isinstance(surcharge, bool):
        raise err("ERR_INVALID_REQUEST", "travel_surcharge_cents must be an integer")
    if body["modality"] != "ONSITE" and surcharge != 0:
        raise err("ERR_INVALID_REQUEST", "travel_surcharge_cents must be 0 for non-ONSITE")
    # supersede prior active row for same key
    for rp in db.rate_plans.values():
        if (rp["client_id"] == body["client_id"]
                and rp["certification_tier"] == body["certification_tier"]
                and rp["modality"] == body["modality"] and rp["active"]):
            rp["active"] = False
            db.touch(rp)
    entity = db.base_fields()
    entity.update({
        "client_id": body["client_id"],
        "certification_tier": body["certification_tier"],
        "modality": body["modality"],
        "billing_mode": body["billing_mode"],
        "rate_cents": rate_cents,
        "min_block_units": min_block,
        "travel_surcharge_cents": surcharge,
        "active": True,
    })
    db.rate_plans[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/rate-plans/<rid>")
def get_rate_plan(rid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    rp = db.rate_plans.get(rid)
    if not rp:
        raise err("ERR_RESOURCE_NOT_FOUND", "Rate plan not found")
    return ok(rp)


@bp.get("/interpretation/rate-plans")
def list_rate_plans():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps"})
    from flask import request
    rows = list(db.rate_plans.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


# ===================== LanguagePair =====================

@bp.post("/interpretation/language-pairs")
def create_language_pair():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["source_lang", "target_lang"])
    rare = body.get("rare", False)
    if not isinstance(rare, bool):
        raise err("ERR_INVALID_REQUEST", "rare must be a boolean")
    entity = db.base_fields()
    entity.update({
        "source_lang": body["source_lang"],
        "target_lang": body["target_lang"],
        "rare": rare,
    })
    db.language_pairs[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/language-pairs/<lid>")
def get_language_pair(lid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "Interpreter"})
    lp = db.language_pairs.get(lid)
    if not lp:
        raise err("ERR_RESOURCE_NOT_FOUND", "Language pair not found")
    return ok(lp)
