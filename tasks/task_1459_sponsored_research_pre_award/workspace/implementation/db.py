"""In-memory data store. Fresh on every process boot — nothing is seeded."""

import uuid
from datetime import datetime, timezone

from utils import fmt_ts3

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.funding_opportunities = {}
        self.principal_investigators = {}
        self.proposals = {}
        self.budget_lines = {}
        self.budget_snapshots = {}
        self.fa_rate_agreements = {}
        self.cost_share_commitments = {}
        self.compliance_reviews = {}
        self.subrecipient_orgs = {}
        self.subrecipient_commitments = {}
        self.negotiation_offers = {}
        self.submission_packages = {}
        self.award_handoffs = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


store = Store()


def mint(fields, versioned=True):
    """Create a record dict with system-managed common fields."""
    store.seq += 1
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_ts3(store.clock),
        "_seq": store.seq,
    }
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version (only for versioned resources)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = fmt_ts3(store.clock)


def public(rec):
    """Strip internal bookkeeping keys from a record for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
