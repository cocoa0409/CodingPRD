"""In-memory data store and logical clock.

The store starts empty on every boot; the harness restarts the server per
test, and every entity a test needs is constructed through the API surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.accounts = {}          # WaterUserAccount by id
        self.wells = {}             # Well by id
        self.reports = {}           # ExtractionReport by id
        self.transfers = {}         # TransferOrder by id
        self.readings = {}          # MonitoringReading by id
        self.snapshots = {}         # BasinConditionSnapshot by id
        self.assessments = {}       # PenaltyAssessment by id
        self.annual_reports = {}    # AnnualStateReport by id
        self.closed_years = set()   # water years closed via close-water-year
        self.seq = itertools.count(1)  # arrival-order counter (created_at tie-break)
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()


store = Store()


def new_id():
    return str(uuid.uuid4())


def stamp(entity):
    """Apply common system fields on creation (id assigned by caller)."""
    entity["created_at"] = store.clock
    entity["updated_at"] = store.clock
    entity["version"] = 1
    entity["_seq"] = next(store.seq)


def stamp_reading(entity):
    """MonitoringReading: append-only, id + created_at only."""
    entity["created_at"] = store.clock
    entity["_seq"] = next(store.seq)


def touch(entity):
    """Refresh updated_at on mutation."""
    entity["updated_at"] = store.clock
