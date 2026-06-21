"""Dispute endpoints and adjudication lifecycle: file, claim (freeze), resolve
(expense-adjust cascade), reject, reopen (PRD §3.9)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import household as hh

bp = Blueprint("disputes", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}


def _other_dispute_under_review(household_id, excluding_id):
    for d in db.disputes.values():
        if d["id"] == excluding_id:
            continue
        if d["household_id"] == household_id and d["status"] == "UNDER_REVIEW":
            return True
    return False


def _unfreeze_if_clear(household, dispute):
    if not _other_dispute_under_review(household["id"], dispute["id"]):
        if household["status"] == "FROZEN":
            household["status"] = "ACTIVE"
            models.touch(household)


@bp.route("/disputes", methods=["POST"])
def file_dispute():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        household_id = validate.require_str(body, "household_id")
        filed_by_id = validate.require_str(body, "filed_by_id")
        reason = validate.require_str(body, "reason")
        expense_id = body.get("expense_id")
        settlement_id = body.get("settlement_id")
        # existence: household, filed_by, target
        household = db.households.get(household_id)
        if not household:
            raise err("ERR_NOT_FOUND", "household_id does not exist.")
        if filed_by_id not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "filed_by_id does not exist.")
        has_exp = expense_id is not None
        has_settle = settlement_id is not None
        if has_exp == has_settle:
            raise err("ERR_VALIDATION", "Exactly one of expense_id or settlement_id must be set.")
        settlement = None
        if has_exp:
            if expense_id not in db.expenses:
                raise err("ERR_NOT_FOUND", "expense_id does not exist.")
        if has_settle:
            settlement = db.settlements.get(settlement_id)
            if not settlement:
                raise err("ERR_NOT_FOUND", "settlement_id does not exist.")

        # When filed against a settlement BY its debtor, drive the settlement -> DISPUTED.
        drive_settlement = False
        if settlement is not None:
            if filed_by_id == settlement["from_profile_id"] and settlement["status"] == "PROPOSED":
                drive_settlement = True

        dispute = {
            "household_id": household_id,
            "expense_id": expense_id if has_exp else None,
            "settlement_id": settlement_id if has_settle else None,
            "filed_by_id": filed_by_id,
            "reason": reason,
            "adjusted_amount_cents": None,
            "status": "OPEN",
        }
        models.stamp_create(dispute)
        db.disputes[dispute["id"]] = dispute
        if drive_settlement:
            settlement["status"] = "DISPUTED"
            models.touch(settlement)
        return response.ok(models.serialize(dispute), 201)


@bp.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        d = db.disputes.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        return response.ok(models.serialize(d))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.disputes.values())
        household_id = request.args.get("household_id")
        expense_id = request.args.get("expense_id")
        settlement_id = request.args.get("settlement_id")
        filed_by_id = request.args.get("filed_by_id")
        if household_id is not None:
            items = [x for x in items if x["household_id"] == household_id]
        if expense_id is not None:
            items = [x for x in items if x.get("expense_id") == expense_id]
        if settlement_id is not None:
            items = [x for x in items if x.get("settlement_id") == settlement_id]
        if filed_by_id is not None:
            items = [x for x in items if x["filed_by_id"] == filed_by_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/disputes/<did>/claim", methods=["POST"])
def claim_dispute(did):
    with db.lock:
        p = authenticate()
        require_roles(p, {"DisputeMediator"})
        d = db.disputes.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        # segregation of duties (priority 4) before state
        if p.user_id == d["filed_by_id"]:
            raise err("ERR_SELF_ADJUDICATION", "Mediator may not adjudicate own dispute.")
        if d["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Dispute is not OPEN.")
        household = db.households.get(d["household_id"])
        d["status"] = "UNDER_REVIEW"
        models.touch(d)
        household["status"] = "FROZEN"
        models.touch(household)
        return response.ok(models.serialize(d))


@bp.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    with db.lock:
        p = authenticate()
        require_roles(p, {"DisputeMediator"})
        d = db.disputes.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        if p.user_id == d["filed_by_id"]:
            raise err("ERR_SELF_ADJUDICATION", "Mediator may not adjudicate own dispute.")
        if d["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
        body = validate.get_json_body()
        household = db.households.get(d["household_id"])
        adjusted = body.get("adjusted_amount_cents")
        if d.get("expense_id") is not None:
            # expense path: adjusted_amount_cents present and > 0
            if adjusted is None or isinstance(adjusted, bool) or not isinstance(adjusted, int) or adjusted <= 0:
                raise err("ERR_VALIDATION", "adjusted_amount_cents must be a positive integer for an expense dispute.")
            d["adjusted_amount_cents"] = adjusted
            expense = db.expenses.get(d["expense_id"])
            expense["total_amount_cents"] = adjusted
            _recompute_expense_shares(expense)
            models.touch(expense)
            # ledger recompute is part of the adjudication cascade itself (the FROZEN gate
            # blocks external ledger writes, not this internal recompute). Unfreezing is
            # handled by _unfreeze_if_clear below, gated on no other dispute under review.
            hh.recompute_net_balances(household)
        else:
            if adjusted is not None:
                if isinstance(adjusted, bool) or not isinstance(adjusted, int):
                    raise err("ERR_VALIDATION", "adjusted_amount_cents must be an integer.")
                d["adjusted_amount_cents"] = adjusted
        d["status"] = "RESOLVED"
        models.touch(d)
        _unfreeze_if_clear(household, d)
        return response.ok(models.serialize(d))


def _recompute_expense_shares(expense):
    from services import calc
    # remove old shares
    old = [sid for sid, s in db.expense_shares.items() if s["expense_id"] == expense["id"]]
    for sid in old:
        del db.expense_shares[sid]
    participants = expense["participant_ids"]
    if expense["split_mode"] == "CUSTOM":
        # CUSTOM overrides no longer sum to the adjusted total; fall back to EQUAL recompute
        entries = [(pid, 1) for pid in participants]
    else:
        entries = [(pid, 1) for pid in participants]
    shares = calc.waterfall_allocation(expense["total_amount_cents"], entries)
    for pid in participants:
        row = {
            "expense_id": expense["id"],
            "profile_id": pid,
            "share_cents": shares.get(pid, 0),
        }
        models.stamp_lean(row)
        db.expense_shares[row["id"]] = row


@bp.route("/disputes/<did>/reject", methods=["POST"])
def reject_dispute(did):
    with db.lock:
        p = authenticate()
        require_roles(p, {"DisputeMediator"})
        d = db.disputes.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        if p.user_id == d["filed_by_id"]:
            raise err("ERR_SELF_ADJUDICATION", "Mediator may not adjudicate own dispute.")
        if d["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
        household = db.households.get(d["household_id"])
        d["status"] = "REJECTED"
        models.touch(d)
        _unfreeze_if_clear(household, d)
        return response.ok(models.serialize(d))


@bp.route("/disputes/<did>/reopen", methods=["POST"])
def reopen_dispute(did):
    with db.lock:
        p = authenticate()
        require_roles(p, {"DisputeMediator"})
        d = db.disputes.get(did)
        if not d:
            raise err("ERR_NOT_FOUND", "Dispute not found.")
        if d["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
        household = db.households.get(d["household_id"])
        d["status"] = "OPEN"
        models.touch(d)
        _unfreeze_if_clear(household, d)
        return response.ok(models.serialize(d))
