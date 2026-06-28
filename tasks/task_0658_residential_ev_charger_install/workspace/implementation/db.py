"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot — no seeding, no preload. Every entity is
created by the test suite via the declared API surface. start.sh re-invocation
launches a fresh process, which re-imports this module and wipes all state.
"""
import uuid

from clock import clock

# One dict per entity type, keyed by id (or sku for ChargerProduct).
homeowners = {}
properties = {}
electricians = {}
charger_products = {}          # keyed by sku
install_jobs = {}
site_assessments = {}
quotes = {}
permit_applications = {}
interconnection_requests = {}
dispatch_assignments = {}
incentive_claims = {}
panel_upgrade_referrals = {}
warranty_tickets = {}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    return clock.iso()


def touch(entity):
    """Refresh updated_at and increment version on a mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity
