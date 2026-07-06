"""InvestmentPolicyStatement endpoints & approval state machine (PRD §3.2)."""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from util import body, require_str, require_pct, opt_pos_int, require_enum, pagination, paginate

bp = Blueprint("ips", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
ACTIONS = {"PROPOSE", "REQUEST_CHANGES", "APPROVE"}


def serialize(i):
    return {
        "id": i["id"],
        "client_id": i["client_id"],
        "target_portfolio_id": i["target_portfolio_id"],
        "max_equity_pct": i["max_equity_pct"],
        "drift_tolerance_bps": i["drift_tolerance_bps"],
        "revision_round": i["revision_round"],
        "approved_by_user_id": i["approved_by_user_id"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


@bp.route("/investment-policy-statements", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    client_id = require_str(data, "client_id")
    target_portfolio_id = require_str(data, "target_portfolio_id")
    max_equity_pct = require_pct(data, "max_equity_pct")
    drift_tolerance_bps = opt_pos_int(data, "drift_tolerance_bps", 500)
    ref_or_422(db.clients, client_id, "client_id")
    ref_or_422(db.portfolios, target_portfolio_id, "target_portfolio_id")
    i = {
        "client_id": client_id,
        "target_portfolio_id": target_portfolio_id,
        "max_equity_pct": max_equity_pct,
        "drift_tolerance_bps": drift_tolerance_bps,
        "revision_round": 0,
        "approved_by_user_id": None,
        "proposing_advisor_id": None,
        "status": "DRAFT",
    }
    stamp_new(i)
    db.investment_policy_statements[i["id"]] = i
    return created(serialize(i))


@bp.route("/investment-policy-statements/<iid>", methods=["GET"])
def read(iid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    i = get_or_404(db.investment_policy_statements, iid)
    return ok(serialize(i))


@bp.route("/investment-policy-statements", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    client_id = request.args.get("client_id")
    target_portfolio_id = request.args.get("target_portfolio_id")
    items = list(db.investment_policy_statements.values())
    if client_id is not None:
        items = [x for x in items if x["client_id"] == client_id]
    if target_portfolio_id is not None:
        items = [x for x in items if x["target_portfolio_id"] == target_portfolio_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/investment-policy-statements/<iid>/state", methods=["POST"])
def state(iid):
    user_id, role = authenticate()
    authorize(role, {"Advisor", "ComplianceOfficer"})
    i = get_or_404(db.investment_policy_statements, iid)
    data = body()
    action = require_enum(data, "action", ACTIONS)

    if action == "PROPOSE":
        # Actor: Advisor
        authorize(role, {"Advisor"})
        if i["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "PROPOSE requires DRAFT")
        # duplicate guard: only one PROPOSED in flight per client
        dup = any(
            x["client_id"] == i["client_id"] and x["status"] == "PROPOSED" and x["id"] != iid
            for x in db.investment_policy_statements.values()
        )
        if dup:
            raise err("ERR_DUPLICATE_APPROVED_IPS",
                      "Client already has a PROPOSED policy statement in flight")
        portfolio = db.portfolios.get(i["target_portfolio_id"])
        # portfolio must still exist & be published; mandate check
        if portfolio is None or not portfolio["is_published"]:
            raise err("ERR_PORTFOLIO_NOT_PUBLISHED", "Target portfolio is not published")
        if i["max_equity_pct"] < portfolio["model_equity_pct"]:
            raise err("ERR_IPS_MANDATE_VIOLATION",
                      "max_equity_pct below target portfolio model_equity_pct")
        i["proposing_advisor_id"] = user_id
        i["status"] = "PROPOSED"

    elif action == "REQUEST_CHANGES":
        authorize(role, {"ComplianceOfficer"})
        if i["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "REQUEST_CHANGES requires PROPOSED")
        i["revision_round"] += 1
        i["status"] = "DRAFT"

    elif action == "APPROVE":
        authorize(role, {"ComplianceOfficer"})
        if i["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "APPROVE requires PROPOSED")
        # segregation of duties (priority 6)
        if user_id == i.get("proposing_advisor_id"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Approver must differ from the proposing advisor")
        i["approved_by_user_id"] = user_id
        i["status"] = "APPROVED"
        # supersede any other APPROVED IPS for the same client
        for other in db.investment_policy_statements.values():
            if (other["id"] != iid and other["client_id"] == i["client_id"]
                    and other["status"] == "APPROVED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        # spawn IPS_ARCHIVE compliance item
        from routes.compliance import make_item
        make_item("CLIENT", i["client_id"], "IPS_ARCHIVE", due_date=None)

    touch(i)
    return ok(serialize(i))
