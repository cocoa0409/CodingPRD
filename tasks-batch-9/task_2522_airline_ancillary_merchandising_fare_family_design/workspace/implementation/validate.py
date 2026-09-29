"""Auth extraction, request-body schema checks and query-parameter parsing.

Precedence (PRD 2.7): auth headers (1) -> role (2) -> request shape (3) ->
path 404 (4) -> body-reference 404 (5) -> everything else.
"""
import re

from flask import request

from errors import ApiError, fail, invalid

ROLES = ('MerchandisingAnalyst', 'PricingApprover', 'DistributionManager',
         'OperationsController', 'RevenueAccountant', 'ChannelPartner')
ALL_ROLES = ROLES

CATEGORIES = ('BAGGAGE', 'SEAT', 'CHANGE', 'BOARDING', 'ONBOARD')
SEAT_LETTERS = ('A', 'B', 'C', 'D', 'E', 'F')

RE_SKU = re.compile(r'^[A-Z0-9_]{3,32}$')
RE_CODE = re.compile(r'^[A-Z0-9_]{3,24}$')
RE_LOCATOR = re.compile(r'^[A-Z0-9]{6}$')
RE_AIRPORT = re.compile(r'^[A-Z]{3}$')


def auth():
    """Priority 1: both headers present and non-empty."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if uid is None or role is None or uid.strip() == '' or role.strip() == '':
        fail('ERR_MISSING_AUTH_HEADERS')
    return uid, role


def require(role, allowed):
    """Priority 2: known role, and authorised for this endpoint."""
    if role not in ROLES or role not in allowed:
        fail('ERR_ROLE_NOT_PERMITTED')


def ctx(allowed):
    uid, role = auth()
    require(role, allowed)
    return uid, role


# --------------------------------------------------------------------------
# value validators -- every failure is ERR_INVALID_REQUEST (priority 3)
# --------------------------------------------------------------------------
def v_str(value, pattern=None, min_len=None, max_len=None):
    if not isinstance(value, str):
        invalid()
    if min_len is not None and len(value) < min_len:
        invalid()
    if max_len is not None and len(value) > max_len:
        invalid()
    if pattern is not None and not pattern.match(value):
        invalid()
    return value


def v_int(value, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid()
    if lo is not None and value < lo:
        invalid()
    if hi is not None and value > hi:
        invalid()
    return value


def v_bool(value):
    if not isinstance(value, bool):
        invalid()
    return value


def v_enum(value, members):
    if not isinstance(value, str) or value not in members:
        invalid()
    return value


def v_datetime(value):
    if not isinstance(value, str) or value.strip() == '':
        invalid()
    parse_iso(value)
    return value


def v_id(value):
    if not isinstance(value, str) or value.strip() == '':
        invalid()
    return value


def v_enum_array(value, members, min_len=1, max_len=None, distinct=True):
    if not isinstance(value, list):
        invalid()
    if min_len is not None and len(value) < min_len:
        invalid()
    if max_len is not None and len(value) > max_len:
        invalid()
    for item in value:
        v_enum(item, members)
    if distinct and len(set(value)) != len(value):
        invalid()
    return value


def v_id_array(value):
    if not isinstance(value, list):
        invalid()
    for item in value:
        v_id(item)
    return value


def parse_iso(text):
    """Parse an ISO 8601 UTC instant; anything unparseable is a shape failure."""
    from datetime import datetime, timezone
    raw = text.strip()
    if raw.endswith('Z') or raw.endswith('z'):
        raw = raw[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        invalid()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# body handling
# --------------------------------------------------------------------------
def body():
    """Return the JSON body as a dict; a malformed body is a shape failure."""
    raw = request.get_data()
    if raw is None or raw.strip() == b'':
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        invalid()
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid()
    return data


def fields(data, spec):
    """spec: list of (name, required, validator).  Validators receive the raw
    value and return the accepted value.  A validator of None accepts an
    explicit JSON null as well (nullable field)."""
    known = set(name for name, _req, _v in spec)
    for key in data.keys():
        if key not in known:
            invalid()
    out = {}
    for name, required, validator in spec:
        if name not in data:
            if required:
                invalid()
            continue
        value = data[name]
        if value is None:
            if validator is None:
                out[name] = None
                continue
            invalid()
        out[name] = validator(value) if validator is not None else value
    return out


def nullable(validator):
    def wrapped(value):
        if value is None:
            return None
        return validator(value)
    wrapped.nullable = True
    return wrapped


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def pagination():
    """PRD 2.3: limit defaults to 10 in 1..100, offset defaults to 0, >= 0."""
    limit = 10
    offset = 0
    raw = request.args.get('limit')
    if raw is not None:
        if not re.match(r'^-?\d+$', raw.strip()):
            invalid()
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            invalid()
    raw = request.args.get('offset')
    if raw is not None:
        if not re.match(r'^-?\d+$', raw.strip()):
            invalid()
        offset = int(raw.strip())
        if offset < 0:
            invalid()
    return limit, offset


def q_enum(name, members):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in members:
        invalid()
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw
