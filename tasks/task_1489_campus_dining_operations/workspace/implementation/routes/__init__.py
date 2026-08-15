"""Route registration."""


def register_routes(app):
    from routes.halls import bp as halls_bp
    from routes.contracts import bp as contracts_bp
    from routes.cycles import bp as cycles_bp
    from routes.recipes import bp as recipes_bp
    from routes.periods import bp as periods_bp
    from routes.forecasts import bp as forecasts_bp
    from routes.accommodations import bp as accommodations_bp
    from routes.shifts import bp as shifts_bp
    from routes.waste import bp as waste_bp
    from routes.inspections import bp as inspections_bp
    from routes.departments import bp as departments_bp
    from routes.catering import bp as catering_bp
    from routes.statements import bp as statements_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(halls_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(periods_bp)
    app.register_blueprint(forecasts_bp)
    app.register_blueprint(accommodations_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(waste_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(departments_bp)
    app.register_blueprint(catering_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(clock_bp)
