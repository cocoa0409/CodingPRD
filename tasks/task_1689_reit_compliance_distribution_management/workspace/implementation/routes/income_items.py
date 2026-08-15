"""IncomeItem endpoints."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.common import (
    get_json_body, make_entity, now_iso, req_bool, req_date, req_enum, req_int, touch,
)
from services.ledger import recompute_quarter_income_total

bp = Blueprint("income_items", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")
INCOME_CLASSES = ("RENTS", "MORTGAGE_INTEREST", "NON_QUALIFYING")


@bp.route("/reit-compliance/income-items", methods=["POST"])
def create_income_item():
    require_roles("ComplianceOfficer")
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

    income_class = req_enum(body, "income_class", INCOME_CLASSES)
    amount_cents = req_int(body, "amount_cents", min_value=0)
    source_is_trs = req_bool(body, "source_is_trs")
    accrued_at = req_date(body, "accrued_at")

    # Quarter-open gate (priority 8) precedes cross-reit check (priority 9)
    if quarter["status"] != "OPEN":
        raise errors.quarter_locked("Income items may only be created against an OPEN quarter")
    if quarter["reit_id"] != reit_id:
        raise errors.cross_reit("quarter_id belongs to a different REIT than reit_id")

    item = make_entity({
        "reit_id": reit_id,
        "quarter_id": quarter_id,
        "income_class": income_class,
        "amount_cents": amount_cents,
        "source_is_trs": source_is_trs,
        "accrued_at": accrued_at,
    })
    db.income_items[item["id"]] = item
    recompute_quarter_income_total(quarter_id)
    return success_object(dict(item), status=201)


@bp.route("/reit-compliance/income-items/<iid>", methods=["GET"])
def get_income_item(iid):
    require_roles(*ALL)
    item = db.income_items.get(iid)
    if item is None:
        raise errors.not_found("Income item not found")
    return success_object(dict(item))


@bp.route("/reit-compliance/income-items", methods=["GET"])
def list_income_items():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.income_items.values())
    reit_id = request.args.get("reit_id")
    quarter_id = request.args.get("quarter_id")
    if reit_id is not None:
        rows = [i for i in rows if i["reit_id"] == reit_id]
    if quarter_id is not None:
        rows = [i for i in rows if i["quarter_id"] == quarter_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(i) for i in page], limit, offset, total)


@bp.route("/reit-compliance/income-items/<iid>", methods=["PATCH"])
def update_income_item(iid):
    require_roles("ComplianceOfficer")
    item = db.income_items.get(iid)
    if item is None:
        raise errors.not_found("Income item not found")
    body = get_json_body()

    if "amount_cents" in body:
        v = body["amount_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise errors.validation("amount_cents must be an integer >= 0")
    if "income_class" in body and body["income_class"] not in INCOME_CLASSES:
        raise errors.validation("income_class out of declared set")

    quarter = db.quarters.get(item["quarter_id"])
    if quarter is None or quarter["status"] != "OPEN":
        raise errors.quarter_locked("Income items may only be amended while the quarter is OPEN")

    if "amount_cents" in body:
        item["amount_cents"] = body["amount_cents"]
    if "income_class" in body:
        item["income_class"] = body["income_class"]

    touch(item)
    recompute_quarter_income_total(item["quarter_id"])
    return success_object(dict(item))
