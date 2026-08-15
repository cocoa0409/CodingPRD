"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.departments = {}
        self.inventors = {}
        self.disclosures = {}
        self.entries = {}            # DisclosureInventor
        self.disputes = {}           # InventorshipDispute
        self.applications = {}       # PatentApplication
        self.costs = {}              # PatentCost
        self.startups = {}
        self.coi_plans = {}          # ConflictOfInterestPlan
        self.licenses = {}           # LicenseAgreement
        self.milestones = {}         # LicenseMilestone
        self.reports = {}            # RoyaltyReport
        self.distributions = {}      # RoyaltyDistribution
        self.compliance_reports = {}  # FederalComplianceReport
        self.writeoff_cleared = set()  # disclosure ids with a sticky clear


db = Store()


def now():
    return db.clock


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def create_record(coll, fields):
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = db.clock
    rec["updated_at"] = db.clock
    rec["version"] = 1
    rec["seq"] = next_seq()
    coll[rec["id"]] = rec
    return rec


def touch(rec):
    """Mutation: refresh updated_at and bump version."""
    rec["updated_at"] = db.clock
    rec["version"] += 1


def refresh_timestamp(rec):
    """Refresh updated_at without a version bump (pay-cascade rollup refresh)."""
    rec["updated_at"] = db.clock
