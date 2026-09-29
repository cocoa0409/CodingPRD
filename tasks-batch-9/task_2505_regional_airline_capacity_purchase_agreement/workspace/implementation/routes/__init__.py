"""Blueprint registration.  Every collection is mounted under the flat /cpa root."""

from routes.common import API_PREFIX

MODULES = (
    "clock",
    "agreements",
    "negotiations",
    "crew_bases",
    "aircraft",
    "pilots",
    "schedule_cycles",
    "flight_legs",
    "cancellation_claims",
    "passthrough",
    "scorecards",
    "invoices",
    "brand_audits",
)


def register(app):
    for name in MODULES:
        module = __import__("routes." + name, fromlist=["bp"])
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)
