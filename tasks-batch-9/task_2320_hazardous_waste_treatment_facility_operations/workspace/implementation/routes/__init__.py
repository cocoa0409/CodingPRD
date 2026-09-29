"""Blueprint registration."""

from routes import (
    clock, facilities, instruments, generators, waste_profiles, storage_units,
    manifests, containers, treatment_batches, inspections, repair_orders, findings,
)

BLUEPRINTS = [
    clock.bp,
    facilities.bp,
    instruments.bp,
    generators.bp,
    waste_profiles.bp,
    storage_units.bp,
    manifests.bp,
    containers.bp,
    treatment_batches.bp,
    inspections.bp,
    repair_orders.bp,
    findings.bp,
]


def register_all(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
