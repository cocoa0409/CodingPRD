"""Tissue units: listing, lifecycle actions, and per-unit subcollections (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_UNIT_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_UNIT_NOT_QUARANTINED,
    ERR_SHIPMENT_NOT_ACCEPTED,
    ERR_SUPPLIER_NOT_QUALIFIED,
    ERR_FREEZER_IN_EXCURSION,
    ERR_UNIT_UNDER_ACTIVE_RECALL,
    ERR_UNIT_NOT_HOLDABLE,
    ERR_UNIT_NOT_ISSUABLE_STATE,
    ERR_RESERVATION_NOT_ACTIVE,
    ERR_UNIT_EXPIRED,
    ERR_RESERVATION_UNIT_MISMATCH,
    ERR_UNIT_NOT_ISSUED,
    ERR_FREEZER_CAPACITY_EXCEEDED,
    ERR_UNIT_NOT_DISCARDABLE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import domain
from util import fmt_dt
from validate import get_body, req_str, opt_str, paginate

bp = Blueprint("units", __name__)

ANY = ALL_ROLES


def get_unit_or_404(unit_id: str) -> dict:
    unit = db["units"].get(unit_id)
    if unit is None:
        raise_error(ERR_UNIT_NOT_FOUND, f"tissue unit {unit_id} does not exist")
    return unit


# ---------------------------------------------------------------------------
# Listing / retrieval
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/tissue-units", methods=["GET"])
def list_units():
    require_roles(ANY)
    items = list(db["units"].values())
    for param in ("supplier_id", "freezer_id", "shipment_id", "status", "tissue_type", "lot_number", "implanted_case_id"):
        v = request.args.get(param)
        if v is not None:
            items = [u for u in items if u.get(param) == v]
    items.sort(key=lambda u: (u["serial_number"], u["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.unit_json(u) for u in page], total, limit, offset)


@bp.route("/tissue-bank/tissue-units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    require_roles(ANY)
    return success_object(domain.unit_json(get_unit_or_404(unit_id)))


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/tissue-units/<unit_id>/release", methods=["POST"])
def release_unit(unit_id):
    require_roles({"QualityManager"})
    unit = get_unit_or_404(unit_id)
    if unit["status"] != "QUARANTINED":
        raise_error(ERR_UNIT_NOT_QUARANTINED, f"unit status is {unit['status']}, not QUARANTINED")
    shipment = db["shipments"][unit["shipment_id"]]
    if shipment["status"] != "ACCEPTED":
        raise_error(ERR_SHIPMENT_NOT_ACCEPTED, f"shipment status is {shipment['status']}, not ACCEPTED")
    supplier = db["suppliers"][unit["supplier_id"]]
    if supplier["status"] != "QUALIFIED":
        raise_error(ERR_SUPPLIER_NOT_QUALIFIED, f"supplier status is {supplier['status']}, not QUALIFIED")
    freezer = db["freezers"][unit["freezer_id"]]
    if freezer["status"] != "OPERATIONAL":
        raise_error(ERR_FREEZER_IN_EXCURSION, f"freezer {freezer['name']} is EXCURSION_ACTIVE")
    if domain.unit_under_active_recall(unit):
        raise_error(ERR_UNIT_UNDER_ACTIVE_RECALL, "an ACTIVE recall matches this unit")
    unit["status"] = "AVAILABLE"
    unit["hold_reason"] = "NONE"
    domain.touch(unit)
    return success_object(domain.unit_json(unit))


@bp.route("/tissue-bank/tissue-units/<unit_id>/hold", methods=["POST"])
def hold_unit(unit_id):
    require_roles({"QualityManager"})
    unit = get_unit_or_404(unit_id)
    if unit["status"] != "AVAILABLE":
        raise_error(ERR_UNIT_NOT_HOLDABLE, f"unit status is {unit['status']}, not AVAILABLE")
    unit["status"] = "QUARANTINED"
    unit["hold_reason"] = "MANUAL"
    domain.touch(unit)
    return success_object(domain.unit_json(unit))


@bp.route("/tissue-bank/tissue-units/<unit_id>/issue", methods=["POST"])
def issue_unit(unit_id):
    require_roles({"TissueBankCoordinator"})
    unit = get_unit_or_404(unit_id)
    body = get_body()
    reservation_id = opt_str(body, "reservation_id")
    reservation = None
    if reservation_id is not None:
        reservation = db["reservations"].get(reservation_id)
        if reservation is None:
            raise_error(ERR_RESERVATION_NOT_FOUND, f"reservation {reservation_id} does not exist")
    # state rung
    if reservation_id is not None:
        if unit["status"] != "RESERVED":
            raise_error(ERR_UNIT_NOT_ISSUABLE_STATE, f"unit status is {unit['status']}, not RESERVED")
        if reservation["status"] != "ACTIVE":
            raise_error(ERR_RESERVATION_NOT_ACTIVE, f"reservation status is {reservation['status']}, not ACTIVE")
    else:
        if unit["status"] != "AVAILABLE":
            raise_error(ERR_UNIT_NOT_ISSUABLE_STATE, f"unit status is {unit['status']}, not AVAILABLE")
    # compliance rung
    if domain.CLOCK.now() > unit["_expiration_dt"]:
        raise_error(ERR_UNIT_EXPIRED, "the logical clock is past this unit's expiration_at")
    freezer = db["freezers"][unit["freezer_id"]]
    if freezer["status"] != "OPERATIONAL":
        raise_error(ERR_FREEZER_IN_EXCURSION, f"freezer {freezer['name']} is EXCURSION_ACTIVE")
    if domain.unit_under_active_recall(unit):
        raise_error(ERR_UNIT_UNDER_ACTIVE_RECALL, "an ACTIVE recall matches this unit")
    supplier = db["suppliers"][unit["supplier_id"]]
    if supplier["status"] != "QUALIFIED":
        raise_error(ERR_SUPPLIER_NOT_QUALIFIED, f"supplier status is {supplier['status']}, not QUALIFIED")
    # referential rung
    if reservation is not None and reservation["tissue_unit_id"] != unit["id"]:
        raise_error(ERR_RESERVATION_UNIT_MISMATCH, "reservation's tissue_unit_id does not match the issued unit")
    # effects
    unit["status"] = "ISSUED"
    unit["_issued_via_case_id"] = reservation["implant_case_id"] if reservation is not None else None
    domain.touch(unit)
    if reservation is not None:
        reservation["status"] = "FULFILLED"
        domain.touch(reservation)
    return success_object(domain.unit_json(unit))


@bp.route("/tissue-bank/tissue-units/<unit_id>/return-to-stock", methods=["POST"])
def return_to_stock(unit_id):
    require_roles({"TissueBankCoordinator"})
    unit = get_unit_or_404(unit_id)
    if unit["status"] != "ISSUED":
        raise_error(ERR_UNIT_NOT_ISSUED, f"unit status is {unit['status']}, not ISSUED")
    if domain.CLOCK.now() > unit["_expiration_dt"]:
        raise_error(ERR_UNIT_EXPIRED, "the logical clock is past this unit's expiration_at")
    if domain.unit_under_active_recall(unit):
        raise_error(ERR_UNIT_UNDER_ACTIVE_RECALL, "an ACTIVE recall matches this unit")
    freezer = db["freezers"][unit["freezer_id"]]
    if not domain.freezer_admits(freezer, 1):
        raise_error(ERR_FREEZER_CAPACITY_EXCEEDED, f"freezer {freezer['name']} has no free effective slot")
    unit["status"] = "AVAILABLE"
    unit["recall_flag"] = False
    unit["_issued_via_case_id"] = None
    domain.touch(unit)
    return success_object(domain.unit_json(unit))


@bp.route("/tissue-bank/tissue-units/<unit_id>/discard", methods=["POST"])
def discard_unit(unit_id):
    caller = require_roles({"QualityManager"})
    unit = get_unit_or_404(unit_id)
    body = get_body()
    reason = req_str(body, "reason")
    if unit["status"] not in ("QUARANTINED", "EXPIRED"):
        raise_error(ERR_UNIT_NOT_DISCARDABLE, f"unit status is {unit['status']}, not QUARANTINED or EXPIRED")
    unit["status"] = "DISCARDED"
    unit["hold_reason"] = "NONE"
    unit["recall_flag"] = False
    domain.touch(unit)
    domain.create_disposition(unit, "DESTROYED", reason, caller.user_id)
    return success_object(domain.unit_json(unit))


@bp.route("/tissue-bank/tissue-units/<unit_id>/return-to-supplier", methods=["POST"])
def return_to_supplier(unit_id):
    caller = require_roles({"QualityManager"})
    unit = get_unit_or_404(unit_id)
    body = get_body()
    reason = req_str(body, "reason")
    if unit["status"] != "QUARANTINED":
        raise_error(ERR_UNIT_NOT_QUARANTINED, f"unit status is {unit['status']}, not QUARANTINED")
    unit["status"] = "RETURNED_TO_SUPPLIER"
    unit["hold_reason"] = "NONE"
    domain.touch(unit)
    domain.create_disposition(unit, "RETURNED_TO_SUPPLIER", reason, caller.user_id)
    return success_object(domain.unit_json(unit))


# ---------------------------------------------------------------------------
# Per-unit subcollections
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/tissue-units/<unit_id>/reservations", methods=["GET"])
def list_unit_reservations(unit_id):
    require_roles(ANY)
    unit = get_unit_or_404(unit_id)
    items = [r for r in db["reservations"].values() if r["tissue_unit_id"] == unit["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.reservation_json(r) for r in page], total, limit, offset)


@bp.route("/tissue-bank/tissue-units/<unit_id>/disposition-records", methods=["GET"])
def list_unit_dispositions(unit_id):
    require_roles(ANY)
    unit = get_unit_or_404(unit_id)
    items = [d for d in db["dispositions"].values() if d["tissue_unit_id"] == unit["id"]]
    items.sort(key=lambda d: (d["_created_dt"], d["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.disposition_json(d) for d in page], total, limit, offset)


@bp.route("/tissue-bank/tissue-units/<unit_id>/adverse-reactions", methods=["GET"])
def list_unit_adverse(unit_id):
    require_roles(ANY)
    unit = get_unit_or_404(unit_id)
    items = [a for a in db["adverse_reactions"].values() if a["tissue_unit_id"] == unit["id"]]
    items.sort(key=lambda a: (a["_created_dt"], a["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.adverse_json(a) for a in page], total, limit, offset)
