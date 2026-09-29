"""The logical clock and the two immutable configuration collections."""
from flask import Blueprint

import calc
import serializers
from auth import ALL_ROLES, get_fund_option, require, require_clock_setter
from errors import fail
from response import (collection, created, paginate, query_bool, query_filter,
                      query_int, single)
from store import db
from util import fmt_instant, parse_instant
from validate import parse_body

bp = Blueprint("config", __name__)

CATEGORIES = ("TARGET_DATE", "CAPITAL_PRESERVATION", "EQUITY_INDEX", "BOND_INDEX")
OPTION_STATUSES = ("OPEN", "CLOSED_TO_NEW", "TERMINATED")

DIALS = (
    ("catch_up_limit_cents", 100000),
    ("escalation_increment_bp", 100),
    ("escalation_cap_bp", 800),
    ("escalation_seasoning_days", 180),
    ("opt_out_window_days", 30),
    ("remittance_due_days", 7),
    ("notice_period_days", 90),
    ("sustained_notice_days", 180),
    ("register_penalty_initial_cents_per_employee", 25000),
    ("register_penalty_sustained_cents_per_employee", 50000),
    ("remit_penalty_monthly_rate_bp", 150),
    ("remit_penalty_floor_cents", 10000),
    ("remit_penalty_cap_bp", 5000),
    ("nia_daily_rate_bp", 2),
)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_clock_setter()
    parsed = parse_body({"current_utc": {"type": "str", "required": True}})
    moment = parse_instant(parsed["current_utc"])
    if moment is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 instant")
    db.set_clock(moment)
    return single({"current_utc": fmt_instant(moment)})


# --------------------------------------------------------------- program years

@bp.route("/program-years", methods=["POST"])
def create_program_year():
    require(["ProgramAdministrator"])
    spec = {
        "calendar_year": {"type": "int", "required": True, "min": 2000, "max": 2100},
        "ira_annual_limit_cents": {"type": "int", "required": True, "min": 1},
        "default_contribution_rate_bp": {"type": "int", "required": True, "min": 100, "max": 1500},
        "correction_deadline_month_day": {"type": "str", "default": "04-15"},
    }
    for name, default in DIALS:
        spec[name] = {"type": "int", "default": default, "min": 0}
    parsed = parse_body(spec)
    if calc.find_program_year(parsed["calendar_year"]) is not None:
        fail("ERR_DUPLICATE_PROGRAM_YEAR",
             "a program year already exists for %d" % parsed["calendar_year"])
    row = {"calendar_year": parsed["calendar_year"],
           "ira_annual_limit_cents": parsed["ira_annual_limit_cents"],
           "default_contribution_rate_bp": parsed["default_contribution_rate_bp"],
           "correction_deadline_month_day": parsed["correction_deadline_month_day"]}
    for name, _default in DIALS:
        row[name] = parsed[name]
    db.insert("program_years", row, versioned=False)
    return created(serializers.program_year(row))


@bp.route("/program-years", methods=["GET"])
def list_program_years():
    require(ALL_ROLES)
    year = query_int("calendar_year")
    rows = db.ordered("program_years")
    if year is not None:
        rows = [r for r in rows if r["calendar_year"] == year]
    return paginate(rows, serializers.program_year)


# ----------------------------------------------------------- investment options

def _valid_fund_code(code):
    if not (4 <= len(code) <= 12):
        return False
    return all(character.isdigit() or (character.isalpha() and character.isupper())
               for character in code)


@bp.route("/investment-options", methods=["POST"])
def create_investment_option():
    require(["ProgramAdministrator"])
    parsed = parse_body({
        "fund_code": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "category": {"type": "str", "required": True, "enum": CATEGORIES},
        "expense_ratio_bp": {"type": "int", "required": True, "min": 0, "max": 500},
        "default_eligible": {"type": "bool", "required": True},
        "target_year": {"type": "int", "nullable": True, "min": 2020, "max": 2085},
        "status": {"type": "str", "default": "OPEN", "enum": OPTION_STATUSES},
    })
    if not _valid_fund_code(parsed["fund_code"]):
        fail("ERR_INVALID_REQUEST", "fund_code must be 4 to 12 uppercase alphanumerics")
    target_year = parsed["target_year"]
    if parsed["category"] == "TARGET_DATE":
        if target_year is None:
            fail("ERR_INVALID_REQUEST", "target_year is required when category is TARGET_DATE")
    elif target_year is not None:
        fail("ERR_INVALID_REQUEST", "target_year is only permitted for a TARGET_DATE option")
    for existing in db.investment_options.values():
        if existing["fund_code"] == parsed["fund_code"]:
            fail("ERR_DUPLICATE_FUND_CODE",
                 "fund_code %s is already on the menu" % parsed["fund_code"])
    row = db.insert("investment_options", {
        "fund_code": parsed["fund_code"],
        "name": parsed["name"],
        "category": parsed["category"],
        "target_year": target_year,
        "expense_ratio_bp": parsed["expense_ratio_bp"],
        "default_eligible": parsed["default_eligible"],
        "status": parsed["status"],
    }, versioned=False)
    return created(serializers.investment_option(row))


@bp.route("/investment-options", methods=["GET"])
def list_investment_options():
    require(ALL_ROLES)
    category = query_filter("category", CATEGORIES)
    status = query_filter("status", OPTION_STATUSES)
    default_eligible = query_bool("default_eligible")
    rows = db.ordered("investment_options")
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if default_eligible is not None:
        rows = [r for r in rows if bool(r["default_eligible"]) is default_eligible]
    return paginate(rows, serializers.investment_option)


@bp.route("/investment-options/<option_id>", methods=["GET"])
def read_investment_option(option_id):
    require(ALL_ROLES)
    row = get_fund_option(option_id)
    return single(serializers.investment_option(row))
