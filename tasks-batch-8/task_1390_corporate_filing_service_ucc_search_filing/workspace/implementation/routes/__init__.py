"""Route registration."""
from routes import admin, filings, parties, reports, requests, searches


def register_routes(app):
    app.register_blueprint(admin.bp)
    app.register_blueprint(parties.bp)
    app.register_blueprint(requests.bp)
    app.register_blueprint(filings.bp)
    app.register_blueprint(searches.bp)
    app.register_blueprint(reports.bp)
