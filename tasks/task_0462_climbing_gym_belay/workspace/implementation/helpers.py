"""Shared request helpers: pagination, body parsing, lookups, recomputes."""
from flask import request

from db import db
from errors import err
from clock import clock


# ---------------------------------------------------------------------------
# Body / query parsing
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON body as a dict; {} when empty. Malformed JSON -> ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not (request.data or b""):
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def parse_pagination():
    """Parse limit/offset query params with PRD defaults (limit 10 [1..100], offset 0 [>=0])."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")

    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit_v, offset_v


def paginate(items, limit, offset):
    """Sort by created_at ascending, then slice. Returns (page, total_count)."""
    ordered = sorted(items, key=lambda r: (r["_created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def find_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found")
    return m


def find_waiver(wid):
    w = db.waivers.get(wid)
    if w is None:
        raise err("ERR_NOT_FOUND", "Waiver not found")
    return w


def find_membership(mid):
    m = db.memberships.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Membership not found")
    return m


def find_certification(cid):
    c = db.certifications.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Certification not found")
    return c


def find_facility(fid):
    f = db.facilities.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", "Facility not found")
    return f


def find_route(rid):
    r = db.routes.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Route not found")
    return r


def find_check_in(cid):
    c = db.check_ins.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Check-in not found")
    return c


def find_clinic(cid):
    c = db.clinics.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Clinic not found")
    return c


def find_enrollment(eid):
    e = db.enrollments.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    return e


def find_rental(rid):
    r = db.rentals.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Rental not found")
    return r


def find_incident(iid):
    i = db.incidents.get(iid)
    if i is None:
        raise err("ERR_NOT_FOUND", "Incident not found")
    return i


# ---------------------------------------------------------------------------
# Recompute helpers (derived counts)
# ---------------------------------------------------------------------------

def recompute_facility_occupancy(facility_id):
    f = db.facilities.get(facility_id)
    if f is None:
        return
    count = sum(
        1 for c in db.check_ins.values()
        if c["facility_id"] == facility_id and c["status"] == "ON_FLOOR"
    )
    f["occupancy"] = count


def recompute_clinic_count(clinic_id):
    c = db.clinics.get(clinic_id)
    if c is None:
        return
    count = sum(
        1 for e in db.enrollments.values()
        if e["clinic_id"] == clinic_id and e["status"] == "ENROLLED"
    )
    c["enrolled_count"] = count


# ---------------------------------------------------------------------------
# Domain predicates
# ---------------------------------------------------------------------------

def member_has_valid_waiver(member_id):
    now = clock.now()
    for w in db.waivers.values():
        if w["member_id"] == member_id and now < w["expires_at"]:
            return True
    return False


def member_has_active_belay_or_lead(member_id):
    """PASSED, non-expired BELAY or LEAD certification (by clock)."""
    now = clock.now()
    for c in db.certifications.values():
        if c["member_id"] != member_id:
            continue
        if c["discipline"] not in ("BELAY", "LEAD"):
            continue
        if c["status"] == "PASSED" and c["expires_at"] is not None and now < c["expires_at"]:
            return True
    return False


def member_has_passed_belay(member_id):
    """PASSED, non-expired BELAY certification — lead prerequisite."""
    now = clock.now()
    for c in db.certifications.values():
        if c["member_id"] != member_id:
            continue
        if c["discipline"] != "BELAY":
            continue
        if c["status"] == "PASSED" and c["expires_at"] is not None and now < c["expires_at"]:
            return True
    return False


def member_active_membership(member_id):
    """Return a membership with access_status ACTIVE for this member, or None."""
    for m in db.memberships.values():
        if m["member_id"] == member_id and m["access_status"] == "ACTIVE":
            return m
    return None
