from routes import aar, episodes, incidents, sites, stays, supplies, transport, workforce

ALL_BLUEPRINTS = (
    episodes.bp,
    sites.bp,
    workforce.bp,
    stays.bp,
    transport.bp,
    supplies.bp,
    incidents.bp,
    aar.bp,
)


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp, url_prefix="/api")
