"""Decedent routes."""
from __future__ import annotations

from flask import Blueprint

import db
from common import (
    get_body,
    iso_format,
    pagination_params,
    parse_iso_datetime,
    require_enum,
    require_field,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import created, list_response, success
from services.cascades import cascade_register_death
from views import view_decedent


bp = Blueprint("decedents", __name__)

VALID_STATES = {"CA", "NY", "TX", "FL", "IL"}


@bp.post("/decedents")
@require_roles("EstatePlanner")
def create_decedent():
    body = get_body()
    full_legal_name = require_string(body, "full_legal_name")
    dob = parse_iso_datetime(require_field(body, "date_of_birth"), "date_of_birth")
    state_code = require_enum(body, "domicile_state_code", VALID_STATES)
    ssn = require_string(body, "ssn_last4")
    if not (ssn.isdigit() and len(ssn) == 4):
        raise APIError(ERR_INVALID_REQUEST, "ssn_last4 must be exactly 4 digits.", 400)

    now = db.now_utc()
    decedent = {
        "full_legal_name": full_legal_name,
        "date_of_birth": dob,
        "date_of_death": None,
        "domicile_state_code": state_code,
        "ssn_last4": ssn,
    }
    stamp_common_fields(decedent, now)
    db.decedents[decedent["id"]] = decedent
    return created(view_decedent(decedent))


@bp.get("/decedents/<dec_id>")
@require_roles("EstatePlanner", "Executor", "Judge", "Beneficiary", "Registrar")
def get_decedent(dec_id: str):
    d = db.decedents.get(dec_id)
    if d is None:
        from errors import not_found
        raise not_found("Decedent")
    return success(view_decedent(d))


@bp.post("/decedents/<dec_id>/register-death")
@require_roles("Registrar")
def register_death(dec_id: str):
    d = db.decedents.get(dec_id)
    if d is None:
        from errors import not_found
        raise not_found("Decedent")

    body = get_body()
    dod = parse_iso_datetime(require_field(body, "date_of_death"), "date_of_death")

    # Determine valid state for the cascade -- date_of_death must be set first.
    # Per PRD §3.3: Estate must be ALIVE for the cascade to occur. If no ALIVE
    # estate exists for this decedent, we still record the date_of_death and
    # silently skip the estate-side cascade; POAs still terminate.
    now = db.now_utc()
    d["date_of_death"] = dod
    touch(d, now)

    cascade_register_death(d, now)
    return success(view_decedent(d))
