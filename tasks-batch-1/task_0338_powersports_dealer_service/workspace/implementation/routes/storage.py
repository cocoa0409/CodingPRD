"""Storage bays and seasonal storage agreements (PRD 3.10)."""

from flask import Blueprint, request

import errors
import calculations as calc
from common import get_body, stamp_new, serialize, touch, paginate, as_int, as_bool, as_str
from db import db, parse_iso
from lookups import (
    get_storage_bay, get_storage_agreement, get_unit, get_customer,
)
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("storage", __name__)


# ---------------------------------------------------------------------------
# Storage bays
# ---------------------------------------------------------------------------
@bp.route("/storage-bays", methods=["POST"])
def create_bay():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    body = get_body()
    label = as_str(body, "label")
    for b in db.storage_bays.values():
        if b["label"] == label:
            errors.err(errors.ERR_DUPLICATE_RESOURCE, "Storage bay label already exists")
    rec = stamp_new({"label": label})
    db.storage_bays[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/storage-bays", methods=["GET"])
def list_bays():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    label = request.args.get("label")
    records = [b for b in db.storage_bays.values() if label is None or b["label"] == label]
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/storage-bays/<bid>", methods=["GET"])
def get_bay_route(bid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    rec = get_storage_bay(bid)
    return ok(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Storage agreements
# ---------------------------------------------------------------------------
@bp.route("/storage-agreements", methods=["POST"])
def create_agreement():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    body = get_body()
    # existence in declared order: unit_id, customer_id, storage_bay_id
    unit_id = as_str(body, "unit_id")
    get_unit(unit_id)
    customer_id = as_str(body, "customer_id")
    get_customer(customer_id)
    storage_bay_id = as_str(body, "storage_bay_id")
    get_storage_bay(storage_bay_id)

    period_start = as_str(body, "period_start")
    period_end = as_str(body, "period_end")
    start_dt = parse_iso(period_start)
    end_dt = parse_iso(period_end)
    if start_dt is None or end_dt is None:
        errors.err(errors.ERR_INVALID_REQUEST, "period_start/period_end must be valid timestamps")
    if not (end_dt > start_dt):
        errors.err(errors.ERR_INVALID_REQUEST, "period_end must be after period_start")
    monthly_rate = as_int(body, "monthly_rate_cents", minimum=0)
    includes_winterization = as_bool(body, "includes_winterization", default=False)

    rec = stamp_new({
        "unit_id": unit_id,
        "customer_id": customer_id,
        "storage_bay_id": storage_bay_id,
        "period_start": period_start,
        "period_end": period_end,
        "includes_winterization": includes_winterization,
        "monthly_rate_cents": monthly_rate,
        "storage_fee_cents": 0,
        "prep_repair_order_id": None,
        "status": "RESERVED",
    })
    db.storage_agreements[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/storage-agreements", methods=["GET"])
def list_agreements():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    f = request.args
    records = []
    for a in db.storage_agreements.values():
        if f.get("unit_id") is not None and a["unit_id"] != f.get("unit_id"):
            continue
        if f.get("customer_id") is not None and a["customer_id"] != f.get("customer_id"):
            continue
        if f.get("storage_bay_id") is not None and a["storage_bay_id"] != f.get("storage_bay_id"):
            continue
        if f.get("status") is not None and a["status"] != f.get("status"):
            continue
        if f.get("prep_repair_order_id") is not None and a.get("prep_repair_order_id") != f.get("prep_repair_order_id"):
            continue
        records.append(a)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/storage-agreements/<aid>", methods=["GET"])
def get_agreement_route(aid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    rec = get_storage_agreement(aid)
    return ok(serialize(rec), 200)


@bp.route("/storage-agreements/<aid>/check-in", methods=["POST"])
def check_in(aid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    agr = get_storage_agreement(aid)
    if agr["status"] != "RESERVED":
        errors.err(errors.ERR_INVALID_STATE, "Storage agreement is not RESERVED")

    # bay double-booking: half-open [start, end) overlap against CHECKED_IN
    start_dt = parse_iso(agr["period_start"])
    end_dt = parse_iso(agr["period_end"])
    for other in db.storage_agreements.values():
        if other["id"] == agr["id"]:
            continue
        if other["status"] != "CHECKED_IN":
            continue
        if other["storage_bay_id"] != agr["storage_bay_id"]:
            continue
        o_start = parse_iso(other["period_start"])
        o_end = parse_iso(other["period_end"])
        # half-open overlap: start < o_end and o_start < end
        if start_dt < o_end and o_start < end_dt:
            errors.err(errors.ERR_BAY_DOUBLE_BOOKED, "Storage bay is double-booked")

    agr["status"] = "CHECKED_IN"

    # winterization mints a prep repair order
    if agr.get("includes_winterization", False):
        prep = stamp_new({
            "unit_id": agr["unit_id"],
            "customer_id": agr["customer_id"],
            "technician_id": None,
            "appointment_start": agr["period_start"],
            "appointment_end": agr["period_end"],
            "is_warranty": False,
            "authorized_amount_cents": 0,
            "labor_total_cents": 0,
            "parts_total_cents": 0,
            "shop_supplies_cents": 0,
            "ro_total_cents": 0,
            "work_status": "OPEN",
            "billing_status": "UNBILLED",
        })
        db.repair_orders[prep["id"]] = prep
        agr["prep_repair_order_id"] = prep["id"]

    touch(agr)
    return ok(serialize(agr), 200)


@bp.route("/storage-agreements/<aid>/check-out", methods=["POST"])
def check_out(aid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    agr = get_storage_agreement(aid)
    if agr["status"] != "CHECKED_IN":
        errors.err(errors.ERR_INVALID_STATE, "Storage agreement is not CHECKED_IN")

    prep_id = agr.get("prep_repair_order_id")
    if prep_id:
        prep = db.repair_orders.get(prep_id)
        if prep is not None and prep["work_status"] not in ("WORK_COMPLETE", "CANCELLED"):
            errors.err(errors.ERR_PREP_RO_OPEN, "Winterization prep RO is not complete")

    agr["storage_fee_cents"] = calc.storage_fee(agr)
    agr["status"] = "CHECKED_OUT"
    touch(agr)
    return ok(serialize(agr), 200)


@bp.route("/storage-agreements/<aid>/cancel", methods=["POST"])
def cancel_agreement(aid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor"})
    agr = get_storage_agreement(aid)
    if agr["status"] != "RESERVED":
        errors.err(errors.ERR_INVALID_STATE, "Storage agreement is not RESERVED")
    agr["status"] = "CANCELLED"
    touch(agr)
    return ok(serialize(agr), 200)
