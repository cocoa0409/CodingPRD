def register_routes(app):
    from . import (capacity, clock, customers, damage, demo, equipment,
                   leases, pickup, reservations, tunes)
    for m in (customers, equipment, reservations, tunes, leases, demo,
              damage, pickup, capacity, clock):
        app.register_blueprint(m.bp)
