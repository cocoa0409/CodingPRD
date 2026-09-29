"""Schema-conformance helpers (validation ladder rank 6 -> ERR_INVALID_REQUEST)
and range coherence (rank 7 -> ERR_INVALID_DATE_RANGE)."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from db import _parse_iso
from errors import fail
from numeric import D

VERSION_FIELDS = ("expected_pathway_version", "expected_facility_version")


class Body:
    """Wraps a decoded JSON body.  Every accessor raises ERR_INVALID_REQUEST on
    a violation, so route code reads like the PRD's field list."""

    def __init__(self, raw, allow_version_fields=()):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        self.raw = raw
        for f in VERSION_FIELDS:
            if f in raw and f not in allow_version_fields:
                fail("ERR_INVALID_REQUEST",
                     "%s is not accepted by this operation." % f)

    # -- presence ------------------------------------------------------------
    def has(self, name):
        return name in self.raw and self.raw[name] is not None

    def _present(self, name, required):
        if name not in self.raw or self.raw[name] is None:
            if required:
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
            return False
        return True

    # -- strings -------------------------------------------------------------
    def string(self, name, required=True, default=None, allow_blank=False):
        if not self._present(name, required):
            return default
        v = self.raw[name]
        if not isinstance(v, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
        if not allow_blank and v.strip() == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % name)
        return v

    def ref(self, name, required=True):
        """Foreign-key field: must be a non-blank string."""
        return self.string(name, required=required)

    # -- booleans ------------------------------------------------------------
    def boolean(self, name, required=True, default=None):
        if not self._present(name, required):
            return default
        v = self.raw[name]
        if not isinstance(v, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
        return v

    # -- integers ------------------------------------------------------------
    def integer(self, name, required=True, default=None,
                gt=None, ge=None, lt=None, le=None):
        if not self._present(name, required):
            return default
        v = self.raw[name]
        if isinstance(v, bool) or not isinstance(v, int):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
        self._bounds(name, D(v), gt, ge, lt, le)
        return v

    # -- decimals ------------------------------------------------------------
    def number(self, name, scale, required=True, default=None,
               gt=None, ge=None, lt=None, le=None):
        if not self._present(name, required):
            return default
        v = self.raw[name]
        if isinstance(v, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
        if isinstance(v, int):
            dv = D(v)
        elif isinstance(v, Decimal):
            dv = v
        elif isinstance(v, float):
            dv = D(v)
        else:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
        try:
            if not dv.is_finite():
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % name)
        except InvalidOperation:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
        if scale is not None:
            exp = dv.as_tuple().exponent
            places = -exp if exp < 0 else 0
            if places > scale:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' accepts at most %d decimal places." % (name, scale))
        self._bounds(name, dv, gt, ge, lt, le)
        return dv

    def _bounds(self, name, dv, gt, ge, lt, le):
        if gt is not None and not dv > D(gt):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, gt))
        if ge is not None and not dv >= D(ge):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, ge))
        if lt is not None and not dv < D(lt):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be less than %s." % (name, lt))
        if le is not None and not dv <= D(le):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, le))

    # -- enums ---------------------------------------------------------------
    def enum(self, name, members, required=True, default=None):
        if not self._present(name, required):
            return default
        v = self.raw[name]
        if not isinstance(v, str) or v not in members:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must be one of: %s." % (name, ", ".join(members)))
        return v

    # -- dates / datetimes ---------------------------------------------------
    def date(self, name, required=True, default=None):
        if not self._present(name, required):
            return default
        v = self.raw[name]
        if not isinstance(v, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)
        return parse_date(v, name)

    def datetime_utc(self, name, required=True, default=None):
        """Returns (raw_string, aware datetime)."""
        if not self._present(name, required):
            return default, None
        v = self.raw[name]
        if not isinstance(v, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
        dt = _parse_iso(v)
        if dt is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
        return v, dt


def parse_date(text, name="date"):
    if not isinstance(text, str) or len(text) != 10 or text[4] != "-" or text[7] != "-":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)


def date_of(text):
    """Parse a stored YYYY-MM-DD string that is already known to be valid."""
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def require_range(start, end):
    if start is not None and end is not None and start > end:
        fail("ERR_INVALID_DATE_RANGE", "Range start must not be after range end.")


def require_strict_range(start, end):
    if start is not None and end is not None and not start < end:
        fail("ERR_INVALID_DATE_RANGE", "window_start_utc must be strictly before window_end_utc.")


def query_pagination(args):
    limit = _query_int(args, "limit", 10)
    offset = _query_int(args, "offset", 0)
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must be zero or more.")
    return limit, offset


def _query_int(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def utc_year(dt):
    return dt.astimezone(timezone.utc).year
