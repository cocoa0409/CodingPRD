"""EPCIS event capture (PRD §3.3).

Events both record and drive the case state machine. event_time later than
the current logical clock is rejected before event sequencing. QUARANTINE and
RELEASE are never captured by hand — the investigation machinery appends them.
"""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from services import events as event_service
from validation import (get_body, req_str, req_enum, req_datetime, body_fk,
                        opt_body_fk, path_entity)

bp = Blueprint("epcis", __name__)

EVENT_TYPES = ["COMMISSION", "AGGREGATE", "SHIP", "RECEIVE",
               "QUARANTINE", "RELEASE", "DECOMMISSION"]


@bp.route("/wholesale/epcis-events", methods=["POST"])
@endpoint(["WarehouseOperator", "QualityAssuranceLead"])
def capture_event():
    body = get_body()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    case = body_fk(body, "subject_case_id", store.serialized_cases, "SerializedCase")
    event_time = req_datetime(body, "event_time")
    sender = body_fk(body, "sender_partner_id", store.trading_partners, "TradingPartner")
    recipient = body_fk(body, "recipient_partner_id", store.trading_partners, "TradingPartner")
    # order_id is carried when the event binds to an order; when supplied it
    # must reference an existing order.
    order = opt_body_fk(body, "order_id", store.purchase_orders, "PurchaseOrder")

    # Temporal freshness (priority 9) is evaluated before event sequencing
    # (priority 10): event_time must be <= the current logical clock.
    if event_time > db.logical_now():
        raise ApiError(errors.ERR_EVENT_TIME_IN_FUTURE[0], errors.ERR_EVENT_TIME_IN_FUTURE[1],
                       "event_time is after the current logical clock")

    # No second captured event may bear the same event_time and recorded_at
    # for the same case (PRD §3.3) — recorded_at is the current logical clock.
    now_iso = db.iso_logical(db.logical_now())
    event_time_iso = db.iso_logical(event_time)
    if any(e["subject_case_id"] == case["id"]
           and e["event_time"] == event_time_iso
           and e["recorded_at"] == now_iso
           for e in store.epcis_events.values()):
        raise ApiError(errors.ERR_INVALID_EVENT_SEQUENCE[0], errors.ERR_INVALID_EVENT_SEQUENCE[1],
                       "Duplicate event_time and recorded_at for the case")

    # Event sequencing per the case state machine.
    if event_type in ("QUARANTINE", "RELEASE"):
        raise ApiError(errors.ERR_INVALID_EVENT_SEQUENCE[0], errors.ERR_INVALID_EVENT_SEQUENCE[1],
                       "QUARANTINE and RELEASE events are appended by the investigation machinery")
    if event_type in ("COMMISSION", "AGGREGATE"):
        if case["case_status"] != "COMMISSIONED":
            raise ApiError(errors.ERR_INVALID_EVENT_SEQUENCE[0], errors.ERR_INVALID_EVENT_SEQUENCE[1],
                           "%s is admissible only while the case is COMMISSIONED" % event_type)
    elif event_type == "SHIP":
        if case["case_status"] != "COMMISSIONED":
            raise ApiError(errors.ERR_CASE_NOT_SHIPPABLE[0], errors.ERR_CASE_NOT_SHIPPABLE[1],
                           "Case must be COMMISSIONED to ship")
        if not case["expiry_date"] > db.logical_now():
            raise ApiError(errors.ERR_PRODUCT_EXPIRED[0], errors.ERR_PRODUCT_EXPIRED[1],
                           "Case expiry_date is not strictly after the current logical clock")
    elif event_type == "RECEIVE":
        if case["case_status"] != "SHIPPED":
            raise ApiError(errors.ERR_CASE_NOT_IN_TRANSIT[0], errors.ERR_CASE_NOT_IN_TRANSIT[1],
                           "RECEIVE requires the case to be SHIPPED")
    elif event_type == "DECOMMISSION":
        if case["case_status"] != "COMMISSIONED":
            raise ApiError(errors.ERR_CASE_NOT_SHIPPABLE[0], errors.ERR_CASE_NOT_SHIPPABLE[1],
                           "Case must be COMMISSIONED to decommission")

    event = event_service.append_event(
        event_type, case, event_time,
        order_id=order["id"] if order else None,
        sender_partner_id=sender["id"],
        recipient_partner_id=recipient["id"],
    )

    # Drive the case state machine (units follow the case).
    if event_type == "SHIP":
        event_service.transition_case(case, "SHIPPED", unit_from={"COMMISSIONED"})
    elif event_type == "RECEIVE":
        event_service.transition_case(case, "RECEIVED", unit_from={"SHIPPED"})
    elif event_type == "DECOMMISSION":
        event_service.transition_case(case, "DECOMMISSIONED", unit_from={"COMMISSIONED"})

    return created(event)


@bp.route("/wholesale/epcis-events", methods=["GET"])
@endpoint(ALL_ROLES)
def list_events():
    pg = Paginator()
    rows = list(store.epcis_events.values())
    rows = pg.filter(rows, "subject_case_id")
    rows = pg.filter(rows, "event_type")
    rows = pg.filter(rows, "order_id")
    rows = pg.filter(rows, "sender_partner_id")
    rows = pg.filter(rows, "recipient_partner_id")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/epcis-events/<eventId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_event(eventId):
    event = path_entity(store.epcis_events, eventId, "EpcisEvent")
    return ok(event)
