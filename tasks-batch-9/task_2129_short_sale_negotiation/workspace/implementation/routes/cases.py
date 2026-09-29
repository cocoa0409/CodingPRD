"""Short sale cases (PRD §3.1)."""
from flask import Blueprint

import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, success
from serializers import case_out

bp = Blueprint("cases", __name__)

READ_ONE_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_LISTING_AGENT,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_MI_UNDERWRITER,
    K.ROLE_JUNIOR_LIEN_HOLDER,
    K.ROLE_BPO_VENDOR,
    K.ROLE_PLATFORM_ADMIN,
)
READ_LIST_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_LISTING_AGENT,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_MI_UNDERWRITER,
    K.ROLE_PLATFORM_ADMIN,
)


@bp.post("/short-sale/cases")
def create_case():
    user_id = require(K.ROLE_NEGOTIATOR)
    data = V.body()
    investor_type = V.req_enum(data, "investor_type", K.INVESTOR_TYPES)
    case = {
        "id": db.new_id(),
        "property_address": V.req_string(data, "property_address"),
        "investor_type": investor_type,
        "unpaid_principal_balance_cents": V.req_int(
            data, "unpaid_principal_balance_cents", minimum=1
        ),
        "servicer_name": V.req_string(data, "servicer_name"),
        "assigned_negotiator_user_id": user_id,
        "negotiation_status": "INTAKE",
        "documentation_status": "DOC_PENDING",
        "final_value_cents": None,
        "minimum_acceptable_net_cents": None,
        "junior_contribution_total_cents": 0,
        "junior_lien_count": 0,
        "failed_offer_count": 0,
        "price_reduction_required": False,
        "deficiency_waiver_permitted": investor_type in ("GSE", "FHA"),
    }
    db.insert("cases", case)
    return created(case_out(case))


@bp.get("/short-sale/cases/<case_id>")
def get_case(case_id):
    require(*READ_ONE_ROLES)
    case = S.need_case(case_id)
    return success(case_out(case))


@bp.get("/short-sale/cases")
def list_cases():
    require(*READ_LIST_ROLES)
    negotiation = enum_filter("negotiation_status", K.NEGOTIATION_STATUSES)
    documentation = enum_filter("documentation_status", K.DOCUMENTATION_STATUSES)
    rows = db.all("cases")
    if negotiation is not None:
        rows = [r for r in rows if r["negotiation_status"] == negotiation]
    if documentation is not None:
        rows = [r for r in rows if r["documentation_status"] == documentation]
    return collection(rows, case_out, sort_key=lambda r: r["_seq"])
