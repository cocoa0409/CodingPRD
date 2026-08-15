from datetime import timedelta
from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, resolve,
                   active_ips_of_client, is_restricted, expire_proposal,
                   cancel_open_trades, PROPOSAL_TTL_DAYS,
                   OPEN_PROPOSAL_STATES)
from logic2 import generate_proposal_totals, execute_proposal
from serialize import proposal_out
from validate import body, no_unknown, req_str, req_int, req_enum, pagination

bp = Blueprint("proposals", __name__)

TRIGGER_TYPES = {"DRIFT_BREACH", "CASH_FLOW", "MANUAL"}


def _pin_check(prop):
    ips = db.ips_policies[prop["ips_id"]]
    if ips["status"] != "ACTIVE" or prop["pinned_ips_version"] != ips["version"]:
        raise ApiError("ERR_PROPOSAL_STALE_PIN", 422,
                       "Pinned IPS is no longer ACTIVE or its version advanced")


def _require_active_portfolio(prop):
    pf = db.portfolios[prop["portfolio_id"]]
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_NOT_ACTIVE", 409,
                       "Portfolio must be ACTIVE")
    return pf


@bp.post("/advisory/rebalance-proposals")
def create_proposal():
    authorize("Advisor")
    b = body()
    no_unknown(b, {"portfolio_id", "trigger_type", "expected_portfolio_version"})
    portfolio_id = req_str(b, "portfolio_id")
    trigger_type = req_enum(b, "trigger_type", TRIGGER_TYPES)
    expected_version = req_int(b, "expected_portfolio_version")
    pf = resolve(db.portfolios, portfolio_id, "portfolio_id")
    if pf["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_PORTFOLIO_NOT_ACTIVE", 409,
                       "Proposal generation requires an ACTIVE portfolio")
    # OCC fires (priority 8) before the drift-breach requirement (priority 11).
    if expected_version != pf["version"]:
        raise ApiError("ERR_STALE_PORTFOLIO_VERSION", 412,
                       "expected_portfolio_version does not match current version")
    if trigger_type == "DRIFT_BREACH" and pf["drift_status"] != "BREACHED":
        raise ApiError("ERR_DRIFT_NOT_BREACHED", 422,
                       "DRIFT_BREACH generation requires drift_status BREACHED")
    ips = active_ips_of_client(pf["client_id"])
    # Create-with-supersede: earlier PROPOSED/NEEDS_REVISION proposals expire.
    for other in list(db.proposals.values()):
        if (other["portfolio_id"] == portfolio_id
                and other["status"] in OPEN_PROPOSAL_STATES):
            expire_proposal(other)
    prop = new_common()
    prop.update({
        "portfolio_id": portfolio_id, "trigger_type": trigger_type,
        "status": "PROPOSED", "ips_id": ips["id"],
        "pinned_ips_version": ips["version"],
        "generated_at_dt": clock.now(),
        "expires_at_dt": clock.now() + timedelta(days=PROPOSAL_TTL_DAYS),
        "total_buys_cents": 0, "total_sells_cents": 0,
        "est_tax_reserve_cents": 0, "cash_delta_cents": 0,
        "decided_by_user_id": None,
    })
    db.proposals[prop["id"]] = prop
    generate_proposal_totals(prop, pf)
    touch(pf)   # generation increments the portfolio's version
    return obj(proposal_out(prop), 201)


