"""The 38-rung validation ladder helpers (PRD 2.9).

Rungs are evaluated strictly in ascending order by each route handler; these
helpers own the reusable rungs (1, 2, 5, 6, 7, 8, 9) and the shared primitives.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import store
from constants import ROLES, ROLES_REQUIRING_USER_ID, TERMINAL_WORKFLOW_STATES
from errors import fail


class Ctx(object):
    """Per-request context: identity, parsed body, and the resolved target order."""

    __slots__ = ("role", "user_id", "body", "endpoint", "order")

    def __init__(self, role, user_id, body, endpoint):
        self.role = role
        self.user_id = user_id
        self.body = body
        self.endpoint = endpoint
        self.order = None


def _json_body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


# --------------------------------------------------------------------------
# Rung 1 + rung 2
# --------------------------------------------------------------------------
def authenticate(endpoint, roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is missing or names no declared role.")
    if role in ROLES_REQUIRING_USER_ID and (user_id is None or user_id == ""):
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required for role %s." % role)
    if role not in roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return Ctx(role, user_id, _json_body(), endpoint)


# --------------------------------------------------------------------------
# Rungs 3 + 4 -- existence
# --------------------------------------------------------------------------
def need_order(order_id):
    row = store.get("orders", order_id)
    if row is None:
        fail("ERR_ORDER_NOT_FOUND")
    return row


def need(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return row


# --------------------------------------------------------------------------
# Rung 5 -- Traveler order membership
# --------------------------------------------------------------------------
def check_membership(ctx, order):
    if ctx.role != "Traveler" or order is None:
        return
    for applicant in store.all_rows("applicants"):
        if applicant["order_id"] == order["id"] and applicant["id"] == ctx.user_id:
            return
    fail("ERR_NOT_ORDER_MEMBER")


# --------------------------------------------------------------------------
# Rungs 6 + 7 -- body validation then enum membership
# --------------------------------------------------------------------------
class Body(object):
    """Collects the FIRST rung-6 failure and the FIRST rung-7 failure, then raises."""

    def __init__(self, data):
        self.data = data if isinstance(data, dict) else {}
        self._e6 = None
        self._e7 = None

    # -- failure registration ------------------------------------------
    def _f6(self, message):
        if self._e6 is None:
            self._e6 = message

    def _f7(self, message):
        if self._e7 is None:
            self._e7 = message

    def invalid(self, condition, message):
        """Register a rung-6 failure when condition is true."""
        if condition:
            self._f6(message)

    def check(self):
        if self._e6 is not None:
            fail("ERR_VALIDATION", self._e6)
        if self._e7 is not None:
            fail("ERR_INVALID_ENUM", self._e7)

    def has(self, name):
        return name in self.data and self.data[name] is not None

    # -- typed accessors -----------------------------------------------
    def string(self, name, required=True, default=None):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, str):
            self._f6("Field '%s' must be a string." % name)
            return default
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if isinstance(value, bool) or not isinstance(value, int):
            self._f6("Field '%s' must be an integer." % name)
            return default
        if minimum is not None and value < minimum:
            self._f6("Field '%s' must be >= %s." % (name, minimum))
            return value
        if maximum is not None and value > maximum:
            self._f6("Field '%s' must be <= %s." % (name, maximum))
        return value

    def number(self, name, required=True, default=None, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._f6("Field '%s' must be a number." % name)
            return default
        try:
            dec = Decimal(str(value))
        except (InvalidOperation, ValueError):
            self._f6("Field '%s' must be a number." % name)
            return default
        if minimum is not None and dec < Decimal(str(minimum)):
            self._f6("Field '%s' must be >= %s." % (name, minimum))
            return dec
        if maximum is not None and dec > Decimal(str(maximum)):
            self._f6("Field '%s' must be <= %s." % (name, maximum))
            return dec
        if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
            self._f6("Field '%s' must be > %s." % (name, exclusive_min))
            return dec
        if exclusive_max is not None and dec >= Decimal(str(exclusive_max)):
            self._f6("Field '%s' must be < %s." % (name, exclusive_max))
        return dec

    def boolean(self, name, required=True, default=None):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, bool):
            self._f6("Field '%s' must be a boolean." % name)
            return default
        return value

    def date(self, name, required=True, default=None):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        raw = self.data[name]
        if not isinstance(raw, str):
            self._f6("Field '%s' must be an ISO-8601 date string." % name)
            return default
        parsed = clock.parse_date(raw)
        if parsed is None:
            self._f6("Field '%s' must be a YYYY-MM-DD date." % name)
            return default
        return parsed

    def instant(self, name, required=True, default=None):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        raw = self.data[name]
        if not isinstance(raw, str):
            self._f6("Field '%s' must be an ISO-8601 instant string." % name)
            return default
        parsed = clock.parse_instant(raw)
        if parsed is None:
            self._f6("Field '%s' must be a valid ISO-8601 instant." % name)
            return default
        return parsed

    def string_array(self, name, required=True, default=None, non_empty=True):
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            self._f6("Field '%s' must be an array of strings." % name)
            return default
        if non_empty and len(value) == 0:
            self._f6("Field '%s' must not be empty." % name)
            return default
        return value

    def enum(self, name, members, required=True, default=None):
        """Rung 6 owns presence/type; rung 7 owns membership."""
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, str):
            self._f6("Field '%s' must be a string." % name)
            return default
        if value not in members:
            self._f7("Field '%s' carries an undeclared enum member." % name)
            return value
        return value

    def non_enum_choice(self, name, members, required=True, default=None):
        """Deliberately NOT on the rung-7 closed list -- off-set values are rung 6."""
        if name not in self.data or self.data[name] is None:
            if required:
                self._f6("Field '%s' is required." % name)
            return default
        value = self.data[name]
        if not isinstance(value, str) or value not in members:
            self._f6("Field '%s' must be one of %s." % (name, ", ".join(members)))
            return default
        return value


# --------------------------------------------------------------------------
# Pagination + filters (rung 6 owns the bounds)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer >= 0.")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def filter_value(name):
    """Exact, case-sensitive string equality; an off-enum value simply matches nothing."""
    return request.args.get(name)


def apply_filter(rows, name, field=None):
    value = filter_value(name)
    if value is None:
        return rows
    key = field or name
    return [r for r in rows if _as_filter_string(r.get(key)) == value]


def _as_filter_string(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return clock.render_date(value) if hasattr(value, "year") else str(value)


# --------------------------------------------------------------------------
# Rung 8 -- the agency-custody write gate
# --------------------------------------------------------------------------
GATE_EXCLUDED = {
    "orders.tender",
    "orders.rfes.create",
    "rfes.respond",
    "rfes.adjudicate",
    "orders.agency_decision",
    "shipments.address",
    "orders.cancel",
    "courier_legs.dispatch",
    "courier_legs.complete",
    "clock.set",
}


def check_agency_gate(ctx, order):
    if order is None:
        return
    if ctx.endpoint in GATE_EXCLUDED:
        return
    if order["custody_holder"] == "AGENCY":
        fail("ERR_AGENCY_CUSTODY_LOCK")


# --------------------------------------------------------------------------
# Rung 9 -- the terminal-order gate
# --------------------------------------------------------------------------
# Adjudication (friction 1): courier dispatch and completion are exempt so that
# the return hop declared out of AGENCY from CANCELLED and ABANDONED remains
# reachable, together with the post-tender refund disbursement it carries.
TERMINAL_EXEMPT = {"courier_legs.dispatch", "courier_legs.complete"}


def check_terminal(ctx, order):
    if order is None:
        return
    if ctx.endpoint in TERMINAL_EXEMPT:
        return
    if order["workflow_status"] in TERMINAL_WORKFLOW_STATES:
        fail("ERR_ORDER_TERMINAL")


def guard_order(ctx, order):
    """Rungs 8 then 9 for a mutating endpoint whose target order is known."""
    ctx.order = order
    check_agency_gate(ctx, order)
    check_terminal(ctx, order)


# --------------------------------------------------------------------------
# Rung 10 -- generic state gate
# --------------------------------------------------------------------------
def require_state(actual, admitted):
    if actual not in admitted:
        fail("ERR_INVALID_STATE", "State '%s' does not admit this transition." % actual)


# --------------------------------------------------------------------------
# Rung 11 -- optimistic concurrency
# --------------------------------------------------------------------------
def check_occ(expected, parent_row):
    if expected != parent_row["version"]:
        fail("ERR_STALE_VERSION")
