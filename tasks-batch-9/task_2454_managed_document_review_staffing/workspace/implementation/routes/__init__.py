from routes import (
    agreements,
    assignments,
    batches,
    clients,
    clock,
    matters,
    privilege,
    protocols,
    qc,
    reviewers,
    screenings,
    sessions,
)

BLUEPRINTS = (
    clock.bp,
    clients.bp,
    matters.bp,
    protocols.bp,
    reviewers.bp,
    screenings.bp,
    agreements.bp,
    sessions.bp,
    batches.bp,
    assignments.bp,
    qc.bp,
    privilege.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
