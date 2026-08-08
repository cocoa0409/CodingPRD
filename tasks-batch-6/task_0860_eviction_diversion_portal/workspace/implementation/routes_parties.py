"""Bootstrap / configuration routes: clock, courts, landlords, tenants, officers."""

from flask import request

import envelope
import services
import store
from common import (authorize, get_body, lookup, require_int, require_str)

ALL_ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge", "ProgramAdmin", "Sheriff"}


def register(app):
    # ----- logical clock -----
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authorize({"Clerk"}, exempt_when_no_auth=True)
        body = get_body()
        raw = body.get("to_iso8601")
        if raw is None:
            from errors import ApiError
            raise ApiError("ERR_VALIDATION", "Missing required field: to_iso8601")
        try:
            dt = store.parse_dt(raw)
        except Exception:
            from errors import ApiError
            raise ApiError("ERR_VALIDATION", "to_iso8601 must be ISO-8601")
        store.set_clock(dt)
        return envelope.empty_success(200)

    # ----- courts -----
    @app.route("/courts", methods=["POST"])
    def create_court():
        authorize({"Clerk"}, exempt_when_no_auth=True)
        body = get_body()
        name = require_str(body, "name")
        jurisdiction = require_str(body, "jurisdiction_code")
        capacity = require_int(body, "hearing_daily_capacity", minimum=1)
        court = services.new_entity("courts", versioned=True)
        court["name"] = name
        court["jurisdiction_code"] = jurisdiction
        court["hearing_daily_capacity"] = capacity
        court["hearings_scheduled_count"] = 0
        return envelope.created(court)

    @app.route("/courts/<court_id>", methods=["GET"])
    def get_court(court_id):
        authorize(ALL_ROLES)
        return envelope.success(lookup("courts", court_id))

    # ----- landlords -----
    @app.route("/landlords", methods=["POST"])
    def create_landlord():
        authorize({"Clerk"}, exempt_when_no_auth=True)
        body = get_body()
        name = require_str(body, "name")
        email = require_str(body, "email")
        ll = services.new_entity("landlords", versioned=False)
        ll["name"] = name
        ll["email"] = email
        return envelope.created(ll)

    @app.route("/landlords/<landlord_id>", methods=["GET"])
    def get_landlord(landlord_id):
        authorize(ALL_ROLES)
        return envelope.success(lookup("landlords", landlord_id))

    # ----- tenants -----
    @app.route("/tenants", methods=["POST"])
    def create_tenant():
        authorize({"Clerk"}, exempt_when_no_auth=True)
        body = get_body()
        name = require_str(body, "name")
        email = require_str(body, "email")
        income = require_int(body, "household_income_cents", minimum=0)
        size = require_int(body, "household_size", minimum=1)
        t = services.new_entity("tenants", versioned=False)
        t["name"] = name
        t["email"] = email
        t["household_income_cents"] = income
        t["household_size"] = size
        return envelope.created(t)

    @app.route("/tenants/<tenant_id>", methods=["GET"])
    def get_tenant(tenant_id):
        authorize(ALL_ROLES)
        return envelope.success(lookup("tenants", tenant_id))

    # ----- officers -----
    @app.route("/officers", methods=["POST"])
    def create_officer():
        authorize({"Clerk"}, exempt_when_no_auth=True)
        body = get_body()
        name = require_str(body, "name")
        badge = require_str(body, "badge_number")
        agency = require_str(body, "agency")
        o = services.new_entity("officers", versioned=False)
        o["name"] = name
        o["badge_number"] = badge
        o["agency"] = agency
        return envelope.created(o)

    @app.route("/officers/<officer_id>", methods=["GET"])
    def get_officer(officer_id):
        authorize(ALL_ROLES)
        return envelope.success(lookup("officers", officer_id))
