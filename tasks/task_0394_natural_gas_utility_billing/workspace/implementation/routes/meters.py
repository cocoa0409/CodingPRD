"""Premise meter endpoints (PRD §3.2)."""

from flask import Blueprint

from db import store
from errors import ERR_DUPLICATE, ERR_INVALID_STATE, ERR_VALIDATION_PENDING_BILLS, err
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    optional_enum,
    optional_number,
    attach_common_fields,
    bump,
    paginate,
)
from services.serialize import view_meter
from services import lookup

bp = Blueprint("meters", __name__)


@bp.route("/accounts/<account_id>/meters", methods=["POST"])
def register_meter(account_id):
    principal = authenticate()
    require_role(principal, {"CustomerService", "FieldTech"})
    with store.lock:
        account = lookup.get_account(account_id)
        body = get_body()
        require_fields(body, ["serial_no"])
        serial_no = require_string(body, "serial_no")
        uom = optional_enum(body, "uom", {"CCF", "THERM"}, default="CCF")
        install_index = optional_number(body, "install_index", minimum=0)
        if install_index is None:
            install_index = 0

        for m in store.meters.values():
            if m["serial_no"] == serial_no:
                raise err(ERR_DUPLICATE, "Meter serial_no already exists")

        rec = {
            "account_id": account_id,
            "serial_no": serial_no,
            "uom": uom,
            "status": "PENDING_SET",
            "install_index": install_index,
        }
        attach_common_fields(rec)
        store.meters[rec["id"]] = rec
        return success(view_meter(rec), 201)


@bp.route("/accounts/<account_id>/meters", methods=["GET"])
def list_meters(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    account = lookup.get_account(account_id)
    require_account_ownership(principal, account_id)
    records = lookup.account_meters(account_id)
    page, list_meta = paginate(records)
    return success([view_meter(m) for m in page], 200, list_meta=list_meta)


@bp.route("/meters/<meter_id>", methods=["GET"])
def get_meter(meter_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    meter = lookup.get_meter(meter_id)
    require_account_ownership(principal, meter["account_id"])
    return success(view_meter(meter), 200)


@bp.route("/meters/<meter_id>/remove", methods=["POST"])
def remove_meter(meter_id):
    principal = authenticate()
    require_role(principal, {"FieldTech"})
    with store.lock:
        meter = lookup.get_meter(meter_id)
        status = meter["status"]
        if status == "SET":
            # Reject when a DRAFT bill references an unconsumed read on this meter.
            if _has_draft_with_unconsumed_read(meter_id):
                raise err(ERR_VALIDATION_PENDING_BILLS, "Draft bill references an unconsumed read on this meter")
        elif status == "LOCKED":
            pass  # unconditional
        else:
            raise err(ERR_INVALID_STATE, "Meter cannot be removed from its current state")
        meter["status"] = "REMOVED"
        bump(meter)
        return success(view_meter(meter), 200)


def _has_draft_with_unconsumed_read(meter_id):
    for b in store.bills.values():
        if b["status"] != "DRAFT":
            continue
        to_read_id = b.get("to_read_id")
        if not to_read_id:
            continue
        read = store.meter_reads.get(to_read_id)
        if read is None:
            continue
        if read["premise_meter_id"] == meter_id and read.get("bill_id") is None:
            return True
    return False
