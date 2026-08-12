"""In-memory store and logical clock. Store starts EMPTY on every boot."""

from datetime import datetime, timezone

# Logical clock — startup default per PRD §2.4 is exactly 2026-05-01T00:00:00Z
_DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        self.zones = {}            # id -> ServiceZone
        self.households = {}       # id -> Household
        self.subscriptions = {}    # id -> Subscription
        self.carts = {}            # id -> Cart
        self.routes = {}           # id -> CollectionRoute
        self.tickets = {}          # id -> PickupTicket
        self.inspections = {}      # id -> ContaminationInspection
        self.surge_events = {}     # id -> SurgeEvent
        self.surge_bookings = {}   # id -> SurgeBooking
        self.facilities = {}       # id -> ProcessingFacility
        self.deliveries = {}       # id -> FacilityDelivery
        self.giveback_events = {}  # id -> CompostGivebackEvent
        self.claims = {}           # id -> CompostClaim
        self.credits = {}          # id -> ServiceCredit
        self.campaigns = {}        # id -> OutreachCampaign
        self._clock_iso = _DEFAULT_CLOCK

    # ---- logical clock ----
    def set_clock(self, iso: str):
        # normalize: strip trailing Z, parse, re-emit canonical Z form
        dt = _parse_dt(iso)
        self._clock_iso = _fmt_dt(dt)

    def clock(self) -> datetime:
        return _parse_dt(self._clock_iso)

    def clock_iso(self) -> str:
        return self._clock_iso

    def clock_date(self):
        return self.clock().date()


def _parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 string that may end with Z; return aware UTC datetime."""
    if s is None:
        raise ValueError("None datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_dt(dt: datetime) -> str:
    """Format an aware UTC datetime as ISO 8601 with Z suffix (second precision)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_ms() -> str:
    """Timestamp for created_at/updated_at — ISO 8601 UTC with 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


# Module-level singleton store (fresh per process)
STORE = Store()
