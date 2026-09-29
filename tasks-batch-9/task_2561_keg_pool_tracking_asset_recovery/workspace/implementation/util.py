"""Shared primitives: timestamps, rounding, day arithmetic, shape validation."""
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request

import clock
from errors import fail

SECONDS_PER_DAY = 86400

ROLES = ("PoolOperator", "Brewer", "Distributor", "ServiceTechnician",
         "AssetRecoveryAnalyst")

# ---------------------------------------------------------------- identity ---


def new_id():
    return str(uuid.uuid4())


# -------------------------------------------------------------- timestamps ---


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_instant(dt):
    """ISO 8601 UTC for a business instant.

    PRD renders the logical clock as ``2026-08-01T00:00:00Z`` and stores
    supplied instants (``scanned_at``, ``received_at``, ``dispatched_at`` ...)
    as given, so a whole-second instant carries no fractional part.  Only
    ``created_at``/``updated_at``/``api_request_timestamp`` are declared to
    carry three fractional digits.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class MillisInstant(datetime):
    """An instant that renders with three fractional digits wherever it lands.

    PRD declares ``created_at`` "an ISO 8601 UTC timestamp with three
    fractional digits", and separately declares that when the caller omits
    ``last_pressure_test_at`` "the server records the new keg's own
    ``created_at``".  A copy of ``created_at`` therefore has to serialise
    exactly like its source, even though the field it lands in is a business
    instant everywhere else.
    """

    @classmethod
    def of(cls, dt):
        if dt is None:
            return None
        return cls(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
                   dt.microsecond, dt.tzinfo)


def _to_millis(dt):
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def parse_instant(value, field):
    if not isinstance(value, str) or "T" not in value:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _to_millis(parsed.astimezone(timezone.utc))


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date." % field)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date." % field)


def now():
    return clock.now()


def logical_date():
    return clock.now().date()


def not_future_instant(dt, field):
    """Priority 33: no supplied instant may lie ahead of the logical clock."""
    if dt is not None and dt > clock.now():
        fail("ERR_SCAN_TIMESTAMP_FUTURE",
             "%s lies in the future relative to the logical clock." % field)


def not_future_date(value, field):
    if value is not None and value > logical_date():
        fail("ERR_SCAN_TIMESTAMP_FUTURE",
             "%s lies in the future relative to the logical clock." % field)


# ------------------------------------------------------------ day counting ---


def elapsed_days(start, end):
    """Whole days between two instants, flooring the remainder away."""
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds() // SECONDS_PER_DAY)


def spell_days(start, at):
    """A clock read: floored to whole days and never negative."""
    if start is None:
        return 0
    return max(0, elapsed_days(start, at))


# ---------------------------------------------------------------- rounding ---


def dec(value):
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole unit (cents / basis points)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to exactly two decimal places."""
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ------------------------------------------------- version / updated_at ------


def bump(row):
    """Advance a row's version by exactly one per request, refreshing
    updated_at.  A second cascade link touching the same row inside the same
    request does not bump it again (PRD 2.4)."""
    if "version" not in row:
        return
    bumped = getattr(g, "_bumped_rows", None)
    if bumped is None:
        bumped = set()
        g._bumped_rows = bumped
    if row["id"] in bumped:
        return
    bumped.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = clock.now()


def apply_changes(row, changes):
    """Write a recompute result.  A recompute that alters nothing neither
    bumps the version nor refreshes updated_at (PRD 2.4)."""
    if any(row.get(key) != value for key, value in changes.items()):
        row.update(changes)
        bump(row)
        return True
    return False


def common_fields(versioned=True):
    stamp = clock.now()
    if versioned:
        return {"id": new_id(), "created_at": stamp, "updated_at": stamp,
                "version": 1}
    return {"id": new_id(), "created_at": stamp}


# ----------------------------------------------------------------- payload ---


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


VERSION_FIELDS = ("expected_agreement_version", "expected_keg_version",
                  "expected_claim_version")


def forbid_version_fields(payload, allowed=None):
    """Operations not guarded by a stale-version check take no version field
    at all and must reject one invented by a client (PRD 2.7)."""
    for field in VERSION_FIELDS:
        if field == allowed:
            continue
        if field in payload:
            fail("ERR_INVALID_REQUEST",
                 "%s is not accepted by this operation." % field)


def missing(field):
    fail("ERR_INVALID_REQUEST", "%s is required." % field)


def bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s." % (field, why))


def req_present(payload, field):
    if field not in payload or payload[field] is None:
        missing(field)
    return payload[field]


def req_string(payload, field, min_len=1, max_len=None, pattern=None,
               non_blank=True):
    value = req_present(payload, field)
    return opt_string(payload, field, min_len, max_len, pattern, non_blank,
                      value=value)


def opt_string(payload, field, min_len=1, max_len=None, pattern=None,
               non_blank=True, default=None, value=None):
    if value is None:
        if field not in payload or payload[field] is None:
            return default
        value = payload[field]
    if not isinstance(value, str):
        bad(field, "must be a string")
    if non_blank and not value.strip():
        bad(field, "must not be blank")
    if min_len is not None and len(value) < min_len:
        bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(field, "must be at most %d characters" % max_len)
    if pattern is not None and not re.match(pattern, value):
        bad(field, "is malformed")
    return value


def req_int(payload, field, minimum=None, maximum=None):
    value = req_present(payload, field)
    return _check_int(field, value, minimum, maximum)


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if field not in payload or payload[field] is None:
        return default
    return _check_int(field, payload[field], minimum, maximum)


def _check_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be <= %d" % maximum)
    return value


def req_number(payload, field, minimum=None, maximum=None, max_decimals=None):
    value = req_present(payload, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(field, "must be a number")
    if minimum is not None and value <= minimum:
        bad(field, "must be greater than %s" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be <= %s" % maximum)
    if max_decimals is not None:
        exponent = dec(value).normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            bad(field, "carries at most %d decimal places" % max_decimals)
    return value


def req_bool(payload, field):
    value = req_present(payload, field)
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def opt_bool(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    if not isinstance(payload[field], bool):
        bad(field, "must be a boolean")
    return payload[field]


def req_enum(payload, field, domain):
    value = req_present(payload, field)
    if not isinstance(value, str) or value not in domain:
        bad(field, "must be one of %s" % ", ".join(domain))
    return value


def opt_enum(payload, field, domain, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_enum(payload, field, domain)


def req_id_list(payload, field):
    value = req_present(payload, field)
    if not isinstance(value, list):
        bad(field, "must be an array")
    for element in value:
        if not isinstance(element, str) or not element:
            bad(field, "must contain resource identifiers")
    return value


def forbid(payload, field, why):
    if field in payload and payload[field] is not None:
        fail("ERR_INVALID_REQUEST", "%s %s." % (field, why))
