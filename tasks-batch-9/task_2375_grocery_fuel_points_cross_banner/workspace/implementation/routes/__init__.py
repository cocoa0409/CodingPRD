"""Route registration for all sixty endpoints."""
from routes import config_routes, dispute_routes, fuel_routes, people_routes, purchase_routes

BLUEPRINTS = (
    config_routes.bp,
    people_routes.bp,
    purchase_routes.bp,
    fuel_routes.bp,
    dispute_routes.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return app
