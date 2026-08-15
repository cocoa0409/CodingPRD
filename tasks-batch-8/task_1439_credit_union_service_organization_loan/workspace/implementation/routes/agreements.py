"""Servicing agreements (PRD 3.3)."""
from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_CUSO_SUSPENDED, ERR_AGR_HAS_OPEN_CERTS, ERR_INVALID_REQUEST,
)
from middleware import (
    auth_context, require_role, body, req_int, opt_int, req_enum, touch,
    paginate, ALL_ROLES,
)
from response import success
from serialize import OPEN_CERT_STATUSES
from services.cascade import certificates_of_agreement

bp = Blueprint("agreements", __name__)

DAY_COUNTS = {"THIRTY_360", "ACT_360"}


def _get_agreement(aid):
    a = db.agreements.get(aid)
    if a is None:
        not_found("ServicingAgreement")
    return a


@bp.post("/network/servicing-agreements")
def create_agreement():
    uid, role = auth_context()
    require_role(role, {"CUSOOfficer"})
    b = body()
    # ownership (priority 3): cuso_id must equal caller X-User-ID
    cuso_id = b.get("cuso_id")
    if cuso_id is not None and cuso_id != uid:
        raise_err(ERR_NOT_OWNER, "cuso_id must equal the caller's X-User-ID")
    # existence (priority 4)
    if cuso_id is not None and cuso_id not in db.cusos:
        not_found("CUSO")
    originator_id = b.get("originator_id")
    if originator_id is not None and originator_id not in db.credit_unions:
        not_found("CreditUnion")
    # shape (priority 5)
    if cuso_id is None:
        raise_err_missing("cuso_id")
    if originator_id is None:
        raise_err_missing("originator_id")
    fee_bps = req_int(b, "servicing_fee_bps", minimum=0)
    due_day = req_int(b, "remittance_due_day", minimum=1)
    if due_day > 28:
        raise_err(ERR_INVALID_REQUEST, "remittance_due_day must be in 1..28")
    grace = opt_int(b, "grace_period_days", 0, minimum=0)
    cure = opt_int(b, "cure_period_days", 30, minimum=0)
    day_count = req_enum(b, "day_count_convention", DAY_COUNTS)
    threshold = opt_int(b, "late_remittance_threshold", 2, minimum=1)
    originator = db.credit_unions[originator_id]
    if originator["cu_type"] not in ("ORIGINATOR", "DUAL"):
        raise_err(
            ERR_INVALID_REQUEST,
            "originator_id must reference a credit union of type ORIGINATOR or DUAL",
        )
    # linked-entity state (priority 9): CUSO must be ACTIVE
    cuso = db.cusos[cuso_id]
    if cuso["status"] != "ACTIVE":
        raise_err(ERR_CUSO_SUSPENDED, "CUSO must be ACTIVE to create a servicing agreement")
    a = db.insert("agreement", {
        "cuso_id": cuso_id,
        "originator_id": originator_id,
        "servicing_fee_bps": fee_bps,
        "remittance_due_day": due_day,
        "grace_period_days": grace,
        "cure_period_days": cure,
        "day_count_convention": day_count,
        "late_remittance_threshold": threshold,
        "late_remittance_count": 0,
        "status": "DRAFT",
    })
    return success(ser.agreement(a), 201)


def raise_err_missing(field):
    raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)


@bp.get("/network/servicing-agreements/<aid>")
def get_agreement(aid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.agreement(_get_agreement(aid)))


@bp.get("/network/servicing-agreements")
def list_agreements():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.agreements.values())
    co = request.args.get("cuso_id")
    if co is not None:
        items = [a for a in items if a["cuso_id"] == co]
    og = request.args.get("originator_id")
    if og is not None:
        items = [a for a in items if a["originator_id"] == og]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    page, meta = paginate(items, ser.agreement)
    return success(page, 200, meta)


@bp.post("/network/servicing-agreements/<aid>/activate")
def activate_agreement(aid):
    uid, role = auth_context()
    require_role(role, {"CUSOOfficer"})
    a = _get_agreement(aid)
    if a["cuso_id"] != uid:
        raise_err(ERR_NOT_OWNER, "CUSOOfficer must own the servicing agreement")
    if a["status"] != "DRAFT":
        invalid_state("Only a DRAFT agreement can be activated")
    cuso = db.cusos.get(a["cuso_id"])
    if cuso is None or cuso["status"] != "ACTIVE":
        raise_err(ERR_CUSO_SUSPENDED, "CUSO must be ACTIVE to activate the agreement")
    a["status"] = "ACTIVE"
    touch("agreement", a)
    return success(ser.agreement(a))


@bp.post("/network/servicing-agreements/<aid>/terminate")
def terminate_agreement(aid):
    uid, role = auth_context()
    require_role(role, {"CUSOOfficer"})
    a = _get_agreement(aid)
    if a["cuso_id"] != uid:
        raise_err(ERR_NOT_OWNER, "CUSOOfficer must own the servicing agreement")
    if a["status"] not in ("DRAFT", "ACTIVE", "DELINQUENT"):
        invalid_state("Agreement cannot be terminated from its current state")
    if a["status"] in ("ACTIVE", "DELINQUENT"):
        open_certs = [
            c for c in certificates_of_agreement(a["id"]) if c["status"] in OPEN_CERT_STATUSES
        ]
        if open_certs:
            raise_err(
                ERR_AGR_HAS_OPEN_CERTS,
                "Agreement has certificates in an open status and cannot be terminated",
            )
    a["status"] = "TERMINATED"
    touch("agreement", a)
    return success(ser.agreement(a))
