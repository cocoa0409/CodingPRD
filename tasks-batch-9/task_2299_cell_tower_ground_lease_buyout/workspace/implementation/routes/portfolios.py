"""Portfolios and the capital ledger (PRD 3.1)."""

from flask import Blueprint

import engine as E
import validate as V
from auth import principal
from db import db
from errors import fail
from response import created, ok, ok_list

bp = Blueprint("portfolios", __name__)

POSTURES = ("OPEN", "CONSTRAINED", "FROZEN")
COMPLIANCE = ("COMPLIANT", "BORROWING_BASE_DEFICIT")

READ_ROLES = ("PlatformAdmin", "PortfolioManager", "AcquisitionAnalyst", "TreasuryOfficer")
FACILITY_READ_ROLES = ("TreasuryOfficer", "PortfolioManager", "PlatformAdmin")


@bp.post("/portfolios")
def create_portfolio():
    principal("PlatformAdmin")
    b = V.body()
    name = V.req_str(b, "name")
    program_code = V.req_str(b, "program_code")
    total = V.req_int(b, "total_capital_cents", minimum=0)

    portfolio = E.new_entity(
        name=name,
        program_code=program_code,
        total_capital_cents=total,
        committed_capital_cents=0,
        deployed_capital_cents=0,
        available_capital_cents=total,
        utilization_bps=0,
        capital_posture="OPEN",
        active_deal_count=0,
    )
    db.portfolios[portfolio["id"]] = portfolio
    return created(E.portfolio_json(portfolio))


@bp.get("/portfolios")
def list_portfolios():
    principal(*READ_ROLES)
    limit, offset = V.pagination()
    posture = V.enum_filter("capital_posture", POSTURES)
    rows = E.ordered(list(db.portfolios.values()))
    if posture is not None:
        rows = [r for r in rows if r["capital_posture"] == posture]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.portfolio_json(r) for r in page], total, limit, offset)


@bp.get("/portfolios/<pid>")
def get_portfolio(pid):
    principal(*READ_ROLES)
    portfolio = E.find("portfolios", pid, "ERR_PORTFOLIO_NOT_FOUND")
    return ok(E.portfolio_json(portfolio))


@bp.post("/portfolios/<pid>/capital-adjustments")
def adjust_capital(pid):
    principal("PlatformAdmin")
    portfolio = E.find("portfolios", pid, "ERR_PORTFOLIO_NOT_FOUND")
    b = V.body()
    delta = V.req_int(b, "delta_cents")
    V.req_str(b, "memo")

    if delta < 0 and -delta > portfolio["available_capital_cents"]:
        fail("ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE")

    portfolio["total_capital_cents"] = portfolio["total_capital_cents"] + delta
    E.touch(portfolio)
    E.recompute_portfolio(portfolio)
    return ok(E.portfolio_json(portfolio))


@bp.get("/portfolios/<pid>/financing-facilities")
def list_portfolio_facilities(pid):
    principal(*FACILITY_READ_ROLES)
    portfolio = E.find("portfolios", pid, "ERR_PORTFOLIO_NOT_FOUND")
    limit, offset = V.pagination()
    state = V.enum_filter("compliance_state", COMPLIANCE)
    rows = [f for f in E.ordered(list(db.facilities.values()))
            if f["portfolio_id"] == portfolio["id"]]
    if state is not None:
        rows = [r for r in rows if r["compliance_state"] == state]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.facility_json(r) for r in page], total, limit, offset)
