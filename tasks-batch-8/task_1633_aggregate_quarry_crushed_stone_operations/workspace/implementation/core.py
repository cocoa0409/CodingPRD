"""Response envelope, auth, common helpers, and the logical clock."""

import random
import string
import uuid
from datetime import datetime, timezone

from flask import request

from db import db
from errors import err_forbidden, err_unauthenticated

ROLES = [
    "QuarryAdmin",
    "SiteManager",
    "BlastForeman",
    "PlantOperator",
    "ScaleHouseOperator",
    "QCTechnician",
    "SalesAgent",
    "FinanceClerk",
    "SafetyOfficer",
]


def new_request_id():
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + rand


def wall_now_iso():
    """Envelope timestamp: server-generated ISO 8601 UTC with 3 fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def logical_now():
    return db.clock


def logical_now_iso():
    """Logical-clock timestamp with 3 fractional digits (used for created_at etc.)."""
    now = db.clock
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def logical_today():
    return db.clock.date()


def new_uuid():
    return str(uuid.uuid4())


def meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def ok_object(data, status=200):
    return {
        "meta": meta(),
        "response_type": "object",
        "data": data,
    }, status


def ok_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return {
        "meta": m,
        "response_type": "array",
        "data": items,
    }, 200


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def get_auth():
    """Tier 1: authentication. Returns (user_id, role) or raises."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    if user_id is None or user_id == "":
        raise err_unauthenticated()
    return user_id, role


def require_roles(allowed):
    """Tier 1+2: authentication then endpoint authorization."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_forbidden()
    return user_id, role


def parse_pagination():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0)."""
    from errors import err_invalid_request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def list_response(collection, filters=None):
    """Filter (equality on fields), sort by created_at ASC, paginate, envelope."""
    items = list(collection.values())
    if filters:
        for key, value in filters.items():
            if value is None:
                continue
            items = [it for it in items if str(it.get(key)) == value]
    items.sort(key=lambda it: (it.get("created_at", ""), it.get("id", "")))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def touch(resource):
    """Refresh updated_at + version on every mutation (incl. cascade touches)."""
    resource["updated_at"] = logical_now_iso()
    resource["version"] = resource.get("version", 0) + 1


def base_resource():
    now = logical_now_iso()
    return {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def body():
    """Return parsed JSON body or raise ERR_INVALID_REQUEST."""
    from errors import err_invalid_request

    if not request.is_json:
        raise err_invalid_request("Request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data
