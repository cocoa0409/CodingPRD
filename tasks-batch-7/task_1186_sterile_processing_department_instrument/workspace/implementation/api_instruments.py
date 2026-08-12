"""Instruments and the repair-or-replace cycle."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, invalid_request, ok, ok_list,
    opt_int, opt_justification, paginate, pagination, query_str, req_enum,
    req_fk, req_int, req_string,
)

bp = Blueprint("instruments", __name__)

CRITICALITIES = ("ROUTINE", "CRITICAL")
REPAIR_OUTCOMES = ("FIXED", "CONDEMNED")


@bp.post("/spd/instruments")
def create_instrument():
    auth(("FacilityAdmin",))
    body = get_body()
    instrument_type = req_string(body, "instrument_type")
    serial_number = req_string(body, "serial_number")
    max_cycles = req_int(body, "max_cycles")
    replacement_cost_cents = req_int(body, "replacement_cost_cents", minimum=1)
    criticality = req_enum(body, "criticality", CRITICALITIES)
    usage_cycles = opt_int(body, "usage_cycles", minimum=0, default=0)

    # p9 constraint gate: uniqueness
    for existing in store.INSTRUMENTS.values():
        if existing["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER", 409,
                           "Instrument serial_number already registered.")

    record = store.new_record()
    record.update({
        "instrument_type": instrument_type,
        "serial_number": serial_number,
        "max_cycles": max_cycles,
        "usage_cycles": usage_cycles,
        "replacement_cost_cents": replacement_cost_cents,
        "criticality": criticality,
        "status": "IN_SERVICE",
        "repair_count": 0,
        "assigned_tray_id": None,
    })
    store.INSTRUMENTS[record["id"]] = record
    return created(views.instrument_view(record))


@bp.get("/spd/instruments")
def list_instruments():
    auth(ANY)
    limit, offset = pagination()
    status = query_str("status")
    assigned_tray_id = query_str("assigned_tray_id")
    instrument_type = query_str("instrument_type")
    rows = [r for r in store.INSTRUMENTS.values()
            if (status is None or r["status"] == status)
            and (assigned_tray_id is None
                 or r["assigned_tray_id"] == assigned_tray_id)
            and (instrument_type is None
                 or r["instrument_type"] == instrument_type)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.instrument_view(r) for r in page], limit, offset, total)


@bp.get("/spd/instruments/<instrument_id>")
def get_instrument(instrument_id):
    auth(ANY)
    record = store.fetch(store.INSTRUMENTS, instrument_id)
    return ok(views.instrument_view(record))


@bp.post("/spd/instruments/<instrument_id>/assign")
def assign_instrument(instrument_id):
    auth(("SpdTechnician",))
    instrument = store.fetch(store.INSTRUMENTS, instrument_id)
    body = get_body()
    tray = req_fk(body, "tray_id", store.TRAYS, "Tray")

    # p6 state gates: own status first, then the linked tray
    if instrument["status"] != "IN_SERVICE":
        raise ApiError("ERR_INSTRUMENT_NOT_IN_SERVICE", 409,
                       "assign requires instrument IN_SERVICE.")
    if tray["status"] != "IN_ASSEMBLY":
        raise ApiError("ERR_TRAY_NOT_IN_ASSEMBLY", 409,
                       "instrument assign requires tray IN_ASSEMBLY.")
    # p9 constraint gates, declared order
    if instrument["assigned_tray_id"] is not None:
        raise ApiError("ERR_INSTRUMENT_ALREADY_ASSIGNED", 409,
                       "Instrument is already assigned to a tray.")
    if instrument["usage_cycles"] >= instrument["max_cycles"]:
        raise ApiError("ERR_INSTRUMENT_CYCLE_LIMIT", 409,
                       "Instrument has reached its lifecycle limit.")

    instrument["assigned_tray_id"] = tray["id"]
    store.touch(instrument)
    return ok(views.instrument_view(instrument))


@bp.post("/spd/instruments/<instrument_id>/flag-for-repair")
def flag_instrument_for_repair(instrument_id):
    auth(("SpdTechnician",))
    instrument = store.fetch(store.INSTRUMENTS, instrument_id)
    if instrument["status"] != "IN_SERVICE":
        raise ApiError("ERR_INSTRUMENT_NOT_IN_SERVICE", 409,
                       "flag-for-repair requires instrument IN_SERVICE.")

    instrument["status"] = "FLAGGED_FOR_REPAIR"
    store.touch(instrument)

    order = store.new_record()
    order.update({
        "instrument_id": instrument["id"],
        "status": "OPEN",
        "vendor": None,
        "quoted_cost_cents": None,
        "actual_cost_cents": None,
        "recommended_outcome": None,
        "outcome": None,
        "outcome_overridden": False,
    })
    store.REPAIR_ORDERS[order["id"]] = order
    return created(views.repair_order_view(order))


@bp.post("/spd/instruments/<instrument_id>/retire")
def retire_instrument(instrument_id):
    auth(("FacilityAdmin",))
    instrument = store.fetch(store.INSTRUMENTS, instrument_id)
    if instrument["status"] not in ("IN_SERVICE", "FLAGGED_FOR_REPAIR"):
        raise ApiError("ERR_INSTRUMENT_NOT_RETIRABLE", 409,
                       "retire requires IN_SERVICE or FLAGGED_FOR_REPAIR.")

    if instrument["status"] == "FLAGGED_FOR_REPAIR":
        # auto-condemn the still-OPEN repair order
        for order in store.REPAIR_ORDERS.values():
            if (order["instrument_id"] == instrument["id"]
                    and order["status"] == "OPEN"):
                order["status"] = "CLOSED_CONDEMNED"
                order["outcome"] = "CONDEMNED"
                order["recommended_outcome"] = "CONDEMNED"
                order["outcome_overridden"] = False
                store.touch(order)

    # same tray demotion cascade as at send time
    domain.demote_tray_for_instrument_repair(instrument)
    instrument["status"] = "RETIRED"
    store.touch(instrument)
    return ok(views.instrument_view(instrument))


# --------------------------------------------------------------------------
# Repair orders
# --------------------------------------------------------------------------


@bp.get("/spd/repair-orders")
def list_repair_orders():
    auth(ANY)
    limit, offset = pagination()
    instrument_id = query_str("instrument_id")
    status = query_str("status")
    rows = [r for r in store.REPAIR_ORDERS.values()
            if (instrument_id is None or r["instrument_id"] == instrument_id)
            and (status is None or r["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.repair_order_view(r) for r in page], limit, offset, total)


@bp.get("/spd/repair-orders/<order_id>")
def get_repair_order(order_id):
    auth(ANY)
    record = store.fetch(store.REPAIR_ORDERS, order_id)
    return ok(views.repair_order_view(record))


@bp.post("/spd/repair-orders/<order_id>/send")
def send_repair_order(order_id):
    auth(("FacilityAdmin",))
    order = store.fetch(store.REPAIR_ORDERS, order_id)
    body = get_body()
    vendor = req_string(body, "vendor")
    quoted_cost_cents = req_int(body, "quoted_cost_cents", minimum=0)

    if order["status"] != "OPEN":
        raise ApiError("ERR_REPAIR_ORDER_NOT_OPEN", 409,
                       "send requires repair order OPEN.")

    order["vendor"] = vendor
    order["quoted_cost_cents"] = quoted_cost_cents
    order["status"] = "SENT"
    store.touch(order)

    instrument = store.INSTRUMENTS.get(order["instrument_id"])
    if instrument is not None:
        instrument["status"] = "OUT_FOR_REPAIR"
        # tray demotion cascade fires at send time
        domain.demote_tray_for_instrument_repair(instrument)
        store.touch(instrument)
    return ok(views.repair_order_view(order))


@bp.post("/spd/repair-orders/<order_id>/receive")
def receive_repair_order(order_id):
    auth(("FacilityAdmin",))
    order = store.fetch(store.REPAIR_ORDERS, order_id)
    body = get_body()
    actual_cost_cents = req_int(body, "actual_cost_cents", minimum=0)
    outcome = req_enum(body, "outcome", REPAIR_OUTCOMES)
    override_justification = opt_justification(body, "override_justification")

    if order["status"] != "SENT":
        raise ApiError("ERR_REPAIR_ORDER_NOT_SENT", 409,
                       "receive requires repair order SENT.")

    instrument = store.INSTRUMENTS.get(order["instrument_id"])
    recommended = domain.repair_recommendation(instrument, actual_cost_cents)

    # p9: applied outcome differing from the recommendation needs justification
    if outcome != recommended and override_justification is None:
        raise ApiError(
            "ERR_OUTCOME_OVERRIDE_JUSTIFICATION_REQUIRED", 400,
            "override_justification (>= 20 chars) is required when the "
            "applied outcome differs from the recommended outcome.")

    order["actual_cost_cents"] = actual_cost_cents
    order["recommended_outcome"] = recommended
    order["outcome"] = outcome
    order["outcome_overridden"] = outcome != recommended

    if outcome == "FIXED":
        order["status"] = "CLOSED_FIXED"
        if instrument is not None:
            instrument["status"] = "IN_SERVICE"
            instrument["repair_count"] = instrument["repair_count"] + 1
            store.touch(instrument)
    else:
        order["status"] = "CLOSED_CONDEMNED"
        if instrument is not None:
            instrument["status"] = "RETIRED"
            store.touch(instrument)
    store.touch(order)
    return ok(views.repair_order_view(order))
