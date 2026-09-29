"""Request-body / query-string validity (PRD section 2.6 step 6) and the
existence resolution helpers of section 2.6 step 5."""
from flask import request

from clock import parse_iso
from errors import ApiError
from store import db

MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("The request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, max_len=None, allow_empty=False):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value == "":
        bad("Field '%s' must be non-empty." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def opt_str(data, key, max_len=None, default=None, allow_empty=True):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value == "":
        bad("Field '%s' must be non-empty." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def req_enum(data, key, members):
    value = req_str(data, key)
    if value not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def opt_enum(data, key, members, default=None):
    if not _present(data, key):
        return default
    value = req_str(data, key)
    if value not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def req_int(data, key, minimum=None):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (key, minimum))
    return value


def req_bool(data, key):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(data, key, default):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def req_datetime(data, key):
    value = req_str(data, key)
    parsed = parse_iso(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_str_array(data, key, allow_empty=False, allow_duplicates=True, members=None):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must be an array of strings." % key)
        if members is not None and item not in members:
            bad("Field '%s' must only contain %s." % (key, ", ".join(members)))
    if not allow_empty and len(value) == 0:
        bad("Field '%s' must be non-empty." % key)
    if not allow_duplicates and len(set(value)) != len(value):
        bad("Field '%s' must not contain duplicates." % key)
    return value


def exact_object(data, key, spec):
    """An object that must carry exactly its declared keys and no others."""
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, dict):
        bad("Field '%s' must be an object." % key)
    if set(value.keys()) != set(spec.keys()):
        bad("Field '%s' must carry exactly the keys %s." % (key, ", ".join(sorted(spec))))
    for inner, kind in spec.items():
        item = value[inner]
        if kind == "string":
            if not isinstance(item, str):
                bad("Field '%s.%s' must be a string." % (key, inner))
        elif kind == "string[]":
            if not isinstance(item, list) or any(not isinstance(x, str) for x in item):
                bad("Field '%s.%s' must be an array of strings." % (key, inner))
    return value


def filter_enum(name, members):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in members:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def filter_str(name):
    return request.args.get(name)


# --- existence resolution (section 2.6 step 5) ------------------------------

def _lookup(table, key, error_id):
    if key is None:
        return None
    row = getattr(db, table).get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def decision_or_404(key):
    return _lookup("decisions", key, "ERR_DECISION_NOT_FOUND")


def request_or_404(key):
    return _lookup("requests", key, "ERR_REQUEST_NOT_FOUND")


def pool_or_404(key):
    return _lookup("pools", key, "ERR_POOL_NOT_FOUND")


def participant_or_404(key):
    return _lookup("participants", key, "ERR_PARTICIPANT_NOT_FOUND")


def study_or_404(key):
    return _lookup("studies", key, "ERR_STUDY_NOT_FOUND")


def recruitment_or_404(key):
    return _lookup("recruitments", key, "ERR_RECRUITMENT_NOT_FOUND")


def consent_or_404(key):
    return _lookup("consents", key, "ERR_CONSENT_NOT_FOUND")


def artifact_or_404(key):
    return _lookup("artifacts", key, "ERR_ARTIFACT_NOT_FOUND")


def theme_or_404(key):
    return _lookup("themes", key, "ERR_THEME_NOT_FOUND")


def finding_or_404(key):
    return _lookup("findings", key, "ERR_FINDING_NOT_FOUND")


def link_or_404(key):
    return _lookup("links", key, "ERR_EVIDENCE_LINK_NOT_FOUND")


def readout_or_404(key):
    return _lookup("readouts", key, "ERR_READOUT_NOT_FOUND")


def followup_or_404(key):
    return _lookup("followups", key, "ERR_FOLLOW_UP_NOT_FOUND")


def ref(data, key):
    """The raw value of a foreign-key body field, or None when absent.

    A present-but-unknown id is a 404 at step 5; an absent field is an
    ERR_INVALID_REQUEST at step 6, which runs later.
    """
    value = data.get(key)
    if value is None or not isinstance(value, str) or value == "":
        return None
    return value
