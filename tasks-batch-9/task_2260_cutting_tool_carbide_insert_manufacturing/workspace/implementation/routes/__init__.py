"""Blueprint registry: every route module of the /tooling surface."""

from routes import (
    batches,
    clock,
    coating_runs,
    customers,
    dossiers,
    geometries,
    grades,
    grinding_runs,
    orders,
    products,
    recipes,
    recondition,
    trials,
    wheels,
)

BLUEPRINTS = (
    clock.bp,
    grades.bp,
    batches.bp,
    geometries.bp,
    recipes.bp,
    coating_runs.bp,
    wheels.bp,
    grinding_runs.bp,
    products.bp,
    dossiers.bp,
    trials.bp,
    customers.bp,
    orders.bp,
    recondition.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
