"""In-memory data store.

The store is a set of plain Python dicts keyed by id.  It starts completely
empty on every boot: no entity is ever seeded, preloaded or hardcoded here.
Every row in this system is created by a client through a declared endpoint.
"""

import threading
import uuid
from datetime import datetime, timezone

from util import iso_now

# PRD §2.6: before any client sets it, the logical clock reads exactly this
# instant.  The server never falls back to real wall-clock time for it.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
LOGICAL_CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "venues",
    "installations",
    "calibration_runs",
    "clubs",
    "players",
    "consent_records",
    "games",
    "event_tags",
    "correction_requests",
    "rights_windows",
    "licensees",
    "feed_sessions",
    "usage_records",
    "normalization_runs",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = LOGICAL_CLOCK_DEFAULT
        # Domain "now" stamps echo the clock exactly as it reads, so that a
        # caller comparing certified_at_utc against the instant it set sees the
        # same spelling back.
        self.clock_raw = LOGICAL_CLOCK_DEFAULT_RAW
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
request_lock = threading.RLock()


def new_id():
    """PRD §2.4: server-generated UUID string, no type prefix."""
    return str(uuid.uuid4())


def audit_new(row):
    """Attach the full audit complement (PRD §2.4)."""
    stamp = iso_now()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def audit_new_immutable(row):
    """CalibrationRun / LicenseUsageRecord expose only id and created_at."""
    row["created_at"] = iso_now()
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    """PRD §2.4: refresh updated_at and increment version on every mutation."""
    if row is None:
        return row
    row["updated_at"] = iso_now()
    row["version"] = int(row.get("version", 0)) + 1
    return row


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def installations_of_venue(venue_id):
    return [r for r in store.installations.values() if r["venue_id"] == venue_id]


def runs_of_installation(installation_id):
    return [r for r in store.calibration_runs.values()
            if r["installation_id"] == installation_id]


def players_of_club(club_id):
    return [r for r in store.players.values() if r["club_id"] == club_id]


def consent_records_of_player(player_id):
    return [r for r in store.consent_records.values() if r["player_id"] == player_id]


def tags_of_game(game_id):
    return [r for r in store.event_tags.values() if r["game_id"] == game_id]


def tags_of_player(player_id):
    return [r for r in store.event_tags.values() if r["player_id"] == player_id]


def corrections_of_tag(tag_id):
    return [r for r in store.correction_requests.values()
            if r["event_tag_id"] == tag_id]


def rights_windows_of_game(game_id):
    return [r for r in store.rights_windows.values() if r["game_id"] == game_id]


def sessions_of_game(game_id):
    return [r for r in store.feed_sessions.values() if r["game_id"] == game_id]


def sessions_of_window(window_id):
    return [r for r in store.feed_sessions.values()
            if r["rights_window_id"] == window_id]


def usage_records_of_session(session_id):
    return [r for r in store.usage_records.values()
            if r["feed_session_id"] == session_id]


def usage_records_of_licensee(licensee_id):
    return [r for r in store.usage_records.values() if r["licensee_id"] == licensee_id]


def normalization_runs_of_game(game_id):
    return [r for r in store.normalization_runs.values() if r["game_id"] == game_id]


def games_of_venue(venue_id):
    return [r for r in store.games.values() if r["venue_id"] == venue_id]
