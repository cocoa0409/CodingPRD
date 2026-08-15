from flask import Blueprint


def register_routes(app):
    from routes import (catalog, clock_route, customers, evaluations, financing,
                        orders, titles, tradein, transport, units, warranty)

    for module in (catalog, clock_route, customers, evaluations, financing,
                   orders, titles, tradein, transport, units, warranty):
        app.register_blueprint(module.bp, url_prefix="/api")
