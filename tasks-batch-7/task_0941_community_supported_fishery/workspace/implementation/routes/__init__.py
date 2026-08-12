"""Route blueprints, all mounted under the /csf prefix."""
from routes import (catalog, deliveries, lots, members, seasons, skips,
                    subscriptions, vessels)

BLUEPRINTS = (
    seasons.bp,
    catalog.bp,
    members.bp,
    subscriptions.bp,
    vessels.bp,
    lots.bp,
    deliveries.bp,
    skips.bp,
)
