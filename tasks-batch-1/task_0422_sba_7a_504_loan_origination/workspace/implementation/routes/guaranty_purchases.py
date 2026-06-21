"""GuarantyPurchase endpoints — PRD §3.10, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services import calculations as calc
from services.common import (
    serialize, get_json_body, require_string, require_positive_int,
    require_number, paginate, sort_by_created,
)

bp = Blueprint("guaranty_purchases", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/guaranty-purchases")
def create_guaranty_purchase():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    claimed = require_positive_int(body, "claimed_principal_cents")
    # repair_pct optional, default 0, in [0, 1].
    if "repair_pct" in body and body["repair_pct"] is not None:
        repair_pct = body["repair_pct"]
        if isinstance(repair_pct, bool) or not isinstance(repair_pct, (int, float)):
            raise errors.invalid_request("repair_pct must be a number")
        if not (0 <= repair_pct <= 1):
            raise errors.invalid_request("repair_pct must be between 0 and 1")
    else:
        repair_pct = 0
    with db.LOCK:
        app = db.applications.get(application_id)
        if app is None:
            raise errors.invalid_request("application_id does not reference an existing Application")
        # PRD §3.10: filing permitted only when servicing_status DEFAULTED or LIQUIDATED.
        if app["servicing_status"] not in ("DEFAULTED", "LIQUIDATED"):
            raise errors.err(errors.ERR_NOT_DEFAULTED, 409,
                             "Application is not DEFAULTED/LIQUIDATED")
        rec = db.init_record({
            "application_id": application_id,
            "requested_by_user_id": user_id,
            "claimed_principal_cents": claimed,
            "repair_pct": repair_pct,
            "approved_amount_cents": 0,
            "status": "FILED",
        })
        db.guaranty_purchases[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/guaranty-purchases")
def list_guaranty_purchases(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [p for p in db.guaranty_purchases.values() if p["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/sba/guaranty-purchases/<purchase_id>/pay")
def pay_guaranty_purchase(purchase_id):
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer"])
    with db.LOCK:
        gp = db.guaranty_purchases.get(purchase_id)
        if gp is None:
            raise errors.not_found("GuarantyPurchase not found")
        app = db.applications.get(gp["application_id"])
        # business precondition: servicing_status DEFAULTED or LIQUIDATED.
        if app["servicing_status"] not in ("DEFAULTED", "LIQUIDATED"):
            raise errors.err(errors.ERR_NOT_DEFAULTED, 409,
                             "Application is not DEFAULTED/LIQUIDATED")
        # state precondition: purchase FILED.
        if gp["status"] != "FILED":
            raise errors.invalid_state("GuarantyPurchase is not FILED")
        sba_recovery_credit = sum(
            l["sba_share_cents"] for l in db.liquidations.values()
            if l["application_id"] == app["id"] and l["status"] == "SETTLED"
        )
        approved = calc.guaranty_purchase_payout(
            app["outstanding_principal_cents"], app["guaranty_pct"],
            gp["claimed_principal_cents"], gp["repair_pct"], sba_recovery_credit)
        gp["approved_amount_cents"] = approved
        gp["status"] = "PAID"
        db.touch(gp)
        # guaranty_status -> PURCHASED_BY_SBA (from RETAINED or REPURCHASED).
        app["guaranty_status"] = "PURCHASED_BY_SBA"
        db.touch(app)
        return object_response(serialize(gp), 200)


@bp.post("/sba/guaranty-purchases/<purchase_id>/deny")
def deny_guaranty_purchase(purchase_id):
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer"])
    with db.LOCK:
        gp = db.guaranty_purchases.get(purchase_id)
        if gp is None:
            raise errors.not_found("GuarantyPurchase not found")
        if gp["status"] != "FILED":
            raise errors.invalid_state("GuarantyPurchase is not FILED")
        gp["status"] = "DENIED"
        db.touch(gp)
        return object_response(serialize(gp), 200)
