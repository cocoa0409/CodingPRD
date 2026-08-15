"""Route registration."""


def register_routes(app):
    from routes import (
        apprentices,
        assignments,
        boats,
        clock,
        distribution,
        incidents,
        invoices,
        orders,
        pilots,
        tariffs,
    )

    for module in (
        pilots,
        orders,
        assignments,
        boats,
        tariffs,
        invoices,
        incidents,
        apprentices,
        distribution,
        clock,
    ):
        app.register_blueprint(module.bp)
