"""LimitedPartner routes (PRD §3.2)."""
from flask import Blueprint

import db
from middleware import authenticate, require_role
from response import success
from services import lookup, serialize
import validation as V

bp = Blueprint("limited_partners", __name__)

LP_TYPES = ("INDIVIDUAL", "INSTITUTION", "FUND_OF_FUNDS", "SOVEREIGN")


@bp.route("/limited-partners", methods=["POST"])
def create_lp():
    caller = authenticate()
    require_role(caller, ["FundAdministrator", "ComplianceOfficer"])
    body = V.get_json_body()

    legal_name = V.require_string(body, "legal_name")
    lp_type = V.require_enum(body, "lp_type", LP_TYPES)
    tax_id_last4 = V.require_string(body, "tax_id_last4")
    is_tax_exempt = V.optional_bool(body, "is_tax_exempt", False)

    with db.lock:
        obj = db.stamp_new(
            {
                "legal_name": legal_name,
                "lp_type": lp_type,
                "tax_id_last4": tax_id_last4,
                "is_tax_exempt": is_tax_exempt,
            }
        )
        db.limited_partners[obj["id"]] = obj
    return success(serialize.limited_partner(obj), status=201)


@bp.route("/limited-partners/<lid>", methods=["GET"])
def read_lp(lid):
    caller = authenticate()
    require_role(
        caller,
        ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"],
    )
    obj = lookup.get_lp(lid)
    return success(serialize.limited_partner(obj))
