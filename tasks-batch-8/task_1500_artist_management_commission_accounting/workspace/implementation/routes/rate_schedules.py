"""CommissionRateSchedule endpoints (PRD 3.2): half-open effective windows."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_RATE_SCHEDULE_OVERLAP,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.calculations import schedule_windows_conflict
from services.core import new_record, touch
from util import parse_date
from validate import (
    get_body, opt_date, req_date, req_enum, req_int, req_str, require_path_resource, require_ref,
)

bp = Blueprint("rate_schedules", __name__)

INCOME_TYPES = {"TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT"}


def _check_overlap(agreement_id, income_type, from_date, to_date, exclude_id=None):
    new_from = parse_date(from_date)
    new_to = parse_date(to_date) if to_date else None
    for s in db["rate_schedules"].values():
        if s["agreement_id"] != agreement_id or s["income_type"] != income_type:
            continue
        if exclude_id and s["id"] == exclude_id:
            continue
        s_from = parse_date(s["effective_from_date"])
        s_to = parse_date(s["effective_to_date"]) if s.get("effective_to_date") else None
        if schedule_windows_conflict(new_from, new_to, s_from, s_to):
            raise_error(ERR_RATE_SCHEDULE_OVERLAP,
                        "half-open effective window collides with an existing schedule")


@bp.post("/rate-schedules")
def create_schedule():
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    agreement = require_ref("agreements", agreement_id, "agreement_id")
    caller = scoped_mutation_auth(["FirmAdmin", "BusinessManager"],
                                  body_artist_id=agreement["artist_id"])
    income_type = req_enum(body, "income_type", INCOME_TYPES)
    in_term_rate_bps = req_int(body, "in_term_rate_bps", minimum=0, maximum=10000)
    sunset_rate_bps = req_int(body, "sunset_rate_bps", minimum=0, maximum=10000)
    if sunset_rate_bps > in_term_rate_bps:
        raise_error(ERR_INVALID_REQUEST, "sunset_rate_bps must be <= in_term_rate_bps")
    sunset_months = req_int(body, "sunset_months", non_negative=True)
    effective_from = req_date(body, "effective_from_date")
    effective_to = opt_date(body, "effective_to_date")
    if effective_to is not None and parse_date(effective_to) <= parse_date(effective_from):
        raise_error(ERR_INVALID_REQUEST, "effective_to_date must be later than effective_from_date")

    _check_overlap(agreement_id, income_type, effective_from, effective_to)

    rec = new_record("rate_schedules", {
        "agreement_id": agreement_id,
        "income_type": income_type,
        "in_term_rate_bps": in_term_rate_bps,
        "sunset_rate_bps": sunset_rate_bps,
        "sunset_months": sunset_months,
        "effective_from_date": effective_from,
        "effective_to_date": effective_to,
    })
    return success_object(public(rec), status=201)


@bp.get("/rate-schedules/<rid>")
def get_schedule(rid):
    rec = require_path_resource("rate_schedules", rid)
    return get_one("rate_schedules", rid)


@bp.get("/rate-schedules")
def list_schedules():
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "income_type": request.args.get("income_type"),
    }
    return list_response("rate_schedules", filters, scope_artist_field=None) \
        if False else _list_schedules_scoped(filters)


def _list_schedules_scoped(filters):
    """Rate schedules have no artist_id field; scope through their agreement."""
    from middleware import get_caller, check_role_allowed, resolve_entity_backed, check_team_active
    from routes.helpers import ALL_READ_ROLES
    from response import success_list
    from routes.helpers import get_pagination

    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    resolve_entity_backed(caller)
    check_team_active(caller)

    items = list(db["rate_schedules"].values())
    if caller.role in ("Agent", "BusinessManager", "Publicist", "Artist"):
        scope = caller.artist_scope_id
        items = [
            s for s in items
            if (db["agreements"].get(s["agreement_id"]) or {}).get("artist_id") == scope
        ]
    for field, value in filters.items():
        if value is None:
            continue
        items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/rate-schedules/<rid>/close")
def close_schedule(rid):
    caller = scoped_mutation_auth(["FirmAdmin", "BusinessManager"], "rate_schedules", rid)
    body = get_body()
    sched = require_path_resource("rate_schedules", rid)
    effective_to = req_date(body, "effective_to_date")
    if parse_date(effective_to) <= parse_date(sched["effective_from_date"]):
        raise_error(ERR_INVALID_REQUEST, "effective_to_date must be later than effective_from_date")
    _check_overlap(sched["agreement_id"], sched["income_type"],
                   sched["effective_from_date"], effective_to, exclude_id=sched["id"])
    sched["effective_to_date"] = effective_to
    touch(sched)
    return success_object(public(sched))
