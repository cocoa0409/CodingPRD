"""Route registration."""

from . import callbacks, fraud, investigations, money, ops, parties, recalls, sanctions, wires


def register_routes(app):
    for module in (parties, wires, callbacks, sanctions, fraud, recalls, money, investigations, ops):
        app.register_blueprint(module.bp)
