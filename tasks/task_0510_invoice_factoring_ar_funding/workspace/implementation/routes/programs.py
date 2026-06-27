"""FactoringProgram endpoints (§3.1)."""

from flask import Blueprint, request

import db
import errors
from common import (public, req_str, opt_str_default, opt_number, opt_int,
                    stamp_common, touch)
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response

bp = Blueprint("programs", __name__)


@bp.post("/factoring/programs")
def create_program():
    _, role = authenticate()
    authorize(role, ("PlatformAdmin",))
    body = get_body()
    name = req_str(body, "name")
    currency = opt_str_default(body, "currency", "USD")
    fee_rate = opt_number(body, "default_fee_rate_per_day", 0.0005)
    tier2 = opt_number(body, "tier2_multiplier", 1.5)
    tier3 = opt_number(body, "tier3_multiplier", 2.0)
    grace = opt_int(body, "recourse_grace_days", 90)

    program = {
        "name": name,
        "currency": currency,
        "default_fee_rate_per_day": fee_rate,
        "tier2_multiplier": tier2,
        "tier3_multiplier": tier3,
        "recourse_grace_days": grace,
        "status": "ACTIVE",
    }
    stamp_common(program)
    db.programs[program["id"]] = program
    return success(public(program), status=201)


@bp.get("/factoring/programs")
def list_programs():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    status = request.args.get("status")
    records = [p for p in db.programs.values()
               if status is None or p["status"] == status]
    return list_response(records)


@bp.get("/factoring/programs/<program_id>")
def read_program(program_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    program = lookup(db.programs, program_id)
    return success(public(program), status=200)


@bp.post("/factoring/programs/<program_id>/suspend")
def suspend_program(program_id):
    _, role = authenticate()
    authorize(role, ("PlatformAdmin",))
    program = lookup(db.programs, program_id)
    if program["status"] != "ACTIVE":
        raise errors.invalid_state("Program is not ACTIVE")
    program["status"] = "SUSPENDED"
    touch(program)
    return success(public(program), status=200)
