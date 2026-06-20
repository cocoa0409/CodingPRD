"""Employer endpoints (PRD §3.1, §3.2)."""

from flask import Blueprint

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.common import base_entity, parse_date, touch
from services.serialize import public

bp = Blueprint("employers", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}


@bp.route("/clinic/employers", methods=["POST"])
def create_employer():
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()

    with LOCK:
        legal_name = body.get("legal_name")
        if not isinstance(legal_name, str) or not legal_name.strip():
            raise err(errors.ERR_INVALID_REQUEST, "legal_name is required")

        mro_user_id = body.get("mro_user_id")
        if not isinstance(mro_user_id, str) or not mro_user_id.strip():
            raise err(errors.ERR_INVALID_REQUEST, "mro_user_id is required")

        dot_regulated = body.get("dot_regulated", False)
        if not isinstance(dot_regulated, bool):
            raise err(errors.ERR_INVALID_REQUEST, "dot_regulated must be a boolean")

        net_terms_days = body.get("net_terms_days", 30)
        if isinstance(net_terms_days, bool) or not isinstance(net_terms_days, int) or net_terms_days < 0:
            raise err(errors.ERR_INVALID_REQUEST, "net_terms_days must be a non-negative integer")

        current_date = body.get("current_date", "1970-01-01")
        if current_date is None:
            current_date = "1970-01-01"
        if parse_date(current_date) is None:
            raise err(errors.ERR_INVALID_REQUEST, "current_date must be a valid date")

        emp = base_entity()
        emp.update({
            "legal_name": legal_name,
            "account_status": "PROSPECT",
            "dot_regulated": dot_regulated,
            "mro_user_id": mro_user_id,
            "net_terms_days": net_terms_days,
            "current_date": current_date,
            "outstanding_balance_cents": 0,
        })
        db.employers[emp["id"]] = emp
        return object_response(public(emp), 201)


@bp.route("/clinic/employers", methods=["GET"])
def list_employers():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    items = sort_by_created(list(db.employers.values()))
    return paginated(items)


@bp.route("/clinic/employers/<employer_id>", methods=["GET"])
def get_employer(employer_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    emp = lookup.get_employer(employer_id)
    return object_response(public(emp), 200)


@bp.route("/clinic/employers/<employer_id>/suspend", methods=["POST"])
def suspend_employer(employer_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    with LOCK:
        emp = lookup.get_employer(employer_id)
        if emp["account_status"] != "ACTIVE":
            raise err(errors.ERR_EMPLOYER_NOT_ACTIVE, "Employer must be ACTIVE to suspend")
        emp["account_status"] = "SUSPENDED"
        touch(emp)
        return object_response(public(emp), 200)


@bp.route("/clinic/employers/<employer_id>/reactivate", methods=["POST"])
def reactivate_employer(employer_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    with LOCK:
        emp = lookup.get_employer(employer_id)
        if emp["account_status"] != "SUSPENDED":
            raise err(errors.ERR_EMPLOYER_NOT_SUSPENDED, "Employer must be SUSPENDED to reactivate")
        emp["account_status"] = "ACTIVE"
        touch(emp)
        return object_response(public(emp), 200)


@bp.route("/clinic/employers/<employer_id>/close", methods=["POST"])
def close_employer(employer_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    with LOCK:
        emp = lookup.get_employer(employer_id)
        if emp["account_status"] not in ("ACTIVE", "SUSPENDED"):
            raise err(errors.ERR_EMPLOYER_NOT_CLOSABLE,
                      "Employer must be ACTIVE or SUSPENDED to close")
        if emp.get("outstanding_balance_cents", 0) != 0:
            raise err(errors.ERR_EMPLOYER_HAS_BALANCE,
                      "Employer has a non-zero outstanding balance")
        for enc in db.encounters.values():
            if enc["employer_id"] == emp["id"] and enc["status"] in (
                "SCHEDULED", "IN_PROGRESS", "PENDING_RESULTS"
            ):
                raise err(errors.ERR_OPEN_ENCOUNTERS_EXIST,
                          "Open encounters exist for this employer")
        emp["account_status"] = "CLOSED"
        touch(emp)
        return object_response(public(emp), 200)
