"""Department endpoints and the supplier-diversity spend report (PRD 3.1/3.10)."""

from decimal import Decimal

from flask import request

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    require_fk,
    parse_dt,
    dec,
    rhu_4dp,
)
from errors import ApiError, ERR_INVALID_REQUEST

bp = make_blueprint("departments")


@bp.post("/departments")
def create_department():
    authenticate(["ProcurementAdmin"])
    body = body_json()
    check_shape(body, {
        "name": {"type": "string", "required": True},
        "cost_center": {"type": "string", "required": True},
        "diversity_goal_pct": {"type": "number", "required": True},
        "sustainability_goal_pct": {"type": "number", "required": True},
        "default_approval_limit_cents": {"type": "integer", "required": True},
    })
    dept = db.new_entity("departments", {
        "name": body["name"],
        "cost_center": body["cost_center"],
        "diversity_goal_pct": body["diversity_goal_pct"],
        "sustainability_goal_pct": body["sustainability_goal_pct"],
        "default_approval_limit_cents": body["default_approval_limit_cents"],
    })
    return success_obj(db.public(dept), 201)


@bp.get("/departments")
def list_departments():
    authenticate(ROLES)
    limit, offset = pagination_params()
    page, total, has_more = paginate(db.all_of("departments"), limit, offset)
    return success_list([db.public(d) for d in page], limit, offset, total, has_more)


@bp.get("/departments/<did>")
def get_department(did):
    authenticate(ROLES)
    dept = require_fk("departments", did)
    return success_obj(db.public(dept), 200)


@bp.get("/departments/<did>/diversity-report")
def diversity_report(did):
    """diversity_spend_ratio: COMMITTED counts issued, non-cancelled POs;
    PAID counts PAID invoices. Default window upper bound is the logical clock;
    optional window_start/window_end are inclusive bounds on the same stamp."""
    authenticate(ROLES)
    dept = require_fk("departments", did)
    basis = request.args.get("basis", "COMMITTED")
    if basis not in ("COMMITTED", "PAID"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "basis must be COMMITTED or PAID")
    ws = request.args.get("window_start")
    we = request.args.get("window_end")
    window_start = parse_dt(ws, "window_start") if ws is not None else None
    window_end = parse_dt(we, "window_end") if we is not None else None
    now = db.now()

    def in_window(ts):
        if ts > now:
            return False
        if window_start is not None and ts < window_start:
            return False
        if window_end is not None and ts > window_end:
            return False
        return True

    total = 0
    diverse = 0
    if basis == "COMMITTED":
        for po in db.all_of("purchase_orders"):
            req = db.get("requisitions", po["requisition_id"])
            if req is None or req["department_id"] != dept["id"]:
                continue
            if po["fulfillment_status"] == "CANCELLED":
                continue
            if not in_window(parse_dt(po["issued_at"])):
                continue
            total += po["total_cents"]
            vendor = db.get("vendors", po["vendor_id"])
            if vendor and vendor["diversity_certification"] != "NONE":
                diverse += po["total_cents"]
    else:  # PAID
        for inv in db.all_of("invoices"):
            if inv["status"] != "PAID":
                continue
            po = db.get("purchase_orders", inv["po_id"])
            req = db.get("requisitions", po["requisition_id"]) if po else None
            if req is None or req["department_id"] != dept["id"]:
                continue
            if not in_window(parse_dt(inv["paid_at"])):
                continue
            total += inv["total_cents"]
            vendor = db.get("vendors", inv["vendor_id"])
            if vendor and vendor["diversity_certification"] != "NONE":
                diverse += inv["total_cents"]

    if total == 0:
        ratio = 0.0
    else:
        ratio = rhu_4dp(Decimal(diverse) / Decimal(total))
    goal_met = dec(ratio) >= dec(dept["diversity_goal_pct"])
    return success_obj({
        "basis": basis,
        "diverse_spend_cents": diverse,
        "total_spend_cents": total,
        "ratio": ratio,
        "goal_met": goal_met,
    }, 200)
