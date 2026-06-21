"""In-memory data store.

Everything lives in process memory keyed by id. The store starts EMPTY on every
boot — nothing is seeded, preloaded, or hardcoded (the test harness restarts the
server before every test and builds all state through the API).

The logical clock (PRD §2.9) starts at exactly 2026-01-01T00:00:00Z and never
falls back to wall-clock until explicitly set.
"""

import uuid

# domain_constants — SCAFFOLD §1.0 / PRD §2.9, §3.2, §3.3, §3.5, §3.7
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"
IAB_MIN_BYTES = 1048576              # 1 MiB IAB counted-download threshold (>=)
MAX_TRANSCODE_ATTEMPTS = 3          # FAILED becomes terminal media_status only at attempt 3
MID_ROLL_BUFFER_MS = 1000          # required silent gap on each side of a MID_ROLL interval
GRACE_MS = 604800000               # 7 days; PAST_DUE -> CANCELLED window after period_end
PREMIUM_MULTIPLIER = "1.25"
HIGH_FILL_MULT = "1.20"
MID_FILL_MULT = "1.10"
LOW_FILL_MULT = "1.00"
MIN_PLACEMENT_CENTS = 100

CATEGORIES = {"TECH", "NEWS", "COMEDY", "BUSINESS", "EDUCATION", "TRUE_CRIME"}
POSITIONS = {"PRE_ROLL", "MID_ROLL", "POST_ROLL"}
CHANNELS = {"APPLE", "SPOTIFY"}
VISIBILITIES = {"PUBLIC", "PRIVATE"}
ROLES = {"Publisher", "Advertiser", "Listener", "PlatformAdmin"}


class Store:
    """All collections plus the logical clock. One instance per process."""

    def __init__(self):
        self.publishers = {}
        self.advertisers = {}
        self.listeners = {}
        self.shows = {}
        self.episodes = {}
        self.media_assets = {}
        self.feeds = {}
        self.subscriptions = {}
        self.distributions = {}
        self.ad_campaigns = {}
        self.ad_placements = {}
        self.download_events = {}
        self.payout_statements = {}
        # Logical clock value as an ISO-8601 string (PRD §2.9).
        self.clock = CLOCK_DEFAULT_UTC


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())
