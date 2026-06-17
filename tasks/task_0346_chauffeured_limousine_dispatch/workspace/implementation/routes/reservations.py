"""Reservation lifecycle: create/get/list, trip-events, wait-events,
billing-events, cancellation-record, flight-trackings list (PRD §3.2-§3.8)."""
from flask import Blueprint, request

import db
import views
from db import new_full, new_lean, touch
from errors import (
    ERR_ACCOUNT_SUSPENDED,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_WINDOW,
    ERR_NOT_BILLABLE,
    ERR_NOT_FOUND,
    ERR_TRIP_TYPE_FIELDS,
    ERR_VALIDATION_RANGE,
    ERR_WAIT_SEQUENCE,
    err,
)
from helpers import (
    as_enum,
    as_int,
    as_number,
    as_str,
    get_pagination,
    paginate,
    parse_dt,
    require_fields,
    sort_by_created,
)
from middleware import authenticate, require_role
from response import success
from routes.common import get_body, must_exist
from services import calc
from services.aggregates import recompute_outstanding_balance
from services.clock import current_utc_dt
from services.reservation_logic import (
    active_assignment_for,
    invoice_billable_amount,
    run_final_settlement,
    stamp_estimate,
)

bp = Blueprint("reservations", __name__)

TRIP_TYPES = {"POINT_TO_POINT", "HOURLY", "AIRPORT"}
TRIP_ACTIONS = {"QUOTE", "CONFIRM", "DISPATCH", "COMPLETE", "CANCEL"}
WAIT_KINDS = {"CHAUFFEUR_ARRIVED", "PASSENGER_BOARDED"}
BILLING_ACTIONS = {"INVOICE", "SETTLE", "WRITE_OFF"}


def _booker_owns(role, user_id, reservation):
    """CorporateBooker ownership: reservation.corporate_account_id == X-User-ID."""
    if role == "CorporateBooker" and reservation["corporate_account_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Booker may only act on its own account's reservations")


# --------------------------------------------------------------------------- #
# Create / Get / List
# --------------------------------------------------------------------------- #
@bp.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = authenticate()
    require_role(role, ["Dispatcher", "CorporateBooker"])
    body = get_body()
    require_fields(body, ["corporate_account_id", "trip_type", "vehicle_class_id",
                          "pickup_at", "planned_drop_at"])
    corporate_account_id = as_str(body["corporate_account_id"], "corporate_account_id")
    trip_type = as_enum(body["trip_type"], "trip_type", TRIP_TYPES)
    vehicle_class_id = as_str(body["vehicle_class_id"], "vehicle_class_id")
    pickup_raw = as_str(body["pickup_at"], "pickup_at")
    drop_raw = as_str(body["planned_drop_at"], "planned_drop_at")

    estimated_miles = body.get("estimated_miles", 0)
    if estimated_miles is None:
        estimated_miles = 0
    estimated_miles = as_number(estimated_miles, "estimated_miles")
    charter_hours = body.get("charter_hours", 0)
    if charter_hours is None:
        charter_hours = 0
    charter_hours = as_number(charter_hours, "charter_hours")
    tolls_cents = body.get("tolls_cents", 0)
    if tolls_cents is None:
        tolls_cents = 0
    tolls_cents = as_int(tolls_cents, "tolls_cents")
    gratuity_override = body.get("gratuity_pct_override")
    if gratuity_override is not None:
        gratuity_override = as_number(gratuity_override, "gratuity_pct_override")

    # Existence of body FKs (PRD §2.5).
    account = must_exist(db.corporate_accounts, corporate_account_id, "CorporateAccount")
    must_exist(db.vehicle_classes, vehicle_class_id, "VehicleClass")

    # Booker may only book for its own account (PRD §2.1).
    if role == "CorporateBooker" and corporate_account_id != user_id:
        raise err(ERR_FORBIDDEN, "Booker may only book for its own account")

    pickup = parse_dt(pickup_raw, "pickup_at")
    drop = parse_dt(drop_raw, "planned_drop_at")

    # planned_drop_at must be strictly after pickup_at (PRD §3.2, priority 5).
    if not (drop > pickup):
        raise err(ERR_INVALID_TIME_WINDOW, "planned_drop_at must be strictly after pickup_at")

    # trip-type-specific required fields (PRD §3.2, priority 6).
    if trip_type in ("POINT_TO_POINT", "AIRPORT"):
        if not (estimated_miles > 0):
            raise err(ERR_TRIP_TYPE_FIELDS, "estimated_miles must be greater than zero")
    elif trip_type == "HOURLY":
        if not (charter_hours > 0):
            raise err(ERR_TRIP_TYPE_FIELDS, "charter_hours must be greater than zero")

    if tolls_cents < 0:
        raise err(ERR_VALIDATION_RANGE, "tolls_cents must be zero or greater")
    if estimated_miles < 0:
        raise err(ERR_VALIDATION_RANGE, "estimated_miles must be zero or greater")
    if charter_hours < 0:
        raise err(ERR_VALIDATION_RANGE, "charter_hours must be zero or greater")

    # gratuity override range 0..30 (PRD §3.1, priority 17).
    if gratuity_override is not None and not (0 <= gratuity_override <= 30):
        raise err(ERR_VALIDATION_RANGE, "gratuity_pct_override must be between 0 and 30")

    rec = new_full({
        "corporate_account_id": corporate_account_id,
        "trip_type": trip_type,
        "vehicle_class_id": vehicle_class_id,
        "pickup_at": pickup_raw,
        "planned_drop_at": drop_raw,
        "estimated_miles": estimated_miles,
        "charter_hours": charter_hours,
        "tolls_cents": tolls_cents,
        "gratuity_pct_override": gratuity_override,
        "trip_status": "DRAFT",
        "settlement_status": "UNBILLED",
        "fulfillment_mode": "IN_HOUSE",
        "quote_estimate_total_cents": None,
        "final_total_cents": None,
        "chargeable_wait_minutes": 0,
        "cancellation_fee_cents": 0,
    })
    db.reservations[rec["id"]] = rec
    return success(views.reservation(rec), status=201)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "CorporateBooker", "Chauffeur"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    if role == "CorporateBooker":
        _booker_owns(role, user_id, rec)
    if role == "Chauffeur":
        _chauffeur_can_read(user_id, rec)
    return success(views.reservation(rec))


