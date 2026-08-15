"""Service accounts (PRD 3.2)."""

import envelope
import serializers as ser
import services
from errors import ApiError
from flask import Blueprint
from middleware import (begin, must_exist, must_ref, paginate, pagination,
                        req_enum, req_int, req_string)
from store import db, stamp_new, sorted_rows, touch

bp = Blueprint("accounts", __name__)

SERVICE_CLASSES = ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")


@bp.route("/service-accounts", methods=["POST"])
def create_account():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    customer_id = req_string(body, "customer_id")
    transformer_id = req_string(body, "transformer_id")
    account_number = req_string(body, "account_number")
    service_class = req_enum(body, "service_class", SERVICE_CLASSES)
    prior_annual_usage_wh = req_int(body, "prior_annual_usage_wh", minimum=0)
    must_ref(db.customers, customer_id)
    must_ref(db.transformers, transformer_id)
    for other in db.accounts.values():
        if other["account_number"] == account_number:
            raise ApiError("ERR_INVALID_REQUEST", "account_number must be unique.")
    row = stamp_new({
        "customer_id": customer_id,
        "transformer_id": transformer_id,
        "account_number": account_number,
        "service_class": service_class,
        "prior_annual_usage_wh": prior_annual_usage_wh,
        "account_status": "ACTIVE",
        "metering_status": "STANDARD",
        "meter_serial": None,
    })
    db.accounts[row["id"]] = row
    return envelope.created(ser.service_account(row))


@bp.route("/service-accounts", methods=["GET"])
def list_accounts():
    ctx = begin()
    rows = list(db.accounts.values())
    customer_id = ctx.query.get("customer_id")
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    transformer_id = ctx.query.get("transformer_id")
    if transformer_id is not None:
        rows = [r for r in rows if r["transformer_id"] == transformer_id]
    account_status = ctx.query.get("account_status")
    if account_status is not None:
        rows = [r for r in rows if r["account_status"] == account_status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.service_account(r) for r in page], limit, offset, total)


@bp.route("/service-accounts/<service_account_id>", methods=["GET"])
def get_account(service_account_id):
    begin()
    row = must_exist(db.accounts, service_account_id)
    return envelope.ok(ser.service_account(row))


@bp.route("/service-accounts/<service_account_id>/suspend", methods=["POST"])
def suspend_account(service_account_id):
    begin("ProgramAdministrator")
    row = must_exist(db.accounts, service_account_id)
    if row["account_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    row["account_status"] = "SUSPENDED"
    touch(row)
    return envelope.ok(ser.service_account(row))


@bp.route("/service-accounts/<service_account_id>/reactivate", methods=["POST"])
def reactivate_account(service_account_id):
    begin("ProgramAdministrator")
    row = must_exist(db.accounts, service_account_id)
    if row["account_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    row["account_status"] = "ACTIVE"
    touch(row)
    return envelope.ok(ser.service_account(row))


@bp.route("/service-accounts/<service_account_id>/close", methods=["POST"])
def close_account(service_account_id):
    begin("ProgramAdministrator")
    row = must_exist(db.accounts, service_account_id)
    if row["account_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    for application in services.applications_of_account(service_account_id):
        if application["application_status"] not in services.TERMINAL:
            raise ApiError("ERR_ACCOUNT_HAS_INFLIGHT_APPLICATIONS")
    row["account_status"] = "CLOSED"
    touch(row)
    return envelope.ok(ser.service_account(row))
