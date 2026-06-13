"""Subsidiary rights (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_principal, require_publisher, serialize
from response import object_response, array_response
from services import validate
from services.access import can_read_contract
from services.money import mul_round
from services.listing import paginate

bp = Blueprint("rights", __name__)

RIGHT_TYPES = {"FOREIGN", "AUDIO", "FILM"}


def _read_contract_or_403(cid):
    role, user_id = get_principal()
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    if not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return contract


@bp.route("/contracts/<cid>/subsidiary-rights", methods=["POST"])
def create_right(cid):
    role, _ = get_principal()
    require_publisher(role)
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    body = validate.get_body()
    right_type = validate.req_enum(body, "right_type", RIGHT_TYPES)
    proceeds_cents = validate.req_int(body, "proceeds_cents")
    author_share_pct = validate.req_number(body, "author_share_pct")
    validate.range_gt(proceeds_cents, "proceeds_cents", 0)
    validate.range_pct_open_low(author_share_pct, "author_share_pct")

    author_income = mul_round(proceeds_cents, author_share_pct)
    rec = db.make_common({
        "contract_id": cid,
        "right_type": right_type,
        "proceeds_cents": proceeds_cents,
        "author_share_pct": author_share_pct,
        "author_income_cents": author_income,
        "status": "REGISTERED",
        "statement_id": None,
    })
    db.subsidiary_rights[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/contracts/<cid>/subsidiary-rights", methods=["GET"])
def list_rights(cid):
    contract = _read_contract_or_403(cid)
    status = request.args.get("status")
    records = [r for r in db.subsidiary_rights.values() if r["contract_id"] == contract["id"]]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/subsidiary-rights/<rid>", methods=["GET"])
def get_right(rid):
    role, user_id = get_principal()
    right = db.subsidiary_rights.get(rid)
    if right is None:
        raise errors.not_found("Subsidiary right not found.")
    contract = db.contracts.get(right["contract_id"])
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return object_response(serialize(right))


@bp.route("/subsidiary-rights/<rid>/void", methods=["POST"])
def void_right(rid):
    role, _ = get_principal()
    require_publisher(role)
    right = db.subsidiary_rights.get(rid)
    if right is None:
        raise errors.not_found("Subsidiary right not found.")
    if right["status"] != "REGISTERED":
        # voiding a STATEMENTED or VOID right (priority 13).
        raise errors.right_already_settled()
    right["status"] = "VOID"
    db.touch(right)
    return object_response(serialize(right))
