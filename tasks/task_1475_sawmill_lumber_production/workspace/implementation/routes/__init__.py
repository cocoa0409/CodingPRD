"""Route registration."""


def register_routes(app):
    from routes.log_loads import bp as log_loads_bp
    from routes.sawing_runs import bp as sawing_runs_bp
    from routes.kiln_charges import bp as kiln_charges_bp
    from routes.lumber_packages import bp as lumber_packages_bp
    from routes.sales import bp as sales_bp
    from routes.ops import bp as ops_bp

    app.register_blueprint(log_loads_bp)
    app.register_blueprint(sawing_runs_bp)
    app.register_blueprint(kiln_charges_bp)
    app.register_blueprint(lumber_packages_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(ops_bp)
