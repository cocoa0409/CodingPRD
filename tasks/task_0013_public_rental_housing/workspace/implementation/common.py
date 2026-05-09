"""Shared helpers: entity stamping, pagination, OCC, body parsing."""
from flask import request

from db import db, new_id, now_iso
from errors import api_error


# ---------- Entity life-cycle stamps ----------

def stamp_new(entity: dict, with_version: bool = True) -> dict:
    """Stamp a new entity with id, created_at, updated_at, version."""
    now = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> None:
    """Refresh updated_at and bump version (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def check_version(entity: dict, body: dict | None) -> None:
    """OCC check (PRD §2.4): if body has 'version', it must equal entity.version."""
    if not body:
        return
    ver = body.get("version", None)
    if ver is None:
        return
    try:
        ver_int = int(ver)
    except (TypeError, ValueError):
        raise api_error("ERR_VERSION_MISMATCH", "version mismatch")
    if ver_int != entity.get("version"):
        raise api_error("ERR_VERSION_MISMATCH", "version mismatch")


# ---------- Pagination (PRD §2.3) ----------

def paginate(items: list, sort_key=None):
    """Parse limit/offset, sort by created_at asc / id asc, return (page, meta)."""
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_INVALID_REQUEST", "invalid limit/offset")
    if limit < 1 or limit > 100:
        raise api_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise api_error("ERR_INVALID_REQUEST", "offset must be >= 0")

    if sort_key is None:
        sort_key = lambda x: (x.get("created_at", ""), x.get("id", ""))
    items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


# ---------- Body parsing ----------

def get_json_body() -> dict:
    """Return the JSON body as a dict, or {} if absent / non-object."""
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise api_error("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def require_int(body: dict, name: str, *, minimum: int | None = None,
                maximum: int | None = None) -> int:
    val = require_field(body, name)
    try:
        v = int(val)
    except (TypeError, ValueError):
        raise api_error("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise api_error("ERR_INVALID_REQUEST", f"{name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise api_error("ERR_INVALID_REQUEST", f"{name} must be <= {maximum}")
    return v


# ---------- Existence helpers ----------

def get_program_or_404(program_id: str) -> dict:
    p = db.programs.get(program_id)
    if not p:
        raise api_error("ERR_PROGRAM_NOT_FOUND", "HousingProgram not found")
    return p


def get_application_or_404(program_id: str, app_id: str) -> dict:
    a = db.applications.get(app_id)
    if not a or a.get("housing_program_id") != program_id:
        raise api_error("ERR_APPLICATION_NOT_FOUND", "Application not found")
    return a


def get_housing_unit_or_404(program_id: str, unit_id: str) -> dict:
    u = db.housing_units.get(unit_id)
    if not u or u.get("housing_program_id") != program_id:
        raise api_error("ERR_HOUSING_UNIT_NOT_FOUND", "HousingUnit not found")
    return u


def get_allocation_or_404(program_id: str, alloc_id: str) -> dict:
    a = db.allocations.get(alloc_id)
    if not a or a.get("housing_program_id") != program_id:
        raise api_error("ERR_ALLOCATION_NOT_FOUND", "Allocation not found")
    return a


def get_objection_or_404(allocation_id: str, obj_id: str) -> dict:
    o = db.objections.get(obj_id)
    if not o or o.get("allocation_id") != allocation_id:
        raise api_error("ERR_OBJECTION_NOT_FOUND", "Objection not found")
    return o


def get_contract_or_404(program_id: str, contract_id: str) -> dict:
    c = db.contracts.get(contract_id)
    if not c:
        raise api_error("ERR_CONTRACT_NOT_FOUND", "Contract not found")
    # Verify the contract's chain belongs to this program by walking allocation -> program
    alloc = db.allocations.get(c.get("allocation_id"))
    if not alloc or alloc.get("housing_program_id") != program_id:
        raise api_error("ERR_CONTRACT_NOT_FOUND", "Contract not found")
    return c


def get_rent_reduction_or_404(program_id: str, rr_id: str) -> dict:
    rr = db.rent_reductions.get(rr_id)
    if not rr:
        raise api_error("ERR_RENT_REDUCTION_NOT_FOUND", "RentReduction not found")
    contract = db.contracts.get(rr.get("contract_id"))
    if not contract:
        raise api_error("ERR_RENT_REDUCTION_NOT_FOUND", "RentReduction not found")
    alloc = db.allocations.get(contract.get("allocation_id"))
    if not alloc or alloc.get("housing_program_id") != program_id:
        raise api_error("ERR_RENT_REDUCTION_NOT_FOUND", "RentReduction not found")
    return rr


def get_annual_review_or_404(application_id: str, review_id: str) -> dict:
    r = db.annual_reviews.get(review_id)
    if not r or r.get("application_id") != application_id:
        raise api_error("ERR_ANNUAL_REVIEW_NOT_FOUND", "AnnualReview not found")
    return r


def get_sync_event_or_404(program_id: str, event_id: str) -> dict:
    e = db.sync_events.get(event_id)
    if not e or e.get("housing_program_id") != program_id:
        raise api_error("ERR_SYNC_EVENT_NOT_FOUND", "SyncEvent not found")
    return e
