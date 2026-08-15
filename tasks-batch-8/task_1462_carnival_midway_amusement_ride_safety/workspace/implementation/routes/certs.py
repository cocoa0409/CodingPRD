"""Operator certifications: issue, read, list, revoke."""
from flask import Blueprint

import db
from db import serialize, touch
from errors import raise_err, ERR_INVALID_REQUEST, ERR_CERT_INVALID_STATE
from helpers import get_or_404, paginate, qparam, fair_id_of_cert
from middleware import authenticate, scope_to_fair
from response import ok
from validators import get_body, reject_unknown, req_str, req_enum, req_date

bp = Blueprint("certs", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

RIDE_CLASSES = ["KIDDIE", "FAMILY", "THRILL", "EXTREME"]


@bp.post("/operator-certifications")
def create_cert():
    authenticate(["StateProgramAdmin"])
    body = get_body()
    reject_unknown(body, {"staff_id", "ride_class", "issued_on", "expires_on"})
    staff_id = req_str(body, "staff_id")
    ride_class = req_enum(body, "ride_class", RIDE_CLASSES)
    issued = req_date(body, "issued_on")
    expires = req_date(body, "expires_on")
    if not (expires > issued):
        raise_err(ERR_INVALID_REQUEST, "expires_on must be strictly after issued_on")
    staff = get_or_404("staff", staff_id)
    if "OPERATOR" not in staff.get("functions", []):
        raise_err(ERR_INVALID_REQUEST, "The staff member must carry the OPERATOR function")
    cert = db.register(
        "certifications",
        {
            "staff_id": staff_id,
            "ride_class": ride_class,
            "issued_on": body["issued_on"],
            "expires_on": body["expires_on"],
            "status": "ACTIVE",
        },
    )
    return ok(serialize(cert), 201)


@bp.get("/operator-certifications/<cid>")
def get_cert(cid):
    ctx = authenticate(ALL)
    cert = get_or_404("certifications", cid)
    scope_to_fair(ctx, fair_id_of_cert(cert))
    return ok(serialize(cert))


@bp.get("/operator-certifications")
def list_certs():
    authenticate(ALL)
    return paginate(
        "certifications",
        {
            "staff_id": qparam("staff_id"),
            "ride_class": qparam("ride_class"),
            "status": qparam("status"),
        },
    )


@bp.post("/operator-certifications/<cid>/revoke")
def revoke_cert(cid):
    authenticate(["StateProgramAdmin", "StateInspector"])
    cert = get_or_404("certifications", cid)
    body = get_body()
    reject_unknown(body, set())
    if cert["status"] != "ACTIVE":
        raise_err(ERR_CERT_INVALID_STATE, "Certification is already REVOKED")
    cert["status"] = "REVOKED"
    touch(cert)
    return ok(serialize(cert))
