"""Blueprint registry.  One module per bounded context."""

from routes import (athletes, clock, enrollments, funding, medical, programs,
                    sessions, staff, testing)

BLUEPRINTS = (
    clock.bp,
    athletes.bp,
    testing.bp,
    programs.bp,
    sessions.bp,
    enrollments.bp,
    staff.bp,
    funding.bp,
    medical.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
