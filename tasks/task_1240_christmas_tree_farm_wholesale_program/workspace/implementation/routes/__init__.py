"""Route blueprint registry."""
from routes import (blocks, buyers, clock, consignments, crews, loads, lots,
                    orders, replants, seasons, tags)

ALL_BLUEPRINTS = [
    clock.bp,
    seasons.bp,
    blocks.bp,
    lots.bp,
    buyers.bp,
    orders.bp,
    crews.bp,
    loads.bp,
    consignments.bp,
    tags.bp,
    replants.bp,
]
