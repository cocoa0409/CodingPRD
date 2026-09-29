"""Route registration."""

from . import catalog, employers, enrollments, money, ops, schools


def register_routes(app):
    employers.register(app)
    schools.register(app)
    catalog.register(app)
    enrollments.register(app)
    money.register(app)
    ops.register(app)
