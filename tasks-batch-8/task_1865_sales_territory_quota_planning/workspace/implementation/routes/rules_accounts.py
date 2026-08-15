"""AssignmentRule, Account, SalesRep, RampSchedule endpoints."""
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  opt_string, req_int, opt_int, req_enum, parse_date,
                  find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("rules_accounts", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")
SEGMENTS = ("ENTERPRISE", "MID_MARKET", "SMB")


# ---------------------------------------------------------------------------
# AssignmentRule
# ---------------------------------------------------------------------------

@bp.route("/sales-planning/assignment-rules", methods=["POST"])
def create_rule():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "rule_type", "priority", "territory_id",
                                 "country_code", "state_code", "segment", "named_account_id"})
    require_fields(body, ["plan_year_id", "rule_type", "priority", "territory_id"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    rule_type = req_enum(body, "rule_type", ("NAMED_ACCOUNT", "GEO_SEGMENT"))
    priority = req_int(body, "priority")
    territory_id = req_string(body, "territory_id")

    country = body.get("country_code")
    state = body.get("state_code")
    segment = body.get("segment")
    named_account_id = body.get("named_account_id")

    # Conditional field rules (ERR_INVALID_REQUEST)
    if rule_type == "NAMED_ACCOUNT":
        if named_account_id is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "named_account_id is required for NAMED_ACCOUNT rules", 400)
        if country is not None or state is not None or segment is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "country_code, state_code and segment are forbidden for NAMED_ACCOUNT rules", 400)
        if not isinstance(named_account_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "named_account_id must be a string", 400)
    else:  # GEO_SEGMENT
        if named_account_id is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "named_account_id is forbidden for GEO_SEGMENT rules", 400)
        if country is not None and not isinstance(country, str):
            raise ApiError("ERR_INVALID_REQUEST", "country_code must be a string", 400)
        if state is not None and not isinstance(state, str):
            raise ApiError("ERR_INVALID_REQUEST", "state_code must be a string", 400)
        if segment is not None and segment not in SEGMENTS:
            raise ApiError("ERR_INVALID_REQUEST", "segment must be ENTERPRISE, MID_MARKET or SMB", 400)

    # Plan gate: rules may be created while plan is not locked
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)

    # Body FK existence
    territory = find_or_404(store.territories, territory_id, "territory")
    account = None
    if named_account_id is not None:
        account = find_or_404(store.accounts, named_account_id, "account")

    # Tier 5 cross-plan
    if territory["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "territory_id belongs to a different plan year", 409)
    if account is not None and account["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "named_account_id belongs to a different plan year", 409)

    # Named-rule uniqueness
    if rule_type == "NAMED_ACCOUNT":
        dup = [r for r in store.assignment_rules.values()
               if r["plan_year_id"] == plan["id"] and r["rule_type"] == "NAMED_ACCOUNT"
               and r["named_account_id"] == named_account_id and r["status"] == "ACTIVE"]
        if dup:
            raise ApiError("ERR_DUPLICATE_NAMED_RULE",
                           "An ACTIVE NAMED_ACCOUNT rule already exists for this account in this plan", 409)

    rule = stamp_new({
        "plan_year_id": plan["id"],
        "rule_type": rule_type,
        "priority": priority,
        "country_code": country,
        "state_code": state,
        "segment": segment,
        "named_account_id": named_account_id,
        "territory_id": territory_id,
        "status": "ACTIVE",
    })
    store.assignment_rules[rule["id"]] = rule
    return success_object(calc.ser_rule(rule), status=201)


@bp.route("/sales-planning/assignment-rules", methods=["GET"])
def list_rules():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.assignment_rules.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [r for r in items if r["plan_year_id"] == v]
    if (v := request.args.get("territory_id")) is not None:
        items = [r for r in items if r["territory_id"] == v]
    if (v := request.args.get("named_account_id")) is not None:
        items = [r for r in items if r["named_account_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [r for r in items if r["status"] == v]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_rule(r) for r in page], limit, offset, total)


@bp.route("/sales-planning/assignment-rules/<rid>", methods=["GET"])
def get_rule(rid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    r = find_or_404(store.assignment_rules, rid, "assignment rule")
    return success_object(calc.ser_rule(r))


@bp.route("/sales-planning/assignment-rules/<rid>/disable", methods=["POST"])
def disable_rule(rid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    r = find_or_404(store.assignment_rules, rid, "assignment rule")
    plan = find_or_404(store.plan_years, r["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Rule disable requires plan status DRAFT or OPEN", 409)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot disable rule in status {r['status']}", 409)
    r["status"] = "DISABLED"
    touch(r)
    return success_object(calc.ser_rule(r))


@bp.route("/sales-planning/assignment-rules/<rid>/enable", methods=["POST"])
def enable_rule(rid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    r = find_or_404(store.assignment_rules, rid, "assignment rule")
    plan = find_or_404(store.plan_years, r["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Rule enable requires plan status DRAFT or OPEN", 409)
    if r["status"] != "DISABLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot enable rule in status {r['status']}", 409)
    if r["rule_type"] == "NAMED_ACCOUNT":
        dup = [o for o in store.assignment_rules.values()
               if o["id"] != rid and o["plan_year_id"] == plan["id"]
               and o["rule_type"] == "NAMED_ACCOUNT"
               and o["named_account_id"] == r["named_account_id"]
               and o["status"] == "ACTIVE"]
        if dup:
            raise ApiError("ERR_DUPLICATE_NAMED_RULE",
                           "Another ACTIVE NAMED_ACCOUNT rule exists for this account", 409)
    r["status"] = "ACTIVE"
    touch(r)
    return success_object(calc.ser_rule(r))


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@bp.route("/sales-planning/accounts", methods=["POST"])
def create_account():
    ctx = get_user_context()
    require_role(ctx, ("SalesOpsAdmin", "SalesOpsAnalyst"))
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "name", "country_code", "state_code",
                                 "segment", "annual_potential_cents"})
    require_fields(body, ["plan_year_id", "name", "country_code", "segment",
                          "annual_potential_cents"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    name = req_string(body, "name")
    country = req_string(body, "country_code")
    state = opt_string(body, "state_code")
    segment = req_enum(body, "segment", SEGMENTS)
    potential = req_int(body, "annual_potential_cents", min_value=0)

    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)

    acct = stamp_new({
        "plan_year_id": plan["id"],
        "name": name,
        "country_code": country,
        "state_code": state,
        "segment": segment,
        "annual_potential_cents": potential,
        "assigned_territory_id": None,
        "assignment_source": "UNASSIGNED",
        "assignment_rule_id": None,
    })
    store.accounts[acct["id"]] = acct
    calc.resolve_assignment(acct)
    touch(acct)
    return success_object(calc.ser_account(acct), status=201)


@bp.route("/sales-planning/accounts", methods=["GET"])
def list_accounts():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.accounts.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [a for a in items if a["plan_year_id"] == v]
    if (v := request.args.get("assigned_territory_id")) is not None:
        items = [a for a in items if a["assigned_territory_id"] == v]
    if (v := request.args.get("assignment_rule_id")) is not None:
        items = [a for a in items if a["assignment_rule_id"] == v]
    if (v := request.args.get("assignment_source")) is not None:
        items = [a for a in items if a["assignment_source"] == v]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_account(a) for a in page], limit, offset, total)


@bp.route("/sales-planning/accounts/<aid>", methods=["GET"])
def get_account(aid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    a = find_or_404(store.accounts, aid, "account")
    return success_object(calc.ser_account(a))


@bp.route("/sales-planning/accounts/<aid>", methods=["PATCH"])
def patch_account(aid):
    ctx = get_user_context()
    require_role(ctx, ("SalesOpsAdmin", "SalesOpsAnalyst"))
    a = find_or_404(store.accounts, aid, "account")
    body = get_body()
    reject_unknown_fields(body, {"name", "country_code", "state_code", "segment",
                                 "annual_potential_cents"})
    plan = find_or_404(store.plan_years, a["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Account edits require plan status DRAFT or OPEN", 409)
    if "name" in body:
        a["name"] = req_string(body, "name")
    if "country_code" in body:
        a["country_code"] = req_string(body, "country_code")
    if "state_code" in body:
        a["state_code"] = opt_string(body, "state_code")
    if "segment" in body:
        a["segment"] = req_enum(body, "segment", SEGMENTS)
    if "annual_potential_cents" in body:
        a["annual_potential_cents"] = req_int(body, "annual_potential_cents", min_value=0)
    touch(a)
    return success_object(calc.ser_account(a))


# ---------------------------------------------------------------------------
# SalesRep
# ---------------------------------------------------------------------------

@bp.route("/sales-planning/reps", methods=["POST"])
def create_rep():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"full_name", "email", "hire_date"})
    require_fields(body, ["full_name", "email", "hire_date"])
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    hire = parse_date(body["hire_date"], "hire_date")
    rep = stamp_new({
        "full_name": full_name,
        "email": email,
        "hire_date": hire.isoformat(),
    })
    store.reps[rep["id"]] = rep
    return success_object(calc.ser_rep(rep), status=201)


@bp.route("/sales-planning/reps/<rid>", methods=["GET"])
def get_rep(rid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    r = find_or_404(store.reps, rid, "sales rep")
    return success_object(calc.ser_rep(r))


# ---------------------------------------------------------------------------
# RampSchedule
# ---------------------------------------------------------------------------

@bp.route("/sales-planning/ramp-schedules", methods=["POST"])
def create_ramp_schedule():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"name", "multipliers"})
    require_fields(body, ["name", "multipliers"])
    name = req_string(body, "name")
    mults = body["multipliers"]
    if not isinstance(mults, list) or len(mults) != 12:
        raise ApiError("ERR_INVALID_RAMP_SCHEDULE",
                       "multipliers must contain exactly 12 values", 422)
    parsed = []
    for m in mults:
        if isinstance(m, bool) or not isinstance(m, (int, float)):
            raise ApiError("ERR_INVALID_RAMP_SCHEDULE",
                           "each multiplier must be a number", 422)
        d = Decimal(str(m))
        try:
            exp = -d.as_tuple().exponent
        except (InvalidOperation, AttributeError):
            raise ApiError("ERR_INVALID_RAMP_SCHEDULE", "invalid multiplier", 422)
        if exp > 2:
            raise ApiError("ERR_INVALID_RAMP_SCHEDULE",
                           "multipliers may have at most 2 decimal places", 422)
        if d < Decimal("0") or d > Decimal("1"):
            raise ApiError("ERR_INVALID_RAMP_SCHEDULE",
                           "multipliers must be between 0.00 and 1.00 inclusive", 422)
        parsed.append(float(d))
    for i in range(1, 12):
        if parsed[i] < parsed[i - 1]:
            raise ApiError("ERR_INVALID_RAMP_SCHEDULE",
                           "multipliers must be non-decreasing", 422)
    sched = stamp_new({
        "name": name,
        "multipliers": parsed,
    })
    store.ramp_schedules[sched["id"]] = sched
    return success_object(calc.ser_ramp_schedule(sched), status=201)


@bp.route("/sales-planning/ramp-schedules/<sid>", methods=["GET"])
def get_ramp_schedule(sid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    s = find_or_404(store.ramp_schedules, sid, "ramp schedule")
    return success_object(calc.ser_ramp_schedule(s))
