"""Shared store helpers: timestamps, version bumps, computed fields,
serialization (stripping internal '_' fields), and pagination.
"""
from db import db
from middleware import fmt_iso, parse_iso
from response import array_response


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD 2.4)."""
    entity["updated_at"] = _now_iso()
    if "version" in entity:
        entity["version"] = entity["version"] + 1


def _now_iso():
    from db import clock
    # created_at/updated_at are recorded against the logical server clock so
    # time-gated ordering and tier reference clocks stay consistent under test.
    return fmt_iso(clock.now())


def stamp_new(entity, with_version=True):
    """Stamp created_at (+ updated_at/version) on a freshly created entity."""
    ts = _now_iso()
    entity["created_at"] = ts
    entity["_seq"] = db.next_seq()
    entity["_created_dt"] = parse_iso(ts)
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


# ----- computed fields for Distance / Wave -----

def confirmed_count(distance_id):
    n = 0
    for r in db.registrations.values():
        if r["distance_id"] == distance_id and r["status"] in ("CONFIRMED", "BIB_ASSIGNED", "FINISHED"):
            n += 1
    return n


def charity_confirmed_count(distance_id):
    n = 0
    for r in db.registrations.values():
        if (r["distance_id"] == distance_id and r["entry_type"] == "CHARITY"
                and r["status"] in ("CONFIRMED", "BIB_ASSIGNED", "FINISHED")):
            n += 1
    return n


def wave_assigned_count(wave_id):
    n = 0
    for b in db.bib_assignments.values():
        if b["wave_id"] == wave_id:
            n += 1
    return n


# ----- serialization -----

def _public(entity, computed=None):
    """Strip internal keys (those starting with '_') and merge computed fields."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = v
    if computed:
        out.update(computed)
    return out


def serialize_distance(d):
    cc = confirmed_count(d["id"])
    return _public(d, {
        "confirmed_count": cc,
        "charity_confirmed_count": charity_confirmed_count(d["id"]),
        "waitlist_open": cc >= d["capacity_total"],
    })


def serialize_wave(w):
    return _public(w, {"assigned_count": wave_assigned_count(w["id"])})


def waitlist_queue_position(entry):
    """1-based FIFO position by created_at ASC among QUEUED entries on the
    same distance (PRD 3.3). None if not QUEUED."""
    if entry["status"] != "QUEUED":
        return None
    queued = [e for e in db.waitlist_entries.values()
              if e["distance_id"] == entry["distance_id"] and e["status"] == "QUEUED"]
    queued.sort(key=lambda e: (e["_created_dt"], e["_seq"]))
    for idx, e in enumerate(queued):
        if e["id"] == entry["id"]:
            return idx + 1
    return None


def serialize_waitlist(e):
    return _public(e, {"queue_position": waitlist_queue_position(e)})


def serialize_generic(e):
    return _public(e)


SERIALIZERS = {
    "distance": serialize_distance,
    "wave": serialize_wave,
    "waitlist": serialize_waitlist,
}


def serialize(kind, entity):
    return SERIALIZERS.get(kind, serialize_generic)(entity)


# ----- pagination + sorting -----

def paginate_and_respond(kind, items, args):
    """Sort by created_at ASC (PRD 2.3), apply limit/offset, return array env."""
    from errors import err, ERR_INVALID_REQUEST

    limit = _parse_int_param(args.get("limit"), default=10, name="limit")
    offset = _parse_int_param(args.get("offset"), default=0, name="offset")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    items = sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    data = [serialize(kind, e) for e in page]
    return array_response(data, limit, offset, total)


def _parse_int_param(raw, default, name):
    from errors import err, ERR_INVALID_REQUEST
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer" % name)
