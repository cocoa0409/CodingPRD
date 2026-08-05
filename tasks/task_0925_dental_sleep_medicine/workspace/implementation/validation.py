"""Rungs 7, 8 and 9: required fields and JSON types, the closed enum list, and
the numeric / calendar domains.

The enum routing of PRD 2.8 is an iff-rule: exactly the fields declared with an
`enum` member set below route an unrecognised value to ERR_INVALID_ENUM (422).
Every other malformed input — wrong JSON type, out-of-domain number, malformed
date, unknown field, free text — is ERR_VALIDATION (400).
"""

from flask import request

from errors import fail
from store import parse_date

# The closed enum list of PRD 2.8 — 24 entries (18 body fields + 6 action verbs).
ENUM_PROVIDER_TYPE = ("SLEEP_PHYSICIAN", "DENTIST", "DENTAL_LAB")
ENUM_PROVIDER_STATUS = ("ACTIVE", "SUSPENDED")
ENUM_PAYER_KIND = ("MEDICAL", "DENTAL")
ENUM_MODALITY = ("HSAT", "PSG")
ENUM_STUDY_PURPOSE = ("DIAGNOSTIC", "EFFICACY")
ENUM_CPAP_HISTORY = ("NONE", "FAILURE", "INTOLERANCE", "REFUSAL")
ENUM_HCPCS = ("E0486", "A9270", "K0739")
ENUM_DENIAL_REASON = ("NOT_MEDICALLY_NECESSARY", "MISSING_DOCUMENTATION", "NON_COVERED_ITEM")
ENUM_APPLIANCE_KIND = ("CUSTOM_FABRICATED", "PREFABRICATED")
ENUM_CAPTURE_METHOD = ("PVS_IMPRESSION", "DIGITAL_SCAN")
ENUM_RECALL_SEVERITY = ("CLASS_I", "CLASS_II", "CLASS_III")
ENUM_POD_METHOD = ("IN_PERSON", "SHIPPED")
ENUM_SIDE_EFFECT = ("NONE", "MILD", "MODERATE", "SEVERE")
ENUM_ADHERENCE_SOURCE = ("OBJECTIVE_MICRORECORDER", "PATIENT_ATTESTED")
ENUM_CLAIM_TYPE = ("INITIAL_DEVICE", "REPAIR", "REPLACEMENT", "CONTINUED_USE")
ENUM_REPAIR_REASON = ("DEFECT", "WEAR", "ABUSE", "LOSS")
ENUM_REFERRAL_DECISION = ("ACCEPTED", "DECLINED")
ENUM_FIT_OUTCOME = ("ACCEPTED", "REMAKE_REQUIRED")
ENUM_PA_DECISION = ("APPROVED", "DENIED")
ENUM_CLAIM_OUTCOME = ("PAID", "DENIED")
ENUM_REPORT_DECISION = ("SIGNED", "DISPUTED")
ENUM_REPAIR_OUTCOME = ("REPAIRED", "NOT_COVERED")


class Field(object):
    __slots__ = ("name", "kind", "required", "enum")

    def __init__(self, name, kind, required=False, enum=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum


def S(name, required=False, enum=None):
    return Field(name, "string", required, enum)


def I(name, required=False):
    return Field(name, "integer", required)


def N(name, required=False):
    return Field(name, "number", required)


def B(name, required=False):
    return Field(name, "boolean", required)


def D(name, required=False):
    return Field(name, "date", required)


def read_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def _type_ok(value, kind):
    if kind == "string" or kind == "date":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return True


def rung7(body, fields):
    """Required fields, declared JSON types, and unknown-field rejection.

    PRD 2.4 declares one specific exception to 2.8's unknown-field rule: a
    client-supplied `id` is *ignored*, never an error, because ids are minted
    by the server.
    """
    declared = set(f.name for f in fields)
    for key in body:
        if key == "id":
            continue
        if key not in declared:
            fail("ERR_VALIDATION", "Unknown field '%s'." % key)
    for f in fields:
        present = f.name in body and body[f.name] is not None
        if f.required and not present:
            fail("ERR_VALIDATION", "Field '%s' is required." % f.name)
        if present and not _type_ok(body[f.name], f.kind):
            fail("ERR_VALIDATION", "Field '%s' has the wrong JSON type." % f.name)


def rung8(body, fields):
    """Enum membership for exactly the fields carrying a declared member set."""
    for f in fields:
        if f.enum is None:
            continue
        if f.name in body and body[f.name] is not None:
            if body[f.name] not in f.enum:
                fail("ERR_INVALID_ENUM", "Field '%s' carries an undeclared value." % f.name)


def get(body, name, default=None):
    value = body.get(name)
    return default if value is None else value


def date_of(body, name):
    """Rung 9 calendar parse.  Returns None when the field was not supplied."""
    raw = body.get(name)
    if raw is None:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return parsed


def between(body, name, low, high):
    value = body.get(name)
    if value is None:
        return
    if value < low or value > high:
        fail("ERR_VALIDATION", "Field '%s' is outside its declared domain." % name)


def at_least(body, name, low):
    value = body.get(name)
    if value is None:
        return
    if value < low:
        fail("ERR_VALIDATION", "Field '%s' is outside its declared domain." % name)


def multiple_of_quarter(body, name):
    value = body.get(name)
    if value is None:
        return
    scaled = round(float(value) * 100)
    if abs(float(value) * 100 - scaled) > 1e-9 or scaled % 25 != 0:
        fail("ERR_VALIDATION", "Field '%s' must be an exact multiple of 0.25." % name)


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit, "limit")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must lie between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset, "offset")
        if offset < 0:
            fail("ERR_VALIDATION", "offset may not be negative.")
    return limit, offset


def _as_int(raw, name):
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    value = int(text)
    return value
