"""Route registration."""


def register_routes(app):
    from routes.admin import bp as admin_bp
    from routes.sites import bp as sites_bp
    from routes.staff import bp as staff_bp
    from routes.carriers import bp as carriers_bp
    from routes.atms import bp as atms_bp
    from routes.seasonal import bp as seasonal_bp
    from routes.fed_orders import bp as fed_orders_bp
    from routes.shipments import bp as shipments_bp
    from routes.fitness import bp as fitness_bp
    from routes.counterfeit import bp as counterfeit_bp
    from routes.ledger import bp as ledger_bp
    from routes.recons import bp as recons_bp
    from routes.forecasts import bp as forecasts_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(sites_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(carriers_bp)
    app.register_blueprint(atms_bp)
    app.register_blueprint(seasonal_bp)
    app.register_blueprint(fed_orders_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(fitness_bp)
    app.register_blueprint(counterfeit_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(recons_bp)
    app.register_blueprint(forecasts_bp)
