"""Route blueprint registration. All endpoints are mounted under /completion."""
from routes import (clock, customers, aircraft, programs, schemes, assessments,
                    discovery, change_orders, hangar, booths, lots, weights,
                    inspections, delays, invoices)

ALL_BLUEPRINTS = (
    clock.bp,
    customers.bp,
    aircraft.bp,
    programs.bp,
    schemes.bp,
    assessments.bp,
    discovery.bp,
    change_orders.bp,
    hangar.bp,
    booths.bp,
    lots.bp,
    weights.bp,
    inspections.bp,
    delays.bp,
    invoices.bp,
)


def register_all(app, prefix="/completion"):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=prefix)
