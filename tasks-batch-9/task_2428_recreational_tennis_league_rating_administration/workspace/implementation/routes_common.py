"""Shared route helpers: lookups, filters and serialization."""

from flask import request

from auth import (ROLE_CAPTAIN, ROLE_COMMITTEE_CHAIR, ROLE_COMMITTEE_MEMBER,
                 ROLE_LEAGUE_COORDINATOR, ROLE_PLAYER, ROLE_SECTION_ADMIN)
from errors import ApiError
from response import paginate
from store import db, public, sorted_rows

ALL_ROLES = (ROLE_SECTION_ADMIN, ROLE_LEAGUE_COORDINATOR, ROLE_CAPTAIN, ROLE_PLAYER,
             ROLE_COMMITTEE_MEMBER, ROLE_COMMITTEE_CHAIR)

ADMIN_ONLY = (ROLE_SECTION_ADMIN,)
COORDINATOR_ONLY = (ROLE_LEAGUE_COORDINATOR,)
CAPTAIN_ONLY = (ROLE_CAPTAIN,)
CHAIR_ONLY = (ROLE_COMMITTEE_CHAIR,)
MEMBER_ONLY = (ROLE_COMMITTEE_MEMBER,)
PLAYER_ONLY = (ROLE_PLAYER,)


def found(collection, identifier):
    """Rank 10 — a path identifier that does not resolve."""
    record = getattr(db, collection).get(identifier)
    if record is None:
        raise ApiError("ERR_NOT_FOUND")
    return record


def reference(collection, identifier):
    """Rank 11 — a payload foreign key that does not resolve."""
    record = getattr(db, collection).get(identifier)
    if record is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return record


def scope_match(expected_section_id, actual_section_id):
    """Rank 12 — a resolved payload foreign key from another section."""
    if expected_section_id != actual_section_id:
        raise ApiError("ERR_SECTION_SCOPE_MISMATCH")


def section_of_league(league):
    return db.sections.get(league.get("section_id"))


def section_of_team(team):
    league = db.leagues.get(team.get("league_id"))
    if league is None:
        return None
    return db.sections.get(league.get("section_id"))


def league_of_team(team):
    return db.leagues.get(team.get("league_id"))


def _as_bool(raw):
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def apply_filters(rows, spec):
    """spec maps query-parameter name to (field_name, kind)."""
    out = rows
    for param, (field, kind) in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "int":
            try:
                wanted = int(raw)
            except ValueError:
                return []
            out = [r for r in out if r.get(field) == wanted]
        elif kind == "bool":
            wanted = _as_bool(raw)
            if wanted is None:
                return []
            out = [r for r in out if bool(r.get(field)) == wanted]
        else:
            out = [r for r in out if r.get(field) == raw]
    return out


def listing(rows, spec=None, serializer=None):
    rows = list(rows)
    if spec:
        rows = apply_filters(rows, spec)
    rows = sorted_rows(rows)
    return paginate(rows, serializer or public)


def collection_rows(name, predicate=None):
    rows = list(getattr(db, name).values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    return rows
