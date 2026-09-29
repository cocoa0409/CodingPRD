"""Schedule grids and slot assignments (PRD 3.4)."""

import response
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import (
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEVELOPMENT_COORDINATOR,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_VOLUNTEER,
    authenticate,
    body,
    datetime_field,
    enum_field,
    int_field,
    int_query,
    invalid,
    lookup,
    str_field,
    str_query,
)
from services import calc, domain
from services import serializers as ser

CONFLICT_POLICIES = ("REJECT", "SENIORITY_PREEMPT")
IMMUTABLE_GRID_STATUSES = ("PUBLISHED", "SUPERSEDED")
CONFIRMABLE_PROGRAM_STATUSES = (
    "APPROVED_UNSCHEDULED",
    "SCHEDULED",
    "ON_AIR_ACTIVE",
    "UNDER_REVIEW",
    "PROBATION",
)

GRID_READ_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_VOLUNTEER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEVELOPMENT_COORDINATOR,
)
SLOT_READ_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_VOLUNTEER,
    ROLE_COMPLIANCE_OFFICER,
)


def _guard_mutable(grid):
    if grid["status"] in IMMUTABLE_GRID_STATUSES:
        raise ApiError("ERR_GRID_NOT_MUTABLE")


def _guard_not_restricted(program):
    if program is not None and domain.program_standing(program) == "RESTRICTED":
        raise ApiError("ERR_PROGRAM_RESTRICTED")


def _host_seniority(program):
    if program is None:
        return calc.ZERO2
    host = db.volunteers.get(program["host_volunteer_id"])
    if host is None:
        return calc.ZERO2
    return host["seniority_score"]


