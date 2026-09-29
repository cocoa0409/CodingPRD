"""Blueprint registry. Every path is flat under the api_prefix "/"."""
from routes import assessments, core, delivery, facilities, leasing

BLUEPRINTS = (
    core.bp,
    assessments.bp,
    leasing.bp,
    delivery.bp,
    facilities.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return app
