"""Enterprise endpoints."""

from decimal import Decimal

from flask import Blueprint, g

import db
import errors
import helpers
import response
from middleware import auth_required, get_actor
from serializers import enterprise_dict


bp = Blueprint("enterprises", __name__)


VALID_JURISDICTIONS = {"JD_ALPHA", "JD_BETA", "JD_GAMMA"}
VALID_INDUSTRIES = {"POWER", "STEEL", "CEMENT", "CHEMICAL", "PETROCHEMICAL"}
VALID_ACCOUNT_STATUSES = {"PENDING", "OPEN", "RESTRICTED", "CLOSED"}


@bp.route("/enterprises", methods=["POST"])
@auth_required("Regulator")
def create_enterprise():
    body = helpers.get_json_body()
    helpers.require_fields(body, ["legal_name", "jurisdiction_code",
                                  "industry_code", "contact_email"])
    if body["jurisdiction_code"] not in VALID_JURISDICTIONS:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid jurisdiction_code.")
    if body["industry_code"] not in VALID_INDUSTRIES:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid industry_code.")

    common = helpers.common_create()
    e = {
        "id": db.new_id(),
        "legal_name": body["legal_name"],
        "jurisdiction_code": body["jurisdiction_code"],
        "industry_code": body["industry_code"],
        "account_status": "PENDING",
        "quota_balance": Decimal("0"),
        "paid_quota_balance": Decimal("0"),
        "ccer_balance": Decimal("0"),
        "contact_email": body["contact_email"],
        **common,
    }
    db.enterprises[e["id"]] = e
    return response.created(enterprise_dict(e))


@bp.route("/enterprises/<eid>", methods=["GET"])
@auth_required("Regulator", "Enterprise")
def read_enterprise(eid):
    e = db.enterprises.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Enterprise {eid} not found.")
    user_id, user_role = get_actor()
    if user_role == "Enterprise" and user_id != eid:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION, "Enterprise can only read own record.")
    return response.ok(enterprise_dict(e))


@bp.route("/enterprises", methods=["GET"])
@auth_required("Regulator")
def list_enterprises():
    limit, offset = helpers.parse_pagination()
    items = list(db.enterprises.values())
    # Filters
    args = {
        "jurisdiction_code": None,
        "industry_code": None,
        "account_status": None,
    }
    from flask import request
    for k in args:
        v = request.args.get(k)
        if v is not None:
            items = [e for e in items if e[k] == v]
    items.sort(key=lambda x: x["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([enterprise_dict(e) for e in page],
                            limit=limit, offset=offset, total_count=total)
