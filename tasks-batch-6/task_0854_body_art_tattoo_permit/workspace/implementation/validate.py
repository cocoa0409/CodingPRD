"""Request-shape validation (PRD §2.7 step 4) and record lookups (§2.6)."""

from flask import request

import store
from errors import ApiError
from util import parse_ts


def bad(message="Invalid request payload."):
    return ApiError("ERR_VALIDATION", message)


def body():
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# field readers
# ---------------------------------------------------------------------------
def req_string(data, field, min_len=1, max_len=None, trim_check=False):
    value = data.get(field)
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % field)
    if trim_check and not value.strip():
        raise bad("Field '%s' must be non-empty after trimming." % field)
    if len(value) < min_len:
        raise bad("Field '%s' is shorter than %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is longer than %d characters." % (field, max_len))
    return value


def opt_string(data, field, min_len=1, max_len=None, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_string(data, field, min_len=min_len, max_len=max_len)


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_enum(data, field, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if not _is_int(value):
        raise bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_number(data, field, gt=None, ge=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % field)
    if gt is not None and not value > gt:
        raise bad("Field '%s' must be greater than %s." % (field, gt))
    if ge is not None and not value >= ge:
        raise bad("Field '%s' must be >= %s." % (field, ge))
    return value


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    return req_bool(data, field)


def req_datetime(data, field):
    value = data.get(field)
    parsed = parse_ts(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def opt_datetime(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_datetime(data, field)


def req_id(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise bad("Field '%s' must be a non-empty string identifier." % field)
    return value


def opt_id(data, field):
    if field not in data or data.get(field) is None:
        return None
    return req_id(data, field)


# ---------------------------------------------------------------------------
# pagination + filters (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if str(raw).strip() != str(limit):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be within [1, 100].")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if str(raw).strip() != str(offset):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def filter_string(name):
    return request.args.get(name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total


# ---------------------------------------------------------------------------
# lookups (PRD §2.6)
# ---------------------------------------------------------------------------
def _lookup(collection, key, error_id):
    rec = collection.get(key)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_establishment(key):
    return _lookup(store.establishments, key, "ERR_ESTABLISHMENT_NOT_FOUND")


def get_artist(key):
    return _lookup(store.artists, key, "ERR_ARTIST_NOT_FOUND")


def get_plan_review(key):
    return _lookup(store.plan_reviews, key, "ERR_PLAN_REVIEW_NOT_FOUND")


def get_inspection(key):
    return _lookup(store.inspections, key, "ERR_INSPECTION_NOT_FOUND")


def get_violation(key):
    return _lookup(store.violations, key, "ERR_VIOLATION_NOT_FOUND")


def get_sterilization_record(key):
    return _lookup(
        store.sterilization_records, key, "ERR_STERILIZATION_RECORD_NOT_FOUND"
    )


def get_minor_consent(key):
    return _lookup(store.minor_consents, key, "ERR_MINOR_CONSENT_NOT_FOUND")


def get_procedure_log(key):
    return _lookup(store.procedure_logs, key, "ERR_PROCEDURE_LOG_NOT_FOUND")


def get_complaint(key):
    return _lookup(store.complaints, key, "ERR_COMPLAINT_NOT_FOUND")


def get_infection_report(key):
    return _lookup(store.infection_reports, key, "ERR_INFECTION_REPORT_NOT_FOUND")


def get_enforcement_action(key):
    return _lookup(store.enforcement_actions, key, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")


def get_renewal_application(key):
    return _lookup(
        store.renewal_applications, key, "ERR_RENEWAL_APPLICATION_NOT_FOUND"
    )
