"""Retailer endpoints + license state machine (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, touch, get_or_404,
                    parse_pagination, paginate, sort_by_created)
from response import success
from validate import require_body, req_str, opt_number

retailers_bp = Blueprint("retailers", __name__)


def _serialize_retailer(r):
    return serialize(r)


@retailers_bp.route("/retailers", methods=["POST"])
def create_retailer():
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    body = require_body(request.get_json(silent=True))

    business_name = req_str(body, "business_name")
    tax_id = req_str(body, "tax_id")
    commission_rate = opt_number(body, "commission_rate", 0.06, minimum=0, maximum=1, max_exclusive=True)
    cashing_bonus_rate = opt_number(body, "cashing_bonus_rate", 0.01, minimum=0, maximum=1, max_exclusive=True)

    # Uniqueness on tax_id
    for r in db.retailers.values():
        if r["tax_id"] == tax_id:
            raise err("ERR_DUPLICATE_RESOURCE", "tax_id already exists")

    retailer = {
        "business_name": business_name,
        "tax_id": tax_id,
        "commission_rate": commission_rate,
        "cashing_bonus_rate": cashing_bonus_rate,
        "license_status": "PENDING",
        "commission_balance_cents": 0,
        "lifetime_settled_cents": 0,
    }
    _stamp_create(retailer)
    db.retailers[retailer["id"]] = retailer
    return success(_serialize_retailer(retailer), 201)


@retailers_bp.route("/retailers/<rid>", methods=["GET"])
def get_retailer(rid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "LicensingAdmin"})
    retailer = get_or_404(db.retailers, rid, "retailer")
    return success(_serialize_retailer(retailer), 200)


@retailers_bp.route("/retailers", methods=["GET"])
def list_retailers():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "LicensingAdmin"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.retailers.values())
    status_f = request.args.get("license_status")
    if status_f is not None:
        rows = [r for r in rows if r["license_status"] == status_f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_retailer(r) for r in page], 200, pagination=meta)


def _terminals_of(retailer_id):
    return [t for t in db.terminals.values() if t["retailer_id"] == retailer_id]


@retailers_bp.route("/retailers/<rid>/license/activate", methods=["POST"])
def activate_license(rid):
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    retailer = get_or_404(db.retailers, rid, "retailer")
    if retailer["license_status"] not in ("PENDING", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "license not in PENDING or SUSPENDED")
    retailer["license_status"] = "ACTIVE"
    touch(retailer)
    # Note: deactivated terminals are NOT auto-reactivated.
    return success(_serialize_retailer(retailer), 200)


@retailers_bp.route("/retailers/<rid>/license/suspend", methods=["POST"])
def suspend_license(rid):
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    retailer = get_or_404(db.retailers, rid, "retailer")
    if retailer["license_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "license not ACTIVE")
    retailer["license_status"] = "SUSPENDED"
    touch(retailer)
    # Cascade: ACTIVE terminals -> DEACTIVATED (PROVISIONED & DEACTIVATED untouched)
    for t in _terminals_of(rid):
        if t["status"] == "ACTIVE":
            t["status"] = "DEACTIVATED"
            touch(t)
    return success(_serialize_retailer(retailer), 200)


@retailers_bp.route("/retailers/<rid>/license/revoke", methods=["POST"])
def revoke_license(rid):
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    retailer = get_or_404(db.retailers, rid, "retailer")
    if retailer["license_status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "license not SUSPENDED")
    retailer["license_status"] = "REVOKED"
    touch(retailer)
    # Cascade: PROVISIONED | ACTIVE terminals -> DEACTIVATED
    for t in _terminals_of(rid):
        if t["status"] in ("PROVISIONED", "ACTIVE"):
            t["status"] = "DEACTIVATED"
            touch(t)
    return success(_serialize_retailer(retailer), 200)
