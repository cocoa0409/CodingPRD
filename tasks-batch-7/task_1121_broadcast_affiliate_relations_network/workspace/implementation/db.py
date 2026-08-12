"""In-memory data store. No persistence — every boot starts empty."""
from datetime import datetime, timezone


# Logical clock — starts at 2026-05-01T00:00:00Z per PRD §2.8
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        # entity-name -> {id -> record dict}
        self.networks = {}
        self.station_groups = {}
        self.stations = {}
        self.territories = {}
        self.agreements = {}
        self.programs = {}
        self.clearance_reports = {}
        self.preemptions = {}
        self.avail_allocations = {}
        self.retrans_settlements = {}
        self.outage_events = {}
        self.outage_credits = {}
        self.renewal_offers = {}
        self.compliance_reports = {}
        self.exclusivity_claims = {}
        # Logical clock: single global clock per server (set via /_clock/set_current_utc)
        self.logical_clock_utc = DEFAULT_CLOCK_ISO


store = Store()


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp. Accepts trailing 'Z' or +00:00."""
    if s is None:
        raise ValueError("cannot parse None as datetime")
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S.")
    ms = f"{dt.microsecond // 1000:03d}"
    return base + ms + "Z"


def now_iso() -> str:
    return format_iso(datetime.now(timezone.utc))
