"""Request-body validation helpers. All defects raise ERR_INVALID_REQUEST (400)."""
from flask import request

from db import parse_dt
from errors import raise_err

# Enum vocabularies
MEDIA_TYPES = ["VIDEO", "AUDIO", "FILM", "PHOTO", "DOCUMENT"]
FORMAT_CLASSES = [
    "BETACAM_SP", "UMATIC", "VHS", "FILM_16MM",
    "AUDIO_REEL", "AUDIO_DAT", "DIGITAL_FILE", "PRORES_FILE",
]
CONTENT_RATINGS = ["G", "PG", "PG13", "R", "NR"]
RENDITION_TYPES = ["PROXY_LOWRES", "PROXY_HIGHRES"]
GRANT_TYPES = ["BROADCAST", "STREAMING", "SYNDICATION", "ARCHIVAL_ONLY"]
TERRITORIES = ["DOMESTIC", "REGIONAL", "GLOBAL"]
RESTRICTION_FLAGS = ["EDITORIAL_ONLY", "NO_RERUN", "NEWS_USE_ONLY", "GEO_BLOCKED"]
PURPOSES = ["BROADCAST", "INTERNAL_REVIEW", "EXHIBITION"]
DELIVERY_TIERS = ["STANDARD", "EXPEDITE"]
USAGE_TYPES = ["BROADCAST", "REBROADCAST", "STREAMING", "PROMO"]
STORAGE_TIERS = ["ONLINE", "NEARLINE", "DEEP_ARCHIVE"]
OUTPUT_FORMATS = ["PRORES_FILE", "H264_FILE"]
WORKSTATION_STATUSES = ["ACTIVE", "MAINTENANCE"]
OBSOLETE_FORMATS = {"BETACAM_SP", "UMATIC", "VHS", "FILM_16MM", "AUDIO_REEL", "AUDIO_DAT"}


def body():
    """Return the JSON request body as a dict; anything else becomes {}."""
    j = request.get_json(silent=True)
    return j if isinstance(j, dict) else {}


def _bad(field, why):
    raise_err("ERR_INVALID_REQUEST", f"Field '{field}': {why}")


def req_str(j, field):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def opt_str(j, field, default=None):
    v = j.get(field, default)
    if v is not None and not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(j, field, positive=False):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if positive and v <= 0:
        _bad(field, "must be > 0")
    return v


def opt_int(j, field, default=None, positive=False):
    v = j.get(field, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if positive and v <= 0:
        _bad(field, "must be > 0")
    return v


def req_num(j, field, positive=False):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field, "must be a number")
    if positive and not (v > 0):
        _bad(field, "must be > 0")
    return v


def req_bool(j, field):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def opt_bool(j, field, default=False):
    v = j.get(field, default)
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_enum(j, field, allowed):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, str) or v not in allowed:
        _bad(field, f"must be one of {', '.join(allowed)}")
    return v


def opt_enum(j, field, allowed, default):
    v = j.get(field, default)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, f"must be one of {', '.join(allowed)}")
    return v


def req_dt(j, field):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    dt = parse_dt(v)
    if dt is None:
        _bad(field, "must be a valid ISO 8601 datetime")
    return dt


def req_str_list(j, field):
    v = j.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(field, "must be an array of strings")
    return list(v)


def opt_str_list(j, field, default=None):
    if default is None:
        default = []
    v = j.get(field, default)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(field, "must be an array of strings")
    return list(v)


def req_enum_list(j, field, allowed):
    v = req_str_list(j, field)
    for x in v:
        if x not in allowed:
            _bad(field, f"entries must be among {', '.join(allowed)}")
    return v


def opt_enum_list(j, field, allowed, default=None):
    if default is None:
        default = []
    v = opt_str_list(j, field, default)
    for x in v:
        if x not in allowed:
            _bad(field, f"entries must be among {', '.join(allowed)}")
    return v
