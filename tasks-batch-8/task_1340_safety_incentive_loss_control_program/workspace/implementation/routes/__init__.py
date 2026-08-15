"""Route registration."""


def register_routes(app):
    from routes.clock_routes import bp as clock_bp
    from routes.programs import bp as programs_bp
    from routes.forecasts import bp as forecasts_bp
    from routes.catalog import bp as catalog_bp
    from routes.employees import bp as employees_bp
    from routes.training import bp as training_bp
    from routes.hazards import bp as hazards_bp
    from routes.controls import bp as controls_bp
    from routes.observations import bp as observations_bp
    from routes.meetings import bp as meetings_bp
    from routes.actions import bp as actions_bp
    from routes.contractors import bp as contractors_bp
    from routes.claims import bp as claims_bp
    from routes.recommendations import bp as recommendations_bp
    from routes.awards import bp as awards_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(forecasts_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(hazards_bp)
    app.register_blueprint(controls_bp)
    app.register_blueprint(observations_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(contractors_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(awards_bp)
