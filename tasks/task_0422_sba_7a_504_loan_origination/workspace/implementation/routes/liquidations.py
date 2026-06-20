"""LiquidationEvent endpoints — PRD §3.10, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_positive_int,
    optional_nonneg_int, paginate, sort_by_created,
)

bp = Blueprint("liquidations", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/liquidations")
def create_liquidation():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    recovery = require_positive_int(body, "recovery_cents")
    expense = optional_nonneg_int(body, "expense_cents", default=0)
    with db.LOCK:
        app = db.applications.get(application_id)
        if app is None:
            raise errors.invalid_request("application_id does not reference an existing Application")
        # PRD §3.10: opening permitted only when servicing_status is DEFAULTED.
        if app["servicing_status"] != "DEFAULTED":
            raise errors.err(errors.ERR_NOT_DEFAULTED, 409,
                             "Application is not DEFAULTED")
        rec = db.init_record({
            "application_id": application_id,
            "recovery_cents": recovery,
            "expense_cents": expense,
            "sba_share_cents": 0,
            "lender_share_cents": 0,
            "status": "OPEN",
        })
        db.liquidations[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/liquidations")
def list_liquidations(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [l for l in db.liquidations.values() if l["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/sba/liquidations/<liquidation_id>/settle")
def settle_liquidation(liquidation_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        liq = db.liquidations.get(liquidation_id)
        if liq is None:
            raise errors.not_found("LiquidationEvent not found")
        app = db.applications.get(liq["application_id"])
        if liq["status"] != "OPEN":
            raise errors.invalid_state("LiquidationEvent is not OPEN")
        net_recovery, sba_share, lender_share = calc.liquidation_split(
            liq["recovery_cents"], liq["expense_cents"], app["guaranty_pct"])
        liq["sba_share_cents"] = sba_share
        liq["lender_share_cents"] = lender_share
        liq["status"] = "SETTLED"
        db.touch(liq)
        # servicing_status DEFAULTED -> LIQUIDATED.
        app["servicing_status"] = "LIQUIDATED"
        # reduce outstanding principal by net recovery (cascade).
        app["outstanding_principal_cents"] -= net_recovery
        db.touch(app)
        return object_response(serialize(liq), 200)
