"""Export control screenings and export licenses."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, pagination
from core import ApiError, dq, fmt_dt, fmt_instant, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch
from routes_orders import guard_embargo

from flask import Blueprint, request

bp = Blueprint("compliance", __name__)

D = Decimal
COMPLIANCE_READ = ("TradeComplianceOfficer", "ExportOpsCoordinator", "PlatformAdmin")
DETERMINATIONS = ("NLR", "LICENSE_REQUIRED", "PROHIBITED")
AUTHORITIES = ("BIS", "DDTC", "OFAC", "NATIONAL_OTHER")
ECCN_PATTERN = r"^[0-9][A-E][0-9]{3}$"


def screening_state_invalid(message="the screening state does not permit this"):
    raise ApiError("ERR_SCREENING_STATE_INVALID", 409, message)


@bp.get("/export-control-screenings")
def list_screenings():
    authenticate(COMPLIANCE_READ)
    limit, offset = pagination()
    rows = ordered(store.screenings)
    order_id = request.args.get("export_order_id")
    if order_id:
        rows = [r for r in rows if r["export_order_id"] == order_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    determination = request.args.get("license_determination")
    if determination:
        rows = [r for r in rows if r["license_determination"] == determination]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/export-control-screenings/<screening_id>")
def read_screening(screening_id):
    authenticate(COMPLIANCE_READ)
    row = require(store.screenings, screening_id, "ERR_SCREENING_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/export-control-screenings/<screening_id>/decision")
def record_decision(screening_id):
    caller = authenticate(("TradeComplianceOfficer",))
    screening = require(store.screenings, screening_id, "ERR_SCREENING_NOT_FOUND")
    body = valid.body()
    determination = valid.enum(body, "license_determination", DETERMINATIONS)
    eccn = valid.string(body, "eccn", required=False, pattern=ECCN_PATTERN,
                        min_len=5, max_len=5, default=None)
    hits = valid.integer(body, "denied_party_hits", required=False, minimum=0, default=0)
    notes = valid.string(body, "notes", required=False, max_len=2000, default=None)

    order = store.orders[screening["export_order_id"]]
    buyer = store.buyers[order["buyer_id"]]
    blocked_branch = hits > 0 or determination == "PROHIBITED"

    if blocked_branch:
        if screening["status"] == "INITIATED":
            if order["fulfillment_status"] not in ("COMPLIANCE_PENDING", "COMPLIANCE_BLOCKED"):
                ledgers.order_state_invalid()
        elif screening["status"] == "PENDING_LICENSE":
            if order["fulfillment_status"] != "COMPLIANCE_PENDING":
                ledgers.order_state_invalid()
        else:
            screening_state_invalid()
    else:
        if screening["status"] != "INITIATED":
            screening_state_invalid()
        if determination == "NLR":
            if order["fulfillment_status"] not in ("COMPLIANCE_PENDING", "COMPLIANCE_BLOCKED"):
                ledgers.order_state_invalid()
        else:
            if order["fulfillment_status"] != "COMPLIANCE_PENDING":
                ledgers.order_state_invalid()

    guard_embargo(buyer)
    if determination == "LICENSE_REQUIRED" and hits == 0 and not eccn:
        valid.bad("eccn is required for a LICENSE_REQUIRED determination")

    screening["decided_by_user_id"] = caller.user_id
    if eccn is not None:
        screening["eccn"] = eccn
    screening["denied_party_hits"] = hits
    if notes is not None:
        screening["notes"] = notes

    if blocked_branch:
        screening["license_determination"] = "PROHIBITED"
        screening["status"] = "BLOCKED"
        touch(screening)
        if order["fulfillment_status"] != "COMPLIANCE_BLOCKED":
            order["fulfillment_status"] = "COMPLIANCE_BLOCKED"
            touch(order)
        if hits > 0:
            buyer["restricted_party_flag"] = True
            buyer["restricted_party_reason"] = "DENIED_PARTY_SCREENING_HIT"
            touch(buyer)
            ledgers.restricted_party_cascade(buyer)
    elif determination == "NLR":
        screening["license_determination"] = "NLR"
        screening["status"] = "CLEARED"
        screening["cleared_at"] = fmt_instant(store.clock)
        touch(screening)
        order["fulfillment_status"] = "COMPLIANCE_CLEARED"
        touch(order)
    else:
        screening["license_determination"] = "LICENSE_REQUIRED"
        screening["status"] = "PENDING_LICENSE"
        touch(screening)
    return ok(serialize(screening))


def _buyer_of_license(license_row):
    screening = store.screenings.get(license_row["export_control_screening_id"])
    if screening is None:
        return None
    order = store.orders.get(screening["export_order_id"])
    return order["buyer_id"] if order is not None else None


@bp.post("/export-control-screenings/<screening_id>/licenses")
def record_license(screening_id):
    authenticate(("TradeComplianceOfficer",))
    screening = require(store.screenings, screening_id, "ERR_SCREENING_NOT_FOUND")
    body = valid.body()
    number = valid.string(body, "license_number", max_len=100)
    authority = valid.enum(body, "authority", AUTHORITIES)
    eccn = valid.string(body, "eccn", pattern=ECCN_PATTERN, min_len=5, max_len=5)
    from_raw, from_dt = valid.instant(body, "valid_from")
    to_raw, to_dt = valid.instant(body, "valid_to")
    value = valid.decimal(body, "licensed_value_usd", 2, minimum=0, exclusive_min=True)

    if to_dt <= from_dt:
        valid.inconsistent("valid_to must be strictly after valid_from")
    if screening["status"] != "PENDING_LICENSE":
        screening_state_invalid("a license may only be recorded on a PENDING_LICENSE case")
    if screening["eccn"] and eccn != screening["eccn"]:
        valid.bad("eccn must equal the screening's eccn")

    order = store.orders[screening["export_order_id"]]
    buyer_id = order["buyer_id"]
    for other in ordered(store.licenses):
        if other["status"] not in ("ISSUED", "ACTIVE", "EXHAUSTED"):
            continue
        if other["eccn"] != eccn or _buyer_of_license(other) != buyer_id:
            continue
        if from_dt <= other["_to_dt"] and other["_from_dt"] <= to_dt:
            raise ApiError("ERR_LICENSE_WINDOW_OVERLAP", 409,
                           "an overlapping license already exists")
    if any(l["license_number"] == number for l in store.licenses.values()):
        raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER", 409,
                       "license_number already exists")

    row = {
        "export_control_screening_id": screening["id"],
        "license_number": number,
        "authority": authority,
        "eccn": eccn,
        "valid_from": from_raw,
        "valid_to": to_raw,
        "licensed_value_usd": dq(value, 2),
        "consumed_value_usd": D("0.00"),
        "remaining_value_usd": dq(value, 2),
        "status": "ISSUED",
        "_from_dt": from_dt,
        "_to_dt": to_dt,
    }
    insert(store.licenses, row)
    return ok(serialize(row), 201)


@bp.post("/export-control-screenings/<screening_id>/clear-with-license")
def clear_with_license(screening_id):
    authenticate(("TradeComplianceOfficer",))
    screening = require(store.screenings, screening_id, "ERR_SCREENING_NOT_FOUND")
    body = valid.body()
    license_row = valid.fk(body, "export_license_id", store.licenses,
                           "ERR_LICENSE_NOT_FOUND")
    order = store.orders[screening["export_order_id"]]

    if screening["status"] != "PENDING_LICENSE":
        screening_state_invalid("the screening is not PENDING_LICENSE")
    if order["fulfillment_status"] != "COMPLIANCE_PENDING":
        ledgers.order_state_invalid()
    if license_row["eccn"] != screening["eccn"]:
        screening_state_invalid("the license eccn does not match the screening")
    if _buyer_of_license(license_row) != order["buyer_id"]:
        screening_state_invalid("the license belongs to a different buyer")
    if license_row["status"] not in ("ISSUED", "ACTIVE"):
        screening_state_invalid("the license is not ISSUED or ACTIVE")
    if not (license_row["_from_dt"] <= store.clock <= license_row["_to_dt"]):
        raise ApiError("ERR_LICENSE_NOT_VALID_AT_DATE", 409,
                       "the clock falls outside the license validity window")
    required = dq(order["ordered_goods_value_usd"], 2)
    if license_row["remaining_value_usd"] < required:
        raise ApiError("ERR_LICENSE_VALUE_EXHAUSTED", 409,
                       "the license has insufficient remaining value")

    screening["export_license_id"] = license_row["id"]
    screening["status"] = "CLEARED"
    screening["cleared_at"] = fmt_instant(store.clock)
    touch(screening)
    if license_row["status"] == "ISSUED":
        license_row["status"] = "ACTIVE"
        touch(license_row)
    order["fulfillment_status"] = "COMPLIANCE_CLEARED"
    touch(order)
    return ok(serialize(screening))


@bp.get("/export-licenses")
def list_licenses():
    authenticate(COMPLIANCE_READ)
    limit, offset = pagination()
    rows = ordered(store.licenses)
    screening_id = request.args.get("export_control_screening_id")
    if screening_id:
        rows = [r for r in rows if r["export_control_screening_id"] == screening_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    eccn = request.args.get("eccn")
    if eccn:
        rows = [r for r in rows if r["eccn"] == eccn]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/export-licenses/<export_license_id>")
def read_license(export_license_id):
    authenticate(COMPLIANCE_READ)
    row = require(store.licenses, export_license_id, "ERR_LICENSE_NOT_FOUND")
    return ok(serialize(row))
