"""Agents and authorized delegates: appointment and oversight scoring (§3.6)."""

from flask import Blueprint

import calculations as calc
from db import base_row, db, now, serialize, set_dt, touch
from middleware import authorize, require_scope
from response import created, ok
from routes.common import filter_rows, get_delegate, get_licensee, paginate
from validators import get_body, pagination, q_enum, q_str, v_enum, v_int, v_str

bp = Blueprint("delegates", __name__)

DELEGATE_STATUSES = ("ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")


@bp.post("/delegates")
def create_delegate():
    authorize("LicensingManager")
    body = get_body()
    licensee_id = v_str(body, "licensee_id")
    legal_name = v_str(body, "legal_name")
    delegate_type = v_enum(body, "delegate_type", ("AGENT", "AUTHORIZED_DELEGATE"))

    get_licensee(licensee_id)

    row = base_row()
    row.update(
        {
            "licensee_id": licensee_id,
            "legal_name": legal_name,
            "delegate_type": delegate_type,
            "status": "ONBOARDING",
            "oversight_score": None,
            "last_oversight_review_at": None,
            "authorized_state_count": 0,
            "oversight_hold": False,
        }
    )
    db.delegates[row["id"]] = row
    return created(serialize(row))


@bp.get("/delegates/<delegate_id>")
def get_one(delegate_id):
    user_id, role = authorize(
        "LicensingManager", "ComplianceOfficer", "DelegateOperator", "StateRegulator"
    )
    row = get_delegate(delegate_id)
    if role == "DelegateOperator":
        require_scope(user_id == delegate_id, user_id, "delegate %s" % delegate_id)
    return ok(serialize(row))


@bp.get("/delegates")
def list_all():
    authorize("LicensingManager", "ComplianceOfficer", "StateRegulator")
    limit, offset = pagination()
    filters = {
        "licensee_id": q_str("licensee_id"),
        "status": q_enum("status", DELEGATE_STATUSES),
    }
    return paginate(filter_rows(db.delegates.values(), filters), limit, offset)


@bp.post("/delegates/<delegate_id>/oversight-reviews")
def oversight_review(delegate_id):
    user_id, role = authorize("ComplianceOfficer", "DelegateOperator")
    body = get_body()
    training = v_int(body, "training_score", minimum=0, maximum=100)
    aml = v_int(body, "aml_test_score", minimum=0, maximum=100)
    recordkeeping = v_int(body, "recordkeeping_score", minimum=0, maximum=100)

    row = get_delegate(delegate_id)
    if role == "DelegateOperator":
        require_scope(user_id == delegate_id, user_id, "delegate %s" % delegate_id)

    row["oversight_score"] = calc.delegate_oversight_score(training, aml, recordkeeping)
    set_dt(row, "last_oversight_review_at", now())
    touch(row)
    return ok(serialize(row))
