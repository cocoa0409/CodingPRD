"""Rental ramp endpoints."""
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, get_unit_or_404,
    require_case_active, req_str, req_dt, opt_int, now, now_iso, iso,
)
from domain import (
    mutate_case, rental_rate_and_deposit, rental_prorated_amount,
    make_invoice_number, ACTIVE_RENTAL_STATUSES,
)

bp = Blueprint("rentals", __name__)


def _get_ramp(case_id, ramp_id):
    case = get_case_or_404(case_id)
    ramp = get_child_or_404("rental_ramps", ramp_id, "case_id", case_id,
                            "ERR_RAMP_NOT_FOUND", "Rental ramp")
    return case, ramp


def _final_invoice_for_unbilled(case, ramp, through_dt):
    """Generate a RENTAL_FINAL invoice (DRAFT) for the unbilled tail period."""
    last = ramp.get("_last_billed_dt") or ramp["_rental_start_dt"]
    days = (through_dt - last).days
    if days <= 0:
        return None
    amount = rental_prorated_amount(ramp["monthly_rate_cents"], days, through_dt)
    if amount <= 0:
        return None
    from datetime import timedelta
    inv = new_record()
    inv.update({
        "case_id": case["id"],
        "invoice_number": make_invoice_number(),
        "invoice_type": "RENTAL_FINAL",
        "status": "DRAFT",
        "issue_date": None,
        "due_date": iso(through_dt + timedelta(days=30)),
        "paid_date": None,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "balance_cents": 0,
        "funding_source_id": None,
        "quote_id": None,
        "rental_ramp_id": ramp["id"],
        "_due_date_dt": through_dt + timedelta(days=30),
    })
    db["invoices"][inv["id"]] = inv
    line = new_record()
    line.update({
        "invoice_id": inv["id"],
        "description": f"Rental final period ({days} days)",
        "quantity": 1.0,
        "unit_price_cents": amount,
        "extended_price_cents": amount,
        "tax_cents": 0,
        "line_total_cents": amount,
        "period_start": iso(last),
        "period_end": iso(through_dt),
    })
    db["invoice_line_items"][line["id"]] = line
    inv["subtotal_cents"] = amount
    inv["total_cents"] = amount
    inv["balance_cents"] = amount
    ramp["last_billed_date"] = iso(through_dt)
    ramp["_last_billed_dt"] = through_dt
    return inv


@bp.route("/cases/<caseId>/rental-ramps", methods=["POST"])
def create_rental(caseId):
    require_roles("LogisticsCoordinator")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    unit_id = req_str(b, "inventory_unit_id")
    rental_start = req_dt(b, "rental_start")
    rental_end = req_dt(b, "rental_end")
    billing_day = opt_int(b, "billing_cycle_day", 1)
    if rental_end <= rental_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "rental_end must be after rental_start")
    unit = get_unit_or_404(unit_id)

    # (8) Clinical guard: purchase_required on the latest completed assessment.
    completed = [a for a in db["assessments"].values()
                 if a["case_id"] == caseId and a["status"] == "COMPLETED"]
    if completed:
        latest = max(completed, key=lambda a: a["_seq"])
        if latest.get("purchase_required"):
            raise ApiError("ERR_RENTAL_NOT_CLINICALLY_INDICATED", 422,
                           "Assessment indicates purchase is required, "
                           "rental not appropriate")
    # (13) Overlap guard: no overlapping active rental of the same unit.
    for r in db["rental_ramps"].values():
        if r["inventory_unit_id"] == unit_id and r["status"] in ACTIVE_RENTAL_STATUSES:
            if rental_start < r["_rental_end_dt"] and r["_rental_start_dt"] < rental_end:
                raise ApiError("ERR_UNIT_UNAVAILABLE", 409,
                               "Inventory unit is not available for the "
                               "requested rental period")
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_UNAVAILABLE", 409,
                       "Inventory unit is not available for the requested "
                       "rental period")

    rate, deposit = rental_rate_and_deposit(unit, rental_start, rental_end)
    rec = new_record()
    rec.update({
        "case_id": caseId,
        "inventory_unit_id": unit_id,
        "status": "RESERVED",
        "rental_start": iso(rental_start),
        "rental_end": iso(rental_end),
        "actual_pickup": None,
        "monthly_rate_cents": rate,
        "deposit_cents": deposit,
        "deposit_status": "HELD",
        "billing_cycle_day": billing_day,
        "last_billed_date": iso(rental_start),
        "_rental_start_dt": rental_start,
        "_rental_end_dt": rental_end,
        "_last_billed_dt": rental_start,
    })
    db["rental_ramps"][rec["id"]] = rec
    unit["status"] = "RESERVED"
    touch(unit)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/rental-ramps", methods=["GET"])
