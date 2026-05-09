from decimal import Decimal
from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields, bump
from envelope import success, created
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_DUPLICATE_RENTAL,
    ERR_CABINET_OFFLINE, ERR_CABINET_UNDER_MAINTENANCE, ERR_NO_AVAILABLE_DEVICE,
    ERR_RETURN_FAILED, ERR_PRICING_NOT_CONFIGURED, ERR_REFUND_LIMIT_EXCEEDED,
    ERR_ABNORMAL_BORROW_PATTERN, ERR_DEPOSIT_INSUFFICIENT, ERR_WALLET_INSUFFICIENT,
)
from validation import need_body, require_str, occ_check
from serializers import serialize_rental
from common import to_money
from clock import clock
from services.cabinet_state import recompute_online_status, is_under_maintenance
from services.billing import (
    rental_fee, overdue_penalty, elapsed_hours,
    LOST_DEVICE_FEE, LOST_THRESHOLD_HOURS,
)
from services.cascade import create_repair_ticket
from services.settlements_calc import per_rental_partner_share

bp = Blueprint("rentals", __name__)

MIN_DEPOSIT = Decimal("99.00")
MIN_BORROW_BATTERY = 50
REFUND_LIMIT_30D = 5
BORROW_LIMIT_24H = 10


def _slot_at(cabinet_id: str, slot_index: int):
    for s in db.slots.values():
        if s["cabinet_id"] == cabinet_id and s["slot_index"] == slot_index:
            return s
    return None


def _pricing_for_city(city_code: str):
    for p in db.pricing_plans.values():
        if p["city_code"] == city_code:
            return p
    return None


def _provisional_billing(rental: dict) -> Decimal | None:
    """Compute provisional charged_amount for a rental in {ACTIVE, OVERDUE, STUCK}.
    Returns None if pricing plan not configured (shouldn't happen post-borrow).
    """
    cab = db.cabinets[rental["start_cabinet_id"]]
    plan = _pricing_for_city(cab["city_code"])
    if plan is None:
        return None
    end_time = clock.now()
    fee = rental_fee(rental["rented_at"], end_time, plan, final=False,
                     return_plan_city_code=None, start_city_code=cab["city_code"])
    total = fee
    if rental["rental_status"] == "OVERDUE":
        total = to_money(total + overdue_penalty(rental["rented_at"], end_time))
    return to_money(total)


def _has_active_rental(user_id: str) -> bool:
    for r in db.rentals.values():
        if r["user_id"] == user_id and r["rental_status"] in {"ACTIVE", "OVERDUE", "STUCK"}:
            return True
    return False


