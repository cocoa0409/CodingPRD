from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_UNIT_NOT_FOUND, ERR_RESIDENT_NOT_FOUND,
    ERR_LEASE_NOT_FOUND, ERR_LEASE_TERM_OVERLAP, ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.common import new_entity
from timeutil import parse_date, add_months

bp = Blueprint("leases", __name__)


def _serialize(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "unit_id": l["unit_id"],
        "resident_id": l["resident_id"],
        "property_id": l["property_id"],
        "term_start_date": l["term_start_date"],
        "term_months": l["term_months"],
        "term_end_date": l["term_end_date"],
        "monthly_rent_cents": l["monthly_rent_cents"],
        "status": l["status"],
        "status_before_offer": l.get("status_before_offer"),
        "mtm_converted_on": l.get("mtm_converted_on"),
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _overlaps(a_start, a_end, b_start, b_end):
    # half-open intervals [start, end)
    return a_start < b_end and b_start < a_end


@bp.route("/leases", methods=["POST"])
def create_lease():
    require_roles("PlatformAdmin", "PropertyManager")
    body = request.get_json(silent=True) or {}
    unit_id = body.get("unit_id")
    resident_id = body.get("resident_id")
    term_start_date = body.get("term_start_date")
    term_months = body.get("term_months")
    monthly_rent_cents = body.get("monthly_rent_cents")

    # Schema
    if not unit_id or not isinstance(unit_id, str):
        raise_err(ERR_INVALID_REQUEST, "unit_id required")
    if not resident_id or not isinstance(resident_id, str):
        raise_err(ERR_INVALID_REQUEST, "resident_id required")
    if not term_start_date or not isinstance(term_start_date, str):
        raise_err(ERR_INVALID_REQUEST, "term_start_date required")
    try:
        ts = parse_date(term_start_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "term_start_date malformed")
    if not isinstance(term_months, int) or isinstance(term_months, bool) or term_months < 1:
        raise_err(ERR_INVALID_REQUEST, "term_months must be int >= 1")
    if not isinstance(monthly_rent_cents, int) or isinstance(monthly_rent_cents, bool) or monthly_rent_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "monthly_rent_cents must be >= 0")

    # Existence — body FKs
    unit = store.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit not found")
    resident = store.residents.get(resident_id)
    if resident is None:
        raise_err(ERR_RESIDENT_NOT_FOUND, "resident not found")

    # term_end_date computed
    te = add_months(ts, term_months)
    term_end_str = te.strftime("%Y-%m-%d")

    # Overlap check against other non-ENDED leases on same unit
    for l in store.leases.values():
        if l["unit_id"] != unit_id:
            continue
        if l["status"] == "ENDED":
            continue
        existing_start = parse_date(l["term_start_date"])
        existing_end = parse_date(l["term_end_date"])
        if _overlaps(ts, te, existing_start, existing_end):
            raise_err(ERR_LEASE_TERM_OVERLAP, "lease overlaps existing lease on unit")

    rec = new_entity()
    rec.update({
        "unit_id": unit_id,
        "resident_id": resident_id,
        "property_id": unit["property_id"],
        "term_start_date": term_start_date,
        "term_months": term_months,
        "term_end_date": term_end_str,
        "monthly_rent_cents": monthly_rent_cents,
        "status": "ACTIVE",
        "status_before_offer": None,
        "mtm_converted_on": None,
    })
    store.leases[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/leases", methods=["GET"])
def list_leases():
    user_id, role = get_auth()
    if role not in ("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"):
        from errors import ERR_FORBIDDEN_ROLE
        raise_err(ERR_FORBIDDEN_ROLE, "forbidden")
    limit, offset = _get_pagination()
    unit_id = request.args.get("unit_id")
    property_id = request.args.get("property_id")
    resident_id = request.args.get("resident_id")
    status = request.args.get("status")
    items = list(store.leases.values())
    if role == "Resident":
        # Ownership-scoped: only own leases
        items = [l for l in items if l["resident_id"] == user_id]
    if unit_id:
        items = [l for l in items if l["unit_id"] == unit_id]
    if property_id:
        items = [l for l in items if l["property_id"] == property_id]
    if resident_id:
        items = [l for l in items if l["resident_id"] == resident_id]
    if status:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(l) for l in page], limit, offset, total)


@bp.route("/leases/<lid>", methods=["GET"])
def get_lease(lid):
    user_id, role = get_auth()
    if role not in ("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"):
        from errors import ERR_FORBIDDEN_ROLE
        raise_err(ERR_FORBIDDEN_ROLE, "forbidden")
    l = store.leases.get(lid)
    if l is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    if role == "Resident" and l["resident_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "not owner")
    return success_object(_serialize(l))
