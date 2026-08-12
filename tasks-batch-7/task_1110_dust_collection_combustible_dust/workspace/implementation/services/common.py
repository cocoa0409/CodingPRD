"""Shared service helpers: entity CRUD plumbing, serialization, pagination,
system auto-transitions on clock advance."""
from datetime import datetime, timezone, timedelta

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import success_list
from services import calculations as calc


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def parse_body():
    if not request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            return {}
        return data
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def parse_iso(value, field):
    """Parse an ISO 8601 timestamp; returns timezone-aware datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string", 400)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 timestamp", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def validate_enum(body, field, allowed):
    if field in body and body[field] is not None and body[field] not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field} must be one of {sorted(allowed)}",
            400,
        )


def validate_number(body, field, gt=None, ge=None):
    if field not in body or body[field] is None:
        return
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a number", 400)
    if gt is not None and not v > gt:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be > {gt}", 400)
    if ge is not None and not v >= ge:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {ge}", 400)


def validate_int(body, field, gt=None, ge=None):
    if field not in body or body[field] is None:
        return
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    if gt is not None and not v > gt:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be > {gt}", 400)
    if ge is not None and not v >= ge:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {ge}", 400)


def validate_str(body, field):
    if field in body and body[field] is not None and not isinstance(body[field], str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string", 400)


# ---------------------------------------------------------------------------
# Common field plumbing
# ---------------------------------------------------------------------------
def init_common(entity):
    entity["id"] = db.new_id()
    entity["created_at"] = db.now_iso()
    entity["updated_at"] = db.now_iso()
    entity["version"] = 1


def touch(entity):
    entity["updated_at"] = db.now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Serialization — strip private *_dt fields
# ---------------------------------------------------------------------------
def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.endswith("_dt")}


def serialize_list(entities):
    return [serialize(e) for e in entities]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items, filters=None):
    """Apply query filters + limit/offset. Returns Flask response."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)

    filtered = items
    if filters:
        for param, key in filters.items():
            val = request.args.get(param)
            if val is not None:
                filtered = [e for e in filtered if str(e.get(key)) == val]

    filtered = sorted(filtered, key=lambda e: (e["created_at"], e["id"]))
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_site_or_404(site_id):
    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_NOT_FOUND, f"Site {site_id} not found", 404)
    return site


def get_child_or_404(store, child_id, parent_key, parent_id, what):
    child = store.get(child_id)
    if child is None or child.get(parent_key) != parent_id:
        raise ApiError(ERR_NOT_FOUND, f"{what} {child_id} not found", 404)
    return child


def get_flat_or_404(store, entity_id, what):
    ent = store.get(entity_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, f"{what} {entity_id} not found", 404)
    return ent


# ---------------------------------------------------------------------------
# System auto-transitions on clock advance
# ---------------------------------------------------------------------------
def run_system_transitions():
    """After clock advance: HousekeepingAudit -> OVERDUE, HotWorkPermit ->
    EXPIRED, CAPAAction -> OVERDUE, plus downstream recomputes."""
    now = db.now_dt()
    affected_sites = set()

    # HousekeepingAudit SCHEDULED -> OVERDUE when now > scheduled_for + frequency_hours
    for audit in list(db.housekeeping_audits.values()):
        if audit["status"] != "SCHEDULED":
            continue
        program = db.housekeeping_programs.get(audit["program_id"])
        if program is None:
            continue
        sched = audit.get("scheduled_for_dt")
        if sched is None:
            continue
        if now > sched + timedelta(hours=program["frequency_hours"]):
            audit["status"] = "OVERDUE"
            touch(audit)
            site = db.sites.get(program["site_id"])
            if site:
                affected_sites.add(site["id"])

    # HotWorkPermit ISSUED -> EXPIRED when now > valid_to
    for permit in list(db.hot_work_permits.values()):
        if permit["status"] != "ISSUED":
            continue
        valid_to = permit.get("valid_to_dt")
        if valid_to is not None and now > valid_to:
            permit["status"] = "EXPIRED"
            touch(permit)
            site = db.sites.get(permit["site_id"])
            if site:
                auto_create_finding(site, "MINOR", permit.get("collector_id"),
                                    "Hot-work permit expired without being started")
                affected_sites.add(site["id"])

    # CAPAAction OPEN/IN_PROGRESS -> OVERDUE when now > due_at
    for capa in list(db.capa_actions.values()):
        if capa["status"] not in ("OPEN", "IN_PROGRESS"):
            continue
        due = capa.get("due_at_dt")
        if due is not None and now > due:
            capa["status"] = "OVERDUE"
            touch(capa)
            incident = db.incidents.get(capa["incident_id"])
            if incident:
                touch(incident)
                affected_sites.add(incident["site_id"])

    # Refresh housekeeping program postures + DHA overdue flags
    for program in db.housekeeping_programs.values():
        old = program.get("current_posture")
        calc.housekeeping_schedule(program)
        if program.get("current_posture") != old:
            touch(program)
            affected_sites.add(program["site_id"])

    for dha in db.dhas.values():
        rdd = dha.get("review_due_at_dt")
        overdue = bool(rdd is not None and rdd < now)
        if dha.get("overdue") != overdue:
            dha["overdue"] = overdue
            touch(dha)

    # Recompute derived counters and posture for affected sites
    for site_id in affected_sites:
        site = db.sites.get(site_id)
        if site is None:
            continue
        calc.recompute_open_overdue_housekeeping(site)
        calc.site_posture_derivation(site)
        touch(site)


# ---------------------------------------------------------------------------
# Auto-create InspectionFinding on most recent OPEN/SUBMITTED Inspection
# ---------------------------------------------------------------------------
def auto_create_finding(site, severity, collector_id, description):
    """Auto-create an InspectionFinding of the given severity on the most
    recent OPEN/SUBMITTED Inspection at the site; create a new OPEN
    Inspection first if none exists."""
    candidates = [
        i for i in db.inspections.values()
        if i["site_id"] == site["id"] and i["status"] in ("OPEN", "SUBMITTED")
    ]
    if candidates:
        candidates.sort(key=lambda i: (i["created_at"], i["id"]))
        inspection = candidates[-1]
    else:
        inspection = {
            "site_id": site["id"],
            "inspector_kind": "INTERNAL",
            "inspector_ref": "system",
            "conducted_at": db.now_iso(),
            "status": "OPEN",
        }
        init_common(inspection)
        db.inspections[inspection["id"]] = inspection

    finding = {
        "inspection_id": inspection["id"],
        "collector_id": collector_id,
        "severity": severity,
        "description": description,
        "due_at": db.now_iso(),
        "status": "OPEN",
    }
    init_common(finding)
    db.inspection_findings[finding["id"]] = finding
    return finding
