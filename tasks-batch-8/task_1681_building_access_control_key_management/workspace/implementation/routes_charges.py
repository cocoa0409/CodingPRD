from datetime import timedelta

from flask import Blueprint, request

from db import STORE, bump, is_int
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_FORBIDDEN,
                    ERR_CHARGE_INVALID_STATE, ERR_PAYMENT_AMOUNT_MISMATCH,
                    ERR_ALERT_INVALID_STATE)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_charge, ser_propped_alert
from validators import get_or_404
from services import line_sort_key, forfeiture_line, TRAILING_LOSS_WINDOW_DAYS

bp = Blueprint("charges", __name__)

STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]


# ------------------------------------------------------------------ charges
@bp.route("/charges", methods=["GET"])
def list_charges():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "SecurityOfficer", "FrontDesk",
                        "Resident", "Vendor"])
    args = request.args
    if ctx.role in ("Resident", "Vendor"):
        if args.get("person_id") != ctx.user_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "Must filter person_id to own id")
    rows = list(STORE["charges"].values())
    for f in ("building_id", "person_id", "campaign_id", "kind", "status"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_charge)


@bp.route("/charges/<chargeId>", methods=["GET"])
def get_charge(chargeId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    ch = get_or_404("charges", chargeId, "Charge")
    return ok_object(ser_charge(ch))


@bp.route("/charges/<chargeId>/issue", methods=["POST"])
def issue_charge(chargeId):
    ctx = authenticate()
    require_roles(ctx, ["FrontDesk", "SecurityAdmin"])
    ch = get_or_404("charges", chargeId, "Charge")
    if ch["status"] != "DRAFT":
        raise ApiError(ERR_CHARGE_INVALID_STATE, 409,
                       "Charge is not DRAFT")
    if ch["kind"] == "MOVE_OUT_SETTLEMENT":
        # Final variant: append trailing-30-day LOST forfeiture lines.
        moved_out_at = ch["moved_out_at"]
        lo = moved_out_at - timedelta(days=TRAILING_LOSS_WINDOW_DAYS)
        extra = [c for c in STORE["credentials"].values()
                 if c["holder_person_id"] == ch["person_id"]
                 and c["lost_at"] is not None
                 and lo <= c["lost_at"] <= moved_out_at]
        extra.sort(key=line_sort_key)
        lines = list(ch["line_items"] or [])
        lines.extend(forfeiture_line(c) for c in extra)
        total = sum(l["fee_cents"] for l in lines)
        ch["line_items"] = lines
        ch["final_forfeit_total_cents"] = total
        ch["final_refund_cents"] = max(0, ch["deposit_cents"] - total)
        ch["amount_cents"] = max(0, total - ch["deposit_cents"])
    ch["status"] = "ISSUED"
    bump(ch)
    return ok_object(ser_charge(ch))


@bp.route("/charges/<chargeId>/pay", methods=["POST"])
def pay_charge(chargeId):
    ctx = authenticate()
    require_roles(ctx, ["Resident", "Vendor", "FrontDesk"])
    ch = get_or_404("charges", chargeId, "Charge")
    if ctx.role in ("Resident", "Vendor"):
        if ch["person_id"] != ctx.user_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "May only pay own charges")
    b = body()
    paid = b.get("paid_amount_cents")
    if not is_int(paid):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "paid_amount_cents is required")
    if ch["status"] != "ISSUED":
        raise ApiError(ERR_CHARGE_INVALID_STATE, 409,
                       "Charge is not ISSUED")
    if paid != ch["amount_cents"]:
        raise ApiError(ERR_PAYMENT_AMOUNT_MISMATCH, 422,
                       "paid_amount_cents must equal amount_cents")
    ch["status"] = "PAID"
    bump(ch)
    return ok_object(ser_charge(ch))


@bp.route("/charges/<chargeId>/void", methods=["POST"])
def void_charge(chargeId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    ch = get_or_404("charges", chargeId, "Charge")
    if ch["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError(ERR_CHARGE_INVALID_STATE, 409,
                       "Charge is not DRAFT or ISSUED")
    ch["status"] = "VOID"
    bump(ch)
    return ok_object(ser_charge(ch))


# ----------------------------------------------------------- propped alerts
@bp.route("/propped-alerts", methods=["GET"])
def list_propped_alerts():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["propped_alerts"].values())
    for f in ("building_id", "door_id", "status", "incident_id"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_propped_alert)


@bp.route("/propped-alerts/<alertId>", methods=["GET"])
def get_propped_alert(alertId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    a = get_or_404("propped_alerts", alertId, "ProppedDoorAlert")
    return ok_object(ser_propped_alert(a))


@bp.route("/propped-alerts/<alertId>/acknowledge", methods=["POST"])
def acknowledge_alert(alertId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityOfficer", "SecurityAdmin"])
    a = get_or_404("propped_alerts", alertId, "ProppedDoorAlert")
    if a["status"] != "OPEN":
        raise ApiError(ERR_ALERT_INVALID_STATE, 409, "Alert is not OPEN")
    a["status"] = "ACKNOWLEDGED"
    bump(a)
    return ok_object(ser_propped_alert(a))


@bp.route("/propped-alerts/<alertId>/resolve", methods=["POST"])
def resolve_alert(alertId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityOfficer", "SecurityAdmin"])
    a = get_or_404("propped_alerts", alertId, "ProppedDoorAlert")
    if a["status"] not in ("OPEN", "ACKNOWLEDGED", "ESCALATED"):
        raise ApiError(ERR_ALERT_INVALID_STATE, 409,
                       "Alert is not OPEN, ACKNOWLEDGED, or ESCALATED")
    a["status"] = "RESOLVED"
    a["resolved_reason"] = "MANUAL"
    bump(a)
    return ok_object(ser_propped_alert(a))
