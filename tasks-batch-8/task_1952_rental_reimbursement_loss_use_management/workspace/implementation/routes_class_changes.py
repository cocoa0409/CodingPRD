"""Class change records (downgrade/upgrade cost responsibility)."""
from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import require_roles
from response import ok
from services import (bump, check_body_fk, claim_of_reservation, new_entity,
                      need_date, need_enum, opt_bool, require_claim_open, view)

bp = Blueprint("class_changes", __name__)

VEHICLE_CLASSES = ("ECONOMY", "STANDARD", "PREMIUM")


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/class-changes")
def create_class_change():
    require_roles(["RentalDeskAgent"])
    b = body()
    # rung 4: body FK existence
    check_body_fk(b, "reservation_id", db.reservations, "ERR_RESERVATION_NOT_FOUND")
    # shape
    reservation_id = b.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise bad_request("reservation_id is required")
    to_class = need_enum(b, "to_class", VEHICLE_CLASSES)
    effective = need_date(b, "effective_date")
    waiver = opt_bool(b, "upgrade_waiver", default=False)
    res = db.reservations[reservation_id]
    # shape: to_class must differ from the current class
    if to_class == res["vehicle_class"]:
        raise bad_request("to_class must differ from the current vehicle_class")
    claim = claim_of_reservation(res)
    # rung 6
    require_claim_open(claim)
    # rung 8
    if res["status"] not in ("AUTHORIZED", "ACTIVE", "EXTENSION_REVIEW"):
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "reservation must be AUTHORIZED, ACTIVE, or EXTENSION_REVIEW")
    # rung 10: effective_date inside the authorized window
    if not (res["pickup_date"] <= effective < res["authorized_return_date"]):
        raise api_error("ERR_INVALID_PERIOD", 400,
                        "effective_date must satisfy pickup_date <= effective_date < authorized_return_date")
    # class_change_cost_responsibility
    remaining_days = (res["authorized_return_date"] - effective).days
    snapshot = res["rate_card_snapshot"]
    from_class = res["vehicle_class"]
    from_rate = snapshot[from_class]
    to_rate = snapshot[to_class]
    limit = claim["coverage_daily_limit_cents"]
    if to_rate <= from_rate:
        # downgrade: insurer always benefits, customer owes nothing
        per_day_customer = 0
        customer_responsibility = 0
        insurer_delta = -(from_rate - to_rate) * remaining_days
    else:
        insurer_per_day = max(0, min(to_rate, limit) - min(from_rate, limit))
        if waiver:
            per_day_customer = 0
        else:
            per_day_customer = max(0, to_rate - max(limit, from_rate))
        customer_responsibility = per_day_customer * remaining_days
        insurer_delta = insurer_per_day * remaining_days
    e = new_entity(common_fields=False)
    e.update({
        "reservation_id": reservation_id,
        "from_class": from_class,
        "to_class": to_class,
        "effective_date": effective,
        "upgrade_waiver": waiver,
        "per_day_customer_cents": per_day_customer,
        "customer_responsibility_cents": customer_responsibility,
        "insurer_delta_cents": insurer_delta,
    })
    db.class_changes[e["id"]] = e
    res["vehicle_class"] = to_class
    res["daily_rate_cents"] = to_rate
    res["estimated_charge_cents"] += insurer_delta
    bump(res)
    bump(claim)
    return ok(view(e), status=201)
