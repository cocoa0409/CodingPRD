"""Cross-cutting request helpers: RBAC, pagination, body parsing, existence,
client ownership. Validation ordering follows PRD §2.12."""
from flask import request

from db import db
from errors import (
    err,
    ERR_UNAUTHORIZED,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0


# --------------------------------------------------------------------------
# RBAC (priority 2 — role permission)
# --------------------------------------------------------------------------
def require_role(caller, *allowed_roles):
    """Reject if the caller's role is not among allowed_roles (PRD §2.1)."""
    if caller.role not in allowed_roles:
        raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation")


# --------------------------------------------------------------------------
# Existence resolution (priority 3 — left to right in the path, §2.9)
# --------------------------------------------------------------------------
def get_or_404(table, _id, msg="Resource not found"):
    rec = table.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, msg)
    return rec


def get_studio(studio_id):
    return get_or_404(db.studios, studio_id, "Studio not found")


def get_project_in_studio(studio_id, project_id):
    get_studio(studio_id)
    proj = get_or_404(db.projects, project_id, "Project not found")
    if proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Project not found in this studio")
    return proj


def get_child_in_project(table, child_id, project_id, label):
    rec = get_or_404(table, child_id, f"{label} not found")
    if rec["project_id"] != project_id:
        raise err(ERR_NOT_FOUND, f"{label} not found in this project")
    return rec


def get_retainer_in_studio(studio_id, retainer_id):
    get_studio(studio_id)
    return get_or_404(db.retainers, retainer_id, "Retainer not found")


def get_carecycle_in_retainer(retainer_id, cycle_id):
    cyc = get_or_404(db.care_cycles, cycle_id, "CareCycle not found")
    if cyc["retainer_id"] != retainer_id:
        raise err(ERR_NOT_FOUND, "CareCycle not found on this retainer")
    return cyc


# --------------------------------------------------------------------------
# Client ownership (priority 2 — entity_backed Client, §2.1)
# --------------------------------------------------------------------------
def project_client_id(project):
    return project.get("client_id")


def require_client_owns_project(caller, project):
    """An entity-backed Client may only act on resources tracing back to its own
    client_id (PRD §2.1). Opaque roles are unaffected."""
    if caller.role == "Client":
        if project_client_id(project) != caller.user_id:
            raise err(ERR_UNAUTHORIZED, "Client does not own this resource")


def require_client_owns_client(caller, client_rec):
    if caller.role == "Client":
        if client_rec["id"] != caller.user_id:
            raise err(ERR_UNAUTHORIZED, "Client does not own this resource")


# --------------------------------------------------------------------------
# Request body / well-formedness (priority 4 — §2.12)
# --------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body, or {} when there is no body. Malformed JSON
    raises ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed request body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {n}")


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return value


def as_string(value, name):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_enum(value, name, allowed):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


def require_nonneg_int(value, name):
    v = as_int(value, name)
    if v < 0:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= 0")
    return v


# --------------------------------------------------------------------------
# Pagination (priority 4-ish — bad params are ERR_INVALID_REQUEST, §2.3)
# --------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err(ERR_INVALID_REQUEST,
                      f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < MIN_OFFSET:
            raise err(ERR_INVALID_REQUEST, f"offset must be >= {MIN_OFFSET}")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (tie-break by internal _seq) and slice.

    PRD §2.3: list endpoints return resources sorted by created_at ascending.
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
