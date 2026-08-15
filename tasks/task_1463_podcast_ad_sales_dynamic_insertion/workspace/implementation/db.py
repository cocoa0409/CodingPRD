"""In-memory data store. All state lives in module-level dicts.

The store starts empty on every boot — no seeding of any kind. Every entity
is constructed via the declared API surface.
"""

# Each dict maps entity id -> entity dict (plain JSON-serializable records,
# plus internal keys prefixed with "_", stripped at serialization).
shows = {}
episodes = {}
agencies = {}
advertisers = {}
campaigns = {}
line_items = {}
ad_copies = {}
downloads = {}
impressions = {}
attribution_events = {}
invoices = {}
make_goods = {}

# Global monotonic creation counter -> deterministic created_at ordering.
_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]


# ---- Logical clock -----------------------------------------------------------
# Startup default is exactly 2026-08-01T00:00:00Z; never falls back to
# wall-clock time. Stored as the raw string supplied (echoed verbatim) plus a
# parsed datetime cache.

clock_raw = "2026-08-01T00:00:00Z"
_clock_dt_cache = None


def current_dt():
    from helpers import parse_dt

    global _clock_dt_cache
    if _clock_dt_cache is None:
        _clock_dt_cache = parse_dt(clock_raw)
    return _clock_dt_cache


def set_clock(raw: str):
    from helpers import parse_dt

    global clock_raw, _clock_dt_cache
    clock_raw = raw
    _clock_dt_cache = parse_dt(raw)
