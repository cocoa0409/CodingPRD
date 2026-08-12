"""Request context and the top of the ordered validation ladder (PRD 2.10).

Rungs 1-10 are enforced by :func:`endpoint`; rungs 11-21 by :class:`Refs`;
rungs 22-27 by the helpers at the bottom of this module.  Everything below
rung 27 is endpoint-specific and lives in the route modules.
"""

import functools

from flask import g, request

from errors import ApiError
from lookups import current_period
from store import db, parse_date, parse_instant

ROLES = (
    "ProgramAdmin",
    "IntakeCoordinator",
    "ActivityLead",
    "FundingOfficer",
    "TransportDispatcher",
    "CaregiverUser",
)

MUTATING_METHODS = ("POST", "PATCH", "PUT", "DELETE")


class Ctx(object):
    def __init__(self):
        self.role = None
        self.user_id = None
        self.actor = None          # StaffMember or Caregiver row for entity-backed roles
        self.body = {}
        self.args = {}
        self.params = {}

    def q(self, name):
        value = self.args.get(name)
        if value is None:
            return None
        value = value.strip()
        return value if value else None


def ctx():
    return g.ctx


# ---------------------------------------------------------------------------
# rungs 1-10
# ---------------------------------------------------------------------------

def endpoint(roles, financial=False, gate_exempt=False, scope=None, delivery=None, sod=None):
    """Wrap a view so that ladder rungs 1-10 run before its body.

    ``scope``    -> callable(ctx) returning participant ids the request names
                    (rung 6, CaregiverUser only).
    ``delivery`` -> callable(ctx) returning the session of a delivery-time
                    operation (rung 7, ActivityLead only).
    ``sod``      -> callable(ctx) returning the award being disbursed (rung 8).
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapper(**params):
            context = Ctx()
            g.ctx = context
            context.params = params
            context.args = request.args
            payload = None
            if request.method in MUTATING_METHODS:
                payload = request.get_json(silent=True)
            context.body = payload if isinstance(payload, dict) else {}

            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")

            # 1 / 2 -- role header is checked before the id header.
            if role is None or role.strip() == "":
                raise ApiError("ERR_MISSING_ROLE_HEADER")
            if user_id is None or user_id.strip() == "":
                raise ApiError("ERR_MISSING_USER_ID_HEADER")
            role = role.strip()
            user_id = user_id.strip()
            context.role = role
            context.user_id = user_id

            # 3 -- declared role
            if role not in ROLES:
                raise ApiError("ERR_UNKNOWN_ROLE")
            # 4 -- authorised for this endpoint
            if role not in roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")

            # 5 -- entity-backed identity resolves
            if role == "ActivityLead":
                context.actor = db.get("staff_members", user_id)
                if context.actor is None:
                    raise ApiError("ERR_IDENTITY_NOT_FOUND")
            elif role == "CaregiverUser":
                context.actor = db.get("caregivers", user_id)
                if context.actor is None:
                    raise ApiError("ERR_IDENTITY_NOT_FOUND")

            # 6 -- caregiver scope
            if role == "CaregiverUser" and scope is not None:
                owned = context.actor["participant_id"]
                for participant_id in scope(context) or ():
                    if participant_id is not None and participant_id != owned:
                        raise ApiError("ERR_CAREGIVER_SCOPE_VIOLATION")

            # 7 -- delivery-time staffing
            if role == "ActivityLead" and delivery is not None:
                session = delivery(context)
                if session is not None and not _staffed_on(session, user_id):
                    raise ApiError("ERR_STAFF_NOT_ASSIGNED_TO_SESSION")

            # 8 -- segregation of duties
            if sod is not None:
                award = sod(context)
                if award is not None and award.get("awarded_by_user_id") == user_id:
                    raise ApiError("ERR_SEGREGATION_OF_DUTIES")

            # 9 -- the global write gate
            if request.method in MUTATING_METHODS and not gate_exempt:
                period = current_period()
                if period is not None and period["status"] in ("FROZEN", "CLOSED"):
                    raise ApiError("ERR_PERIOD_FROZEN")

            # 10 -- the financial-write gate
            if financial:
                period = current_period()
                if period is not None and period["status"] in ("RESTRICTED", "CLOSING"):
                    raise ApiError("ERR_PERIOD_RESTRICTED")

            return view(context, **params)

        return wrapper

    return decorator


def _staffed_on(session, staff_id):
    for assignment in db.rows("staff_assignments"):
        if (
            assignment["session_id"] == session["id"]
            and assignment["staff_member_id"] == staff_id
            and assignment["status"] in ("PROPOSED", "CONFIRMED", "DELIVERED")
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# rungs 11-21 -- the ordered existence layer
# ---------------------------------------------------------------------------

# rung number -> (table, error_id) for every family in ladder order
EXISTENCE = {
    "participant": (11, "participants", "ERR_PARTICIPANT_NOT_FOUND"),
    "program": (12, "activity_programs", "ERR_PROGRAM_NOT_FOUND"),
    "session": (13, "program_sessions", "ERR_SESSION_NOT_FOUND"),
    "enrollment": (14, "enrollments", "ERR_ENROLLMENT_NOT_FOUND"),
    "charge": (14, "enrollment_charges", "ERR_CHARGE_NOT_FOUND"),
    "staff": (15, "staff_members", "ERR_STAFF_NOT_FOUND"),
    "certification": (15, "staff_certifications", "ERR_CERTIFICATION_NOT_FOUND"),
    "assignment": (15, "staff_assignments", "ERR_ASSIGNMENT_NOT_FOUND"),
    "equipment": (16, "equipment_items", "ERR_EQUIPMENT_NOT_FOUND"),
    "reservation": (16, "equipment_reservations", "ERR_RESERVATION_NOT_FOUND"),
    "run": (17, "transport_runs", "ERR_TRANSPORT_RUN_NOT_FOUND"),
    "booking": (17, "transport_bookings", "ERR_TRANSPORT_BOOKING_NOT_FOUND"),
    "source": (18, "funding_sources", "ERR_FUNDING_SOURCE_NOT_FOUND"),
    "award": (18, "scholarship_awards", "ERR_AWARD_NOT_FOUND"),
    "band": (18, "fee_scale_bands", "ERR_FEE_BAND_NOT_FOUND"),
    "consent": (19, "consents", "ERR_CONSENT_NOT_FOUND"),
    "assessment": (19, "support_assessments", "ERR_ASSESSMENT_NOT_FOUND"),
    "caregiver": (19, "caregivers", "ERR_CAREGIVER_NOT_FOUND"),
    "goal": (20, "goals", "ERR_GOAL_NOT_FOUND"),
    "rating": (20, "goal_ratings", "ERR_RATING_NOT_FOUND"),
    "period": (21, "operating_periods", "ERR_PERIOD_NOT_FOUND"),
}


class Refs(object):
    """Collects referenced identifiers and resolves them in ladder order.

    Ordering (PRD 2.7 + 2.10): the rung number decides across families; within
    one rung the identifier named earliest in the URL path wins, and path
    identifiers are always judged before body identifiers.
    """

    def __init__(self):
        self._items = []
        self._counter = 0

    def add(self, kind, ident, path=True):
        rung, table, error_id = EXISTENCE[kind]
        self._counter += 1
        self._items.append((rung, 0 if path else 1, self._counter, table, error_id, ident, kind))
        return self

    def resolve(self):
        resolved = {}
        for _rung, _origin, _seq, table, error_id, ident, kind in sorted(self._items):
            row = db.get(table, ident)
            if row is None:
                raise ApiError(error_id)
            resolved.setdefault(kind, row)
            resolved[(kind, ident)] = row
        return resolved


def resolve_one(kind, ident):
    rung, table, error_id = EXISTENCE[kind]
    row = db.get(table, ident)
    if row is None:
        raise ApiError(error_id)
    return row


# ---------------------------------------------------------------------------
# rung 22 / 23 -- payload validation, then enum membership
# ---------------------------------------------------------------------------

def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


class Body(object):
    """Two-phase payload reader.

    Every ``req_*`` / ``opt_*`` call belongs to rung 22 (presence, declared JSON
    type, declared numeric range).  Enum membership is deferred to
    :meth:`check_enums`, which is rung 23 -- so a missing required field is
    always reported before a bad enum member.
    """

    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else {}
        self._pending = []

    # -- helpers --------------------------------------------------------
    def present(self, name):
        return name in self.raw and self.raw[name] is not None

    def _required(self, name):
        if name not in self.raw or self.raw[name] is None:
            _bad("Field '%s' is required." % name)
        return self.raw[name]

    # -- scalars --------------------------------------------------------
    def req_string(self, name):
        value = self._required(name)
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        return value

    def opt_string(self, name, default=None):
        if not self.present(name):
            return default
        value = self.raw[name]
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        return value

    def req_int(self, name, minimum=None, maximum=None):
        value = self._required(name)
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field '%s' must be an integer." % name)
        self._range(name, value, minimum, maximum)
        return value

    def opt_int(self, name, default=None, minimum=None, maximum=None):
        if not self.present(name):
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field '%s' must be an integer." % name)
        self._range(name, value, minimum, maximum)
        return value

    def _range(self, name, value, minimum, maximum):
        if minimum is not None and value < minimum:
            _bad("Field '%s' must be at least %s." % (name, minimum))
        if maximum is not None and value > maximum:
            _bad("Field '%s' must be at most %s." % (name, maximum))

    def req_bool(self, name):
        value = self._required(name)
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value

    def opt_bool(self, name, default=False):
        if not self.present(name):
            return default
        value = self.raw[name]
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value

    def req_date(self, name):
        value = self.req_string(name)
        if parse_date(value) is None:
            _bad("Field '%s' must be an ISO date (YYYY-MM-DD)." % name)
        return value

    def opt_date(self, name, default=None):
        if not self.present(name):
            return default
        value = self.opt_string(name)
        if parse_date(value) is None:
            _bad("Field '%s' must be an ISO date (YYYY-MM-DD)." % name)
        return value

    def req_instant(self, name):
        value = self.req_string(name)
        if parse_instant(value) is None:
            _bad("Field '%s' must be an ISO 8601 instant." % name)
        return value

    # -- enums (rung 23) -------------------------------------------------
    def req_enum(self, name, members):
        value = self.req_string(name)
        self._pending.append((name, value, members))
        return value

    def opt_enum(self, name, members, default=None):
        if not self.present(name):
            return default
        value = self.opt_string(name)
        self._pending.append((name, value, members))
        return value

    def opt_enum_list(self, name, members, default=None):
        """A list whose members are enum-typed (required_*_types)."""
        if not self.present(name):
            return list(default or [])
        value = self.raw[name]
        if not isinstance(value, list):
            _bad("Field '%s' must be an array." % name)
        for entry in value:
            if not isinstance(entry, str):
                _bad("Field '%s' must contain strings." % name)
            self._pending.append((name, entry, members))
        return list(value)

    def check_enums(self):
        for name, value, members in self._pending:
            if value not in members:
                raise ApiError(
                    "ERR_INVALID_ENUM",
                    "Field '%s' carries an undeclared enum member." % name,
                )
        self._pending = []


# ---------------------------------------------------------------------------
# rung 24 -- pagination
# ---------------------------------------------------------------------------

def pagination(context):
    limit = 10
    offset = 0
    raw_limit = context.q("limit")
    raw_offset = context.q("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# ---------------------------------------------------------------------------
# rungs 25 / 26 / 27
# ---------------------------------------------------------------------------

def check_version(expected, parent):
    if expected != parent.get("version"):
        raise ApiError("ERR_STALE_VERSION")


def check_transition(current, sources, terminals):
    """Rung 26 then rung 27.

    PRD 2.10: "a row in a non-terminal but wrong source state earns
    ERR_INVALID_STATE, while a row already parked in a terminal state earns
    ERR_ALREADY_TERMINAL."
    """
    if current in sources:
        return
    if current in terminals:
        raise ApiError("ERR_ALREADY_TERMINAL")
    raise ApiError("ERR_INVALID_STATE")
