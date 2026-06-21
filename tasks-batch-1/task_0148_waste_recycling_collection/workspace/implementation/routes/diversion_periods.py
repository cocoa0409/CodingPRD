"""DiversionPeriod endpoints (PRD §3.8)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import calculations as calc
from services import serializers as ser
from services.common import get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("diversion_periods", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    # Half-open [start, end) intervals; touching at a shared endpoint is allowed.
    return a_start < b_end and b_start < a_end


@bp.route("/accounts/<account_id>/diversion-periods", methods=["POST"])
def create_diversion_period(account_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    body = get_json_body()
    require_fields(body, ["period_start", "period_end"])
    if not (body["period_start"] < body["period_end"]):
        raise err("ERR_INVALID_PERIOD", "period_start must be strictly before period_end.")
    # Must not overlap an existing OPEN or FINALIZED period for this account.
    for dp in db.diversion_periods.values():
        if dp["account_id"] == account_id and dp["status"] in ("OPEN", "FINALIZED"):
            if _overlaps(body["period_start"], body["period_end"], dp["period_start"], dp["period_end"]):
                raise err("ERR_PERIOD_OVERLAP", "New diversion period overlaps an existing window.")

    rec = base_record()
    rec.update(
        {
            "account_id": account_id,
            "period_start": body["period_start"],
            "period_end": body["period_end"],
            "status": "OPEN",
            "diverted_weight_lbs": 0,
            "total_weight_lbs": 0,
            "diversion_rate_pct": 0,
        }
    )
    db.diversion_periods[rec["id"]] = rec
    return success(ser.diversion_period(rec), status=201)


@bp.route("/diversion-periods/<dp_id>", methods=["GET"])
def get_diversion_period(dp_id):
    _, role = authenticate()
    require_roles(role, {"Billing", "ResidentAccount"})
    rec = db.diversion_periods.get(dp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Diversion period not found.")
    return success(ser.diversion_period(rec), status=200)


@bp.route("/diversion-periods", methods=["GET"])
def list_diversion_periods():
    _, role = authenticate()
    require_roles(role, {"Billing", "ResidentAccount"})
    parse_pagination()
    items = list(db.diversion_periods.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, pagination = paginate(items)
    return success([ser.diversion_period(d) for d in page], status=200, pagination=pagination)


@bp.route("/diversion-periods/<dp_id>/finalize", methods=["POST"])
def finalize_diversion_period(dp_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.diversion_periods.get(dp_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Diversion period not found.")
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN diversion period can be finalized.")

    period_start = rec["period_start"]
    period_end = rec["period_end"]
    account_id = rec["account_id"]
    diverted = 0.0
    total = 0.0
    for wt in db.weight_tickets.values():
        pu = db.pickups.get(wt["pickup_id"])
        if pu is None or pu["outcome"] != "COMPLETED":
            continue
        cart = db.carts.get(pu["cart_id"])
        if cart is None or cart["account_id"] != account_id:
            continue
        if not (period_start <= wt["created_at"] < period_end):
            continue
        total += wt["net_weight_lbs"]
        if wt["diverted"]:
            diverted += wt["net_weight_lbs"]

    rec["diverted_weight_lbs"] = round(diverted, 3)
    rec["total_weight_lbs"] = round(total, 3)
    rec["diversion_rate_pct"] = calc.diversion_rate_pct(diverted, total)
    rec["status"] = "FINALIZED"
    touch(rec)
    return success(ser.diversion_period(rec), status=200)
