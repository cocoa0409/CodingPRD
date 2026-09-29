"""In-memory data store.

Everything lives in plain dicts; the store is empty on every boot. No entity is
ever seeded, preloaded or hardcoded at startup (PRD: every entity is created
through the declared API surface).
"""

import threading
import uuid
from datetime import datetime, timezone

from timeutil import fmt_dt

# PRD 2.6: at startup the logical clock reads exactly 2026-08-01T00:00:00Z and
# must keep reading that instant until explicitly repositioned.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Collections whose rows carry `version` / `updated_at` (PRD 2.4). Load studies
# and community objections are excluded: a study is an immutable artifact and an
# objection is not an addressable resource.
VERSIONED = (
    "programs",
    "utilities",
    "water_sources",
    "sites",
    "applications",
    "negotiations",
    "zoning",
    "ppas",
    "options",
)

# PRD 2.4 names the version-bumping trigger for a water source as a change to
# "a water source's drought stage" -- and PRD 3.2 enumerates the effects of a
# screening exhaustively, incrementing only the *site's* version even though the
# serving basin's `committed_annual_demand_mgal` is recomputed at the same time.
# These figures are therefore excluded from the basin's change set: they are pure
# functions of the drought stage (which is in the set) and of sibling demand
# (which belongs to the sibling's own request), so a basin's version moves only
# when a drought declaration moves its stage (PRD 3.3).
DIFF_EXCLUDED = {
    "water_sources": (
        "committed_annual_demand_mgal",
        "effective_supply_mgal",
        "stage_curtailment_pct",
    ),
}


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.programs = {}
        self.utilities = {}
        self.water_sources = {}
        self.sites = {}
        self.applications = {}
        self.load_studies = {}
        self.negotiations = {}
        self.zoning = {}
        self.objections = {}
        self.ppas = {}
        self.options = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.force_dirty = set()
        # Sites whose site_capital_commitment_usd must be re-aggregated at the end
        # of this request (the figure is trigger-based, not blanket-recomputed).
        self.capital_dirty = set()

    # --- identity / clock ---------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        return fmt_dt(self.clock)

    def coll(self, name):
        return getattr(self, name)

    # --- change tracking ----------------------------------------------------
    def snapshot(self):
        """Copy every versioned row so post-request diffing can bump versions."""
        self.force_dirty = set()
        self.capital_dirty = set()
        return {
            name: {rid: dict(row) for rid, row in self.coll(name).items()}
            for name in VERSIONED
        }

    def apply_versions(self, snap):
        """PRD 2.4: any request that changes a row bumps its version by exactly 1
        and refreshes updated_at, including changes performed by a cascade."""
        stamp = self.now_iso()
        for name in VERSIONED:
            before = snap.get(name, {})
            ignored = DIFF_EXCLUDED.get(name, ())
            for rid, row in self.coll(name).items():
                old = before.get(rid)
                if old is None:
                    # Freshly created in this request: version already 1.
                    continue
                if rid in self.force_dirty or _differs(old, row, ignored):
                    row["version"] = int(row.get("version", 1)) + 1
                    row["updated_at"] = stamp
        self.force_dirty = set()

    def touch(self, row):
        """Force a version bump even when no field value changed."""
        self.force_dirty.add(row["id"])


def _differs(old, new, ignored=()):
    keys = set(old) | set(new)
    for key in keys:
        if key in ("version", "updated_at") or key in ignored:
            continue
        if old.get(key, None) != new.get(key, None):
            return True
    return False


store = Store()
