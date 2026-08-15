"""Fee assessment endpoints."""
from flask import Blueprint

from middleware import ADMIN, auth
from response import ok
from services import get_fee, ser_fee, touch
from util import as_str, body, required

bp = Blueprint("fees", __name__)


@bp.post("/fee-assessments/<fid>/waive")
def waive_fee(fid):
    auth(ADMIN)
    fee = get_fee(fid)
    data = body()
    reason = as_str(required(data, "reason"), "reason")
    fee["waived"] = True
    fee["waived_reason"] = reason
    fee["charged_cents"] = 0
    touch(fee)
    return ok(ser_fee(fee))
