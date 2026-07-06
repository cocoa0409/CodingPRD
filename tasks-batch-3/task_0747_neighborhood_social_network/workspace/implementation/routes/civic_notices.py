"""CivicNotice endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from clock import CLOCK, iso_format, parse_iso
from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    InvalidTimeWindow,
    EffectiveFromInPast,
    NoticeWindowOverlap,
    InvalidState,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from validators import as_str, as_enum


bp = Blueprint("civic_notices", __name__)

NOTICE_KINDS = {"POLICE", "FIRE", "PUBLIC_WORKS", "HEALTH", "ELECTION"}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _intervals_overlap(a_from, a_until, b_from, b_until) -> bool:
    """Half-open [from, until) overlap. Adjacency (a_until == b_from) is NOT overlap."""
    return a_from < b_until and b_from < a_until


@bp.post("/neighborhood/civic-notices")
@require_roles("AgencyOfficer")
def create_notice():
    payload = request.get_json(silent=True) or {}
    neighborhood_id = as_str(payload, "neighborhood_id")
    title = as_str(payload, "title")
    body = as_str(payload, "body")
    notice_kind = as_enum(payload, "notice_kind", NOTICE_KINDS)
    effective_from_str = as_str(payload, "effective_from")
    effective_until_str = as_str(payload, "effective_until")

    if DB.neighborhoods.get(neighborhood_id) is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    try:
        eff_from = parse_iso(effective_from_str)
        eff_until = parse_iso(effective_until_str)
    except ValueError:
        raise InvalidRequest("effective_from/until must be ISO 8601 timestamps")

    # Priority 120: end > start
    if not (eff_until > eff_from):
        raise InvalidTimeWindow("effective_until must be strictly greater than effective_from")

    # Priority 121: effective_from >= now
    if eff_from < CLOCK.now():
        raise EffectiveFromInPast("effective_from must be >= current logical clock")

    # Priority 130: no overlap on (neighborhood_id, notice_kind) with ACTIVE or SCHEDULED
    for existing in DB.civic_notices.values():
        if (
            existing["neighborhood_id"] == neighborhood_id
            and existing["notice_kind"] == notice_kind
            and existing["state"] in ("ACTIVE", "SCHEDULED")
        ):
            e_from = parse_iso(existing["effective_from"])
            e_until = parse_iso(existing["effective_until"])
            if _intervals_overlap(eff_from, eff_until, e_from, e_until):
                raise NoticeWindowOverlap(
                    "Proposed civic notice overlaps with an ACTIVE/SCHEDULED notice"
                )

    n = {
        "agency_officer_id": g.user_id,
        "neighborhood_id": neighborhood_id,
        "title": title,
        "body": body,
        "notice_kind": notice_kind,
        "effective_from": iso_format(eff_from),
        "effective_until": iso_format(eff_until),
        "state": "SCHEDULED",
    }
    stamp_new(n)
    DB.civic_notices[n["id"]] = n
    return success(n, status=201)


@bp.get("/neighborhood/civic-notices/<cid>")
@require_roles(*ALL_ROLES)
def get_notice(cid: str):
    c = DB.civic_notices.get(cid)
    if c is None:
        raise NotFound(f"CivicNotice {cid} not found")
    return success(c)


@bp.get("/neighborhood/civic-notices")
@require_roles(*ALL_ROLES)
def list_notices():
    nid = request.args.get("neighborhood_id")
    kind = request.args.get("notice_kind")
    oid = request.args.get("agency_officer_id")
    state = request.args.get("state")
    rows = list(DB.civic_notices.values())
    if nid is not None:
        rows = [c for c in rows if c["neighborhood_id"] == nid]
    if kind is not None:
        rows = [c for c in rows if c["notice_kind"] == kind]
    if oid is not None:
        rows = [c for c in rows if c["agency_officer_id"] == oid]
    if state is not None:
        rows = [c for c in rows if c["state"] == state]
    rows.sort(key=lambda c: (c["created_at"], c["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/civic-notices/<cid>/retract")
@require_roles("AgencyOfficer")
def retract_notice(cid: str):
    c = DB.civic_notices.get(cid)
    if c is None:
        raise NotFound(f"CivicNotice {cid} not found")
    if c["state"] not in ("SCHEDULED", "ACTIVE"):
        raise InvalidState(f"CivicNotice.state is {c['state']}, expected SCHEDULED or ACTIVE")
    if c["agency_officer_id"] != g.user_id:
        raise Forbidden("Only the publishing officer may retract this notice")
    c["state"] = "RETRACTED"
    bump(c)
    return success(c)
