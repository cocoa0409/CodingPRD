"""In-memory data store.

Every collection is a plain dict keyed by the entity's server-minted UUID.
The store starts COMPLETELY EMPTY on every process boot — nothing is seeded,
preloaded, or hardcoded. Tests build all preconditions through the declared
API surface. Because start.sh re-launches a fresh process before every test,
module-load of this file wipes every byte of state.
"""

import uuid

from clock import now_iso8601

# ---- Catalog / configuration -----------------------------------------------
channel_packages = {}
premium_channels = {}
equipment_models = {}
promotion_offers = {}
regional_sports_fee_rules = {}
technicians = {}

# ---- Aggregate root and children -------------------------------------------
accounts = {}
subscriptions = {}
add_on_subscriptions = {}
equipment_leases = {}
service_visits = {}
promotion_applications = {}
billing_statements = {}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def stamp_new():
    """Return (created_at, updated_at, version) for a freshly created resource."""
    ts = now_iso8601()
    return ts, ts, 1


def touch(resource):
    """Refresh updated_at and bump version by exactly 1 on a mutation."""
    resource["updated_at"] = now_iso8601()
    resource["version"] = resource.get("version", 1) + 1
