"""Programs, aggregators, customers (PRD §3.1, §3.2)."""
from flask import Blueprint, request

from errors import err
from common import (require, ALL_ROLES, get_body, ok_object, list_response,
                    require_str, require_int, require_enum, opt_int, opt_number)
from models import get_or_404, insert, touch
from store import parse_iso, db

bp_parties = Blueprint("parties", __name__)

BASELINE_METHODS = {"TEN_OF_TEN", "WEATHER_REGRESSION"}
SETTLEMENT_METHODS = {"PAY_FOR_PERFORMANCE", "CAPACITY_PAYMENT"}


def _require_iso(body, field):
    require_str(body, field)
    try:
        parse_iso(body[field])
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field %s must be an ISO 8601 datetime." % field)
    return body[field]


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
@bp_parties.route("/dr/programs", methods=["POST"])
def create_program():
    require(["ProgramOperator"])
    body = get_body()
    # step 6: required + well-typed
    name = require_str(body, "name")
    utility_name = require_str(body, "utility_name")
    incentive = require_int(body, "incentive_rate_cents_per_kwh", minimum=0)
    penalty = require_int(body, "penalty_rate_cents_per_kwh", minimum=0)
    capacity = require_int(body, "capacity_incentive_cents_per_kw", minimum=0)
    season_start = _require_iso(body, "season_start_date")
    season_end = _require_iso(body, "season_end_date")
    floor = opt_number(body, "performance_floor_pct", gt=0, le=1)
    lead = opt_int(body, "notification_lead_minutes", minimum=0)
    max_events = opt_int(body, "max_events_per_season", minimum=0)
    # step 7: enums
    baseline_method = require_enum(body, "baseline_method", BASELINE_METHODS, default="TEN_OF_TEN")
    settlement_method = require_enum(body, "settlement_method", SETTLEMENT_METHODS, default="PAY_FOR_PERFORMANCE")

    rec = insert("programs", {
        "name": name,
        "utility_name": utility_name,
        "incentive_rate_cents_per_kwh": incentive,
        "penalty_rate_cents_per_kwh": penalty,
        "capacity_incentive_cents_per_kw": capacity,
        "baseline_method": baseline_method,
        "settlement_method": settlement_method,
        "performance_floor_pct": floor if floor is not None else 0.75,
        "notification_lead_minutes": lead if lead is not None else 60,
        "max_events_per_season": max_events if max_events is not None else 3,
        "season_start_date": season_start,
        "season_end_date": season_end,
        "status": "DRAFT",
        "total_committed_kw": 0,
    })
    return ok_object(rec, status=201)


@bp_parties.route("/dr/programs/<pid>", methods=["GET"])
def get_program(pid):
    require(ALL_ROLES)
    return ok_object(get_or_404("programs", pid))


@bp_parties.route("/dr/programs", methods=["GET"])
def list_programs():
    require(ALL_ROLES)
    status = request.args.get("status")
    records = [p for p in db.data["programs"].values()
               if status is None or p["status"] == status]
    return list_response(records)


@bp_parties.route("/dr/programs/<pid>", methods=["PATCH"])
def update_program(pid):
    require(["ProgramOperator"])
    prog = get_or_404("programs", pid)
    body = get_body()
    # step 6: expected_program_version required + typed; supplied fields typed
    expected = require_int(body, "expected_program_version")
    incentive = opt_int(body, "incentive_rate_cents_per_kwh", minimum=0)
    penalty = opt_int(body, "penalty_rate_cents_per_kwh", minimum=0)
    capacity = opt_int(body, "capacity_incentive_cents_per_kw", minimum=0)
    floor = opt_number(body, "performance_floor_pct", gt=0, le=1)
    lead = opt_int(body, "notification_lead_minutes", minimum=0)
    max_events = opt_int(body, "max_events_per_season", minimum=0)
    # OCC (priority 21)
    if expected != prog["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_program_version %s does not match current version %s."
                  % (expected, prog["version"]))
    # apply supplied fields
    if incentive is not None:
        prog["incentive_rate_cents_per_kwh"] = incentive
    if penalty is not None:
        prog["penalty_rate_cents_per_kwh"] = penalty
    if capacity is not None:
        prog["capacity_incentive_cents_per_kw"] = capacity
    if floor is not None:
        prog["performance_floor_pct"] = floor
    if lead is not None:
        prog["notification_lead_minutes"] = lead
    if max_events is not None:
        prog["max_events_per_season"] = max_events
    touch(prog)
    return ok_object(prog)


@bp_parties.route("/dr/programs/<pid>/activate", methods=["POST"])
def activate_program(pid):
    require(["ProgramOperator"])
    prog = get_or_404("programs", pid)
    if prog["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Program is not in DRAFT status.")
    for f in ("incentive_rate_cents_per_kwh", "penalty_rate_cents_per_kwh",
              "capacity_incentive_cents_per_kw"):
        if prog.get(f) is None:
            raise err("ERR_VALIDATION", "Program rate %s must be set before activation." % f)
    if not parse_iso(prog["season_start_date"]) < parse_iso(prog["season_end_date"]):
        raise err("ERR_VALIDATION", "season_start_date must be earlier than season_end_date.")
    prog["status"] = "ACTIVE"
    touch(prog)
    return ok_object(prog)


@bp_parties.route("/dr/programs/<pid>/close", methods=["POST"])
def close_program(pid):
    require(["ProgramOperator"])
    prog = get_or_404("programs", pid)
    if prog["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Program is not in ACTIVE status.")
    for ev in db.data["dispatch_events"].values():
        if ev["program_id"] == pid and ev["status"] in ("SCHEDULED", "NOTIFIED", "ACTIVE"):
            raise err("ERR_INVALID_STATE", "Program has an open dispatch event.")
    prog["status"] = "CLOSED"
    touch(prog)
    return ok_object(prog)


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------
@bp_parties.route("/dr/aggregators", methods=["POST"])
def create_aggregator():
    require(["ProgramOperator"])
    body = get_body()
    name = require_str(body, "name")
    contact_email = require_str(body, "contact_email")
    rec = insert("aggregators", {
        "name": name,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "enrolled_committed_kw": 0,
        "season_delivered_kwh": 0,
        "paid_balance_cents": 0,
    })
    return ok_object(rec, status=201)


@bp_parties.route("/dr/aggregators/<aid>", methods=["GET"])
def get_aggregator(aid):
    require(ALL_ROLES)
    return ok_object(get_or_404("aggregators", aid))


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp_parties.route("/dr/customers", methods=["POST"])
def create_customer():
    require(["ProgramOperator"])
    body = get_body()
    name = require_str(body, "name")
    email = require_str(body, "email")
    service_address = require_str(body, "service_address")
    utility_account_id = require_str(body, "utility_account_id")
    rec = insert("customers", {
        "name": name,
        "email": email,
        "service_address": service_address,
        "utility_account_id": utility_account_id,
    })
    return ok_object(rec, status=201)


@bp_parties.route("/dr/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require(ALL_ROLES)
    return ok_object(get_or_404("customers", cid))
