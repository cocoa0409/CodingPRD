"""Appointment and Bond routes."""

from flask import Blueprint, request

from clock import clock
from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_int,
    optional_bool,
    parse_pagination,
    paginate,
)
from services import (
    resolve_path,
    resolve_ref,
    accounts_for_case,
    touch_account,
    touch_case,
    advance_due_iso,
)
from calculations import bond_amount_required

bp = Blueprint("appointments", __name__)


def _granted_petition_for_case(case_id):
    for pet in db.petitions.values():
        if pet["case_id"] == case_id and pet["status"] == "GRANTED":
            return pet
    return None


def _bond_for_appointment(appointment_id):
    for bond in db.bonds.values():
        if bond["appointment_id"] == appointment_id:
            return bond
    return None


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------
@bp.route("/gc/appointments", methods=["POST"])
def create_appointment():
    _, role = get_identity()
    require_role(role, ["Judge"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    fiduciary_id = require_string(body, "fiduciary_id")
    case = resolve_ref(db.cases, case_id)
    fiduciary = resolve_ref(db.fiduciaries, fiduciary_id)

    # Fiduciary must not be disqualified (priority 14).
    if fiduciary["is_disqualified"]:
        raise err("ERR_FIDUCIARY_DISQUALIFIED", "Fiduciary is disqualified")

    # granted_authority copied from the granted petition's requested_authority.
    petition = _granted_petition_for_case(case_id)
    granted_authority = petition["requested_authority"] if petition else None

    record = {
        "case_id": case_id,
        "fiduciary_id": fiduciary_id,
        "granted_authority": granted_authority,
        "letters_issued_iso": None,
        "status": "PENDING_QUALIFICATION",
    }
    stamp_create(record)
    with db.lock:
        db.appointments[record["id"]] = record
        # If the case requires a bond, auto-create one in REQUIRED.
        if case["requires_bond"]:
            person = db.protected_persons.get(case["protected_person_id"])
            required = bond_amount_required(
                person["liquid_estate_cents"],
                person["annual_income_cents"],
                case["case_type"],
            )
            bond = {
                "appointment_id": record["id"],
                "required_amount_cents": required,
                "posted_amount_cents": 0,
                "surety_name": None,
                "status": "REQUIRED",
            }
            stamp_create(bond)
            db.bonds[bond["id"]] = bond
    return object_response(record, 201)


@bp.route("/gc/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.appointments, aid), 200)


@bp.route("/gc/appointments", methods=["GET"])
def list_appointments():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.appointments.values())
    case_id = request.args.get("case_id")
    fiduciary_id = request.args.get("fiduciary_id")
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    if fiduciary_id is not None:
        items = [a for a in items if a["fiduciary_id"] == fiduciary_id]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/appointments/<aid>/qualify", methods=["POST"])
def qualify_appointment(aid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    appt = resolve_path(db.appointments, aid)
    case = db.cases.get(appt["case_id"])
    if appt["status"] != "PENDING_QUALIFICATION":
        raise err("ERR_INVALID_STATE", "Appointment must be PENDING_QUALIFICATION")
    if case is None or case["status"] != "AWAITING_APPOINTMENT":
        raise err("ERR_INVALID_STATE", "Case must be AWAITING_APPOINTMENT")
    fiduciary = db.fiduciaries.get(appt["fiduciary_id"])
    if fiduciary is None or fiduciary["is_disqualified"]:
        raise err("ERR_FIDUCIARY_DISQUALIFIED", "Fiduciary is disqualified")
    if case["requires_bond"]:
        bond = _bond_for_appointment(aid)
        if bond is None or bond["status"] != "APPROVED":
            raise err("ERR_BOND_NOT_APPROVED", "Bond must be APPROVED before qualification")

    now_iso = clock.now_iso()
    appt["letters_issued_iso"] = now_iso
    appt["status"] = "ACTIVE"
    stamp_update(appt)
    fiduciary["open_appointment_count"] += 1
    stamp_update(fiduciary)
    case["status"] = "ACTIVE"
    case["next_accounting_due_iso"] = advance_due_iso(now_iso)
    touch_case(case)
    return object_response(appt, 200)


@bp.route("/gc/appointments/<aid>/suspend", methods=["POST"])
def suspend_appointment(aid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    appt = resolve_path(db.appointments, aid)
    if appt["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Appointment must be ACTIVE")
    appt["status"] = "SUSPENDED"
    stamp_update(appt)
    for acc in accounts_for_case(appt["case_id"]):
        if acc["status"] == "OPEN":
            acc["status"] = "FROZEN"
            touch_account(acc)
    case = db.cases.get(appt["case_id"])
    if case is not None:
        touch_case(case)
    return object_response(appt, 200)


@bp.route("/gc/appointments/<aid>/reinstate", methods=["POST"])
def reinstate_appointment(aid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    appt = resolve_path(db.appointments, aid)
    if appt["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Appointment must be SUSPENDED")
    appt["status"] = "ACTIVE"
    stamp_update(appt)
    for acc in accounts_for_case(appt["case_id"]):
        if acc["status"] == "FROZEN":
            acc["status"] = "OPEN"
            touch_account(acc)
    case = db.cases.get(appt["case_id"])
    if case is not None:
        touch_case(case)
    return object_response(appt, 200)


@bp.route("/gc/appointments/<aid>/remove", methods=["POST"])
def remove_appointment(aid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    body = get_json_body()
    for_cause = optional_bool(body, "for_cause", default=False)
    appt = resolve_path(db.appointments, aid)
    if appt["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Appointment must be ACTIVE or SUSPENDED")

    appt["status"] = "REVOKED"
    stamp_update(appt)
    fiduciary = db.fiduciaries.get(appt["fiduciary_id"])
    if fiduciary is not None:
        if for_cause:
            fiduciary["is_disqualified"] = True
        # ACTIVE and SUSPENDED both count as open; decrement either way.
        fiduciary["open_appointment_count"] = max(0, fiduciary["open_appointment_count"] - 1)
        stamp_update(fiduciary)
    bond = _bond_for_appointment(aid)
    if bond is not None and bond["status"] == "APPROVED":
        bond["status"] = "EXONERATED"
        stamp_update(bond)
    case = db.cases.get(appt["case_id"])
    if case is not None:
        touch_case(case)
    return object_response(appt, 200)


# ---------------------------------------------------------------------------
# Bond
# ---------------------------------------------------------------------------
@bp.route("/gc/bonds/<bid>", methods=["GET"])
def get_bond(bid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.bonds, bid), 200)


@bp.route("/gc/bonds", methods=["GET"])
def list_bonds():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.bonds.values())
    appointment_id = request.args.get("appointment_id")
    if appointment_id is not None:
        items = [b for b in items if b["appointment_id"] == appointment_id]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/bonds/<bid>/post", methods=["POST"])
def post_bond(bid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    posted_amount = require_int(body, "posted_amount_cents", minimum=0)
    surety_name = require_string(body, "surety_name")
    bond = resolve_path(db.bonds, bid)
    if bond["status"] != "REQUIRED":
        raise err("ERR_INVALID_STATE", "Bond must be REQUIRED")
    if posted_amount < bond["required_amount_cents"]:
        raise err("ERR_BOND_INSUFFICIENT", "Posted amount below required amount")
    bond["posted_amount_cents"] = posted_amount
    bond["surety_name"] = surety_name
    bond["status"] = "POSTED"
    stamp_update(bond)
    return object_response(bond, 200)


@bp.route("/gc/bonds/<bid>/approve", methods=["POST"])
def approve_bond(bid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    bond = resolve_path(db.bonds, bid)
    if bond["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Bond must be POSTED")
    bond["status"] = "APPROVED"
    stamp_update(bond)
    return object_response(bond, 200)


@bp.route("/gc/bonds/<bid>/reject", methods=["POST"])
def reject_bond(bid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    bond = resolve_path(db.bonds, bid)
    if bond["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Bond must be POSTED")
    bond["status"] = "REQUIRED"
    bond["posted_amount_cents"] = 0
    stamp_update(bond)
    return object_response(bond, 200)
