def register_routes(app):
    from . import (
        terminals, products, customers, contracts, rights, schedules,
        notices, agreements, tickets, tax_rules, audit, clock_routes,
    )
    for m in (
        terminals, products, customers, contracts, rights, schedules,
        notices, agreements, tickets, tax_rules, audit, clock_routes,
    ):
        app.register_blueprint(m.bp)
