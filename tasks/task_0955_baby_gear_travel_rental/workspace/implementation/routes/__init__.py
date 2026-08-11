from routes import (catalog, claims, cleaning, clockroute, customers,
                    extensions, lines, logistics, partners, plans,
                    recalls, reservations, units)


def all_blueprints():
    return [
        customers.bp, catalog.bp, units.bp, partners.bp, plans.bp,
        reservations.bp, extensions.bp, lines.bp, logistics.bp,
        recalls.bp, cleaning.bp, claims.bp, clockroute.bp,
    ]
