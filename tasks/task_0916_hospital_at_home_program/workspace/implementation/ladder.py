"""The sixteen-rung rejection ladder of PRD 2.5.

Every handler calls these helpers in ascending rung order and nothing else
decides precedence. Within a rung the sub-rules run in the order PRD spells
out. Evaluation stops at the first violation.

  rung  1  authentication              ERR_UNAUTHENTICATED
  rung  2  authorization               ERR_FORBIDDEN_ROLE
  rung  3  path resource existence     ERR_*_NOT_FOUND
  rung  4  request body schema         4a required / 4b enum / 4c bounds
  rung  5  body foreign-key existence  ERR_*_NOT_FOUND
  rung  6  optimistic concurrency      ERR_STALE_VERSION
  rung  7  target state precondition   ERR_INVALID_STATE
  rung  8  parent episode state gate   ERR_EPISODE_NOT_ACTIVE
  rung  9  admission gauntlet          eight ordered rules
  rung 10  segregation of duties       ERR_SEGREGATION_OF_DUTIES
  rung 11  clinical custody / safety   11a witness / 11b cold chain
  rung 12  temporal overlap            ERR_VISIT_OVERLAP
  rung 13  referential compatibility   ERR_DIET_INCOMPATIBLE
  rung 14  capacity and caps           14a beds / 14b kit / 14c redeliv / 14d appeal
  rung 15  discharge reconciliation    15a med rec / 15b delivery / 15c components
  rung 16  fiscal gate                 ERR_NO_BILLABLE_DAYS
"""

from flask import request

import clock
import errors
from errors import fail
from store import DB

