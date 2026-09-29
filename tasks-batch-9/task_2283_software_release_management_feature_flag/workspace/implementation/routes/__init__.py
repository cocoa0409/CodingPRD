"""Blueprint registry."""

from routes import changes, deployments, docs, flags, incidents, releases, system, trains

BLUEPRINTS = (
    system.bp,
    trains.bp,
    releases.bp,
    changes.bp,
    flags.bp,
    deployments.bp,
    incidents.bp,
    docs.bp,
)
