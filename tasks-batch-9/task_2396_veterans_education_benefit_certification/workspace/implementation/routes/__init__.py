"""Route registration."""

from routes import (
    academics,
    admin,
    certifications,
    changes,
    students,
    yellow_ribbon,
)

_MODULES = (admin, students, academics, yellow_ribbon, certifications, changes)


def register_routes(app):
    for module in _MODULES:
        module.register(app)
