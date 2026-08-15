"""CreditBalanceLedger, CreditBalanceElection, ContributionDemand, and
ContributionPayment endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, parse_iso
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import (
    invalid_state, plan_terminated, validation, not_found, stale_version, ApiError,
    ERR_ELECTION_WINDOW_CONFLICT, ERR_CREDIT_BALANCE_EXCEEDED, ERR_OVERPAYMENT,
    ERR_REVOCATION_WINDOW_EXPIRED,
)
from validate import body_of, req_str, req_num
from services.core import (
    base_record, touch, public, get_plan, get_election, get_demand, get_run,
    ledger_for_plan, recompute_demand, waterfall_draw, waterfall_restore,
    effective_elections, r2d, D, fmt_ts,
)

bp = Blueprint("funding", __name__)

READ_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor"]


def _plan_active_gate(plan):
    if plan["status"] != "ACTIVE":
        raise plan_terminated()


# ---------------------------------------------------------------------------
# CreditBalanceLedger (1:1 sub-resource, array of 0-1)
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/credit-balance-ledger", methods=["GET"])
def get_credit_balance_ledger(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    ledger = ledger_for_plan(plan["id"])
    items = [ledger] if ledger is not None else []
    page, total = list_page(items, limit, offset)
    return success_list([public(l) for l in page], limit, offset, total)


# ---------------------------------------------------------------------------
# CreditBalanceElection
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/credit-balance-elections", methods=["POST"])
def create_election(plan_id):
    require_roles(["PlanAdmin"])
    plan = get_plan(plan_id)
    body = body_of(request)

    # body-referenced demand must exist and belong to this plan (existence)
    demand_id = body.get("contribution_demand_id")
    demand = None
    if isinstance(demand_id, str):
        demand = store.contribution_demands.get(demand_id)
        if demand is None or demand["plan_id"] != plan["id"]:
            raise not_found("ContributionDemand not found")

    # priority 4: from-state — elections only against OPEN/PARTIALLY_SATISFIED/DELINQUENT
    if demand is not None and demand["status"] == "SATISFIED":
        raise invalid_state("ContributionDemand is SATISFIED")

    # priority 5: plan-active gate
    _plan_active_gate(plan)

    # OCC: expected_plan_version == Plan.version
    epv = body.get("expected_plan_version")
    if epv is not None:
        if isinstance(epv, bool) or not isinstance(epv, int):
            raise validation("expected_plan_version must be an integer")
        if epv != plan["version"]:
            raise stale_version()

    # priority 10: another EFFECTIVE election on the same demand with its
    # revocation window [created_at, created_at+21d) still open blocks creation
    if demand is not None:
        now = store.now()
        for e in effective_elections(demand["id"]):
            if now < parse_iso(e["revoke_deadline"]):
                raise ApiError(
                    ERR_ELECTION_WINDOW_CONFLICT, 409,
                    "Another EFFECTIVE election's revocation window is still open",
                )

    # priority 20: fiscal ceilings — pool capacity and demand outstanding
    amount_raw = body.get("amount")
    if demand is not None and isinstance(amount_raw, (int, float)) and not isinstance(amount_raw, bool):
        amount = r2d(amount_raw)
        ledger = ledger_for_plan(plan["id"])
        pool = r2d(ledger["carryover_balance"]) + r2d(ledger["prefunding_balance"]) if ledger else Decimal("0.00")
        outstanding = r2d(demand["outstanding_amount"])
        if amount > pool:
            raise ApiError(ERR_CREDIT_BALANCE_EXCEEDED, 422, "Election amount exceeds the available credit balances")
        if amount > outstanding:
            raise ApiError(ERR_CREDIT_BALANCE_EXCEEDED, 422, "Election amount exceeds the demand's outstanding_amount")

    # priority 22: body well-formedness
    demand_id = req_str(body, "contribution_demand_id")
    if demand is None:
        demand = store.contribution_demands.get(demand_id)
        if demand is None or demand["plan_id"] != plan["id"]:
            raise not_found("ContributionDemand not found")
        if demand["status"] == "SATISFIED":
            raise invalid_state("ContributionDemand is SATISFIED")
    amount = req_num(body, "amount")
    if amount <= 0:
        raise validation("amount must be > 0")
    if epv is None:
        raise validation("Missing required field: expected_plan_version")
    amount = r2d(amount)

    # forward waterfall draw
    ledger = ledger_for_plan(plan["id"])
    from_carryover, from_prefunding = waterfall_draw(ledger, amount)

    rec = base_record()
    deadline = store.now() + timedelta(days=21)
    rec.update({
        "plan_id": plan["id"],
        "contribution_demand_id": demand["id"],
        "amount": float(amount),
        "status": "EFFECTIVE",
        "revoke_deadline": fmt_ts(deadline),
        "_draw_carryover": float(from_carryover),
        "_draw_prefunding": float(from_prefunding),
    })
    store.credit_balance_elections[rec["id"]] = rec

    # side effects: plan version increment + demand recompute/auto-transition
    touch(plan)
    recompute_demand(demand)
    touch(demand)

    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/credit-balance-elections", methods=["GET"])
def list_elections(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [e for e in store.credit_balance_elections.values() if e["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


@bp.route("/v1/credit-balance-elections/<election_id>/revoke", methods=["POST"])
def revoke_election(election_id):
    require_roles(["PlanAdmin"])
    election = get_election(election_id)
    # priority 4: from-state
    if election["status"] != "EFFECTIVE":
        raise invalid_state("CreditBalanceElection is not EFFECTIVE")
    plan = store.plans.get(election["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # priority 9: logical clock strictly before revoke_deadline
    if not (store.now() < parse_iso(election["revoke_deadline"])):
        raise ApiError(ERR_REVOCATION_WINDOW_EXPIRED, 422, "Revocation window has expired")

    election["status"] = "REVOKED"
    touch(election)

    # reverse waterfall pass restores pools in the recorded proportions
    ledger = ledger_for_plan(election["plan_id"])
    if ledger is not None:
        waterfall_restore(
            ledger,
            election.get("_draw_carryover", 0.0),
            election.get("_draw_prefunding", 0.0),
            election["amount"],
        )

    # recompute the demand; may exit SATISFIED as compensation
    demand = store.contribution_demands.get(election["contribution_demand_id"])
    if demand is not None:
        recompute_demand(demand)
        touch(demand)

    return success_object(public(election))


# ---------------------------------------------------------------------------
# ContributionDemand
# ---------------------------------------------------------------------------

@bp.route("/v1/contribution-demands/<demand_id>", methods=["GET"])
def fetch_demand(demand_id):
    require_roles(READ_ROLES)
    demand = get_demand(demand_id)
    return success_object(public(demand))


@bp.route("/v1/plans/<plan_id>/contribution-demands", methods=["GET"])
def list_demands_by_plan(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [d for d in store.contribution_demands.values() if d["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(d) for d in page], limit, offset, total)


@bp.route("/v1/valuation-runs/<run_id>/contribution-demands", methods=["GET"])
def list_demands_by_run(run_id):
    require_roles(READ_ROLES)
    run = get_run(run_id)
    limit, offset = parse_pagination(request.args)
    items = [d for d in store.contribution_demands.values() if d["valuation_run_id"] == run["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(d) for d in page], limit, offset, total)


@bp.route("/v1/contribution-demands/<demand_id>/elections", methods=["GET"])
def list_demand_elections(demand_id):
    require_roles(READ_ROLES)
    demand = get_demand(demand_id)
    limit, offset = parse_pagination(request.args)
    items = [e for e in store.credit_balance_elections.values() if e["contribution_demand_id"] == demand["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# ContributionPayment (immutable event: id + created_at only)
# ---------------------------------------------------------------------------

@bp.route("/v1/contribution-demands/<demand_id>/payments", methods=["POST"])
def create_payment(demand_id):
    require_roles(["PlanAdmin"])
    demand = get_demand(demand_id)
    # priority 4: paying a SATISFIED demand is a state error (beats overpayment)
    if demand["status"] == "SATISFIED":
        raise invalid_state("ContributionDemand is SATISFIED")
    plan = store.plans.get(demand["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    body = body_of(request)

    # priority 21: overpayment
    amount_raw = body.get("amount")
    if isinstance(amount_raw, (int, float)) and not isinstance(amount_raw, bool):
        if r2d(amount_raw) > r2d(demand["outstanding_amount"]):
            raise ApiError(ERR_OVERPAYMENT, 422, "Payment amount exceeds outstanding_amount")

    # priority 22: body well-formedness
    amount = req_num(body, "amount")
    if amount <= 0:
        raise validation("amount must be > 0")
    paid_on = req_str(body, "paid_on")
    try:
        from datetime import datetime as _dt
        parse_iso(paid_on) if "T" in paid_on else _dt.fromisoformat(paid_on)
    except Exception:
        raise validation("paid_on must be an ISO 8601 date or datetime")

    from db import new_id
    rec = {
        "id": new_id(),
        "created_at": store.now_str(),
        "_seq": store.next_seq(),
        "contribution_demand_id": demand["id"],
        "amount": float(r2d(amount)),
        "paid_on": paid_on,
    }
    store.contribution_payments[rec["id"]] = rec

    recompute_demand(demand)
    touch(demand)
    return success_object(public(rec), status=201)


@bp.route("/v1/contribution-demands/<demand_id>/payments", methods=["GET"])
def list_payments(demand_id):
    require_roles(READ_ROLES)
    demand = get_demand(demand_id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.contribution_payments.values() if p["contribution_demand_id"] == demand["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(p) for p in page], limit, offset, total)
