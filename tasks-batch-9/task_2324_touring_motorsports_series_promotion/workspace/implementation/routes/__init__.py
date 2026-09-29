from routes import (
    bookings,
    catalog,
    entries,
    finance,
    safety,
    sponsorship,
    stops,
    ticketing,
)

MODULES = (catalog, bookings, stops, entries, ticketing, sponsorship, safety, finance)


def register(app):
    for module in MODULES:
        module.register(app)