def _chauffeur_can_read(user_id, reservation):
    """A chauffeur may read a reservation they are assigned to (PRD §2.1)."""
    for a in db.assignments.values():
        if a["reservation_id"] == reservation["id"] and a["chauffeur_id"] == user_id:
            return
    raise err(ERR_FORBIDDEN, "Chauffeur may only read their own trips")


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "CorporateBooker"])
    limit, offset = get_pagination(request.args)
    items = list(db.reservations.values())
    acct = request.args.get("corporate_account_id")
    vclass = request.args.get("vehicle_class_id")
    if acct is not None:
        items = [r for r in items if r["corporate_account_id"] == acct]
    if vclass is not None:
        items = [r for r in items if r["vehicle_class_id"] == vclass]
    # Booker only sees its own account's reservations (PRD §2.1).
    if role == "CorporateBooker":
        items = [r for r in items if r["corporate_account_id"] == user_id]
    items = sort_by_created(items)
    window, pagination = paginate(items, limit, offset)
    return success([views.reservation(r) for r in window], pagination=pagination)


# --------------------------------------------------------------------------- #
# Trip events
# --------------------------------------------------------------------------- #
@bp.route("/reservations/<reservation_id>/trip-events", methods=["POST"])
def trip_events(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["Dispatcher", "CorporateBooker", "Chauffeur"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    body = get_body()
    require_fields(body, ["action"])
    action = as_enum(body["action"], "action", TRIP_ACTIONS)

    if action == "QUOTE":
        return _quote(rec, role, user_id)
    if action == "CONFIRM":
        return _confirm(rec, role, user_id)
    if action == "DISPATCH":
        return _dispatch(rec, role, user_id)
    if action == "COMPLETE":
        return _complete(rec, role, user_id)
    if action == "CANCEL":
        return _cancel(rec, role, user_id)


def _quote(rec, role, user_id):
    # QUOTE: Dispatcher or CorporateBooker (endpoint + RBAC matrix).
    if role not in ("Dispatcher", "CorporateBooker"):
        raise err(ERR_FORBIDDEN, "Only a Dispatcher or CorporateBooker may quote")
    _booker_owns(role, user_id, rec)
    if rec["trip_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Reservation is not DRAFT")
    vclass = db.vehicle_classes[rec["vehicle_class_id"]]
    if vclass["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Vehicle class is not ACTIVE")
    stamp_estimate(rec)
    rec["trip_status"] = "QUOTED"
    touch(rec)
    return success(views.reservation(rec))


def _confirm(rec, role, user_id):
    # CONFIRM: Dispatcher or CorporateBooker (PRD §3.3).
    if role not in ("Dispatcher", "CorporateBooker"):
        raise err(ERR_FORBIDDEN, "Only a Dispatcher or CorporateBooker may confirm")
    _booker_owns(role, user_id, rec)
    if rec["trip_status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Reservation is not QUOTED")
    account = db.corporate_accounts[rec["corporate_account_id"]]
    if account["status"] != "ACTIVE":
        raise err(ERR_ACCOUNT_SUSPENDED, "Corporate account is suspended")
    rec["trip_status"] = "CONFIRMED"
    touch(rec)
    return success(views.reservation(rec))


def _dispatch(rec, role, user_id):
    # DISPATCH: Dispatcher or the assigned Chauffeur (PRD §3.3).
    if role not in ("Dispatcher", "Chauffeur"):
        raise err(ERR_FORBIDDEN, "Only a Dispatcher or Chauffeur may dispatch")
    if rec["trip_status"] != "ASSIGNED":
        raise err(ERR_INVALID_STATE, "Reservation is not ASSIGNED")
    assignment = active_assignment_for(rec["id"])
    if assignment is None:
        raise err(ERR_INVALID_STATE, "No active assignment for this reservation")
    # Chauffeur ownership: must be the assigned chauffeur (PRD §2.1).
    if role == "Chauffeur" and assignment["chauffeur_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Chauffeur may only dispatch their own trip")
    chauffeur = db.chauffeurs[assignment["chauffeur_id"]]
    rec["trip_status"] = "EN_ROUTE"
    touch(rec)
    # Cascade hop 2: Chauffeur ON_DUTY -> ON_TRIP, set active_assignment_id (PRD §3.3).
    chauffeur["status"] = "ON_TRIP"
    chauffeur["active_assignment_id"] = assignment["id"]
    touch(chauffeur)
    return success(views.reservation(rec))


def _complete(rec, role, user_id):
    # COMPLETE: Dispatcher or the assigned Chauffeur (PRD §3.4).
    if role not in ("Dispatcher", "Chauffeur"):
        raise err(ERR_FORBIDDEN, "Only a Dispatcher or Chauffeur may complete")
    if rec["trip_status"] != "PASSENGER_ABOARD":
        raise err(ERR_INVALID_STATE, "Reservation is not PASSENGER_ABOARD")
    assignment = active_assignment_for(rec["id"])
    if role == "Chauffeur":
        if assignment is None or assignment["chauffeur_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Chauffeur may only complete their own trip")
    run_final_settlement(rec)
    rec["trip_status"] = "COMPLETED"
    touch(rec)
    # Operational unwind (PRD §3.4).
    if assignment is not None:
        chauffeur = db.chauffeurs[assignment["chauffeur_id"]]
        chauffeur["status"] = "ON_DUTY"
        chauffeur["active_assignment_id"] = None
        touch(chauffeur)
        assignment["status"] = "RELEASED"
        touch(assignment)
    return success(views.reservation(rec))


def _cancel(rec, role, user_id):
    # CANCEL: Dispatcher or CorporateBooker; EN_ROUTE cancel is Dispatcher-only (PRD §3.7).
    if role not in ("Dispatcher", "CorporateBooker"):
        raise err(ERR_FORBIDDEN, "Only a Dispatcher or CorporateBooker may cancel")
    _booker_owns(role, user_id, rec)
    status = rec["trip_status"]
    if status not in ("DRAFT", "QUOTED", "CONFIRMED", "ASSIGNED", "EN_ROUTE"):
        raise err(ERR_INVALID_STATE, "Reservation cannot be cancelled from this state")
    if status == "EN_ROUTE" and role != "Dispatcher":
        raise err(ERR_FORBIDDEN, "Only a Dispatcher may cancel an EN_ROUTE reservation")

    account = db.corporate_accounts[rec["corporate_account_id"]]
    now_dt = current_utc_dt()
    tier, lead_minutes, fee = calc.cancellation_tier(rec, account, now_dt)
    rec["cancellation_fee_cents"] = fee

    assignment = active_assignment_for(rec["id"])
    if status == "ASSIGNED" and assignment is not None:
        # release assignment; revert chauffeur ON_DUTY -> OFF_DUTY (PRD §3.7).
        chauffeur = db.chauffeurs[assignment["chauffeur_id"]]
        assignment["status"] = "RELEASED"
        touch(assignment)
        chauffeur["status"] = "OFF_DUTY"
        chauffeur["active_assignment_id"] = None
        touch(chauffeur)
    elif status == "EN_ROUTE" and assignment is not None:
        # release assignment; revert chauffeur ON_TRIP -> OFF_DUTY, clear ptr (PRD §3.7).
        chauffeur = db.chauffeurs[assignment["chauffeur_id"]]
        assignment["status"] = "RELEASED"
        touch(assignment)
        chauffeur["status"] = "OFF_DUTY"
        chauffeur["active_assignment_id"] = None
        touch(chauffeur)

    rec["trip_status"] = "CANCELLED"
    touch(rec)

    cr = new_lean({
        "reservation_id": rec["id"],
        "tier": tier,
        "lead_minutes": lead_minutes,
        "fee_cents": fee,
    })
    db.cancellation_records[cr["id"]] = cr
    return success(views.reservation(rec))


# --------------------------------------------------------------------------- #
# Wait events
# --------------------------------------------------------------------------- #
@bp.route("/reservations/<reservation_id>/wait-events", methods=["POST"])
def create_wait_event(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["Dispatcher", "Chauffeur"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    body = get_body()
    require_fields(body, ["kind", "occurred_at"])
    kind = as_enum(body["kind"], "kind", WAIT_KINDS)
    occurred_raw = as_str(body["occurred_at"], "occurred_at")
    occurred_at = parse_dt(occurred_raw, "occurred_at")

    # Chauffeur ownership: must be the assigned chauffeur (PRD §2.1).
    if role == "Chauffeur":
        assignment = active_assignment_for(rec["id"])
        if assignment is None or assignment["chauffeur_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Chauffeur may only act on their own trip")

    existing = sort_by_created([w for w in db.wait_events.values()
                                if w["reservation_id"] == rec["id"]])

    if kind == "CHAUFFEUR_ARRIVED":
        # Sequence first (PRD §3.4): a duplicate CHAUFFEUR_ARRIVED is out of order.
        if any(w["kind"] == "CHAUFFEUR_ARRIVED" for w in existing):
            raise err(ERR_WAIT_SEQUENCE, "CHAUFFEUR_ARRIVED already recorded")
        # state must be EN_ROUTE (PRD §3.4).
        if rec["trip_status"] != "EN_ROUTE":
            raise err(ERR_INVALID_STATE, "Reservation is not EN_ROUTE")
        we = _append_wait(rec, kind, occurred_raw)
        rec["trip_status"] = "ON_LOCATION"
        touch(rec)
        return success(views.wait_event(we), status=201)

    # PASSENGER_BOARDED — sequence checks precede the state check (PRD §3.4):
    # a PASSENGER_BOARDED before any arrival is rejected with ERR_WAIT_SEQUENCE.
    arrived = next((w for w in existing if w["kind"] == "CHAUFFEUR_ARRIVED"), None)
    if arrived is None:
        raise err(ERR_WAIT_SEQUENCE, "PASSENGER_BOARDED requires a prior CHAUFFEUR_ARRIVED")
    arrived_dt = parse_dt(arrived["occurred_at"], "occurred_at")
    # occurred_at must not predate the prior event (PRD §3.4).
    if not (occurred_at > arrived_dt):
        raise err(ERR_WAIT_SEQUENCE, "PASSENGER_BOARDED must occur after CHAUFFEUR_ARRIVED")
    # state must be ON_LOCATION (PRD §3.4).
    if rec["trip_status"] != "ON_LOCATION":
        raise err(ERR_INVALID_STATE, "Reservation is not ON_LOCATION")

    we = _append_wait(rec, kind, occurred_raw)
    # run wait_time, stamp chargeable_wait_minutes (PRD §3.4).
    vclass = db.vehicle_classes[rec["vehicle_class_id"]]
    rec["chargeable_wait_minutes"] = calc.wait_time(arrived_dt, occurred_at, vclass)
    rec["trip_status"] = "PASSENGER_ABOARD"
    touch(rec)
    return success(views.wait_event(we), status=201)


def _append_wait(rec, kind, occurred_raw):
    we = new_lean({
        "reservation_id": rec["id"],
        "kind": kind,
        "occurred_at": occurred_raw,
    })
    db.wait_events[we["id"]] = we
    return we


@bp.route("/reservations/<reservation_id>/wait-events", methods=["GET"])
def list_wait_events(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "Chauffeur"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    if role == "Chauffeur":
        _chauffeur_can_read(user_id, rec)
    limit, offset = get_pagination(request.args)
    items = sort_by_created([w for w in db.wait_events.values()
                             if w["reservation_id"] == reservation_id])
    window, pagination = paginate(items, limit, offset)
    return success([views.wait_event(w) for w in window], pagination=pagination)


# --------------------------------------------------------------------------- #
# Billing events
# --------------------------------------------------------------------------- #
@bp.route("/reservations/<reservation_id>/billing-events", methods=["POST"])
def billing_events(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["Dispatcher", "DispatchAdmin"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    body = get_body()
    require_fields(body, ["action"])
    action = as_enum(body["action"], "action", BILLING_ACTIONS)

    if action == "INVOICE":
        # INVOICE: Dispatcher (and DispatchAdmin superset).
        if role not in ("Dispatcher", "DispatchAdmin"):
            raise err(ERR_FORBIDDEN, "Only a Dispatcher may invoice")
        if rec["settlement_status"] != "UNBILLED":
            raise err(ERR_INVALID_STATE, "Reservation is not UNBILLED")
        if rec["trip_status"] not in ("COMPLETED", "CANCELLED"):
            raise err(ERR_NOT_BILLABLE, "Reservation is neither COMPLETED nor CANCELLED")
        if invoice_billable_amount(rec) is None:
            raise err(ERR_NOT_BILLABLE, "Reservation has no known final amount")
        rec["settlement_status"] = "INVOICED"
        touch(rec)
        recompute_outstanding_balance(rec["corporate_account_id"])
        return success(views.reservation(rec))

    if action == "SETTLE":
        if role not in ("Dispatcher", "DispatchAdmin"):
            raise err(ERR_FORBIDDEN, "Only a Dispatcher may settle")
        if rec["settlement_status"] != "INVOICED":
            raise err(ERR_INVALID_STATE, "Reservation is not INVOICED")
        rec["settlement_status"] = "SETTLED"
        touch(rec)
        recompute_outstanding_balance(rec["corporate_account_id"])
        return success(views.reservation(rec))

    # WRITE_OFF — reserved for DispatchAdmin (PRD §3.8).
    if role != "DispatchAdmin":
        raise err(ERR_FORBIDDEN, "Write-off is reserved for DispatchAdmin")
    if rec["settlement_status"] != "INVOICED":
        raise err(ERR_INVALID_STATE, "Reservation is not INVOICED")
    rec["settlement_status"] = "WRITTEN_OFF"
    touch(rec)
    recompute_outstanding_balance(rec["corporate_account_id"])
    return success(views.reservation(rec))


# --------------------------------------------------------------------------- #
# Cancellation record
# --------------------------------------------------------------------------- #
@bp.route("/reservations/<reservation_id>/cancellation-record", methods=["GET"])
def get_cancellation_record(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "CorporateBooker"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    if role == "CorporateBooker":
        _booker_owns(role, user_id, rec)
    limit, offset = get_pagination(request.args)
    items = sort_by_created([c for c in db.cancellation_records.values()
                             if c["reservation_id"] == reservation_id])
    window, pagination = paginate(items, limit, offset)
    return success([views.cancellation_record(c) for c in window], pagination=pagination)


# --------------------------------------------------------------------------- #
# Flight trackings for a reservation
# --------------------------------------------------------------------------- #
@bp.route("/reservations/<reservation_id>/flight-trackings", methods=["GET"])
def list_reservation_flight_trackings(reservation_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "CorporateBooker", "Chauffeur"])
    rec = must_exist(db.reservations, reservation_id, "Reservation")
    if role == "CorporateBooker":
        _booker_owns(role, user_id, rec)
    if role == "Chauffeur":
        _chauffeur_can_read(user_id, rec)
    limit, offset = get_pagination(request.args)
    items = sort_by_created([f for f in db.flight_trackings.values()
                             if f["reservation_id"] == reservation_id])
    window, pagination = paginate(items, limit, offset)
    return success([views.flight_tracking(f) for f in window], pagination=pagination)
