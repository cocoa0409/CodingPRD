"""MaterialRental routes."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_referenced_not_found, err_invalid_request, err_invalid_temporal,
    err_invalid_state, err_org_suspended, err_title_withdrawn, err_rental_kind_mismatch,
    err_deposit_not_held, err_rental_not_due_lost,
)
from middleware import require_roles, check_applicant_owner
from response import ok_object, ok_list, parse_pagination
from services import calculations
from services.serializers import rental_out

bp = Blueprint("rentals", __name__)


@bp.post("/licensing/rentals")
def create_rental():
    require_roles("MaterialsClerk")
    body = request.get_json(silent=True) or {}
    agreement_id = body.get("agreement_id")
    if not isinstance(agreement_id, str) or not agreement_id:
        raise err_invalid_request("agreement_id is required")
    g = db.agreements.get(agreement_id)
    if not g:
        raise err_referenced_not_found("agreement_id not found")
    scripts_qty = body.get("scripts_qty")
    scores_qty = body.get("scores_qty")
    if not isinstance(scripts_qty, int) or isinstance(scripts_qty, bool) or scripts_qty < 0:
        raise err_invalid_request("scripts_qty must be an integer >= 0")
    if not isinstance(scores_qty, int) or isinstance(scores_qty, bool) or scores_qty < 0:
        raise err_invalid_request("scores_qty must be an integer >= 0")
    due_raw = body.get("due_date")
    due = db.parse_ts(due_raw) if due_raw is not None else None
    if due is None:
        raise err_invalid_temporal("due_date must be a valid ISO8601 UTC datetime")
    if due <= db.clock_now():
        raise err_invalid_temporal("due_date must be in the future")
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to create a rental")
    title = db.titles[g["title_id"]]
    if title["status"] != "ACTIVE":
        raise err_title_withdrawn()
    if title["title_kind"] == "PLAY" and scores_qty > 0:
        raise err_rental_kind_mismatch("scores_qty must be 0 for PLAY titles")
    if scripts_qty + scores_qty < 1:
        raise err_rental_kind_mismatch("scripts_qty + scores_qty must be >= 1")
    now = db.clock_now()
    r = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "scripts_qty": scripts_qty,
        "scores_qty": scores_qty,
        "deposit_cents": title["rental_deposit_cents"],
        "deposit_status": "HELD",
        "due_date": due,
        "returned_at": None,
        "accrued_late_fee_cents": 0,
        "status": "RESERVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.rentals[r["id"]] = r
    return ok_object(rental_out(r), 201)


@bp.get("/licensing/rentals/<rental_id>")
def get_rental(rental_id):
    user_id, role = require_roles("RightsAdmin", "MaterialsClerk", "Applicant", "FinanceOfficer")
    r = db.rentals.get(rental_id)
    if not r:
        raise err_not_found("Rental not found")
    if role == "Applicant":
        g = db.agreements[r["agreement_id"]]
        check_applicant_owner(user_id, role, g["organization_id"])
    return ok_object(rental_out(r))


@bp.get("/licensing/rentals")
def list_rentals():
    require_roles("RightsAdmin", "MaterialsClerk", "FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    deposit_status = request.args.get("deposit_status")
    items = list(db.rentals.values())
    if agreement_id is not None:
        items = [r for r in items if r["agreement_id"] == agreement_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if deposit_status is not None:
        items = [r for r in items if r["deposit_status"] == deposit_status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([rental_out(r) for r in page], limit, offset, total)


@bp.post("/licensing/rentals/<rental_id>/ship")
def ship_rental(rental_id):
    require_roles("MaterialsClerk")
    r = db.rentals.get(rental_id)
    if not r:
        raise err_not_found("Rental not found")
    if r["status"] != "RESERVED":
        raise err_invalid_state("Rental must be RESERVED to ship")
    g = db.agreements[r["agreement_id"]]
    if g["license_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to ship")
    org = db.organizations[g["organization_id"]]
    if org["standing"] != "GOOD":
        raise err_org_suspended()
    if r["deposit_status"] != "HELD":
        raise err_deposit_not_held()
    r["status"] = "SHIPPED"
    r["updated_at"] = db.clock_now()
    r["version"] += 1
    return ok_object(rental_out(r))


@bp.post("/licensing/rentals/<rental_id>/mark_received")
def mark_received(rental_id):
    user_id, role = require_roles("Applicant")
    r = db.rentals.get(rental_id)
    if not r:
        raise err_not_found("Rental not found")
    g = db.agreements[r["agreement_id"]]
    check_applicant_owner(user_id, role, g["organization_id"])
    if r["status"] != "SHIPPED":
        raise err_invalid_state("Rental must be SHIPPED to mark received")
    r["status"] = "RECEIVED"
    r["updated_at"] = db.clock_now()
    r["version"] += 1
    return ok_object(rental_out(r))


@bp.post("/licensing/rentals/<rental_id>/ship_return")
def ship_return(rental_id):
    user_id, role = require_roles("Applicant")
    r = db.rentals.get(rental_id)
    if not r:
        raise err_not_found("Rental not found")
    g = db.agreements[r["agreement_id"]]
    check_applicant_owner(user_id, role, g["organization_id"])
    if r["status"] != "RECEIVED":
        raise err_invalid_state("Rental must be RECEIVED to ship return")
    r["status"] = "RETURN_IN_TRANSIT"
    r["updated_at"] = db.clock_now()
    r["version"] += 1
    return ok_object(rental_out(r))


@bp.post("/licensing/rentals/<rental_id>/receive_return")
def receive_return(rental_id):
    require_roles("MaterialsClerk")
    r = db.rentals.get(rental_id)
    if not r:
        raise err_not_found("Rental not found")
    if r["status"] not in ("RETURN_IN_TRANSIT", "OVERDUE"):
        raise err_invalid_state("Rental must be RETURN_IN_TRANSIT or OVERDUE to receive return")
    body = request.get_json(silent=True) or {}
    damage_lines = body.get("damage_lines", [])
    if not isinstance(damage_lines, list):
        raise err_invalid_request("damage_lines must be an array")
    for d in damage_lines:
        if not isinstance(d, dict):
            raise err_invalid_request("each damage line must be an object")
        amt = d.get("amount_cents")
        frac = d.get("damage_fraction")
        if not isinstance(amt, int) or isinstance(amt, bool) or amt < 0:
            raise err_invalid_request("damage line amount_cents must be an integer >= 0")
        if not isinstance(frac, (int, float)) or isinstance(frac, bool) or frac < 0:
            raise err_invalid_request("damage line damage_fraction must be a number >= 0")
    now = db.clock_now()
    g = db.agreements[r["agreement_id"]]
    title = db.titles[g["title_id"]]
    r["status"] = "RETURNED"
    r["returned_at"] = now
    fee = calculations.overdue_fine_cents(r, title, now)  # ACTUAL variant: evaluation clock = returned_at
    r["accrued_late_fee_cents"] = fee
    deposit_status, refund_cents, _ded = calculations.deposit_settlement(r, damage_lines, fee)
    r["deposit_status"] = deposit_status
    if fee > 0:
        f = {
            "id": db.new_id(),
            "organization_id": g["organization_id"],
            "rental_id": r["id"],
            "agreement_id": g["id"],
            "fine_kind": "OVERDUE_MATERIAL",
            "amount_cents": fee,
            "status": "ASSESSED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.fines[f["id"]] = f
    r["updated_at"] = now
    r["version"] += 1
    return ok_object(rental_out(r))


@bp.post("/licensing/rentals/<rental_id>/declare_lost")
def declare_lost(rental_id):
    require_roles("MaterialsClerk")
    r = db.rentals.get(rental_id)
    if not r:
        raise err_not_found("Rental not found")
    if r["status"] != "OVERDUE":
        raise err_invalid_state("Rental must be OVERDUE to declare lost")
    now = db.clock_now()
    from datetime import timedelta
    if now < r["due_date"] + timedelta(days=30):
        raise err_rental_not_due_lost()
    g = db.agreements[r["agreement_id"]]
    r["status"] = "LOST"
    r["deposit_status"] = "FORFEITED"
    # replacement_cost_rule: fine amount = deposit + accrued late fee
    amount = r["deposit_cents"] + r["accrued_late_fee_cents"]
    f = {
        "id": db.new_id(),
        "organization_id": g["organization_id"],
        "rental_id": r["id"],
        "agreement_id": g["id"],
        "fine_kind": "LOSS",
        "amount_cents": amount,
        "status": "ASSESSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.fines[f["id"]] = f
    r["updated_at"] = now
    r["version"] += 1
    return ok_object(rental_out(r))
