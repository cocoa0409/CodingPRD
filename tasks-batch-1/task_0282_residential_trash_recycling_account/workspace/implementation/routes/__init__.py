"""Route registration. Each module exposes a Flask Blueprint."""


def register_routes(app):
    from routes.plans_zones import bp as plans_zones_bp
    from routes.accounts import bp as accounts_bp
    from routes.carts import bp as carts_bp
    from routes.lifecycle import bp as lifecycle_bp
    from routes.invoices import bp as invoices_bp
    from routes.schedules import bp as schedules_bp
    from routes.extras import bp as extras_bp
    from routes.credits_notices import bp as credits_notices_bp
    from routes.clock_route import bp as clock_bp

    for bp in (
        plans_zones_bp,
        accounts_bp,
        carts_bp,
        lifecycle_bp,
        invoices_bp,
        schedules_bp,
        extras_bp,
        credits_notices_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)
