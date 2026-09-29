"""Ownership guards (ladder rung 3).

Ownership is evaluated before path existence, so every guard passes vacuously
when the governing record cannot be resolved: rung 4 then reports the 404.
"""

from errors import fail
from store import find


def not_owner(detail="The acting identity does not own this resource."):
    fail("ERR_NOT_RESOURCE_OWNER", detail)


def owns(ctx, role, expected_id):
    """For an entity-backed role, X-User-ID must equal the governing foreign key."""
    if ctx.role == role and expected_id is not None and ctx.user_id != expected_id:
        not_owner()


def coach_owns_team(ctx, team):
    if ctx.role == "Coach" and team is not None:
        owns(ctx, "Coach", team.get("coach_id"))


def director_owns_team(ctx, team):
    if ctx.role == "AthleticDirector" and team is not None:
        owns(ctx, "AthleticDirector", team.get("school_id"))


def coach_ids_of_match(match):
    ids = []
    for key in ("home_team_id", "away_team_id"):
        team = find("team", match.get(key))
        if team is not None and team.get("coach_id") is not None:
            ids.append(team["coach_id"])
    return ids


def coach_participates(ctx, match):
    """A coach may act on a match only through one of the two participating teams."""
    if ctx.role != "Coach" or match is None:
        return
    if ctx.user_id not in coach_ids_of_match(match):
        not_owner("The acting coach does not coach either participating team.")


def team_of_body(body):
    value = body.get("team_id")
    return find("team", value) if isinstance(value, str) else None


def team_by_id(value):
    return find("team", value) if isinstance(value, str) else None