ROLES = (
    "ProgramAdmin",
    "AdmittingPhysician",
    "FieldNurse",
    "CommunityParamedic",
    "PharmacyAuthorizer",
    "LogisticsCoordinator",
    "BillingAnalyst",
    "Patient",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


# --- rung 1 and rung 2 ----------------------------------------------------

def authenticate_and_authorize(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        fail(errors.ERR_UNAUTHENTICATED)
    if role not in ROLES:
        fail(errors.ERR_UNAUTHENTICATED)
    if role not in allowed_roles:
        fail(errors.ERR_FORBIDDEN_ROLE)
    return Caller(user_id, role)


# --- rung 3: path resource existence, left to right -----------------------

_TABLE_ERROR = {
    "patients": errors.ERR_PATIENT_NOT_FOUND,
    "referrals": errors.ERR_REFERRAL_NOT_FOUND,
    "episodes": errors.ERR_EPISODE_NOT_FOUND,
}


def path_row(table, row_id):
    row = getattr(DB, table).get(row_id)
    if row is None:
        fail(_TABLE_ERROR.get(table, errors.ERR_RESOURCE_NOT_FOUND))
    return row


# --- rung 4: request body schema -----------------------------------------

def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def require_fields(body, names):
    """4a: every declared-required field is present and not null."""
    for name in names:
        if name not in body or body[name] is None:
            fail(errors.ERR_VALIDATION, "Field '%s' is required." % name)


def check_enum(body, name, allowed, required=True):
    """4b: every enum-typed field carries a value inside its declared set.

    Every enum-membership failure in this program routes to ERR_INVALID_ENUM.
    """
    if name not in body or body[name] is None:
        # An absent field is a rung 4a concern, never a rung 4b one.
        return
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail(errors.ERR_INVALID_ENUM, "Field '%s' carries an undeclared enum value." % name)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_number_min(body, name, minimum, required=True):
    """4c: numeric lower bound."""
    if name not in body or body[name] is None:
        return
    value = body[name]
    if not _is_number(value):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a number." % name)
    if value < minimum:
        fail(errors.ERR_VALIDATION, "Field '%s' must be at least %s." % (name, minimum))


def as_integer(value, name):
    """Accept an int, or a float carrying an exact integral value."""
    if isinstance(value, bool):
        fail(errors.ERR_VALIDATION, "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    fail(errors.ERR_VALIDATION, "Field '%s' must be an integer." % name)


def check_integer_range(body, name, minimum, maximum=None):
    """4c: integer bound (total_beds, daily_delivery_count, excursion_minutes)."""
    if name not in body or body[name] is None:
        return None
    value = as_integer(body[name], name)
    if value < minimum:
        fail(errors.ERR_VALIDATION, "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail(errors.ERR_VALIDATION, "Field '%s' must be at most %s." % (name, maximum))
    body[name] = value
    return value


def check_boolean(body, name):
    if name not in body or body[name] is None:
        return
    if not isinstance(body[name], bool):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a boolean." % name)


def check_non_empty_string(body, name):
    if name not in body or body[name] is None:
        return
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        fail(errors.ERR_VALIDATION, "Field '%s' must be a non-empty string." % name)


def check_string(body, name):
    if name not in body or body[name] is None:
        return
    if not isinstance(body[name], str):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a string." % name)


def check_datetime(body, name):
    """4c: every datetime supplied anywhere parses as an ISO 8601 UTC instant."""
    if name not in body or body[name] is None:
        return None
    parsed = clock.parse_iso(body[name])
    if parsed is None:
        fail(errors.ERR_VALIDATION, "Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def check_date_string(body, name):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a YYYY-MM-DD calendar date." % name)
    try:
        return clock.date_str_to_dt(value)
    except ValueError:
        fail(errors.ERR_VALIDATION, "Field '%s' must be a YYYY-MM-DD calendar date." % name)


def check_unique(table, field, value):
    for row in getattr(DB, table).values():
        if row.get(field) == value:
            fail(errors.ERR_VALIDATION, "Field '%s' must be unique." % field)


def expected_version(body, name):
    """The OCC field is a required body element (PRD 2.6); rung 4 guards its shape."""
    value = body.get(name)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            fail(errors.ERR_VALIDATION, "Field '%s' must be an integer version." % name)
    return as_integer(value, name)


def pagination_params():
    """4c: limit between 1 and 100 inclusive, offset at least 0."""
    import envelope

    limit = envelope.PAGINATION_DEFAULT_LIMIT
    offset = envelope.PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(errors.ERR_VALIDATION, "Query parameter 'limit' must be an integer.")
        if limit < envelope.PAGINATION_MIN_LIMIT or limit > envelope.PAGINATION_MAX_LIMIT:
            fail(errors.ERR_VALIDATION, "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(errors.ERR_VALIDATION, "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail(errors.ERR_VALIDATION, "Query parameter 'offset' must be at least 0.")
    return limit, offset


# --- rung 5: body foreign-key existence -----------------------------------
# Checked in the declared resource-type order: patient, referral, episode,
# then unit / kit.

def body_patient(body, name="patient_id"):
    value = body.get(name)
    row = DB.patients.get(value)
    if row is None:
        fail(errors.ERR_PATIENT_NOT_FOUND)
    return row


def body_referral(body, name="referral_id"):
    value = body.get(name)
    row = DB.referrals.get(value)
    if row is None:
        fail(errors.ERR_REFERRAL_NOT_FOUND)
    return row


def body_episode(body, name="episode_id"):
    value = body.get(name)
    row = DB.episodes.get(value)
    if row is None:
        fail(errors.ERR_EPISODE_NOT_FOUND)
    return row


def body_unit(body, name="unit_id"):
    value = body.get(name)
    row = DB.units.get(value)
    if row is None:
        fail(errors.ERR_RESOURCE_NOT_FOUND)
    return row


# --- rung 6: optimistic concurrency ---------------------------------------

def check_occ(parent_row, supplied_version):
    if parent_row["version"] != supplied_version:
        fail(errors.ERR_STALE_VERSION)


# --- rung 7: target state precondition ------------------------------------

def require_state(condition):
    if not condition:
        fail(errors.ERR_INVALID_STATE)


# --- rung 8: parent episode state gate ------------------------------------

def require_episode_active(episode):
    if episode["status"] != "ACTIVE":
        fail(errors.ERR_EPISODE_NOT_ACTIVE)
