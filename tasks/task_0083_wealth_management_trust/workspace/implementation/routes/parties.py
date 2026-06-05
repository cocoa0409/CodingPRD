"""Grantor / Trustee / Beneficiary party CRUD (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.helpers import (
    get_json_body, require_str, optional_int, optional_bool, require_int, must_exist,
)
from services.ledger import recompute_grantor_remaining

bp = Blueprint("parties", __name__)

GST_LIFETIME_DEFAULT = 1399000000


# ---- Grantor ----
@bp.route("/grantors", methods=["POST"])
def create_grantor():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    generation_level = optional_int(body, "generation_level", 0)
    total = optional_int(body, "gst_exemption_total_cents", GST_LIFETIME_DEFAULT)
    if generation_level < 0:
        raise err("ERR_INVALID_AMOUNT", "generation_level must be >= 0")
    if total < 0:
        raise err("ERR_INVALID_AMOUNT", "gst_exemption_total_cents must be >= 0")

    with db.LOCK:
        g = db.base_fields()
        g.update({
            "full_name": full_name,
            "generation_level": generation_level,
            "gst_exemption_total_cents": total,
            "gst_exemption_remaining_cents": total,
        })
        db.grantors[g["id"]] = g
    return success(serialize.grantor(g), status=201)


@bp.route("/grantors/<gid>", methods=["GET"])
def get_grantor(gid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Grantor"})
    g = must_exist(db.grantors, gid)
    if role == "Grantor" and user_id != g["id"]:
        raise err("ERR_NOT_OWNER")
    return success(serialize.grantor(g))


# ---- Trustee ----
@bp.route("/trustees", methods=["POST"])
def create_trustee():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    is_corporate = optional_bool(body, "is_corporate", False)
    with db.LOCK:
        t = db.base_fields()
        t.update({"full_name": full_name, "is_corporate": is_corporate})
        db.trustees[t["id"]] = t
    return success(serialize.trustee(t), status=201)


@bp.route("/trustees/<tid>", methods=["GET"])
def get_trustee(tid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    t = must_exist(db.trustees, tid)
    if role == "Trustee" and user_id != t["id"]:
        raise err("ERR_NOT_OWNER")
    return success(serialize.trustee(t))


# ---- Beneficiary ----
@bp.route("/beneficiaries", methods=["POST"])
def create_beneficiary():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    grantor_id = require_str(body, "grantor_id")
    generation_level = require_int(body, "generation_level")
    # existence (priority 3) before business-rule amount check (priority 11)
    grantor = must_exist(db.grantors, grantor_id)
    if generation_level < 0:
        raise err("ERR_INVALID_AMOUNT", "generation_level must be >= 0")

    with db.LOCK:
        is_skip = (generation_level - grantor["generation_level"]) >= 2
        b = db.base_fields()
        b.update({
            "full_name": full_name,
            "grantor_id": grantor_id,
            "generation_level": generation_level,
            "is_skip_person": is_skip,
        })
        db.beneficiaries[b["id"]] = b
    return success(serialize.beneficiary(b), status=201)


@bp.route("/beneficiaries/<bid>", methods=["GET"])
def get_beneficiary(bid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Beneficiary"})
    b = must_exist(db.beneficiaries, bid)
    if role == "Beneficiary" and user_id != b["id"]:
        raise err("ERR_NOT_OWNER")
    return success(serialize.beneficiary(b))


@bp.route("/beneficiaries", methods=["GET"])
def list_beneficiaries():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    limit, offset = parse_pagination()
    grantor_id = request.args.get("grantor_id")
    items = list(db.beneficiaries.values())
    if grantor_id is not None:
        items = [b for b in items if b["grantor_id"] == grantor_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.beneficiary(b) for b in page], pagination=meta)
