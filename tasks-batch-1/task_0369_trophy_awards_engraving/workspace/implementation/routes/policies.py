from flask import Blueprint
from db import db
from errors import err
from response import ok
from middleware import authenticate, require_role
from services import serialize
from services.common import (
    get_json_body, stamp_create, require_fields, is_str, is_int, is_bool, is_number,
)

bp = Blueprint("policies", __name__)


# ----- RushPolicy -----

@bp.route("/rush-policies", methods=["POST"])
def create_rush_policy():
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    body = get_json_body()
    require_fields(body, ["name", "expedited_surcharge_pct", "rush_surcharge_pct"])
    name = body["name"]
    if not is_str(name):
        raise err("ERR_INVALID_REQUEST", "name must be a string")
    exp = body["expedited_surcharge_pct"]
    rush = body["rush_surcharge_pct"]
    std = body.get("standard_surcharge_pct", 0)
    rmbd = body.get("rush_min_business_days", 1)
    active = body.get("active", True)
    for f, v in (("expedited_surcharge_pct", exp), ("rush_surcharge_pct", rush),
                 ("standard_surcharge_pct", std)):
        if not is_number(v):
            raise err("ERR_INVALID_REQUEST", f"{f} must be a number")
    if not is_int(rmbd) or rmbd < 1:
        raise err("ERR_INVALID_REQUEST", "rush_min_business_days must be an integer >= 1")
    if not is_bool(active):
        raise err("ERR_INVALID_REQUEST", "active must be a boolean")
    # Semantic validation: surcharge pcts must be >= 0
    if exp < 0 or rush < 0 or std < 0:
        raise err("ERR_VALIDATION", "surcharge percentages must be >= 0")

    rec = {
        "name": name,
        "standard_surcharge_pct": std,
        "expedited_surcharge_pct": exp,
        "rush_surcharge_pct": rush,
        "rush_min_business_days": rmbd,
        "active": active,
    }
    stamp_create(rec)
    db.rush_policies[rec["id"]] = rec
    if active:
        for p in db.rush_policies.values():
            if p["id"] != rec["id"] and p.get("active"):
                p["active"] = False
    return ok(serialize.rush_policy(rec), 201)


@bp.route("/rush-policies/<pid>", methods=["GET"])
def get_rush_policy(pid):
    caller = authenticate()
    require_role(caller, ("ShopStaff", "ShopManager"))
    rec = db.rush_policies.get(pid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Rush policy not found")
    return ok(serialize.rush_policy(rec))


# ----- PromoCode -----

@bp.route("/promo-codes", methods=["POST"])
def create_promo():
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    body = get_json_body()
    require_fields(body, ["code", "kind"])
    code = body["code"]
    kind = body["kind"]
    if not is_str(code) or not code.strip():
        raise err("ERR_INVALID_REQUEST", "code must be a non-empty string")
    if kind not in ("PERCENT", "FLAT"):
        raise err("ERR_INVALID_REQUEST", "kind must be PERCENT or FLAT")
    percent_off = body.get("percent_off")
    flat_off_cents = body.get("flat_off_cents")
    min_subtotal = body.get("min_subtotal_cents", 0)
    max_uses = body.get("max_uses")
    active = body.get("active", True)

    if percent_off is not None and not is_number(percent_off):
        raise err("ERR_INVALID_REQUEST", "percent_off must be a number")
    if flat_off_cents is not None and not is_int(flat_off_cents):
        raise err("ERR_INVALID_REQUEST", "flat_off_cents must be an integer")
    if not is_int(min_subtotal) or min_subtotal < 0:
        raise err("ERR_INVALID_REQUEST", "min_subtotal_cents must be an integer >= 0")
    if max_uses is not None and (not is_int(max_uses) or max_uses < 0):
        raise err("ERR_INVALID_REQUEST", "max_uses must be an integer >= 0 or null")
    if not is_bool(active):
        raise err("ERR_INVALID_REQUEST", "active must be a boolean")

    # Semantic validation (well-typed but invalid)
    if kind == "PERCENT":
        if percent_off is None or not (0 < percent_off <= 1):
            raise err("ERR_VALIDATION", "PERCENT promo requires percent_off in (0, 1]")
    else:  # FLAT
        if flat_off_cents is None or flat_off_cents <= 0:
            raise err("ERR_VALIDATION", "FLAT promo requires flat_off_cents > 0")

    # unique uppercase code
    if code != code.upper():
        raise err("ERR_VALIDATION", "code must be uppercase")
    for p in db.promo_codes.values():
        if p["code"] == code:
            raise err("ERR_DUPLICATE_VALUE", "A promo code with this code already exists")

    rec = {
        "code": code,
        "kind": kind,
        "percent_off": percent_off,
        "flat_off_cents": flat_off_cents,
        "min_subtotal_cents": min_subtotal,
        "max_uses": max_uses,
        "uses_count": 0,
        "active": active,
    }
    stamp_create(rec)
    db.promo_codes[rec["id"]] = rec
    return ok(serialize.promo_code(rec), 201)


@bp.route("/promo-codes/<pid>", methods=["GET"])
def get_promo(pid):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    rec = db.promo_codes.get(pid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Promo code not found")
    return ok(serialize.promo_code(rec))
