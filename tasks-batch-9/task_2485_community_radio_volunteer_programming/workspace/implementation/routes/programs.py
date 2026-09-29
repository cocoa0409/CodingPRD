"""Programs: performance review and cancellation (PRD 3.8)."""

from decimal import Decimal

import response
from db import clock, db, ordered, touch
from errors import ApiError
from middleware import (
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEVELOPMENT_COORDINATOR,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_VOLUNTEER,
    authenticate,
    body,
    enum_field,
    int_field,
    lookup,
    str_field,
    str_query,
)
from services import calc, domain
from services import serializers as ser

REVIEW_WINDOWS = ("TRAILING_SIX", "QUARTER_TO_DATE")
REVIEWABLE = ("ON_AIR_ACTIVE", "UNDER_REVIEW", "PROBATION")
CANCELLABLE = ("UNDER_REVIEW", "PROBATION")

READ_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_VOLUNTEER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEVELOPMENT_COORDINATOR,
)


def register(app):
    @app.get("/programs")
    def list_programs():
        authenticate(*READ_ROLES)
        programming_status = str_query("programming_status")
        compliance_standing = str_query("compliance_standing")
        host_id = str_query("host_volunteer_id")
        proposal_id = str_query("proposal_id")
        format_code = str_query("format_code")

        def keep(row):
            if programming_status is not None and row["programming_status"] != programming_status:
                return False
            if compliance_standing is not None and domain.program_standing(row) != compliance_standing:
                return False
            if host_id is not None and row["host_volunteer_id"] != host_id:
                return False
            if proposal_id is not None and row["proposal_id"] != proposal_id:
                return False
            if format_code is not None and row["format_code"] != format_code:
                return False
            return True

        return response.listing(ordered(db.programs, keep), ser.program)

    @app.get("/programs/<program_id>")
    def get_program(program_id):
        authenticate(*READ_ROLES)
        row = lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        return response.obj(ser.program(row))

    @app.post("/programs/<program_id>/performance-reviews")
    def review_program(program_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        review_window = enum_field(data, "review_window", REVIEW_WINDOWS)
        program = lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        if program["programming_status"] not in REVIEWABLE:
            raise ApiError("ERR_INVALID_STATE", "Only an airing, under-review, or probationary show can be evaluated.")

        before = program["programming_status"]
        score = calc.performance_score(program, review_window)
        program["performance_score"] = score
        program["performance_score_method"] = review_window
        program["last_evaluated_at"] = clock.now
        touch(program)

        host = db.volunteers.get(program["host_volunteer_id"])
        # Rewriting a hosted show's score refreshes the host's seniority.
        domain.recompute_seniority(host)
        host_fit = host is not None and host["status"] in ("CERTIFIED", "PROBATION")

        if before == "ON_AIR_ACTIVE":
            if score < Decimal("60.00"):
                program["programming_status"] = "UNDER_REVIEW"
        elif before == "UNDER_REVIEW":
            if score < Decimal("45.00"):
                program["programming_status"] = "PROBATION"
            elif score >= Decimal("60.00") and host_fit:
                program["programming_status"] = "ON_AIR_ACTIVE"
        elif before == "PROBATION":
            if score >= Decimal("60.00") and host_fit:
                program["programming_status"] = "ON_AIR_ACTIVE"

        return response.obj(ser.program(program))

    @app.post("/programs/<program_id>/cancel")
    def cancel_program(program_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        expected_version = int_field(data, "expected_program_version")
        cancellation_reason = str_field(data, "cancellation_reason")
        program = lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        if expected_version != program["version"]:
            raise ApiError("ERR_STALE_PROGRAM_VERSION")
        if program["programming_status"] not in CANCELLABLE:
            raise ApiError("ERR_INVALID_STATE", "Only an under-review or probationary show can be cancelled.")
        domain.cancel_program(program, cancellation_reason)
        return response.obj(ser.program(program))
