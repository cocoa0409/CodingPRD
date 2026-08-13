"""Route registration."""
from routes import (agreements, clock, clusters, developers, milestones,
                    projects, studies, transparency)

_MODULES = (developers, clusters, projects, milestones, studies, agreements,
            transparency, clock)


def register_routes(app):
    for module in _MODULES:
        app.register_blueprint(module.bp)
