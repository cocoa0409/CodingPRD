"""In-memory data store, logical clock and record helpers.

Storage is purely in-memory (plain dicts keyed by id).  Nothing is seeded at
startup: every record is created by clients through the declared endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone

# The logical clock reads exactly this instant before an operator repositions it.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

KINDS = [
    "Referral",
    "Participant",
    "Assessment",
    "MeetingSpace",
    "Cohort",
    "Enrollment",
    "Counselor",
    "CounselingReferral",
    "VolunteerCompanion",
    "CompanionMatch",
    "RemembranceEvent",
    "Invitation",
    "GrantAward",
    "FundingAllocation",
    "GrantReport",
    "AnniversaryOutreach",
]

# Entities that carry only id + created_at (no updated_at / version).
NO_VERSION_KINDS = {"Assessment"}


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_ts(value):
    """Parse an ISO 8601 instant (with or without trailing Z / offset)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.data = {kind: {} for kind in KINDS}
        self._seq = 0
        self.clock = CLOCK_EPOCH

    # ---- logical clock -------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_ts(self.clock)

    def today(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt

    # ---- records -------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def create(self, kind, fields):
        rec = {"id": str(uuid.uuid4())}
        rec.update(fields)
        rec["created_at"] = self.now_iso()
        if kind not in NO_VERSION_KINDS:
            rec["updated_at"] = self.now_iso()
            rec["version"] = 1
        rec["_kind"] = kind
        rec["_seq"] = self.next_seq()
        self.data[kind][rec["id"]] = rec
        return rec

    def get(self, kind, rid):
        if not isinstance(rid, str):
            return None
        return self.data[kind].get(rid)

    def all(self, kind):
        """All records of a kind in creation order."""
        return sorted(self.data[kind].values(), key=lambda r: r["_seq"])

    def find(self, kind, **filters):
        out = []
        for rec in self.all(kind):
            ok = True
            for key, value in filters.items():
                if rec.get(key) != value:
                    ok = False
                    break
            if ok:
                out.append(rec)
        return out

    def touch(self, rec):
        """Refresh updated_at and bump version, exactly as a direct write does."""
        if "version" in rec:
            rec["version"] = rec["version"] + 1
            rec["updated_at"] = self.now_iso()
        return rec


store = Store()


def public(rec):
    """Strip internal bookkeeping keys from a record."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]


def add_days(d, days):
    return d + timedelta(days=days)
