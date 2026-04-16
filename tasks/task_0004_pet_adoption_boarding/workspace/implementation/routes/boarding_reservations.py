from flask import Blueprint, request
from datetime import timedelta
from db import (
    boarding_reservations,
    boarding_matches,
    animals,
    shelters,
    fee_invoices,
    gen_id,
    now_iso,
    utc_now,
    parse_iso,
)
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATES,
    ERR_SHELTER_NOT_FOUND,
    ERR_ANIMAL_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_BOARDING_MATCH_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SHELTER_SUSPENDED,
    ERR_VACCINATION_NOT_COMPLIANT,
    ERR_COMPLIANCE_HOLD_ACTIVE,
    ERR_BOARDING_CAPACITY_FULL,
    ERR_BOARDING_DATE_OVERLAP,
    ERR_TOO_EARLY_TO_CHECK_IN,
)
from middleware import require_roles, parse_pagination
from response import success_response, list_response
from services.animal_service import (
    vaccination_compliant,
    has_active_high_critical_hold,
)
from services.boarding_service import (
    serialize_reservation,
    serialize_boarding_match,
    compute_planned_duration_days,
    compute_actual_duration_days,
    compute_boarding_zone,
    compute_compatibility,
    reservations_overlap,
)
from services.fee_service import compute_boarding_fee, serialize_invoice

reservations_bp = Blueprint("reservations", __name__)
boarding_matches_bp = Blueprint("boarding_matches", __name__)


@reservations_bp.route("/petcare/boarding-reservations", methods=["POST"])
def create_reservation():
    require_roles("CaseWorker")
    body = request.get_json(silent=True) or {}

    shelter_id = body.get("shelter_id")
    animal_id = body.get("animal_id")
    owner_name = body.get("owner_name")
    owner_contact = body.get("owner_contact")
    check_in_date = body.get("check_in_date")
    check_out_date = body.get("check_out_date")
    special_instructions = body.get("special_instructions")

    if not shelter_id:
        raise_error(ERR_INVALID_REQUEST, "shelter_id is required")
    if not animal_id:
        raise_error(ERR_INVALID_REQUEST, "animal_id is required")
    if not owner_name or not isinstance(owner_name, str):
        raise_error(ERR_INVALID_REQUEST, "owner_name is required")
    if not owner_contact or not isinstance(owner_contact, str):
        raise_error(ERR_INVALID_REQUEST, "owner_contact is required")
    if not check_in_date:
        raise_error(ERR_INVALID_REQUEST, "check_in_date is required")
    if not check_out_date:
        raise_error(ERR_INVALID_REQUEST, "check_out_date is required")

    if shelter_id not in shelters:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    animal = animals.get(animal_id)
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    shelter = shelters[shelter_id]
    if shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    ci = parse_iso(check_in_date)
    co = parse_iso(check_out_date)
    if ci is None or co is None:
        raise_error(ERR_INVALID_DATES, "Invalid dates")
    if co <= ci:
        raise_error(ERR_INVALID_DATES, "check_out_date must be strictly greater than check_in_date")
    now = utc_now()
    # check_in_date >= the day of submission: compare date components
    if ci.date() < now.date():
        raise_error(ERR_INVALID_DATES, "check_in_date must be >= current day")

    rid = gen_id()
    ts = now_iso()
    reservation = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter_id,
        "animal_id": animal_id,
        "owner_name": owner_name,
        "owner_contact": owner_contact,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "actual_check_in": None,
        "actual_check_out": None,
        "special_instructions": special_instructions,
        "boarding_match_id": None,
        "fee_invoice_id": None,
        "status": "REQUESTED",
    }
    boarding_reservations[rid] = reservation
    return success_response(serialize_reservation(reservation), status_code=201)


@reservations_bp.route("/petcare/boarding-reservations", methods=["GET"])
def list_reservations():
    require_roles("ShelterManager", "CaseWorker")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    items = []
    for r in boarding_reservations.values():
        if shelter_id and r["shelter_id"] != shelter_id:
            continue
        if animal_id and r["animal_id"] != animal_id:
            continue
        if status and r["status"] != status:
            continue
        items.append(r)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_reservation(x) for x in page], total, limit, offset)


