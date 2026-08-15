"""In-memory data store. Empty on every boot; no persistence, no seeding."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def iso_now_wall():
    """Wall-clock timestamp for meta.api_request_timestamp (3 fractional digits, UTC)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_from_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.clinics = {}
        self.veterinarians = {}
        self.producers = {}
        self.animal_groups = {}
        self.drugs = {}
        self.vcp_verifications = {}
        self.vfd_authorizations = {}
        self.feed_mills = {}
        self.feed_orders = {}
        self.feed_shipments = {}
        self.withdrawal_plans = {}
        self.distributor_acknowledgments = {}
        self.residue_cases = {}
        self.audit_bundles = {}


store = Store()
