"""Meter read endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import store
from errors import ERR_INDEX_ROLLBACK, ERR_INVALID_STATE, err
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_number,
    optional_enum,
    attach_event_fields,
    parse_dt,
    to_iso,
    paginate,
)
from services.serialize import view_meter_read
from services import lookup, calc

bp = Blueprint("meter_reads", __name__)


@bp.route("/meters/<meter_id>/reads", methods=["POST"])
def post_read(meter_id):
    principal = authenticate()
    require_role(principal, {"FieldTech", "BillingAdmin"})
    with store.lock:
        meter = lookup.get_meter(meter_id)
        body = get_body()
        require_fields(body, ["reading_index"])
        reading_index = require_number(body, "reading_index", minimum=0)
        read_type = optional_enum(body, "read_type", {"ACTUAL", "ESTIMATED"}, default="ACTUAL")
        if "read_date" in body and body["read_date"] is not None:
            read_dt = parse_dt(body["read_date"])
        else:
            read_dt = calc.clock_now()
        read_date_iso = to_iso(read_dt)

        # Register cannot roll backward (priority 9).
        ccf, therms, raw_delta = calc.compute_consumption(meter, reading_index, read_dt)
        if raw_delta < 0:
            raise err(ERR_INDEX_ROLLBACK, "Register reading cannot run backward")

        rec = {
            "premise_meter_id": meter_id,
            "account_id": meter["account_id"],
            "read_date": read_date_iso,
            "reading_index": reading_index,
            "read_type": read_type,
            "status": "POSTED",
            "ccf_consumed": ccf,
            "therms_consumed": therms,
            "bill_id": None,
        }
        attach_event_fields(rec)
        store.meter_reads[rec["id"]] = rec
        return success(view_meter_read(rec), 201)


@bp.route("/meters/<meter_id>/reads/<read_id>/void", methods=["POST"])
def void_read(meter_id, read_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        meter = lookup.get_meter(meter_id)
        read = lookup.get_read_under_meter(meter_id, read_id)
        if read["status"] == "VOID":
            raise err(ERR_INVALID_STATE, "Read already voided")
        read["status"] = "VOID"
        return success(view_meter_read(read), 200)


@bp.route("/meter-reads", methods=["GET"])
def list_reads():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    premise_meter_id = request.args.get("premise_meter_id")
    account_id = request.args.get("account_id")
    bill_id = request.args.get("bill_id")
    records = list(store.meter_reads.values())
    if premise_meter_id is not None:
        records = [r for r in records if r["premise_meter_id"] == premise_meter_id]
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if bill_id is not None:
        records = [r for r in records if r.get("bill_id") == bill_id]
    if principal.role == "Account":
        records = [r for r in records if r["account_id"] == principal.user_id]
    page, list_meta = paginate(records)
    return success([view_meter_read(r) for r in page], 200, list_meta=list_meta)


@bp.route("/meter-reads/<read_id>", methods=["GET"])
def get_read(read_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    read = lookup.get_read(read_id)
    require_account_ownership(principal, read["account_id"])
    return success(view_meter_read(read), 200)
