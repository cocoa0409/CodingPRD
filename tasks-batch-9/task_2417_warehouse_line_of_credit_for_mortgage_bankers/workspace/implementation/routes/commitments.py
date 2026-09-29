"""Take-out commitment routes (PRD 3.2)."""

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import COLLATERAL_ANALYST, CREDIT_OFFICER, INVESTOR, require_auth
from response import ok
from routes.common import get_commitment
from serializers import commitment_out
from services.states import orphan_cascade
from validation import body, v_string

bp = Blueprint("commitments", __name__)


@bp.get("/commitments/<commitment_id>")
def read_commitment(commitment_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, INVESTOR])
    commitment = get_commitment(commitment_id)
    return ok(commitment_out(commitment))


@bp.post("/commitments/<commitment_id>/withdraw")
def withdraw_commitment(commitment_id):
    require_auth([CREDIT_OFFICER, INVESTOR])
    commitment = get_commitment(commitment_id)
    data = body()
    v_string(data, "reason", max_len=500)
    # priority 15
    if commitment["status"] not in ("OPEN", "PARTIALLY_ALLOCATED"):
        raise ApiError("ERR_COMMITMENT_NOT_ACTIVE",
                       "Only an OPEN or PARTIALLY_ALLOCATED commitment may be "
                       "withdrawn.")
    facility = db.facilities[commitment["facility_id"]]
    commitment["status"] = "WITHDRAWN"
    touch(commitment)
    orphan_cascade(facility, [commitment])
    return ok(commitment_out(commitment))
