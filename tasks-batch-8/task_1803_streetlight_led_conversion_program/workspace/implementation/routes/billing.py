"""TariffRateSchedule, TariffAccount, BillingLine endpoints (PRD 3.5)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import (
    find_rate_schedule, monthly_charge, program_of_account, require_active,
    ser_account, ser_billing_line, ser_rate_schedule,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from util import CLOCK, add_one_month, parse_date, period_bounds
from validate import (
    get_body, opt_nullable_date, req_date, req_enum, req_str,
)
from routes.common import list_endpoint, require_record

bp = Blueprint("billing", __name__)

BA = ["BillingAnalyst"]
OWNERSHIP = ["MUNICIPAL", "UTILITY_OWNED"]


# ---------------------------------------------------------------------------
# Rate schedules
# ---------------------------------------------------------------------------

def _valid_tier_rates(body):
    rates = body.get("tier_rates")
    if not isinstance(rates, dict) or set(rates.keys()) != {"T1", "T2", "T3", "T4", "T5"}:
        raise_error("ERR_INVALID_REQUEST", "tier_rates must be a map of exactly T1..T5")
    out = {}
    for tier, cents in rates.items():
        if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
            raise_error("ERR_INVALID_REQUEST", f"tier_rates[{tier}] must be a positive integer")
        out[tier] = cents
    return out


@bp.route("/streetlights/rate-schedules", methods=["POST"])
@locked
def create_rate_schedule():
    caller = get_caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    ownership_class = req_enum(body, "ownership_class", OWNERSHIP)
    effective_from = req_date(body, "effective_from")
    effective_until = opt_nullable_date(body, "effective_until", default=None)
    tier_rates = _valid_tier_rates(body)
    if effective_until is not None and parse_date(effective_until) <= parse_date(effective_from):
        raise_error("ERR_INVALID_REQUEST", "effective_until must be later than effective_from")
    require_roles(caller, BA)
    program = store.programs.get(program_id)
    if program is None:
        raise_error("ERR_PROGRAM_NOT_FOUND", f"program not found: {program_id}")
    require_active(program)
    rec = new_record("rate_schedules", {
        "program_id": program_id,
        "ownership_class": ownership_class,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "tier_rates": tier_rates,
        "status": "DRAFT",
    })
    return success_object(ser_rate_schedule(rec), status=201)


@bp.route("/streetlights/rate-schedules", methods=["GET"])
@locked
def list_rate_schedules():
    return list_endpoint("rate_schedules", ser_rate_schedule,
                         ["program_id", "ownership_class", "status"])


@bp.route("/streetlights/rate-schedules/<sid>", methods=["GET"])
@locked
def get_rate_schedule(sid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("rate_schedules", sid, "ERR_RATE_SCHEDULE_NOT_FOUND")
    return success_object(ser_rate_schedule(rec))


def _window_overlaps(a_from, a_until, b_from, b_until):
    """Half-open [from, until) overlap; null until = open-ended. Adjacency
    (until == other's from) is allowed."""
    a_end = parse_date(a_until) if a_until else None
    b_end = parse_date(b_until) if b_until else None
    a_f, b_f = parse_date(a_from), parse_date(b_from)
    return (a_end is None or b_f < a_end) and (b_end is None or a_f < b_end)


@bp.route("/streetlights/rate-schedules/<sid>/file", methods=["POST"])
@locked
def file_rate_schedule(sid):
    caller = get_caller()
    require_roles(caller, BA)
    rec = require_record("rate_schedules", sid, "ERR_RATE_SCHEDULE_NOT_FOUND")
    require_active(store.programs.get(rec["program_id"]))
    if rec["status"] != "DRAFT":
        raise_error("ERR_RATE_SCHEDULE_NOT_DRAFT", "file requires a DRAFT schedule")
    for other in store.rate_schedules.values():
        if (other["id"] == rec["id"] or other["program_id"] != rec["program_id"]
                or other["ownership_class"] != rec["ownership_class"]
                or other["status"] not in ("FILED", "EFFECTIVE")):
            continue
        if _window_overlaps(rec["effective_from"], rec["effective_until"],
                            other["effective_from"], other["effective_until"]):
            raise_error("ERR_RATE_WINDOW_OVERLAP",
                        "window overlaps a FILED or EFFECTIVE schedule of the same class")
    rec["status"] = "FILED"
    touch(rec)
    return success_object(ser_rate_schedule(rec))


@bp.route("/streetlights/rate-schedules/<sid>/activate", methods=["POST"])
@locked
def activate_rate_schedule(sid):
    caller = get_caller()
    require_roles(caller, BA)
    rec = require_record("rate_schedules", sid, "ERR_RATE_SCHEDULE_NOT_FOUND")
    require_active(store.programs.get(rec["program_id"]))
    if rec["status"] != "FILED":
        raise_error("ERR_RATE_SCHEDULE_NOT_FILED", "activate requires a FILED schedule")
    rec["status"] = "EFFECTIVE"
    touch(rec)
    return success_object(ser_rate_schedule(rec))


@bp.route("/streetlights/rate-schedules/<sid>/retire", methods=["POST"])
@locked
def retire_rate_schedule(sid):
    caller = get_caller()
    body = get_body()
    effective_until = req_date(body, "effective_until")
    require_roles(caller, BA)
    rec = require_record("rate_schedules", sid, "ERR_RATE_SCHEDULE_NOT_FOUND")
    # Entity-dependent shape check (stage 2 per PRD 2.10, evaluated once the
    # resource is loaded): after effective_from, not before the current date.
    if parse_date(effective_until) <= parse_date(rec["effective_from"]):
        raise_error("ERR_INVALID_REQUEST", "effective_until must be later than effective_from")
    if parse_date(effective_until) < CLOCK.today():
        raise_error("ERR_INVALID_REQUEST", "effective_until must not be before the current date")
    require_active(store.programs.get(rec["program_id"]))
    if rec["status"] != "EFFECTIVE":
        raise_error("ERR_RATE_SCHEDULE_NOT_EFFECTIVE", "retire requires an EFFECTIVE schedule")
    rec["effective_until"] = effective_until
    rec["status"] = "SUPERSEDED"
    touch(rec)
    return success_object(ser_rate_schedule(rec))


# ---------------------------------------------------------------------------
# Tariff accounts
# ---------------------------------------------------------------------------

@bp.route("/streetlights/tariff-accounts", methods=["POST"])
@locked
def create_tariff_account():
    caller = get_caller()
    body = get_body()
    district_id = req_str(body, "district_id")
    account_number = req_str(body, "account_number")
    ownership_class = req_enum(body, "ownership_class", OWNERSHIP)
    require_roles(caller, BA)
    district = store.districts.get(district_id)
    if district is None:
        raise_error("ERR_DISTRICT_NOT_FOUND", f"district not found: {district_id}")
    require_active(store.programs.get(district["program_id"]))
    program_id = district["program_id"]
    for a in store.accounts.values():
        ad = store.districts.get(a["district_id"])
        if ad and ad["program_id"] == program_id and a["account_number"] == account_number:
            raise_error("ERR_INVALID_REQUEST", "account_number must be unique within the program")
    for a in store.accounts.values():
        if (a["district_id"] == district_id and a["ownership_class"] == ownership_class
                and a["status"] in ("OPEN", "FROZEN")):
            raise_error("ERR_DUPLICATE_ACCOUNT",
                        "an OPEN/FROZEN account already exists for this district and class")
    rec = new_record("accounts", {
        "district_id": district_id,
        "account_number": account_number,
        "ownership_class": ownership_class,
        "current_period": CLOCK.current_month(),
        "status": "OPEN",
    })
    return success_object(ser_account(rec), status=201)


@bp.route("/streetlights/tariff-accounts", methods=["GET"])
@locked
def list_tariff_accounts():
    return list_endpoint("accounts", ser_account, ["district_id", "ownership_class", "status"])


@bp.route("/streetlights/tariff-accounts/<aid>", methods=["GET"])
@locked
def get_tariff_account(aid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("accounts", aid, "ERR_ACCOUNT_NOT_FOUND")
    return success_object(ser_account(rec))


@bp.route("/streetlights/tariff-accounts/<aid>/freeze", methods=["POST"])
@locked
def freeze_account(aid):
    caller = get_caller()
    require_roles(caller, BA)
    rec = require_record("accounts", aid, "ERR_ACCOUNT_NOT_FOUND")
    require_active(program_of_account(rec))
    if rec["status"] != "OPEN":
        raise_error("ERR_ACCOUNT_NOT_OPEN", "freeze requires an OPEN account")
    rec["status"] = "FROZEN"
    touch(rec)
    return success_object(ser_account(rec))


@bp.route("/streetlights/tariff-accounts/<aid>/unfreeze", methods=["POST"])
@locked
def unfreeze_account(aid):
    caller = get_caller()
    require_roles(caller, BA)
    rec = require_record("accounts", aid, "ERR_ACCOUNT_NOT_FOUND")
    require_active(program_of_account(rec))
    if rec["status"] != "FROZEN":
        raise_error("ERR_ACCOUNT_NOT_OPEN", "unfreeze requires a FROZEN account")
    rec["status"] = "OPEN"
    touch(rec)
    return success_object(ser_account(rec))


@bp.route("/streetlights/tariff-accounts/<aid>/generate-lines", methods=["POST"])
@locked
def generate_lines(aid):
    caller = get_caller()
    require_roles(caller, BA)
    account = require_record("accounts", aid, "ERR_ACCOUNT_NOT_FOUND")
    program = program_of_account(account)
    require_active(program)
    if account["status"] != "OPEN":
        raise_error("ERR_ACCOUNT_NOT_OPEN", "line generation requires an OPEN account")
    period = account["current_period"]
    eligible = [p for p in store.poles.values()
                if p["district_id"] == account["district_id"]
                and p["ownership_type"] == account["ownership_class"]
                and p["status"] != "EXEMPT"]
    eligible.sort(key=lambda p: p["_seq"])
    to_create = []
    skipped = 0
    for pole in eligible:
        dup = any(l for l in store.billing_lines.values()
                  if l["account_id"] == account["id"] and l["pole_id"] == pole["id"]
                  and l["period"] == period and l["line_type"] == "REGULAR"
                  and l["status"] != "SUPERSEDED")
        if dup:
            skipped += 1
        else:
            to_create.append(pole)
    if to_create:
        p_start, _p_end, _D = period_bounds(period)
        sched = find_rate_schedule(program["id"], account["ownership_class"], p_start)
        if sched is None:
            raise_error("ERR_NO_EFFECTIVE_RATE_SCHEDULE",
                        "no EFFECTIVE/SUPERSEDED schedule covers the period start")
    for pole in to_create:
        calc = monthly_charge(pole, period)
        if calc is None:
            # Defensive: the class-level schedule lookup above already passed.
            raise_error("ERR_NO_EFFECTIVE_RATE_SCHEDULE",
                        "no EFFECTIVE/SUPERSEDED schedule covers the period start")
        new_record("billing_lines", {
            "account_id": account["id"],
            "pole_id": pole["id"],
            "rate_schedule_id": calc["rate_schedule_id"],
            "period": period,
            "line_type": "REGULAR",
            "billing_wattage": calc["billing_wattage"],
            "tier": calc["tier"],
            "charge_cents": calc["charge_cents"],
            "supersedes_line_id": None,
            "status": "ESTIMATED",
        })
    return success_object({"created_count": len(to_create), "skipped_count": skipped})


@bp.route("/streetlights/tariff-accounts/<aid>/close-period", methods=["POST"])
@locked
def close_period(aid):
    caller = get_caller()
    require_roles(caller, BA)
    account = require_record("accounts", aid, "ERR_ACCOUNT_NOT_FOUND")
    require_active(program_of_account(account))
    if account["status"] != "OPEN":
        raise_error("ERR_ACCOUNT_NOT_OPEN", "period close requires an OPEN account")
    period = account["current_period"]
    for line in store.billing_lines.values():
        if (line["account_id"] == account["id"] and line["period"] == period
                and line["status"] == "ESTIMATED"):
            line["status"] = "BILLED"
            touch(line)
    account["current_period"] = add_one_month(period)
    touch(account)
    return success_object(ser_account(account))


# ---------------------------------------------------------------------------
# Billing lines (read-only)
# ---------------------------------------------------------------------------

def _line_sort_key(line):
    return (line["period"], line["_seq"])


@bp.route("/streetlights/billing-lines", methods=["GET"])
@locked
def list_billing_lines():
    return list_endpoint(
        "billing_lines", ser_billing_line,
        ["account_id", "pole_id", "rate_schedule_id", "supersedes_line_id",
         "period", "status", "line_type"],
        sort_key=_line_sort_key)


@bp.route("/streetlights/billing-lines/<lid>", methods=["GET"])
@locked
def get_billing_line(lid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("billing_lines", lid, "ERR_BILLING_LINE_NOT_FOUND")
    return success_object(ser_billing_line(rec))