def register(app):
    # ------------------------------------------------------------------ grids
    @app.post("/schedule-grids")
    def create_grid():
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        season_code = str_field(data, "season_code", non_empty=True)
        effective_from = datetime_field(data, "effective_from")
        effective_to = datetime_field(data, "effective_to")
        if effective_to <= effective_from:
            raise ApiError("ERR_INVALID_INTERVAL")
        for row in db.grids.values():
            if row["season_code"] == season_code:
                raise ApiError("ERR_DUPLICATE_KEY", "A grid for that season code already exists.")
        grid = new_row(db.grids, {
            "season_code": season_code,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "DRAFT",
            "published_at": None,
        })
        return response.created(ser.grid(grid))

    @app.get("/schedule-grids")
    def list_grids():
        authenticate(*GRID_READ_ROLES)
        status = str_query("status")
        season_code = str_query("season_code")

        def keep(row):
            if status is not None and row["status"] != status:
                return False
            if season_code is not None and row["season_code"] != season_code:
                return False
            return True

        return response.listing(ordered(db.grids, keep), ser.grid)

    @app.get("/schedule-grids/<grid_id>")
    def get_grid(grid_id):
        authenticate(*GRID_READ_ROLES)
        grid = lookup(db.grids, grid_id, "ERR_GRID_NOT_FOUND")
        return response.obj(ser.grid(grid))

    @app.post("/schedule-grids/<grid_id>/publish")
    def publish_grid(grid_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        expected_version = int_field(data, "expected_grid_version")
        grid = lookup(db.grids, grid_id, "ERR_GRID_NOT_FOUND")
        if expected_version != grid["version"]:
            raise ApiError("ERR_STALE_GRID_VERSION")
        _guard_mutable(grid)
        if grid["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Only a grid in review can be published.")
        total, pct = calc.grid_figures(grid)
        if total == 0:
            raise ApiError("ERR_GRID_EMPTY")
        if any(s["status"] == "TENTATIVE" for s in calc.grid_live_slots(grid["id"])):
            raise ApiError("ERR_TENTATIVE_SLOTS_PRESENT")
        if pct < calc.DIVERSITY_QUOTA_PCT:
            raise ApiError("ERR_DIVERSITY_QUOTA_UNMET")
        if total > calc.WEEK_MINUTE_CAP:
            raise ApiError("ERR_WEEK_MINUTES_EXCEEDED")
        domain.publish_grid(grid)
        return response.obj(ser.grid(grid))

    # ------------------------------------------------------- slot assignments
    @app.post("/schedule-grids/<grid_id>/slot-assignments")
    def create_slot(grid_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        expected_version = int_field(data, "expected_grid_version")
        program_id = str_field(data, "program_id")
        conflict_policy = enum_field(data, "conflict_policy", CONFLICT_POLICIES, required=False, default="REJECT")
        day_of_week = int_field(data, "day_of_week", 0, 6)
        start_minute = int_field(data, "start_minute", 0, 1425)
        duration = int_field(data, "duration_minutes", 15, 720)
        if start_minute + duration > 1440:
            invalid("An occupation may not run past the end of its broadcast day.")

        grid = lookup(db.grids, grid_id, "ERR_GRID_NOT_FOUND")
        program = lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        if expected_version != grid["version"]:
            raise ApiError("ERR_STALE_GRID_VERSION")
        _guard_mutable(grid)

        collisions = [
            s for s in calc.grid_live_slots(grid["id"])
            if calc.slots_collide(
                day_of_week, start_minute, duration,
                s["day_of_week"], s["start_minute"], s["duration_minutes"],
            )
        ]
        if collisions and conflict_policy != "SENIORITY_PREEMPT":
            raise ApiError("ERR_SLOT_CONFLICT")

        total, _ = calc.grid_figures(grid)
        if total + duration > calc.WEEK_MINUTE_CAP:
            raise ApiError("ERR_WEEK_MINUTES_EXCEEDED")

        if collisions:
            challenger = _host_seniority(program)
            for incumbent in collisions:
                incumbent_program = db.programs.get(incumbent["program_id"])
                if challenger - _host_seniority(incumbent_program) < calc.SENIORITY_PREEMPT_MARGIN:
                    raise ApiError("ERR_SENIORITY_MARGIN_UNMET")
            for incumbent in collisions:
                incumbent["status"] = "PREEMPTED"
                incumbent["preempted_by_program_id"] = program["id"]
                touch(incumbent)

        slot = new_row(db.slots, {
            "grid_id": grid["id"],
            "program_id": program["id"],
            "day_of_week": day_of_week,
            "start_minute": start_minute,
            "duration_minutes": duration,
            "status": "TENTATIVE",
            "preempted_by_program_id": None,
            "release_reason": None,
        })
        if grid["status"] == "DRAFT":
            grid["status"] = "IN_REVIEW"
        touch(grid)
        return response.created(ser.slot(slot))

    @app.get("/slot-assignments")
    def list_slots():
        authenticate(*SLOT_READ_ROLES)
        grid_id = str_query("grid_id")
        program_id = str_query("program_id")
        preempted_by = str_query("preempted_by_program_id")
        status = str_query("status")
        day_of_week = int_query("day_of_week")

        def keep(row):
            if grid_id is not None and row["grid_id"] != grid_id:
                return False
            if program_id is not None and row["program_id"] != program_id:
                return False
            if preempted_by is not None and row["preempted_by_program_id"] != preempted_by:
                return False
            if status is not None and row["status"] != status:
                return False
            if day_of_week is not None and row["day_of_week"] != day_of_week:
                return False
            return True

        return response.listing(ordered(db.slots, keep), ser.slot)

    @app.get("/slot-assignments/<slot_id>")
    def get_slot(slot_id):
        authenticate(*SLOT_READ_ROLES)
        slot = lookup(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
        return response.obj(ser.slot(slot))

    @app.post("/slot-assignments/<slot_id>/confirm")
    def confirm_slot(slot_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        slot = lookup(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
        program = db.programs.get(slot["program_id"])
        _guard_not_restricted(program)
        grid = db.grids.get(slot["grid_id"])
        if grid is not None:
            _guard_mutable(grid)
        if slot["status"] != "TENTATIVE":
            raise ApiError("ERR_INVALID_STATE", "Only a tentative occupation can be confirmed.")
        if program is None or program["programming_status"] not in CONFIRMABLE_PROGRAM_STATUSES:
            raise ApiError("ERR_INVALID_STATE", "The show cannot hold confirmed airtime.")
        slot["status"] = "CONFIRMED"
        touch(slot)
        if program["programming_status"] == "APPROVED_UNSCHEDULED":
            program["programming_status"] = "SCHEDULED"
            touch(program)
        if grid is not None:
            touch(grid)
        return response.obj(ser.slot(slot))

    @app.post("/slot-assignments/<slot_id>/release")
    def release_slot(slot_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        data = body()
        release_reason = str_field(data, "release_reason")
        slot = lookup(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
        grid = db.grids.get(slot["grid_id"])
        if grid is not None:
            _guard_mutable(grid)
        if slot["status"] not in calc.LIVE_SLOT_STATUSES:
            raise ApiError("ERR_INVALID_STATE", "Only a tentative or confirmed occupation can be released.")
        domain.release_slot(slot, release_reason)
        return response.obj(ser.slot(slot))

    @app.post("/slot-assignments/<slot_id>/reinstate")
    def reinstate_slot(slot_id):
        authenticate(ROLE_PROGRAM_DIRECTOR)
        slot = lookup(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
        program = db.programs.get(slot["program_id"])
        _guard_not_restricted(program)
        grid = db.grids.get(slot["grid_id"])
        if grid is not None:
            _guard_mutable(grid)
        if slot["status"] != "PREEMPTED":
            raise ApiError("ERR_INVALID_STATE", "Only a preempted occupation can be reinstated.")
        for other in calc.grid_live_slots(slot["grid_id"]):
            if other["id"] == slot["id"]:
                continue
            if calc.slots_collide(
                slot["day_of_week"], slot["start_minute"], slot["duration_minutes"],
                other["day_of_week"], other["start_minute"], other["duration_minutes"],
            ):
                raise ApiError("ERR_SLOT_CONFLICT")
        slot["status"] = "CONFIRMED"
        slot["preempted_by_program_id"] = None
        touch(slot)
        if grid is not None:
            touch(grid)
        return response.obj(ser.slot(slot))
