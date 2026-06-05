"""Payout routes: create, read, list-by-statement, settle, reverse."""
from flask import Blueprint, request

import db
from errors import (fail, ERR_INVALID_STATE, ERR_RIGHTSHOLDER_SUSPENDED,
                    ERR_NOTHING_PAYABLE)
from middleware import authorize
from response import success
from services import serialize as S
from services.common import (stamp_create, touch, require_body,
                             parse_pagination, paginate, sorted_by_creation)
from services.lookup import path_get, fk_get, require_owner

bp = Blueprint("payouts", __name__)


@bp.route("/payouts", methods=["POST"])
def create_payout():
    authorize({"RoyaltyOperator"})
    data = require_body(request.get_json(silent=True))
    statement_id = data.get("statement_id")
    stmt = fk_get(db.statements, statement_id)
    # State (priority 6): statement must be FINALIZED.
    if stmt["status"] != "FINALIZED":
        fail(ERR_INVALID_STATE, "Payout requires a FINALIZED statement")
    rh = db.rightsholders[stmt["rightsholder_id"]]
    # Suspension (priority 19) then payability (priority 20).
    if rh["status"] != "ACTIVE":
        fail(ERR_RIGHTSHOLDER_SUSPENDED, "Rightsholder is suspended")
    if stmt["net_payable_cents"] < 1:
        fail(ERR_NOTHING_PAYABLE, "Statement net_payable_cents is below 1")
    rec = {
        "statement_id": statement_id,
        "rightsholder_id": stmt["rightsholder_id"],
        "amount_cents": stmt["net_payable_cents"],
        "status": "PENDING",
    }
    stamp_create(rec)
    db.payouts[rec["id"]] = rec
    # Statement FINALIZED -> PAID, version bump.
    stmt["status"] = "PAID"
    touch(stmt)
    return success(S.payout(rec), status=201)


@bp.route("/payouts/<rid>", methods=["GET"])
def get_payout(rid):
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    rec = path_get(db.payouts, rid)
    require_owner(rec["rightsholder_id"], user_id, role)
    return success(S.payout(rec))


@bp.route("/statements/<rid>/payouts", methods=["GET"])
def list_statement_payouts(rid):
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    stmt = path_get(db.statements, rid)
    require_owner(stmt["rightsholder_id"], user_id, role)
    limit, offset = parse_pagination(request.args)
    items = [p for p in db.payouts.values() if p["statement_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.payout(p) for p in page], pagination=meta)


@bp.route("/payouts/<rid>/settle", methods=["POST"])
def settle_payout(rid):
    authorize({"RoyaltyOperator"})
    rec = path_get(db.payouts, rid)
    if rec["status"] != "PENDING":
        fail(ERR_INVALID_STATE, "Only a PENDING payout can be settled")
    rec["status"] = "SETTLED"
    touch(rec)
    return success(S.payout(rec))


@bp.route("/payouts/<rid>/reverse", methods=["POST"])
def reverse_payout(rid):
    authorize({"RoyaltyOperator"})
    rec = path_get(db.payouts, rid)
    if rec["status"] != "PENDING":
        fail(ERR_INVALID_STATE, "Only a PENDING payout can be reversed")
    rec["status"] = "REVERSED"
    touch(rec)
    # Referenced statement reverts PAID -> FINALIZED, version bump (PRD §3.8).
    stmt = db.statements.get(rec["statement_id"])
    if stmt is not None and stmt["status"] == "PAID":
        stmt["status"] = "FINALIZED"
        touch(stmt)
    return success(S.payout(rec))
