"""Reference data + logical clock: Accountholders, Employers, PayrollPeriods,
and POST /_clock/set_current_utc (PRD §3.1, §3.11)."""
from flask import Blueprint

import serializers
from clock import clock
from db import db, stamp_create, touch
from errors import err
from helpers import (get_json_body, paginate, qarg, require_bool, require_enum,
                     require_int, require_string)
from lookups import get_employer, get_payroll_period
from middleware import caller, require_role
from response import success

bp = Blueprint("reference", __name__)


# ---- Accountholders ----
@bp.route("/hsa/accountholders", methods=["POST"])
def create_accountholder():
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    date_of_birth = require_string(body, "date_of_birth")
    o = {
        "full_name": full_name,
        "email": email,
        "date_of_birth": date_of_birth,
        # Computed lazily on account verify / catch-up tests; null until then.
        "turns_55_or_older_in_plan_year": None,
    }
    stamp_create(o)
    db.accountholders[o["id"]] = o
    return success(serializers.accountholder(o), status=201)


@bp.route("/hsa/accountholders/<holder_id>", methods=["GET"])
def get_accountholder_route(holder_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    o = db.accountholders.get(holder_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Accountholder not found")
    return success(serializers.accountholder(o), status=200)


# ---- Employers ----
@bp.route("/hsa/employers", methods=["POST"])
def create_employer():
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    enabled = require_bool(body, "payroll_contributions_enabled", required=False, default=True)
    o = {"name": name, "payroll_contributions_enabled": enabled}
    stamp_create(o)
    db.employers[o["id"]] = o
    return success(serializers.employer(o), status=201)


@bp.route("/hsa/employers/<employer_id>", methods=["GET"])
def get_employer_route(employer_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    o = get_employer(employer_id)
    return success(serializers.employer(o), status=200)


@bp.route("/hsa/employers/<employer_id>", methods=["PATCH"])
def patch_employer(employer_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    o = get_employer(employer_id)
    body = get_json_body()
    enabled = require_bool(body, "payroll_contributions_enabled", required=True)
    o["payroll_contributions_enabled"] = enabled
    touch(o)
    return success(serializers.employer(o), status=200)


# ---- PayrollPeriods (half-open day intervals under an Employer) ----
@bp.route("/hsa/employers/<employer_id>/payroll-periods", methods=["POST"])
def create_payroll_period(employer_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    employer = get_employer(employer_id)
    body = get_json_body()
    start = require_int(body, "period_start_day")
    end = require_int(body, "period_end_day")

    # Bad day bounds -> ERR_PAYROLL_PERIOD_OVERLAP (PRD §3.1).
    # Valid: 1 <= start < end <= 366.
    if not (start >= 1 and start < end and end <= 366):
        raise err("ERR_PAYROLL_PERIOD_OVERLAP", "Invalid payroll period day bounds")

    # Half-open overlap vs existing SCHEDULED periods on this employer:
    # overlap iff a.start < b.end AND b.start < a.end.
    for p in db.payroll_periods.values():
        if p["employer_id"] != employer["id"] or p["status"] != "SCHEDULED":
            continue
        if start < p["period_end_day"] and p["period_start_day"] < end:
            raise err("ERR_PAYROLL_PERIOD_OVERLAP", "Payroll period window overlaps an existing SCHEDULED period")

    o = {
        "employer_id": employer["id"],
        "period_start_day": start,
        "period_end_day": end,
        "status": "SCHEDULED",
    }
    stamp_create(o)
    db.payroll_periods[o["id"]] = o
    return success(serializers.payroll_period(o), status=201)


@bp.route("/hsa/employers/<employer_id>/payroll-periods", methods=["GET"])
def list_payroll_periods(employer_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    employer = get_employer(employer_id)
    status_filter = qarg("status")
    items = [
        p for p in db.payroll_periods.values()
        if p["employer_id"] == employer["id"]
        and (status_filter is None or p["status"] == status_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.payroll_period(p) for p in page], status=200, pagination=meta)


@bp.route("/hsa/employers/<employer_id>/payroll-periods/<pp_id>/cancel", methods=["POST"])
def cancel_payroll_period(employer_id, pp_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    employer = get_employer(employer_id)
    pp = get_payroll_period(employer["id"], pp_id)
    if pp["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "PayrollPeriod is not SCHEDULED")
    pp["status"] = "CANCELLED"
    touch(pp)
    return success(serializers.payroll_period(pp), status=200)


# ---- Logical clock ----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    body = get_json_body()
    to_iso = require_string(body, "to_iso8601")
    try:
        clock.set(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    return success({}, status=200)
