"""Maintenance dispatches: creation inside the response window, technician
progress, the parts-hold promise and the recovery cascade (PRD §3.5)."""
from flask import Blueprint

import calc
import cascades
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id
from response import array_response, object_response, paginate

bp = Blueprint("dispatches", __name__)

CERTIFICATION_CLASSES = ("L2", "DCFC_BASIC", "DCFC_HV")
PROGRESS_EVENTS = ("EN_ROUTE", "ARRIVE", "RESUME_ONSITE")


def _require_assigned_technician(dispatch):
    if dispatch["technician_user_id"] != current_user_id():
        raise err("ERR_NOT_ASSIGNED_TECHNICIAN",
                  "Only the assigned technician may act on this dispatch.")


@bp.post("/maintenance-dispatches")
@endpoint("NetworkOperator")
def create_dispatch():
    body = validation.json_body()

    # §2.5 body declaration order: port_id resolves before outage_event_id.
    raw_port_id = validation.fk(body, "port_id")
    port = lookup.port(raw_port_id) if raw_port_id is not None else None
    raw_outage_id = validation.fk(body, "outage_event_id")
    outage = lookup.outage(raw_outage_id) if raw_outage_id is not None else None

    validation.as_string(body, "outage_event_id")
    validation.as_string(body, "port_id")
    technician_user_id = validation.as_string(body, "technician_user_id")
    certification_class = validation.as_enum(body, "technician_certification_class",
                                             CERTIFICATION_CLASSES)
    window_start_at = validation.as_datetime(body, "window_start_at")
    window_end_at = validation.as_datetime(body, "window_end_at")

    outage_port = db.ports.get(outage["port_id"])
    station = db.stations.get(outage_port["station_id"]) if outage_port else None

    if outage["state"] != "CLASSIFIED":
        raise err("ERR_INVALID_STATE", "Only a CLASSIFIED outage may be dispatched.")
    if port["service_state"] == "RETIRED":
        raise err("ERR_INVALID_STATE", "A retired dispenser may not be dispatched to.")

    if not calc.technician_covers(certification_class, station["power_class"]):
        raise err("ERR_TECHNICIAN_NOT_CERTIFIED",
                  "The technician's certification does not cover the station's power class.")

    if port["id"] != outage["port_id"]:
        raise err("ERR_OUTAGE_PORT_MISMATCH",
                  "port_id must be the dispenser the outage was reported on.")

    if not window_end_at > window_start_at:
        raise err("ERR_DISPATCH_WINDOW_INVALID",
                  "window_end_at must be strictly after window_start_at.")
    if window_start_at < outage["detected_at"]:
        raise err("ERR_DISPATCH_WINDOW_INVALID",
                  "window_start_at may not be earlier than the outage's detected_at.")

    for existing in db.dispatches_of_port(port["id"]):
        if existing["state"] not in calc.LIVE_DISPATCH_STATES:
            continue
        # half-open [start, end): touching endpoints do not overlap
        if window_start_at < existing["window_end_at"] and existing["window_start_at"] < window_end_at:
            raise err("ERR_DISPATCH_WINDOW_OVERLAP",
                      "The window intersects a live dispatch window on this dispenser.")

    host_site = db.host_sites.get(station["host_site_id"]) if station else None
    deadline = calc.dispatch_response_deadline(outage, station, host_site)

    row = db.base_record()
    row.update({
        "outage_event_id": outage["id"],
        "port_id": port["id"],
        "technician_user_id": technician_user_id,
        "technician_certification_class": certification_class,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "response_deadline_at": deadline,
        "arrived_at": None,
        "response_met": None,
        "promised_repair_at": None,
        "total_hold_minutes": None,
        "created_by_user_id": current_user_id(),
        "state": "CREATED",
    })
    db.dispatches[row["id"]] = row
    db.mark_fresh(row)

    outage["state"] = "DISPATCHED"
    outage["dispatch_created_by_user_id"] = current_user_id()
    db.touch(outage)

    if port["maintenance_state"] == "NONE":
        port["maintenance_state"] = "DISPATCH_PENDING"
        db.touch(port)

    return object_response(serialize.maintenance_dispatch(row), 201)


@bp.get("/maintenance-dispatches")
@endpoint()
def list_dispatches():
    limit, offset = validation.pagination()
    rows = db.sort_rows(list(db.dispatches.values()))
    rows = validation.apply_filters(rows, validation.filters(
        "outage_event_id", "port_id", "state", "technician_user_id"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.maintenance_dispatch(r) for r in page],
                          limit, offset, total)


@bp.get("/maintenance-dispatches/<dispatch_id>")
@endpoint()
def get_dispatch(dispatch_id):
    return object_response(serialize.maintenance_dispatch(lookup.dispatch(dispatch_id)))