@bp.post("/rentals")
def borrow():
    uid, _ = require_role({"User"})
    body = need_body(request.get_json(silent=True))
    cabinet_id = require_str(body, "cabinet_id")

    cab = db.cabinets.get(cabinet_id)
    if cab is None:
        # cabinet_id is a body field (not a path param). Treat as invalid input.
        raise APIError(ERR_NOT_FOUND, 404, "Cabinet not found")

    user = db.users.get(uid)
    if user is None:
        # User-role X-User-ID must point to a real user; treat absence as auth-level forbidden.
        raise APIError(ERR_FORBIDDEN, 403, "Acting user does not exist")

    # Priority 5 — state. Not directly applicable here for the cabinet itself, but
    # we evaluate priority 6 (one active rental) here.
    # Priority 6: ERR_DUPLICATE_RENTAL
    if _has_active_rental(uid):
        raise APIError(ERR_DUPLICATE_RENTAL, 409, "User already has an active rental")

    # Priority 8: cabinet online
    recompute_online_status(cab)
    if cab["online_status"] != "ONLINE":
        raise APIError(ERR_CABINET_OFFLINE, 409, "Cabinet is offline")

    # Priority 9: maintenance window
    if is_under_maintenance(cabinet_id):
        raise APIError(ERR_CABINET_UNDER_MAINTENANCE, 409, "Cabinet under maintenance")

    # Priority 10: at least one available device with battery >= 50
    eligible = [
        d for d in db.devices.values()
        if d["status"] == "AVAILABLE"
        and d.get("current_cabinet_id") == cabinet_id
        and d["battery_level"] >= MIN_BORROW_BATTERY
    ]
    if not eligible:
        raise APIError(ERR_NO_AVAILABLE_DEVICE, 409, "No available device in cabinet")

    # Priority 13: pricing plan
    plan = _pricing_for_city(cab["city_code"])
    if plan is None:
        raise APIError(ERR_PRICING_NOT_CONFIGURED, 422, "Pricing plan not configured for city")

    # Priority 14: refund risk control (strict <)
    if user["refund_count_30d"] >= REFUND_LIMIT_30D:
        raise APIError(ERR_REFUND_LIMIT_EXCEEDED, 403, "Refund risk-control limit exceeded")

    # Priority 15: abnormal borrow pattern (strict <)
    if user["borrow_count_24h"] >= BORROW_LIMIT_24H:
        raise APIError(ERR_ABNORMAL_BORROW_PATTERN, 403, "Abnormal borrow pattern detected")

    # Priority 16: deposit
    if user["deposit_balance"] < MIN_DEPOSIT:
        raise APIError(ERR_DEPOSIT_INSUFFICIENT, 402, "Deposit balance below minimum")

    # Priority 17: wallet not in debt
    if user["wallet_balance"] < 0:
        raise APIError(ERR_WALLET_INSUFFICIENT, 402, "Wallet balance is negative")

    # Selector: ORDER BY battery_level DESC, tie-break ORDER BY device.id ASC
    eligible.sort(key=lambda d: (-d["battery_level"], d["id"]))
    chosen = eligible[0]

    # Find the slot housing this device.
    housing_slot = None
    if chosen.get("current_cabinet_id") is not None and chosen.get("current_slot_index") is not None:
        housing_slot = _slot_at(chosen["current_cabinet_id"], chosen["current_slot_index"])

    start_slot_index = chosen["current_slot_index"]

    chosen["status"] = "BORROWED"
    chosen["current_cabinet_id"] = None
    chosen["current_slot_index"] = None
    bump(chosen)

    if housing_slot is not None:
        housing_slot["slot_status"] = "EMPTY"
        housing_slot["device_id"] = None
        bump(housing_slot)

    cf = make_common_fields()
    rental = {
        **cf,
        "user_id": uid,
        "start_cabinet_id": cabinet_id,
        "start_slot_index": start_slot_index,
        "device_id": chosen["id"],
        "rented_at": cf["created_at"],
        "return_cabinet_id": None,
        "return_slot_index": None,
        "returned_at": None,
        "rental_status": "ACTIVE",
        "payment_status": "PENDING",
        "charged_amount": None,
        "refund_amount": None,
    }
    db.rentals[rental["id"]] = rental

    user["borrow_count_24h"] += 1
    bump(user)

    return created(serialize_rental(rental))


@bp.get("/rentals/<rental_id>")
def get_rental(rental_id):
    uid, role = require_role({"Admin", "User"})
    r = db.rentals.get(rental_id)
    if r is None:
        raise APIError(ERR_NOT_FOUND, 404, "Rental not found")
    if role == "User" and r["user_id"] != uid:
        raise APIError(ERR_FORBIDDEN, 403, "Cannot read another user's rental")

    out = serialize_rental(r)
    if r["rental_status"] in {"ACTIVE", "OVERDUE", "STUCK"}:
        prov = _provisional_billing(r)
        if prov is not None:
            out["charged_amount"] = float(format(prov, "f"))
    return success(out)


def _ownership_check_for_rental(uid: str, role: str, rental: dict) -> None:
    if role == "User" and rental["user_id"] != uid:
        raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this rental")


def _settle_partner_cascade_on_refund(rental: dict) -> None:
    """When a refund happens, if the rental's start_cabinet partner has an INVOICED Settlement
    covering rental.returned_at, that settlement.refund_adjustment increases by the per-rental partner share."""
    cab = db.cabinets.get(rental["start_cabinet_id"])
    if cab is None:
        return
    partner = db.location_partners.get(cab["location_partner_id"])
    if partner is None:
        return
    refund_share = per_rental_partner_share(rental, partner, basis="refund_amount")
    for s in db.settlements.values():
        if s["status"] != "INVOICED":
            continue
        if s["location_partner_id"] != partner["id"]:
            continue
        if not (s["period_start"] <= rental["returned_at"] < s["period_end"]):
            continue
        s["refund_adjustment"] = to_money(s["refund_adjustment"] + refund_share)
        s["partner_amount"] = to_money(s["partner_amount"] - refund_share)
        bump(s)


