from flask import Blueprint


def make_blueprint(name):
    return Blueprint(name, __name__)


from . import (clock, agencies, grants, inventory, intake, purchase_orders,  # noqa: E402,F401
               allocation_runs, events, issuances, households, shifts)  # noqa: E402,F401


def register_all(app):
    for mod in (clock, agencies, grants, inventory, intake, purchase_orders,
                allocation_runs, events, issuances, households, shifts):
        app.register_blueprint(mod.bp)
