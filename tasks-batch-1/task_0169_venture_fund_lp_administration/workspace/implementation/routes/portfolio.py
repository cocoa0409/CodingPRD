"""PortfolioCompany & Investment routes (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import lookup, serialize
import validation as V

bp = Blueprint("portfolio", __name__)

READ_ALL_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer", "LimitedPartnerUser"]
READ_OPS_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer"]


# ---- PortfolioCompany ----
@bp.route("/portfolio-companies", methods=["POST"])
def create_portfolio_company():
    caller = authenticate()
    require_role(caller, ["FundManager"])
    body = V.get_json_body()
    name = V.require_string(body, "name")
    sector = V.require_string(body, "sector")
    with db.lock:
        obj = db.stamp_new(
            {"name": name, "sector": sector, "status": "PROSPECT"}
        )
        db.portfolio_companies[obj["id"]] = obj
    return success(serialize.portfolio_company(obj), status=201)


@bp.route("/portfolio-companies/<pid>", methods=["GET"])
def read_portfolio_company(pid):
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    obj = lookup.get_portfolio_company(pid)
    return success(serialize.portfolio_company(obj))


# ---- Investment ----
@bp.route("/investments", methods=["POST"])
def create_investment():
    caller = authenticate()
    require_role(caller, ["FundManager"])
    body = V.get_json_body()
    fund_id = V.require_string(body, "fund_id")
    portfolio_company_id = V.require_string(body, "portfolio_company_id")
    cost_basis_cents = V.require_int(body, "cost_basis_cents")
    ownership_pct_bps = V.require_int(body, "ownership_pct_bps")

    # Existence/referential: Fund and PortfolioCompany must both exist (422).
    fund = db.funds.get(fund_id)
    company = db.portfolio_companies.get(portfolio_company_id)
    if fund is None or company is None:
        errors.fail(
            errors.ERR_INVALID_REFERENCE,
            "Investment references a non-existent Fund or PortfolioCompany.",
        )

    V.check_range(cost_basis_cents, "cost_basis_cents", lo=1)
    V.check_range(ownership_pct_bps, "ownership_pct_bps", lo=1, hi=10000)

    with db.lock:
        obj = db.stamp_new(
            {
                "fund_id": fund_id,
                "portfolio_company_id": portfolio_company_id,
                "cost_basis_cents": cost_basis_cents,
                "ownership_pct_bps": ownership_pct_bps,
                "status": "ACTIVE",
                "realized_proceeds_cents": 0,
            }
        )
        db.investments[obj["id"]] = obj
        # PortfolioCompany.status -> HELD.
        company["status"] = "HELD"
        db.touch(company)
    return success(serialize.investment(obj), status=201)


@bp.route("/investments/<iid>", methods=["GET"])
def read_investment(iid):
    caller = authenticate()
    require_role(caller, READ_ALL_ROLES)
    obj = lookup.get_investment(iid)
    return success(serialize.investment(obj))


@bp.route("/investments", methods=["GET"])
def list_investments():
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    limit, offset = V.parse_pagination()
    fund_id = request.args.get("fund_id")
    portfolio_company_id = request.args.get("portfolio_company_id")
    status = request.args.get("status")
    items = list(db.investments.values())
    if fund_id is not None:
        items = [i for i in items if i["fund_id"] == fund_id]
    if portfolio_company_id is not None:
        items = [i for i in items if i["portfolio_company_id"] == portfolio_company_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.investment(o) for o in page], pagination=meta)


@bp.route("/investments/<iid>/realize", methods=["POST"])
def realize_investment(iid):
    caller = authenticate()
    require_role(caller, ["FundManager"])
    body = V.get_json_body()
    realized_proceeds_cents = V.require_int(body, "realized_proceeds_cents")
    with db.lock:
        inv = lookup.get_investment(iid)
        if inv["status"] != "ACTIVE":
            errors.fail(errors.ERR_INVALID_STATE, "Investment is not ACTIVE.")
        V.check_range(realized_proceeds_cents, "realized_proceeds_cents", lo=0)
        inv["status"] = "REALIZED"
        inv["realized_proceeds_cents"] = realized_proceeds_cents
        db.touch(inv)
        # Owning company HELD -> EXITED.
        company = db.portfolio_companies.get(inv["portfolio_company_id"])
        if company:
            company["status"] = "EXITED"
            db.touch(company)
    return success(serialize.investment(inv))
