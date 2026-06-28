"""Program and InvestmentOption routes."""
from flask import Blueprint

from db import db, stamp_new
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from routes.common import (
    get_body, find_or_404, require_string, require_int, optional_int,
    optional_number, optional_bool, require_enum, paginate,
)

bp = Blueprint("config", __name__)

RISK_TIERS = {"CONSERVATIVE", "MODERATE", "AGGRESSIVE", "CASH"}
ALL_ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative"}


@bp.post("/able/programs")
def create_program():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    body = get_body()
    require_string(body, "name")
    require_string(body, "state_code")
    require_int(body, "annual_contribution_cap_cents")
    require_int(body, "able_to_work_fpl_cents")
    require_int(body, "program_fee_bps")
    p = {
        "name": body["name"],
        "state_code": body["state_code"],
        "annual_contribution_cap_cents": body["annual_contribution_cap_cents"],
        "able_to_work_fpl_cents": body["able_to_work_fpl_cents"],
        "ssi_suspension_threshold_cents": optional_int(body, "ssi_suspension_threshold_cents", 10000000),
        "ssi_resource_limit_cents": optional_int(body, "ssi_resource_limit_cents", 200000),
        "program_fee_bps": body["program_fee_bps"],
        "nonqualified_additional_tax_pct": optional_number(body, "nonqualified_additional_tax_pct", 0.10),
        "max_investment_changes_per_year": optional_int(body, "max_investment_changes_per_year", 2),
        "disability_onset_max_age": optional_int(body, "disability_onset_max_age", 26),
    }
    stamp_new(p)
    db.programs[p["id"]] = p
    return created(domain.serialize_program(p))


@bp.get("/able/programs/<pid>")
def get_program(pid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    p = find_or_404(db.programs, pid, "Program")
    return ok(domain.serialize_program(p))


@bp.post("/able/investment-options")
def create_investment_option():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    body = get_body()
    require_string(body, "program_id")
    require_string(body, "name")
    require_enum(body, "risk_tier", RISK_TIERS)
    # FK existence (path-style referential): program must exist
    find_or_404(db.programs, body["program_id"], "Program")
    o = {
        "program_id": body["program_id"],
        "name": body["name"],
        "risk_tier": body["risk_tier"],
        "is_open": optional_bool(body, "is_open", True),
    }
    stamp_new(o)
    db.investment_options[o["id"]] = o
    return created(domain.serialize_investment_option(o))


@bp.get("/able/investment-options/<oid>")
def get_investment_option(oid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    o = find_or_404(db.investment_options, oid, "InvestmentOption")
    return ok(domain.serialize_investment_option(o))


@bp.get("/able/investment-options")
def list_investment_options():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    from flask import request
    program_id = request.args.get("program_id")
    items = list(db.investment_options.values())
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_investment_option(o) for o in page],
                   limit, offset, total)