def _do_final_return(rental: dict, return_cabinet: dict) -> dict:
    """Perform the final-return side effects: device, slot, rental, billing, wallet."""
    # Selector: lowest slot_index EMPTY slot in the return cabinet.
    empty_slots = sorted(
        [s for s in db.slots.values() if s["cabinet_id"] == return_cabinet["id"] and s["slot_status"] == "EMPTY"],
        key=lambda s: s["slot_index"],
    )
    if not empty_slots:
        return _do_return_failure(rental, return_cabinet)

    chosen_slot = empty_slots[0]
    rental["return_cabinet_id"] = return_cabinet["id"]
    rental["return_slot_index"] = chosen_slot["slot_index"]
    rental["returned_at"] = clock.now()

    # Device → AVAILABLE; slot housing the device updated.
    device = db.devices[rental["device_id"]]
    device["status"] = "AVAILABLE"
    device["current_cabinet_id"] = return_cabinet["id"]
    device["current_slot_index"] = chosen_slot["slot_index"]
    bump(device)

    chosen_slot["slot_status"] = "OCCUPIED"
    chosen_slot["device_id"] = device["id"]
    bump(chosen_slot)

    # Final billing.
    start_cab = db.cabinets[rental["start_cabinet_id"]]
    plan = _pricing_for_city(start_cab["city_code"])
    fee = rental_fee(
        rental["rented_at"], rental["returned_at"], plan,
        final=True,
        return_plan_city_code=return_cabinet["city_code"],
        start_city_code=start_cab["city_code"],
    )
    total = fee
    if rental["rental_status"] == "OVERDUE":
        total = to_money(total + overdue_penalty(rental["rented_at"], rental["returned_at"]))
    rental["charged_amount"] = to_money(total)

    # Wallet debit.
    user = db.users[rental["user_id"]]
    user["wallet_balance"] = to_money(user["wallet_balance"] - rental["charged_amount"])
    bump(user)

    rental["rental_status"] = "RETURNED"
    rental["payment_status"] = "BILLED"
    bump(rental)
    return rental


def _do_return_failure(rental: dict, return_cabinet: dict) -> dict:
    """All slots in return_cabinet are non-empty: rental → STUCK, lowest-slot_index slot → STUCK,
    device → STUCK_IN_SLOT, RepairTicket auto-created. Raises ERR_RETURN_FAILED at end.
    """
    candidate_slots = sorted(
        [s for s in db.slots.values() if s["cabinet_id"] == return_cabinet["id"]],
        key=lambda s: s["slot_index"],
    )
    if candidate_slots:
        attempted = candidate_slots[0]
        attempted["slot_status"] = "STUCK"
        bump(attempted)

    rental["return_cabinet_id"] = return_cabinet["id"]
    rental["rental_status"] = "STUCK"
    bump(rental)

    device = db.devices[rental["device_id"]]
    device["status"] = "STUCK_IN_SLOT"
    bump(device)

    create_repair_ticket(
        target_type="DEVICE",
        target_id=device["id"],
        source="AUTO_ANOMALY",
        issue_code="STUCK_DEVICE",
    )
    raise APIError(ERR_RETURN_FAILED, 409, "Return failed; rental marked STUCK")


