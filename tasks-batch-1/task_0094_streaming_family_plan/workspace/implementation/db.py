"""In-memory data store for the Streaming Family Plan API.

Starts empty on every process boot. No seeding, no preloading, no disk
persistence. The test harness re-launches start.sh before every test under
`--isolation per-test-server`, so a fresh Store() per process is exactly the
required clean-slate behavior.
"""
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Real wall-clock ISO 8601 UTC with three fractional digits.

    Used only as the default value of the logical clock at boot. All
    time-sensitive computation reads the logical clock (store.current_utc),
    which the test seam advances via POST /_clock/advance (PRD §2.9).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (now.microsecond // 1000))


class Store:
    """Pure in-memory dict store keyed by id. One instance per process."""

    def __init__(self):
        # Catalog / configuration (lean: id + created_at only)
        self.subscription_plans = {}   # id -> SubscriptionPlan
        self.titles = {}               # id -> Title
        self.plan_changes = {}         # id -> PlanChange (lean)

        # Full-spine aggregates (id + created_at + updated_at + version)
        self.accounts = {}             # id -> Account
        self.profiles = {}             # id -> Profile
        self.parental_controls = {}    # id -> ParentalControl
        self.invites = {}              # id -> Invite
        self.devices = {}              # id -> Device
        self.stream_sessions = {}      # id -> StreamSession
        self.downloads = {}            # id -> Download
        self.watch_progress = {}       # id -> WatchProgress

        # Logical clock — ISO 8601 UTC string. Advanced only by the test seam.
        # Defaults to the real wall clock at boot (PRD §2.9).
        self.current_utc = utc_now_iso()


# Module-level singleton (per process). Re-created on every process boot.
store = Store()
