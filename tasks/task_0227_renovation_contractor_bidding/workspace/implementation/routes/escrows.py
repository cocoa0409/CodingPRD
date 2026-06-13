"""Escrow routes: fetch, list, fund (AWARDED -> IN_PROGRESS)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("escrows", __name__)


@bp.route("/escrows/<rid>", methods=["GET"])
def get_escrow(rid):
    require_roles("Homeowner", "EscrowAgent", "PlatformAdmin")
    rec = lookups.get_escrow(rid)
    return response.success(common.public(rec), 200)


@bp.route("/escrows", methods=["GET"])
def list_escrows():
    require_roles("Homeowner", "EscrowAgent", "PlatformAdmin")
    items = list(db.escrows.values())
    pid = request.args.get("project_id")
    if pid is not None:
        items = [e for e in items if e["project_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


@bp.route("/escrows/<rid>/fund", methods=["POST"])
def fund_escrow(rid):
    require_roles("EscrowAgent")
    escrow = lookups.get_escrow(rid)
    project = lookups.get_project(escrow["project_id"])
    body = common.get_body()
    deposit = common.as_int(common.require_field(body, "deposit_cents"), "deposit_cents")
    # state: escrow must be UNFUNDED
    if escrow["status"] != "UNFUNDED":
        raise errors.invalid_state("Only an UNFUNDED escrow can be funded.")
    # fiscal: deposit must equal contract_value (ERR_INSUFFICIENT_ESCROW)
    if deposit != project["contract_value_cents"]:
        raise errors.ApiError(errors.ERR_INSUFFICIENT_ESCROW, 409,
                              "deposit_cents must equal the project contract_value_cents.")
    escrow["funded_cents"] = deposit
    escrow["available_cents"] = deposit
    escrow["status"] = "FUNDED"
    common.touch(escrow)
    project["status"] = "IN_PROGRESS"
    common.touch(project)
    return response.success(common.public(escrow), 200)
