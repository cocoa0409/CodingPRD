"""Boarding reservation endpoints."""

import math
from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_RESERVATION_NOT_FOUND, ERR_ANIMAL_NOT_FOUND,
                    ERR_SHELTER_NOT_FOUND, ERR_SHELTER_SUSPENDED,
                    ERR_INVALID_STATE, ERR_VACCINATION_NOT_COMPLIANT,
                    ERR_BOARDING_CAPACITY_FULL, ERR_BOARDING_DATE_OVERLAP,
                    ERR_COMPLIANCE_HOLD_ACTIVE, ERR_INVALID_DATES, ERR_INVALID_REQUEST)
from services.vaccination import check_vaccination_compliant
from services.compliance import has_active_high_critical_hold
from services.boarding import create_boarding_match, check_date_overlap
from services.fees import compute_boarding_fee, create_invoice, _parse_dt, recompute_shelter_revenue

bp = Blueprint("boarding_reservations", __name__)


def serialize_res(r):
    return {k: v for k, v in r.items()}


@bp.route("/boarding-reservations", methods=["POST"])
def create_reservation():
    user_id, role = require_role("CaseWorker")
    body = request.get_json(force=True, silent=True) or {}

    required = ["shelter_id", "animal_id", "owner_name", "owner_contact", "check_in_date", "check_out_date"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    shelter = db.shelters.get(body["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")

    animal = db.animals.get(body["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    if shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    # Validate dates
    ci = _parse_dt(body["check_in_date"])
    co = _parse_dt(body["check_out_date"])
    if co <= ci:
        raise_error(ERR_INVALID_DATES, "check_out_date must be after check_in_date")

    diff_seconds = (co - ci).total_seconds()
    duration_days = math.ceil(diff_seconds / 86400)
    if duration_days < 1:
        duration_days = 1

    ts = now_iso()
    reservation = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": body["shelter_id"],
        "animal_id": body["animal_id"],
        "owner_name": body["owner_name"],
        "owner_contact": body["owner_contact"],
        "check_in_date": body["check_in_date"],
        "check_out_date": body["check_out_date"],
        "actual_check_in": None,
        "actual_check_out": None,
        "duration_days": duration_days,
        "special_instructions": body.get("special_instructions", None),
        "boarding_match_id": None,
        "fee_invoice_id": None,
        "status": "REQUESTED",
    }
    db.boarding_reservations[reservation["id"]] = reservation
    return success_object(serialize_res(reservation), 201)


@bp.route("/boarding-reservations", methods=["GET"])
def list_reservations():
    require_role("ShelterManager", "CaseWorker")
    limit, offset = get_pagination()

    items = list(db.boarding_reservations.values())
    shelter_id = request.args.get("shelter_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    if shelter_id:
        items = [r for r in items if r["shelter_id"] == shelter_id]
    if animal_id:
        items = [r for r in items if r["animal_id"] == animal_id]
    if status:
        items = [r for r in items if r["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_res(r) for r in page], total, limit, offset)


@bp.route("/boarding-reservations/<reservationId>", methods=["GET"])
def get_reservation(reservationId):
    require_role("ShelterManager", "CaseWorker")
    res = db.boarding_reservations.get(reservationId)
    if not res:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    return success_object(serialize_res(res))


@bp.route("/boarding-reservations/<reservationId>/confirm", methods=["POST"])
def confirm_reservation(reservationId):
    user_id, role = require_role("ShelterManager")
    res = db.boarding_reservations.get(reservationId)
    if not res:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if res["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Reservation must be REQUESTED")

    shelter = db.shelters.get(res["shelter_id"])
    if shelter and shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    animal = db.animals.get(res["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    # Vaccination compliance (boarding-level)
    if not check_vaccination_compliant(res["animal_id"], for_boarding=True):
        raise_error(ERR_VACCINATION_NOT_COMPLIANT, "Animal vaccination not compliant for boarding")

    # Capacity check
    if shelter and shelter["current_boarding_count"] >= shelter["boarding_capacity"]:
        raise_error(ERR_BOARDING_CAPACITY_FULL, "Shelter boarding capacity full")

    # Date overlap check
    if check_date_overlap(res["animal_id"], res["check_in_date"], res["check_out_date"], exclude_reservation_id=res["id"]):
        raise_error(ERR_BOARDING_DATE_OVERLAP, "Date overlap with existing reservation")

    # Create boarding match
    match = create_boarding_match(res["id"], res["animal_id"], res["shelter_id"])
    res["boarding_match_id"] = match["id"]

    # Create fee invoice
    line_items, subtotal, tax_amount, discount_amount, total_amount, duration_days = compute_boarding_fee(
        res["shelter_id"], animal, res["check_in_date"], res["check_out_date"]
    )
    invoice = create_invoice(
        res["shelter_id"], "BOARDING", res["id"],
        line_items, subtotal, tax_amount, discount_amount, total_amount
    )
    res["fee_invoice_id"] = invoice["id"]

    res["status"] = "CONFIRMED"
    res["updated_at"] = now_iso()
    res["version"] += 1
    return success_object(serialize_res(res))


@bp.route("/boarding-reservations/<reservationId>/check-in", methods=["POST"])
def check_in_reservation(reservationId):
    user_id, role = require_role("CaseWorker")
    res = db.boarding_reservations.get(reservationId)
    if not res:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if res["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Reservation must be CONFIRMED")

    # Re-verify vaccination compliance at check-in time
    if not check_vaccination_compliant(res["animal_id"], for_boarding=True):
        raise_error(ERR_VACCINATION_NOT_COMPLIANT, "Animal vaccination not compliant")

    if has_active_high_critical_hold(res["animal_id"]):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Animal has active HIGH/CRITICAL compliance hold")

    ts = now_iso()
    res["actual_check_in"] = ts
    res["status"] = "CHECKED_IN"
    res["updated_at"] = ts
    res["version"] += 1

    # Increment shelter boarding count
    shelter = db.shelters.get(res["shelter_id"])
    if shelter:
        shelter["current_boarding_count"] = shelter.get("current_boarding_count", 0) + 1
        shelter["updated_at"] = ts
        shelter["version"] += 1

    # Animal -> BOARDING (if shelter-owned, i.e. has shelter_id)
    animal = db.animals.get(res["animal_id"])
    if animal and animal.get("shelter_id") == res["shelter_id"]:
        if animal["status"] == "AVAILABLE":
            animal["status"] = "BOARDING"
            animal["updated_at"] = ts
            animal["version"] += 1

    return success_object(serialize_res(res))


@bp.route("/boarding-reservations/<reservationId>/check-out", methods=["POST"])
def check_out_reservation(reservationId):
    user_id, role = require_role("CaseWorker")
    res = db.boarding_reservations.get(reservationId)
    if not res:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if res["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, "Reservation must be CHECKED_IN")

    ts = now_iso()
    res["actual_check_out"] = ts
    res["status"] = "CHECKED_OUT"
    res["updated_at"] = ts
    res["version"] += 1

    # Recompute duration from actual dates
    ci = _parse_dt(res["actual_check_in"])
    co = _parse_dt(ts)
    diff_seconds = (co - ci).total_seconds()
    actual_duration = math.ceil(diff_seconds / 86400)
    if actual_duration < 1:
        actual_duration = 1
    res["duration_days"] = actual_duration

    # Adjust fee invoice if duration differs
    if res.get("fee_invoice_id"):
        animal = db.animals.get(res["animal_id"])
        if animal:
            line_items, subtotal, tax_amount, discount_amount, total_amount, _ = compute_boarding_fee(
                res["shelter_id"], animal, res["actual_check_in"], ts
            )
            invoice = db.fee_invoices.get(res["fee_invoice_id"])
            if invoice:
                invoice["line_items"] = line_items
                invoice["subtotal"] = subtotal
                invoice["tax_amount"] = tax_amount
                invoice["discount_amount"] = discount_amount
                invoice["total_amount"] = total_amount
                invoice["balance_due"] = total_amount - invoice.get("paid_amount", 0.0) + invoice.get("refund_amount", 0.0)
                invoice["updated_at"] = ts
                invoice["version"] += 1

    # Decrement shelter boarding count
    shelter = db.shelters.get(res["shelter_id"])
    if shelter:
        shelter["current_boarding_count"] = max(0, shelter.get("current_boarding_count", 0) - 1)
        shelter["updated_at"] = ts
        shelter["version"] += 1

    # Animal -> AVAILABLE (if shelter-owned)
    animal = db.animals.get(res["animal_id"])
    if animal and animal.get("shelter_id") == res["shelter_id"]:
        if animal["status"] == "BOARDING":
            animal["status"] = "AVAILABLE"
            animal["updated_at"] = ts
            animal["version"] += 1
            from services.compliance import recompute_animal_eligibility
            recompute_animal_eligibility(animal["id"])

    return success_object(serialize_res(res))


@bp.route("/boarding-reservations/<reservationId>/cancel", methods=["POST"])
def cancel_reservation(reservationId):
    user_id, role = require_role("CaseWorker")
    res = db.boarding_reservations.get(reservationId)
    if not res:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if res["status"] not in ("REQUESTED", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, "Reservation must be REQUESTED or CONFIRMED to cancel")

    ts = now_iso()

    # Handle invoice
    if res.get("fee_invoice_id"):
        invoice = db.fee_invoices.get(res["fee_invoice_id"])
        if invoice:
            if invoice["status"] == "ISSUED":
                invoice["status"] = "VOID"
                invoice["updated_at"] = ts
                invoice["version"] += 1
            elif invoice["status"] == "PAID":
                invoice["refund_amount"] = invoice["paid_amount"]
                invoice["status"] = "REFUNDED"
                invoice["updated_at"] = ts
                invoice["version"] += 1
                recompute_shelter_revenue(res["shelter_id"])

    res["status"] = "CANCELLED"
    res["updated_at"] = ts
    res["version"] += 1
    return success_object(serialize_res(res))
