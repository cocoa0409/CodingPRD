"""Blueprint registry.

``app.py`` imports :data:`BLUEPRINTS` and registers each entry in order.
"""

from routes import (
    certifications,
    clock_control,
    compounds,
    customers,
    lots,
    orders,
    procurement,
    products,
    reels,
    shipments,
)

BLUEPRINTS = (
    clock_control.bp,
    procurement.bp,
    compounds.bp,
    certifications.bp,
    products.bp,
    customers.bp,
    orders.bp,
    lots.bp,
    reels.bp,
    shipments.bp,
)
