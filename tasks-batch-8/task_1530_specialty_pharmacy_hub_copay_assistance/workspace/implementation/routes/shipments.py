"""Shipments: create, ship, deliver, spoil."""

from datetime import timedelta, date
from decimal import Decimal

from flask import Blueprint

from db import store, new_id, now_iso, logical_today
from errors import (
    ApiError,
    ERR_ENROLLMENT_DISCONTINUED,
    ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT,
    ERR_INVALID_TRANSITION,
    ERR_ALREADY_TERMINAL,
    ERR_COLD_CHAIN_EXCEEDED,
    ERR_TRAINING_INCOMPLETE,
    ERR_ADHERENCE_TOO_LOW,
    ERR_REFILL_SPACING_VIOLATION,
)
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, body_optional, req_date, req_int,
    get_enrollment_or_404, get_shipment_or_404,
    pagination_params, paginate, touch,
)
from services.calc import (
    serialize_shipment, shipments_for_enrollment, bi_for_enrollment,
    nonterminal_assistance, run_split, compute_pdc, REFILL_MIN_PDC_PCT,
)

bp = Blueprint("shipments", __name__)


@bp.post("/hub/enrollments/<eid>/shipments")
def create_shipment(eid):
    require_roles("CaseManager")
    e = get_enrollment_or_404(eid)
    data = body()
    requested_delivery_date = req_date(data, "requested_delivery_date")
    transit_hours = req_int(data, "transit_hours")
    days_supply = req_int(data, "days_supply")

    # Body schema: requested_delivery_date >= current logical clock date.
    if requested_delivery_date < logical_today():
        from errors import ERR_VALIDATION
        raise ApiError(ERR_VALIDATION,
                       "requested_delivery_date must not lie in the past.", 400)

    # State validity.
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)
    if e["status"] not in ("PA_PENDING", "APPROVED", "ACTIVE"):
        raise ApiError(ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT,
                       "Enrollment is not ready for shipment.", 409)

    program = store.drug_programs[e["program_id"]]
    bi = bi_for_enrollment(eid)

    # fill_number / fill_type.
    existing = shipments_for_enrollment(eid)
    fill_number = (max((s["fill_number"] for s in existing), default=0)) + 1
    has_prior_delivered = any(s["status"] == "DELIVERED" for s in existing)
    fill_type = "REFILL" if has_prior_delivered else "FIRST_FILL"

    # Gate 1 (compliance/safety): cold chain.
    if program["requires_cold_chain"] and transit_hours > program["max_transit_hours"]:
        raise ApiError(ERR_COLD_CHAIN_EXCEEDED,
                       "transit_hours exceeds the program's cold-chain "
                       "maximum.", 422)

    # Gate 2 (domain): first-fill training.
    if fill_type == "FIRST_FILL" and program["requires_injection_training"] \
            and e["training_sessions_completed"] < 1:
        raise ApiError(ERR_TRAINING_INCOMPLETE,
                       "First fill requires at least one completed nurse "
                       "training session.", 422)

    # Gate 3 (domain): refill adherence.
    if fill_type == "REFILL":
        pdc = compute_pdc(e, confirmed=True)
        # therapy_start_date is guaranteed set when a DELIVERED shipment
        # exists, so pdc is not None here.
        if pdc is None or Decimal(str(pdc)) < REFILL_MIN_PDC_PCT:
            raise ApiError(ERR_ADHERENCE_TOO_LOW,
                           "Confirmed adherence is below 80.0 percent.", 422)

    # Gate 4 (temporal): refill spacing.
    if fill_type == "REFILL":
        delivered = [s for s in existing if s["status"] == "DELIVERED"]
        latest = max(delivered,
                     key=lambda s: (date.fromisoformat(s["delivered_date"]),
                                    s["fill_number"]))
        earliest = date.fromisoformat(latest["delivered_date"]) + \
            timedelta(days=program["min_days_between_fills"])
        if requested_delivery_date < earliest:
            raise ApiError(ERR_REFILL_SPACING_VIOLATION,
                           "requested_delivery_date precedes the latest "
                           "delivered fill plus min_days_between_fills.", 422)

    # Financial clearance at creation.
    a = nonterminal_assistance(eid)
    if e["status"] in ("APPROVED", "ACTIVE") and \
            not (a is not None and a["status"] == "RESERVED"):
        initial_status = "SCHEDULED"
    else:
        initial_status = "REQUESTED"

    ts = now_iso()
    shipment = {
        "id": new_id(),
        "enrollment_id": eid,
        "fill_number": fill_number,
        "fill_type": fill_type,
        "requested_delivery_date": requested_delivery_date.isoformat(),
        "transit_hours": transit_hours,
        "days_supply": days_supply,
        "status": initial_status,
        "patient_cost_share_cents": bi["patient_cost_share_cents"],
        "assistance_pay_cents": None,
        "patient_pay_cents": None,
        "payer_accumulator_delta_cents": None,
        "delivered_date": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.shipments[shipment["id"]] = shipment
    return success_object(serialize_shipment(shipment), 201)


@bp.get("/hub/enrollments/<eid>/shipments")
def list_shipments(eid):
    get_auth()
    get_enrollment_or_404(eid)
    limit, offset = pagination_params()
    page, total = paginate(shipments_for_enrollment(eid), limit, offset)
    return success_array([serialize_shipment(s) for s in page],
                         limit, offset, total, 200)


@bp.post("/hub/shipments/<sid>/ship")
def ship_shipment(sid):
    require_roles("PharmacyPartner")
    body_optional()
    s = get_shipment_or_404(sid)
    if s["status"] in ("DELIVERED", "SPOILED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Shipment is terminal.", 409)
    if s["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Ship requires a SCHEDULED shipment.", 409)

    e = store.enrollments[s["enrollment_id"]]
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)
    if e["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Enrollment must be APPROVED or ACTIVE to ship.", 409)
    a = nonterminal_assistance(s["enrollment_id"])
    if a is not None and a["status"] == "RESERVED":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "A RESERVED assistance blocks financial clearance.",
                       409)

    bi = bi_for_enrollment(s["enrollment_id"])
    # Split runs against a non-terminal assistance with remaining benefit > 0.
    split_assistance = a if (a is not None and a["status"] in ("ACTIVE", "EXHAUSTED")) else None
    assistance_pay, patient_pay, delta = run_split(s, split_assistance, bi)

    s["status"] = "SHIPPED"
    s["assistance_pay_cents"] = assistance_pay
    s["patient_pay_cents"] = patient_pay
    s["payer_accumulator_delta_cents"] = delta
    touch(s)

    # Debit the assistance.
    if split_assistance is not None and assistance_pay > 0:
        split_assistance["remaining_annual_benefit_cents"] -= assistance_pay
        split_assistance["disbursed_cents"] += assistance_pay
        if split_assistance["status"] == "ACTIVE" and \
                split_assistance["remaining_annual_benefit_cents"] == 0:
            split_assistance["status"] = "EXHAUSTED"
        touch(split_assistance)

    # Accrue payer-side OOP.
    e["payer_accumulated_oop_cents"] = min(
        bi["oop_max_cents"], e["payer_accumulated_oop_cents"] + delta)
    e["remaining_oop_cents"] = bi["oop_max_cents"] - e["payer_accumulated_oop_cents"]
    touch(e)

    return success_object(serialize_shipment(s), 200)


