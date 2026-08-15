"""Route registration."""


def register_routes(app):
    from routes.clock_routes import bp as clock_bp
    from routes.machines import bp as machines_bp
    from routes.surveys import bp as surveys_bp
    from routes.procedures import bp as procedures_bp
    from routes.employees import bp as employees_bp
    from routes.training import bp as training_bp
    from routes.sessions import bp as sessions_bp
    from routes.locks import bp as locks_bp
    from routes.audits import bp as audits_bp
    from routes.incidents import bp as incidents_bp
    from routes.permits import bp as permits_bp
    from routes.exceptions import bp as exceptions_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(machines_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(procedures_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(locks_bp)
    app.register_blueprint(audits_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(exceptions_bp)
