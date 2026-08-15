"""In-memory data store and logical program clock.

The store starts EMPTY on every boot: no seeding anywhere. All entities are
created exclusively through the declared API surface.
"""
import itertools
import threading
from datetime import datetime, timezone

START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = START_CLOCK
        self.seq = itertools.count(1)
        self.cycles = {}            # ProgramCycle
        self.owners = {}            # PropertyOwner
        self.parcels = {}           # PropertyParcel
        self.segments = {}          # SidewalkSegment
        self.defects = {}           # Defect
        self.notices = {}           # RepairNotice
        self.applications = {}      # CostShareApplication
        self.batches = {}           # BidBatch
        self.work_items = {}        # BatchWorkItem
        self.contractors = {}       # Contractor
        self.bids = {}              # Bid
        self.forestry_reviews = {}  # ForestryReview
        self.liens = {}             # LienCase
        self.inspections = {}       # InspectionRecord


db = DB()


def base_entity(has_common=True):
    """Common fields for a fresh entity (version starts at 1)."""
    from util import new_id, now_iso
    e = {'id': new_id(), 'created_at': now_iso(), '_seq': next(db.seq)}
    if has_common:
        e['updated_at'] = e['created_at']
        e['version'] = 1
    return e


def touch(e):
    """Every mutation bumps version by exactly one and refreshes updated_at."""
    from util import now_iso
    if 'version' in e:
        e['version'] += 1
        e['updated_at'] = now_iso()
