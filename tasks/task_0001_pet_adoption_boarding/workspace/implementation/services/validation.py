"""Common request body / existence validation helpers."""

from flask import request

from errors import (
    APIError, raise_err,
    ERR_INVALID_REQUEST,
    ERR_SHELTER_NOT_FOUND,
    ERR_ANIMAL_NOT_FOUND,
    ERR_ADOPTER_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_HOME_VISIT_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_SETTLEMENT_NOT_FOUND,
)
from db import store, parse_dt


def get_json_body(required=False):
    try:
        body = request.get_json(silent=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "JSON body required")
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


def require_field(body, field, types=None, allow_none=False):
    if field not in body:
        raise_err(ERR_INVALID_REQUEST, f"Missing field: {field}")
    v = body[field]
    if v is None and not allow_none:
        raise_err(ERR_INVALID_REQUEST, f"Field cannot be null: {field}")
    if types is not None and not isinstance(v, types):
        raise_err(ERR_INVALID_REQUEST, f"Invalid type for field: {field}")
    return v


def require_enum(body, field, allowed):
    v = require_field(body, field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Invalid enum value for {field}: {v}")
    return v


def get_int_query(name, default=None, min_v=None, max_v=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, f"Invalid {name}")
    if min_v is not None and v < min_v:
        raise_err(ERR_INVALID_REQUEST, f"{name} below minimum")
    if max_v is not None and v > max_v:
        raise_err(ERR_INVALID_REQUEST, f"{name} above maximum")
    return v


def pagination():
    limit = get_int_query("limit", default=50, min_v=1, max_v=200)
    offset = get_int_query("offset", default=0, min_v=0)
    return limit, offset


def get_shelter_or_404(sid):
    rec = store.shelters.get(sid)
    if rec is None:
        raise_err(ERR_SHELTER_NOT_FOUND, f"Shelter {sid} not found")
    return rec


def get_animal_or_404(aid):
    rec = store.animals.get(aid)
    if rec is None:
        raise_err(ERR_ANIMAL_NOT_FOUND, f"Animal {aid} not found")
    return rec


def get_adopter_or_404(aid):
    rec = store.adopters.get(aid)
    if rec is None:
        raise_err(ERR_ADOPTER_NOT_FOUND, f"Adopter {aid} not found")
    return rec


def get_application_or_404(aid):
    rec = store.applications.get(aid)
    if rec is None:
        raise_err(ERR_APPLICATION_NOT_FOUND, f"Application {aid} not found")
    return rec


def get_home_visit_or_404(hvid):
    rec = store.home_visits.get(hvid)
    if rec is None:
        raise_err(ERR_HOME_VISIT_NOT_FOUND, f"HomeVisit {hvid} not found")
    return rec


def get_reservation_or_404(rid):
    rec = store.reservations.get(rid)
    if rec is None:
        raise_err(ERR_RESERVATION_NOT_FOUND, f"Reservation {rid} not found")
    return rec


def get_settlement_or_404(sid):
    rec = store.settlements.get(sid)
    if rec is None:
        raise_err(ERR_SETTLEMENT_NOT_FOUND, f"Settlement {sid} not found")
    return rec


def parse_required_dt(body, field):
    v = require_field(body, field)
    dt = parse_dt(v)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, f"Invalid datetime for {field}")
    return dt