def list_rentals(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [r for r in db["rental_ramps"].values() if r["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/rental-ramps/<rampId>", methods=["GET"])
def get_rental(caseId, rampId):
    require_roles()
    _case, ramp = _get_ramp(caseId, rampId)
    return ok_object(serialize(ramp))


@bp.route("/cases/<caseId>/rental-ramps/<rampId>/deliver", methods=["POST"])
def deliver_rental(caseId, rampId):
    require_roles("LogisticsCoordinator")
    case, ramp = _get_ramp(caseId, rampId)
    require_case_active(case)
    if ramp["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Rental must be RESERVED to deliver")
    unit = get_unit_or_404(ramp["inventory_unit_id"])
    if unit["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Inventory unit must be RESERVED to deliver")
    if now() < ramp["_rental_start_dt"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Rental period has not started")
    ramp["status"] = "DELIVERED"
    touch(ramp)
    unit["status"] = "DEPLOYED"
    unit["current_case_id"] = caseId
    touch(unit)
    return ok_object(serialize(ramp))


@bp.route("/cases/<caseId>/rental-ramps/<rampId>/install", methods=["POST"])
def install_rental(caseId, rampId):
    require_roles("CrewLead")
    case, ramp = _get_ramp(caseId, rampId)
    require_case_active(case)
    if ramp["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Rental must be DELIVERED to install")
    ramp["status"] = "INSTALLED"
    touch(ramp)
    return ok_object(serialize(ramp))


@bp.route("/cases/<caseId>/rental-ramps/<rampId>/schedule-pickup", methods=["POST"])
def schedule_pickup(caseId, rampId):
    require_roles("LogisticsCoordinator")
    case, ramp = _get_ramp(caseId, rampId)
    require_case_active(case)
    if ramp["status"] not in ("IN_USE", "INSTALLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Rental must be IN_USE or INSTALLED to schedule pickup")
    ramp["status"] = "PICKUP_SCHEDULED"
    touch(ramp)
    return ok_object(serialize(ramp))


@bp.route("/cases/<caseId>/rental-ramps/<rampId>/confirm-pickup", methods=["POST"])
def confirm_pickup(caseId, rampId):
    require_roles("LogisticsCoordinator")
    case, ramp = _get_ramp(caseId, rampId)
    require_case_active(case)
    if ramp["status"] != "PICKUP_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Rental must be PICKUP_SCHEDULED to confirm pickup")
    b = body()
    ts = now()
    forfeit = False
    for key in ("forfeit_deposit", "deposit_forfeited"):
        v = b.get(key)
        if isinstance(v, bool) and v:
            forfeit = True
    cond = b.get("condition_on_return") or b.get("returned_condition")
    if isinstance(cond, str) and cond.upper() in ("POOR", "DAMAGED", "C", "D"):
        forfeit = True

    ramp["status"] = "RETURNED"
    ramp["actual_pickup"] = iso(ts)
    ramp["deposit_status"] = "FORFEITED" if forfeit else "REFUNDED"
    unit = get_unit_or_404(ramp["inventory_unit_id"])
    unit["status"] = "AVAILABLE"
    days = (ts - ramp["_rental_start_dt"]).days
    unit["total_rental_days"] = unit.get("total_rental_days", 0) + max(0, days)
    unit["current_case_id"] = None
    touch(unit)

    _final_invoice_for_unbilled(case, ramp, ts)
    touch(ramp)
    mutate_case(case)
    return ok_object(serialize(ramp))


@bp.route("/cases/<caseId>/rental-ramps/<rampId>/cancel", methods=["POST"])
def cancel_rental(caseId, rampId):
    require_roles("LogisticsCoordinator")
    case, ramp = _get_ramp(caseId, rampId)
    require_case_active(case)
    if ramp["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a RESERVED rental can be cancelled")
    ramp["status"] = "CANCELLED"
    ramp["deposit_status"] = "REFUNDED"
    touch(ramp)
    unit = get_unit_or_404(ramp["inventory_unit_id"])
    unit["status"] = "AVAILABLE"
    unit["current_case_id"] = None
    touch(unit)
    return ok_object(serialize(ramp))
