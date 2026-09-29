"""Blueprint registry: every collection is rooted at "/" (flat topology)."""
from routes import (assessments, households, inspections, misc, money, parties,
                    programs, projects)

BLUEPRINTS = (
    programs.bp,
    households.bp,
    parties.bp,
    assessments.bp,
    projects.bp,
    money.bp,
    inspections.bp,
    misc.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
