"""Body-schema conformance: rung 3 of PRD 2.9, always ERR_INVALID_REQUEST."""

import json
import re
from decimal import Decimal

from flask import request

from errors import ApiError
from store import parse_iso_date, parse_iso_instant

LOCI = ("A", "B", "C", "DRB1", "DQB1")

_CODE_RE = re.compile(r"^[A-Z0-9-]+$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ALLELE_RE = re.compile(r"^[^:\s]+:[^:\s]+$")
_ANTIGEN_RE = re.compile(r"^[^:\s]+$")


def bad(message="Invalid request body."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def read_body():
    """Parse the JSON body, keeping decimal literals exact."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        bad("Body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Body must be a JSON object.")
    return parsed


def _present(body, field):
    return isinstance(body, dict) and field in body and body[field] is not None


def req_str(body, field, min_len=1, max_len=None, pattern=None):
    if not _present(body, field):
        bad("%s is required." % field)
    return _check_str(body[field], field, min_len, max_len, pattern)


def opt_str(body, field, min_len=1, max_len=None, pattern=None, default=None):
    if not _present(body, field):
        return default
    return _check_str(body[field], field, min_len, max_len, pattern)


def _check_str(value, field, min_len, max_len, pattern):
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if len(value) < min_len:
        bad("%s is too short." % field)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long." % field)
    if pattern is not None and not pattern.match(value):
        bad("%s is malformed." % field)
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        bad("%s is required." % field)
    return _check_int(body[field], field, minimum, maximum)


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if not _present(body, field):
        return default
    return _check_int(body[field], field, minimum, maximum)


def _check_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s is below its minimum." % field)
    if maximum is not None and value > maximum:
        bad("%s is above its maximum." % field)
    return value


def req_bool(body, field):
    if not _present(body, field):
        bad("%s is required." % field)
    if not isinstance(body[field], bool):
        bad("%s must be a boolean." % field)
    return body[field]


def opt_bool(body, field, default=None):
    if not _present(body, field):
        return default
    if not isinstance(body[field], bool):
        bad("%s must be a boolean." % field)
    return body[field]


def req_num(body, field, gt=None, ge=None, le=None, max_dp=None):
    if not _present(body, field):
        bad("%s is required." % field)
    return _check_num(body[field], field, gt, ge, le, max_dp)


def opt_num(body, field, gt=None, ge=None, le=None, max_dp=None, default=None):
    if not _present(body, field):
        return default
    return _check_num(body[field], field, gt, ge, le, max_dp)


def _check_num(value, field, gt, ge, le, max_dp):
    if isinstance(value, bool):
        bad("%s must be a number." % field)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        value = Decimal(repr(value))
    else:
        bad("%s must be a number." % field)
    if not value.is_finite():
        bad("%s must be a finite number." % field)
    if gt is not None and value <= Decimal(gt):
        bad("%s must be greater than %s." % (field, gt))
    if ge is not None and value < Decimal(ge):
        bad("%s is below its minimum." % field)
    if le is not None and value > Decimal(le):
        bad("%s is above its maximum." % field)
    if max_dp is not None:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_dp:
            bad("%s carries more than %d decimal places." % (field, max_dp))
    return value


def req_enum(body, field, allowed):
    if not _present(body, field):
        bad("%s is required." % field)
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        bad("%s is not one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    if not _present(body, field):
        bad("%s is required." % field)
    return _check_date(body[field], field)


def opt_date(body, field, default=None):
    if not _present(body, field):
        return default
    return _check_date(body[field], field)


def _check_date(value, field):
    parsed = parse_iso_date(value)
    if parsed is None:
        bad("%s must be a YYYY-MM-DD UTC calendar date." % field)
    return parsed


def req_instant(body, field):
    if not _present(body, field):
        bad("%s is required." % field)
    parsed = parse_iso_instant(body[field])
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant." % field)
    return parsed


def req_obj(body, field):
    if not _present(body, field):
        bad("%s is required." % field)
    if not isinstance(body[field], dict):
        bad("%s must be an object." % field)
    return body[field]


def opt_obj(body, field, default=None):
    if not _present(body, field):
        return default
    if not isinstance(body[field], dict):
        bad("%s must be an object." % field)
    return body[field]


def req_enum_list(body, field, allowed, allow_empty=False, default=None,
                  required=True):
    if not _present(body, field):
        if required:
            bad("%s is required." % field)
        return default
    value = body[field]
    if not isinstance(value, list):
        bad("%s must be an array." % field)
    if not allow_empty and len(value) == 0:
        bad("%s must not be empty." % field)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("%s contains an unknown value." % field)
        if item in seen:
            bad("%s contains duplicates." % field)
        seen.append(item)
    return seen


def hla_typing(body, field, antigen_allowed=()):
    """Exactly the five loci, each an array of exactly two strings.

    Loci named in antigen_allowed may carry antigen-level strings (first field
    only); every other locus must carry allele-level strings (PRD 3.2).
    """
    value = req_obj(body, field)
    if set(value.keys()) != set(LOCI):
        bad("%s must carry exactly the five loci A, B, C, DRB1, DQB1." % field)
    out = {}
    for locus in LOCI:
        alleles = value[locus]
        if not isinstance(alleles, list) or len(alleles) != 2:
            bad("%s.%s must be an array of exactly two strings." % (field, locus))
        pair = []
        for allele in alleles:
            if not isinstance(allele, str) or not allele.strip():
                bad("%s.%s must contain strings." % (field, locus))
            text = allele.strip()
            if locus in antigen_allowed:
                if not (_ALLELE_RE.match(text) or _ANTIGEN_RE.match(text)):
                    bad("%s.%s carries a malformed typing string." % (field, locus))
            else:
                if not _ALLELE_RE.match(text):
                    bad("%s.%s must be allele-level (field:allele)." % (field, locus))
            pair.append(text)
        out[locus] = pair
    return out


def hla_typing_any_resolution(body, field):
    """Five loci, two strings each; resolution is judged by a later rung."""
    value = req_obj(body, field)
    if set(value.keys()) != set(LOCI):
        bad("%s must carry exactly the five loci A, B, C, DRB1, DQB1." % field)
    out = {}
    for locus in LOCI:
        alleles = value[locus]
        if not isinstance(alleles, list) or len(alleles) != 2:
            bad("%s.%s must be an array of exactly two strings." % (field, locus))
        pair = []
        for allele in alleles:
            if not isinstance(allele, str) or not allele.strip():
                bad("%s.%s must contain strings." % (field, locus))
            pair.append(allele.strip())
        out[locus] = pair
    return out


def is_allele_level(text):
    return bool(_ALLELE_RE.match(text))


CODE_RE = _CODE_RE
COUNTRY_RE = _COUNTRY_RE
CURRENCY_RE = _CURRENCY_RE
