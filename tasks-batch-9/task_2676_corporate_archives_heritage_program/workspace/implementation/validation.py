"""Rung 3 payload-shape validation helpers plus the declared enumerations."""

from flask import request

from core import parse_instant
from errors import ApiError

# --- declared enumerations (PRD section 3) ---------------------------------

DISPOSITION_ACTIONS = ("DESTROY", "REVIEW", "TRANSFER")
SENSITIVITY_LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
TRANSFER_INSTRUMENTS = ("DEED_OF_GIFT", "INTERNAL_TRANSFER", "PURCHASE", "BEQUEST")
CONDITION_GRADES = ("GOOD", "FAIR", "POOR", "UNSTABLE")
ORIGINAL_FORMATS = ("PAPER", "PHOTO", "FILM", "MAGNETIC_TAPE", "BORN_DIGITAL")
TARGET_FORMATS = ("PRESERVATION_TIFF", "PRESERVATION_WAV", "PRESERVATION_MKV")
ARRANGEMENT_LEVELS = ("COLLECTION", "SERIES", "FILE", "ITEM")
REQUESTER_CLASSES = ("INTERNAL_BUSINESS", "EXTERNAL_RESEARCHER", "MEDIA")
SCREENING_DECISIONS = ("GRANT_FULL", "GRANT_REDACTED", "DENY", "CHANGES_REQUESTED")
APPROVAL_SCOPES = ("FULL", "REDACTED")
CONSENT_ACTIONS = ("SIGN", "RESTRICT", "WITHDRAW")
TRANSCRIPTION_ACTIONS = ("START_DRAFT", "MARK_REVIEWED", "APPROVE")
DEACCESSION_ROUTES = ("DESTRUCTION", "DONATION")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


_MISSING = object()


def _present(payload, name, required):
    if name not in payload or payload[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return False
    return True


def vstr(payload, name, min_len=1, max_len=None, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def vint(payload, name, minimum=None, maximum=None, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def vnum(payload, name, minimum=None, maximum=None, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    value = float(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def vbool(payload, name, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def venum(payload, name, allowed, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def vinstant(payload, name, required=True, default=None):
    if not _present(payload, name, required):
        return default
    try:
        return parse_instant(payload[name])
    except ValueError:
        bad("Field '%s' must be an ISO 8601 UTC instant." % name)


def vid(payload, name, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-empty identifier string." % name)
    return value


def vid_list(payload, name, max_len, required=True, default=None):
    """Array of identifiers: 0..max_len entries, no duplicates (rung 3)."""
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if len(value) > max_len:
        bad("Field '%s' must hold at most %d entries." % (name, max_len))
    for entry in value:
        if not isinstance(entry, str) or entry.strip() == "":
            bad("Field '%s' must contain identifier strings." % name)
    if len(set(value)) != len(value):
        bad("Field '%s' must not contain duplicate identifiers." % name)
    return list(value)
