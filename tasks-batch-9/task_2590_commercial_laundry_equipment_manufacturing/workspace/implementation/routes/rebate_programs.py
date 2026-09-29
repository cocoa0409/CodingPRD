"""Utility rebate programs and their non-colliding validity windows (PRD 3.2)."""

from datetime import timedelta
from decimal import Decimal

import lookup
import response
import validate
from db import base_row, db
from errors import (ERR_DUPLICATE_RESOURCE_CODE, ERR_INTERVAL_INVALID,
                    ERR_INVALID_REQUEST, ERR_PROGRAM_WINDOW_CONFLICT, fail)
from middleware import CHANNEL_MANAGER, COMPLIANCE_OFFICER, PRODUCT_ENGINEER, endpoint
from validate import PRODUCT_LINES

PROGRAM_CLASSES = ["WATER", "ENERGY", "COMBINED"]
PROGRAM_STATES = ["ACTIVE", "RETIRED"]
ONE_DAY = timedelta(days=1)


def register(app):
    @app.post("/clm/rebate-programs")
    @endpoint([COMPLIANCE_OFFICER])
    def create_rebate_program():
        body = validate.parse_body()
        program_code = body.code("program_code")
        utility_code = body.string("utility_code", 1, 32)
        program_class = body.enum("program_class", PROGRAM_CLASSES)
        eligible_product_lines = body.enum_array("eligible_product_lines",
                                                 PRODUCT_LINES)
        max_water = body.decimal("max_water_gal_per_cwt", gt=Decimal(0))
        max_kwh = body.decimal("max_kwh_per_cwt", gt=Decimal(0))
        min_capacity_rating_lb = body.integer("min_capacity_rating_lb", minimum=0)
        rebate_base_cents = body.integer("rebate_base_cents", minimum=1)
        capacity_bonus = body.integer("capacity_bonus_cents_per_10lb", minimum=0,
                                      required=False, default=0)
        rebate_cap_cents = body.integer("rebate_cap_cents", minimum=0)
        effective_from = body.instant("effective_from")
        effective_to = body.instant("effective_to")
        if rebate_cap_cents < rebate_base_cents:
            fail(ERR_INVALID_REQUEST,
                 "rebate_cap_cents must be at least rebate_base_cents.")

        # rule 44: interval sanity on the date components
        if effective_to.date() < effective_from.date():
            fail(ERR_INTERVAL_INVALID,
                 "effective_to must not fall before effective_from.")
        # rule 47: at least one full clear day from every non-retired window
        new_from = effective_from.date()
        new_to = effective_to.date()
        for other in db.programs.values():
            if other["program_state"] == "RETIRED":
                continue
            if other["utility_code"] != utility_code:
                continue
            if other["program_class"] != program_class:
                continue
            other_from = other["effective_from"].date()
            other_to = other["effective_to"].date()
            if new_from <= other_to + ONE_DAY and other_from <= new_to + ONE_DAY:
                fail(ERR_PROGRAM_WINDOW_CONFLICT,
                     "The window must be separated from program '%s' by at least "
                     "one full clear day." % other["program_code"])
        # rule 48: natural-key uniqueness
        if any(p["program_code"] == program_code for p in db.programs.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "program_code '%s' already exists." % program_code)

        row = base_row()
        row.update({
            "program_code": program_code,
            "utility_code": utility_code,
            "program_class": program_class,
            "eligible_product_lines": eligible_product_lines,
            "max_water_gal_per_cwt": max_water,
            "max_kwh_per_cwt": max_kwh,
            "min_capacity_rating_lb": min_capacity_rating_lb,
            "rebate_base_cents": rebate_base_cents,
            "capacity_bonus_cents_per_10lb": capacity_bonus,
            "rebate_cap_cents": rebate_cap_cents,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "program_state": "ACTIVE",
        })
        db.programs[row["id"]] = row
        return response.created(row)

    @app.get("/clm/rebate-programs/<program_id>")
    @endpoint([COMPLIANCE_OFFICER, PRODUCT_ENGINEER, CHANNEL_MANAGER])
    def read_rebate_program(program_id):
        return response.ok(lookup.program(program_id))

    @app.get("/clm/rebate-programs")
    @endpoint([COMPLIANCE_OFFICER, PRODUCT_ENGINEER, CHANNEL_MANAGER])
    def list_rebate_programs():
        limit, offset = validate.q_pagination()
        utility_code = validate.q_str("utility_code")
        program_state = validate.q_enum("program_state", PROGRAM_STATES)
        rows = list(db.programs.values())
        if utility_code is not None:
            rows = [r for r in rows if r["utility_code"] == utility_code]
        if program_state is not None:
            rows = [r for r in rows if r["program_state"] == program_state]
        rows = sorted(rows, key=lambda r: (r["effective_from"], r["program_code"],
                                           r["_seq"]))
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)
