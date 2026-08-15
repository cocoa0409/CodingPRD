"""RefurbProgram endpoints: create, read, advance phase machine, cancel."""
from flask import Blueprint, request

import calc
from db import STORE, now_dt
from domain import (new_entity, bump, bump_program, get_or_404, by_created,
                    serialize_program)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_AIRCRAFT_BUSY, ERR_CREDIT_HOLD, ERR_ASSESSMENT_REQUIRED,
                    ERR_CORROSION_DISCOVERY_REQUIRED, ERR_SCHEME_NOT_APPROVED,
                    ERR_BOOTH_BOOKING_REQUIRED, ERR_DISCOVERY_ITEMS_OPEN,
                    ERR_INSPECTION_OUTSTANDING, ERR_CERT_REQUIRED,
                    ERR_WEIGHT_NOT_SIGNED_OFF, ERR_INVOICE_NOT_SETTLED)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("programs", __name__)

PROGRAM_PHASES = ("QUOTED", "BOOKED", "INDUCTED", "SURFACE_REVIEW", "IN_WORK",
                  "IN_INSPECTION", "READY_FOR_DELIVERY", "DELIVERED", "CANCELLED")


@bp.post("/programs")
def create_program():
    auth("ProgramManager")
    data = get_body(required=True)
    aircraft_id = field(data, "aircraft_id", "str")
    customer_id = field(data, "customer_id", "str")
    base_price_cents = field(data, "base_price_cents", "int")
    daily_penalty_rate_cents = field(data, "daily_penalty_rate_cents", "int")
    penalty_cap_pct = field(data, "penalty_cap_pct", "num")
    contractual_delivery_date = field(data, "contractual_delivery_date", "datetime")

    aircraft = STORE.aircraft.get(aircraft_id)
    if aircraft is None:
        raise ref_integrity("aircraft_id does not reference an existing aircraft")
    # State gate (priority 7) precedes cross-consistency (priority 10).
    if aircraft["status"] == "IN_REFURB":
        raise ApiError(ERR_AIRCRAFT_BUSY, 409,
                       "Aircraft is already under refurbishment")
    if customer_id not in STORE.customers:
        raise ref_integrity("customer_id does not reference an existing customer")
    if aircraft["customer_id"] != customer_id:
        raise ref_integrity("customer_id must equal the owning aircraft's customer_id")

    prog = new_entity()
    prog.update({
        "aircraft_id": aircraft_id,
        "customer_id": customer_id,
        "base_price_cents": base_price_cents,
        "daily_penalty_rate_cents": daily_penalty_rate_cents,
        "penalty_cap_pct": penalty_cap_pct,
        "contractual_delivery_date": contractual_delivery_date,
        "actual_delivery_date": None,
        "status": "QUOTED",
        "penalty_final_cents": 0,
        "rework_cycles": 0,
        "approved_scheme_id": None,
    })
    STORE.programs[prog["id"]] = prog
    return success(serialize_program(prog), status=201)


@bp.get("/programs/<pid>")
def get_program(pid):
    auth()
    prog = get_or_404(STORE.programs, pid, "RefurbProgram")
    return success(serialize_program(prog))


