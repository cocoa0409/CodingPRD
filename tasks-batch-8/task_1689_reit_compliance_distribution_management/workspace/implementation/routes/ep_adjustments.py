"""EpAdjustment endpoints — OCC-guarded create, post with chronological replay."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.common import get_json_body, make_entity, req_date, req_enum, req_int, touch
from services.ledger import refresh_ep_balance

bp = Blueprint("ep_adjustments", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")
EP_KINDS = ("TAXABLE_INCOME", "DISALLOWED_DEDUCTION", "FEDERAL_TAX")


@bp.route("/reit-compliance/ep-adjustments", methods=["POST"])
def create_adjustment():
    require_roles("TaxDirector")
    body = get_json_body()
    reit_id = body.get("reit_id")
    quarter_id = body.get("quarter_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if not isinstance(quarter_id, str) or not quarter_id:
        raise errors.validation("Field 'quarter_id' is required")
    reit = db.reits.get(reit_id)
    if reit is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")
    quarter = db.quarters.get(quarter_id)
    if quarter is None:
        raise errors.not_found("quarter_id does not resolve to an existing Quarter")

    kind = req_enum(body, "kind", EP_KINDS)
    amount_cents = req_int(body, "amount_cents", min_value=0)
    effective_date = req_date(body, "effective_date")

    expected = body.get("expected_reit_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.validation("expected_reit_version is required and must be an integer")

    # Quarter-open gate (priority 8) precedes cross-reit (9); OCC is priority 16
    if quarter["status"] != "OPEN":
        raise errors.quarter_locked("E&P adjustments may only be created against an OPEN quarter")
    if quarter["reit_id"] != reit_id:
        raise errors.cross_reit("quarter_id belongs to a different REIT than reit_id")
    if expected != reit["version"]:
        raise errors.stale_version()

    adj = make_entity({
        "reit_id": reit_id,
        "quarter_id": quarter_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "status": "DRAFT",
    })
    db.ep_adjustments[adj["id"]] = adj
    # Creating an adjustment increments the REIT's version
    touch(reit)
    return success_object(dict(adj), status=201)


@bp.route("/reit-compliance/ep-adjustments/<aid>", methods=["GET"])
def get_adjustment(aid):
    require_roles(*ALL)
    adj = db.ep_adjustments.get(aid)
    if adj is None:
        raise errors.not_found("E&P adjustment not found")
    return success_object(dict(adj))


@bp.route("/reit-compliance/ep-adjustments", methods=["GET"])
def list_adjustments():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.ep_adjustments.values())
    reit_id = request.args.get("reit_id")
    quarter_id = request.args.get("quarter_id")
    if reit_id is not None:
        rows = [a for a in rows if a["reit_id"] == reit_id]
    if quarter_id is not None:
        rows = [a for a in rows if a["quarter_id"] == quarter_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(a) for a in page], limit, offset, total)


@bp.route("/reit-compliance/ep-adjustments/<aid>/post", methods=["POST"])
def post_adjustment(aid):
    require_roles("TaxDirector")
    adj = db.ep_adjustments.get(aid)
    if adj is None:
        raise errors.not_found("E&P adjustment not found")
    if adj["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT adjustments can be posted")
    quarter = db.quarters.get(adj["quarter_id"])
    if quarter is None:
        raise errors.not_found("Quarter not found")
    if quarter["status"] != "OPEN":
        raise errors.quarter_locked("E&P adjustments may only be posted while the quarter is OPEN")

    adj["status"] = "POSTED"
    touch(adj)

    reit = db.reits.get(adj["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")
    refresh_ep_balance(reit)
    touch(reit)

    return success_object(dict(adj))
