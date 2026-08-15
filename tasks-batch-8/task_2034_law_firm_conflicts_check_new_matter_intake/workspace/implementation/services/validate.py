"""Shared route helpers: FK resolution, shape checks, the adverse-overlap
rule (PRD 3.3 / V-T1), and OCC (PRD 2.10)."""

from datetime import datetime

import db
from errors import ApiError, invalid, not_found, ERR_STALE_VERSION

PARTY_TYPES = ("CORPORATION", "INDIVIDUAL", "PARTNERSHIP", "TRUST", "GOVERNMENT")
PRACTICE_GROUPS = ("LITIGATION", "CORPORATE", "TAX", "IP")
ROLES_IN_MATTER = ("ADVERSE", "WITNESS", "RELATED")
HIRE_TYPES = ("INTERNAL", "LATERAL")
SEARCH_VARIANTS = ("STRICT", "PHONETIC")
WALL_REASONS = ("CONFLICT_CONFIRMED", "LATERAL_IMPUTATION", "CLIENT_REQUEST")
REVIEW_DECISIONS = ("CONFIRMED", "DISMISSED")


def resolve(table, value):
    """Tier 3: a present FK value must resolve, else ERR_NOT_FOUND."""
    row = table.get(value)
    if row is None:
        raise not_found()
    return row


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def check_occ(payload, matter):
    """Tier 6 concurrency gate: when expected_matter_version is a usable
    integer, compare; mismatch -> ERR_STALE_VERSION. Missing/malformed is
    left for the shape tier (PRD 2.11 ordering)."""
    expected = payload.get("expected_matter_version")
    if is_int(expected) and expected != matter["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_matter_version does not match the matter's "
                       "current version")


def require_occ(payload):
    """Shape tier: expected_matter_version is non-optional on OCC endpoints."""
    if not is_int(payload.get("expected_matter_version")):
        raise invalid("expected_matter_version is required and must be an integer")


def adverse_overlap_check(attorney_id, client_party_id, roster_party_roles,
                          exclude_matter_id=None):
    """V-T1: reject assigning attorney R when R is responsible on another
    OPEN matter M2 and (the target matter's client appears ADVERSE on M2, or
    M2's client appears ADVERSE on the target matter). M2's activity window
    is half-open [opened_at, closed_at); a CLOSED M2 does not overlap.
    roster_party_roles: iterable of (party_id, role_in_matter) on the target.
    Returns True when the assignment is blocked."""
    from errors import ERR_ATTORNEY_ADVERSE_OVERLAP  # noqa: F401  (caller raises)

    now = db.now()
    target_roster = list(roster_party_roles)
    for other in db.store.matters.values():
        if other["id"] == exclude_matter_id:
            continue
        if other["responsible_attorney_id"] != attorney_id:
            continue
        if other["lifecycle_status"] != "OPEN":
            # Half-open interval: only currently-OPEN matters overlap.
            continue
        if other["opened_at"] is None:
            continue
        if other["closed_at"] is not None and db.parse_ts(other["closed_at"]) <= now:
            continue
        # Clause 1: target's client appears ADVERSE on the other matter.
        for mp in db.store.matter_parties.values():
            if (mp["matter_id"] == other["id"]
                    and mp["party_id"] == client_party_id
                    and mp["role_in_matter"] == "ADVERSE"):
                return True
        # Clause 2: the other matter's client appears ADVERSE on the target.
        for party_id, role in target_roster:
            if party_id == other["client_party_id"] and role == "ADVERSE":
                return True
    return False


def valid_date_string(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True