@bp.post("/rentals/<rental_id>/return")
def return_rental(rental_id):
    uid, role = require_role({"User"})
    rental = db.rentals.get(rental_id)
    if rental is None:
        raise APIError(ERR_NOT_FOUND, 404, "Rental not found")

    body = need_body(request.get_json(silent=True))
    return_cabinet_id = require_str(body, "return_cabinet_id")
    occ_check(rental, body)

    # Priority 5: state — must be ACTIVE or OVERDUE.
    if rental["rental_status"] not in {"ACTIVE", "OVERDUE"}:
        raise APIError(ERR_INVALID_STATE, 409, "Rental not in returnable state")

    # Priority 7: ownership.
    _ownership_check_for_rental(uid, role, rental)

    return_cabinet = db.cabinets.get(return_cabinet_id)
    if return_cabinet is None:
        raise APIError(ERR_NOT_FOUND, 404, "Return cabinet not found")

    # Priority 8: cabinet online
    recompute_online_status(return_cabinet)
    if return_cabinet["online_status"] != "ONLINE":
        raise APIError(ERR_CABINET_OFFLINE, 409, "Return cabinet is offline")

    # Priority 9: maintenance
    if is_under_maintenance(return_cabinet_id):
        raise APIError(ERR_CABINET_UNDER_MAINTENANCE, 409, "Return cabinet under maintenance")

    rental = _do_final_return(rental, return_cabinet)
    return success(serialize_rental(rental))


@bp.post("/rentals/<rental_id>/return-retry")
def return_retry(rental_id):
    uid, role = require_role({"User"})
    rental = db.rentals.get(rental_id)
    if rental is None:
        raise APIError(ERR_NOT_FOUND, 404, "Rental not found")
    body = need_body(request.get_json(silent=True))
    return_cabinet_id = require_str(body, "return_cabinet_id")
    occ_check(rental, body)

    # Priority 5: must be STUCK.
    if rental["rental_status"] != "STUCK":
        raise APIError(ERR_INVALID_STATE, 409, "Rental not in STUCK state")

    # Priority 7: ownership.
    _ownership_check_for_rental(uid, role, rental)

    return_cabinet = db.cabinets.get(return_cabinet_id)
    if return_cabinet is None:
        raise APIError(ERR_NOT_FOUND, 404, "Return cabinet not found")

    # Priority 8: cabinet online
    recompute_online_status(return_cabinet)
    if return_cabinet["online_status"] != "ONLINE":
        raise APIError(ERR_CABINET_OFFLINE, 409, "Return cabinet is offline")

    # Priority 9: maintenance
    if is_under_maintenance(return_cabinet_id):
        raise APIError(ERR_CABINET_UNDER_MAINTENANCE, 409, "Return cabinet under maintenance")

    # Cycle close: clear the previously STUCK slot/device, then advance through ACTIVE→RETURNED.
    device = db.devices[rental["device_id"]]
    if device["status"] == "STUCK_IN_SLOT":
        # clear stuck slot
        for s in db.slots.values():
            if s["slot_status"] == "STUCK" and s.get("device_id") in (None, device["id"]):
                # only clear the slot tied to the same cabinet as the prior failed return attempt
                # in our model the stuck slot has device_id None (we never wrote it during failure)
                pass
        # Clear any slot in any cabinet that is STUCK and tied to this device's prior return cabinet:
        prior_cab_id = rental.get("return_cabinet_id")
        if prior_cab_id is not None:
            for s in db.slots.values():
                if s["cabinet_id"] == prior_cab_id and s["slot_status"] == "STUCK":
                    s["slot_status"] = "EMPTY"
                    s["device_id"] = None
                    bump(s)
        device["status"] = "AVAILABLE"
        bump(device)

    # Now perform the ACTIVE-equivalent return into the (possibly different) return cabinet.
    rental["rental_status"] = "ACTIVE"
    bump(rental)
    rental = _do_final_return(rental, return_cabinet)
    return success(serialize_rental(rental))


@bp.post("/rentals/<rental_id>/refund")
def refund(rental_id):
    require_role({"Admin"})
    rental = db.rentals.get(rental_id)
    if rental is None:
        raise APIError(ERR_NOT_FOUND, 404, "Rental not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(rental, body)

    if not (rental["payment_status"] == "BILLED" and rental["rental_status"] == "RETURNED"):
        raise APIError(ERR_INVALID_STATE, 409, "Rental cannot be refunded in current state")

    rental["refund_amount"] = rental["charged_amount"]
    rental["payment_status"] = "REFUNDED"
    bump(rental)

    user = db.users[rental["user_id"]]
    user["wallet_balance"] = to_money(user["wallet_balance"] + rental["refund_amount"])
    user["refund_count_30d"] += 1
    bump(user)

    _settle_partner_cascade_on_refund(rental)
    return success(serialize_rental(rental))
