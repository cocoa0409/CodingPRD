"""WorkCreditRecord endpoints."""
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_DUPLICATE_CREDIT_YEAR,
    invalid_request,
    not_found,
    ref_not_found,
)
from middleware import require_roles
from response import created, ok, paginated
from services.utils import (
    paginate,
    parse_pagination,
    require_body,
    require_int,
    require_str,
)

bp = Blueprint("work_credits", __name__)


@bp.route("/ssdi/work-credits", methods=["POST"])
@require_roles("SSAAdmin")
def create_work_credit(user_id, role):
    body = require_body()
    claimant_id = require_str(body, "claimant_id")
    if claimant_id not in db.claimants:
        raise ref_not_found(f"claimant {claimant_id} not found")
    year = require_int(body, "year")
    if not (1990 <= year <= 2099):
        raise invalid_request("year must be between 1990 and 2099")
    credits = require_int(body, "credits_earned")
    if not (0 <= credits <= 4):
        raise invalid_request("credits_earned must be between 0 and 4")
    earnings = require_int(body, "earnings_cents")
    if earnings < 0:
        raise invalid_request("earnings_cents must be non-negative")

    # Uniqueness per (claimant_id, year)
    for r in db.work_credits.values():
        if r.get("claimant_id") == claimant_id and r.get("year") == year:
            raise APIError(
                ERR_DUPLICATE_CREDIT_YEAR,
                409,
                f"work credit for claimant {claimant_id} year {year} already exists",
            )

    rec = {
        "claimant_id": claimant_id,
        "year": year,
        "credits_earned": credits,
        "earnings_cents": earnings,
    }
    db.stamp_create(rec)
    db.work_credits[rec["id"]] = rec
    return created(rec)


@bp.route("/ssdi/work-credits/<wid>", methods=["GET"])
@require_roles("SSAAdmin", "Claimant")
def get_work_credit(wid, user_id, role):
    rec = db.work_credits.get(wid)
    if rec is None:
        raise not_found(f"work credit {wid} not found")
    return ok(rec)


@bp.route("/ssdi/work-credits", methods=["GET"])
@require_roles("SSAAdmin", "Claimant")
def list_work_credits(user_id, role):
    limit, offset = parse_pagination(request.args)
    claimant_filter = request.args.get("claimant_id")
    items = list(db.work_credits.values())
    if claimant_filter:
        items = [r for r in items if r.get("claimant_id") == claimant_filter]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)
