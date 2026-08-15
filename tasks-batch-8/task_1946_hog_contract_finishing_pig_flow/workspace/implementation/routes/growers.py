"""Growers (PRD §3.1)."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict, ERR_INVALID_STATE_TRANSITION, ERR_DUPLICATE_GROWER_CODE,
)
from middleware import (
    require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER,
)
from response import success_object, paginate
from services.core import new_record, touch, ser_grower
from util import get_body, req, as_str, load_or_404

bp = Blueprint("growers", __name__)


@bp.route("/growers", methods=["POST"])
def create_grower():
    require_roles([ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    legal_name = as_str(req(body, "legal_name"), "legal_name")
    grower_code = as_str(req(body, "grower_code"), "grower_code")
    email = as_str(req(body, "email"), "email")
    # grower_code is unique across Grower (priority 11)
    for g in store.growers.values():
        if g["grower_code"] == grower_code:
            raise conflict(ERR_DUPLICATE_GROWER_CODE,
                           f"grower_code already in use: {grower_code}")
    rec = new_record()
    rec.update({
        "legal_name": legal_name, "grower_code": grower_code, "email": email,
        "grower_status": "ACTIVE", "balance_due_cents": 0, "lifetime_paid_cents": 0,
    })
    store.growers[rec["id"]] = rec
    return success_object(ser_grower(rec), 201)


@bp.route("/growers", methods=["GET"])
def list_growers():
    require_roles([ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH])
    status = request.args.get("grower_status")
    items = list(store.growers.values())
    if status is not None:
        items = [g for g in items if g["grower_status"] == status]
    return paginate(items, request.args, ser_grower)


@bp.route("/growers/<gid>", methods=["GET"])
def get_grower(gid):
    require_roles([ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER])
    return success_object(ser_grower(load_or_404(store.growers, gid, "Grower")))


@bp.route("/growers/<gid>/suspend", methods=["POST"])
def suspend_grower(gid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    grower = load_or_404(store.growers, gid, "Grower")
    if grower["grower_status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot suspend a grower in {grower['grower_status']}")
    grower["grower_status"] = "SUSPENDED"
    touch(grower)
    return success_object(ser_grower(grower))


@bp.route("/growers/<gid>/reinstate", methods=["POST"])
def reinstate_grower(gid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    grower = load_or_404(store.growers, gid, "Grower")
    if grower["grower_status"] != "SUSPENDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot reinstate a grower in {grower['grower_status']}")
    grower["grower_status"] = "ACTIVE"
    touch(grower)
    return success_object(ser_grower(grower))


@bp.route("/growers/<gid>/terminate", methods=["POST"])
def terminate_grower(gid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    grower = load_or_404(store.growers, gid, "Grower")
    if grower["grower_status"] not in ("ACTIVE", "SUSPENDED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot terminate a grower in {grower['grower_status']}")
    # refused while the grower still holds an ACTIVE contract
    for c in store.contracts.values():
        if c["grower_id"] == gid and c["contract_status"] == "ACTIVE":
            raise conflict(ERR_INVALID_STATE_TRANSITION,
                           "Grower still holds an ACTIVE contract")
    grower["grower_status"] = "TERMINATED"
    touch(grower)
    return success_object(ser_grower(grower))
