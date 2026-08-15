"""In-memory data store. Empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone

# Entity stores (dict keyed by id)
acquisitions = {}
units = {}
lease_files = {}
rent_roll_entries = {}
concessions = {}
inspections = {}
findings = {}
utility_records = {}
tax_projections = {}
deposits = {}
employee_decisions = {}
service_contracts = {}
insurance_policies = {}
proration_statements = {}
proration_lines = {}
post_closing_adjustments = {}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (wall clock used only for created_at/updated_at metadata)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
