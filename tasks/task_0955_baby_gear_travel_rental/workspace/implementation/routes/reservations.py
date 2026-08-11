from flask import Blueprint, request

import calc
import services
from db import bump, create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import (ser_extension, ser_line, ser_reservation, ser_txn)
from util import parse_date
from validate import req_str

bp = Blueprint("reservations", __name__)


def _get_reservation(rid):
    r = store.reservations.get(rid)
    if r is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND", 404, "Reservation not found")
    return r


def _check_read_access(r, uid, role):
    if role == "Customer" and r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    if role == "HotelPartner" and r["hotel_partner_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation's hotel partner")


def _expected_version(b):
    v = b.get("expected_reservation_version")
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_reservation_version is required and must be an integer")
    return v


@bp.post("/reservations")
def create_reservation():
    uid, _ = require_roles("Customer")
    b = body()
    # Existence: the acting customer record, then body FKs left-to-right.
    customer = store.customers.get(uid)
    if customer is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    partner_id = b.get("hotel_partner_id")
    partner = None
    if partner_id is not None:
        if not isinstance(partner_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "hotel_partner_id must be a string")
        partner = store.partners.get(partner_id)
        if partner is None:
            raise ApiError("ERR_PARTNER_NOT_FOUND", 404, "Hotel partner not found")
    plan_id = b.get("insurance_plan_id")
    if plan_id is not None:
        if not isinstance(plan_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "insurance_plan_id must be a string")
        if plan_id not in store.plans:
            raise ApiError("ERR_PLAN_NOT_FOUND", 404, "Insurance plan not found")
    # Shape
    address = req_str(b, "delivery_address")
    zone = req_str(b, "zone_code")
    lines_in = b.get("lines")
    if not isinstance(lines_in, list) or not lines_in:
        raise ApiError("ERR_INVALID_REQUEST", 400, "lines must be a non-empty array")
    item_ids = []
    for entry in lines_in:
        if not isinstance(entry, dict) or not isinstance(entry.get("catalog_item_id"), str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "each line must name a catalog_item_id")
        item_id = entry["catalog_item_id"]
        if item_id not in store.catalog_items:
            raise ApiError("ERR_CATALOG_ITEM_NOT_FOUND", 404, "Catalog item not found")
        item_ids.append(item_id)
    start = parse_date(b.get("start_date"))
    end = parse_date(b.get("end_date"))
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "start_date and end_date must be YYYY-MM-DD")
    # Date sanity
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    # Structural: zone match, then partner standing
    if partner is not None:
        if partner["zone_code"] != zone:
            raise ApiError("ERR_ZONE_MISMATCH", 422,
                           "Reservation zone must equal the partner zone")
        if partner["status"] == "SUSPENDED":
            raise ApiError("ERR_PARTNER_SUSPENDED", 409, "Hotel partner is SUSPENDED")
    res = create_rec(store.reservations, {
        "customer_id": uid, "hotel_partner_id": partner_id,
        "delivery_address": address, "zone_code": zone,
        "start_date": start, "end_date": end, "insurance_plan_id": plan_id,
        "status": "QUOTED", "payment_status": "DEPOSIT_PENDING",
        "quoted_total_cents": 0, "gear_subtotal_cents": 0,
        "final_total_cents": None, "deposit_hold_cents": 0,
        "deposit_captured_cents": 0, "deposit_released_cents": 0,
        "late_fee_cents": 0, "extension_charge_cents": 0, "extension_days": 0,
        "commission_cents": 0, "returned_at": None})
    lines = []
    for item_id in item_ids:
        lines.append(create_rec(store.lines, {
            "reservation_id": res["id"], "catalog_item_id": item_id,
            "assigned_unit_id": None, "status": "PENDING",
            "unit_rate_cents": 0, "line_charge_cents": 0}))
    calc.compute_quote(res, lines)
    return ok_obj(ser_reservation(res), 201)


@bp.get("/reservations/<rid>")
def get_reservation(rid):
    uid, role = require_roles("Customer", "HotelPartner", "OperationsAdmin")
    r = _get_reservation(rid)
    _check_read_access(r, uid, role)
    return ok_obj(ser_reservation(r))


