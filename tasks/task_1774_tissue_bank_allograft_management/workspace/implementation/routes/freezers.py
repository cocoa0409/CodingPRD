"""Freezers, temperature readings, and manual excursion reports (PRD §3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_FREEZER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TEMP_RANGE,
    ERR_DUPLICATE_VALUE,
    ERR_STALE_VERSION,
    ERR_CAPACITY_BELOW_OCCUPIED,
    ERR_EXCURSION_INVALID_STATE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import domain
from util import fmt_dt, dec
from validate import get_body, req_str, req_num, opt_num, opt_int, paginate, MISSING

bp = Blueprint("freezers", __name__)

ANY = ALL_ROLES


def get_freezer_or_404(freezer_id: str) -> dict:
    freezer = db["freezers"].get(freezer_id)
    if freezer is None:
        raise_error(ERR_FREEZER_NOT_FOUND, f"freezer {freezer_id} does not exist")
    return freezer


# ---------------------------------------------------------------------------
# Freezer registry
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/freezers", methods=["POST"])
def create_freezer():
    require_roles({"SupplyChainAdmin"})
    body = get_body()
    name = req_str(body, "name")
    min_celsius = req_num(body, "min_celsius")
    max_celsius = req_num(body, "max_celsius")
    nominal_capacity = body.get("nominal_capacity", MISSING)
    if nominal_capacity is MISSING:
        raise_error(ERR_INVALID_REQUEST, "missing required field: nominal_capacity")
    if isinstance(nominal_capacity, bool) or not isinstance(nominal_capacity, int) or nominal_capacity < 1:
        raise_error(ERR_INVALID_REQUEST, "nominal_capacity must be an integer >= 1")
    if dec(min_celsius) >= dec(max_celsius):
        raise_error(ERR_INVALID_TEMP_RANGE, "min_celsius must be strictly below max_celsius")
    if any(f["name"] == name for f in db["freezers"].values()):
        raise_error(ERR_DUPLICATE_VALUE, f"freezer name {name} is already registered")
    freezer = {
        "name": name,
        "min_celsius": min_celsius,
        "max_celsius": max_celsius,
        "nominal_capacity": nominal_capacity,
        "status": "OPERATIONAL",
        "current_excursion_id": None,
    }
    domain.stamp_new(freezer)
    db["freezers"][freezer["id"]] = freezer
    return success_object(domain.freezer_json(freezer), status=201)


@bp.route("/tissue-bank/freezers", methods=["GET"])
def list_freezers():
    require_roles(ANY)
    items = list(db["freezers"].values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [f for f in items if f["status"] == status_filter]
    excursion_filter = request.args.get("current_excursion_id")
    if excursion_filter is not None:
        items = [f for f in items if f["current_excursion_id"] == excursion_filter]
    items.sort(key=lambda f: (f["_created_dt"], f["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.freezer_json(f) for f in page], total, limit, offset)


@bp.route("/tissue-bank/freezers/<freezer_id>", methods=["GET"])
def get_freezer(freezer_id):
    require_roles(ANY)
    return success_object(domain.freezer_json(get_freezer_or_404(freezer_id)))


@bp.route("/tissue-bank/freezers/<freezer_id>", methods=["PUT"])
def reconfigure_freezer(freezer_id):
    require_roles({"SupplyChainAdmin"})
    freezer = get_freezer_or_404(freezer_id)
    body = get_body()
    # request shape (rung 3.4): provided fields typed; expected version mandatory
    min_celsius = opt_num(body, "min_celsius")
    max_celsius = opt_num(body, "max_celsius")
    nominal_capacity = opt_int(body, "nominal_capacity", min_val=1)
    expected = body.get("expected_freezer_version", MISSING)
    if expected is MISSING or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_freezer_version is required and must be an integer")
    new_min = min_celsius if min_celsius is not None else freezer["min_celsius"]
    new_max = max_celsius if max_celsius is not None else freezer["max_celsius"]
    if dec(new_min) >= dec(new_max):
        raise_error(ERR_INVALID_TEMP_RANGE, "min_celsius must be strictly below max_celsius")
    # OCC (rung 3.5) — before any business rule
    if expected != freezer["version"]:
        raise_error(ERR_STALE_VERSION, f"expected_freezer_version {expected} does not match current version {freezer['version']}")
    # structural: capacity revalidation against the re-derived reserve
    if nominal_capacity is not None:
        occ = domain.freezer_occupied_count(freezer["id"])
        from fractions import Fraction
        new_util = Fraction(occ * 100, nominal_capacity)
        new_reserve = domain.RESERVED_SLOTS if new_util >= domain.RESERVE_TRIGGER_UTILIZATION else 0
        if occ > nominal_capacity - new_reserve:
            raise_error(
                ERR_CAPACITY_BELOW_OCCUPIED,
                f"nominal_capacity {nominal_capacity} strands {occ} stored unit(s) under reserve {new_reserve}",
            )
    if min_celsius is not None:
        freezer["min_celsius"] = min_celsius
    if max_celsius is not None:
        freezer["max_celsius"] = max_celsius
    if nominal_capacity is not None:
        freezer["nominal_capacity"] = nominal_capacity
    domain.touch(freezer)
    return success_object(domain.freezer_json(freezer))


# ---------------------------------------------------------------------------
# Temperature readings
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/freezers/<freezer_id>/readings", methods=["POST"])
def create_reading(freezer_id):
    caller = require_roles({"TissueBankCoordinator"})
    freezer = get_freezer_or_404(freezer_id)
    body = get_body()
    temp_celsius = req_num(body, "temp_celsius")
    # in_range snapshots the freezer's bounds as they stand at record time
    in_range = dec(freezer["min_celsius"]) <= dec(temp_celsius) <= dec(freezer["max_celsius"])
    now = domain.CLOCK.now()
    reading = {
        "freezer_id": freezer["id"],
        "temp_celsius": temp_celsius,
        "in_range": in_range,
        "recorded_by_user_id": caller.user_id,
        "excursion_id": None,
    }
    # immutable observation: id + created_at only (no version / updated_at)
    from util import new_id, fmt_dt_full
    reading["id"] = new_id()
    reading["created_at"] = fmt_dt_full(now)
    reading["_created_dt"] = now
    reading["_seq"] = domain.next_seq()
    db["readings"][reading["id"]] = reading

    if not in_range:
        deviation = max(
            dec(0),
            dec(temp_celsius) - dec(freezer["max_celsius"]),
            dec(freezer["min_celsius"]) - dec(temp_celsius),
        )
        if freezer["status"] == "OPERATIONAL":
            excursion = domain.open_excursion(freezer, "AUTO_READING", None, float(deviation))
        else:
            # extend the freezer's unresolved excursion
            excursion = db["excursions"][freezer["current_excursion_id"]]
            if deviation > dec(excursion["max_deviation_celsius"]):
                excursion["max_deviation_celsius"] = float(deviation)
            excursion["last_reading_at"] = fmt_dt(now)
            domain.touch(excursion)
        reading["excursion_id"] = excursion["id"]
    return success_object(domain.reading_json(reading), status=201)


@bp.route("/tissue-bank/freezers/<freezer_id>/readings", methods=["GET"])
def list_readings(freezer_id):
    require_roles(ANY)
    freezer = get_freezer_or_404(freezer_id)
    items = [r for r in db["readings"].values() if r["freezer_id"] == freezer["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.reading_json(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Manual excursion reports
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/freezers/<freezer_id>/excursions", methods=["POST"])
def report_excursion(freezer_id):
    caller = require_roles({"TissueBankCoordinator"})
    freezer = get_freezer_or_404(freezer_id)
    body = get_body()
    req_str(body, "reason")
    if freezer["status"] != "OPERATIONAL":
        raise_error(ERR_EXCURSION_INVALID_STATE, f"freezer {freezer['name']} is already EXCURSION_ACTIVE")
    excursion = domain.open_excursion(freezer, "MANUAL_REPORT", caller.user_id, 0.0)
    return success_object(domain.excursion_json(excursion), status=201)


@bp.route("/tissue-bank/freezers/<freezer_id>/excursions", methods=["GET"])
def list_freezer_excursions(freezer_id):
    require_roles(ANY)
    freezer = get_freezer_or_404(freezer_id)
    items = [e for e in db["excursions"].values() if e["freezer_id"] == freezer["id"]]
    items.sort(key=lambda e: (e["_created_dt"], e["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.excursion_json(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Freezer-scoped unit / shipment lists
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/freezers/<freezer_id>/units", methods=["GET"])
def list_freezer_units(freezer_id):
    require_roles(ANY)
    freezer = get_freezer_or_404(freezer_id)
    items = [u for u in db["units"].values() if u["freezer_id"] == freezer["id"]]
    items.sort(key=lambda u: (u["serial_number"], u["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.unit_json(u) for u in page], total, limit, offset)


@bp.route("/tissue-bank/freezers/<freezer_id>/shipments", methods=["GET"])
def list_freezer_shipments(freezer_id):
    require_roles(ANY)
    freezer = get_freezer_or_404(freezer_id)
    items = [sh for sh in db["shipments"].values() if sh["freezer_id"] == freezer["id"]]
    items.sort(key=lambda sh: (sh["_created_dt"], sh["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.shipment_json(sh) for sh in page], total, limit, offset)
