"""AccessGrant coverage checks (PRD §2.11).

A grant is ACTIVE while revoked_at is unset and the program's current_period_utc
falls inside the closed interval [valid_from, valid_until].

Gate enablement: a scope gate is inert for a program until at least one grant row
of that scope exists in the program (access control not yet configured). Once any
grant of the scope exists, callers must hold an ACTIVE grant of that scope.
"""
from db import db
from errors import raise_error, ERR_NO_ACTIVE_GRANT
from util import parse_dt


def _grant_active(grant, program) -> bool:
    if grant.get("revoked_at") is not None:
        return False
    now = program["_clock_dt"]
    return grant["_valid_from_dt"] <= now <= grant["_valid_until_dt"]


def grant_configured(program_id, scope) -> bool:
    """True once any grant row of this scope exists in the program."""
    for g in db["access_grants"].values():
        if g["program_id"] == program_id and g["grant_scope"] == scope:
            return True
    return False


def has_active_grant(program_id, user_id, scope) -> bool:
    program = db["assessment_programs"].get(program_id)
    if program is None:
        return False
    for g in db["access_grants"].values():
        if (
            g["program_id"] == program_id
            and g["grantee_user_id"] == user_id
            and g["grant_scope"] == scope
            and _grant_active(g, program)
        ):
            return True
    return False


def check_grant(caller, program_id, scope):
    """Raise ERR_NO_ACTIVE_GRANT when the gate is configured and the caller lacks coverage."""
    if not grant_configured(program_id, scope):
        return
    if not has_active_grant(program_id, caller.user_id, scope):
        raise_error(
            ERR_NO_ACTIVE_GRANT,
            f"caller lacks an active {scope} grant for this program",
        )


def caller_may(caller, program_id, scope) -> bool:
    """Non-raising variant for list filtering / read gating."""
    if not grant_configured(program_id, scope):
        return True
    return has_active_grant(program_id, caller.user_id, scope)


def intervals_fully_overlap(existing, new_from, new_until) -> bool:
    """Full-overlap (containment) semantics over closed intervals: the new interval
    is rejected iff it lies entirely within an existing active grant's interval.
    Adjacent intervals (end == start) do not overlap."""
    return (
        existing["_valid_from_dt"] <= new_from
        and new_until <= existing["_valid_until_dt"]
    )


def find_full_overlap(program_id, grantee_user_id, scope, new_from, new_until):
    program = db["assessment_programs"].get(program_id)
    for g in db["access_grants"].values():
        if (
            g["program_id"] == program_id
            and g["grantee_user_id"] == grantee_user_id
            and g["grant_scope"] == scope
            and program is not None
            and _grant_active(g, program)
            and intervals_fully_overlap(g, new_from, new_until)
        ):
            return g
    return None
