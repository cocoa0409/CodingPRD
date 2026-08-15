"""Carrier endpoints and the carrier logical-clock control (PRD 2.5, 3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from routes.common import resolve_carrier
from serializers import carrier_view
from services.core import run_clock_transitions
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    parse_iso8601,
)

bp = Blueprint("carriers", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")

CREATE_FIELDS = {"carrier_code", "legal_name", "reinsurance_treaty_attachment_cents"}
CLOCK_FIELDS = {"to_iso8601"}


@bp.route("/carriers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_carrier(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    carrier_code = require_string(body, "carrier_code")
    legal_name = require_string(body, "legal_name")
    attachment = require_int(body, "reinsurance_treaty_attachment_cents", minimum=0)

    for other in db.carriers.values():
        if other["carrier_code"] == carrier_code:
            raise_err(ERR_INVALID_REQUEST,
                      f"carrier_code {carrier_code} already exists")

    carrier = db.stamp_new({
        "carrier_code": carrier_code,
        "legal_name": legal_name,
        "current_utc": db.CLOCK_DEFAULT,
        "reinsurance_treaty_attachment_cents": attachment,
        "_policy_seq": 0,
    }, db.CLOCK_DEFAULT)
    db.carriers[carrier["id"]] = carrier
    return success_object(carrier_view(carrier), 201)


@bp.route("/carriers/<carrierId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_carrier(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    return success_object(carrier_view(carrier))


@bp.route("/carriers/<carrierId>/_clock/set_current_utc", methods=["POST"])
@require_roles("Underwriter")
def set_current_utc(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    body = get_json_body()
    reject_unknown_fields(body, CLOCK_FIELDS)
    value = require_string(body, "to_iso8601")
    parse_iso8601(value, "to_iso8601")  # validates; the verbatim string is stored

    carrier["current_utc"] = value
    db.touch(carrier, value)
    run_clock_transitions(carrier)
    return success_object(carrier_view(carrier))