@bp.get("/reservations")
def list_reservations():
    uid, role = require_roles("Customer", "HotelPartner", "OperationsAdmin")
    recs = sorted_ords(list(store.reservations.values()))
    if role == "Customer":
        recs = [r for r in recs if r["customer_id"] == uid]
    elif role == "HotelPartner":
        recs = [r for r in recs if r["hotel_partner_id"] == uid]
    for param, field in (("customer_id", "customer_id"),
                         ("hotel_partner_id", "hotel_partner_id"),
                         ("insurance_plan_id", "insurance_plan_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, ser_reservation)


@bp.post("/reservations/<rid>/confirm")
def confirm_reservation(rid):
    uid, _ = require_roles("Customer")
    r = _get_reservation(rid)
    if r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    customer = store.customers[r["customer_id"]]
    services.confirm_reservation(r, customer)
    return ok_obj(ser_reservation(r))


@bp.post("/reservations/<rid>/cancel")
def cancel_reservation(rid):
    uid, role = require_roles("Customer", "OperationsAdmin")
    r = _get_reservation(rid)
    if role == "Customer" and r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    services.cancel_reservation(r)
    return ok_obj(ser_reservation(r))


@bp.post("/reservations/<rid>/amend-dates")
def amend_dates(rid):
    uid, _ = require_roles("Customer")
    r = _get_reservation(rid)
    if r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    b = body()
    start = parse_date(b.get("start_date"))
    end = parse_date(b.get("end_date"))
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "start_date and end_date must be YYYY-MM-DD")
    expected = _expected_version(b)
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    if r["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not QUOTED")
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_reservation_version does not match the current version")
    r["start_date"] = start
    r["end_date"] = end
    calc.compute_quote(r, services.lines_of(r["id"]))
    bump(r)
    return ok_obj(ser_reservation(r))


@bp.post("/reservations/<rid>/settle")
def settle_reservation(rid):
    require_roles("OperationsAdmin")
    r = _get_reservation(rid)
    services.settle_reservation(r)
    return ok_obj(ser_reservation(r))


@bp.get("/reservations/<rid>/deposit-transactions")
def deposit_transactions(rid):
    uid, role = require_roles("Customer", "OperationsAdmin")
    r = _get_reservation(rid)
    if role == "Customer" and r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    recs = sorted_ords([t for t in store.txns.values() if t["reservation_id"] == r["id"]])
    return paginate(recs, ser_txn)


@bp.get("/reservations/<rid>/extensions")
def list_extensions(rid):
    uid, role = require_roles("Customer", "OperationsAdmin")
    r = _get_reservation(rid)
    if role == "Customer" and r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    recs = services.extensions_of(r["id"])
    status = request.args.get("status")
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    return paginate(recs, ser_extension)


@bp.post("/reservations/<rid>/extensions")
def create_extension(rid):
    uid, _ = require_roles("Customer")
    r = _get_reservation(rid)
    if r["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    b = body()
    requested = parse_date(b.get("requested_end_date"))
    if requested is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "requested_end_date must be YYYY-MM-DD")
    expected = _expected_version(b)
    if requested <= r["end_date"]:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "requested_end_date must be after the current end_date")
    if r["status"] in ("SETTLED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is in a terminal state")
    if expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_reservation_version does not match the current version")
    # A new extension legitimately supersedes any prior PENDING one
    for ext in services.extensions_of(r["id"]):
        if ext["status"] == "PENDING":
            ext["status"] = "SUPERSEDED"
            bump(ext)
    rec = create_rec(store.extensions, {
        "reservation_id": r["id"], "requested_end_date": requested,
        "status": "PENDING", "extension_charge_cents": 0,
        "decided_by_user_id": None})
    bump(r)
    return ok_obj(ser_extension(rec), 201)


@bp.get("/reservation-lines")
def list_lines():
    uid, role = require_roles("Customer", "Inspector", "OperationsAdmin")
    recs = sorted_ords(list(store.lines.values()))
    if role == "Customer":
        own = {rid for rid, r in store.reservations.items() if r["customer_id"] == uid}
        recs = [l for l in recs if l["reservation_id"] in own]
    for param, field in (("reservation_id", "reservation_id"),
                         ("catalog_item_id", "catalog_item_id"),
                         ("assigned_unit_id", "assigned_unit_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [l for l in recs if l[field] == v]
    return paginate(recs, ser_line)
