"""In-memory data store. Everything lives in module-level dicts that are
re-created fresh on every process boot. NOTHING is seeded here.

The test harness restarts the server (via start.sh) before every test, so a
fresh import gives a clean, empty ledger.
"""
import datetime
import uuid

# One dict per entity type, keyed by id (UUID string, no prefix per PRD §2.4).
customers = {}
invoices = {}
payments = {}
payment_applications = {}
disputes = {}
promises = {}
write_offs = {}
dunning_sequences = {}
dunning_notices = {}
dunning_pauses = {}
statements = {}


# ---------------------------------------------------------------------------
# System clock (PRD §3.10): an AR_MANAGER can override "now" via
# POST /_clock/set_current_utc. Default is the real wall clock.
# ---------------------------------------------------------------------------
_clock_override_ms = None  # epoch milliseconds, or None for wall clock


def now_ms():
    if _clock_override_ms is not None:
        return _clock_override_ms
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)


def set_clock_ms(epoch_ms):
    global _clock_override_ms
    _clock_override_ms = epoch_ms


def new_id():
    return str(uuid.uuid4())


def iso_now():
    return iso_from_ms(real_now_ms())


def real_now_ms():
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)


def iso_from_ms(ms):
    dt = datetime.datetime.fromtimestamp(ms / 1000.0, tz=datetime.timezone.utc)
    # ISO 8601 UTC with exactly three fractional digits and a trailing Z.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(int(dt.microsecond / 1000))
