"""Filing, departure, cancellation and cargo release (PRD 3.2, 3.3, 3.5)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("movements", __name__)

IN_BOND_TYPES = ("IT", "TE", "IE")
AMENDABLE = ("FILED", "IN_TRANSIT", "OVERDUE")


def covers_transit(bond, deadline):
    if bond["effective_date"] > db.now:
        return False
    if bond["expiry_date"] < deadline + calc.days(calc.BOND_COVERAGE_MARGIN_DAYS):
        return False
    return True


def stb_conflict(bond, filed_at, deadline, exclude_id=None):
    """Closed-interval window collision on a SINGLE_TRANSACTION bond."""
    if bond["bond_type"] != "SINGLE_TRANSACTION":
        return False
    for other in domain.rows(db.movements):
        if other["id"] == exclude_id or other["bond_id"] != bond["id"]:
            continue
        if other["transit_status"] not in calc.OPEN_MOVEMENT_STATUSES:
            continue
        if calc.closed_windows_collide(filed_at, deadline,
                                       other["filed_at"], other["transit_deadline_utc"]):
            return True
    return False


def route_shape_ok(in_bond_type, origin_port_id, destination_port_id):
    if in_bond_type == "IE":
        return origin_port_id == destination_port_id
    return origin_port_id != destination_port_id


# --------------------------------------------------------------------------
# POST /in-bond/movements
# --------------------------------------------------------------------------
@bp.route("/in-bond/movements", methods=["POST"])
def file_movement():
    user_id, _role = require("BondedCarrier")

    # Band 3 sits ahead of request-shape validation (PRD 2.10).
    peeked = v.peek_body().get("carrier_id")
    if isinstance(peeked, str) and peeked != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    carrier_id = v.req_str(body, "carrier_id")
    in_bond_type = v.req_enum(body, "in_bond_type", IN_BOND_TYPES)
    origin_port_id = v.req_str(body, "origin_port_id")
    destination_port_id = v.req_str(body, "destination_port_id")
    manifest_reference = v.req_str(body, "manifest_reference")
    cargo_value = v.req_money(body, "cargo_value", positive=True)
    gross_weight_kg = v.req_money(body, "gross_weight_kg", positive=True)
    package_count = v.req_int(body, "package_count", minimum=1)
    bond_id = v.opt_str(body, "bond_id")
    predecessor_movement_id = v.opt_str(body, "predecessor_movement_id")
    if carrier_id != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    # Band 6 - existence, carrier then bond then ports then predecessor.
    carrier = db.carriers.get(carrier_id)
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    bond = None
    if bond_id is not None:
        bond = db.bonds.get(bond_id)
        if bond is None:
            raise ApiError("ERR_BOND_NOT_FOUND")
    origin = db.ports.get(origin_port_id)
    if origin is None:
        raise ApiError("ERR_PORT_NOT_FOUND")
    destination = db.ports.get(destination_port_id)
    if destination is None:
        raise ApiError("ERR_PORT_NOT_FOUND")
    predecessor = None
    if predecessor_movement_id is not None:
        predecessor = db.movements.get(predecessor_movement_id)
        if predecessor is None:
            raise ApiError("ERR_MOVEMENT_NOT_FOUND")

    # Band 10 - other records' state.
    if carrier["custodial_status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_NOT_ACTIVE")
    if bond is not None and bond["status"] != "ACTIVE":
        raise ApiError("ERR_BOND_NOT_ACTIVE")
    if predecessor is not None:
        if predecessor["carrier_id"] != carrier_id or predecessor["transit_status"] != "ARRIVED":
            raise ApiError("ERR_PREDECESSOR_NOT_ARRIVED")

    filed_at = db.now
    obligation = calc.movement_obligation(cargo_value, gross_weight_kg, package_count)
    transit_days = calc.transit_allowance(in_bond_type, origin["region_code"],
                                          destination["region_code"],
                                          carrier["sanction_points"], 0)
    deadline = calc.deadline_from(filed_at, transit_days)

    # Band 12 - temporal: the bond must cover the whole transit.
    if bond is not None and not covers_transit(bond, deadline):
        raise ApiError("ERR_BOND_COVERAGE_GAP")

    # Band 13 - business constraints.
    if not route_shape_ok(in_bond_type, origin_port_id, destination_port_id):
        raise ApiError("ERR_ROUTE_TYPE_MISMATCH")
    if bond is not None and stb_conflict(bond, filed_at, deadline):
        raise ApiError("ERR_STB_WINDOW_CONFLICT")

    # Band 14 - fiscal.
    if bond is None:
        candidates = []
        for candidate in domain.rows(db.bonds):
            if candidate["carrier_id"] != carrier_id:
                continue
            if candidate["status"] != "ACTIVE":
                continue
            if not covers_transit(candidate, deadline):
                continue
            if candidate["available_amount"] < obligation:
                continue
            if stb_conflict(candidate, filed_at, deadline):
                continue
            candidates.append(candidate)
        if not candidates:
            raise ApiError("ERR_NO_ELIGIBLE_BOND")
        candidates.sort(key=lambda b: (0 if b["bond_type"] == "CONTINUOUS" else 1,
                                       -b["available_amount"]))
        bond = candidates[0]
    elif obligation > bond["available_amount"]:
        raise ApiError("ERR_BOND_INSUFFICIENT")

    rec = new_record()
    rec.update({
        "carrier_id": carrier_id,
        "bond_id": bond["id"],
        "origin_port_id": origin_port_id,
        "destination_port_id": destination_port_id,
        "arrival_port_id": None,
        "predecessor_movement_id": predecessor_movement_id,
        "in_bond_type": in_bond_type,
        "manifest_reference": manifest_reference,
        "cargo_value": calc.round2(cargo_value),
        "gross_weight_kg": calc.round2(gross_weight_kg),
        "package_count": package_count,
        "transit_status": "FILED",
        "custody_status": "BONDED",
        "obligation_amount": obligation,
        "transit_days_allowed": transit_days,
        "deadline_anchor_utc": filed_at,
        "transit_deadline_utc": deadline,
        "extension_days_granted": 0,
        "overdue_days": 0,
        "filed_at": filed_at,
        "seal_number": None,
        "seal_intact": False,
        "arrival_reported_at": None,
        "export_reported_at": None,
        "go_deadline_utc": None,
        "go_grace_applied": False,
        "diversion_flag": False,
        "cancellation_reason": None,
    })
    db.movements[rec["id"]] = rec
    domain.append_ledger(bond, rec["id"], "OBLIGATE", obligation, "MOVEMENT_FILED")
    return ok(domain.movement_json(rec), 201)


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@bp.route("/in-bond/movements/<movement_id>", methods=["GET"])
def read_movement(movement_id):
    require(*ALL_ROLES)
    rec = db.movements.get(movement_id)
    if rec is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    return ok(domain.movement_json(rec))


@bp.route("/in-bond/movements", methods=["GET"])
def list_movements():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = domain.rows(db.movements)
    for key in ("carrier_id", "bond_id", "origin_port_id", "destination_port_id",
                "arrival_port_id", "predecessor_movement_id", "in_bond_type",
                "transit_status", "custody_status"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [m for m in items if m[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.movement_json(m) for m in page], limit, offset, total)


# --------------------------------------------------------------------------
# POST /in-bond/movements/{id}/departure
# --------------------------------------------------------------------------
@bp.route("/in-bond/movements/<movement_id>/departure", methods=["POST"])
def depart(movement_id):
    user_id, _role = require("BondedCarrier")
    rec = db.movements.get(movement_id)
    if rec is not None and rec["carrier_id"] != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    seal_number = v.req_str(body, "seal_number")

    if rec is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    if rec["transit_status"] != "FILED":
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")
    if rec["custody_status"] != "BONDED" or domain.open_holds(rec["id"]):
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")

    carrier = db.carriers.get(rec["carrier_id"])
    if carrier is None or carrier["custodial_status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_NOT_ACTIVE")
    bond = db.bonds.get(rec["bond_id"])
    if bond is None or bond["status"] != "ACTIVE":
        raise ApiError("ERR_BOND_NOT_ACTIVE")

    origin = db.ports.get(rec["origin_port_id"])
    event = new_record(full=False)
    event.update({
        "movement_id": rec["id"],
        "seal_number": seal_number,
        "event_type": "APPLIED",
        "port_code": origin["port_code"] if origin else None,
        "recorded_by_user_id": user_id,
        "occurred_at": db.now,
        "resulting_seal_intact": True,
    })
    db.seal_events[event["id"]] = event

    rec["transit_status"] = "IN_TRANSIT"
    rec["seal_number"] = seal_number
    rec["seal_intact"] = True
    touch(rec)
    return ok(domain.movement_json(rec))


# --------------------------------------------------------------------------
# POST /in-bond/movements/{id}/cancellation
# --------------------------------------------------------------------------
@bp.route("/in-bond/movements/<movement_id>/cancellation", methods=["POST"])
def cancel(movement_id):
    user_id, _role = require("BondedCarrier")
    rec = db.movements.get(movement_id)
    if rec is not None and rec["carrier_id"] != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    reason_code = v.req_str(body, "reason_code")

    if rec is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    if rec["transit_status"] != "FILED":
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")

    rec["transit_status"] = "CANCELLED"
    rec["cancellation_reason"] = reason_code
    touch(rec)
    bond = db.bonds.get(rec["bond_id"])
    domain.append_ledger(bond, rec["id"], "RELEASE",
                         -rec["obligation_amount"], "MOVEMENT_CANCELLED")
    return ok(domain.movement_json(rec))


# --------------------------------------------------------------------------
# POST /in-bond/movements/{id}/release  (cargo release from CBP custody)
# --------------------------------------------------------------------------
@bp.route("/in-bond/movements/<movement_id>/release", methods=["POST"])
def release_cargo(movement_id):
    require("CBPOfficer")
    body = v.get_body()
    v.opt_str(body, "reason_code")  # accepted, but the PRD stores no field for it

    rec = db.movements.get(movement_id)
    if rec is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")

    if rec["transit_status"] not in ("ARRIVED", "EXPORTED"):
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")
    if rec["custody_status"] == "RELEASED":
        raise ApiError("ERR_MOVEMENT_INVALID_STATE")
    if rec["custody_status"] == "GENERAL_ORDER":
        raise ApiError("ERR_MOVEMENT_IN_GENERAL_ORDER")
    if not rec["seal_intact"]:
        raise ApiError("ERR_SEAL_INTEGRITY_UNRESOLVED")
    if domain.open_holds(rec["id"]):
        raise ApiError("ERR_HOLD_OPEN")

    rec["custody_status"] = "RELEASED"
    close = rec["in_bond_type"] == "IT" and rec["transit_status"] == "ARRIVED"
    if close:
        rec["transit_status"] = "CLOSED"
    touch(rec)
    if close:
        bond = db.bonds.get(rec["bond_id"])
        domain.append_ledger(bond, rec["id"], "RELEASE",
                             -rec["obligation_amount"], "CARGO_RELEASED")
    return ok(domain.movement_json(rec))


# --------------------------------------------------------------------------
# nested reads: seal history and amendment history
# --------------------------------------------------------------------------
@bp.route("/in-bond/movements/<movement_id>/seal-events", methods=["GET"])
def list_seal_events(movement_id):
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    if db.movements.get(movement_id) is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    items = [e for e in db.seal_events.values() if e["movement_id"] == movement_id]
    items.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    event_type = request.args.get("event_type")
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.seal_event_json(e) for e in page], limit, offset, total)


@bp.route("/in-bond/movements/<movement_id>/amendment-requests", methods=["GET"])
def list_amendments(movement_id):
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    if db.movements.get(movement_id) is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")
    items = domain.amendments_of(movement_id)
    for key in ("amendment_type", "status"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [a for a in items if a[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.amendment_json(a) for a in page], limit, offset, total)


# --------------------------------------------------------------------------
# ledger entries
# --------------------------------------------------------------------------
@bp.route("/in-bond/ledger-entries/<entry_id>", methods=["GET"])
def read_ledger_entry(entry_id):
    require(*ALL_ROLES)
    rec = db.ledger_entries.get(entry_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return ok(domain.ledger_json(rec))


@bp.route("/in-bond/ledger-entries", methods=["GET"])
def list_ledger_entries():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = domain.rows(db.ledger_entries)
    for key in ("bond_id", "movement_id", "claim_id", "entry_type"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [e for e in items if e[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.ledger_json(e) for e in page], limit, offset, total)
