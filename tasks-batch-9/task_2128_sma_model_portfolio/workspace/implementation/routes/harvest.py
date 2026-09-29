"""HarvestProposal routes (PRD 3.8)."""

from flask import Blueprint, g

from core import (
    ApiError, READ_ROLES, ROLE_COMPLIANCE_OFFICER, ROLE_PORTFOLIO_MANAGER,
    arg, body_json, clock, db, lookup, new_row, ok, paged, qfilter,
    require_roles, serialize, touch, v_int, v_str,
)
from calc import (
    apply_hifo_plan, hifo_plan, plan_loss_figures, wash_lookback_conflict,
)
from entities import guard_not_suspended, guard_not_written_off, serialize_account

bp = Blueprint("harvest", __name__)


def _budget_guard(account, loss_cents):
    """Ladder rung 26."""
    if not account.get("tax_overlay_enabled"):
        raise ApiError("ERR_HARVEST_BUDGET_EXCEEDED",
                       "The account does not have the tax overlay enabled.")
    if account["realized_loss_ytd_cents"] + loss_cents > account["harvest_budget_cents"]:
        raise ApiError("ERR_HARVEST_BUDGET_EXCEEDED",
                       "The harvest would exceed the account's annual budget.")


@bp.post("/sma/harvest-proposals")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def create_proposal():
    body = body_json()

    # Rung 6: body reference existence, in declared input order.
    account = None
    security = None
    replacement = None
    if isinstance(body.get("account_id"), str):
        account = lookup(db.accounts, body["account_id"], "ERR_ACCOUNT_NOT_FOUND")
    if isinstance(body.get("security_id"), str):
        security = lookup(db.securities, body["security_id"], "ERR_SECURITY_NOT_FOUND")
    if isinstance(body.get("replacement_security_id"), str):
        replacement = lookup(db.securities, body["replacement_security_id"],
                             "ERR_SECURITY_NOT_FOUND")

    # Rung 7: request shape.
    v_str(body, "account_id")
    v_str(body, "security_id")
    shares = v_int(body, "shares", minimum=1)
    replacement_security_id = None
    if body.get("replacement_security_id") is not None:
        replacement_security_id = v_str(body, "replacement_security_id")
    expected = v_int(body, "expected_account_version")

    # Rung 8: optimistic concurrency on the parent Account.
    if expected != account["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "The account has advanced since it was last observed.")

    # Rungs 9 / 10.
    guard_not_suspended(account)
    guard_not_written_off(account)

    # Rung 14: wash-sale coordination.
    if replacement_security_id is not None and replacement_security_id == security["id"]:
        raise ApiError("ERR_WASH_SALE_WINDOW_CONFLICT",
                       "The replacement security may not be the harvested security.")
    if wash_lookback_conflict(account["id"], security["id"]):
        raise ApiError("ERR_WASH_SALE_WINDOW_CONFLICT",
                       "A TRADE-origin lot was acquired inside the wash-sale lookback window.")

    # Rung 25: the HIFO walk must complete.
    quoted_price_cents = security["last_price_cents"]
    plan = hifo_plan(account["id"], security["id"], shares, quoted_price_cents)
    target_loss_cents, proposed_loss_cents = plan_loss_figures(plan)

    # Rung 26: harvest budget.
    _budget_guard(account, proposed_loss_cents)

    row = new_row(
        account_id=account["id"],
        security_id=security["id"],
        replacement_security_id=replacement_security_id,
        shares=shares,
        status="PROPOSED",
        quoted_price_cents=quoted_price_cents,
        target_loss_cents=target_loss_cents,
        proposed_loss_cents=proposed_loss_cents,
        realized_loss_cents=None,
        approved_by_user_id=None,
        rejection_note=None,
        executed_at=None,
    )

    for existing in db.harvest_proposals.values():
        if (existing["account_id"] == account["id"]
                and existing["security_id"] == security["id"]
                and existing["status"] == "PROPOSED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    db.harvest_proposals[row["id"]] = row
    touch(account)
    return ok(serialize(row), 201)


@bp.get("/sma/harvest-proposals/<harvest_proposal_id>")
@require_roles(*READ_ROLES)
def get_proposal(harvest_proposal_id):
    row = lookup(db.harvest_proposals, harvest_proposal_id, "ERR_HARVEST_PROPOSAL_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/harvest-proposals")
@require_roles(*READ_ROLES)
def list_proposals():
    rows = qfilter(db.harvest_proposals.values(),
                   account_id=arg("account_id"),
                   security_id=arg("security_id"),
                   replacement_security_id=arg("replacement_security_id"),
                   status=arg("status"))
    return paged(rows)


@bp.post("/sma/harvest-proposals/<harvest_proposal_id>/approve")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def approve_proposal(harvest_proposal_id):
    proposal = lookup(db.harvest_proposals, harvest_proposal_id, "ERR_HARVEST_PROPOSAL_NOT_FOUND")
    account = db.accounts.get(proposal["account_id"])
    if account is not None:
        guard_not_suspended(account)
    if proposal["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PROPOSED harvest may be approved.")
    proposal["status"] = "APPROVED"
    proposal["approved_by_user_id"] = g.user_id
    touch(proposal)
    return ok(serialize(proposal))


@bp.post("/sma/harvest-proposals/<harvest_proposal_id>/reject")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def reject_proposal(harvest_proposal_id):
    proposal = lookup(db.harvest_proposals, harvest_proposal_id, "ERR_HARVEST_PROPOSAL_NOT_FOUND")
    body = body_json()
    rejection_note = v_str(body, "rejection_note")
    if proposal["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PROPOSED harvest may be rejected.")
    proposal["status"] = "REJECTED"
    proposal["rejection_note"] = rejection_note
    touch(proposal)
    return ok(serialize(proposal))


@bp.post("/sma/harvest-proposals/<harvest_proposal_id>/execute")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def execute_proposal(harvest_proposal_id):
    proposal = lookup(db.harvest_proposals, harvest_proposal_id, "ERR_HARVEST_PROPOSAL_NOT_FOUND")
    account = db.accounts.get(proposal["account_id"])
    if account is not None:
        guard_not_suspended(account)
    if proposal["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED harvest may be executed.")

    security = db.securities.get(proposal["security_id"])
    price = security["last_price_cents"] if security else 0

    # Rung 25: re-evaluated HIFO walk against the current ledger.
    plan = hifo_plan(account["id"], proposal["security_id"], proposal["shares"], price)
    _target, realized_loss_cents = plan_loss_figures(plan)

    # Rung 26: harvest budget re-check.
    _budget_guard(account, realized_loss_cents)

    apply_hifo_plan(account, plan, closing_trade_order_id=None)
    account["cash_cents"] += proposal["shares"] * price
    account["realized_loss_ytd_cents"] += realized_loss_cents
    touch(account)

    proposal["status"] = "EXECUTED"
    proposal["realized_loss_cents"] = realized_loss_cents
    proposal["executed_at"] = clock()
    touch(proposal)
    return ok(serialize(proposal))