@reservations_bp.route("/petcare/boarding-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_roles("ShelterManager", "CaseWorker")
    r = boarding_reservations.get(rid)
    if not r:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    return success_response(serialize_reservation(r))


@reservations_bp.route("/petcare/boarding-reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    require_roles("ShelterManager")
    r = boarding_reservations.get(rid)
    if not r:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if r["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Reservation must be REQUESTED")

    shelter = shelters.get(r["shelter_id"])
    if not shelter or shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    animal = animals.get(r["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    if not vaccination_compliant(animal, "boarding"):
        raise_error(ERR_VACCINATION_NOT_COMPLIANT, "Animal not boarding-compliant")

    if has_active_high_critical_hold(animal["id"]):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Animal has HIGH/CRITICAL hold")

    # Capacity check: CONFIRMED + CHECKED_IN at shelter < capacity
    busy_count = sum(1 for x in boarding_reservations.values()
                      if x["shelter_id"] == r["shelter_id"]
                      and x["status"] in ("CONFIRMED", "CHECKED_IN"))
    if busy_count >= shelter["boarding_capacity"]:
        raise_error(ERR_BOARDING_CAPACITY_FULL, "Shelter at boarding capacity")

    # Overlap check for the same animal
    for other in boarding_reservations.values():
        if other["id"] == r["id"]:
            continue
        if other["animal_id"] != r["animal_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        if reservations_overlap(r["check_in_date"], r["check_out_date"],
                                 other["check_in_date"], other["check_out_date"]):
            raise_error(ERR_BOARDING_DATE_OVERLAP, "Animal already has overlapping reservation")

    # Create boarding match
    score, conflicts = compute_compatibility(animal, r["shelter_id"])
    zone = compute_boarding_zone(animal)
    match_id = gen_id()
    ts = now_iso()
    match = {
        "id": match_id,
        "created_at": ts,
        "reservation_id": r["id"],
        "animal_id": animal["id"],
        "shelter_id": r["shelter_id"],
        "compatibility_score": score,
        "boarding_zone": zone,
        "conflict_flags": conflicts,
        "voided_at": None,
    }
    boarding_matches[match_id] = match

    # Create boarding fee invoice (provisional)
    duration = compute_planned_duration_days(r["check_in_date"], r["check_out_date"]) or 0
    fee = compute_boarding_fee(animal, shelter, duration)
    inv_id = gen_id()
    invoice = {
        "id": inv_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter["id"],
        "reference_type": "BOARDING",
        "reference_id": r["id"],
        "line_items": fee["line_items"],
        "subtotal_cents": fee["subtotal_cents"],
        "discount_cents": fee["discount_cents"],
        "tax_cents": fee["tax_cents"],
        "total_amount_cents": fee["total_amount_cents"],
        "paid_amount_cents": 0,
        "refund_amount_cents": 0,
        "settlement_batch_id": None,
        "status": "ISSUED",
        "paid_at": None,
        "refunded_at": None,
    }
    fee_invoices[inv_id] = invoice

    r["status"] = "CONFIRMED"
    r["boarding_match_id"] = match_id
    r["fee_invoice_id"] = inv_id
    r["updated_at"] = now_iso()
    r["version"] += 1

    return success_response(serialize_reservation(r))


@reservations_bp.route("/petcare/boarding-reservations/<rid>/check-in", methods=["POST"])
def check_in_reservation(rid):
    require_roles("CaseWorker")
    r = boarding_reservations.get(rid)
    if not r:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if r["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Reservation must be CONFIRMED")
    animal = animals.get(r["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    if not vaccination_compliant(animal, "boarding"):
        raise_error(ERR_VACCINATION_NOT_COMPLIANT, "Animal not boarding-compliant")
    if has_active_high_critical_hold(animal["id"]):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Animal has HIGH/CRITICAL hold")
    now = utc_now()
    ci = parse_iso(r["check_in_date"])
    if now < ci:
        raise_error(ERR_TOO_EARLY_TO_CHECK_IN, "Current time is before check_in_date")

    r["status"] = "CHECKED_IN"
    r["actual_check_in"] = now_iso()
    r["updated_at"] = now_iso()
    r["version"] += 1

    if animal["status"] == "AVAILABLE":
        animal["status"] = "BOARDING"
        animal["updated_at"] = now_iso()
        animal["version"] += 1

    return success_response(serialize_reservation(r))


@reservations_bp.route("/petcare/boarding-reservations/<rid>/check-out", methods=["POST"])
def check_out_reservation(rid):
    require_roles("CaseWorker")
    r = boarding_reservations.get(rid)
    if not r:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if r["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, "Reservation must be CHECKED_IN")

    r["actual_check_out"] = now_iso()
    r["status"] = "CHECKED_OUT"
    r["updated_at"] = now_iso()
    r["version"] += 1

    # Recompute boarding invoice with actual duration
    animal = animals.get(r["animal_id"])
    shelter = shelters.get(r["shelter_id"])
    inv_id = r.get("fee_invoice_id")
    invoice = fee_invoices.get(inv_id) if inv_id else None
    if invoice and animal and shelter:
        actual_duration = compute_actual_duration_days(r["actual_check_in"], r["actual_check_out"]) or 0
        fee = compute_boarding_fee(animal, shelter, actual_duration)
        line_items = list(fee["line_items"])
        new_total = fee["total_amount_cents"]

        old_paid = invoice["paid_amount_cents"]

        if old_paid > new_total:
            # Record credit line with negative amount; move to PAID with paid = new_total
            credit_amount = old_paid - new_total
            line_items.append({
                "description": "Overpayment credit",
                "quantity": 1,
                "unit_price_cents": -credit_amount,
                "amount_cents": -credit_amount,
            })
            invoice["paid_amount_cents"] = new_total
            invoice["status"] = "PAID"
            invoice["paid_at"] = now_iso()
        else:
            # Normal recompute; status stays or adjusts based on paid vs new total
            if invoice["status"] in ("ISSUED", "PARTIALLY_PAID"):
                if old_paid == 0:
                    invoice["status"] = "ISSUED"
                elif old_paid >= new_total:
                    invoice["status"] = "PAID"
                    invoice["paid_amount_cents"] = new_total
                    invoice["paid_at"] = now_iso()
                else:
                    invoice["status"] = "PARTIALLY_PAID"

        invoice["line_items"] = line_items
        invoice["subtotal_cents"] = fee["subtotal_cents"]
        invoice["discount_cents"] = fee["discount_cents"]
        invoice["tax_cents"] = fee["tax_cents"]
        invoice["total_amount_cents"] = new_total
        invoice["updated_at"] = now_iso()
        invoice["version"] += 1

    if animal and animal["status"] == "BOARDING":
        animal["status"] = "AVAILABLE"
        animal["updated_at"] = now_iso()
        animal["version"] += 1

    return success_response(serialize_reservation(r))


@reservations_bp.route("/petcare/boarding-reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    require_roles("ShelterManager")
    r = boarding_reservations.get(rid)
    if not r:
        raise_error(ERR_RESERVATION_NOT_FOUND, "Reservation not found")
    if r["status"] not in ("REQUESTED", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, "Reservation must be REQUESTED or CONFIRMED")

    r["status"] = "CANCELLED"
    r["updated_at"] = now_iso()
    r["version"] += 1

    match_id = r.get("boarding_match_id")
    if match_id:
        match = boarding_matches.get(match_id)
        if match:
            match["voided_at"] = now_iso()

    inv_id = r.get("fee_invoice_id")
    if inv_id:
        invoice = fee_invoices.get(inv_id)
        if invoice and invoice["status"] == "ISSUED":
            invoice["status"] = "VOID"
            invoice["updated_at"] = now_iso()
            invoice["version"] += 1

    return success_response(serialize_reservation(r))


@boarding_matches_bp.route("/petcare/boarding-matches/<match_id>", methods=["GET"])
def get_boarding_match(match_id):
    require_roles("ShelterManager", "CaseWorker")
    match = boarding_matches.get(match_id)
    if not match:
        raise_error(ERR_BOARDING_MATCH_NOT_FOUND, "Boarding match not found")
    return success_response(serialize_boarding_match(match))
