"""Bootstrap/admin resources: clock, policyholders, repair shops, rental partners."""
from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (bump, check_body_fk, claim_view, get_claim, is_int,
                      new_entity, need_date, need_int, need_str,
                      sorted_by_creation, view)
from util import parse_datetime

bp = Blueprint("admin", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["SystemAdmin"])
    b = body()
    target = parse_datetime(b.get("to_iso8601"))
    if target is None:
        raise bad_request("to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(target)
    return ok({}, status=200)


# ---------------------------------------------------------------------------
# Policyholders
# ---------------------------------------------------------------------------


@bp.post("/policyholders")
def create_policyholder():
    require_roles(["SystemAdmin"])
    b = body()
    full_name = need_str(b, "full_name")
    policy_number = need_str(b, "policy_number")
    contact_email = need_str(b, "contact_email")
    for p in db.policyholders.values():
        if p["policy_number"] == policy_number:
            raise api_error("ERR_DUPLICATE_POLICY_NUMBER", 409,
                            "policy_number already registered")
    e = new_entity()
    e.update({"full_name": full_name, "policy_number": policy_number,
              "contact_email": contact_email})
    db.policyholders[e["id"]] = e
    return ok(view(e), status=201)


@bp.get("/policyholders/<pid>")
def get_policyholder(pid):
    require_roles(ALL_ROLES)
    p = db.policyholders.get(pid)
    if p is None:
        raise api_error("ERR_POLICYHOLDER_NOT_FOUND", 404, "policyholder not found: %s" % pid)
    return ok(view(p))


@bp.get("/policyholders/<pid>/claims")
def list_policyholder_claims(pid):
    require_roles(ALL_ROLES)
    p = db.policyholders.get(pid)
    if p is None:
        raise api_error("ERR_POLICYHOLDER_NOT_FOUND", 404, "policyholder not found: %s" % pid)
    items = sorted_by_creation([c for c in db.claims.values() if c["policyholder_id"] == pid])
    page, meta = paginate(items, request.args)
    return ok([claim_view(c) for c in page], response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Repair shops
# ---------------------------------------------------------------------------


@bp.post("/repair-shops")
def create_repair_shop():
    require_roles(["SystemAdmin"])
    b = body()
    shop_name = need_str(b, "shop_name")
    shop_code = need_str(b, "shop_code")
    for s in db.repair_shops.values():
        if s["shop_code"] == shop_code:
            raise api_error("ERR_DUPLICATE_SHOP_CODE", 409, "shop_code already registered")
    e = new_entity()
    e.update({"shop_name": shop_name, "shop_code": shop_code})
    db.repair_shops[e["id"]] = e
    return ok(view(e), status=201)


@bp.get("/repair-shops/<sid>")
def get_repair_shop(sid):
    require_roles(ALL_ROLES)
    s = db.repair_shops.get(sid)
    if s is None:
        raise api_error("ERR_REPAIR_SHOP_NOT_FOUND", 404, "repair shop not found: %s" % sid)
    return ok(view(s))


# ---------------------------------------------------------------------------
# Rental partners
# ---------------------------------------------------------------------------


@bp.post("/rental-partners")
def create_rental_partner():
    require_roles(["SystemAdmin"])
    b = body()
    partner_name = need_str(b, "partner_name")
    partner_code = need_str(b, "partner_code")
    economy_rate = need_int(b, "economy_rate_cents")
    standard_rate = need_int(b, "standard_rate_cents")
    premium_rate = need_int(b, "premium_rate_cents")
    economy_cap = need_int(b, "economy_capacity")
    standard_cap = need_int(b, "standard_capacity")
    premium_cap = need_int(b, "premium_capacity")
    if economy_rate <= 0 or standard_rate <= 0 or premium_rate <= 0:
        raise bad_request("rate card values must be greater than zero")
    if economy_cap < 0 or standard_cap < 0 or premium_cap < 0:
        raise bad_request("fleet capacities may not be negative")
    for p in db.rental_partners.values():
        if p["partner_code"] == partner_code:
            raise api_error("ERR_DUPLICATE_PARTNER_CODE", 409,
                            "partner_code already registered")
    e = new_entity()
    e.update({
        "partner_name": partner_name,
        "partner_code": partner_code,
        "economy_rate_cents": economy_rate,
        "standard_rate_cents": standard_rate,
        "premium_rate_cents": premium_rate,
        "economy_capacity": economy_cap,
        "standard_capacity": standard_cap,
        "premium_capacity": premium_cap,
        "status": "ACTIVE",
    })
    db.rental_partners[e["id"]] = e
    return ok(view(e), status=201)


@bp.get("/rental-partners/<pid>")
def get_rental_partner(pid):
    require_roles(ALL_ROLES)
    p = db.rental_partners.get(pid)
    if p is None:
        raise api_error("ERR_RENTAL_PARTNER_NOT_FOUND", 404, "rental partner not found: %s" % pid)
    return ok(view(p))


@bp.post("/rental-partners/<pid>/suspend")
def suspend_rental_partner(pid):
    require_roles(["SystemAdmin"])
    p = db.rental_partners.get(pid)
    if p is None:
        raise api_error("ERR_RENTAL_PARTNER_NOT_FOUND", 404, "rental partner not found: %s" % pid)
    p["status"] = "SUSPENDED"
    bump(p)
    return ok(view(p))


@bp.post("/rental-partners/<pid>/reactivate")
def reactivate_rental_partner(pid):
    require_roles(["SystemAdmin"])
    p = db.rental_partners.get(pid)
    if p is None:
        raise api_error("ERR_RENTAL_PARTNER_NOT_FOUND", 404, "rental partner not found: %s" % pid)
    p["status"] = "ACTIVE"
    bump(p)
    return ok(view(p))
