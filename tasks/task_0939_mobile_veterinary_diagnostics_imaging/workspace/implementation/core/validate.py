"""Ladder rungs 5 (request shape) and 6 (closed-enum membership).

=============================================================================
CLOSED, EXHAUSTIVE iff-LIST FOR ERR_INVALID_ENUM  (PRD 2.8 rung 6)
=============================================================================
A field routes to ERR_INVALID_ENUM **if and only if** it appears in this list.
NO OTHER FIELD IN THE SYSTEM ROUTES HERE.

  1.  POST /clinics                          -> status
  2.  POST /clinics/{clinic_id}/billing-hold -> billing_hold_status
  3.  POST /contracts                        -> kind
  4.  POST /mobile-units                     -> service_status
  5.  POST /mobile-units/{unit_id}/service-status -> service_status
  6.  POST /equipment                        -> modality
  7.  POST /technicians                      -> certified_modalities[]  (each member)
  8.  POST /specialists                      -> modality_privileges[]   (each member)
  9.  POST /specialists                      -> species_privileges[]    (each member)
 10.  POST /specialists                      -> status
 11.  POST /routes/{route_id}/stops          -> stop_priority
 12.  POST /referrals                        -> species
 13.  POST /referrals                        -> study_kind
 14.  POST /referrals                        -> requested_modality
 15.  POST /referrals                        -> priority
 16.  POST /studies                          -> modality
 17.  POST /studies/{study_id}/hold          -> hold_reason
 18.  POST /studies/{study_id}/repeat        -> repeat_cause
 19.  POST /studies/{study_id}/qc            -> qc_result
 20.  POST /qc-checks                        -> result
 21.  POST /reports                          -> kind

DELIBERATE EXCLUSIONS — each named with the code it uses instead:
  * Every GET list-filter query parameter (`status`, `modality`, `kind`,
    `workflow_status`, `qc_status`, `tat_status`, `billing_status`, `priority`,
    `study_kind`, `calibration_status`, `result`, ...).  Filters NEVER error:
    an unrecognised filter value simply matches no row and yields an empty page.
  * Numeric range violations — `limit` outside 1..100, negative `offset`, a
    minute-of-day outside 0..1440, a peer-review `score` outside 1..5, a
    calibration window that ends at or before its start or spans over 30 days,
    a negative `drive_minutes_from_prev`, a non-positive `additional_studies`
    or `image_count`.  All -> ERR_VALIDATION (rung 5).
  * Wrong-STATE values — a resource sitting in a state that does not admit the
    requested transition.  -> the rung 17..22 state codes
    (ERR_ROUTE_INVALID_STATE, ERR_STOP_INVALID_STATE,
    ERR_REFERRAL_INVALID_STATE, ERR_APPOINTMENT_INVALID_STATE,
    ERR_STUDY_TERMINAL / ERR_STUDY_INVALID_STATE,
    ERR_TAT_CLOCK_STATE_INVALID, ERR_ALREADY_STAT,
    ERR_ASSIGNMENT_INVALID_STATE, ERR_REPORT_INVALID_STATE,
    ERR_PEER_REVIEW_INVALID_STATE).
  * Body foreign keys (`clinic_id`, `contract_id`, `mobile_unit_id`,
    `technician_id`, `equipment_id`, `specialist_id`, `route_stop_id`,
    `referral_id`, `appointment_id`, `study_id`, `report_id`,
    `assigned_unit_id`, `performed_by_technician_id`,
    `reviewer_specialist_id`).  A value naming no row -> the rung 4 existence
    codes (ERR_*_NOT_FOUND / ERR_RECORD_NOT_FOUND); a well-formed value never
    routes to ERR_INVALID_ENUM.
  * Free-text fields (`name`, `address_zone`, `serial_label`, `full_name`,
    `patient_name`, `body_region`, `findings`, `note`, `cancel_reason`,
    `return_reason`, `reject_reason`, `retract_reason`, `decline_reason`,
    `outcome_note`, `clinical_history`) — a wrong TYPE -> ERR_VALIDATION.
  * Date / instant strings (`service_date`, `period_start`, `period_end`,
    `valid_from`, `valid_until`, `calibration_valid_from`,
    `calibration_valid_until`, `to_iso8601`) — malformed -> ERR_VALIDATION.
=============================================================================
"""

from flask import request

from .constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from .errors import ApiError

_MISSING = object()


def body():
    """The JSON body as a dict.  A malformed or non-object body is rung 5."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        data = None
    if data is None:
        if request.data.strip() == b"":
            return {}
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def fail(message):
    raise ApiError("ERR_VALIDATION", message)


def req_str(data, field, allow_empty=True):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        fail("Field '%s' is required." % field)
    if not isinstance(value, str):
        fail("Field '%s' must be a string." % field)
    if not allow_empty and value == "":
        fail("Field '%s' must be a non-empty string." % field)
    return value


def opt_str(data, field, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        fail("Field '%s' must be a string." % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        fail("Field '%s' is required." % field)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        fail("Field '%s' must be at most %d." % (field, maximum))
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        fail("Field '%s' must be at most %d." % (field, maximum))
    return value


def opt_bool(data, field, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        fail("Field '%s' must be a boolean." % field)
    return value


def req_id(data, field):
    """A body foreign key: must be present and a string (existence is rung 4)."""
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        fail("Field '%s' is required." % field)
    if not isinstance(value, str):
        fail("Field '%s' must be a string identifier." % field)
    return value


def opt_id(data, field):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, str):
        fail("Field '%s' must be a string identifier." % field)
    return value


def has_field(data, field):
    return field in data and data[field] is not None


def req_list(data, field, min_len=1):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        fail("Field '%s' is required." % field)
    if not isinstance(value, list):
        fail("Field '%s' must be an array." % field)
    if len(value) < min_len:
        fail("Field '%s' must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str):
            fail("Every member of '%s' must be a string." % field)
    if len(set(value)) != len(value):
        fail("Members of '%s' must be distinct." % field)
    return value


# --- rung 6 -----------------------------------------------------------------


def enum_value(value, allowed, field):
    """Rung 6 for a scalar field on the closed iff-list above."""
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "Field '%s' must be one of %s." % (field, ", ".join(allowed)),
        )
    return value


def enum_members(values, allowed, field):
    """Rung 6 for an array field on the closed iff-list above."""
    for item in values:
        if item not in allowed:
            raise ApiError(
                "ERR_INVALID_ENUM",
                "Every member of '%s' must be one of %s." % (field, ", ".join(allowed)),
            )
    return values


# --- pagination (PRD 2.3) ---------------------------------------------------


def pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("Query parameter 'offset' must be at least 0.")
    return limit, offset


def filters(*names):
    """Optional equality filters straight off the query string (never error)."""
    out = {}
    for name in names:
        if name in request.args:
            out[name] = request.args.get(name)
    return out
