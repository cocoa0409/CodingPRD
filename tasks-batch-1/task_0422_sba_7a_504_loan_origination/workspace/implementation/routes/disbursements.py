"""Disbursement endpoints — PRD §3.7, §4. Draw windows are half-open [start,end)."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services.common import (
    serialize, get_json_body, require_string, require_positive_int,
    require_int, paginate, sort_by_created,
)

bp = Blueprint("disbursements", __name__)

READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/disbursements")
def create_disbursement():
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    body = get_json_body()
    application_id = require_string(body, "application_id")
    amount = require_positive_int(body, "amount_cents")
    tranche_label = require_string(body, "tranche_label")
    start_day = require_int(body, "draw_window_start_day")
    end_day = require_int(body, "draw_window_end_day")
    # A half-open window must be non-empty: start < end.
    if start_day < 0 or end_day < 0 or start_day >= end_day:
        raise errors.invalid_request("draw window must satisfy 0 <= start_day < end_day")
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.invalid_request("application_id does not reference an existing Application")
        rec = db.init_record({
            "application_id": application_id,
            "amount_cents": amount,
            "tranche_label": tranche_label,
            "draw_window_start_day": start_day,
            "draw_window_end_day": end_day,
            "status": "REQUESTED",
        })
        db.disbursements[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/applications/<application_id>/disbursements")
def list_disbursements(application_id):
    user_id, role = get_user_context()
    require_roles(role, READ_ROLES)
    with db.LOCK:
        if application_id not in db.applications:
            raise errors.not_found("Application not found")
        items = [d for d in db.disbursements.values() if d["application_id"] == application_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open windows [start, end) overlap iff a_start < b_end and b_start < a_end.
    Touching endpoints (one's end == other's start) do NOT overlap."""
    return a_start < b_end and b_start < a_end


@bp.post("/sba/disbursements/<disbursement_id>/post")
def post_disbursement(disbursement_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        disb = db.disbursements.get(disbursement_id)
        if disb is None:
            raise errors.not_found("Disbursement not found")
        app = db.applications.get(disb["application_id"])
        if disb["status"] != "REQUESTED":
            raise errors.invalid_state("Disbursement is not REQUESTED")
        # business preconditions in PRD §3.7 order:
        # 1. application AUTHORIZED or DISBURSING.
        if app["status"] not in ("AUTHORIZED", "DISBURSING"):
            raise errors.err(errors.ERR_NOT_AUTHORIZED_FOR_DISBURSAL, 409,
                             "Application is not AUTHORIZED/DISBURSING")
        # 2. over-disbursement.
        if app["disbursed_amount_cents"] + disb["amount_cents"] > app["requested_amount_cents"]:
            raise errors.err(errors.ERR_OVER_DISBURSEMENT, 409,
                             "Posting would exceed requested amount")
        # 3. draw window overlap with other POSTED draws on same application.
        for other in db.disbursements.values():
            if other["id"] == disb["id"]:
                continue
            if other["application_id"] != app["id"]:
                continue
            if other["status"] != "POSTED":
                continue
            if _windows_overlap(disb["draw_window_start_day"], disb["draw_window_end_day"],
                                other["draw_window_start_day"], other["draw_window_end_day"]):
                raise errors.err(errors.ERR_DRAW_WINDOW_OVERLAP, 409,
                                 "Draw window overlaps another posted draw")
        # success: post + cascades.
        is_first_posted = not any(
            d["application_id"] == app["id"] and d["status"] == "POSTED"
            for d in db.disbursements.values()
        )
        disb["status"] = "POSTED"
        db.touch(disb)
        app["disbursed_amount_cents"] += disb["amount_cents"]
        app["outstanding_principal_cents"] += disb["amount_cents"]
        if is_first_posted:
            app["status"] = "DISBURSING"
            app["servicing_status"] = "CURRENT"
        db.touch(app)
        return object_response(serialize(disb), 200)


@bp.post("/sba/disbursements/<disbursement_id>/reverse")
def reverse_disbursement(disbursement_id):
    user_id, role = get_user_context()
    require_roles(role, ["LoanOfficer"])
    with db.LOCK:
        disb = db.disbursements.get(disbursement_id)
        if disb is None:
            raise errors.not_found("Disbursement not found")
        app = db.applications.get(disb["application_id"])
        if disb["status"] != "POSTED":
            raise errors.invalid_state("Disbursement is not POSTED")
        # servicing_status must not be DEFAULTED or LIQUIDATED.
        if app["servicing_status"] in ("DEFAULTED", "LIQUIDATED"):
            raise errors.invalid_state("Cannot reverse on a defaulted/liquidated loan")
        disb["status"] = "REVERSED"
        db.touch(disb)
        app["disbursed_amount_cents"] -= disb["amount_cents"]
        app["outstanding_principal_cents"] -= disb["amount_cents"]
        db.touch(app)
        return object_response(serialize(disb), 200)
