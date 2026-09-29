"""Logical clock and CertifyingOfficial endpoints."""

from common import (
    ListQuery,
    ROLE_SCO,
    ROLE_SUPERVISORY,
    ROLE_VA,
    authenticate,
    get_official,
    new_row,
    parse_instant,
    require_official,
    serialize,
    touch,
)
from db import db, lock
from domain import refresh_protection
from errors import fail
from response import object_response
from validation import body, enum_field, instant_field, string_field

OFFICIAL_LEVELS = ("SCO", "SUPERVISORY")
OFFICIAL_STATUSES = ("ACTIVE", "INACTIVE")

READ_ROLES = (ROLE_VA, ROLE_SUPERVISORY, ROLE_SCO)


def register(app):
    # ------------------------------------------------------------------ clock
    @app.post("/_clock/set_current_utc")
    def set_clock():
        with lock:
            actor = authenticate((ROLE_VA, ROLE_SUPERVISORY))
            data = body()
            raw = instant_field(data, "to_iso8601")
            require_official(actor)

            target = parse_instant(raw)
            if target < db.clock:
                fail("ERR_CLOCK_REWIND",
                     "The logical clock may not be moved backwards.")

            db.clock = target
            for student in list(db.students.values()):
                if refresh_protection(student):
                    touch(student)
            return object_response({})

    # ------------------------------------------------- certifying officials
    @app.post("/certifying-officials")
    def create_official():
        with lock:
            authenticate((ROLE_VA,))
            data = body()
            full_name = string_field(data, "full_name")
            email = string_field(data, "email")
            official_level = enum_field(data, "official_level", OFFICIAL_LEVELS)

            for existing in db.officials.values():
                if existing["email"] == email:
                    fail("ERR_DUPLICATE_OFFICIAL_EMAIL",
                         "Another certifying official already uses this email.")

            row = new_row()
            row["full_name"] = full_name
            row["email"] = email
            row["official_level"] = official_level
            row["status"] = "ACTIVE"
            db.officials[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/certifying-officials/<official_id>")
    def read_official(official_id):
        with lock:
            actor = authenticate(READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_official(official_id)))

    @app.get("/certifying-officials")
    def list_officials():
        with lock:
            actor = authenticate(READ_ROLES)
            query = ListQuery((("official_level", OFFICIAL_LEVELS),
                               ("status", OFFICIAL_STATUSES)))
            require_official(actor)
            return query.emit(db.officials.values())

    @app.post("/certifying-officials/<official_id>/deactivate")
    def deactivate_official(official_id):
        with lock:
            authenticate((ROLE_VA,))
            official = get_official(official_id)
            if official["status"] != "ACTIVE":
                fail("ERR_OFFICIAL_ALREADY_INACTIVE",
                     "This certifying official is already inactive.")
            official["status"] = "INACTIVE"
            touch(official)
            return object_response(serialize(official))