@bp.post("/maintenance-dispatches/<dispatch_id>/progress")
@endpoint("FieldTechnician")
def post_progress(dispatch_id):
    dispatch = lookup.dispatch(dispatch_id)
    body = validation.json_body()
    event = validation.as_enum(body, "event", PROGRESS_EVENTS)

    port = db.ports.get(dispatch["port_id"])
    station = db.stations.get(port["station_id"]) if port else None

    if event == "EN_ROUTE":
        if dispatch["state"] != "CREATED":
            raise err("ERR_INVALID_STATE", "Only a CREATED dispatch may go EN_ROUTE.")
        _require_assigned_technician(dispatch)
        if not calc.station_is_serviceable(station):
            raise err("ERR_STATION_NOT_SERVICEABLE",
                      "The station must be OPERATIONAL or SUSPENDED.")
        dispatch["state"] = "EN_ROUTE"

    elif event == "ARRIVE":
        if dispatch["state"] != "EN_ROUTE":
            raise err("ERR_INVALID_STATE", "Only an EN_ROUTE dispatch may arrive on site.")
        _require_assigned_technician(dispatch)
        dispatch["state"] = "ON_SITE"
        dispatch["arrived_at"] = clock.now()
        dispatch["response_met"] = dispatch["arrived_at"] <= dispatch["response_deadline_at"]
        if port["maintenance_state"] == "DISPATCH_PENDING":
            port["maintenance_state"] = "UNDER_REPAIR"
            db.touch(port)

    else:  # RESUME_ONSITE
        if dispatch["state"] != "PARTS_HOLD":
            raise err("ERR_INVALID_STATE", "Only a PARTS_HOLD dispatch may resume on site.")
        _require_assigned_technician(dispatch)
        dispatch["state"] = "ON_SITE"
        if port["maintenance_state"] == "AWAITING_PARTS":
            port["maintenance_state"] = "UNDER_REPAIR"
            db.touch(port)

    db.touch(dispatch)
    return object_response(serialize.maintenance_dispatch(dispatch))


@bp.post("/maintenance-dispatches/<dispatch_id>/parts-hold")
@endpoint("FieldTechnician")
def parts_hold(dispatch_id):
    dispatch = lookup.dispatch(dispatch_id)

    if dispatch["state"] != "ON_SITE":
        raise err("ERR_INVALID_STATE", "Only an ON_SITE dispatch may be placed on parts hold.")
    _require_assigned_technician(dispatch)

    outstanding = [r for r in db.reservations_of_dispatch(dispatch["id"])
                   if r["state"] in ("RESERVED", "BACKORDERED")]
    if not outstanding:
        raise err("ERR_INVALID_STATE",
                  "A parts hold requires at least one outstanding part reservation.")

    total_hold_minutes, promised_repair_at = calc.parts_hold_promise(dispatch)
    dispatch["state"] = "PARTS_HOLD"
    dispatch["total_hold_minutes"] = total_hold_minutes
    dispatch["promised_repair_at"] = promised_repair_at
    db.touch(dispatch)

    port = db.ports.get(dispatch["port_id"])
    if port is not None and port["maintenance_state"] == "UNDER_REPAIR":
        port["maintenance_state"] = "AWAITING_PARTS"
        db.touch(port)

    return object_response(serialize.maintenance_dispatch(dispatch))


@bp.post("/maintenance-dispatches/<dispatch_id>/complete")
@endpoint("FieldTechnician")
def complete_dispatch(dispatch_id):
    dispatch = lookup.dispatch(dispatch_id)

    if dispatch["state"] != "ON_SITE":
        raise err("ERR_INVALID_STATE", "Only an ON_SITE dispatch may be completed.")
    _require_assigned_technician(dispatch)

    reservations = db.reservations_of_dispatch(dispatch["id"])
    if any(r["state"] == "BACKORDERED" for r in reservations):
        raise err("ERR_INVALID_STATE",
                  "A dispatch with a backordered part reservation may not be completed.")

    # link 1 — the dispatch itself and the stock it consumed
    dispatch["state"] = "COMPLETED"
    db.touch(dispatch)
    for reservation in reservations:
        if reservation["state"] != "RESERVED":
            continue
        reservation["state"] = "CONSUMED"
        db.touch(reservation)
        part = db.spare_parts.get(reservation["spare_part_id"])
        if part is not None:
            part["on_hand_qty"] = part["on_hand_qty"] - reservation["qty"]
            db.touch(part)

    # link 2 — the outage it was sent to clear
    outage = db.outages.get(dispatch["outage_event_id"])
    if outage is not None and outage["state"] == "DISPATCHED":
        outage["state"] = "RESOLVED"
        outage["cleared_at"] = clock.now()
        db.touch(outage)

    # links 3 and 4 — the dispenser's posture and availability, then the station
    port = db.ports.get(dispatch["port_id"])
    if port is not None:
        if port["service_state"] != "RETIRED":
            port["maintenance_state"] = cascades.rederive_maintenance_state(port)
            db.touch(port)
        cascades.port_back_in_service(port)

    return object_response(serialize.maintenance_dispatch(dispatch))
