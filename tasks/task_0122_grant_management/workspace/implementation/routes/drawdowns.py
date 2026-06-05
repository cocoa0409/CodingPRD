"""Drawdown endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c
from services.drawdown import derive_waterfall, plans_match

bp = Blueprint("drawdowns", __name__)

READ_ROLES = ("FinanceOfficer", "AgencyOfficer", "Auditor")


def _serialize(dd):
    return c.serialize(dd)


def _load(dd_id):
    dd = db.drawdowns.get(dd_id)
    if dd is None:
        raise errors.not_found("Drawdown not found.")
    return dd


def _validate_allocation_plan(body):
    """Validate the allocation_plan shape (priority 14, PRD §3.5).

    Each entry must name a restricted_fund_id (string) and amount_cents
    (integer). Returns the normalized list of {restricted_fund_id, amount_cents}.
    """
    plan = c.require_present(body, "allocation_plan")
    if not isinstance(plan, list):
        raise errors.invalid_request("allocation_plan must be an array.")
    normalized = []
    for entry in plan:
        if not isinstance(entry, dict):
            raise errors.invalid_request("Each allocation_plan entry must be an object.")
        fund_id = entry.get("restricted_fund_id")
        amt = entry.get("amount_cents")
        if not isinstance(fund_id, str) or fund_id == "":
            raise errors.invalid_request("allocation_plan entry restricted_fund_id must be a string.")
        if isinstance(amt, bool) or not isinstance(amt, int):
            raise errors.invalid_request("allocation_plan entry amount_cents must be an integer.")
        normalized.append({"restricted_fund_id": fund_id, "amount_cents": amt})
    return normalized


@bp.route("/drawdowns", methods=["POST"])
@require_roles("FinanceOfficer")
def create_drawdown(user_id, role):
    body = c.get_body()

    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        if award_id not in db.awards:
            raise errors.not_found("Award not found.")

        amount_cents = c.require_int(body, "amount_cents", minimum=1)
        plan = _validate_allocation_plan(body)

        # Plan must sum to amount_cents (PRD §3.5, ERR_INVALID_REQUEST).
        if sum(e["amount_cents"] for e in plan) != amount_cents:
            raise errors.invalid_request("allocation_plan must sum to amount_cents.")

        record = {
            "award_id": award_id,
            "initiated_by_user_id": user_id,
            "amount_cents": amount_cents,
            "allocation_plan": plan,
            "status": "REQUESTED",
        }
        db.stamp_create(record)
        db.drawdowns[record["id"]] = record
        return success(_serialize(record), status=201)


@bp.route("/drawdowns", methods=["GET"])
@require_roles(*READ_ROLES)
def list_drawdowns(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.drawdowns.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/drawdowns/<dd_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_drawdown(dd_id, user_id, role):
    with db.LOCK:
        return success(_serialize(_load(dd_id)), status=200)


@bp.route("/drawdowns/<dd_id>/allocations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_drawdown_allocations(dd_id, user_id, role):
    limit, offset = c.parse_pagination()
    with db.LOCK:
        _load(dd_id)
        records = [a for a in db.fund_allocations.values() if a["drawdown_id"] == dd_id]
    page, pagination = c.paginate(records, limit, offset)
    return success([c.serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/drawdowns/<dd_id>/disburse", methods=["POST"])
@require_roles("FinanceOfficer")
def disburse_drawdown(dd_id, user_id, role):
    with db.LOCK:
        dd = _load(dd_id)
        # priority 4: state
        if dd["status"] != "REQUESTED":
            raise errors.invalid_state("Only a REQUESTED drawdown may be disbursed.")
        award = db.awards.get(dd["award_id"])
        # priority 6: parent award must be ACTIVE (ERR_AWARD_NOT_ACTIVE).
        if award is None or award["status"] != "ACTIVE":
            raise errors.award_not_active()

        # Derive the canonical waterfall (pure; mutates nothing).
        derived_lines, remaining = derive_waterfall(dd["award_id"], dd["amount_cents"])

        # priority 10: allocation_plan must match the derived waterfall.
        if not plans_match(derived_lines, dd["allocation_plan"]):
            raise errors.allocation_mismatch()

        # priority 12: federal ceiling guard.
        if award["federal_drawn_cents"] + dd["amount_cents"] > award["federal_ceiling_cents"]:
            raise errors.ceiling_exceeded()

        # priority 13: per-fund budget guard. With the waterfall capping each
        # take at headroom, the only way a breach surfaces is an undistributed
        # remainder (insufficient total headroom).
        if remaining > 0:
            raise errors.budget_would_exceed()

        # Commit the cascade in order (PRD §3.5):
        # 1) one FundAllocation per waterfall line.
        for line in derived_lines:
            alloc = {
                "drawdown_id": dd["id"],
                "restricted_fund_id": line["restricted_fund_id"],
                "amount_cents": line["amount_cents"],
            }
            db.stamp_create_light(alloc)
            db.fund_allocations[alloc["id"]] = alloc
            # 2) increase the fund's allocated_cents.
            fund = db.restricted_funds[line["restricted_fund_id"]]
            fund["allocated_cents"] += line["amount_cents"]
            db.touch(fund)

        # 3) increase the award's federal_drawn_cents.
        award["federal_drawn_cents"] += dd["amount_cents"]
        # 4) increment the award's version.
        db.touch(award)

        dd["status"] = "DISBURSED"
        db.touch(dd)
        return success(_serialize(dd), status=200)


@bp.route("/drawdowns/<dd_id>/return", methods=["POST"])
@require_roles("FinanceOfficer")
def return_drawdown(dd_id, user_id, role):
    with db.LOCK:
        dd = _load(dd_id)
        if dd["status"] != "DISBURSED":
            raise errors.invalid_state("Only a DISBURSED drawdown may be returned.")
        award = db.awards.get(dd["award_id"])

        # Reverse each allocation line into its fund (compensation, PRD §3.5).
        for alloc in db.fund_allocations.values():
            if alloc["drawdown_id"] != dd["id"]:
                continue
            fund = db.restricted_funds.get(alloc["restricted_fund_id"])
            if fund is not None:
                fund["allocated_cents"] -= alloc["amount_cents"]
                db.touch(fund)

        # Reverse the federal-drawn ledger (conserved quantity).
        if award is not None:
            award["federal_drawn_cents"] -= dd["amount_cents"]
            db.touch(award)

        dd["status"] = "RETURNED"
        db.touch(dd)
        return success(_serialize(dd), status=200)
