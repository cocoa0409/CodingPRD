"""RestrictedFund endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("restricted_funds", __name__)

CATEGORIES = {
    "PERSONNEL", "EQUIPMENT", "TRAVEL", "SUPPLIES",
    "SUBAWARD_PASS_THROUGH", "INDIRECT",
}

READ_ROLES = ("FinanceOfficer", "AgencyOfficer", "Auditor")


def _serialize(fund):
    return c.serialize(fund)


@bp.route("/restricted-funds", methods=["POST"])
@require_roles("FinanceOfficer")
def create_fund(user_id, role):
    body = c.get_body()

    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        if award_id not in db.awards:
            raise errors.not_found("Award not found.")

        # priority 14: field validity.
        category = c.require_enum(body, "category", CATEGORIES)
        budgeted_cents = c.require_int(body, "budgeted_cents", minimum=0)
        priority_order = c.require_int(body, "priority_order", minimum=1)

        # priority 15: uniqueness of priority_order and category within an award.
        for f in db.restricted_funds.values():
            if f["award_id"] != award_id:
                continue
            if f["priority_order"] == priority_order:
                raise errors.duplicate("priority_order already used within this award.")
            if f["category"] == category:
                raise errors.duplicate("category already used within this award.")

        record = {
            "award_id": award_id,
            "category": category,
            "budgeted_cents": budgeted_cents,
            "allocated_cents": 0,
            "priority_order": priority_order,
        }
        db.stamp_create(record)
        db.restricted_funds[record["id"]] = record
        return success(_serialize(record), status=201)


@bp.route("/restricted-funds", methods=["GET"])
@require_roles(*READ_ROLES)
def list_funds(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    with db.LOCK:
        records = list(db.restricted_funds.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/restricted-funds/<fund_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_fund(fund_id, user_id, role):
    with db.LOCK:
        fund = db.restricted_funds.get(fund_id)
        if fund is None:
            raise errors.not_found("Restricted fund not found.")
        return success(_serialize(fund), status=200)


@bp.route("/restricted-funds/<fund_id>/allocations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_fund_allocations(fund_id, user_id, role):
    limit, offset = c.parse_pagination()
    with db.LOCK:
        fund = db.restricted_funds.get(fund_id)
        if fund is None:
            raise errors.not_found("Restricted fund not found.")
        records = [
            a for a in db.fund_allocations.values()
            if a["restricted_fund_id"] == fund_id
        ]
    page, pagination = c.paginate(records, limit, offset)
    return success([c.serialize(r) for r in page], status=200, pagination=pagination)
