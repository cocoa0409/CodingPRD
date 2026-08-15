from . import (alerts, asrs, crime_log, csas, fires, geographies, incidents,
               referrals, reviews)


def register_blueprints(app):
    for mod in (geographies, csas, referrals, incidents, alerts, crime_log,
                asrs, fires, reviews):
        app.register_blueprint(mod.bp)
