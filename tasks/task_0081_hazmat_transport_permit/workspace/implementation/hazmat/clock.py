"""The server's logical wall clock.

The PRD §2.5 prose names this as "a single server-side logical clock that
advances strictly monotonically and reports the current value as an ISO 8601
UTC string with three fractional-second digits". In production the clock is
backed by the operating-system clock; in the test mode of the benchmark
container the clock is decoupled from the OS clock so the `POST /v1/_clock/advance`
test-harness endpoint can drive time deterministically. The convention the
rest of the application uses is to read `now()` through this module's
`current_now()` function rather than calling `datetime.utcnow()` directly,
so the test-harness's clock-advance has the global effect the PRD's prose
asserts.

The state is a module-level `_NOW` `datetime` plus a starting wall-clock
anchor; the `current_now()` function returns the simulated time as a
timezone-aware UTC `datetime`. The `advance(seconds)` mutator adds a
nonnegative duration to the simulated clock and is protected by a
`threading.Lock` so concurrent test-harness drivers cannot race the clock-
mutating sequence. The reset hook `init_clock()` re-anchors the clock to the
current OS clock at module-init or at the test harness's between-test
admin/reset call, returning the simulated `now` to "the OS wall clock" so the
container's-startup-time aligns with the host's-time.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone


# The module-level singleton state.
_CLOCK_LOCK = threading.RLock()
_NOW: datetime | None = None  # Initialized by init_clock()


def init_clock() -> None:
    """Initialize (or re-initialize) the simulated clock to the current OS
    wall-clock value. Called once at `create_app()` time and again on each
    `/v1/_admin/reset` test-harness call, which the test fixtures fire between
    tests to wipe the per-test simulated-time advances.
    """
    global _NOW
    with _CLOCK_LOCK:
        _NOW = datetime.now(timezone.utc)


def current_now() -> datetime:
    """The simulated current wall-clock value, as a timezone-aware UTC
    `datetime`. The rest of the application reads "now" exclusively through
    this function so the time-advancing test-harness endpoint's effect is
    globally observable.

    The function returns the stored `_NOW` directly (a `datetime` is immutable
    in the Python sense; the rebind on `advance()` is what changes the
    value). The lock is acquired briefly for the read so the read-then-the-
    advancing-thread's-write doesn't tear the value on platforms that wouldn't
    guarantee word-atomicity on a pointer-rebinding.
    """
    with _CLOCK_LOCK:
        if _NOW is None:
            init_clock()
            assert _NOW is not None
        return _NOW


def advance_clock(seconds: float) -> tuple[datetime, datetime]:
    """Advance the simulated clock by the given nonnegative number of seconds
    and return the pair `(prior_now, new_now)`. A negative `seconds` raises
    `ValueError`, on the PRD §2.5 prose's "the logical clock cannot go
    backwards in time, even in test mode" rule that the test-harness
    `/v1/_clock/advance` endpoint's-handler maps onto `ERR_VALIDATION` 422.

    The caller (the admin blueprint's clock-advance handler) is responsible
    for the `ERR_VALIDATION`-on-negative-input mapping and the
    `advance_seconds`-larger-than-the-deployment-cap check. This function's
    contract is "the inputs have already been validated; mutate the clock".

    Zero is a permitted no-op (returns `(now, now)`); this is the harness's
    "sync the test's idea of the clock with the server's" idempotent ping.
    """
    if seconds < 0:
        # The caller's-side handler should have caught this at the validation
        # tier; we defend in depth.
        raise ValueError("advance_seconds must be nonnegative")
    global _NOW
    with _CLOCK_LOCK:
        if _NOW is None:
            init_clock()
        assert _NOW is not None
        prior = _NOW
        # `timedelta` accepts integer-or-float seconds. The fractional-second
        # case carries through to the ISO-8601 millisecond-precision output
        # the `iso_now()` helper formats.
        from datetime import timedelta
        _NOW = _NOW + timedelta(seconds=seconds)
        return prior, _NOW


def iso_format(dt: datetime) -> str:
    """Format a UTC `datetime` as the canonical ISO 8601 string with the
    millisecond precision and the trailing `Z` zone indicator. The PRD §2.5
    "ISO 8601 UTC string with three fractional-second digits" convention is
    the canonical observable; the response-envelope's `api_request_timestamp`
    and every `created_at`, `updated_at`, `valid_from`, `valid_until`,
    `inspected_at`, `valid_until` (on the inspection), `issued_at`, `voided_at`,
    `observed_at`, `upheld_at`, `actual_departure_at`, `actual_arrival_at`,
    `aborted_at`, `reported_at`, `received_at`, `last_verified_at`,
    `endorsement_valid_until`, `submitted_at`, `approved_at`, `revoked_at`,
    and the renewal-history entry's timestamp fields all use this format.
    The conversion truncates to milliseconds (drops the trailing microseconds
    beyond the three-digit-millisecond precision) and uses the literal `Z`
    rather than `+00:00` for the UTC zone, matching the PRD's wording.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        # Convert to UTC so the output is unambiguously UTC. The arithmetic
        # is the standard offset-subtraction; the result is timezone-aware
        # with the UTC offset.
        dt = dt.astimezone(timezone.utc)
    # The default isoformat() emits microsecond precision with a `+00:00`
    # suffix on a timezone-aware UTC datetime. We rewrite to the
    # millisecond-and-Z form the PRD pins.
    # The microsecond field is the integer 0..999_999; the millisecond is
    # microsecond // 1000.
    millis = dt.microsecond // 1000
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{millis:03d}Z"


def iso_now() -> str:
    """The canonical ISO 8601 string of the current simulated clock value.
    A shorthand the response-envelope's `api_request_timestamp` field and
    the system-set timestamp fields' write paths use to stamp the current
    moment onto the relevant rows or response-meta keys.
    """
    return iso_format(current_now())


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 datetime string from the request body or query
    parameter back into a timezone-aware UTC `datetime`. The accepted forms
    are the canonical millisecond-and-Z form `YYYY-MM-DDTHH:MM:SS.sssZ`, the
    second-precision form `YYYY-MM-DDTHH:MM:SSZ`, the microsecond-precision
    form, and any form Python's `datetime.fromisoformat` understands as of
    Python 3.11 (which accepts the `Z` suffix natively). A malformed input
    raises `ValueError` which the body-shape validation tier maps onto
    `ERR_VALIDATION` 422.

    The function normalizes the returned datetime to UTC: a naive (no-zone)
    input is interpreted as UTC; an aware non-UTC input is converted to UTC.
    The rest of the application's datetime-arithmetic assumes UTC throughout.
    """
    if not isinstance(value, str):
        raise ValueError("datetime field must be a string")
    # Python <3.11 `fromisoformat` doesn't handle the trailing `Z`. Replace
    # the `Z` with `+00:00` for cross-version compatibility.
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
