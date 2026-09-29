"""Travel authorization decision endpoints.

Creation lives on the parent contract (routes/contracts.py) because it is
guarded by optimistic concurrency on the contract row; this module only holds
the reads and the two terminal decisions.
"""
from flask import Blueprint

from core import (
    TRAVEL_READERS,
    ROLE_MANAGER,
    ApiError,
    actor,
    authenticate,
    db,
    enum_filter,
    paginate,
    pagination,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import get_travel_authorization
from serial import travel_authorization_out
from validate import Field, validate

bp = Blueprint("travel_authorizations", __name__)

AUTH_STATUSES = ("REQUESTED", "APPROVED", "DENIED")

DENY_FIELDS = [Field("denial_reason", "string", nullable=True, default=None)]


@bp.get("/travel-authorizations")
def list_authorizations():
    authenticate(TRAVEL_READERS)
    contract_id = str_filter("contract_id")
    branch_id = str_filter("receiving_branch_id")
    status = enum_filter("status", AUTH_STATUSES)
    limit, offset = pagination()
    rows = sorted_rows(db.travel_authorizations.values())
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if branch_id is not None:
        rows = [r for r in rows if r["receiving_branch_id"] == branch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, travel_authorization_out)


@bp.get("/travel-authorizations/<travel_authorization_id>")
def read_authorization(travel_authorization_id):
    authenticate(TRAVEL_READERS)
    return respond(
        travel_authorization_out(get_travel_authorization(travel_authorization_id))
    )


@bp.post("/travel-authorizations/<travel_authorization_id>/approve")
def approve_authorization(travel_authorization_id):
    """Approval re-checks the contract and the patient's risk posture."""
    authenticate((ROLE_MANAGER,))
    auth = get_travel_authorization(travel_authorization_id)
    if auth["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    contract = db.contracts.get(auth["contract_id"])
    if contract is None:
        raise ApiError("ERR_INVALID_STATE")
    if contract["billing_status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    if contract["service_status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE")
    patient = db.patients.get(contract["patient_id"])
    if patient is not None and patient["compliance_hold"]:
        raise ApiError("ERR_PATIENT_ON_COMPLIANCE_HOLD")
    auth["decided_by_user_id"] = actor()
    auth["status"] = "APPROVED"
    touch(auth)
    return respond(travel_authorization_out(auth))


@bp.post("/travel-authorizations/<travel_authorization_id>/deny")
def deny_authorization(travel_authorization_id):
    authenticate((ROLE_MANAGER,))
    auth = get_travel_authorization(travel_authorization_id)
    validate(DENY_FIELDS)
    if auth["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    auth["decided_by_user_id"] = actor()
    auth["status"] = "DENIED"
    touch(auth)
    return respond(travel_authorization_out(auth))
