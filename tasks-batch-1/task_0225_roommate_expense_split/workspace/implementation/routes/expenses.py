"""Expense endpoints: log (EQUAL/CUSTOM split), read, lists, shares, void (PRD §3.6)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import calc
from services import household as hh

bp = Blueprint("expenses", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}
SPLIT_MODE = {"EQUAL", "CUSTOM"}


def _build_expense_shares(expense):
    """Create ExpenseShare rows. EQUAL uses waterfall; CUSTOM uses share_overrides."""
    participants = expense["participant_ids"]
    if expense["split_mode"] == "CUSTOM":
        overrides = expense["share_overrides"]
        for pid in participants:
            row = {
                "expense_id": expense["id"],
                "profile_id": pid,
                "share_cents": overrides[pid],
            }
            models.stamp_lean(row)
            db.expense_shares[row["id"]] = row
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


@bp.route("/expenses", methods=["POST"])
def create_expense():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        household_id = validate.require_str(body, "household_id")
        payer_id = validate.require_str(body, "payer_id")
        description = validate.require_str(body, "description")
        total = validate.require_int(body, "total_amount_cents", minimum=1)
        split_mode = validate.require_enum(body, "split_mode", SPLIT_MODE, default="EQUAL")
        participant_ids = validate.require_str_list(body, "participant_ids")
        share_overrides = body.get("share_overrides")

        # existence: household, payer, every participant (left-to-right)
        household = db.households.get(household_id)
        if not household:
            raise err("ERR_NOT_FOUND", "household_id does not exist.")
        if payer_id not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "payer_id does not exist.")
        for pid in participant_ids:
            if pid not in db.roommate_profiles:
                raise err("ERR_NOT_FOUND", f"participant {pid} does not exist.")

        # frozen gate (priority 7)
        if household["status"] == "FROZEN":
            raise err("ERR_HOUSEHOLD_FROZEN", "Household is frozen.")

        # priority 8: payer + every participant must be ACTIVE members
        if not hh.is_active_member(household_id, payer_id):
            raise err("ERR_NOT_HOUSEHOLD_MEMBER", "Payer is not an active member.")
        for pid in participant_ids:
            if not hh.is_active_member(household_id, pid):
                raise err("ERR_NOT_HOUSEHOLD_MEMBER", f"Participant {pid} is not an active member.")

        # priority 10: CUSTOM shares must cover exactly the participants and sum to total
        if split_mode == "CUSTOM":
            if not isinstance(share_overrides, dict):
                raise err("ERR_SHARES_DO_NOT_SUM", "share_overrides required for CUSTOM split.")
            if set(share_overrides.keys()) != set(participant_ids):
                raise err("ERR_SHARES_DO_NOT_SUM", "share_overrides keys must equal participant_ids.")
            for v in share_overrides.values():
                if isinstance(v, bool) or not isinstance(v, int):
                    raise err("ERR_SHARES_DO_NOT_SUM", "share_overrides values must be integers.")
            if sum(share_overrides.values()) != total:
                raise err("ERR_SHARES_DO_NOT_SUM", "share_overrides must sum to total_amount_cents.")

        expense = {
            "household_id": household_id,
            "payer_id": payer_id,
            "description": description,
            "total_amount_cents": total,
            "split_mode": split_mode,
            "participant_ids": list(participant_ids),
            "share_overrides": share_overrides if split_mode == "CUSTOM" else None,
            "status": "POSTED",
        }
        models.stamp_create(expense)
        db.expenses[expense["id"]] = expense
        _build_expense_shares(expense)
        hh.recompute_net_balances(household)
        models.touch(household)
        return response.ok(models.serialize(expense), 201)


@bp.route("/expenses", methods=["GET"])
def list_expenses():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.expenses.values())
        household_id = request.args.get("household_id")
        payer_id = request.args.get("payer_id")
        if household_id is not None:
            items = [x for x in items if x["household_id"] == household_id]
        if payer_id is not None:
            items = [x for x in items if x["payer_id"] == payer_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/expenses/<eid>", methods=["GET"])
def get_expense(eid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        expense = db.expenses.get(eid)
        if not expense:
            raise err("ERR_NOT_FOUND", "Expense not found.")
        return response.ok(models.serialize(expense))


@bp.route("/expenses/<eid>/shares", methods=["GET"])
def list_expense_shares(eid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        if eid not in db.expenses:
            raise err("ERR_NOT_FOUND", "Expense not found.")
        limit, offset = parse_pagination()
        items = [s for s in db.expense_shares.values() if s["expense_id"] == eid]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/expenses/<eid>/void", methods=["POST"])
def void_expense(eid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        expense = db.expenses.get(eid)
        if not expense:
            raise err("ERR_NOT_FOUND", "Expense not found.")
        household = db.households.get(expense["household_id"])
        if expense["status"] != "POSTED":
            raise err("ERR_INVALID_STATE", "Expense is not POSTED.")
        if household["status"] == "FROZEN":
            raise err("ERR_HOUSEHOLD_FROZEN", "Household is frozen.")
        expense["status"] = "VOIDED"
        models.touch(expense)
        hh.recompute_net_balances(household)
        models.touch(household)
        return response.ok(models.serialize(expense))
