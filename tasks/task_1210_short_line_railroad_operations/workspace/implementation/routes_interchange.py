"""InterchangeEvents and CarHireStatements (PRD 3.3)."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INTERCHANGE_DUPLICATE,
                    ERR_INTERCHANGE_DIRECTION_INVALID, not_found, invalid_state)
from util import (json_body, req_str, opt_str, opt_int, opt_dt, req_enum,
                  paginate)
from domain import (new_record, touch, interchange_event_view,
                    car_hire_statement_view, statement_final_cents, DIRECTIONS)

bp = Blueprint("interchange", __name__)

STATEMENT_READ_ROLES = ["SettlementClerk", "SystemAdmin"]


# ---------------------------------------------------------------------------
# Interchange events
# ---------------------------------------------------------------------------

def _has_open_received(railcar_id):
    """An open RECEIVED: REPORTED/CONFIRMED with no later CONFIRMED DELIVERED."""
    events = sorted((e for e in store.interchange_events.values()
                     if e["railcar_id"] == railcar_id), key=lambda e: e["_seq"])
    delivered_after = [e["_seq"] for e in events
                       if e["direction"] == "DELIVERED" and e["status"] == "CONFIRMED"]
    for e in events:
        if e["direction"] == "RECEIVED" and e["status"] in ("REPORTED", "CONFIRMED"):
            if not any(d > e["_seq"] for d in delivered_after):
                return True
    return False


@bp.post("/rail/interchange-events")
def create_interchange_event():
    uid, role = authenticate()
    body = json_body(required=True)
    class_i_partner = req_str(body, "class_i_partner")
    direction = req_enum(body, "direction", DIRECTIONS)
    railcar_id = req_str(body, "railcar_id")
    waybill_id = opt_str(body, "waybill_id")
    occurred_at = opt_dt(body, "occurred_at")
    miles = opt_int(body, "miles_traveled_on_line")
    require_role(role, ["Dispatcher"])
    car = store.railcars.get(railcar_id)
    if car is None:
        raise not_found("railcar not found")
    if waybill_id is not None and waybill_id not in store.waybills:
        raise not_found("waybill not found")
    if direction == "RECEIVED":
        # Constraint band: one open received event per car.
        if _has_open_received(railcar_id):
            raise ApiError(409, ERR_INTERCHANGE_DUPLICATE,
                           "an open RECEIVED event already exists for this railcar")
    else:  # DELIVERED (referential band)
        if car["status"] not in ("AVAILABLE", "LOADED", "IN_TRANSIT"):
            raise ApiError(409, ERR_INTERCHANGE_DIRECTION_INVALID,
                           "DELIVERED requires the car on line (AVAILABLE, LOADED, IN_TRANSIT)")
        if car["ownership"] == "FOREIGN" and miles is None:
            raise ApiError(409, ERR_INTERCHANGE_DIRECTION_INVALID,
                           "miles_traveled_on_line is required for DELIVERED FOREIGN cars")
    rec = new_record({
        "class_i_partner": class_i_partner,
        "direction": direction,
        "railcar_id": railcar_id,
        "waybill_id": waybill_id,
        "occurred_at": occurred_at if occurred_at is not None else store.now,
        "miles_traveled_on_line": miles,
        "status": "REPORTED",
    })
    store.interchange_events[rec["id"]] = rec
    return success_object(interchange_event_view(rec), status=201)


@bp.get("/rail/interchange-events")
def list_interchange_events():
    uid, role = authenticate()
    records = list(store.interchange_events.values())
    for param, field in (("railcar_id", "railcar_id"), ("waybill_id", "waybill_id"),
                         ("direction", "direction"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [e for e in records if e[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([interchange_event_view(e) for e in page], limit, offset, total)


def _get_event(eid):
    rec = store.interchange_events.get(eid)
    if rec is None:
        raise not_found("interchange event not found")
    return rec


@bp.get("/rail/interchange-events/<eid>")
def get_interchange_event(eid):
    uid, role = authenticate()
    return success_object(interchange_event_view(_get_event(eid)))


def _open_statement_for(railcar_id, period_month=None):
    candidates = [s for s in store.car_hire_statements.values()
                  if s["railcar_id"] == railcar_id and s["status"] == "OPEN"
                  and (period_month is None or s["period_month"] == period_month)]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s["_seq"])


@bp.post("/rail/interchange-events/<eid>/confirm")
def confirm_interchange_event(eid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    ev = _get_event(eid)
    if ev["status"] != "REPORTED":
        raise invalid_state("only a REPORTED event can be confirmed")
    car = store.railcars.get(ev["railcar_id"])
    if ev["direction"] == "RECEIVED":
        if car is not None and car["ownership"] == "FOREIGN":
            # Open (or reuse) the car-hire accrual for the current period.
            period = "%04d-%02d" % (store.now.year, store.now.month)
            stmt = _open_statement_for(car["id"], period)
            if stmt is not None:
                stmt["hire_accrual_start"] = store.now
                touch(stmt)
            else:
                stmt = new_record({
                    "railcar_id": car["id"],
                    "period_month": period,
                    "hire_accrual_start": store.now,
                    "hire_accrual_end": None,
                    "accrued_miles": 0,
                    "final_amount_cents": None,
                    "status": "OPEN",
                })
                store.car_hire_statements[stmt["id"]] = stmt
    else:  # DELIVERED
        if car is None or car["status"] not in ("AVAILABLE", "LOADED", "IN_TRANSIT"):
            raise invalid_state("car is not on line for a DELIVERED confirmation")
        car["status"] = "INTERCHANGED_OUT"
        touch(car)
        if car["ownership"] == "FOREIGN":
            stmt = _open_statement_for(car["id"])
            if stmt is not None:
                # Stop the meter: stamp the end, record the miles, freeze the
                # final amount, and close the statement.
                stmt["hire_accrual_end"] = store.now
                stmt["accrued_miles"] = ev["miles_traveled_on_line"] or 0
                stmt["final_amount_cents"] = statement_final_cents(stmt)
                stmt["status"] = "CLOSED"
                touch(stmt)
    ev["status"] = "CONFIRMED"
    touch(ev)
    return success_object(interchange_event_view(ev))


@bp.post("/rail/interchange-events/<eid>/dispute")
def dispute_interchange_event(eid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    ev = _get_event(eid)
    if ev["status"] != "CONFIRMED":
        raise invalid_state("only a CONFIRMED event can be disputed")
    ev["status"] = "DISPUTED"
    touch(ev)
    return success_object(interchange_event_view(ev))


@bp.post("/rail/interchange-events/<eid>/resolve")
def resolve_interchange_event(eid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    ev = _get_event(eid)
    if ev["status"] != "DISPUTED":
        raise invalid_state("only a DISPUTED event can be resolved")
    ev["status"] = "CONFIRMED"
    touch(ev)
    return success_object(interchange_event_view(ev))


# ---------------------------------------------------------------------------
# Car hire statements
# ---------------------------------------------------------------------------

@bp.get("/rail/car-hire-statements")
def list_statements():
    uid, role = authenticate()
    require_role(role, STATEMENT_READ_ROLES)
    records = list(store.car_hire_statements.values())
    for param, field in (("railcar_id", "railcar_id"),
                         ("period_month", "period_month"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [s for s in records if s[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([car_hire_statement_view(s) for s in page], limit, offset, total)


def _get_statement(sid):
    rec = store.car_hire_statements.get(sid)
    if rec is None:
        raise not_found("car hire statement not found")
    return rec


@bp.get("/rail/car-hire-statements/<sid>")
def get_statement(sid):
    uid, role = authenticate()
    require_role(role, STATEMENT_READ_ROLES)
    return success_object(car_hire_statement_view(_get_statement(sid)))


@bp.post("/rail/car-hire-statements/<sid>/close")
def close_statement(sid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    stmt = _get_statement(sid)
    if stmt["status"] != "OPEN":
        raise invalid_state("only an OPEN statement can be closed")
    stmt["hire_accrual_end"] = store.now
    stmt["final_amount_cents"] = statement_final_cents(stmt)
    stmt["status"] = "CLOSED"
    touch(stmt)
    return success_object(car_hire_statement_view(stmt))


@bp.post("/rail/car-hire-statements/<sid>/settle")
def settle_statement(sid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    stmt = _get_statement(sid)
    if stmt["status"] != "CLOSED":
        raise invalid_state("only a CLOSED statement can be settled")
    stmt["status"] = "SETTLED"
    touch(stmt)
    return success_object(car_hire_statement_view(stmt))


@bp.post("/rail/car-hire-statements/<sid>/dispute")
def dispute_statement(sid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    stmt = _get_statement(sid)
    if stmt["status"] != "CLOSED":
        raise invalid_state("only a CLOSED statement can be disputed")
    stmt["status"] = "DISPUTED"
    touch(stmt)
    return success_object(car_hire_statement_view(stmt))


@bp.post("/rail/car-hire-statements/<sid>/reopen")
def reopen_statement(sid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    stmt = _get_statement(sid)
    if stmt["status"] != "DISPUTED":
        raise invalid_state("only a DISPUTED statement can be reopened")
    # Recompute afresh at the next close: accrual resumes, frozen final clears.
    stmt["status"] = "OPEN"
    stmt["final_amount_cents"] = None
    stmt["hire_accrual_end"] = None
    touch(stmt)
    return success_object(car_hire_statement_view(stmt))
