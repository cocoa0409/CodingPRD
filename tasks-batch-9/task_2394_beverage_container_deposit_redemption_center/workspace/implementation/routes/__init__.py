from routes import (accounts, bag_drops, batches, centers, clock_routes,
                    distributors, machines, periods, products, retailers,
                    visits)

BLUEPRINTS = (
    clock_routes.bp,
    distributors.bp,
    products.bp,
    centers.bp,
    machines.bp,
    accounts.bp,
    visits.bp,
    bag_drops.bp,
    batches.bp,
    retailers.bp,
    periods.bp,
)


def register(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
