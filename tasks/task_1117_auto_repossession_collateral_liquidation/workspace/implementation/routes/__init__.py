from . import (borrowers, loans, cases, agents, items, quotes, auctions,
               deficiency, complaints, clock_routes)

_MODULES = (borrowers, loans, cases, agents, items, quotes, auctions,
            deficiency, complaints, clock_routes)


def register_routes(app):
    for module in _MODULES:
        app.register_blueprint(module.bp)
