"""Route registration."""
from routes import disposition, funding, maintenance, ops, properties


def register_routes(app):
    properties.register(app)
    funding.register(app)
    maintenance.register(app)
    disposition.register(app)
    ops.register(app)
