"""Blueprint registry."""

from routes import (clock, counselors, courses, enrollments, leads, partnerships,
                   programs, statements, teachout)

BLUEPRINTS = (
    partnerships.bp,
    programs.bp,
    courses.bp,
    counselors.bp,
    leads.bp,
    enrollments.bp,
    statements.bp,
    teachout.bp,
    clock.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
