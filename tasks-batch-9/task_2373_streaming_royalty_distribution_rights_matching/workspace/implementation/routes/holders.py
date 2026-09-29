"""RightsHolder endpoints (§3.1)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import API_PREFIX, HOLDER_TYPES, ROLE_ROYALTY_ADMIN
from db import db, stamp_new
from middleware import require
from response import created_response, object_response

bp = Blueprint("holders", __name__, url_prefix=API_PREFIX)


@bp.post("/rights-holders")
@require(ROLE_ROYALTY_ADMIN)
def create_holder():
    data = validation.body()
    legal_name = validation.get_string(data, "legal_name", max_len=200)
    holder_type = validation.get_enum(data, "holder_type", HOLDER_TYPES)
    home_territory_code = validation.get_territory(
        data, "home_territory_code", allow_world=True)
    direct_deal_rate_bps = validation.get_int(
        data, "direct_deal_rate_bps", required=False, minimum=0, maximum=5000,
        default=None, nullable=True)

    record = {
        "legal_name": legal_name,
        "holder_type": holder_type,
        "home_territory_code": home_territory_code,
        "direct_deal_rate_bps": direct_deal_rate_bps,
    }
    stamp_new(record)
    db.rights_holders[record["id"]] = record
    return created_response(serializers.rights_holder(record))


@bp.get("/rights-holders/<holder_id>")
@require()
def read_holder(holder_id):
    holder = lookup.holder(holder_id)
    return object_response(serializers.rights_holder(holder))
