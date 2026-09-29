"""Test-driving endpoints for the server-held logical clock."""
from db import parse_iso, store
from middleware import ALL_ROLES, ROLE_PROGRAM_ADMIN, register
from response import object_response
from services import domain

ADMIN = [ROLE_PROGRAM_ADMIN]

SET_SCHEMA = {"to_iso8601": {"type": "datetime", "required": True}}


def init(app):
    @register(app, "/_clock/set_current_utc", "POST", ADMIN, schema=SET_SCHEMA)
    def set_clock(ctx):
        target = parse_iso(ctx.body["to_iso8601"])
        domain.require(target >= store.clock, "ERR_CLOCK_NOT_MONOTONIC",
                       "the logical clock never moves backwards")
        store.clock = target
        return object_response({"current_utc": domain.clock_iso()})

    @register(app, "/_clock", "GET", ALL_ROLES)
    def get_clock(ctx):
        return object_response({"current_utc": domain.clock_iso()})
