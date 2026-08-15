"""Shared cross-resource helpers: 404 resolution, fair derivation, certification
validity, covering-shift checks, list pagination, and common cascade pieces."""
from datetime import timedelta

import db
from db import store, sort_key, serialize, touch
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NO_COVERING_SHIFT,
)
from response import ok_list
from flask import request


# ---------------------------------------------------------------------------
# Existence (family 4/6)
# ---------------------------------------------------------------------------

def get_or_404(collection, entity_id):
    entity = db.get(collection, entity_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "No %s with id %s" % (collection, entity_id))
    return entity


# ---------------------------------------------------------------------------
# Fair derivation for scoping / cross-fair checks
# ---------------------------------------------------------------------------

def fair_id_of_ride(ride):
    return ride["fair_id"] if ride else None


def fair_id_of_day(day):
    return day["fair_id"] if day else None


def fair_id_of_checklist(checklist):
    ride = db.get("rides", checklist["ride_id"])
    return ride["fair_id"] if ride else None


def fair_id_of_cycle(cycle):
    ride = db.get("rides", cycle["ride_id"])
    return ride["fair_id"] if ride else None


def fair_id_of_redemption(redemption):
    ride = db.get("rides", redemption["ride_id"])
    return ride["fair_id"] if ride else None


def fair_id_of_sale(sale):
    day = db.get("operating_days", sale["operating_day_id"])
    return day["fair_id"] if day else None


def fair_id_of_observation(obs):
    day = db.get("operating_days", obs["operating_day_id"])
    return day["fair_id"] if day else None


def fair_id_of_incident(incident):
    ride = db.get("rides", incident["ride_id"])
    return ride["fair_id"] if ride else None


def fair_id_of_cert(cert):
    staff = db.get("staff", cert["staff_id"])
    return staff["fair_id"] if staff else None


# ---------------------------------------------------------------------------
# Certification validity
# ---------------------------------------------------------------------------

def has_valid_certification(staff_id, ride_class):
    """A certification is valid exactly when status == ACTIVE and
    expires_on >= the current logical date (evaluated at enforcement time)."""
    today = db.today_str()
    for cert in store["certifications"].values():
        if (
            cert["staff_id"] == staff_id
            and cert["ride_class"] == ride_class
            and cert["status"] == "ACTIVE"
            and cert["expires_on"] >= today
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Covering crew shift
# ---------------------------------------------------------------------------

def has_covering_shift(staff_id, shift_role):
    today = db.today_str()
    for shift in store["shifts"].values():
        if (
            shift["staff_id"] == staff_id
            and shift["shift_role"] == shift_role
            and shift["work_date"] == today
            and shift["status"] in ("SCHEDULED", "CONFIRMED")
        ):
            return True
    return False


def require_covering_shift(staff_id, shift_role):
    if not has_covering_shift(staff_id, shift_role):
        raise_err(
            ERR_NO_COVERING_SHIFT,
            "Caller lacks a covering %s shift on the current date" % shift_role,
        )


# ---------------------------------------------------------------------------
# Season windows for crew shifts
# ---------------------------------------------------------------------------

def shift_season_window(fair, shift_role):
    """[start, end] inclusive date window for a shift role."""
    opening = _parse_date(fair["opening_date"])
    closing = _parse_date(fair["closing_date"])
    if shift_role == "SETUP":
        start = _parse_date(fair["setup_start_date"])
        end = opening - timedelta(days=1)
    elif shift_role == "OPERATIONS":
        start = opening
        end = closing
    else:  # TEARDOWN
        start = closing + timedelta(days=1)
        end = _parse_date(fair["teardown_end_date"])
    return start, end


def _parse_date(s):
    from datetime import datetime

    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# Pagination (family: list endpoints; limit 1..100 default 10, offset >= 0)
# ---------------------------------------------------------------------------

def paginate(collection, filters):
    items = [e for e in store[collection].values() if _matches(e, filters)]
    items.sort(key=sort_key)
    limit, offset = _pagination_params()
    total = len(items)
    page = [serialize(e) for e in items[offset : offset + limit]]
    return ok_list(page, limit, offset, total)


def _matches(entity, filters):
    for key, value in filters.items():
        if value is None:
            continue
        if entity.get(key) != value:
            return False
    return True


def _pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not (
            isinstance(raw_limit, str) and raw_limit.strip().lstrip("+").isdigit()
        ):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if isinstance(raw_offset, str) and not raw_offset.strip().lstrip("+").isdigit():
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def qparam(name):
    return request.args.get(name)
