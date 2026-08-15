from routes import (
    applications,
    assignments,
    booths,
    hookups,
    load_slots,
    markets,
    permits,
    pos_devices,
    programming,
    renewal,
    settlements,
    toplevel,
    vendors,
    weather,
)

BLUEPRINTS = (
    markets.bp,
    vendors.bp,
    applications.bp,
    booths.bp,
    assignments.bp,
    permits.bp,
    hookups.bp,
    pos_devices.bp,
    settlements.bp,
    programming.bp,
    load_slots.bp,
    weather.bp,
    renewal.bp,
    toplevel.bp,
)


def register_blueprints(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
