"""Authentication, authorization, ownership, segregation of duties (PRD 2.1)
and the body schema validator (ladder position 5)."""

from flask import request

from calc import is_date, is_month
from errors import fail

APPLICANT = "Applicant"
CASEWORKER = "Caseworker"
SUPERVISOR = "EligibilitySupervisor"
SPECIALIST = "WorkProgramSpecialist"
FISCAL = "FiscalOfficer"
FRAUD = "FraudInvestigator"
ANALYST = "StateReportingAnalyst"

STAFF_ROLES = (CASEWORKER, SUPERVISOR, SPECIALIST, FISCAL, FRAUD, ANALYST)
ALL_ROLES = (APPLICANT,) + STAFF_ROLES


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_applicant(self):
        return self.role == APPLICANT


def require(*roles):
    """Ladder 1 then 2: authentication, then endpoint role membership."""
    user_id = request.headers.get("X-User-ID", None)
    role = request.headers.get("X-User-Role", None)
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED",
             "X-User-ID and X-User-Role headers are required.")
    allowed = roles if roles else ALL_ROLES
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE",
             "Role %s may not perform this operation." % role)
    return Actor(user_id, role)


def require_owner(actor, household_id):
    """Ladder 6: an Applicant may act only on its own household (PRD 2.1)."""
    if actor.is_applicant and actor.user_id != household_id:
        fail("ERR_NOT_HOUSEHOLD_OWNER",
             "This applicant does not own the target household.")


def require_different_actor(actor, other_user_id):
    """Ladder 7: segregation of duties (PRD 2.1)."""
    if other_user_id is not None and actor.user_id == other_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The acting user may not dispose of its own earlier step.")


# ---------------------------------------------------------------------------
# Body parsing / schema validation
# ---------------------------------------------------------------------------
_MISSING = object()


def raw_body():
    """The parsed JSON object, or {} for an absent body."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def body_str(body, name):
    """Raw string value used for body foreign-key lookups (ladder 4)."""
    value = body.get(name, _MISSING)
    if value is _MISSING or not isinstance(value, str):
        return None
    return value


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field %s %s." % (name, detail))


class Fields(object):
    """Declarative body reader.  Fields are validated in declaration order."""

    def __init__(self, body):
        self.body = body
        self.values = {}

    def _present(self, name, required, default):
        value = self.body.get(name, _MISSING)
        if value is _MISSING or value is None:
            if required:
                _bad(name, "is required")
            self.values[name] = default
            return _MISSING
        return value

    def text(self, name, required=True, default=None, allow_empty=True):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if not allow_empty and not value.strip():
            _bad(name, "may not be empty")
        self.values[name] = value
        return self

    def pattern(self, name, regex, required=True, default=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not isinstance(value, str) or not regex.match(value):
            _bad(name, "is malformed")
        self.values[name] = value
        return self

    def enum(self, name, domain, required=True, default=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not isinstance(value, str) or value not in domain:
            _bad(name, "must be one of %s" % ", ".join(domain))
        self.values[name] = value
        return self

    def integer(self, name, required=True, default=None, minimum=None,
                maximum=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        if minimum is not None and value < minimum:
            _bad(name, "may not be smaller than %d" % minimum)
        if maximum is not None and value > maximum:
            _bad(name, "may not be larger than %d" % maximum)
        self.values[name] = value
        return self

    def number(self, name, required=True, default=None, minimum=None,
               maximum=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name, "must be a number")
        if minimum is not None and value < minimum:
            _bad(name, "may not be smaller than %s" % minimum)
        if maximum is not None and value > maximum:
            _bad(name, "may not be larger than %s" % maximum)
        self.values[name] = value
        return self

    def boolean(self, name, required=True, default=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        self.values[name] = value
        return self

    def month(self, name, required=True, default=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not is_month(value):
            _bad(name, "must be a YYYY-MM month")
        self.values[name] = value
        return self

    def date(self, name, required=True, default=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not is_date(value):
            _bad(name, "must be a YYYY-MM-DD date")
        self.values[name] = value
        return self

    def month_list(self, name, required=True, default=None, min_items=1):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not isinstance(value, list) or len(value) < min_items:
            _bad(name, "must be a non-empty list of YYYY-MM months")
        for item in value:
            if not is_month(item):
                _bad(name, "must contain only YYYY-MM months")
        self.values[name] = value
        return self

    def identifier(self, name, required=True, default=None):
        value = self._present(name, required, default)
        if value is _MISSING:
            return self
        if not isinstance(value, str) or not value.strip():
            _bad(name, "must be an identifier string")
        self.values[name] = value
        return self

    def get(self, name):
        return self.values.get(name)

    def __getitem__(self, name):
        return self.values[name]