@bp.post("/hub/shipments/<sid>/deliver")
def deliver_shipment(sid):
    require_roles("PharmacyPartner")
    s = get_shipment_or_404(sid)
    data = body()
    delivered_date = req_date(data, "delivered_date")
    if s["status"] in ("DELIVERED", "SPOILED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Shipment is terminal.", 409)
    if s["status"] != "SHIPPED":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Deliver requires a SHIPPED shipment.", 409)

    s["status"] = "DELIVERED"
    s["delivered_date"] = delivered_date.isoformat()
    touch(s)

    e = store.enrollments[s["enrollment_id"]]
    if e["status"] == "APPROVED":
        # First delivery activates therapy.
        e["status"] = "ACTIVE"
        e["therapy_start_date"] = delivered_date.isoformat()
        e["fills_delivered_count"] += 1
    else:
        e["fills_delivered_count"] += 1
    touch(e)
    return success_object(serialize_shipment(s), 200)


@bp.post("/hub/shipments/<sid>/spoil")
def spoil_shipment(sid):
    require_roles("PharmacyPartner")
    body_optional()  # optional reason accepted, not persisted
    s = get_shipment_or_404(sid)
    if s["status"] in ("DELIVERED", "SPOILED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Shipment is terminal.", 409)
    if s["status"] != "SHIPPED":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Spoil requires a SHIPPED shipment.", 409)

    e = store.enrollments[s["enrollment_id"]]
    bi = bi_for_enrollment(s["enrollment_id"])
    a = nonterminal_assistance(s["enrollment_id"])

    # CASCADE B link 1: compensate the funding assistance.
    if s["assistance_pay_cents"] and s["assistance_pay_cents"] > 0 and \
            a is not None and a["status"] != "RELEASED":
        a["remaining_annual_benefit_cents"] += s["assistance_pay_cents"]
        a["disbursed_cents"] -= s["assistance_pay_cents"]
        if a["status"] == "EXHAUSTED" and a["remaining_annual_benefit_cents"] > 0:
            a["status"] = "ACTIVE"  # auto-revert
        touch(a)

    # CASCADE B link 2: roll back the payer accrual.
    delta = s["payer_accumulator_delta_cents"] or 0
    e["payer_accumulated_oop_cents"] = max(
        0, e["payer_accumulated_oop_cents"] - delta)
    e["remaining_oop_cents"] = bi["oop_max_cents"] - e["payer_accumulated_oop_cents"]
    touch(e)

    s["status"] = "SPOILED"
    touch(s)
    return success_object(serialize_shipment(s), 200)
