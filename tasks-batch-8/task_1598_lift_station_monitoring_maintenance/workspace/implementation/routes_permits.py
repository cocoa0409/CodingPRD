"""ConfinedSpacePermit routes: create/list/get and the permit lifecycle with
segregation-of-duties, certification, and gas-test gates (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_INSUFFICIENT_CERTIFICATION,
    ERR_GAS_TEST_REQUIRED,
    ERR_PERMIT_EXPIRED,
)
from helpers import body, bad, req_str, opt_bool, paginate
from middleware import require_roles
from routes_stations import get_station_or_404
from serializers import ser_permit

bp = Blueprint("confined_space_permits", __name__)

PERMIT_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "Operator", "MaintenancePlanner",
)

CSE_CERTS = ("CSE_1", "CSE_2")
PERMIT_VALID_HOURS = 12


def get_permit_or_404(pid):
    p = db.confined_space_permits.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Confined-space permit not found")
    return p


def _check_sod(entrant, attendant, supervisor):
    if entrant == attendant or supervisor == entrant or supervisor == attendant:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION, 422,
            "Entrant, attendant, and entry supervisor must be three distinct "
            "operators",
        )


def _check_certs(entrant_id, attendant_id):
    entrant = db.operators[entrant_id]
    attendant = db.operators[attendant_id]
    if not any(c in entrant["certifications"] for c in CSE_CERTS):
        raise ApiError(
            ERR_INSUFFICIENT_CERTIFICATION, 422,
            "Authorized entrant must hold CSE_1 or CSE_2",
        )
    if not any(c in attendant["certifications"] for c in CSE_CERTS):
        raise ApiError(
            ERR_INSUFFICIENT_CERTIFICATION, 422,
            "Attendant must hold CSE_1 or CSE_2",
        )


@bp.post("/stations/<sid>/confined-space-permits")
def create_permit(sid):
    require_roles("Operator", "OperationsSupervisor")
    st = get_station_or_404(sid)
    b = body()
    # body FK existence (priority 5)
    for field in ("authorized_entrant_id", "attendant_operator_id", "entry_supervisor_id"):
        v = b.get(field)
        if v is None:
            bad("%s is required" % field)
        if not isinstance(v, str):
            bad("%s must be a string" % field)
        if v not in db.operators:
            raise ApiError(
                ERR_REFERENCE_NOT_FOUND, 422,
                "%s does not resolve to an existing operator" % field,
            )
    entrant = b["authorized_entrant_id"]
    attendant = b["attendant_operator_id"]
    supervisor = b["entry_supervisor_id"]
    # posture gate (priority 7)
    services.check_posture(st)
    # business safety: segregation of duties (9), certification (10)
    _check_sod(entrant, attendant, supervisor)
    _check_certs(entrant, attendant)
    # shape (priority 30)
    description = req_str(b, "work_description")
    gas = opt_bool(b, "gas_test_passed", False)
    p = {
        "id": db.new_id(),
        "station_id": sid,
        "work_description": description,
        "authorized_entrant_id": entrant,
        "attendant_operator_id": attendant,
        "entry_supervisor_id": supervisor,
        "status": "DRAFT",
        "issued_at": None,
        "valid_until": None,
        "closed_at": None,
        "gas_test_passed": gas,
    }
    db.stamp(p)
    db.confined_space_permits[p["id"]] = p
    return success(ser_permit(p), 201)


@bp.get("/stations/<sid>/confined-space-permits")
def list_station_permits(sid):
    require_roles(*PERMIT_READ_ROLES)
    get_station_or_404(sid)
    items = [
        p for p in db.confined_space_permits.values() if p["station_id"] == sid
    ]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success([ser_permit(p) for p in page], 200, meta)


@bp.get("/confined-space-permits")
def list_permits():
    require_roles(*PERMIT_READ_ROLES)
    items = list(db.confined_space_permits.values())
    for field in ("station_id", "status", "authorized_entrant_id",
                  "attendant_operator_id", "entry_supervisor_id"):
        v = request.args.get(field)
        if v is not None:
            items = [p for p in items if p[field] == v]
    page, meta = paginate(items)
    return success([ser_permit(p) for p in page], 200, meta)


@bp.get("/confined-space-permits/<pid>")
def get_permit(pid):
    require_roles(*PERMIT_READ_ROLES)
    return success(ser_permit(get_permit_or_404(pid)))


# --------------------------------------------------------------------- lifecycle


@bp.post("/confined-space-permits/<pid>/issue")
def issue_permit(pid):
    require_roles("Operator")
    p = get_permit_or_404(pid)
    st = db.stations[p["station_id"]]
    if p["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT permit can be issued")
    # posture: issuance requires neither FROZEN nor EMERGENCY (PRD 3.9)
    services.check_posture(st)
    # only the named entry supervisor may issue
    if g.user_id != p["entry_supervisor_id"]:
        raise ApiError(
            ERR_UNAUTHORIZED, 403,
            "Only the permit's entry supervisor may issue it",
        )
    _check_sod(
        p["authorized_entrant_id"], p["attendant_operator_id"],
        p["entry_supervisor_id"],
    )
    _check_certs(p["authorized_entrant_id"], p["attendant_operator_id"])
    if not p["gas_test_passed"]:
        raise ApiError(
            ERR_GAS_TEST_REQUIRED, 422,
            "Pre-entry atmospheric testing must pass before issuance",
        )
    p["issued_at"] = db.now()
    p["valid_until"] = p["issued_at"] + timedelta(hours=PERMIT_VALID_HOURS)
    p["status"] = "ISSUED"
    db.touch(p)
    return success(ser_permit(p))


@bp.post("/confined-space-permits/<pid>/activate")
def activate_permit(pid):
    require_roles("Operator")
    p = get_permit_or_404(pid)
    st = db.stations[p["station_id"]]
    if p["status"] not in ("ISSUED", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only an ISSUED or SUSPENDED permit can be activated",
        )
    services.check_posture(st)
    # referential (priority 24): activation only within the validity window
    if not (db.now() < p["valid_until"]):
        raise ApiError(ERR_PERMIT_EXPIRED, 422, "Permit validity has expired")
    p["status"] = "ACTIVE"
    db.touch(p)
    return success(ser_permit(p))


@bp.post("/confined-space-permits/<pid>/suspend")
def suspend_permit(pid):
    require_roles("Operator")
    p = get_permit_or_404(pid)
    st = db.stations[p["station_id"]]
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE permit can be suspended")
    services.check_posture(st)
    p["status"] = "SUSPENDED"
    db.touch(p)
    return success(ser_permit(p))


@bp.post("/confined-space-permits/<pid>/close")
def close_permit(pid):
    require_roles("Operator")
    p = get_permit_or_404(pid)
    st = db.stations[p["station_id"]]
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE permit can be closed")
    services.check_posture(st)
    if g.user_id != p["entry_supervisor_id"]:
        raise ApiError(
            ERR_UNAUTHORIZED, 403,
            "Only the permit's entry supervisor may close it",
        )
    p["closed_at"] = db.now()
    p["status"] = "CLOSED"
    db.touch(p)
    return success(ser_permit(p))


@bp.post("/confined-space-permits/<pid>/cancel")
def cancel_permit(pid):
    require_roles("OperationsSupervisor")
    p = get_permit_or_404(pid)
    st = db.stations[p["station_id"]]
    if p["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a DRAFT or ISSUED permit can be cancelled",
        )
    services.check_posture(st)
    p["status"] = "CANCELLED"
    db.touch(p)
    return success(ser_permit(p))
