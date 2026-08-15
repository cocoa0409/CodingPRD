"""Blueprint registration for all resource groups."""
from routes import (
    clock, members, dogs, memberships, guest_passes, areas, closures,
    visits, incidents, waste_stations, service_runs,
)

ALL_BLUEPRINTS = (
    clock.bp,
    members.bp,
    dogs.bp,
    memberships.bp,
    guest_passes.bp,
    areas.bp,
    closures.bp,
    visits.bp,
    incidents.bp,
    waste_stations.bp,
    service_runs.bp,
)


def register_routes(app):
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)