@bp.get("/advisory/rebalance-proposals")
def list_proposals():
    authorize("Advisor", "ComplianceOfficer")
    limit, offset = pagination()
    rows = sorted(db.proposals.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    pf_id = request.args.get("portfolio_id")
    if pf_id is not None:
        rows = [p for p in rows if p["portfolio_id"] == pf_id]
    ips_id = request.args.get("ips_id")
    if ips_id is not None:
        rows = [p for p in rows if p["ips_id"] == ips_id]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    total = len(rows)
    return page([proposal_out(p) for p in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/rebalance-proposals/<pid>")
def get_proposal(pid):
    authorize("Advisor", "ComplianceOfficer")
    prop = get_or_404(db.proposals, pid)
    return obj(proposal_out(prop))


@bp.post("/advisory/rebalance-proposals/<pid>/approve")
def approve_proposal(pid):
    uid, _ = authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    prop = get_or_404(db.proposals, pid)
    if prop["status"] != "PROPOSED":
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Approval requires PROPOSED")
    _require_active_portfolio(prop)
    _pin_check(prop)
    # Compliance scan: restricted-side or non-LISTED pending trades -> BLOCKED.
    for t in db.trades.values():
        if t["proposal_id"] != pid or t["status"] != "PENDING":
            continue
        sec = db.securities[t["security_id"]]
        if is_restricted(sec["id"], t["side"]) or sec["trading_status"] != "LISTED":
            t["status"] = "BLOCKED"
            touch(t)
    prop["status"] = "APPROVED"
    prop["decided_by_user_id"] = uid
    touch(prop)
    return obj(proposal_out(prop))


@bp.post("/advisory/rebalance-proposals/<pid>/request-changes")
def request_changes(pid):
    uid, _ = authorize("ComplianceOfficer")
    if request.data:
        b = body()
        no_unknown(b, {"reason"})
        if "reason" in b and b["reason"] is not None and not isinstance(b["reason"], str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    prop = get_or_404(db.proposals, pid)
    if prop["status"] != "PROPOSED":
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Request-changes requires PROPOSED")
    prop["status"] = "NEEDS_REVISION"
    prop["decided_by_user_id"] = uid
    touch(prop)
    return obj(proposal_out(prop))


@bp.post("/advisory/rebalance-proposals/<pid>/revise")
def revise_proposal(pid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    prop = get_or_404(db.proposals, pid)
    if prop["status"] != "NEEDS_REVISION":
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Revise requires NEEDS_REVISION")
    pf = _require_active_portfolio(prop)
    if prop["trigger_type"] == "DRIFT_BREACH" and pf["drift_status"] != "BREACHED":
        raise ApiError("ERR_DRIFT_NOT_BREACHED", 422,
                       "DRIFT_BREACH revision requires drift_status BREACHED")
    cancel_open_trades(prop)
    generate_proposal_totals(prop, pf)      # regenerate at current prices
    ips = db.ips_policies[prop["ips_id"]]
    prop["pinned_ips_version"] = ips["version"]
    prop["expires_at_dt"] = clock.now() + timedelta(days=PROPOSAL_TTL_DAYS)
    prop["status"] = "PROPOSED"
    touch(prop)
    return obj(proposal_out(prop))


@bp.post("/advisory/rebalance-proposals/<pid>/reject")
def reject_proposal(pid):
    uid, _ = authorize("ComplianceOfficer")
    if request.data:
        b = body()
        no_unknown(b, {"reason"})
        if "reason" in b and b["reason"] is not None and not isinstance(b["reason"], str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    prop = get_or_404(db.proposals, pid)
    if prop["status"] not in ("PROPOSED", "NEEDS_REVISION"):
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Reject requires PROPOSED or NEEDS_REVISION")
    cancel_open_trades(prop)
    prop["status"] = "REJECTED"
    prop["decided_by_user_id"] = uid
    touch(prop)
    return obj(proposal_out(prop))


@bp.post("/advisory/rebalance-proposals/<pid>/cancel")
def cancel_proposal(pid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    prop = get_or_404(db.proposals, pid)
    if prop["status"] not in ("PROPOSED", "NEEDS_REVISION"):
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Cancel requires PROPOSED or NEEDS_REVISION")
    cancel_open_trades(prop)
    prop["status"] = "CANCELLED"
    touch(prop)
    return obj(proposal_out(prop))


@bp.post("/advisory/rebalance-proposals/<pid>/execute")
def execute(pid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    prop = get_or_404(db.proposals, pid)
    if prop["status"] != "APPROVED":
        raise ApiError("ERR_PROPOSAL_INVALID_STATE", 409,
                       "Execution requires APPROVED")
    pf = _require_active_portfolio(prop)
    trades = [t for t in db.trades.values() if t["proposal_id"] == pid]
    if any(t["status"] == "BLOCKED" for t in trades):
        raise ApiError("ERR_TRADES_BLOCKED", 409,
                       "Proposal has BLOCKED trades")
    # Compliance gates re-examine each pending trade.
    for t in sorted((t for t in trades if t["status"] == "PENDING"),
                    key=lambda t: t["_seq"]):
        if is_restricted(t["security_id"], t["side"]):
            raise ApiError("ERR_SECURITY_RESTRICTED", 422,
                           "An ACTIVE restriction blocks this trade's side")
        if db.securities[t["security_id"]]["trading_status"] != "LISTED":
            raise ApiError("ERR_SECURITY_NOT_TRADEABLE", 422,
                           "Security is not LISTED")
    _pin_check(prop)
    execute_proposal(prop, pf)
    return obj(proposal_out(prop))
