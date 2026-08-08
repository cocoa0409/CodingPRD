"""The program's logical UTC clock and the single timestamp-rendering discipline.

PRD 2.4: the service never reads the host wall clock for a business decision.
Before any operator call the logical clock reads exactly ``2026-05-01T00:00:00Z``.

TIMESTAMP RENDERING RULE (one rule, applied everywhere):

* Caller-supplied instants (``in_person_eval_at``, ``scheduled_start_at``,
  ``scheduled_end_at``, ``gap_start_at``, ``gap_end_at``, ``to_iso8601``) are
  echoed back **verbatim**, exactly as the caller wrote them.
* ``created_at`` and ``updated_at`` -- and the envelope's
  ``api_request_timestamp`` -- use one consistent rendering: ISO 8601 UTC with
  exactly three fractional-second digits (PRD 2.4).
* Every other server-written instant (``admitted_at``, ``returned_at``,
  ``discharged_at``, ``deployed_at``, ``finalized_at``, ``held_at``,
  ``occupied_at``, ``tier_entered_at``, ``current_utc``) renders the logical
  clock in the *exact* textual style the clock currently carries -- i.e. the
  string the operator set it to.
* An instant *derived* from another instant (``hold_expires_at`` from
  ``held_at``, ``ack_deadline_at`` from ``tier_entered_at``) preserves the
  fractional-digit style of its source string.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class LogicalClock(object):
    """Before any operator call the clock reads exactly DEFAULT_CLOCK_UTC."""

    def __init__(self):
        self.raw = DEFAULT_CLOCK_UTC
        self.dt = parse_iso(DEFAULT_CLOCK_UTC)

    def set(self, raw, dt):
        self.raw = raw
        self.dt = dt


CLOCK = LogicalClock()


def fractional_digits(template):
    """How many fractional-second digits the given ISO string carries."""
    if not isinstance(template, str):
        return 3
    body = template
    for suffix in ("Z", "z"):
        if body.endswith(suffix):
            body = body[:-1]
            break
    else:
        if "+" in body[10:]:
            body = body[: body.rindex("+")]
        elif body[10:].count("-") and body.rindex("-") > 10:
            body = body[: body.rindex("-")]
    if "." not in body:
        return 0
    return len(body.split(".")[-1])


def render(dt, digits=3):
    """Render an aware datetime as an ISO 8601 UTC string with N fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if digits <= 0:
        return base + "Z"
    micros = "%06d" % dt.microsecond
    return base + "." + micros[:digits].ljust(digits, "0") + "Z"


def render_like(dt, template):
    """Render ``dt`` in the same fractional-digit style as ``template``."""
    return render(dt, fractional_digits(template))


def now_dt():
    return CLOCK.dt


def now_raw():
    """The logical clock rendered exactly as the operator wrote it."""
    return CLOCK.raw


def audit_stamp():
    """created_at / updated_at rendering: three fractional digits (PRD 2.4)."""
    return render(CLOCK.dt, 3)


def plus_minutes(source_raw, minutes):
    """An instant derived from ``source_raw``, preserving its textual style."""
    source_dt = parse_iso(source_raw)
    return render_like(source_dt + timedelta(minutes=minutes), source_raw)


def utc_date(dt):
    """The YYYY-MM-DD UTC calendar date of an aware datetime."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def today_date():
    return utc_date(CLOCK.dt)


def date_str_to_dt(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def date_range_inclusive(start_date, end_date):
    """All YYYY-MM-DD strings from start to end inclusive (empty when reversed)."""
    out = []
    if start_date > end_date:
        return out
    cursor = date_str_to_dt(start_date)
    stop = date_str_to_dt(end_date)
    while cursor <= stop:
        out.append(utc_date(cursor))
        cursor = cursor + timedelta(days=1)
    return out
