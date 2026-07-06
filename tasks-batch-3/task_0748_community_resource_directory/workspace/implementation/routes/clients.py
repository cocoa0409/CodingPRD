from datetime import datetime

from flask import request

from db import db
from errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_VIOLATION,
    raise_error,
)
from middleware import get_auth, require_roles
from response import success
from services import make_client, serialise_client
from util import parse_ts
from validate import (
    ACCESS_ENUM,
    LANG_ENUM,
    require_body,
    require_enum,
    require_enum_subset,
    require_int,
    require_number,
    require_str,
)


def _client_or_404(cid: str):
    c = db.clients.get(cid)
    if not c:
        raise_error(ERR_CLIENT_NOT_FOUND, f"client {cid} not found")
    return c


def _validate_dob(dob: str) -> None:
    # ISO 8601 date, strictly > 1900-01-01, strictly < current logical clock date.
    try:
        d = datetime.strptime(dob, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "date_of_birth must be YYYY-MM-DD")
    lower = datetime(1900, 1, 1).date()
    upper = db.clock.date()
    if not (d > lower):
        raise_error(ERR_INVALID_REQUEST, "date_of_birth must be strictly greater than 1900-01-01")
    if not (d < upper):
        raise_error(ERR_INVALID_REQUEST, "date_of_birth must be strictly less than current clock date")


def register(app):
    @app.post("/clients")
    @require_roles("Caseworker", "PlatformAdmin")
    def create_client():
        body = require_body(request.get_json(silent=True))
        name = require_str(body, "full_name")
        dob = require_str(body, "date_of_birth")
        _validate_dob(dob)
        income = require_int(body, "monthly_income_cents")
        if income < 0:
            raise_error(ERR_INVALID_REQUEST, "monthly_income_cents must be >= 0")
        lat = require_number(body, "home_lat")
        lng = require_number(body, "home_lng")
        if lat < -90.0 or lat > 90.0:
            raise_error(ERR_INVALID_REQUEST, "home_lat out of range")
        if lng < -180.0 or lng > 180.0:
            raise_error(ERR_INVALID_REQUEST, "home_lng out of range")
        pref = require_enum(body, "preferred_language", LANG_ENUM)
        needs = require_enum_subset(body, "accessibility_needs", ACCESS_ENUM, non_empty=False)

        entity = make_client(name, dob, income, lat, lng, pref, needs)
        return success(serialise_client(entity), 201)

    @app.get("/clients/<cid>")
    @require_roles("Client", "Caseworker", "PlatformAdmin")
    def get_client(cid):
        c = _client_or_404(cid)
        uid, role = get_auth()
        if role == "Client" and uid != c["id"]:
            raise_error(ERR_OWNERSHIP_VIOLATION, "Client can only fetch self")
        return success(serialise_client(c), 200)
