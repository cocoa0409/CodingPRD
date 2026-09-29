"""Programs (PRD section 3.1)."""

import re

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import OPERATOR_ROLES, ROLE_PROGRAM_MANAGER, authorize
from validate import (body_of, req_enum, req_int, req_str)

bp = Blueprint("programs", __name__)

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _validate_price_tiers(body):
    tiers = body.get("price_tiers")
    if not isinstance(tiers, list) or len(tiers) < 1:
        err("ERR_INVALID_REQUEST", "price_tiers must be a non-empty array.")
    seen_codes = set()
    result = []
    previous = None
    for item in tiers:
        if not isinstance(item, dict):
            err("ERR_INVALID_REQUEST", "Each price_tiers item must be an object.")
        tier_code = req_str(item, "tier_code", 1, 40)
        min_pax = req_int(item, "min_pax", 1)
        max_pax = req_int(item, "max_pax", 1)
        per_pax = req_int(item, "per_pax_price_cents", 0)
        single = req_int(item, "single_supplement_cents", 0)
        deposit = req_int(item, "deposit_cents", 0)
        if max_pax < min_pax:
            err("ERR_INVALID_REQUEST", "price_tiers item max_pax must be >= min_pax.")
        if tier_code in seen_codes:
            err("ERR_INVALID_REQUEST", "price_tiers tier_code values must be unique.")
        seen_codes.add(tier_code)
        if previous is not None:
            if min_pax < previous["min_pax"]:
                err("ERR_INVALID_REQUEST", "price_tiers must be sorted by min_pax ascending.")
            if min_pax != previous["max_pax"] + 1:
                err("ERR_INVALID_REQUEST",
                    "price_tiers must be contiguous: min_pax must equal the previous "
                    "item's max_pax plus one.")
        entry = {
            "tier_code": tier_code,
            "min_pax": min_pax,
            "max_pax": max_pax,
            "per_pax_price_cents": per_pax,
            "single_supplement_cents": single,
            "deposit_cents": deposit,
        }
        result.append(entry)
        previous = entry
    return result


def _validate_cancellation_grid(body):
    grid = body.get("cancellation_grid")
    if not isinstance(grid, list) or len(grid) < 1:
        err("ERR_INVALID_REQUEST", "cancellation_grid must be a non-empty array.")
    seen_days = set()
    result = []
    previous = None
    for item in grid:
        if not isinstance(item, dict):
            err("ERR_INVALID_REQUEST", "Each cancellation_grid item must be an object.")
        min_days_before = req_int(item, "min_days_before", 0)
        penalty_bp = req_int(item, "penalty_bp", 0, 10000)
        if min_days_before in seen_days:
            err("ERR_INVALID_REQUEST", "cancellation_grid min_days_before values must be unique.")
        seen_days.add(min_days_before)
        if previous is not None and min_days_before > previous["min_days_before"]:
            err("ERR_INVALID_REQUEST",
                "cancellation_grid must be sorted by min_days_before descending.")
        entry = {"min_days_before": min_days_before, "penalty_bp": penalty_bp}
        result.append(entry)
        previous = entry
    if 0 not in seen_days:
        err("ERR_INVALID_REQUEST",
            "cancellation_grid must contain an item whose min_days_before is 0.")
    return result


@bp.route("/programs", methods=["POST"])
def create_program():
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        name = req_str(body, "name", 1, 160)
        destination_country = req_str(body, "destination_country", 2, 2)
        if not COUNTRY_RE.match(destination_country):
            err("ERR_INVALID_REQUEST",
                "destination_country must be a two-letter uppercase ISO country code.")
        faith_tradition = req_enum(body, "faith_tradition", core.FAITH_TRADITIONS)
        duration_days = req_int(body, "duration_days", 2, 40)
        price_tiers = _validate_price_tiers(body)
        cancellation_grid = _validate_cancellation_grid(body)

        row = core.base_row()
        row.update({
            "name": name,
            "destination_country": destination_country,
            "faith_tradition": faith_tradition,
            "duration_days": duration_days,
            "price_tiers": price_tiers,
            "cancellation_grid": cancellation_grid,
            "departure_count": 0,
        })
        db.programs[row["id"]] = row
        return response.ok(core.serialize(row), 201)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    authorize(OPERATOR_ROLES)
    with lock:
        row = db.programs.get(program_id)
        if row is None:
            err("ERR_PROGRAM_NOT_FOUND", "Program %s does not exist." % program_id)
        return response.ok(core.serialize(row))
