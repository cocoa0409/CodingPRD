"""Perusal copies, buffered holds, and conversion (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_IN_GOOD_STANDING,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_FORMAT_NOT_AVAILABLE,
    ERR_PERUSAL_HOLD_CONFLICT,
    ERR_PERUSAL_NOT_ALLOWED,
    ERR_PERUSAL_REQUEST_NOT_FOUND,
    ERR_PERUSAL_REQUIRES_INSTITUTION,
    ERR_RENTAL_SET_NOT_FOUND,
    ERR_WORK_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_perusal, ser_sale
from services import get_or_404, maybe_restore_standing
from util import is_int, new_record, now_date, now_dt, touch
from routes.helpers import body, paginate, require_fields
from routes.rental_orders import create_order_record, do_reserve

bp = Blueprint("perusals", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")
INSTITUTION_KINDS = ("SCHOOL", "INSTITUTION")
FORMATS = ("PHYSICAL", "DIGITAL")
_LIVE_HOLD_STATUSES = ("APPROVED", "SHIPPED", "OVERDUE_PERUSAL")


@bp.post("/library/perusal-requests")
def create_perusal():
    require_auth("Customer", "LibraryClerk")
    data = body()
    require_fields(data, ["account_id", "work_id", "format"])
    account = db["customer_accounts"].get(data["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "CustomerAccount not found")
    work = db["works"].get(data["work_id"])
    if work is None:
        raise ApiError(ERR_WORK_NOT_FOUND, 404, "Work not found")
    # Institution-only privilege, enforced both at filing and at approval.
    if account["account_kind"] not in INSTITUTION_KINDS:
        raise ApiError(ERR_PERUSAL_REQUIRES_INSTITUTION, 422, "Perusals require SCHOOL/INSTITUTION accounts")
    if data["format"] not in FORMATS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid format")
    rec = new_record()
    rec.update(
        {
            "account_id": account["id"],
            "work_id": work["id"],
            "format": data["format"],
            "ship_date": None,
            "return_due_date": None,
            "hold_start": None,
            "hold_end": None,
            "converted_target_kind": "NONE",
            "converted_target_id": None,
            "status": "REQUESTED",
        }
    )
    db["perusal_requests"][rec["id"]] = rec
    return success_object(ser_perusal(rec), status=201)


@bp.get("/library/perusal-requests")
def list_perusals():
    require_auth(*ALL_ROLES)
    rows = list(db["perusal_requests"].values())
    for param in ("account_id", "work_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [p for p in rows if p[param] == v]
    return paginate(rows, ser_perusal)


@bp.get("/library/perusal-requests/<pid>")
def get_perusal(pid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("perusal_requests", pid, ERR_PERUSAL_REQUEST_NOT_FOUND)
    return success_object(ser_perusal(rec))


@bp.post("/library/perusal-requests/<pid>/approve")
def approve_perusal(pid):
    require_auth("LibraryClerk")
    rec = get_or_404("perusal_requests", pid, ERR_PERUSAL_REQUEST_NOT_FOUND)
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REQUESTED perusal may be approved")
    account = db["customer_accounts"].get(rec["account_id"])
    work = db["works"].get(rec["work_id"])
    publisher = db["publishers"].get(work["publisher_id"]) if work else None
    # Perusal eligibility: work allows it, work CATALOGED, publisher ACTIVE.
    if not work["perusal_allowed"] or work["status"] != "CATALOGED" or publisher["status"] != "ACTIVE":
        raise ApiError(ERR_PERUSAL_NOT_ALLOWED, 409, "Perusal not allowed for this work")
    # (7) license format
    if rec["format"] == "DIGITAL":
        if not publisher["allows_digital_perusal"] or work["license_format"] == "PRINT_ONLY":
            raise ApiError(ERR_LICENSE_FORMAT_NOT_AVAILABLE, 422, "Digital perusal not licensed")
    # (11) hold separation: closed intervals, adjacency forbidden.
    new_start = now_date()
    for other in db["perusal_requests"].values():
        if other["id"] == rec["id"] or other["work_id"] != rec["work_id"]:
            continue
        if other["status"] in _LIVE_HOLD_STATUSES and other["hold_end"] is not None:
            if not (new_start > other["hold_end"].date()):
                raise ApiError(ERR_PERUSAL_HOLD_CONFLICT, 409, "Perusal hold violates quarantine separation")
    # (16) standing gate
    if account is not None and account["standing"] != "GOOD":
        raise ApiError(ERR_ACCOUNT_NOT_IN_GOOD_STANDING, 409, "Account is not in good standing")
    # (17) institution-only
    if account is not None and account["account_kind"] not in INSTITUTION_KINDS:
        raise ApiError(ERR_PERUSAL_REQUIRES_INSTITUTION, 422, "Perusals require SCHOOL/INSTITUTION accounts")

    ship = now_dt()
    rec["ship_date"] = ship
    rec["return_due_date"] = ship + timedelta(days=calc.PERUSAL_WINDOW_DAYS)
    rec["hold_start"] = ship
    rec["hold_end"] = ship + timedelta(days=calc.PERUSAL_WINDOW_DAYS + calc.QUARANTINE_DAYS)
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(ser_perusal(rec))


@bp.post("/library/perusal-requests/<pid>/reject")
def reject_perusal(pid):
    require_auth("LibraryClerk")
    rec = get_or_404("perusal_requests", pid, ERR_PERUSAL_REQUEST_NOT_FOUND)
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REQUESTED perusal may be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(ser_perusal(rec))


@bp.post("/library/perusal-requests/<pid>/ship")
def ship_perusal(pid):
    require_auth("LibraryClerk")
    rec = get_or_404("perusal_requests", pid, ERR_PERUSAL_REQUEST_NOT_FOUND)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an APPROVED perusal may be shipped")
    rec["status"] = "SHIPPED"
    touch(rec)
    return success_object(ser_perusal(rec))


@bp.post("/library/perusal-requests/<pid>/record-return")
def record_return_perusal(pid):
    require_auth("ReturnsClerk")
    rec = get_or_404("perusal_requests", pid, ERR_PERUSAL_REQUEST_NOT_FOUND)
    if rec["status"] not in ("SHIPPED", "OVERDUE_PERUSAL"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SHIPPED or OVERDUE_PERUSAL perusal may be returned")
    rec["status"] = "RETURNED"
    touch(rec)
    account = db["customer_accounts"].get(rec["account_id"])
    if account is not None:
        maybe_restore_standing(account)  # restore GOOD when no other overdue items
    return success_object(ser_perusal(rec))


@bp.post("/library/perusal-requests/<pid>/convert")
def convert_perusal(pid):
    require_auth("LibraryClerk")
    rec = get_or_404("perusal_requests", pid, ERR_PERUSAL_REQUEST_NOT_FOUND)
    if rec["status"] != "SHIPPED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SHIPPED perusal may be converted")
    data = body()
    kind = data.get("converted_target_kind")
    if kind not in ("RENTAL", "PURCHASE"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "converted_target_kind must be RENTAL or PURCHASE")
    account = db["customer_accounts"].get(rec["account_id"])

    if kind == "RENTAL":
        require_fields(data, ["rental_set_id", "copies_requested", "checkout_date", "due_date"])
        rental_set = db["rental_sets"].get(data["rental_set_id"])
        if rental_set is None:
            raise ApiError(ERR_RENTAL_SET_NOT_FOUND, 404, "RentalSet not found")
        # Delegates to the full reservation chain of PRD 3.5.
        order = create_order_record(account, rental_set, data)
        do_reserve(order)
        target_id = order["id"]
    else:  # PURCHASE
        if account is not None and account["standing"] != "GOOD":
            raise ApiError(ERR_ACCOUNT_NOT_IN_GOOD_STANDING, 409, "Account is not in good standing")
        quantity = data.get("quantity", 1)
        if not is_int(quantity) or quantity < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400, "quantity must be an integer >= 1")
        work = db["works"].get(rec["work_id"])
        unit = calc.conversion_unit_price(work["sale_price_cents"], discounted=True)
        sale = new_record()
        sale.update(
            {
                "account_id": rec["account_id"],
                "work_id": rec["work_id"],
                "quantity": quantity,
                "unit_price_cents": unit,
                "total_cents": unit * quantity,
                "balance_due_cents": unit * quantity,
                "perusal_request_id": rec["id"],
                "status": "INVOICED",
            }
        )
        db["sale_records"][sale["id"]] = sale
        target_id = sale["id"]
        if account is not None:
            touch(account)  # exposure recompute

    rec["status"] = "CONVERTED"
    rec["converted_target_kind"] = kind
    rec["converted_target_id"] = target_id
    touch(rec)
    return success_object(ser_perusal(rec))
