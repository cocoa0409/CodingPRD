"""PremiumSchedule routes (PRD §3.1).

PremiumSchedule is immutable; it carries only id + created_at (no updated_at,
no version) — PRD §2.4.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response
from services.common import serialize

bp = Blueprint("premium_schedules", __name__)


def _validate_tiers(tiers):
    """tiers: ordered array of {upper_bound_cents, rate_bps}; ascending by
    upper_bound_cents with the open (null) tier last (PRD §3.1)."""
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise err(errors.ERR_INVALID_REQUEST, "tiers must be a non-empty array")
    normalized = []
    prev_bound = None
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise err(errors.ERR_INVALID_REQUEST, "each tier must be an object")
        if "rate_bps" not in tier or "upper_bound_cents" not in tier:
            raise err(errors.ERR_INVALID_REQUEST,
                      "each tier needs upper_bound_cents and rate_bps")
        rate = tier["rate_bps"]
        if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
            raise err(errors.ERR_INVALID_REQUEST, "rate_bps must be a non-negative integer")
        ub = tier["upper_bound_cents"]
        is_open = ub is None
        if not is_open:
            if isinstance(ub, bool) or not isinstance(ub, int) or ub <= 0:
                raise err(errors.ERR_INVALID_REQUEST,
                          "upper_bound_cents must be a positive integer or null")
        # ordering: open tier must be last; ascending bounds.
        if is_open and i != len(tiers) - 1:
            raise err(errors.ERR_INVALID_REQUEST, "the open (null) tier must be last")
        if not is_open and prev_bound is not None and ub <= prev_bound:
            raise err(errors.ERR_INVALID_REQUEST,
                      "tiers must be sorted ascending by upper_bound_cents")
        if not is_open:
            prev_bound = ub
        normalized.append({"upper_bound_cents": ub, "rate_bps": rate})
    return normalized


@bp.route("/premium-schedules", methods=["POST"])
def create_premium_schedule():
    require_role({"SaleAdministrator"})
    body = get_json_body()
    name = body.get("name")
    if not isinstance(name, str) or name == "":
        raise err(errors.ERR_INVALID_REQUEST, "name must be a non-empty string")
    if "tiers" not in body:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: tiers")
    tiers = _validate_tiers(body["tiers"])

    with db.LOCK:
        common = db.new_common(with_version=False)
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "_seq": common["_seq"],
            "name": name,
            "tiers": tiers,
        }
        db.premium_schedules[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/premium-schedules/<id>", methods=["GET"])
def get_premium_schedule(id):
    require_role({"SaleAdministrator", "FinanceOfficer", "Auctioneer", "Viewer"})
    with db.LOCK:
        record = db.premium_schedules.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Premium schedule not found")
        return object_response(serialize(record), 200)
