"""Shared ladder guards and the generic list / read handlers."""

from db import rows
from errors import fail
import lookups as lk
from auth import require_roles
from envelope import collection, filtered, ok

ALE_STATES = ("DETERMINED_ALE", "CORRECTION_OPEN")


def require_season_open(season):
    """Ladder rung 7."""
    if season is None:
        return
    if season["status"] != "OPEN":
        fail("ERR_SEASON_LOCKED", "The governing filing season is locked.")


def require_group_unlocked(group):
    """Ladder rung 8."""
    if group is None:
        return
    if group["determination_state"] == "LOCKED":
        fail("ERR_DETERMINATION_LOCKED", "The controlled group is locked.")


def require_group_ale(group):
    """Ladder rung 9."""
    if group is None or group["determination_state"] not in ALE_STATES:
        fail(
            "ERR_GROUP_NOT_DETERMINED_ALE",
            "The controlled group is not in DETERMINED_ALE or CORRECTION_OPEN.",
        )


def season_of_form(form):
    employee = lk.get("employees", form["employee_id"])
    return lk.season_of_employee(employee) if employee else None


def group_of_transmittal(transmittal):
    member = lk.get("group_members", transmittal["group_member_id"])
    return lk.group_of_member(member) if member else None


def season_of_transmittal(transmittal):
    group = group_of_transmittal(transmittal)
    return lk.season_of_group(group) if group else None


# --------------------------------------------------------------------------- #
# generic read handlers
# --------------------------------------------------------------------------- #
def listing(table, spec, roles):
    require_roles(*roles)
    return collection(filtered(rows(table), spec))


def single_read(table, identifier, roles):
    require_roles(*roles)
    return ok(lk.find(table, identifier))
