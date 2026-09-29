"""The Order of Refusal (PRD 2.6) implemented as one central ordered pipeline.

Priorities 1..7 are declarative and always run first, in this fixed order:
  1 authentication context      2 role authorisation
  3 path identifier existence   4 body identifier existence
  5 field types / enums / ranges
  6 the revision (OCC) guard    7 cross-aggregate scoping

Priorities 8..16 are operation specific. A handler hands `run_checks` a list of
(priority, callable) pairs; the runner sorts them by priority ascending (stable
within a priority) and evaluates until the first failure. Handlers may therefore
list their checks in any order and the ladder still decides the winner.
"""

from flask import request

import store
from const import ROLES
from errors import ApiError
from fields import validate

KINDS = {
    "unit": ("units", "ERR_UNIT_NOT_FOUND"),
    "bed": ("beds", "ERR_BED_NOT_FOUND"),
    "staff": ("staff", "ERR_STAFF_NOT_FOUND"),
    "shift": ("shifts", "ERR_SHIFT_NOT_FOUND"),
    "encounter": ("encounters", "ERR_ENCOUNTER_NOT_FOUND"),
    "care": ("care", "ERR_CARE_ASSIGNMENT_NOT_FOUND"),
    "booking": ("bookings", "ERR_BOOKING_NOT_FOUND"),
    "activation": ("activations", "ERR_ACTIVATION_NOT_FOUND"),
    "item": ("items", "ERR_CHECKLIST_ITEM_NOT_FOUND"),
    "assessment": ("assessments", "ERR_ASSESSMENT_NOT_FOUND"),
    "cesarean": ("cesareans", "ERR_CESAREAN_EVENT_NOT_FOUND"),
    "drill": ("drills", "ERR_DRILL_NOT_FOUND"),
    "review": ("reviews", "ERR_REVIEW_NOT_FOUND"),
    "pass": ("passes", "ERR_PASS_NOT_FOUND"),
    "snapshot": ("snapshots", "ERR_SNAPSHOT_NOT_FOUND"),
}


class Ctx(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.body = {}
        self.v = None
        self.p = {}
        self.r = {}


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def need(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)


def run_checks(checks):
    order = sorted(range(len(checks)), key=lambda i: (checks[i][0], i))
    for i in order:
        checks[i][1]()


def _auth(roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if not role or role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if roles is not None and role not in roles:
        fail("ERR_INSUFFICIENT_PERMISSIONS")
    return user_id, role


def lookup(kind, ident):
    table, _ = KINDS[kind]
    return getattr(store.S, table).get(ident)


def _resolve_path(ctx, path):
    for entry in path or []:
        kind = entry[0]
        ident = entry[1]
        parent_kind = entry[2] if len(entry) > 2 else None
        parent_field = entry[3] if len(entry) > 3 else None
        _, not_found = KINDS[kind]
        rec = lookup(kind, ident) if isinstance(ident, str) else None
        if rec is None:
            fail(not_found)
        if parent_kind is not None:
            parent = ctx.p.get(parent_kind)
            if parent is None or rec.get(parent_field) != parent["id"]:
                fail(not_found)
        ctx.p[kind] = rec


def _resolve_body_refs(ctx, body_refs):
    """Priority 4. A field that is absent or not a string is left for priority 5."""
    for entry in body_refs or []:
        field = entry[0]
        kind = entry[1]
        alias = entry[2] if len(entry) > 2 else kind
        raw = ctx.body.get(field)
        if not isinstance(raw, str):
            continue
        rec = lookup(kind, raw)
        if rec is None:
            fail(KINDS[kind][1])
        ctx.r[alias] = rec


def begin(roles=None, path=None, body_refs=None, specs=None, occ=None, scope=None):
    user_id, role = _auth(roles)                     # priorities 1 and 2
    ctx = Ctx(user_id, role)
    _resolve_path(ctx, path)                         # priority 3
    payload = request.get_json(silent=True)
    ctx.body = payload if isinstance(payload, dict) else {}
    _resolve_body_refs(ctx, body_refs)               # priority 4
    ctx.v = validate(ctx.body, specs or [])          # priority 5
    if occ is not None:                              # priority 6
        field, error_id, target = occ
        record = target(ctx)
        if record is not None and ctx.v.get(field) != record.get("version"):
            fail(error_id)
    if scope is not None:                            # priority 7
        scope(ctx)
    return ctx


def same_unit(ctx, unit_id, records):
    """Priority 7 helper: every referenced record must live in `unit_id`."""
    for rec in records:
        if rec is None:
            continue
        other = rec.get("unit_id")
        if other is not None and other != unit_id:
            fail("ERR_CROSS_UNIT_REFERENCE")
