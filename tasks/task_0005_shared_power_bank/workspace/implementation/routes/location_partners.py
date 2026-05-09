from decimal import Decimal
from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields
from envelope import created
from validation import need_body, require_str, require_decimal
from serializers import serialize_location_partner

bp = Blueprint("location_partners", __name__)


@bp.post("/location-partners")
def create_location_partner():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))
    partner_code = require_str(body, "partner_code")
    name = require_str(body, "name")
    revenue_share_pct = require_decimal(body, "revenue_share_pct",
                                        min_value=Decimal("0"), max_value=Decimal("1"))

    cf = make_common_fields()
    partner = {
        **cf,
        "partner_code": partner_code,
        "name": name,
        "revenue_share_pct": revenue_share_pct,
    }
    db.location_partners[partner["id"]] = partner
    return created(serialize_location_partner(partner))
