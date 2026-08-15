"""Shared helpers: IDs, logical-clock timestamps, body/field validation,
pagination, serialization, and ownership resolution chains (PRD §2)."""
import uuid
from datetime import datetime, timezone

from flask import request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_business_role, forbid_unless_owner
from response import success_list, success_object


def new_id():
    return str(uuid.uuid4())


def iso_z(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Current logical-clock instant as an ISO 8601 UTC stamp (3 fractional digits)."""
    return iso_z(db.now_dt())


def parse_iso_datetime(value, field="datetime"):
    """Parse an ISO 8601 datetime string to an aware datetime (ERR_INVALID_REQUEST)."""
    if not isinstance(value, str):
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            f"{field} must be an ISO 8601 datetime string, got {type(value).__name__}",
            400,
        )
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Unparseable datetime for {field}: {value!r}", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_new(record):
    """Set id, created_at, updated_at, version, and the internal insertion counter."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version on any modification (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def pub(record):
    """Public view of a record — strip internal fields."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Body and field validation (pipeline step 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict; missing body counts as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _present(data, field):
    return field in data and data[field] is not None


def req_str(data, field):
    if not _present(data, field):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    val = data[field]
    if not isinstance(val, str) or not val.strip():
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be a non-empty string", 400)
    return val


def req_int(data, field, minimum=None, maximum=None):
    if not _present(data, field):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not _present(data, field):
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(val, field, minimum, maximum):
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    if minimum is not None and val < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be >= {minimum}", 400)
    if maximum is not None and val > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be <= {maximum}", 400)
    return val


def req_num(data, field, minimum=None, maximum=None, strict_min=False):
    if not _present(data, field):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    return _as_num(data[field], field, minimum, maximum, strict_min)


def opt_num(data, field, default=None, minimum=None, maximum=None, strict_min=False):
    if not _present(data, field):
        return default
    return _as_num(data[field], field, minimum, maximum, strict_min)


def _as_num(val, field, minimum, maximum, strict_min):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be a number", 400)
    if minimum is not None:
        if strict_min and not val > minimum:
            raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be > {minimum}", 400)
        if not strict_min and val < minimum:
            raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be >= {minimum}", 400)
    if maximum is not None and val > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be <= {maximum}", 400)
    return val


def req_enum(data, field, allowed):
    if not _present(data, field):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    val = data[field]
    if val not in allowed:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            f"{field} must be one of {sorted(allowed)}, got {val!r}",
            400,
        )
    return val


def opt_enum(data, field, allowed, default=None):
    if not _present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_bool(data, field):
    if not _present(data, field):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    val = data[field]
    if not isinstance(val, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"{field} must be a boolean", 400)
    return val


def opt_bool(data, field, default=None):
    if not _present(data, field):
        return default
    return req_bool(data, field)


def req_datetime(data, field):
    """Require an ISO 8601 datetime string; returns the raw string (echo fidelity)."""
    if not _present(data, field):
        raise ApiError(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    parse_iso_datetime(data[field], field)
    return data[field]


# ---------------------------------------------------------------------------
# Existence helpers (pipeline step 5: ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def get_or_404(store, rid, what="Resource"):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, f"{what} not found: {rid}", 404)
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0;
# default sort created_at ascending (insertion order breaks logical-clock ties).
# ---------------------------------------------------------------------------

def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


# ---------------------------------------------------------------------------
# Ownership resolution chains (PRD §2.1): every customer-linked resource
# resolves to its owning Customer.id; materials have no owner.
# ---------------------------------------------------------------------------

def owner_of_customer(rec):
    return rec["id"]


def owner_of_material(rec):
    return None


def owner_of_spec(rec):
    return rec.get("customer_id")


def owner_of_cut_program(rec):
    spec = db.package_specs.get(rec.get("package_spec_id"))
    return spec.get("customer_id") if spec else None


def owner_of_tooling(rec):
    prog = db.cut_programs.get(rec.get("cut_program_id"))
    return owner_of_cut_program(prog) if prog else None


def owner_of_drop_test(rec):
    return owner_of_spec(db.package_specs.get(rec.get("package_spec_id"), {}))


def owner_of_production_order(rec):
    return owner_of_spec(db.package_specs.get(rec.get("package_spec_id"), {}))


def owner_of_inventory_program(rec):
    return rec.get("customer_id")


def owner_of_release_order(rec):
    prog = db.inventory_programs.get(rec.get("inventory_program_id"))
    return prog.get("customer_id") if prog else None


def owner_of_scrap_batch(rec):
    order = db.production_orders.get(rec.get("production_order_id"))
    return owner_of_production_order(order) if order else None


# ---------------------------------------------------------------------------
# Generic GET handlers shared by every resource group (PRD §2.1 read access).
# ---------------------------------------------------------------------------

def get_single(store, rid, owner_fn, what):
    user_id, role = get_auth_context()
    require_business_role(role)
    rec = get_or_404(store, rid, what)
    forbid_unless_owner(role, user_id, owner_fn(rec))
    return success_object(pub(rec))


def list_many(store, owner_fn, filter_fields):
    user_id, role = get_auth_context()
    require_business_role(role)
    items = list(store.values())
    for field in filter_fields:
        raw = request.args.get(field)
        if raw is not None:
            items = [r for r in items if r.get(field) is not None and str(r.get(field)) == raw]
    if role == "Customer":
        items = [r for r in items if owner_fn(r) == user_id]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return success_list([pub(r) for r in page], limit, offset, total)
