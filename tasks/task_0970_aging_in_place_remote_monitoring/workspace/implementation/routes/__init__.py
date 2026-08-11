from . import core, fleet, installs, care, alerts, meds, wellness, clock


def register_routes(app):
    for mod in (core, fleet, installs, care, alerts, meds, wellness, clock):
        app.register_blueprint(mod.bp)