@bp.get("/programs")
def list_programs():
    auth()
    items = by_created(list(STORE.programs.values()))
    for key in ("aircraft_id", "customer_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [p for p in items if p[key] == value]
    return paginate(items, serialize_program)


def _credit_check(prog):
    cust = STORE.customers.get(prog["customer_id"])
    if cust is None or cust["credit_status"] != "GOOD_STANDING":
        raise ApiError(ERR_CREDIT_HOLD, 402,
                       "Customer is on CREDIT_HOLD")


def _program_slots(prog):
    return [s for s in STORE.hangar_slots.values() if s["program_id"] == prog["id"]]


def _program_bookings(prog):
    return [b for b in STORE.booth_bookings.values() if b["program_id"] == prog["id"]]


def _advance_gates(prog, to_phase):
    """Raise the highest-priority gate failure for the requested transition;
    returns the aircraft cascade flag for INDUCTED/DELIVERED handling."""
    cur = prog["status"]
    clock = now_dt()

    if cur == "QUOTED" and to_phase == "BOOKED":
        if not any(s["status"] == "BOOKED" for s in _program_slots(prog)):
            raise invalid_state("Advance to BOOKED requires a BOOKED hangar slot")
        _credit_check(prog)
        return

    if cur == "BOOKED" and to_phase == "INDUCTED":
        ok = any(s["status"] == "ACTIVE" and s["start_at"] <= clock < s["end_at"]
                 for s in _program_slots(prog))
        if not ok:
            raise invalid_state(
                "Advance to INDUCTED requires an ACTIVE hangar slot covering the clock")
        return

    if cur == "INDUCTED" and to_phase == "SURFACE_REVIEW":
        a = calc.current_assessment(prog["id"])
        if a is None or a["status"] not in ("PENDING", "DECIDED"):
            raise ApiError(ERR_ASSESSMENT_REQUIRED, 409,
                           "Advance requires an existing surface assessment")
        return

    if cur == "SURFACE_REVIEW" and to_phase == "IN_WORK":
        # Gate order pinned by PRD §3.5: assessment -> corrosion -> scheme ->
        # booth -> credit.
        a = calc.current_assessment(prog["id"])
        if a is None or a["status"] != "DECIDED":
            raise ApiError(ERR_ASSESSMENT_REQUIRED, 409,
                           "Advance to IN_WORK requires a DECIDED surface assessment")
        if a["corrosion_severity"] == "HEAVY":
            linked = any(d["assessment_id"] == a["id"]
                         for d in calc.discovery_items_of(prog["id"]))
            if not linked:
                raise ApiError(ERR_CORROSION_DISCOVERY_REQUIRED, 409,
                               "HEAVY corrosion requires a linked DiscoveryItem")
        if not prog["approved_scheme_id"]:
            raise ApiError(ERR_SCHEME_NOT_APPROVED, 409,
                           "Advance to IN_WORK requires an APPROVED paint scheme")
        if not any(b["status"] == "BOOKED" for b in _program_bookings(prog)):
            raise ApiError(ERR_BOOTH_BOOKING_REQUIRED, 409,
                           "Advance to IN_WORK requires a BOOKED booth booking")
        _credit_check(prog)
        return

    if cur == "IN_WORK" and to_phase == "IN_INSPECTION":
        for d in calc.discovery_items_of(prog["id"]):
            if d["status"] not in ("COMPLETED", "REJECTED", "DEFERRED"):
                raise ApiError(ERR_DISCOVERY_ITEMS_OPEN, 409,
                               "Discovery items remain non-terminal")
        if not any(b["status"] == "COMPLETED" for b in _program_bookings(prog)):
            raise ApiError(ERR_BOOTH_BOOKING_REQUIRED, 409,
                           "Advance to IN_INSPECTION requires a COMPLETED booth booking")
        return

    if cur == "IN_INSPECTION" and to_phase == "READY_FOR_DELIVERY":
        _delivery_gate(prog)
        return

    if cur == "READY_FOR_DELIVERY" and to_phase == "DELIVERED":
        settled = any(i["kind"] == "FINAL" and i["status"] == "PAID"
                      for i in calc.invoices_of(prog["id"]))
        if not settled:
            raise ApiError(ERR_INVOICE_NOT_SETTLED, 409,
                           "DELIVERED requires the FINAL invoice to be PAID")
        return

    raise invalid_state(f"Cannot advance from {cur} to {to_phase}")


def _delivery_gate(prog):
    """Pinned three-step safety gate: inspection -> certification -> weight."""
    inspections = [i for i in STORE.quality_inspections.values()
                   if i["program_id"] == prog["id"]]
    # Step 1: every FAILED inspection answered by a later PASSED of same type;
    # a FINAL inspection has PASSED.
    for failed in [i for i in inspections if i["status"] == "FAILED"]:
        answered = any(j["status"] == "PASSED"
                       and j["inspection_type"] == failed["inspection_type"]
                       and j["_seq"] > failed["_seq"]
                       for j in inspections)
        if not answered:
            raise ApiError(ERR_INSPECTION_OUTSTANDING, 409,
                           "A FAILED inspection lacks a later PASSED re-inspection")
    if not any(i["inspection_type"] == "FINAL" and i["status"] == "PASSED"
               for i in inspections):
        raise ApiError(ERR_INSPECTION_OUTSTANDING, 409,
                       "A FINAL inspection has not PASSED")
    # Step 2: every soft-goods lot CERTIFIED.
    for lot in STORE.soft_good_lots.values():
        if lot["program_id"] == prog["id"] and lot["status"] != "CERTIFIED":
            raise ApiError(ERR_CERT_REQUIRED, 409,
                           "Every soft-goods lot must be CERTIFIED")
    # Step 3: SIGNED_OFF FINAL weight record within limit, or WEIGHT_ACK-approved.
    aircraft = STORE.aircraft.get(prog["aircraft_id"])
    max_delta = aircraft["max_delta_lbs"] if aircraft else 0
    signed_finals = [w for w in STORE.weight_records.values()
                     if w["program_id"] == prog["id"]
                     and w["variant"] == "FINAL" and w["status"] == "SIGNED_OFF"]
    gate_ok = False
    for rec in signed_finals:
        if abs(rec["delta_lbs"]) <= max_delta:
            gate_ok = True
            break
        acked = any(co["kind"] == "WEIGHT_ACK" and co["status"] == "APPROVED"
                    and co["acknowledges_weight_record_id"] == rec["id"]
                    for co in calc.change_orders_of(prog["id"]))
        if acked:
            gate_ok = True
            break
    if not gate_ok:
        raise ApiError(ERR_WEIGHT_NOT_SIGNED_OFF, 409,
                       "A SIGNED_OFF FINAL weight record within limit (or "
                       "WEIGHT_ACK-acknowledged) is required")


@bp.post("/programs/<pid>/advance")
def advance_program(pid):
    auth("ProgramManager")
    data = get_body(required=True)
    to_phase = field(data, "to_phase", "str", enum=PROGRAM_PHASES)
    prog = get_or_404(STORE.programs, pid, "RefurbProgram")
    _advance_gates(prog, to_phase)

    # Side effects per RefurbProgram state machine.
    if to_phase == "INDUCTED":
        aircraft = STORE.aircraft.get(prog["aircraft_id"])
        if aircraft is not None and aircraft["status"] in ("IN_SERVICE", "RETURNED"):
            aircraft["status"] = "IN_REFURB"
            bump(aircraft)
    elif to_phase == "DELIVERED":
        prog["actual_delivery_date"] = now_dt()
        prog["penalty_final_cents"] = calc.delivery_penalty(
            prog, "settlement", reference_date=prog["actual_delivery_date"].date())
        for slot in _program_slots(prog):
            if slot["status"] == "ACTIVE":
                slot["status"] = "RELEASED"
                bump(slot)
        aircraft = STORE.aircraft.get(prog["aircraft_id"])
        if aircraft is not None:
            aircraft["status"] = "RETURNED"
            bump(aircraft)

    prog["status"] = to_phase
    bump_program(prog)
    return success(serialize_program(prog))


@bp.post("/programs/<pid>/cancel")
def cancel_program(pid):
    auth("ProgramManager")
    prog = get_or_404(STORE.programs, pid, "RefurbProgram")
    if prog["status"] not in ("QUOTED", "BOOKED", "INDUCTED"):
        raise invalid_state(f"Cannot cancel a program in {prog['status']}")
    was_inducted = prog["status"] == "INDUCTED"
    for slot in _program_slots(prog):
        if slot["status"] in ("BOOKED", "ACTIVE"):
            slot["status"] = "CANCELLED"
            bump(slot)
    if was_inducted:
        aircraft = STORE.aircraft.get(prog["aircraft_id"])
        if aircraft is not None:
            aircraft["status"] = "RETURNED"
            bump(aircraft)
    prog["status"] = "CANCELLED"
    bump_program(prog)
    return success(serialize_program(prog))
