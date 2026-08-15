"""In-memory data store + logical clock.

The store starts empty on every boot — no seeding anywhere. Resource
timestamps (created_at / updated_at) and all time-sensitive judgments read
the server-side logical clock (PRD §2.5), whose startup default is exactly
2026-08-01T00:00:00Z.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

_CLOCK_START_RAW = "2026-08-01T00:00:00Z"
_clock_raw: str = _CLOCK_START_RAW
_clock_dt: datetime = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock_raw() -> str:
    return _clock_raw


def get_now() -> datetime:
    return _clock_dt


def set_clock(raw: str, dt: datetime) -> None:
    global _clock_raw, _clock_dt
    _clock_raw = raw
    _clock_dt = dt


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return format_ts(_clock_dt)


# ---------------------------------------------------------------------------
# Identity / stamping helpers
# ---------------------------------------------------------------------------

_seq = itertools.count(1)


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    return next(_seq)


def make_common_fields() -> dict:
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Stores — empty at boot, populated exclusively through the API
# ---------------------------------------------------------------------------

zones = {}            # id -> StorageZone
collections = {}      # id -> Collection
accessions = {}       # id -> Accession
deeds = {}            # id -> DeedOfGift
items = {}            # id -> Item
assessments = {}      # id -> ConservationAssessment
finding_aids = {}     # id -> FindingAid
projects = {}         # id -> VolunteerProject
tickets = {}          # id -> DigitizationTicket
researchers = {}      # id -> Researcher
requests = {}         # id -> ResearchRequest
appointments = {}     # id -> ReadingRoomAppointment
orders = {}           # id -> ReproductionOrder
proposals = {}        # id -> DeaccessionProposal
oral_histories = {}   # id -> OralHistoryRecording

# 1-based count of accessions created per logical calendar year (accession_number)
accession_year_counters = {}
