"""In-memory data store.

ALL state lives in module-level dicts keyed by id. Nothing is persisted to disk,
and NOTHING is seeded at import/boot — the store starts completely empty on every
fresh process. Tests construct every entity via the declared API surface.
"""

# One dict per entity type, keyed by the entity's UUID id.
salons = {}
stylists = {}
resources = {}
services = {}
clients = {}
membership_plans = {}
memberships = {}
packages = {}
package_purchases = {}
appointments = {}
product_skus = {}
checkouts = {}
product_sales = {}


# Map an entity-collection name to its dict (used by generic helpers / tests).
COLLECTIONS = {
    "salons": salons,
    "stylists": stylists,
    "resources": resources,
    "services": services,
    "clients": clients,
    "membership_plans": membership_plans,
    "memberships": memberships,
    "packages": packages,
    "package_purchases": package_purchases,
    "appointments": appointments,
    "product_skus": product_skus,
    "checkouts": checkouts,
    "product_sales": product_sales,
}
