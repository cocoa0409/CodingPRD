"""Shared route helpers: body parsing, validation, ownership, pagination, OCC."""
from flask import request

from db import db
from errors import err

# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("GET",):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Existence (priority 3) — left-to-right path resolution
# ---------------------------------------------------------------------------
def find_or_404(collection, _id, label="resource"):
    obj = collection.get(_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    return obj


# ---------------------------------------------------------------------------
# Field validation (priority 5: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    return v


def require_positive_amount(body, name="amount_cents"):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be greater than zero" % name)
    return v


def require_enum(body, name, members):
    v = body.get(name)
    if v not in members:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(members)))
    return v


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    return v


def optional_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return v


def optional_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
    return v


# ---------------------------------------------------------------------------
# Ownership (priority 4: ERR_NOT_ACCOUNT_OWNER)
# ---------------------------------------------------------------------------
def check_account_owner(account, role, user_id):
    """For Beneficiary / AuthorizedRepresentative acting on an account-scoped
    write. ProgramAdministrator and MedicaidAgency are exempt."""
    if role == "Beneficiary":
        if account["beneficiary_id"] != user_id:
            raise err("ERR_NOT_ACCOUNT_OWNER", "Beneficiary does not own this account")
    elif role == "AuthorizedRepresentative":
        rep = db.authorized_representatives.get(user_id)
        if (rep is None or rep["account_id"] != account["id"]
                or rep["status"] != "ACTIVE"):
            raise err("ERR_NOT_ACCOUNT_OWNER",
                      "Not an active representative of this account")


# ---------------------------------------------------------------------------
# Optimistic concurrency (priority 7: ERR_STALE_ACCOUNT_VERSION)
# ---------------------------------------------------------------------------
def check_occ(body, account):
    expected = body.get("expected_account_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST",
                  "Field expected_account_version must be an integer")
    if expected != account["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION",
                  "expected_account_version does not match the account version")


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------
def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """Sort by created_at asc (_seq tiebreak) and slice by pagination params."""
    limit, offset = get_pagination()
    ordered = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
