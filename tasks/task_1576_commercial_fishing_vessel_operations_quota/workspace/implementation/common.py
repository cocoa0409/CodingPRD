"""Shared helpers: response envelope, auth, pagination, field validation."""

import random
import string

from flask import jsonify, request

from errors import ApiError
import store

ROLES = [
    "VesselOwner",
    "Captain",
    "CrewMember",
    "Observer",
    "ObserverCoordinator",
    "FisheriesRegulator",
    "SettlementClerk",
]
ALL_ROLES = list(ROLES)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            400,
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must both be present and X-User-Role "
            "must be a declared role",
        )
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(
            403,
            "ERR_FORBIDDEN_ROLE",
            f"role {role} is not permitted on this endpoint",
        )


def not_owner(message="X-User-ID fails the ownership check for this resource"):
    raise ApiError(403, "ERR_NOT_RESOURCE_OWNER", message)


# ---------------------------------------------------------------------------
# Body parsing and field validation
# ---------------------------------------------------------------------------

def body():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def f_str(data, name, required=True):
    value = data.get(name)
    if value is None:
        if required:
            raise ApiError(400, "ERR_INVALID_REQUEST", f"missing required field: {name}")
        return None
    if not isinstance(value, str) or value == "":
        raise ApiError(400, "ERR_INVALID_REQUEST", f"field {name} must be a non-empty string")
    return value


def f_int(data, name, minimum=None, required=True):
    value = data.get(name)
    if value is None:
        if required:
            raise ApiError(400, "ERR_INVALID_REQUEST", f"missing required field: {name}")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(400, "ERR_INVALID_REQUEST", f"field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError(400, "ERR_INVALID_REQUEST", f"field {name} must be >= {minimum}")
    return value


def f_number(data, name, required=True):
    value = data.get(name)
    if value is None:
        if required:
            raise ApiError(400, "ERR_INVALID_REQUEST", f"missing required field: {name}")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "ERR_INVALID_REQUEST", f"field {name} must be a number")
    return value


def f_enum(data, name, values, required=True):
    value = data.get(name)
    if value is None:
        if required:
            raise ApiError(400, "ERR_INVALID_REQUEST", f"missing required field: {name}")
        return None
    if value not in values:
        raise ApiError(
            400,
            "ERR_INVALID_REQUEST",
            f"field {name} must be one of {sorted(values)}",
        )
    return value


def f_dt(data, name, required=True):
    value = data.get(name)
    if value is None:
        if required:
            raise ApiError(400, "ERR_INVALID_REQUEST", f"missing required field: {name}")
        return None
    return store.parse_dt(value)


# ---------------------------------------------------------------------------
# Pagination and listing
# ---------------------------------------------------------------------------

def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


def list_response(collection, filters=None):
    """filters: list of (field_name, query_arg_string) to exact-match."""
    items = list(collection)
    if filters:
        for field, raw in filters:
            if raw is None:
                continue
            items = [e for e in items if str(e.get(field)) == raw]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def make_entity(fields):
    entity = dict(fields)
    entity["id"] = store.new_id()
    ts = store.now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    return entity


def make_event(fields):
    """Append-only event record: id + created_at only (no updated_at/version)."""
    event = dict(fields)
    event["id"] = store.new_id()
    event["created_at"] = store.now_iso()
    event["_seq"] = store.next_seq()
    return event


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = store.now_iso()


def pub(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Existence helpers (404 family)
# ---------------------------------------------------------------------------

def _get(collection, rid, error_id, label):
    entity = collection.get(rid if isinstance(rid, str) else "")
    if entity is None:
        raise ApiError(404, error_id, f"{label} not found: {rid}")
    return entity


def get_vessel(rid):
    return _get(store.db.vessels, rid, "ERR_VESSEL_NOT_FOUND", "vessel")


def get_permit(rid):
    return _get(store.db.permits, rid, "ERR_PERMIT_NOT_FOUND", "permit")


def get_holding(rid):
    return _get(store.db.holdings, rid, "ERR_QUOTA_HOLDING_NOT_FOUND", "quota holding")


def get_opening(rid):
    return _get(store.db.openings, rid, "ERR_SEASON_OPENING_NOT_FOUND", "season opening")


def get_trip(rid):
    return _get(store.db.trips, rid, "ERR_TRIP_NOT_FOUND", "fishing trip")


def get_declaration(rid):
    return _get(store.db.declarations, rid, "ERR_LANDING_DECLARATION_NOT_FOUND", "landing declaration")


def get_transfer(rid):
    return _get(store.db.transfers, rid, "ERR_TRANSFER_NOT_FOUND", "quota transfer")


def get_observer(rid):
    return _get(store.db.observers, rid, "ERR_OBSERVER_NOT_FOUND", "observer")


def get_assignment(rid):
    return _get(store.db.assignments, rid, "ERR_ASSIGNMENT_NOT_FOUND", "observer assignment")


def get_crew_contract(rid):
    return _get(store.db.crew_contracts, rid, "ERR_CREW_CONTRACT_NOT_FOUND", "crew share contract")


def get_expense(rid):
    return _get(store.db.expenses, rid, "ERR_EXPENSE_NOT_FOUND", "expense record")


def get_settlement(rid):
    return _get(store.db.settlements, rid, "ERR_SETTLEMENT_NOT_FOUND", "trip settlement")


def get_gear_asset(rid):
    return _get(store.db.gear_assets, rid, "ERR_GEAR_ASSET_NOT_FOUND", "gear asset")


def get_violation(rid):
    return _get(store.db.violations, rid, "ERR_VIOLATION_NOT_FOUND", "compliance violation")


def find_holding(vessel_id, fishery_code, season_year):
    for h in store.db.holdings.values():
        if (
            h["vessel_id"] == vessel_id
            and h["fishery_code"] == fishery_code
            and h["season_year"] == season_year
        ):
            return h
    return None


def vessel_has_issued_permit(vessel_id, fishery_code):
    for p in store.db.permits.values():
        if (
            p["vessel_id"] == vessel_id
            and p["fishery_code"] == fishery_code
            and p["status"] == "ISSUED"
        ):
            return True
    return False
