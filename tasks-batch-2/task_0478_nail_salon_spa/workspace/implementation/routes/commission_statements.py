"""Commission statements and period settlement (PRD §3.16)."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, parse_pagination,
                    paginate)
from db import db
from datetime_util import parse_iso8601
from errors import err, ERR_INVALID_STATE, ERR_FORBIDDEN
from middleware import authorize
from lookup import get_technician, get_commission_statement
from response import success_object, success_list
from serialize import commission_statement_out
import services as svc

bp = Blueprint("commission_statements", __name__)


@bp.route("/commission-statements", methods=["POST"])
def create_statement():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    technician_id = get_str(body, "technician_id", required=True)
    period_start_raw = get_str(body, "period_start", required=True)
    period_end_raw = get_str(body, "period_end", required=True)

    get_technician(technician_id)  # FK existence (PRD §2.6)
    parse_iso8601(period_start_raw)
    parse_iso8601(period_end_raw)

    rec = make_record({
        "technician_id": technician_id,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "gross_service_cents": 0,
        "technician_payout_cents": 0,
        "salon_retained_cents": 0,
        "swept_appointment_count": 0,
        "status": "DRAFT",
    })
    db.commission_statements[rec["id"]] = rec
    return success_object(commission_statement_out(rec), status=201)


@bp.route("/commission-statements", methods=["GET"])
def list_statements():
    authorize({"SalonManager"})
    items = list(db.commission_statements.values())
    tid = request.args.get("technician_id")
    if tid is not None:
        items = [s for s in items if s["technician_id"] == tid]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([commission_statement_out(s) for s in page], limit, offset, total)


@bp.route("/commission-statements/<sid>", methods=["GET"])
def get_one_statement(sid):
    user_id, role = authorize({"SalonManager", "Technician"})
    rec = get_commission_statement(sid)
    if role == "Technician" and user_id != rec["technician_id"]:
        raise err(ERR_FORBIDDEN, "Technician may only read their own statements")
    return success_object(commission_statement_out(rec), status=200)


@bp.route("/commission-statements/<sid>/settle", methods=["POST"])
def settle_statement(sid):
    authorize({"SalonManager"})
    rec = get_commission_statement(sid)
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Only a DRAFT statement can be settled")
    technician = get_technician(rec["technician_id"])
    if technician["status"] == "TERMINATED":
        raise err(ERR_INVALID_STATE, "Technician is TERMINATED")
    svc.settle_statement(rec, technician)
    return success_object(commission_statement_out(rec), status=200)


@bp.route("/commission-statements/<sid>/void", methods=["POST"])
def void_statement(sid):
    authorize({"SalonManager"})
    rec = get_commission_statement(sid)
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Only a DRAFT statement can be voided")
    rec["status"] = "VOID"
    touch(rec)
    return success_object(commission_statement_out(rec), status=200)
