from . import (clock_routes, fy_routes, airline_routes, agreement_routes,
               rates_routes, capital_routes, settlement_routes, pfc_routes)


def register(app):
    for module in (clock_routes, fy_routes, airline_routes, agreement_routes,
                   rates_routes, capital_routes, settlement_routes, pfc_routes):
        app.register_blueprint(module.bp)
