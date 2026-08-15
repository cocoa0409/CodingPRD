"""Shared helpers for entity management, validation, and cascades."""

from datetime import datetime, date, timezone, timedelta
from db import store, new_id
from errors import *


def parse_date(s, field_name="date"):
    """Parse an ISO date string (YYYY-MM-DD). Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(s, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be a string", 400)
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO date", 400)


def parse_datetime(s, field_name="datetime"):
    """Parse an ISO 8601 datetime string. Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(s, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be a string", 400)
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO datetime", 400)


def require_fields(payload: dict, fields: list):
    """Check all required fields are present and not None."""
    if not isinstance(payload, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    for f in fields:
        if f not in payload or payload[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def require_int(payload: dict, field: str):
    val = payload[field]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    return val


def require_str(payload: dict, field: str):
    val = payload[field]
    if not isinstance(val, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string", 400)
    return val


def optional_int(payload: dict, field: str, default=None):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    return val


def optional_str(payload: dict, field: str, default=None):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if not isinstance(val, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string", 400)
    return val


def optional_bool(payload: dict, field: str, default=False):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if not isinstance(val, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a boolean", 400)
    return val


def require_enum(payload: dict, field: str, allowed: list):
    val = payload[field]
    if not isinstance(val, str) or val not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be one of {allowed}", 400)
    return val


def touch(entity: dict):
    """Increment version and refresh updated_at on an entity."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = store.clock.now_iso()


def make_entity(fields: dict) -> dict:
    """Create a new entity with common fields."""
    now = store.clock.now_iso()
    entity = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    entity.update(fields)
    return entity


# ---- Lookup helpers (raise ERR_NOT_FOUND) ----

def get_production(pid: str) -> dict:
    p = store.productions.get(pid)
    if not p:
        raise ApiError(ERR_NOT_FOUND, "Production not found", 404)
    return p


def get_jurisdiction(jid: str) -> dict:
    j = store.jurisdictions.get(jid)
    if not j:
        raise ApiError(ERR_NOT_FOUND, "Jurisdiction not found", 404)
    return j


def get_location(lid: str) -> dict:
    loc = store.locations.get(lid)
    if not loc:
        raise ApiError(ERR_NOT_FOUND, "Location not found", 404)
    return loc


def get_owner(oid: str) -> dict:
    o = store.location_owners.get(oid)
    if not o:
        raise ApiError(ERR_NOT_FOUND, "LocationOwner not found", 404)
    return o


def get_scoped(store_dict: dict, rid: str, production_id: str, label: str) -> dict:
    """Get a child resource, verifying it belongs to the production scope."""
    r = store_dict.get(rid)
    if not r or r.get("production_id") != production_id:
        raise ApiError(ERR_NOT_FOUND, f"{label} not found", 404)
    return r


def get_permit_application(rid: str) -> dict:
    pa = store.permit_applications.get(rid)
    if not pa:
        raise ApiError(ERR_NOT_FOUND, "PermitApplication not found", 404)
    return pa


def get_shoot_day(rid: str) -> dict:
    sd = store.shoot_days.get(rid)
    if not sd:
        raise ApiError(ERR_NOT_FOUND, "ShootDay not found", 404)
    return sd


# ---- Filtered list helper ----

def list_filtered(store_dict: dict, filters: dict = None, production_id: str = None):
    """Return sorted list of entities matching filters.
    Sort by created_at ascending."""
    items = list(store_dict.values())
    if production_id is not None:
        items = [i for i in items if i.get("production_id") == production_id]
    if filters:
        for k, v in filters.items():
            if v is not None:
                items = [i for i in items if str(i.get(k)) == str(v)]
    items.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    return items


def paginate(items: list, limit: int, offset: int):
    """Apply pagination. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def get_pagination_params(args):
    """Parse limit/offset from query string with defaults limit=10, min=1, max=100, offset=0."""
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


# ---- Cascades ----

def cancel_shoot_day_monitors(shoot_day: dict):
    """Release ASSIGNED/CONFIRMED monitor assignments for a shoot day."""
    for ma in store.monitor_assignments.values():
        if ma.get("shoot_day_id") == shoot_day["id"] and ma["status"] in ("ASSIGNED", "CONFIRMED"):
            ma["status"] = "RELEASED"
            touch(ma)


def recompute_monitors_confirmed(shoot_day: dict):
    """Recompute monitors_confirmed on a shoot day."""
    count = sum(1 for ma in store.monitor_assignments.values()
                if ma.get("shoot_day_id") == shoot_day["id"] and ma["status"] == "CONFIRMED")
    shoot_day["monitors_confirmed"] = count


def recompute_compliance(shoot_day: dict):
    """Recompute compliance_status (strict variant: all complaints count)."""
    from services.calculations import shoot_day_compliance
    complaints = [c for c in store.complaints.values()
                  if c.get("shoot_day_id") == shoot_day["id"]]
    shoot_day["compliance_status"] = shoot_day_compliance(
        shoot_day.get("overtime_minutes", 0),
        shoot_day.get("monitors_confirmed", 0),
        shoot_day.get("monitors_required", 0),
        complaints,
    )


def shut_down_shoot_day(shoot_day: dict):
    """Shut down an IN_PROGRESS shoot day and cascade."""
    shoot_day["status"] = "SHUT_DOWN"
    touch(shoot_day)
    # Cancel APPROVED/ACTIVE street closures for this day's permit
    pa_id = shoot_day.get("permit_application_id")
    for sc in store.street_closures.values():
        if sc.get("permit_application_id") == pa_id and sc["status"] in ("APPROVED", "ACTIVE"):
            sc["status"] = "CANCELLED"
            touch(sc)


def supersede_permit_application(old_app: dict):
    """Supersede an ISSUED or CONDITIONALLY_APPROVED permit application."""
    old_app["status"] = "SUPERSEDED"
    touch(old_app)
    if old_app.get("_was_issued"):
        # Cancel REQUESTED/APPROVED street closures
        for sc in store.street_closures.values():
            if sc.get("permit_application_id") == old_app["id"] and sc["status"] in ("REQUESTED", "APPROVED"):
                sc["status"] = "CANCELLED"
                touch(sc)
        # Cancel PLANNED/READY shoot days and release their monitors
        for sd in store.shoot_days.values():
            if sd.get("permit_application_id") == old_app["id"] and sd["status"] in ("PLANNED", "READY"):
                sd["status"] = "CANCELLED"
                touch(sd)
                cancel_shoot_day_monitors(sd)


def find_verified_cert_covering(production_id: str, jurisdiction_id: str,
                                 shoot_start: date, shoot_end: date):
    """Find a VERIFIED insurance cert for (production, jurisdiction) covering the window."""
    for cert in store.insurance_certificates.values():
        if (cert.get("production_id") == production_id
                and cert.get("jurisdiction_id") == jurisdiction_id
                and cert["status"] == "VERIFIED"):
            eff = parse_date(cert["effective_date"])
            exp = parse_date(cert["expiry_date"])
            if eff <= shoot_start and exp >= shoot_end:
                return cert
    return None


def find_verified_cert_covering_date(production_id: str, jurisdiction_id: str,
                                      check_date: date):
    """Find a VERIFIED cert covering a single date."""
    for cert in store.insurance_certificates.values():
        if (cert.get("production_id") == production_id
                and cert.get("jurisdiction_id") == jurisdiction_id
                and cert["status"] == "VERIFIED"):
            eff = parse_date(cert["effective_date"])
            exp = parse_date(cert["expiry_date"])
            if eff <= check_date <= exp:
                return cert
    return None
