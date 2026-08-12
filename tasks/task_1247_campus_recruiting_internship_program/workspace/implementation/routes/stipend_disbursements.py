"""StipendDisbursement routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_season_posture_forbidden,
    err_disbursement_state_forbidden,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_offer,
    get_stipend_disbursement,
    stipend_disbursement_view,
    offer_season,
)
from utils import parse_pagination, touch

bp = Blueprint("stipend_disbursements", __name__)


@bp.route("/offers/<oid>/stipend-disbursements", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_offer_disbursements(oid):
    get_offer(oid)
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.stipend_disbursements.values() if d["offer_id"] == oid]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([stipend_disbursement_view(d) for d in page], total, limit, offset)


@bp.route("/stipend-disbursements/<sid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def get_one_disbursement(sid):
    d = get_stipend_disbursement(sid)
    return success_object(stipend_disbursement_view(d))


@bp.route("/stipend-disbursements/<sid>/disburse", methods=["POST"])
@require_auth(["Recruiter", "RecruitingAdmin"])
def disburse(sid):
    d = get_stipend_disbursement(sid)
    season = offer_season(get_offer(d["offer_id"]))
    # Posture
    if season["status"] != "INTERN_ACTIVE":
        raise err_season_posture_forbidden()
    # State
    if d["status"] != "RESERVED":
        raise err_disbursement_state_forbidden()
    d["status"] = "DISBURSED"
    touch(d)
    season["stipend_reserved_cents"] -= d["amount_cents"]
    season["stipend_disbursed_cents"] += d["amount_cents"]
    touch(season)
    return success_object(stipend_disbursement_view(d))
