"""Implant cases, reservations against cases, and adverse-reaction reports (PRD §3.5, §3.7)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    ERR_INVALID_WINDOW,
    ERR_OR_ROOM_DOUBLE_BOOKED,
    ERR_CASE_OWNERSHIP_VIOLATION,
    ERR_CASE_INVALID_STATE,
    ERR_UNIT_NOT_RESERVABLE,
    ERR_UNIT_EXPIRES_BEFORE_CASE,
    ERR_IMPLANT_WINDOW_CLOSED,
    ERR_UNIT_NOT_ISSUED,
    ERR_UNIT_ISSUED_TO_ANOTHER_CASE,
    ERR_UNIT_NOT_IMPLANTED_ON_CASE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import domain
from util import fmt_dt
from validate import get_body, req_str, req_dt, req_enum, paginate

bp = Blueprint("cases", __name__)

ANY = ALL_ROLES


def get_case_or_404(case_id: str) -> dict:
    case = db["cases"].get(case_id)
    if case is None:
        raise_error(ERR_CASE_NOT_FOUND, f"implant case {case_id} does not exist")
    return case


def _check_ownership(case: dict, caller):
    if case["surgeon_id"] != caller.user_id:
        raise_error(ERR_CASE_OWNERSHIP_VIOLATION, "the case belongs to a different surgeon")


def _release_case_reservations(case: dict, reason: str):
    """Cancel/complete cascade: every ACTIVE reservation -> RELEASED; its
    RESERVED unit returns to AVAILABLE."""
    reservations = sorted(
        (r for r in db["reservations"].values()
         if r["implant_case_id"] == case["id"] and r["status"] == "ACTIVE"),
        key=lambda r: r["_seq"],
    )
    for r in reservations:
        r["status"] = "RELEASED"
        r["release_reason"] = reason
        domain.touch(r)
        unit = db["units"].get(r["tissue_unit_id"])
        if unit is not None and unit["status"] == "RESERVED":
            unit["status"] = "AVAILABLE"
            domain.touch(unit)


# ---------------------------------------------------------------------------
# Implant cases
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/implant-cases", methods=["POST"])
def create_case():
    caller = require_roles({"ImplantingSurgeon"})
    body = get_body()
    patient_ref = req_str(body, "patient_ref")
    or_room_id = req_str(body, "or_room_id")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise_error(ERR_INVALID_WINDOW, "scheduled_end must be strictly after scheduled_start")
    # half-open [start, end) overlap against SCHEDULED cases in the same room;
    # adjacent end == start is allowed
    for other in db["cases"].values():
        if (
            other["or_room_id"] == or_room_id
            and other["status"] == "SCHEDULED"
            and scheduled_start < other["_scheduled_end"]
            and other["_scheduled_start"] < scheduled_end
        ):
            raise_error(ERR_OR_ROOM_DOUBLE_BOOKED, f"or_room_id {or_room_id} already has a SCHEDULED case in that window")
    case = {
        "surgeon_id": caller.user_id,
        "patient_ref": patient_ref,
        "or_room_id": or_room_id,
        "scheduled_start": fmt_dt(scheduled_start),
        "scheduled_end": fmt_dt(scheduled_end),
        "status": "SCHEDULED",
        "implanted_unit_count": 0,
        "_scheduled_start": scheduled_start,
        "_scheduled_end": scheduled_end,
    }
    domain.stamp_new(case)
    db["cases"][case["id"]] = case
    return success_object(domain.case_json(case), status=201)


@bp.route("/tissue-bank/implant-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_roles(ANY)
    return success_object(domain.case_json(get_case_or_404(case_id)))


@bp.route("/tissue-bank/implant-cases/<case_id>/cancel", methods=["POST"])
def cancel_case(case_id):
    caller = require_roles({"ImplantingSurgeon"})
    case = get_case_or_404(case_id)
    _check_ownership(case, caller)
    if case["status"] != "SCHEDULED":
        raise_error(ERR_CASE_INVALID_STATE, f"case status is {case['status']}, not SCHEDULED")
    case["status"] = "CANCELLED"
    domain.touch(case)
    _release_case_reservations(case, "CASE_CANCELLED")
    return success_object(domain.case_json(case))


@bp.route("/tissue-bank/implant-cases/<case_id>/complete", methods=["POST"])
def complete_case(case_id):
    caller = require_roles({"ImplantingSurgeon"})
    case = get_case_or_404(case_id)
    _check_ownership(case, caller)
    if case["status"] != "SCHEDULED":
        raise_error(ERR_CASE_INVALID_STATE, f"case status is {case['status']}, not SCHEDULED")
    case["status"] = "COMPLETED"
    domain.touch(case)
    _release_case_reservations(case, "CASE_COMPLETED")
    return success_object(domain.case_json(case))


@bp.route("/tissue-bank/implant-cases/<case_id>/record-implantation", methods=["POST"])
def record_implantation(case_id):
    caller = require_roles({"ImplantingSurgeon"})
    case = get_case_or_404(case_id)
    body = get_body()
    tissue_unit_id = req_str(body, "tissue_unit_id")
    _check_ownership(case, caller)
    if case["status"] != "SCHEDULED":
        raise_error(ERR_CASE_INVALID_STATE, f"case status is {case['status']}, not SCHEDULED")
    unit = db["units"].get(tissue_unit_id)
    if unit is None:
        raise_error(ERR_UNIT_NOT_FOUND, f"tissue unit {tissue_unit_id} does not exist")
    # state rung before the temporal rung (PRD §2.8 ladder)
    if unit["status"] != "ISSUED":
        raise_error(ERR_UNIT_NOT_ISSUED, f"unit status is {unit['status']}, not ISSUED")
    now = domain.CLOCK.now()
    window_open = case["_scheduled_start"] - timedelta(hours=1)
    window_close = case["_scheduled_end"] + timedelta(hours=24)
    if not (window_open <= now <= window_close):
        raise_error(ERR_IMPLANT_WINDOW_CLOSED, "the logical clock is outside the implant window")
    # referential rung: a unit issued via reservation belongs to that reservation's case
    if unit["_issued_via_case_id"] is not None and unit["_issued_via_case_id"] != case["id"]:
        raise_error(ERR_UNIT_ISSUED_TO_ANOTHER_CASE, "unit was issued via a reservation on a different case")
    unit["status"] = "IMPLANTED"
    unit["implanted_case_id"] = case["id"]
    unit["implanted_at"] = fmt_dt(now)
    unit["recall_flag"] = False
    unit["_issued_via_case_id"] = None
    domain.touch(unit)
    case["implanted_unit_count"] += 1
    domain.touch(case)
    domain.create_disposition(unit, "IMPLANTED", f"Implanted in implant case {case['id']}", caller.user_id)
    return success_object(domain.unit_json(unit))


# ---------------------------------------------------------------------------
# Reservations against a case
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/implant-cases/<case_id>/reservations", methods=["POST"])
def create_reservation(case_id):
    require_roles({"TissueBankCoordinator"})
    case = get_case_or_404(case_id)
    body = get_body()
    tissue_unit_id = req_str(body, "tissue_unit_id")
    if case["status"] != "SCHEDULED":
        raise_error(ERR_CASE_INVALID_STATE, f"case status is {case['status']}, not SCHEDULED")
    unit = db["units"].get(tissue_unit_id)
    if unit is None:
        raise_error(ERR_UNIT_NOT_FOUND, f"tissue unit {tissue_unit_id} does not exist")
    if unit["status"] != "AVAILABLE":
        raise_error(ERR_UNIT_NOT_RESERVABLE, f"unit status is {unit['status']}, not AVAILABLE")
    # temporal rung: the unit must strictly outlive the surgery
    if unit["_expiration_dt"] <= case["_scheduled_end"]:
        raise_error(ERR_UNIT_EXPIRES_BEFORE_CASE, "unit expiration_at must fall strictly after scheduled_end")
    hold_until = case["_scheduled_end"] + timedelta(hours=2)
    reservation = {
        "implant_case_id": case["id"],
        "tissue_unit_id": unit["id"],
        "status": "ACTIVE",
        "hold_until": fmt_dt(hold_until),
        "release_reason": "NONE",
        "_hold_until": hold_until,
    }
    domain.stamp_new(reservation)
    db["reservations"][reservation["id"]] = reservation
    unit["status"] = "RESERVED"
    domain.touch(unit)
    return success_object(domain.reservation_json(reservation), status=201)


@bp.route("/tissue-bank/implant-cases/<case_id>/reservations", methods=["GET"])
def list_case_reservations(case_id):
    require_roles(ANY)
    case = get_case_or_404(case_id)
    items = [r for r in db["reservations"].values() if r["implant_case_id"] == case["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.reservation_json(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Adverse-reaction reports against a case
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/implant-cases/<case_id>/adverse-reactions", methods=["POST"])
def create_adverse_reaction(case_id):
    caller = require_roles({"ImplantingSurgeon"})
    case = get_case_or_404(case_id)
    body = get_body()
    tissue_unit_id = req_str(body, "tissue_unit_id")
    reaction_type = req_enum(body, "reaction_type", domain.REACTION_TYPES)
    severity = req_enum(body, "severity", domain.REACTION_SEVERITIES)
    description = req_str(body, "description", min_len=10)
    _check_ownership(case, caller)
    unit = db["units"].get(tissue_unit_id)
    if unit is None:
        raise_error(ERR_UNIT_NOT_FOUND, f"tissue unit {tissue_unit_id} does not exist")
    if unit["status"] != "IMPLANTED" or unit["implanted_case_id"] != case["id"]:
        raise_error(ERR_UNIT_NOT_IMPLANTED_ON_CASE, "unit is not IMPLANTED on this case")
    adverse = {
        "implant_case_id": case["id"],
        "tissue_unit_id": unit["id"],
        "reporter_user_id": caller.user_id,
        "reaction_type": reaction_type,
        "severity": severity,
        "description": description,
        "status": "REPORTED",
        "investigator_user_id": None,
        "reopened_count": 0,
    }
    domain.stamp_new(adverse)
    db["adverse_reactions"][adverse["id"]] = adverse
    # the provisional score immediately absorbs the open-case term; evaluate the gate
    supplier = db["suppliers"].get(unit["supplier_id"])
    if supplier is not None:
        domain.maybe_auto_suspend(supplier)
    return success_object(domain.adverse_json(adverse), status=201)


@bp.route("/tissue-bank/implant-cases/<case_id>/adverse-reactions", methods=["GET"])
def list_case_adverse(case_id):
    require_roles(ANY)
    case = get_case_or_404(case_id)
    items = [a for a in db["adverse_reactions"].values() if a["implant_case_id"] == case["id"]]
    items.sort(key=lambda a: (a["_created_dt"], a["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.adverse_json(a) for a in page], total, limit, offset)
